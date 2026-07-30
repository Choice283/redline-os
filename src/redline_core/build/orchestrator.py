"""Transport-neutral build command orchestration for Phase 13."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from redline_core.build.manifest import ManifestResolution, resolve_manifest_path
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


class BuildOrchestrationError(Exception):
    """Base class for build-orchestration failures."""


class ManifestIdentityMismatchError(BuildOrchestrationError):
    """Raised when a validated manifest does not match the parsed build target."""

    def __init__(self, *, target_episode_id: str, manifest_episode_id: str):
        super().__init__(
            "manifest episode.id does not match build target: "
            f"target episode_id={target_episode_id}, manifest episode_id={manifest_episode_id}"
        )
        self.target_episode_id = target_episode_id
        self.manifest_episode_id = manifest_episode_id


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
    ):
        self.config = config
        self.episode_manager = episode_manager
        self._target_parser = target_parser
        self._manifest_resolver = manifest_resolver
        self._manifest_loader = manifest_loader
        self._manifest_validator = manifest_validator

    def build(
        self,
        target: str,
        *,
        working_directory: Path | str,
        manifest_path: Path | str | None = None,
        allow_unsafe_retry: bool = False,
    ) -> BuildResult:
        """Run the approved build composition through episode assembly."""
        completed_stages: list[BuildStage] = []

        build_target = self._target_parser(target, self.config.naming)
        completed_stages.append(BuildStage.TARGET_PARSED)

        manifest_resolution = self._manifest_resolver(
            build_target,
            manifest_path=manifest_path,
            working_directory=working_directory,
        )
        completed_stages.append(BuildStage.MANIFEST_RESOLVED)

        manifest = self._manifest_loader(manifest_resolution.path)
        completed_stages.append(BuildStage.MANIFEST_LOADED)

        plan = self._manifest_validator(
            manifest,
            manifest_path=manifest_resolution.path,
            config=self.config,
        )
        completed_stages.append(BuildStage.MANIFEST_VALIDATED)

        if plan.episode_id != build_target.episode_id:
            raise ManifestIdentityMismatchError(
                target_episode_id=build_target.episode_id,
                manifest_episode_id=plan.episode_id,
            )
        completed_stages.append(BuildStage.IDENTITY_CONFIRMED)

        episode_created = False
        try:
            self.episode_manager.get_episode_status(build_target.episode_number)
        except EpisodeNotFoundError:
            completed_stages.append(BuildStage.EPISODE_RESOLVED)
            self.episode_manager.create_episode(build_target.episode_number)
            episode_created = True
            completed_stages.append(BuildStage.EPISODE_CREATED)
        else:
            completed_stages.append(BuildStage.EPISODE_RESOLVED)

        assembly_result = self.episode_manager.build_episode(
            plan.to_build_definition(),
            allow_unsafe_retry=allow_unsafe_retry,
        )
        completed_stages.append(BuildStage.EPISODE_ASSEMBLED)

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
        warnings=(),
        episode_created=episode_created,
    )
