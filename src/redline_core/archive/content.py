"""Archive Rev1 complete-content plan (Phase 15 Mission 15E.2).

`redline_core.archive.integrity.SourceInventory` (Mission 15C) describes
exactly one coherent subtree -- the episode workspace. Repository
reconciliation (Mission 15E's own architecture-review session) proved
that a truthful Rev1 archive must also preserve two things that do *not*
live inside that subtree: the original episode manifest (when it is not
already captured inside the workspace) and every manifest-referenced
ingest/assets media file, which Resolve imports by reference and never
copies into the workspace.

This module defines the small, explicit, domain-neutral (no DB, no
Resolve, no build orchestration) model that lets `ArchiveManager` describe
*all* required preservation content -- workspace subtree plus a short,
explicit list of individually-verified external files -- as one plan the
package builder (`redline_core.archive.package`) can consume without ever
walking an entire ingest or assets root.

Ownership boundary (unchanged from the accepted Mission 15E core, just
extended): `ArchiveManager` decides *what* belongs in the plan and
resolves every fingerprint before handing it to the package builder;
`package.py` only ever consumes an already-resolved plan -- copies,
verifies, reconciles, seals, publishes. Neither this module nor
`package.py` reads config, touches SQLite, or contacts Resolve.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from redline_core.archive.integrity import SourceInventory

_CONTENT_SET_SCHEMA_VERSION = 1


class ArchiveSourceKind(str, Enum):
    """Where an `ArchiveArtifact`'s bytes physically come from.

    WORKSPACE: the artifact is an ordinary file already inside the
    episode workspace subtree -- it is copied exactly once, by the
    workspace tree-copy, never a second time. An `ArchiveArtifact` of
    this kind exists in a plan only to attach an *additional*
    classification to that already-copied file (e.g. "this workspace
    file is also the render master") -- see `classifications` below.

    SOURCE_MEDIA: a manifest-referenced ingest/assets file living outside
    the workspace. Requires its own independent copy under
    `external/source_media/{ingest,assets}/...`.

    EPISODE_MANIFEST: the original episode manifest YAML, when it is not
    already captured inside the workspace (the legacy-episode fallback
    path -- see ArchiveManager). Requires its own independent copy under
    `external/episode_manifest/...`.
    """

    WORKSPACE = "workspace"
    SOURCE_MEDIA = "source_media"
    EPISODE_MANIFEST = "episode_manifest"


class ArchiveClassification(str, Enum):
    """Controlled vocabulary for `ArchiveArtifact.classifications`.

    Manifest-only (Phase 15 Mission 15E.2 item 28): never written to
    SQLite. Deliberately closed -- never generated from arbitrary caller/
    user input.
    """

    WORKSPACE = "workspace"
    RENDER_MASTER = "render_master"
    EPISODE_MANIFEST = "episode_manifest"
    MANIFEST_PROVENANCE = "manifest_provenance"
    SOURCE_MEDIA = "source_media"
    INGEST_MEDIA = "ingest_media"
    ASSET_MEDIA = "asset_media"


class ArchiveContentPlanError(ValueError):
    """A content plan could not be constructed: a structural invariant
    (unique archive_relative_path, unique absolute_source_path, a
    recognized source_kind) was violated. Raised by `build_content_plan()`
    defensively -- these are caller (ArchiveManager) bugs, not user-facing
    archive failures, so this intentionally does not subclass
    `ArchiveError`."""


@dataclass(frozen=True, slots=True)
class ArchiveArtifact:
    """One explicitly-planned, individually fingerprinted preservation
    artifact -- either an overlay onto an already-workspace-copied file
    (`source_kind=WORKSPACE`, no independent copy) or a genuinely external
    file requiring its own copy (`SOURCE_MEDIA`/`EPISODE_MANIFEST`).

    `absolute_source_path` is provenance/runtime-only: it is never part of
    `content_set_digest` (Question F/item 20 -- relocating an approved
    root must not change content identity as long as the logical
    `source_root` + `source_relative_path` pair is unchanged), but is
    still recorded in the sealed Archive Manifest for human/forensic
    provenance.

    `size_bytes`/`sha256` are the trusted, pre-package fingerprint --
    already computed (via `redline_core.fsutil.hash_stable_file()` for
    external artifacts, or copied verbatim from the matching
    `InventoryFile` for a workspace overlay) before this object is
    constructed. Nothing here re-reads bytes.

    No timestamps, no DB state -- see the module docstring's ownership
    boundary.
    """

    absolute_source_path: Path
    archive_relative_path: str
    size_bytes: int
    sha256: str
    classifications: tuple[str, ...]
    source_kind: ArchiveSourceKind
    source_root: str | None = None
    source_relative_path: str | None = None

    def __post_init__(self) -> None:
        if not self.archive_relative_path or self.archive_relative_path.startswith("/"):
            raise ArchiveContentPlanError(
                f"archive_relative_path must be a non-empty, relative POSIX path: {self.archive_relative_path!r}"
            )
        if not self.classifications:
            raise ArchiveContentPlanError(
                f"artifact {self.archive_relative_path!r} must carry at least one classification"
            )
        if self.source_kind == ArchiveSourceKind.SOURCE_MEDIA and self.source_root is None:
            raise ArchiveContentPlanError(
                f"artifact {self.archive_relative_path!r} has source_kind=SOURCE_MEDIA but no source_root"
            )
        if self.source_root is not None and self.source_relative_path is None:
            raise ArchiveContentPlanError(
                f"artifact {self.archive_relative_path!r} has source_root but no source_relative_path"
            )


@dataclass(frozen=True, slots=True)
class ArchiveContentPlan:
    """The complete, resolved set of content one Archive Rev1 package must
    preserve: the workspace subtree plus every explicit artifact.

    `artifacts` deliberately does *not* repeat every ordinary workspace
    file (`workspace_inventory.files` already fully describes those) --
    it holds only workspace *classification overlays* (a workspace file
    that also carries an extra role, e.g. render_master) and genuinely
    external artifacts. `package.py` derives the sealed manifest's full
    `artifacts[]` list by combining `workspace_inventory.files` (default
    classification `workspace`) with these overlays/additions -- see that
    module.
    """

    workspace_inventory: SourceInventory
    artifacts: tuple[ArchiveArtifact, ...]
    content_set_digest: str


# -- deterministic construction -------------------------------------------------


def _sort_key(archive_relative_path: str) -> str:
    return archive_relative_path.casefold()


def enum_value(value: str | Enum) -> str:
    """Return the plain string value of `value`, whether it is a bare
    string or a `(str, Enum)` member (`ArchiveSourceKind`/
    `ArchiveClassification`).

    Deliberately not `str(value)`: for a `(str, Enum)` mixin, `str()`
    returns `"ClassName.MEMBER"` (e.g. `"ArchiveSourceKind.WORKSPACE"`),
    not the plain value (`"workspace"`) -- true on every Python version
    this repository supports, not just pre-3.11. Every JSON-facing
    serialization of a source_kind/classification in this module and in
    `package.py` must go through this, never a bare `str()`.
    """
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_artifact_payload(artifact: ArchiveArtifact) -> dict:
    return {
        "archive_relative_path": artifact.archive_relative_path,
        "classifications": sorted({enum_value(c) for c in artifact.classifications}),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "source_kind": enum_value(artifact.source_kind),
        "source_relative_path": artifact.source_relative_path,
        "source_root": artifact.source_root,
    }


def compute_content_set_digest(
    workspace_source_set_digest: str, artifacts: Sequence[ArchiveArtifact]
) -> str:
    """Canonical SHA-256 identity of a complete archive content plan.

    Hashes a canonical logical representation -- `workspace_source_set_digest`
    (already an aggregate; the workspace subtree is never re-enumerated
    here) plus each artifact's `{archive_relative_path, classifications,
    sha256, size_bytes, source_kind, source_relative_path, source_root}`,
    sorted deterministically by `archive_relative_path` -- never raw
    bytes, and never `absolute_source_path` (see `ArchiveArtifact`'s
    docstring: relocating an approved root must not change content
    identity). Also never a machine/attempt-specific field (created_at,
    staging path, archive root, process id, a random UUID) -- see Mission
    15E.2 item 20.

    `artifacts` is expected to already satisfy `build_content_plan()`'s
    own invariants (unique archive_relative_path, unique
    absolute_source_path) -- this function does not re-validate that; it
    only canonicalizes and hashes.
    """
    sorted_artifacts = sorted(artifacts, key=lambda a: _sort_key(a.archive_relative_path))
    payload = {
        "artifacts": [_canonical_artifact_payload(a) for a in sorted_artifacts],
        "schema_version": _CONTENT_SET_SCHEMA_VERSION,
        "workspace": {"source_set_digest": workspace_source_set_digest},
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def build_content_plan(
    workspace_inventory: SourceInventory, artifacts: Sequence[ArchiveArtifact]
) -> ArchiveContentPlan:
    """Validate `artifacts` for internal consistency, sort them
    deterministically, compute `content_set_digest`, and return the
    immutable plan. The one recommended constructor for
    `ArchiveContentPlan` -- callers should not compute
    `content_set_digest` by hand.

    Raises `ArchiveContentPlanError` (a caller/ArchiveManager bug, not a
    user-facing archive failure) if:
      - two artifacts share the same `archive_relative_path` (a real
        collision -- would silently overwrite one artifact's destination
        with another's).
      - two artifacts share the same resolved `absolute_source_path` (per
        Mission 15E.2's physical-path dedup rule, the *same* physical
        source must appear as exactly one artifact carrying every
        applicable classification, never as two separate artifacts).
    """
    if type(workspace_inventory) is not SourceInventory:
        raise ArchiveContentPlanError("build_content_plan requires a verified SourceInventory instance.")

    ordered = tuple(sorted(artifacts, key=lambda a: _sort_key(a.archive_relative_path)))

    seen_relative_paths: dict[str, ArchiveArtifact] = {}
    seen_absolute_paths: dict[Path, ArchiveArtifact] = {}
    for artifact in ordered:
        key = _sort_key(artifact.archive_relative_path)
        if key in seen_relative_paths:
            raise ArchiveContentPlanError(
                f"duplicate archive_relative_path: {artifact.archive_relative_path!r} collides with "
                f"{seen_relative_paths[key].archive_relative_path!r}"
            )
        seen_relative_paths[key] = artifact

        resolved_source = artifact.absolute_source_path
        if resolved_source in seen_absolute_paths:
            other = seen_absolute_paths[resolved_source]
            raise ArchiveContentPlanError(
                f"duplicate physical source path {resolved_source} used by both "
                f"{other.archive_relative_path!r} and {artifact.archive_relative_path!r} -- "
                "merge classifications onto a single artifact instead of two"
            )
        seen_absolute_paths[resolved_source] = artifact

    digest = compute_content_set_digest(workspace_inventory.source_set_digest, ordered)
    return ArchiveContentPlan(
        workspace_inventory=workspace_inventory,
        artifacts=ordered,
        content_set_digest=digest,
    )
