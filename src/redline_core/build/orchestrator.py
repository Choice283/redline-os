"""Transport-neutral build command orchestration for Phase 13."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from redline_core.build.manifest import ManifestResolution, resolve_manifest_path
from redline_core.build.manifest_provenance import ManifestProvenanceResult, persist_manifest_provenance
from redline_core.build.preflight import (
    BuildOrchestrationError,
    BuildPreflight,
    ManifestIdentityMismatchError,
    PreparedBuildRequest,
)
from redline_core.build.target import BuildTarget, parse_build_target
from redline_core.config.schema import NamingConfig, RedlineConfig
from redline_core.db.models import EpisodeStatus
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.episode.manager import EpisodeManager
from redline_core.episode.models import EpisodeBuildResult
from redline_core.manifest import load_manifest, validate_manifest
from redline_core.manifest.models import EpisodeManifest, ValidatedEpisodePlan


class BuildStage(str, Enum):
    TARGET_PARSED = "target_parsed"
    MANIFEST_RESOLVED = "manifest_resolved"
    MANIFEST_LOADED = "manifest_loaded"
    MANIFEST_VALIDATED = "manifest_validated"
    IDENTITY_CONFIRMED = "identity_confirmed"
    EPISODE_RESOLVED = "episode_resolved"
    EPISODE_CREATED = "episode_created"
    EPISODE_ASSEMBLED = "episode_assembled"
    MANIFEST_PROVENANCE_PERSISTED = "manifest_provenance_persisted"


@dataclass(frozen=True, slots=True)
class BuildResult:
    target: BuildTarget
    manifest_path: Path
    completed_stages: tuple[BuildStage, ...]
    final_state: EpisodeStatus
    project_name: str
    timeline_name: str
    media_count: int
    markers_applied: int
    clips_placed: int
    video_item_count: int
    warnings: tuple[str, ...] = ()
    episode_created: bool = False


class BuildOrchestrator:
    """Coordinate the approved build stages without owning manager policy."""

    def __init__(
        self,
        *,
        config: RedlineConfig,
        episode_manager: EpisodeManager,
        target_parser: Callable[[str, NamingConfig], BuildTarget] = parse_build_target,
        manifest_resolver: Callable[..., ManifestResolution] = resolve_manifest_path,
        manifest_loader: Callable[[Path], EpisodeManifest] = load_manifest,
        manifest_validator: Callable[..., ValidatedEpisodePlan] = validate_manifest,
        manifest_provenance_persister: Callable[..., ManifestProvenanceResult] = persist_manifest_provenance,
    ):
        self.config = config
        self.episode_manager = episode_manager
        self._target_parser = target_parser
        self._manifest_resolver = manifest_resolver
        self._manifest_loader = manifest_loader
        self._manifest_validator = manifest_validator
        self._manifest_provenance_persister = manifest_provenance_persister

    def build(
        self,
        target: str,
        *,
        working_directory: Path | str,
        manifest_path: Path | str | None = None,
        allow_unsafe_retry: bool = False,
    ) -> BuildResult:
        """Run the approved build composition through episode assembly."""
        prepared_request = BuildPreflight(
            config=self.config,
            target_parser=self._target_parser,
            manifest_resolver=self._manifest_resolver,
            manifest_loader=self._manifest_loader,
            manifest_validator=self._manifest_validator,
        ).prepare(
            target,
            working_directory=working_directory,
            manifest_path=manifest_path,
        )
        return self.build_prepared(
            prepared_request,
            allow_unsafe_retry=allow_unsafe_retry,
        )

    def build_prepared(
        self,
        prepared_request: PreparedBuildRequest,
        *,
        allow_unsafe_retry: bool = False,
    ) -> BuildResult:
        """Run mutable build orchestration from already preflighted inputs."""
        completed_stages: list[BuildStage] = [
            BuildStage.TARGET_PARSED,
            BuildStage.MANIFEST_RESOLVED,
            BuildStage.MANIFEST_LOADED,
            BuildStage.MANIFEST_VALIDATED,
        ]
        build_target = prepared_request.target
        manifest_resolution = prepared_request.manifest_resolution
        plan = prepared_request.plan

        if plan.episode_id != build_target.episode_id:
            raise ManifestIdentityMismatchError(
                target_episode_id=build_target.episode_id,
                manifest_episode_id=plan.episode_id,
            )
        completed_stages.append(BuildStage.IDENTITY_CONFIRMED)

        episode_created = False
        try:
            episode = self.episode_manager.get_episode_status(build_target.episode_number)
        except EpisodeNotFoundError:
            completed_stages.append(BuildStage.EPISODE_RESOLVED)
            episode = self.episode_manager.create_episode(build_target.episode_number)
            episode_created = True
            completed_stages.append(BuildStage.EPISODE_CREATED)
        else:
            completed_stages.append(BuildStage.EPISODE_RESOLVED)

        assembly_result = self.episode_manager.build_episode(
            plan.to_build_definition(),
            allow_unsafe_retry=allow_unsafe_retry,
        )
        completed_stages.append(BuildStage.EPISODE_ASSEMBLED)

        # Phase 15 Mission 15E.2: persist a byte-for-byte canonical copy of
        # the manifest that was actually used, plus a deterministic
        # provenance record of its validated media identities, into the
        # episode's own workspace. A build that cannot safely persist this
        # required provenance must not report success -- see
        # persist_manifest_provenance()'s own docstring for exactly why
        # and what it guarantees. Reuses the `episode` reference captured
        # above (folder_path is set at episode-creation time and untouched
        # by build_episode()/assembly) rather than re-reading the DB.
        # Injected (self._manifest_provenance_persister), matching this
        # class's existing DI pattern for every other build-stage
        # function, so orchestration-sequencing tests do not need real
        # filesystem I/O.
        self._manifest_provenance_persister(
            original_manifest_path=manifest_resolution.path,
            plan=plan,
            config=self.config,
            episode_folder_path=episode.folder_path,
        )
        completed_stages.append(BuildStage.MANIFEST_PROVENANCE_PERSISTED)

        return _build_result(
            target=build_target,
            manifest_path=manifest_resolution.path,
            completed_stages=tuple(completed_stages),
            assembly_result=assembly_result,
            episode_created=episode_created,
        )


def _build_result(
    *,
    target: BuildTarget,
    manifest_path: Path,
    completed_stages: tuple[BuildStage, ...],
    assembly_result: EpisodeBuildResult,
    episode_created: bool,
) -> BuildResult:
    return BuildResult(
        target=target,
        manifest_path=manifest_path,
        completed_stages=completed_stages,
        final_state=EpisodeStatus.ASSEMBLED,
        project_name=assembly_result.project_name,
        timeline_name=assembly_result.timeline_name,
        media_count=len(assembly_result.media_ids),
        markers_applied=assembly_result.markers_applied,
        clips_placed=len(assembly_result.timeline_item_ids),
        video_item_count=assembly_result.video_item_count,
        warnings=(),
        episode_created=episode_created,
    )
