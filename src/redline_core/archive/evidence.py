"""Archive Rev1 episode-scoped evidence authority (Phase 15 Mission 15G.1).

Mission 15G found no authoritative repository-defined rule for
associating an arbitrary on-disk file with a specific episode, and
therefore never resolved or archived any production evidence. Mission
15G.1 closes exactly that gap with one frozen, narrow authority:

    <configured evidence root>/<episode_id>/

is the *entire* evidence scope for `episode_id`. The directory boundary
is the authority -- a filename containing an episode ID elsewhere under
the evidence root is never evidence for that episode; a file with no
episode identity of its own, sitting inside `<evidence_root>/<episode_id>/`,
is. This module never scans the whole evidence root looking for a
filename match, and never inspects any location outside the exact
derived episode directory.

This module only resolves/plans -- it reads (for safety-proof hashing and
narrow JSON-identity inspection), never copies, writes, mutates a
database, or contacts Resolve. `ArchiveManager` is the only caller, and
`package.py` is the only thing that ever actually copies a resolved
`FileArchiveSupplement`'s bytes into a package.

Filesystem safety and hashing are entirely Mission 15C's own
(`redline_core.archive.integrity`) -- this module does not implement a
second, weaker tree walk. `integrity.build_source_inventory()` already
provides everything needed: root-safety validation (rejects a symlink/
junction/reparse-point root or one that is not a genuine directory),
recursive enumeration that rejects every unsafe object anywhere in the
subtree, case-insensitive identity-collision detection (Archive Rev1's
Windows-target policy), and already-verified per-file SHA-256/size.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from redline_core.archive import integrity
from redline_core.archive.exceptions import ArchiveEvidenceIdentityConflictError, ArchivePathError
from redline_core.archive.supplement import ArchiveSupplementClassification, FileArchiveSupplement

_EVIDENCE_DESTINATION_PREFIX = "external/evidence"
_EVIDENCE_CLASSIFICATION = ArchiveSupplementClassification.PRODUCTION_EVIDENCE.value
_EVIDENCE_SOURCE_KIND = "production_evidence"
_JSON_SUFFIX = ".json"
_JSON_EPISODE_ID_FIELD = "episode_id"


@dataclass(frozen=True, slots=True)
class EpisodeEvidencePlan:
    """The complete, resolved evidence scope for one episode: every
    file-backed supplement plus every directory-only path (an evidence
    subdirectory with no file of its own, still required to exist in the
    sealed package -- see `ArchivePackagePlan.supplement_directories`).
    Both are already `external/evidence/...`-prefixed, ready to hand to
    `redline_core.archive.supplement.build_package_plan()` alongside the
    generated metadata supplements. Empty (`supplements=()`,
    `directories=()`) is a valid, ordinary result -- see
    `resolve_episode_evidence()`'s zero-evidence semantics."""

    supplements: tuple[FileArchiveSupplement, ...]
    directories: tuple[str, ...]


def _validate_episode_id_path_component(episode_id: str) -> None:
    """Defense-in-depth guard, deliberately the same check
    `package._validate_identity_component()` already applies to
    `episode_id`/`archive_id` becoming literal path-name components --
    duplicated as a small module-local copy rather than a cross-module
    import of a private helper, matching this codebase's established
    convention for this exact kind of tiny safety check (see
    `archive.integrity`'s own `_is_windows()` docstring)."""
    if not isinstance(episode_id, str) or not episode_id:
        raise ArchivePathError("episode_id must be a non-empty string.")
    if "/" in episode_id or "\\" in episode_id or episode_id in (".", ".."):
        raise ArchivePathError(f"episode_id must not contain path separators: {episode_id!r}")


def _read_safe_json(path: Path) -> object:
    with integrity.open_stable_source(path) as (fh, size_bytes):
        data = fh.read()
    if len(data) != size_bytes:
        raise ArchivePathError(f"evidence file size changed while reading: {path}")
    return json.loads(data)


