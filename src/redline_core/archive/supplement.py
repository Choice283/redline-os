"""Archive Rev1 package supplements (Phase 15 Mission 15G).

`redline_core.archive.content.ArchiveContentPlan` describes exactly one
thing: the identity-bearing preservation payload (workspace subtree,
render master, original build manifest, manifest provenance, and every
manifest-referenced ingest/asset media file) whose canonical digest
(`content_set_digest`) is Archive Rev1's stable, environment-independent
preservation identity.

Mission 15G adds a second, deliberately separate kind of package content:
sealed *supplements* -- production evidence and generated restore
metadata -- that are useful to preserve inside the sealed package but
must never influence `content_set_digest` or `archive_id`. Making them
part of that identity would turn a supposedly content-bound identity into
one that also depends on the archival environment or moment (which
evidence happened to exist, what the effective configuration was that
day), which Mission 15E.2 explicitly established `content_set_digest`
must not do.

This module therefore defines the small, explicit, domain-neutral (no DB,
no Resolve, no config access) model that lets `ArchiveManager` describe a
complete package -- required preservation content plus its supplements --
as one plan the package builder (`redline_core.archive.package`) can
consume. `ArchiveManager` decides what supplements exist and resolves
every supplement's bytes/fingerprint before handing them to the package
builder; `package.py` only ever consumes an already-resolved plan.

Two supplement shapes exist:

`FileArchiveSupplement` -- an already-existing file elsewhere on disk
(e.g. a piece of production evidence) that requires its own independent
copy into the package, using the same Mission 15C/15D safe-file copy
model as every other external artifact. Nothing in this mission
constructs one (see Mission 15G's evidence-source-mapping finding in
`docs/CHANGELOG.md`) -- the shape exists so the package builder can
handle file-backed supplements generically, for a later mission to
populate once an authoritative evidence source exists.

`GeneratedArchiveSupplement` -- small, canonically-serialized JSON bytes
this module's own bytes were never read from a file; `ArchiveManager`
builds them in memory (see `redline_core.archive.metadata_snapshot`) and
the package builder writes them directly into staging, then independently
hashes the destination. This mission uses this shape for all four
metadata snapshots (episode, render job, config, software identity).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence, Union


class ArchiveSupplementKind(str, Enum):
    """Which of the two supplement shapes a supplement is."""

    FILE = "file"
    GENERATED = "generated"


class ArchiveSupplementClassification(str, Enum):
    """Controlled vocabulary for a supplement's `classifications`.

    Manifest-only, exactly like `archive.content.ArchiveClassification` --
    never written to SQLite, never generated from arbitrary caller input.
    `PRODUCTION_EVIDENCE` is defined for a future evidence-resolution
    mission to use; this mission's `ArchiveManager` never constructs a
    supplement carrying it (see the module docstring).
    """

    PRODUCTION_EVIDENCE = "production_evidence"
    GENERATED_METADATA = "generated_metadata"
    EPISODE_SNAPSHOT = "episode_snapshot"
    RENDER_JOB_SNAPSHOT = "render_job_snapshot"
    CONFIG_SNAPSHOT = "config_snapshot"
    SOFTWARE_IDENTITY = "software_identity"


class ArchiveSupplementPlanError(ValueError):
    """A package plan could not be constructed: a structural invariant
    (unique archive_relative_path across content + supplements, a
    recognized supplement kind) was violated. Raised by
    `build_package_plan()` defensively -- these are caller (ArchiveManager)
    bugs, not user-facing archive failures, so this intentionally does not
    subclass `ArchiveError`, matching `ArchiveContentPlanError`'s own
    convention."""


@dataclass(frozen=True, slots=True)
class FileArchiveSupplement:
    """One explicitly-planned, individually fingerprinted file-backed
    supplement requiring its own independent copy into the package.

    `absolute_source_path` is provenance/runtime-only, exactly like
    `ArchiveArtifact.absolute_source_path`: never part of any package
    identity, still recorded in the sealed Archive Manifest for human/
    forensic provenance.

    `size_bytes`/`sha256` are the trusted, pre-package fingerprint,
    already computed (via `redline_core.archive.integrity.hash_stable_file()`)
    before this object is constructed. Nothing here re-reads bytes.
    """

    absolute_source_path: Path
    archive_relative_path: str
    size_bytes: int
    sha256: str
    classifications: tuple[str, ...]
    source_kind: str

    def __post_init__(self) -> None:
        _validate_common_fields(self.archive_relative_path, self.classifications)


@dataclass(frozen=True, slots=True)
class GeneratedArchiveSupplement:
    """One small, canonically-serialized JSON supplement generated in
    memory (never read from an existing file). `sha256`/`size_bytes` are
    always derived from `canonical_bytes` by `build_generated_supplement()`
    -- never computed a second, independent way -- so a caller cannot
    construct one with bytes/fingerprint that disagree.
    """

    archive_relative_path: str
    canonical_bytes: bytes
    size_bytes: int
    sha256: str
    classifications: tuple[str, ...]
    source_kind: str

    def __post_init__(self) -> None:
        _validate_common_fields(self.archive_relative_path, self.classifications)
        if self.size_bytes != len(self.canonical_bytes):
            raise ArchiveSupplementPlanError(
                f"supplement {self.archive_relative_path!r} size_bytes does not match canonical_bytes length"
            )
        if self.sha256 != hashlib.sha256(self.canonical_bytes).hexdigest():
            raise ArchiveSupplementPlanError(
                f"supplement {self.archive_relative_path!r} sha256 does not match canonical_bytes"
            )


ArchiveSupplement = Union[FileArchiveSupplement, GeneratedArchiveSupplement]


def _validate_common_fields(archive_relative_path: str, classifications: tuple[str, ...]) -> None:
    if not archive_relative_path or archive_relative_path.startswith("/"):
        raise ArchiveSupplementPlanError(
            f"archive_relative_path must be a non-empty, relative POSIX path: {archive_relative_path!r}"
        )
    if not classifications:
        raise ArchiveSupplementPlanError(
            f"supplement {archive_relative_path!r} must carry at least one classification"
        )


def build_generated_supplement(
    *, archive_relative_path: str, canonical_bytes: bytes, classifications: tuple[str, ...], source_kind: str
) -> GeneratedArchiveSupplement:
    """The one recommended constructor for `GeneratedArchiveSupplement` --
    callers should not compute `sha256`/`size_bytes` by hand."""
    return GeneratedArchiveSupplement(
        archive_relative_path=archive_relative_path,
        canonical_bytes=canonical_bytes,
        size_bytes=len(canonical_bytes),
        sha256=hashlib.sha256(canonical_bytes).hexdigest(),
        classifications=classifications,
        source_kind=source_kind,
    )


def supplement_kind(supplement: ArchiveSupplement) -> ArchiveSupplementKind:
    if isinstance(supplement, GeneratedArchiveSupplement):
        return ArchiveSupplementKind.GENERATED
    return ArchiveSupplementKind.FILE


def _sort_key(archive_relative_path: str) -> str:
    return archive_relative_path.casefold()


@dataclass(frozen=True, slots=True)
class ArchivePackagePlan:
    """The complete package plan: identity-bearing preservation content
    plus sealed, non-identity-bearing supplements.

    `content.content_set_digest` remains the sole authority for
    `archive_id` (see `ArchiveManager._derive_archive_id()`) -- nothing in
    this module reads or derives from `supplements`/`supplement_directories`
    for identity purposes. Supplements are, however, not optional from a
    package-integrity perspective once sealed: the Archive Manifest
    records every supplement's own path/size/sha256/classification, so
    `archive verify` detects supplement tampering exactly like any other
    package content (see `package.py`).

    `supplement_directories` (Phase 15 Mission 15G.1) is a separate,
    directory-only companion to `supplements`: archive-relative paths
    (e.g. `"external/evidence/render/completion"`) that must exist in the
    sealed package even though they hold no file directly -- mirroring
    `ArchiveContentPlan.workspace_inventory.directories`' own first-class
    empty-directory preservation. `supplements` alone cannot represent an
    empty directory (a file-backed/generated supplement is always a
    file), so an episode evidence subtree containing an empty
    subdirectory needs this to preserve it. Never derived automatically
    from `supplements` -- the evidence resolver (or any future
    supplement source) supplies it explicitly, since only it walked the
    real directory structure.
    """

    content: "object"  # ArchiveContentPlan; typed loosely to avoid a circular import at module load time
    supplements: tuple[ArchiveSupplement, ...]
    supplement_directories: tuple[str, ...] = ()


def build_package_plan(
    content, supplements: Sequence[ArchiveSupplement], *, supplement_directories: Sequence[str] = ()
) -> ArchivePackagePlan:
    """Validate `supplements`/`supplement_directories` for internal
    consistency against each other and against `content`'s own
    artifact/workspace paths, sort them deterministically, and return the
    immutable plan.

    Raises `ArchiveSupplementPlanError` (a caller/ArchiveManager bug, not a
    user-facing archive failure) if two supplements share the same
    `archive_relative_path`, if a supplement's `archive_relative_path`
    collides with a path `content` already occupies (`workspace/...` or
    `external/...`) -- a real collision that would silently overwrite one
    payload entry with another -- or if a supplement directory path is
    empty/absolute or collides with a supplement *file* path.
    """
    from redline_core.archive.content import ArchiveContentPlan  # local import: avoid a module-load-time cycle

    if type(content) is not ArchiveContentPlan:
        raise ArchiveSupplementPlanError("build_package_plan requires a resolved ArchiveContentPlan instance.")

    ordered = tuple(sorted(supplements, key=lambda s: _sort_key(s.archive_relative_path)))
    ordered_directories = tuple(sorted(set(supplement_directories), key=_sort_key))

    content_paths: set[str] = {f"workspace/{f.relative_path}" for f in content.workspace_inventory.files}
    content_paths |= {a.archive_relative_path for a in content.artifacts}

    seen: dict[str, ArchiveSupplement] = {}
    for supplement in ordered:
        key = _sort_key(supplement.archive_relative_path)
        if key in seen:
            raise ArchiveSupplementPlanError(
                f"duplicate supplement archive_relative_path: {supplement.archive_relative_path!r} collides with "
                f"{seen[key].archive_relative_path!r}"
            )
        seen[key] = supplement
        if supplement.archive_relative_path in content_paths:
            raise ArchiveSupplementPlanError(
                f"supplement archive_relative_path collides with existing package content: "
                f"{supplement.archive_relative_path!r}"
            )

    file_paths = {s.archive_relative_path for s in ordered}
    for directory_path in ordered_directories:
        if not directory_path or directory_path.startswith("/"):
            raise ArchiveSupplementPlanError(
                f"supplement_directories entry must be a non-empty, relative POSIX path: {directory_path!r}"
            )
        if directory_path in file_paths or directory_path in content_paths:
            raise ArchiveSupplementPlanError(
                f"supplement directory path collides with an existing file path: {directory_path!r}"
            )

    return ArchivePackagePlan(content=content, supplements=ordered, supplement_directories=ordered_directories)
