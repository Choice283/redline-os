"""Read-only build preflight for canonical build commands."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from redline_core.build.manifest import ManifestResolution, resolve_manifest_path
from redline_core.build.target import BuildTarget, parse_build_target
from redline_core.config.schema import NamingConfig, RedlineConfig
from redline_core.manifest import load_manifest, validate_manifest
from redline_core.manifest.models import EpisodeManifest, ValidatedEpisodePlan


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
class PreparedBuildRequest:
    """Parsed and validated build inputs ready for mutable orchestration."""

    target: BuildTarget
    manifest_resolution: ManifestResolution
    manifest: EpisodeManifest
    plan: ValidatedEpisodePlan


class BuildPreflight:
    """Resolve and validate build inputs before mutable resources are composed."""

    def __init__(
        self,
        *,
        config: RedlineConfig,
        target_parser: Callable[[str, NamingConfig], BuildTarget] = parse_build_target,
        manifest_resolver: Callable[..., ManifestResolution] = resolve_manifest_path,
        manifest_loader: Callable[[Path], EpisodeManifest] = load_manifest,
        manifest_validator: Callable[..., ValidatedEpisodePlan] = validate_manifest,
    ):
        self.config = config
        self._target_parser = target_parser
        self._manifest_resolver = manifest_resolver
        self._manifest_loader = manifest_loader
        self._manifest_validator = manifest_validator

    def prepare(
        self,
        target: str,
        *,
        working_directory: Path | str,
        manifest_path: Path | str | None = None,
    ) -> PreparedBuildRequest:
        """Parse, select, load, and validate a build request without mutation."""
        build_target = self._target_parser(target, self.config.naming)
        manifest_resolution = self._manifest_resolver(
            build_target,
            manifest_path=manifest_path,
            working_directory=working_directory,
        )
        manifest = self._manifest_loader(manifest_resolution.path)
        plan = self._manifest_validator(
            manifest,
            manifest_path=manifest_resolution.path,
            config=self.config,
        )
        if plan.episode_id != build_target.episode_id:
            raise ManifestIdentityMismatchError(
                target_episode_id=build_target.episode_id,
                manifest_episode_id=plan.episode_id,
            )

        return PreparedBuildRequest(
            target=build_target,
            manifest_resolution=manifest_resolution,
            manifest=manifest,
            plan=plan,
        )
