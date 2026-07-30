"""Deterministic manifest path selection for Phase 13 builds."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from redline_core.build.target import BuildTarget

_SUPPORTED_MANIFEST_SUFFIXES = {".yaml", ".yml"}


class ManifestResolutionError(ValueError):
    """Raised when a build manifest path cannot be selected deterministically."""


@dataclass(frozen=True, slots=True)
class ManifestResolution:
    path: Path
    source: str


def resolve_manifest_path(
    target: BuildTarget,
    *,
    manifest_path: Path | str | None = None,
    working_directory: Path | str,
) -> ManifestResolution:
    """Select the one manifest path for a parsed build target."""
    if not isinstance(target, BuildTarget):
        raise ManifestResolutionError("target must be a BuildTarget.")

    working_dir = _resolve_working_directory(working_directory)
    if manifest_path is not None:
        return _resolve_explicit_manifest(manifest_path, working_directory=working_dir)

    return _resolve_default_manifest(target, working_directory=working_dir)


def _resolve_working_directory(working_directory: Path | str) -> Path:
    if not isinstance(working_directory, (str, Path)):
        raise ManifestResolutionError("working_directory must be a path string or Path.")

    path = Path(working_directory).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ManifestResolutionError(f"working_directory does not exist or cannot be resolved: {path}") from exc

    if not resolved.is_dir():
        raise ManifestResolutionError(f"working_directory must be a directory: {resolved}")
    return resolved


def _resolve_explicit_manifest(manifest_path: Path | str, *, working_directory: Path) -> ManifestResolution:
    if not isinstance(manifest_path, (str, Path)):
        raise ManifestResolutionError("manifest_path must be a path string, Path, or None.")

    selected = Path(manifest_path).expanduser()
    if selected.suffix not in _SUPPORTED_MANIFEST_SUFFIXES:
        raise ManifestResolutionError(f"manifest_path must use .yaml or .yml extension: {selected}")

    candidate = selected if selected.is_absolute() else working_directory / selected
    resolved = candidate.resolve(strict=False)

    if not resolved.exists():
        raise ManifestResolutionError(f"explicit manifest does not exist: {resolved}")
    if not resolved.is_file():
        raise ManifestResolutionError(f"explicit manifest is not a file: {resolved}")

    return ManifestResolution(path=resolved, source="explicit")


def _resolve_default_manifest(target: BuildTarget, *, working_directory: Path) -> ManifestResolution:
    yaml_candidate = (working_directory / f"{target.original_target}.yaml").resolve(strict=False)
    yml_candidate = (working_directory / f"{target.original_target}.yml").resolve(strict=False)

    if yaml_candidate.exists() and yaml_candidate.is_file():
        return ManifestResolution(path=yaml_candidate, source="default_yaml")
    if yml_candidate.exists() and yml_candidate.is_file():
        return ManifestResolution(path=yml_candidate, source="default_yml")

    raise ManifestResolutionError(
        "default manifest not found; expected one regular file at "
        f"{yaml_candidate} or {yml_candidate}"
    )
