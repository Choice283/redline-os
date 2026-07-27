"""Archive Manager — moves a finished episode's working folder to cold storage.

This is the last stop in the episode lifecycle. It doesn't gate on render
status (an episode can technically be archived at any stage) — that's a
deliberate simplicity choice for now, not an oversight; see
docs/ARCHITECTURE.md §9 recommendation on keeping business rules minimal
until there's a real need for more.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from redline_core.archive.exceptions import ArchiveError, EpisodeAlreadyArchivedError
from redline_core.config.schema import RedlineConfig
from redline_core.db.database import Database
from redline_core.db.models import ArchiveRecord, EpisodeStatus
from redline_core.episode.exceptions import EpisodeNotFoundError

logger = logging.getLogger(__name__)


class ArchiveManager:
    def __init__(self, config: RedlineConfig, db: Database):
        self.config = config
        self.db = db

    def archive_episode(self, episode_id: str) -> ArchiveRecord:
        episode = self.db.get_episode_by_episode_id(episode_id)
        if episode is None:
            raise EpisodeNotFoundError(f"No episode with episode_id={episode_id}.")

        existing = self.db.get_archive_by_episode_id(episode_id)
        if existing is not None:
            raise EpisodeAlreadyArchivedError(
                f"Episode {episode_id} was already archived at {existing.archive_path}."
            )

        if not episode.folder_path:
            raise ArchiveError(f"Episode {episode_id} has no working folder to archive.")

        src = Path(episode.folder_path)
        if not src.is_dir():
            raise ArchiveError(f"Working folder {src} does not exist.")

        dest_root = Path(self.config.paths.archive_path)
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / episode_id
        if dest.exists():
            raise ArchiveError(f"Archive destination {dest} already exists.")

        shutil.move(str(src), str(dest))
        logger.info("Archived %s: %s -> %s", episode_id, src, dest)

        record = self.db.create_archive_record(episode_id, str(dest))
        self.db.update_episode_status(episode_id, EpisodeStatus.ARCHIVED)
        self.db.update_episode_paths(episode_id, folder_path=str(dest))
        return record

    def list_archives(self) -> list[ArchiveRecord]:
        return self.db.list_archives()