def _require_no_conflicting_episode_identity(path: Path, episode_id: str) -> None:
    """Narrow structured-identity check (Mission 15G.1): if a `.json`
    evidence file parses cleanly and carries a top-level `episode_id`
    field, it must agree with the episode this file's directory already
    proves ownership for -- an internally contradictory file (right
    directory, wrong embedded identity) fails closed rather than being
    silently preserved. Malformed/unparsable JSON, or JSON with no
    top-level `episode_id` field, is treated as opaque evidence and
    preserved as-is -- this function never rejects a file merely for
    being invalid JSON; the directory boundary already proved ownership,
    and no repository-defined schema requires every evidence JSON file to
    parse."""
    if path.suffix.lower() != _JSON_SUFFIX:
        return
    try:
        parsed = _read_safe_json(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(parsed, dict):
        return
    embedded_episode_id = parsed.get(_JSON_EPISODE_ID_FIELD)
    if embedded_episode_id is None:
        return
    if embedded_episode_id != episode_id:
        raise ArchiveEvidenceIdentityConflictError(
            f"evidence file {path} is located under episode {episode_id!r}'s authoritative evidence "
            f"directory but its own {_JSON_EPISODE_ID_FIELD!r} field says {embedded_episode_id!r}."
        )


def resolve_episode_evidence(*, evidence_root: str | Path, episode_id: str) -> EpisodeEvidencePlan:
    """Resolve the complete, authoritative evidence scope for
    `episode_id`: every safe regular file (and every otherwise-empty
    directory) under `<evidence_root>/<episode_id>/`, recursively,
    preserving nested structure exactly.

    Fails closed (never silently degrades to "zero evidence") when:
      - `evidence_root` itself does not exist, is not a directory, or is
        a symlink/junction/reparse point (`ArchivePathError`/
        `ArchiveUnsafeFilesystemObjectError`, via
        `integrity.validate_source_root()`) -- a misconfigured evidence
        root is a configuration/environment error, not "this episode has
        no evidence."
      - `episode_id` is not a safe single path-name component
        (`ArchivePathError`).
      - `<evidence_root>/<episode_id>` exists but is not a safe directory
        -- a file, a symlink, a junction, a reparse point, or any other
        special object (`ArchivePathError`/`ArchiveUnsafeFilesystemObjectError`,
        via `integrity.build_source_inventory()`'s own root validation).
      - anything inside the episode directory is itself unsafe (a
        symlink/junction/reparse point anywhere in the subtree, or a
        case-colliding relative-path identity) -- the same
        `integrity.build_source_inventory()` walk that already enforces
        this for an episode workspace.
      - a `.json` evidence file's own `episode_id` field disagrees with
        `episode_id` (`ArchiveEvidenceIdentityConflictError`).

    Returns an empty `EpisodeEvidencePlan` -- a valid, ordinary result,
    not an error -- when `<evidence_root>/<episode_id>` simply does not
    exist at all: evidence generation is not mandatory for every
    archive-eligible episode.

    Never copies anything, never writes to the package, never touches
    SQLite, never contacts Resolve.
    """
    _validate_episode_id_path_component(episode_id)
    root_resolved = integrity.validate_source_root(evidence_root)

    # `episode_id` is already proven above to be a single path-name
    # component with no separators and no `.`/`..` -- joining it onto
    # `root_resolved` can never itself construct an escaping path, so
    # this is a cheap structural invariant check, not a filesystem
    # operation. Deliberately not `.resolve()`-based: resolving *before*
    # `episode_dir_candidate`'s own symlink/junction safety has been
    # proven would follow a link straight through this check (defeating
    # it) instead of being caught, correctly, as an unsafe object by
    # `build_source_inventory()`'s own lstat-first `validate_source_root()`
    # below -- exactly the ordering Mission 15C's own root validator
    # documents as load-bearing.
    episode_dir_candidate = root_resolved / episode_id
    if episode_dir_candidate.parent != root_resolved:
        raise ArchivePathError(
            f"episode evidence directory escapes the configured evidence root: {episode_dir_candidate}"
        )

    try:
        os.lstat(episode_dir_candidate)
    except FileNotFoundError:
        return EpisodeEvidencePlan(supplements=(), directories=())
    except OSError as exc:
        raise ArchivePathError(f"cannot inspect episode evidence directory: {episode_dir_candidate}") from exc

    inventory = integrity.build_source_inventory(episode_dir_candidate)

    for inv_file in inventory.files:
        _require_no_conflicting_episode_identity(inv_file.absolute_source_path, episode_id)

    supplements = tuple(
        FileArchiveSupplement(
            absolute_source_path=inv_file.absolute_source_path,
            archive_relative_path=f"{_EVIDENCE_DESTINATION_PREFIX}/{inv_file.relative_path}",
            size_bytes=inv_file.size_bytes,
            sha256=inv_file.sha256,
            classifications=(_EVIDENCE_CLASSIFICATION,),
            source_kind=_EVIDENCE_SOURCE_KIND,
        )
        for inv_file in inventory.files
    )
    directories = tuple(f"{_EVIDENCE_DESTINATION_PREFIX}/{d.relative_path}" for d in inventory.directories)

    return EpisodeEvidencePlan(supplements=supplements, directories=directories)
