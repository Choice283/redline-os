"""Domain and path validation for Episode Manifest V1."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from redline_core.config.schema import RedlineConfig
from redline_core.manifest.exceptions import ManifestPathError, ManifestValidationError
from redline_core.manifest.models import EpisodeManifest, MarkerEntry, ValidatedEpisodePlan, ValidatedMarker

logger = logging.getLogger(__name__)


def validate_manifest(
    manifest: EpisodeManifest,
    *,
    manifest_path: str | Path,
    config: RedlineConfig,
) -> ValidatedEpisodePlan:
    """Validate manifest domain and media paths into a trusted runtime plan."""
    if not isinstance(manifest, EpisodeManifest):
        raise ManifestValidationError("manifest must be an EpisodeManifest", code="manifest.type_invalid")

    logger.debug(
        "Validating episode manifest: episode_id=%s media_count=%d marker_count=%d",
        manifest.episode.id,
        len(manifest.assembly.media),
        len(manifest.assembly.markers),
    )

    markers = _build_markers(manifest.assembly.markers)
    media_paths = _resolve_media_paths(manifest, manifest_path=manifest_path, config=config)
    plan = ValidatedEpisodePlan(
        episode_id=manifest.episode.id,
        media_paths=tuple(str(path) for path in media_paths),
        markers=tuple(markers),
        bin_name=manifest.assembly.bin_name,
    )
    logger.debug(
        "Validated episode manifest: episode_id=%s media_count=%d marker_count=%d",
        plan.episode_id,
        len(plan.media_paths),
        len(plan.markers),
    )
    return plan


def _build_markers(marker_entries: tuple[MarkerEntry, ...]) -> tuple[ValidatedMarker, ...]:
    markers: list[ValidatedMarker] = []
    for marker in marker_entries:
        markers.append(
            ValidatedMarker(
                frame=marker.frame,
                color=marker.color,
                name=marker.name,
                note=marker.note,
            )
        )
    return tuple(markers)


def _resolve_media_paths(
    manifest: EpisodeManifest,
    *,
    manifest_path: str | Path,
    config: RedlineConfig,
) -> tuple[Path, ...]:
    try:
        resolved_manifest_path = Path(manifest_path).expanduser().resolve(strict=False)
    except OSError as exc:
        raise ManifestPathError(
            f"unable to resolve manifest path {manifest_path}: {exc}",
            code="manifest.path_manifest_invalid",
        ) from exc
    manifest_dir = resolved_manifest_path.parent
    approved_roots = _approved_roots(config)
    failures: list[str] = []
    resolved_paths: list[Path] = []
    seen: dict[str, int] = {}

    for index, entry in enumerate(manifest.assembly.media):
        field_path = f"assembly.media[{index}].path"
        raw_path = entry.path
        try:
            candidate = Path(raw_path).expanduser()
            target = candidate if candidate.is_absolute() else manifest_dir / candidate
            resolved = target.resolve(strict=True)
        except OSError as exc:
            failures.append(f"{field_path}: path cannot be resolved as an existing file ({raw_path!r}): {exc}")
            continue

        if not _is_contained_in_any_root(resolved, approved_roots):
            failures.append(f"{field_path}: resolved path is outside approved media roots ({raw_path!r})")
            continue
        if not resolved.is_file():
            failures.append(f"{field_path}: resolved path is not a file ({raw_path!r})")
            continue

        duplicate_key = _duplicate_key(resolved)
        if duplicate_key in seen:
            failures.append(
                f"{field_path}: duplicate resolved media path also used at assembly.media[{seen[duplicate_key]}].path"
            )
            continue
        seen[duplicate_key] = index
        resolved_paths.append(resolved)

    if failures:
        raise ManifestPathError(
            "manifest media path validation failed: " + "; ".join(failures),
            code="manifest.path_invalid",
        )
    return tuple(resolved_paths)


def _approved_roots(config: RedlineConfig) -> tuple[Path, Path]:
    roots: list[Path] = []
    failures: list[str] = []
    configured = (
        ("config.paths.ingest_path", config.paths.ingest_path),
        ("config.paths.assets_path", config.paths.assets_path),
    )
    for label, value in configured:
        try:
            root = Path(value).expanduser().resolve(strict=True)
        except OSError as exc:
            failures.append(f"{label}: approved root cannot be resolved ({value!r}): {exc}")
            continue
        if not root.is_dir():
            failures.append(f"{label}: approved root is not a directory ({value!r})")
            continue
        roots.append(root)
    if failures:
        raise ManifestPathError(
            "manifest approved root validation failed: " + "; ".join(failures),
            code="manifest.root_invalid",
        )
    return (roots[0], roots[1])


def _is_contained_in_any_root(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_windows() -> bool:
    """Return whether the current OS is Windows.

    Kept as a small, module-local indirection (rather than reading
    ``os.name`` directly at each call site) so tests can exercise the
    Windows-specific branch below by patching this function alone --
    without mutating the shared, process-wide ``os`` module's ``name``
    attribute, which previously leaked into pytest's own internal
    ``pathlib`` usage later in the same test session.
    """
    return os.name == "nt"


def _duplicate_key(path: Path) -> str:
    normalized = os.path.normcase(str(path))
    if _is_windows():
        normalized = normalized.casefold()
    return normalized
