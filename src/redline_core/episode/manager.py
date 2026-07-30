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

import logging
import uuid
from pathlib import Path

from redline_core.config.schema import MarkerDefinition, RedlineConfig
from redline_core.db.database import Database
from redline_core.db.models import Episode, EpisodeStatus
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeBuildError, EpisodeNotFoundError
from redline_core.episode.models import EpisodeBuildDefinition, EpisodeBuildResult
from redline_core.logging.setup import get_episode_logger
from redline_core.media.manager import MediaManager
from redline_core.resolve.adapter import ResolveAdapter
from redline_core.timeline.builder import TimelineBuilder

logger = logging.getLogger(__name__)

STAGE_VALIDATION = "validation"
STAGE_EPISODE_LOOKUP = "episode_lookup"
STAGE_MEDIA_IMPORT = "media_import"
STAGE_MEDIA_RESULT_VALIDATION = "media_result_validation"
STAGE_TIMELINE_BUILD = "timeline_build"
STAGE_CLIP_PLACEMENT = "clip_placement"
STAGE_RESULT_VALIDATION = "result_validation"
STAGE_STATUS_UPDATE = "status_update"


class EpisodeManager:
    """Creates and tracks episodes. Depends on an already-connected ResolveAdapter."""

    def __init__(
        self,
        config: RedlineConfig,
        db: Database,
        resolve: ResolveAdapter,
        media_manager: MediaManager | None = None,
        timeline_builder: TimelineBuilder | None = None,
    ):
        self.config = config
        self.db = db
        self.resolve = resolve
        if media_manager is not None and getattr(media_manager, "resolve", resolve) is not resolve:
            raise ValueError("media_manager must use the same ResolveAdapter as EpisodeManager.")
        if timeline_builder is not None and getattr(timeline_builder, "resolve", resolve) is not resolve:
            raise ValueError("timeline_builder must use the same ResolveAdapter as EpisodeManager.")
        self.media_manager = media_manager or MediaManager(config, resolve)
        self.timeline_builder = timeline_builder or TimelineBuilder(config, resolve)

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

    def build_episode(
        self, definition: EpisodeBuildDefinition, *, allow_unsafe_retry: bool = False
    ) -> EpisodeBuildResult:
        """Assemble an already-created episode from explicit ordered media paths.

        V1 delegates media import to MediaManager and timeline creation,
        marker insertion, and clip placement to TimelineBuilder. It does not
        perform rollback or persist generated Resolve IDs.

        allow_unsafe_retry (ADR-0001, "Episode Assembly Retry Policy"): default
        False. Retry eligibility is enforced entirely inside this manager via
        an atomic, persisted assembly claim (see Database.claim_episode_for_assembly());
        no transport implements any part of this policy itself. Transports map
        their own vocabulary onto this parameter (the CLI's --force maps to
        allow_unsafe_retry=True) without redline_core ever knowing that
        vocabulary. Terminal statuses (ASSEMBLED, RENDER_QUEUED, RENDERED,
        ARCHIVED) are never retryable, with or without this flag.
        """
        definition = self._validate_build_definition(definition)
        episode, claim_token = self._claim_episode_for_build(
            definition.episode_id, allow_unsafe_retry=allow_unsafe_retry
        )
        project_name = episode.project_name
        timeline_name = self.timeline_builder.timeline_name_for_episode(episode.episode_id)
        completed_stages: list[str] = []
        imported_count = 0
        markers_applied = 0
        placed_count = 0

        logger.info(
            "Starting episode assembly: episode_id=%s, project_name=%s, media_path_count=%d, "
            "marker_count=%d, bin_name=%s",
            episode.episode_id,
            project_name,
            len(definition.media_paths),
            len(definition.markers),
            definition.bin_name,
        )

        try:
            logger.info("Episode assembly stage started: %s", STAGE_MEDIA_IMPORT)
            media_ids = self.media_manager.import_media(project_name, list(definition.media_paths), definition.bin_name)
            imported_count = len(media_ids)
            completed_stages.append(STAGE_MEDIA_IMPORT)
            logger.info("Episode assembly stage succeeded: %s imported_count=%d", STAGE_MEDIA_IMPORT, imported_count)
        except EpisodeBuildError:
            raise
        except Exception as exc:
            raise self._build_error(
                "Episode media import failed.",
                stage=STAGE_MEDIA_IMPORT,
                episode_id=episode.episode_id,
                claim_token=claim_token,
                completed_stages=completed_stages,
                project_name=project_name,
                timeline_name=timeline_name,
                imported_count=imported_count,
                markers_applied=markers_applied,
                placed_count=placed_count,
                cause=exc,
            )

        self._validate_media_ids(
            media_ids,
            expected_count=len(definition.media_paths),
            episode_id=episode.episode_id,
            claim_token=claim_token,
            project_name=project_name,
            timeline_name=timeline_name,
            completed_stages=completed_stages,
            imported_count=imported_count,
        )

        try:
            logger.info("Episode assembly stage started: %s", STAGE_TIMELINE_BUILD)
            timeline_result = self.timeline_builder.build_timeline_for_episode(
                project_name,
                episode.episode_id,
                markers=list(definition.markers),
            )
            markers_applied = timeline_result.markers_applied
            timeline_name = timeline_result.timeline_name
            completed_stages.append(STAGE_TIMELINE_BUILD)
            logger.info(
                "Episode assembly stage succeeded: %s timeline_name=%s markers_applied=%d",
                STAGE_TIMELINE_BUILD,
                timeline_name,
                markers_applied,
            )
        except Exception as exc:
            raise self._build_error(
                "Episode timeline build failed.",
                stage=STAGE_TIMELINE_BUILD,
                episode_id=episode.episode_id,
                claim_token=claim_token,
                completed_stages=completed_stages,
                project_name=project_name,
                timeline_name=timeline_name,
                imported_count=imported_count,
                markers_applied=markers_applied,
                placed_count=placed_count,
                cause=exc,
            )

        try:
            logger.info("Episode assembly stage started: %s", STAGE_CLIP_PLACEMENT)
            timeline_item_ids = self.timeline_builder.place_clips(project_name, timeline_name, list(media_ids))
            placed_count = len(timeline_item_ids)
            completed_stages.append(STAGE_CLIP_PLACEMENT)
            logger.info("Episode assembly stage succeeded: %s placed_count=%d", STAGE_CLIP_PLACEMENT, placed_count)
        except Exception as exc:
            raise self._build_error(
                "Episode clip placement failed.",
                stage=STAGE_CLIP_PLACEMENT,
                episode_id=episode.episode_id,
                claim_token=claim_token,
                completed_stages=completed_stages,
                project_name=project_name,
                timeline_name=timeline_name,
                imported_count=imported_count,
                markers_applied=markers_applied,
                placed_count=placed_count,
                cause=exc,
            )

        self._validate_timeline_item_ids(
            timeline_item_ids,
            expected_count=len(media_ids),
            episode_id=episode.episode_id,
            claim_token=claim_token,
            project_name=project_name,
            timeline_name=timeline_name,
            completed_stages=completed_stages,
            imported_count=imported_count,
            markers_applied=markers_applied,
            placed_count=placed_count,
        )

        result = EpisodeBuildResult(
            episode_id=episode.episode_id,
            project_name=project_name,
            timeline_id=timeline_result.timeline_id,
            timeline_name=timeline_name,
            media_paths=list(definition.media_paths),
            media_ids=list(media_ids),
            markers_applied=markers_applied,
            timeline_item_ids=list(timeline_item_ids),
        )
        try:
            self.db.release_assembly_claim(episode.episode_id, claim_token, EpisodeStatus.ASSEMBLED)
        except Exception as exc:
            logger.error(
                "Resolve assembly already completed but status persistence failed: episode_id=%s, "
                "project_name=%s, timeline_name=%s. Database status is stale; the assembly claim "
                "remains set (this is the persisted, cross-process 'uncertain outcome' signal ADR-0001 "
                "requires), so ordinary retries are blocked until an operator inspects Resolve and "
                "SQLite and retries with allow_unsafe_retry=True.",
                episode.episode_id,
                project_name,
                timeline_name,
            )
            raise self._build_error(
                "Episode assembly completed, but status update failed.",
                stage=STAGE_STATUS_UPDATE,
                episode_id=episode.episode_id,
                claim_token=claim_token,
                completed_stages=completed_stages,
                project_name=project_name,
                timeline_name=timeline_name,
                imported_count=imported_count,
                markers_applied=markers_applied,
                placed_count=placed_count,
                cause=exc,
            )
        logger.info(
            "Episode assembly complete: episode_id=%s, project_name=%s, timeline_name=%s, "
            "imported_count=%d, marker_count=%d, placed_count=%d",
            episode.episode_id,
            project_name,
            timeline_name,
            imported_count,
            markers_applied,
            placed_count,
        )
        return result

    def _validate_build_definition(self, definition: EpisodeBuildDefinition) -> EpisodeBuildDefinition:
        if not isinstance(definition, EpisodeBuildDefinition):
            raise EpisodeBuildError(
                "definition must be an EpisodeBuildDefinition.",
                stage=STAGE_VALIDATION,
                episode_id="<invalid>",
            )
        if not isinstance(definition.episode_id, str) or not definition.episode_id.strip():
            raise EpisodeBuildError(
                "episode_id must be a non-empty string.",
                stage=STAGE_VALIDATION,
                episode_id=str(definition.episode_id),
            )
        if not isinstance(definition.media_paths, list):
            raise EpisodeBuildError(
                "media_paths must be a list of strings.",
                stage=STAGE_VALIDATION,
                episode_id=definition.episode_id,
            )
        if not definition.media_paths:
            raise EpisodeBuildError(
                "media_paths must contain at least one path.",
                stage=STAGE_VALIDATION,
                episode_id=definition.episode_id,
            )
        normalized_paths: set[str] = set()
        for index, media_path in enumerate(definition.media_paths):
            if not isinstance(media_path, str) or not media_path.strip():
                raise EpisodeBuildError(
                    f"media path index {index} must be a non-empty string.",
                    stage=STAGE_VALIDATION,
                    episode_id=definition.episode_id,
                )
            normalized = str(Path(media_path).expanduser().resolve(strict=False)).casefold()
            if normalized in normalized_paths:
                raise EpisodeBuildError(
                    f"duplicate media path at index {index}: {media_path}",
                    stage=STAGE_VALIDATION,
                    episode_id=definition.episode_id,
                )
            normalized_paths.add(normalized)
        if not isinstance(definition.markers, list):
            raise EpisodeBuildError(
                "markers must be a list of MarkerDefinition objects.",
                stage=STAGE_VALIDATION,
                episode_id=definition.episode_id,
            )
        for index, marker in enumerate(definition.markers):
            if not isinstance(marker, MarkerDefinition):
                raise EpisodeBuildError(
                    f"marker index {index} must be a MarkerDefinition.",
                    stage=STAGE_VALIDATION,
                    episode_id=definition.episode_id,
                )
        if not isinstance(definition.bin_name, str) or not definition.bin_name.strip():
            raise EpisodeBuildError(
                "bin_name must be a non-empty string.",
                stage=STAGE_VALIDATION,
                episode_id=definition.episode_id,
            )
        return definition

    def _claim_episode_for_build(self, episode_id: str, *, allow_unsafe_retry: bool) -> tuple[Episode, str]:
        """Atomically claim episode_id for assembly (ADR-0001). Returns
        (episode, claim_token) on success.

        Eligibility and claim acquisition are one atomic repository
        operation (Database.claim_episode_for_assembly()'s own True/False
        return is the sole authority on whether the claim was acquired).
        The claim commits here, before build_episode() calls anything that
        touches Resolve, so no other process can ever observe this episode
        as unclaimed once assembly has begun.

        On failure, raises EpisodeBuildError (stage=episode_lookup). The
        SELECT below only builds a precise message for *why* the claim
        failed -- it does not re-decide eligibility.
        """
        claim_token = uuid.uuid4().hex
        claimed = self.db.claim_episode_for_assembly(
            episode_id, claim_token, allow_unsafe_retry=allow_unsafe_retry
        )
        if claimed:
            return self.db.get_episode_by_episode_id(episode_id), claim_token

        episode = self.db.get_episode_by_episode_id(episode_id)
        if episode is None:
            raise EpisodeBuildError(
                f"No existing episode with episode_id={episode_id}.",
                stage=STAGE_EPISODE_LOOKUP,
                episode_id=episode_id,
            )
        if episode.status == EpisodeStatus.ASSEMBLED:
            raise EpisodeBuildError(
                f"Episode {episode_id} is already assembled.",
                stage=STAGE_EPISODE_LOOKUP,
                episode_id=episode_id,
                project_name=episode.project_name,
            )
        if episode.status in (EpisodeStatus.RENDER_QUEUED, EpisodeStatus.RENDERED, EpisodeStatus.ARCHIVED):
            raise EpisodeBuildError(
                f"Episode {episode_id} has status '{episode.status.value}'; assembly is not permitted "
                "for downstream episodes.",
                stage=STAGE_EPISODE_LOOKUP,
                episode_id=episode_id,
                project_name=episode.project_name,
            )
        if episode.status == EpisodeStatus.FAILED and not allow_unsafe_retry:
            raise EpisodeBuildError(
                f"Episode {episode_id} is marked failed; retry requires allow_unsafe_retry=True.",
                stage=STAGE_EPISODE_LOOKUP,
                episode_id=episode_id,
                project_name=episode.project_name,
            )
        detail = "" if allow_unsafe_retry else " (retry requires allow_unsafe_retry=True)"
        raise EpisodeBuildError(
            f"Episode {episode_id} already has an active or unresolved assembly claim{detail}.",
            stage=STAGE_EPISODE_LOOKUP,
            episode_id=episode_id,
            project_name=episode.project_name,
        )

    def _validate_media_ids(
        self,
        media_ids: list[str],
        *,
        expected_count: int,
        episode_id: str,
        claim_token: str,
        project_name: str,
        timeline_name: str,
        completed_stages: list[str],
        imported_count: int,
    ) -> None:
        self._validate_ordered_ids(
            media_ids,
            expected_count=expected_count,
            label="media ID",
            stage=STAGE_MEDIA_RESULT_VALIDATION,
            episode_id=episode_id,
            claim_token=claim_token,
            project_name=project_name,
            timeline_name=timeline_name,
            completed_stages=completed_stages,
            imported_count=imported_count,
        )

    def _validate_timeline_item_ids(
        self,
        timeline_item_ids: list[str],
        *,
        expected_count: int,
        episode_id: str,
        claim_token: str,
        project_name: str,
        timeline_name: str,
        completed_stages: list[str],
        imported_count: int,
        markers_applied: int,
        placed_count: int,
    ) -> None:
        self._validate_ordered_ids(
            timeline_item_ids,
            expected_count=expected_count,
            label="TimelineItem ID",
            stage=STAGE_RESULT_VALIDATION,
            episode_id=episode_id,
            claim_token=claim_token,
            project_name=project_name,
            timeline_name=timeline_name,
            completed_stages=completed_stages,
            imported_count=imported_count,
            markers_applied=markers_applied,
            placed_count=placed_count,
        )

    def _validate_ordered_ids(
        self,
        ids: list[str],
        *,
        expected_count: int,
        label: str,
        stage: str,
        episode_id: str,
        claim_token: str,
        project_name: str,
        timeline_name: str,
        completed_stages: list[str],
        imported_count: int,
        markers_applied: int = 0,
        placed_count: int = 0,
    ) -> None:
        if not isinstance(ids, list):
            raise self._build_error(
                f"{label}s must be returned as a list.",
                stage=stage,
                episode_id=episode_id,
                claim_token=claim_token,
                completed_stages=completed_stages,
                project_name=project_name,
                timeline_name=timeline_name,
                imported_count=imported_count,
                markers_applied=markers_applied,
                placed_count=placed_count,
            )
        if len(ids) != expected_count:
            raise self._build_error(
                f"Expected {expected_count} {label}(s), got {len(ids)}.",
                stage=stage,
                episode_id=episode_id,
                claim_token=claim_token,
                completed_stages=completed_stages,
                project_name=project_name,
                timeline_name=timeline_name,
                imported_count=imported_count,
                markers_applied=markers_applied,
                placed_count=placed_count,
            )
        seen: set[str] = set()
        for index, value in enumerate(ids):
            if not isinstance(value, str) or not value.strip():
                raise self._build_error(
                    f"{label} index {index} must be a non-empty string.",
                    stage=stage,
                    episode_id=episode_id,
                    claim_token=claim_token,
                    completed_stages=completed_stages,
                    project_name=project_name,
                    timeline_name=timeline_name,
                    imported_count=imported_count,
                    markers_applied=markers_applied,
                    placed_count=placed_count,
                )
            if value in seen:
                raise self._build_error(
                    f"Duplicate {label}: {value}",
                    stage=stage,
                    episode_id=episode_id,
                    claim_token=claim_token,
                    completed_stages=completed_stages,
                    project_name=project_name,
                    timeline_name=timeline_name,
                    imported_count=imported_count,
                    markers_applied=markers_applied,
                    placed_count=placed_count,
                )
            seen.add(value)

    def _build_error(
        self,
        message: str,
        *,
        stage: str,
        episode_id: str,
        claim_token: str,
        completed_stages: list[str],
        project_name: str | None = None,
        timeline_name: str | None = None,
        imported_count: int = 0,
        markers_applied: int = 0,
        placed_count: int = 0,
        cause: Exception | None = None,
    ) -> EpisodeBuildError:
        error = EpisodeBuildError(
            message,
            stage=stage,
            episode_id=episode_id,
            completed_stages=tuple(completed_stages),
            project_name=project_name,
            timeline_name=timeline_name,
            imported_count=imported_count,
            markers_applied=markers_applied,
            placed_count=placed_count,
        )
        if stage not in (STAGE_VALIDATION, STAGE_EPISODE_LOOKUP, STAGE_STATUS_UPDATE):
            try:
                self.db.release_assembly_claim(episode_id, claim_token, EpisodeStatus.FAILED)
            except Exception:
                logger.warning(
                    "Unable to mark episode %s failed after assembly error; preserving original failure.",
                    episode_id,
                    exc_info=True,
                )
        logger.error(
            "Episode assembly failed: episode_id=%s, project_name=%s, timeline_name=%s, "
            "failed_stage=%s, completed_stages=%s, imported_count=%d, markers_applied=%d, "
            "placed_count=%d. Persistent partial Resolve state may remain.",
            episode_id,
            project_name,
            timeline_name,
            stage,
            tuple(completed_stages),
            imported_count,
            markers_applied,
            placed_count,
        )
        if cause is not None:
            raise error from cause
        return error

    def get_episode_status(self, episode_number: int) -> Episode:
        episode = self.db.get_episode_by_number(episode_number)
        if episode is None:
            raise EpisodeNotFoundError(f"No episode with episode_number={episode_number}.")
        return episode

    def list_episodes(self) -> list[Episode]:
        return self.db.list_episodes()
