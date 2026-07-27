"""Episode Manager — orchestrates the episode lifecycle.

This is the one module allowed to coordinate across Config, DB, and the
Resolve adapter for episode creation. It owns no state of its own: the DB is
the source of truth for pipeline state, the filesystem for the working
folder, and Resolve for the project itself. This module just sequences
calls to those three and keeps the DB row in sync.

Known limitation (see docs/ARCHITECTURE.md §8 "State desync risk"): if
folder creation or the Resolve call fails partway through create_episode(),
the DB row will already exist but with missing project_path/folder_path.
That's an accepted tradeoff for now — a reconciliation/status-check tool is
future work, not a Phase 2 concern.
"""
from __future__ import annotations

from pathlib import Path

from redline_core.config.schema import RedlineConfig
from redline_core.db.database import Database
from redline_core.db.models import Episode
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeNotFoundError
from redline_core.logging.setup import get_episode_logger
from redline_core.resolve.adapter import ResolveAdapter


class EpisodeManager:
    """Creates and tracks episodes. Depends on an already-connected ResolveAdapter."""

    def __init__(self, config: RedlineConfig, db: Database, resolve: ResolveAdapter):
        self.config = config
        self.db = db
        self.resolve = resolve

    def create_episode(self, episode_number: int) -> Episode:
        """Create a new episode: DB row, working folder, duplicated Resolve project.

        Raises EpisodeAlreadyExistsError if episode_number is already tracked.
        Any downstream failure (folder creation, Resolve duplication) propagates
        as-is (ProjectAlreadyExistsError, OSError, etc.) — the DB row created
        before that point is left in place rather than rolled back.
        """
        existing = self.db.get_episode_by_number(episode_number)
        if existing is not None:
            raise EpisodeAlreadyExistsError(
                f"Episode {episode_number} already exists (episode_id={existing.episode_id})."
            )

        episode_id = self.config.naming.episode_id_pattern.format(episode_number=episode_number)
        project_name = self.config.naming.project_name_pattern.format(
            episode_id=episode_id, episode_number=episode_number
        )

        logger = get_episode_logger(episode_id)
        logger.info("Creating episode: project_name=%s", project_name)

        # 1. DB row first, so the episode is trackable even if later steps fail.
        self.db.create_episode(episode_number, episode_id, project_name)

        # 2. On-disk working folder.
        folder_path = self._create_episode_folder(episode_id)
        self.db.update_episode_paths(episode_id, folder_path=str(folder_path))
        logger.info("Working folder created at %s", folder_path)

        # 3. Duplicate the master Resolve project template.
        project_handle = self.resolve.duplicate_project(
            project_name, self.config.paths.master_project_template
        )
        self.db.update_episode_paths(episode_id, project_path=project_handle.path)
        logger.info("Resolve project duplicated at %s", project_handle.path)

        return self.db.get_episode_by_number(episode_number)

    def _create_episode_folder(self, episode_id: str) -> Path:
        root = Path(self.config.folder_structure.root_path) / episode_id
        root.mkdir(parents=True, exist_ok=True)
        for subfolder in self.config.folder_structure.subfolders:
            (root / subfolder).mkdir(parents=True, exist_ok=True)
        return root

    def get_episode_status(self, episode_number: int) -> Episode:
        episode = self.db.get_episode_by_number(episode_number)
        if episode is None:
            raise EpisodeNotFoundError(f"No episode with episode_number={episode_number}.")
        return episode

    def list_episodes(self) -> list[Episode]:
        return self.db.list_episodes()
