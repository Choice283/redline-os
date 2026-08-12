"""Canonical episode-manifest provenance persistence (Phase 15 Mission
15E.2).

Repository investigation (Mission 15E's own architecture-review session)
proved the original episode build manifest is never persisted anywhere
today: `BuildOrchestrator.build_prepared()` knows its resolved path only
as a transient in-memory `BuildResult.manifest_path`, and it is discarded
at the `EpisodeBuildDefinition` boundary (that type carries only
`episode_id`/`media_paths`/`markers`/`bin_name`) -- there is no
`episodes.manifest_path` DB column, and `EpisodeManager` never references
one. A future Archive Rev1 archive cannot truthfully preserve "the
manifest used to build this episode" without a durable answer to "where
is it," so this module gives every future successful build one: a
byte-for-byte canonical copy plus a small deterministic provenance record,
persisted into the episode's own workspace.

Ownership: `BuildOrchestrator` is the narrowest point that knows all of
the resolved original manifest path, the validated `ValidatedEpisodePlan`
(and therefore its already-approved-root-contained media paths), and the
episode workspace path -- see that module. This module does not decide
*when* to run; it only performs the persistence operation and fails
closed if it cannot be done safely, so a build that cannot durably record
its own provenance must not report success.

Uses `redline_core.fsutil` (the domain-neutral safe-open/hash primitive)
rather than `redline_core.archive` -- importing the archive package from
here would create a backwards layering dependency (an earlier-lifecycle
build-time operation depending on a later, domain-branded preservation
module) with no counterpart anywhere else in this repository's module
graph. See `fsutil`'s own module docstring.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from redline_core import fsutil
from redline_core.build.preflight import BuildOrchestrationError
from redline_core.config.schema import RedlineConfig
from redline_core.manifest.models import ValidatedEpisodePlan

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_PROJECT_SUBFOLDER_NAME = "project"
_PROVENANCE_DIRNAME = "episode_manifest"
_PROVENANCE_FILENAME = "manifest_provenance.json"
_COPY_CHUNK_SIZE = 1024 * 1024

SOURCE_ROOT_INGEST = "ingest"
SOURCE_ROOT_ASSETS = "assets"
_APPROVED_SOURCE_ROOTS = (SOURCE_ROOT_INGEST, SOURCE_ROOT_ASSETS)


class ManifestProvenanceError(BuildOrchestrationError):
    """Canonical manifest provenance could not be safely persisted for a
    completed build: the workspace has no configured 'project' subfolder,
    a canonical copy already exists (this episode was already built
    once), the byte-for-byte copy failed its own integrity check, a
    validated media path could not be mapped to exactly one approved
    source root, or two validated media paths would collide once mapped to
    the same normalized `(source_root, source_relative_path)` identity. A
    build that raises this must not report success -- required provenance
    that cannot be safely persisted is a build failure, not a warning."""


@dataclass(frozen=True, slots=True)
class ManifestProvenanceResult:
    """What got persisted, and where -- consumed later at archive time
    (`ArchiveManager`) to discover the canonical manifest without
    guessing."""

    canonical_manifest_path: Path
    provenance_path: Path
    manifest_sha256: str
    manifest_size_bytes: int


def persist_manifest_provenance(
    *,
    original_manifest_path: Path | str,
    plan: ValidatedEpisodePlan,
    config: RedlineConfig,
    episode_folder_path: Path | str,
) -> ManifestProvenanceResult:
    """Copy `original_manifest_path` byte-for-byte into the episode
    workspace's `project/episode_manifest/` folder and write a
    deterministic `manifest_provenance.json` beside it, recording the
    manifest's own SHA-256 and every validated media path's
    (source_root, source_relative_path) identity -- never its absolute
    path, so relocating an approved root does not invalidate provenance
    already recorded, and never the manifest's own absolute path as a
    recovery *authority* (only as non-authoritative provenance) -- see
    `ManifestProvenanceResult`/the Archive Manifest Rev1 content-identity
    rules this feeds later.

    Raises `ManifestProvenanceError` (fails closed) rather than silently
    proceeding if: the workspace has no real `project` subfolder, a
    canonical manifest already exists for this episode (this function is
    for the *first* successful build only), the persisted copy's SHA-256/
    size do not match what was streamed from the source, or any validated
    media path cannot be mapped to exactly one approved root -- this last
    case should be structurally unreachable (`validate_manifest()`
    already enforces root containment before this function ever sees
    `plan`), and is kept as a defensive, fail-closed check, never a
    silent 'other' classification.
    """
    resolved_manifest_path = Path(original_manifest_path).resolve()
    project_dir = Path(episode_folder_path) / _PROJECT_SUBFOLDER_NAME
    if not project_dir.is_dir():
        raise ManifestProvenanceError(
            f"episode workspace has no configured {_PROJECT_SUBFOLDER_NAME!r} subfolder: {project_dir}"
        )

    provenance_dir = project_dir / _PROVENANCE_DIRNAME
    if provenance_dir.exists() and any(provenance_dir.iterdir()):
        raise ManifestProvenanceError(
            f"canonical manifest provenance already exists for this episode: {provenance_dir}"
        )

    # Resolved and validated before any filesystem mutation below: an
    # unmappable media path must fail closed without creating so much as
    # the provenance directory, not leave a half-formed canonical copy
    # with no provenance record behind it.
    media_entries = map_media_paths_to_approved_roots(plan.media_paths, config)

    provenance_dir.mkdir(parents=True, exist_ok=True)

    canonical_manifest_path = provenance_dir / resolved_manifest_path.name
    source_sha256, source_size = _copy_manifest_bytes(resolved_manifest_path, canonical_manifest_path)

    persisted_sha256, persisted_size = fsutil.hash_stable_file(canonical_manifest_path)
    if persisted_sha256 != source_sha256 or persisted_size != source_size:
        raise ManifestProvenanceError(
            f"canonical manifest copy failed integrity verification: {canonical_manifest_path} "
            f"(source sha256={source_sha256} size={source_size}, "
            f"persisted sha256={persisted_sha256} size={persisted_size})"
        )

    provenance = {
        "manifest_sha256": persisted_sha256,
        "media": media_entries,
        "original_manifest_filename": resolved_manifest_path.name,
        "original_manifest_path": str(resolved_manifest_path),
        "schema_version": _SCHEMA_VERSION,
    }
    canonical_bytes = json.dumps(provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    provenance_path = provenance_dir / _PROVENANCE_FILENAME
    try:
        provenance_path.write_bytes(canonical_bytes)
    except OSError as exc:
        raise ManifestProvenanceError(f"failed to write manifest provenance record: {provenance_path}") from exc

    written_sha256, written_size = fsutil.hash_stable_file(provenance_path)
    if written_size != len(canonical_bytes) or written_sha256 != hashlib.sha256(canonical_bytes).hexdigest():
        raise ManifestProvenanceError(f"manifest provenance record failed to persist correctly: {provenance_path}")

    logger.info(
        "Canonical manifest provenance persisted: episode_folder=%s canonical_manifest=%s manifest_sha256=%s "
        "media_count=%d",
        episode_folder_path,
        canonical_manifest_path,
        persisted_sha256,
        len(media_entries),
    )

    return ManifestProvenanceResult(
        canonical_manifest_path=canonical_manifest_path,
        provenance_path=provenance_path,
        manifest_sha256=persisted_sha256,
        manifest_size_bytes=persisted_size,
    )


def _copy_manifest_bytes(source: Path, destination: Path) -> tuple[str, int]:
    """Stream-copy `source` to `destination` through
    `fsutil.open_stable_source()` (never a plain, unverified
    `Path.open()`), computing the source's SHA-256 in the same pass --
    never a whole-file `read_bytes()`. Destination is opened
    exclusive-create ('xb') so this can never silently overwrite an
    existing file. Returns (source_sha256, source_size_bytes)."""
    digest = hashlib.sha256()
    total_bytes = 0
    try:
        with fsutil.open_stable_source(source) as (src_fh, _size_bytes):
            with destination.open("xb") as dst_fh:
                while True:
                    chunk = src_fh.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    total_bytes += len(chunk)
                    dst_fh.write(chunk)
    except OSError as exc:
        raise ManifestProvenanceError(f"failed to copy manifest: {source} -> {destination}") from exc
    except fsutil.SafeFileError as exc:
        raise ManifestProvenanceError(f"manifest source failed safety verification: {source}: {exc}") from exc

    return digest.hexdigest(), total_bytes


def _media_identity_key(source_root: str, source_relative_path: str) -> tuple[str, str]:
    """Case-insensitive, root-relative collision key for one media entry's
    `(source_root, source_relative_path)` identity -- the same
    unconditional-casefold policy `archive.integrity._normalized_identity_key()`
    applies to workspace relative paths, kept as its own small module-local
    copy here rather than an import (see the module docstring: this module
    does not depend on `redline_core.archive`). Applied regardless of which
    OS persists this record, since Archive Rev1 packages are built for a
    Windows production filesystem regardless of which OS builds them."""
    return (source_root, source_relative_path.casefold())


def map_media_paths_to_approved_roots(media_paths: tuple[str, ...], config: RedlineConfig) -> list[dict]:
    """Map every validated media path to its (source_root,
    source_relative_path) identity relative to the *currently configured*
    `ingest_path`/`assets_path` -- the recoverable identity archive-time
    resolution uses later, per Mission 15E.2's explicit design: never the
    absolute path as authority, so an approved root relocating (with the
    same root-relative file layout) does not invalidate already-recorded
    provenance.

    Raises `ManifestProvenanceError` (fails closed) if two entries would
    resolve to the same normalized `(source_root, source_relative_path)`
    identity. `media_paths` is already unique by resolved absolute path
    (`validate_manifest()`'s own duplicate-media-path check runs before
    this function ever sees `plan.media_paths`), but that upstream check is
    only case-insensitive on Windows -- two case-distinct paths that are
    genuinely different files on a case-sensitive filesystem could still
    collide once mapped into this function's always-casefolded identity, so
    this is kept as its own defensive, fail-closed check: a build that
    cannot durably record duplicate-free provenance must not report
    success."""
    ingest_root = Path(config.paths.ingest_path).expanduser().resolve()
    assets_root = Path(config.paths.assets_path).expanduser().resolve()

    entries: list[dict] = []
    seen_identities: dict[tuple[str, str], str] = {}
    for media_path in media_paths:
        resolved = Path(media_path).resolve()
        if resolved.is_relative_to(ingest_root):
            source_root = SOURCE_ROOT_INGEST
            source_relative_path = resolved.relative_to(ingest_root).as_posix()
        elif resolved.is_relative_to(assets_root):
            source_root = SOURCE_ROOT_ASSETS
            source_relative_path = resolved.relative_to(assets_root).as_posix()
        else:
            raise ManifestProvenanceError(
                f"validated media path does not belong to exactly one approved source root "
                f"({', '.join(_APPROVED_SOURCE_ROOTS)}): {resolved}"
            )

        identity = _media_identity_key(source_root, source_relative_path)
        existing = seen_identities.get(identity)
        if existing is not None:
            raise ManifestProvenanceError(
                "duplicate normalized provenance media identity: "
                f"source_root={source_root!r} source_relative_path={source_relative_path!r} "
                f"collides with {existing!r} once case-insensitively normalized (media path: {resolved})"
            )
        seen_identities[identity] = source_relative_path

        entries.append({"source_relative_path": source_relative_path, "source_root": source_root})

    entries.sort(key=lambda e: (e["source_root"], e["source_relative_path"].casefold()))
    return entries
