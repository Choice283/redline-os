"""Archive Rev1 package-construction layer (Phase 15 Mission 15D, extended
by Mission 15E.2 to the complete-content-plan contract).

Turns an already-resolved `redline_core.archive.content.ArchiveContentPlan`
into a sealed, hash-verified, atomically-published package directory. This
module builds package *mechanics* only -- it does not decide what belongs
in the plan, does not read config, does not read or write SQLite, does
not talk to Resolve, and does not choose archive IDs or render-job
identity. All of that is `ArchiveManager` orchestration.

Pipeline (see the module's public functions for the exact contract each
step enforces):

    resolved ArchiveContentPlan (Mission 15C SourceInventory + Mission
    15E.2 explicit ArchiveArtifact list)
            v
    build_staged_package(): allocate staging, recreate the workspace
    directory topology under payload/workspace/, copy every workspace
    file (through a safety-proven source descriptor), copy every
    external artifact under payload/external/..., re-verify source
    stability post-copy for both, verify destination content for both,
    independently verify complete staging-payload completeness,
    reconcile the complete content plan (workspace digest + every
    external artifact + the aggregate content_set_digest) against what
    was originally planned, write + seal Archive Manifest Rev1, write
    PACKAGE_COMPLETE
            v
    publish_package(): re-verify the sealed staging package one more
    time, then atomically rename staging -> final destination
            v
    PackageResult

``build_archive_package()`` is a thin convenience wrapper calling both in
sequence. The two-step split exists so a caller can inspect or
deliberately tamper with a sealed staging package between sealing and
publication -- several required failure tests exercise exactly that
boundary.

Final Rev1 payload layout (Mission 15E.2; extended by Mission 15G's
supplements -- see ``redline_core.archive.supplement`` -- below; there is
one canonical layout, not several):

    payload/
    ├── workspace/
    │   └── <episode workspace subtree, unchanged from Mission 15D>
    ├── external/
    │   ├── episode_manifest/
    │   │   └── <legacy original manifest filename>.yaml
    │   ├── source_media/
    │   │   ├── ingest/<relative-to-ingest-root>
    │   │   └── assets/<relative-to-assets-root>
    │   └── evidence/
    │       └── <supplement-defined path -- no supplement of this kind
    │            is produced by any caller in this mission; see
    │            supplement.py's module docstring>
    └── metadata/
        ├── episode.json
        ├── render_job.json
        ├── config_snapshot.json
        └── software.json

``external/`` may be entirely absent when a content plan has no external
artifacts (e.g. a low-level test exercising the workspace-only case via
``build_content_plan(inventory, ())``) -- the resulting package layout is
then just ``payload/workspace/...``, still under the one canonical
``workspace/`` prefix. ``metadata/`` (and any ``external/evidence/``)
likewise only exist when the caller's ``ArchivePackagePlan`` actually
carries supplements at those paths -- this module never invents one;
every supplement's own ``archive_relative_path`` decides where it lands
under ``payload/``, and ``metadata/``/``external/evidence/`` are simply
the paths Mission 15G's ``ArchiveManager`` and a future evidence-
resolution mission are expected to use, not paths this module enforces.

Every filesystem safety and hashing primitive here is Mission 15C's own
(``redline_core.archive.integrity``, itself now backed by the
domain-neutral ``redline_core.fsutil``) -- this module does not implement
a second, weaker tree walk, hashing routine, or safe-open routine for
either the workspace or the external-artifact case.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from redline_core.archive import integrity
from redline_core.archive.content import ArchiveContentPlan, ArchiveSourceKind, compute_content_set_digest, enum_value
from redline_core.archive.exceptions import (
    ArchiveCopyVerificationError,
    ArchiveDestinationCollisionError,
    ArchivePackageError,
    ArchivePackageVerificationError,
    ArchivePathError,
    ArchivePublicationError,
    ArchiveSourceChangedError,
    ArchiveSupplementCopyError,
)
from redline_core.archive.supplement import (
    ArchivePackagePlan,
    ArchiveSupplement,
    FileArchiveSupplement,
    GeneratedArchiveSupplement,
)

logger = logging.getLogger(__name__)

_COPY_CHUNK_SIZE = 1024 * 1024  # 1 MiB; matches integrity.py's/fsutil's streaming-hash chunk size.
_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_FILENAME = "archive_manifest.json"
_MANIFEST_SHA256_FILENAME = "archive_manifest.sha256"
_MARKER_FILENAME = "PACKAGE_COMPLETE"
_PAYLOAD_DIRNAME = "payload"
_WORKSPACE_DIRNAME = "workspace"
_STAGING_DIRNAME = ".staging"
_EPISODES_DIRNAME = "episodes"
_DEFAULT_CLASSIFICATION = "workspace"
_ARTIFACT_SOURCE_KINDS = frozenset(
    {enum_value(ArchiveSourceKind.WORKSPACE), enum_value(ArchiveSourceKind.SOURCE_MEDIA), enum_value(ArchiveSourceKind.EPISODE_MANIFEST)}
)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_PERMITTED_PACKAGE_ROOT_ENTRIES = frozenset({_MANIFEST_FILENAME, _MANIFEST_SHA256_FILENAME, _MARKER_FILENAME, _PAYLOAD_DIRNAME})

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


# -- models ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StagedPackage:
    """A fully copied, verified, and sealed package still at its staging
    location -- not yet published. Returned by ``build_staged_package()``
    and consumed by ``publish_package()``."""

    archive_id: str
    episode_id: str
    staging_path: Path
    payload_root: Path
    final_path: Path
    manifest_path: Path
    manifest_sha256_path: Path
    marker_path: Path
    manifest_sha256: str
    content_plan: ArchiveContentPlan
    package_plan: ArchivePackagePlan
    content_set_digest: str
    workspace_source_set_digest: str
    file_count: int
    directory_count: int
    total_bytes: int
    supplement_count: int


@dataclass(frozen=True, slots=True)
class PackageResult:
    """The result of a successfully published Archive Rev1 package.
    Deliberately carries no database or episode-status field -- filesystem
    package construction and DB registration are distinct boundaries."""

    archive_id: str
    episode_id: str
    final_path: Path
    manifest_path: Path
    manifest_sha256: str
    content_set_digest: str
    workspace_source_set_digest: str
    supplement_count: int
    file_count: int
    directory_count: int
    total_bytes: int


# -- identity / path safety ------------------------------------------------------


def _coerce_package_plan(plan: "ArchiveContentPlan | ArchivePackagePlan") -> ArchivePackagePlan:
    """Accept either a bare ``ArchiveContentPlan`` (every pre-Mission-15G
    caller, and every existing Mission 15D/15E.2 test) or a Mission 15G
    ``ArchivePackagePlan``. A bare content plan is treated as a package
    plan with zero supplements -- this keeps every existing call site
    working unchanged while `ArchiveManager` (the only caller that
    constructs supplements) passes a real ``ArchivePackagePlan``."""
    if isinstance(plan, ArchivePackagePlan):
        return plan
    if type(plan) is ArchiveContentPlan:
        return ArchivePackagePlan(content=plan, supplements=())
    raise ArchivePackageError(
        "build_staged_package/build_archive_package require an ArchiveContentPlan or ArchivePackagePlan instance."
    )


def _validate_identity_component(value: str, field_name: str) -> None:
    """Defense-in-depth guard on ``episode_id``/``archive_id``: both
    become literal path-name components, so a value containing a path
    separator or a bare ``.``/``..`` is rejected outright."""
    if not isinstance(value, str) or not value:
        raise ArchivePackageError(f"{field_name} must be a non-empty string.")
    if "/" in value or "\\" in value or value in (".", ".."):
        raise ArchivePackageError(f"{field_name} must not contain path separators: {value!r}")


def _safe_destination_path(root_resolved: Path, relative_path: str) -> Path:
    """Join ``relative_path`` under ``root_resolved`` and require the
    result to still resolve inside it.

    Defense in depth on top of the already-trusted source of
    ``relative_path`` (a Mission 15C ``InventoryFile.relative_path``, or
    an ``ArchiveArtifact.archive_relative_path`` this module itself
    computed) -- fails closed on any impossible/path-escape condition.
    """
    candidate = (root_resolved / relative_path).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise ArchivePathError(f"destination path escapes the staging payload root: {relative_path!r}")
    return candidate


# -- file copy --------------------------------------------------------------------


def _copy_file_chunked(source: Path, destination: Path) -> None:
    """Chunked stdlib copy through the safe-open source descriptor
    (``integrity.open_stable_source()``) -- never a plain, unverified
    ``Path.open()``. Destination is opened exclusive-create ('xb') so
    this can never silently overwrite an existing file."""
    try:
        with integrity.open_stable_source(source) as (src_fh, _source_size_bytes):
            with destination.open("xb") as dst_fh:
                shutil.copyfileobj(src_fh, dst_fh, length=_COPY_CHUNK_SIZE)
    except OSError as exc:
        raise ArchivePackageError(f"failed to copy file: {source} -> {destination}") from exc


def _copy_and_verify_workspace_files(plan: ArchiveContentPlan, workspace_root: Path) -> None:
    """Copy every workspace file, exactly Mission 15D's original
    per-file pipeline, now rooted under ``workspace_root`` instead of
    bare ``payload_root``."""
    for directory in plan.workspace_inventory.directories:
        dest_dir = _safe_destination_path(workspace_root, directory.relative_path)
        dest_dir.mkdir(parents=True, exist_ok=True)

    for inv_file in plan.workspace_inventory.files:
        dest_path = _safe_destination_path(workspace_root, inv_file.relative_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            raise ArchivePackageError(f"unexpected pre-existing staging artifact: {dest_path}")
        _copy_file_chunked(inv_file.absolute_source_path, dest_path)

        post_copy_sha256, post_copy_size = integrity.hash_stable_file(inv_file.absolute_source_path)
        if post_copy_sha256 != inv_file.sha256 or post_copy_size != inv_file.size_bytes:
            raise ArchiveSourceChangedError(
                f"source changed after inventory, detected during package copy: {inv_file.relative_path}"
            )

        dest_sha256, dest_size = integrity.hash_stable_file(dest_path)
        if dest_sha256 != inv_file.sha256 or dest_size != inv_file.size_bytes:
            raise ArchiveCopyVerificationError(
                f"copied artifact does not match verified source: {inv_file.relative_path}"
            )


def _copy_and_verify_external_artifacts(plan: ArchiveContentPlan, payload_root: Path) -> None:
    """Copy every non-workspace explicit artifact under its own planned
    ``archive_relative_path`` (already ``external/...``-prefixed).
    Workspace-kind artifacts (classification overlays onto an
    already-workspace-copied file) are skipped here entirely -- they
    have no independent physical copy; see ``content.ArchiveSourceKind``.
    """
    for artifact in plan.artifacts:
        if artifact.source_kind == ArchiveSourceKind.WORKSPACE:
            continue

        dest_path = _safe_destination_path(payload_root, artifact.archive_relative_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            raise ArchivePackageError(f"unexpected pre-existing staging artifact: {dest_path}")
        _copy_file_chunked(artifact.absolute_source_path, dest_path)

        post_copy_sha256, post_copy_size = integrity.hash_stable_file(artifact.absolute_source_path)
        if post_copy_sha256 != artifact.sha256 or post_copy_size != artifact.size_bytes:
            raise ArchiveSourceChangedError(
                f"external source changed after planning, detected during package copy: "
                f"{artifact.archive_relative_path}"
            )

        dest_sha256, dest_size = integrity.hash_stable_file(dest_path)
        if dest_sha256 != artifact.sha256 or dest_size != artifact.size_bytes:
            raise ArchiveCopyVerificationError(
                f"copied external artifact does not match verified source: {artifact.archive_relative_path}"
            )


# -- supplement staging (Phase 15 Mission 15G) -------------------------------------


def _copy_and_verify_file_supplements(supplements: Sequence[FileArchiveSupplement], payload_root: Path) -> None:
    """File-backed supplements are copied and verified exactly like an
    external artifact (``_copy_and_verify_external_artifacts()``) -- same
    safe-open source, same post-copy source re-hash, same destination
    verify -- because they are structurally the same operation: an
    already-existing file elsewhere on disk, copied into the package
    under its own planned path. No supplement of this kind is constructed
    anywhere in this mission (see ``redline_core.archive.supplement``'s
    module docstring); this function exists so the package builder
    already handles the shape generically for a later evidence-resolution
    mission."""
    for supplement in supplements:
        dest_path = _safe_destination_path(payload_root, supplement.archive_relative_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            raise ArchivePackageError(f"unexpected pre-existing staging artifact: {dest_path}")
        _copy_file_chunked(supplement.absolute_source_path, dest_path)

        post_copy_sha256, post_copy_size = integrity.hash_stable_file(supplement.absolute_source_path)
        if post_copy_sha256 != supplement.sha256 or post_copy_size != supplement.size_bytes:
            raise ArchiveSourceChangedError(
                f"supplement source changed after planning, detected during package copy: "
                f"{supplement.archive_relative_path}"
            )

        dest_sha256, dest_size = integrity.hash_stable_file(dest_path)
        if dest_sha256 != supplement.sha256 or dest_size != supplement.size_bytes:
            raise ArchiveCopyVerificationError(
                f"copied supplement does not match verified source: {supplement.archive_relative_path}"
            )


def _write_and_verify_generated_supplements(supplements: Sequence[GeneratedArchiveSupplement], payload_root: Path) -> None:
    """Generated supplements have no source file to copy: their
    ``canonical_bytes`` are written directly into staging (exclusive
    creation, never overwriting), then the *destination* is independently
    hashed -- never trusting the in-memory hash alone (Mission 15G item
    28) -- and required to still match the supplement's own already-
    validated fingerprint (``GeneratedArchiveSupplement.__post_init__``
    already proved ``sha256``/``size_bytes`` match ``canonical_bytes`` at
    construction time)."""
    for supplement in supplements:
        dest_path = _safe_destination_path(payload_root, supplement.archive_relative_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            raise ArchivePackageError(f"unexpected pre-existing staging artifact: {dest_path}")
        try:
            with dest_path.open("xb") as fh:
                fh.write(supplement.canonical_bytes)
        except OSError as exc:
            raise ArchivePackageError(f"failed to write generated supplement: {dest_path}") from exc

        dest_sha256, dest_size = integrity.hash_stable_file(dest_path)
        if dest_sha256 != supplement.sha256 or dest_size != supplement.size_bytes:
            raise ArchiveSupplementCopyError(
                f"written generated supplement does not match its own planned bytes: {supplement.archive_relative_path}"
            )


def _create_supplement_directories(directories: Sequence[str], payload_root: Path) -> None:
    """Pre-create every supplement-only directory (Mission 15G.1) --
    mirrors ``_copy_and_verify_workspace_files()``'s own directory-first
    loop for ``plan.workspace_inventory.directories``, so an empty
    evidence subdirectory is preserved exactly like an empty workspace
    subdirectory, not silently dropped because no file happens to imply
    its existence."""
    for directory_path in directories:
        dest_dir = _safe_destination_path(payload_root, directory_path)
        dest_dir.mkdir(parents=True, exist_ok=True)


def _stage_supplements(package_plan: ArchivePackagePlan, payload_root: Path) -> None:
    file_supplements = [s for s in package_plan.supplements if isinstance(s, FileArchiveSupplement)]
    generated_supplements = [s for s in package_plan.supplements if isinstance(s, GeneratedArchiveSupplement)]
    _create_supplement_directories(package_plan.supplement_directories, payload_root)
    _copy_and_verify_file_supplements(file_supplements, payload_root)
    _write_and_verify_generated_supplements(generated_supplements, payload_root)


# -- completeness verification -----------------------------------------------------


def _expected_payload_contents(package_plan: ArchivePackagePlan) -> tuple[dict[str, tuple[int, str]], set[str]]:
    """Return (expected_files, expected_dirs), both keyed/valued by path
    relative to the *payload root* (i.e. already ``workspace/...``,
    ``external/...``, or ``metadata/...``-prefixed) -- the complete
    expected filesystem shape of a sealed package, derived purely from
    the plan, no filesystem access."""
    plan = package_plan.content
    expected_files: dict[str, tuple[int, str]] = {}
    expected_dirs: set[str] = {_WORKSPACE_DIRNAME}

    for f in plan.workspace_inventory.files:
        expected_files[f"{_WORKSPACE_DIRNAME}/{f.relative_path}"] = (f.size_bytes, f.sha256)
    for d in plan.workspace_inventory.directories:
        expected_dirs.add(f"{_WORKSPACE_DIRNAME}/{d.relative_path}")

    for artifact in plan.artifacts:
        if artifact.source_kind == ArchiveSourceKind.WORKSPACE:
            continue
        expected_files[artifact.archive_relative_path] = (artifact.size_bytes, artifact.sha256)
        parts = artifact.archive_relative_path.split("/")
        for i in range(1, len(parts)):
            expected_dirs.add("/".join(parts[:i]))

    for supplement in package_plan.supplements:
        expected_files[supplement.archive_relative_path] = (supplement.size_bytes, supplement.sha256)
        parts = supplement.archive_relative_path.split("/")
        for i in range(1, len(parts)):
            expected_dirs.add("/".join(parts[:i]))

    for directory_path in package_plan.supplement_directories:
        expected_dirs.add(directory_path)
        parts = directory_path.split("/")
        for i in range(1, len(parts)):
            expected_dirs.add("/".join(parts[:i]))

    return expected_files, expected_dirs


def _reconcile_payload_contents(
    expected_files: dict[str, tuple[int, str]],
    expected_dirs: set[str],
    payload_root: Path,
    *,
    error_context: str,
) -> "integrity.SourceInventory":
    """Independently re-enumerate the *entire* ``payload_root`` (a full
    Mission 15C ``build_source_inventory()`` walk, not a weaker duplicate
    traversal) and require it to exactly match ``(expected_files,
    expected_dirs)``: zero missing, zero unexpected, zero hash mismatches,
    zero size mismatches. Returns the freshly-built inventory so a caller
    that needs actual counts (e.g. summary reconciliation) does not have
    to re-walk the tree a second time.

    Shared by both staging-time completeness verification
    (``_verify_payload_completeness()``, expectations derived from an
    in-memory ``ArchiveContentPlan``) and read-only finalized-package
    verification (``verify_archive_package()``, expectations derived from
    a sealed package's own ``archive_manifest.json``) -- one reconciliation
    algorithm, two expectation sources, never two competing
    implementations.
    """
    staging_inventory = integrity.build_source_inventory(payload_root)

    actual_files = {f.relative_path: (f.size_bytes, f.sha256) for f in staging_inventory.files}
    actual_dirs = {d.relative_path for d in staging_inventory.directories}

    missing_files = sorted(expected_files.keys() - actual_files.keys())
    unexpected_files = sorted(actual_files.keys() - expected_files.keys())
    missing_dirs = sorted(expected_dirs - actual_dirs)
    unexpected_dirs = sorted(actual_dirs - expected_dirs)

    common_files = expected_files.keys() & actual_files.keys()
    hash_mismatches = sorted(p for p in common_files if expected_files[p][1] != actual_files[p][1])
    size_mismatches = sorted(p for p in common_files if expected_files[p][0] != actual_files[p][0])

    if missing_files or unexpected_files or missing_dirs or unexpected_dirs or hash_mismatches or size_mismatches:
        raise ArchivePackageVerificationError(
            f"{error_context}: "
            f"missing_files={missing_files} unexpected_files={unexpected_files} "
            f"missing_directories={missing_dirs} unexpected_directories={unexpected_dirs} "
            f"hash_mismatches={hash_mismatches} size_mismatches={size_mismatches}"
        )
    return staging_inventory


def _verify_payload_completeness(package_plan: ArchivePackagePlan, payload_root: Path) -> None:
    """Staging-time completeness check: expectations derived from an
    in-memory ``ArchivePackagePlan`` (content plus supplements). Run once
    after copying and again (via ``_verify_sealed_staging_package()``)
    immediately before publication. A copy loop that returned
    successfully for every individual file/artifact/supplement is not, by
    itself, sufficient evidence of a complete package -- this is the
    independent check.
    """
    expected_files, expected_dirs = _expected_payload_contents(package_plan)
    _reconcile_payload_contents(
        expected_files, expected_dirs, payload_root, error_context="staging payload completeness verification failed"
    )


def _reconcile_supplements(supplements: Sequence[ArchiveSupplement]) -> None:
    """Re-verify every file-backed supplement's source, one more time,
    immediately before sealing -- the same source-stability guarantee
    ``_reconcile_complete_content_plan()`` gives every external artifact
    (Mission 15G item 35). A generated supplement has no external source
    to re-check: its bytes are already fixed, in memory, at plan-
    construction time; ``GeneratedArchiveSupplement.__post_init__``
    already proved its own ``sha256``/``size_bytes`` agree with
    ``canonical_bytes``, and ``_write_and_verify_generated_supplements()``
    independently re-hashes what actually landed on disk. Fails closed
    (``ArchiveSourceChangedError``) on any mismatch; never silently
    adopts a changed source."""
    for supplement in supplements:
        if not isinstance(supplement, FileArchiveSupplement):
            continue
        fresh_sha256, fresh_size = integrity.hash_stable_file(supplement.absolute_source_path)
        if fresh_sha256 != supplement.sha256 or fresh_size != supplement.size_bytes:
            raise ArchiveSourceChangedError(
                f"supplement source changed since the package plan was built: {supplement.archive_relative_path}"
            )


def _reconcile_complete_content_plan(plan: ArchiveContentPlan) -> None:
    """Re-verify the *source side* of the complete content plan, one more
    time, immediately before sealing:

      1. workspace: a fresh ``build_source_inventory()`` of the workspace
         root's ``source_set_digest`` must still equal the digest the
         plan was built from -- per-file post-copy re-hashing (see
         ``_copy_and_verify_workspace_files()``) proves every *expected*
         file is unchanged; it cannot by itself prove no file/directory
         was *added* since the plan was resolved. This closes that gap
         (Mission 15D's own ``_reconcile_complete_source_set``,
         unchanged in spirit, now plan-aware).
      2. every external artifact: a fresh
         ``integrity.hash_stable_file()`` of its ``absolute_source_path``
         must still equal the size/sha256 it was planned with.
      3. the complete logical plan: recomputing ``content_set_digest``
         from the freshly-verified workspace digest and the (otherwise
         unchanged) artifact records must still equal the digest the plan
         was sealed under.

    Any mismatch fails closed (``ArchiveSourceChangedError``). The
    original plan is never silently replaced or rebuilt from what was
    freshly observed.
    """
    fresh_workspace_inventory = integrity.build_source_inventory(plan.workspace_inventory.root)
    if fresh_workspace_inventory.source_set_digest != plan.workspace_inventory.source_set_digest:
        raise ArchiveSourceChangedError(
            "workspace source tree changed since the content plan was built: "
            f"root={plan.workspace_inventory.root} "
            f"original_digest={plan.workspace_inventory.source_set_digest} "
            f"current_digest={fresh_workspace_inventory.source_set_digest}"
        )

    for artifact in plan.artifacts:
        if artifact.source_kind == ArchiveSourceKind.WORKSPACE:
            continue
        fresh_sha256, fresh_size = integrity.hash_stable_file(artifact.absolute_source_path)
        if fresh_sha256 != artifact.sha256 or fresh_size != artifact.size_bytes:
            raise ArchiveSourceChangedError(
                f"external source changed since the content plan was built: {artifact.archive_relative_path}"
            )

    fresh_digest = compute_content_set_digest(fresh_workspace_inventory.source_set_digest, plan.artifacts)
    if fresh_digest != plan.content_set_digest:
        raise ArchiveSourceChangedError(
            "complete content plan changed since it was resolved: "
            f"original_content_set_digest={plan.content_set_digest} current_content_set_digest={fresh_digest}"
        )


def _verify_sealed_staging_package(staged: StagedPackage) -> None:
    """The pre-publication re-verification: does not trust any earlier
    in-memory state. Re-runs the full independent payload-completeness
    check and the full content-plan reconciliation again, then confirms
    the manifest, its SHA-256 sidecar, and the completion marker are all
    present and that the sidecar hash still matches the manifest's actual
    on-disk bytes -- this is what catches tampering that happened after
    sealing but before publication."""
    _verify_payload_completeness(staged.package_plan, staged.payload_root)
    _reconcile_complete_content_plan(staged.content_plan)
    _reconcile_supplements(staged.package_plan.supplements)

    if not staged.manifest_path.is_file():
        raise ArchivePackageVerificationError(f"sealed package is missing its manifest: {staged.manifest_path}")
    if not staged.manifest_sha256_path.is_file():
        raise ArchivePackageVerificationError(
            f"sealed package is missing its manifest SHA-256 sidecar: {staged.manifest_sha256_path}"
        )

    actual_manifest_sha256, _ = integrity.hash_stable_file(staged.manifest_path)
    recorded_sha256 = staged.manifest_sha256_path.read_text(encoding="utf-8").strip()
    if actual_manifest_sha256 != recorded_sha256:
        raise ArchivePackageVerificationError(
            f"sealed manifest hash mismatch: on-disk={actual_manifest_sha256} sidecar={recorded_sha256}"
        )
    if actual_manifest_sha256 != staged.manifest_sha256:
        raise ArchivePackageVerificationError(
            "sealed manifest hash no longer matches the hash recorded at sealing time: "
            f"sealed_at_build_time={staged.manifest_sha256} on-disk-now={actual_manifest_sha256}"
        )
    if not staged.marker_path.is_file():
        raise ArchivePackageVerificationError(f"sealed package is missing its completion marker: {staged.marker_path}")


# -- manifest ----------------------------------------------------------------------


def _format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_unified_artifact_entries(plan: ArchiveContentPlan) -> list[dict]:
    """Return the sealed manifest's complete ``artifacts[]`` list: one
    entry per workspace file (default classification ``workspace``, with
    any matching classification-overlay from ``plan.artifacts`` merged
    in) plus one entry per external artifact. Deterministically ordered
    by ``archive_relative_path`` (case-folded).

    Fails closed (``ArchivePackageError``) if a workspace-kind overlay in
    ``plan.artifacts`` does not correspond to any actual workspace file,
    or if its recorded size/sha256 disagree with that file's -- both
    would indicate the plan was built inconsistently, a caller
    (``ArchiveManager``) bug this function refuses to paper over.
    """
    overlays = {a.archive_relative_path: a for a in plan.artifacts if a.source_kind == ArchiveSourceKind.WORKSPACE}
    matched_overlay_keys: set[str] = set()

    entries: list[dict] = []
    for f in plan.workspace_inventory.files:
        archive_relative_path = f"{_WORKSPACE_DIRNAME}/{f.relative_path}"
        classifications = {_DEFAULT_CLASSIFICATION}
        overlay = overlays.get(archive_relative_path)
        if overlay is not None:
            matched_overlay_keys.add(archive_relative_path)
            if overlay.size_bytes != f.size_bytes or overlay.sha256 != f.sha256:
                raise ArchivePackageError(
                    f"workspace classification overlay fingerprint mismatch: {archive_relative_path}"
                )
            classifications |= {enum_value(c) for c in overlay.classifications}
        entries.append(
            {
                "archive_relative_path": archive_relative_path,
                "classifications": sorted(classifications),
                "original_absolute_path": str(f.absolute_source_path),
                "sha256": f.sha256,
                "size_bytes": f.size_bytes,
                "source_kind": enum_value(ArchiveSourceKind.WORKSPACE),
                "source_relative_path": None,
                "source_root": None,
            }
        )

    unmatched_overlays = sorted(overlays.keys() - matched_overlay_keys)
    if unmatched_overlays:
        raise ArchivePackageError(
            f"workspace classification overlay target(s) not found in workspace inventory: {unmatched_overlays}"
        )

    for artifact in plan.artifacts:
        if artifact.source_kind == ArchiveSourceKind.WORKSPACE:
            continue
        entries.append(
            {
                "archive_relative_path": artifact.archive_relative_path,
                "classifications": sorted({enum_value(c) for c in artifact.classifications}),
                "original_absolute_path": str(artifact.absolute_source_path),
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "source_kind": enum_value(artifact.source_kind),
                "source_relative_path": artifact.source_relative_path,
                "source_root": artifact.source_root,
            }
        )

    entries.sort(key=lambda e: e["archive_relative_path"].casefold())
    return entries


def _build_unified_supplement_entries(supplements: Sequence[ArchiveSupplement]) -> list[dict]:
    """Return the sealed manifest's ``supplements[]`` list: one entry per
    planned supplement (file-backed or generated), deterministically
    ordered by ``archive_relative_path`` (case-folded) -- exactly
    ``ArchivePackagePlan.supplements``'s own already-deterministic order,
    re-sorted here defensively rather than assumed."""
    entries: list[dict] = []
    for supplement in supplements:
        if isinstance(supplement, GeneratedArchiveSupplement):
            supplement_kind_value = "generated"
            original_absolute_path = None
        else:
            supplement_kind_value = "file"
            original_absolute_path = str(supplement.absolute_source_path)
        entries.append(
            {
                "archive_relative_path": supplement.archive_relative_path,
                "classifications": sorted(set(supplement.classifications)),
                "original_absolute_path": original_absolute_path,
                "sha256": supplement.sha256,
                "size_bytes": supplement.size_bytes,
                "source_kind": supplement.source_kind,
                "supplement_kind": supplement_kind_value,
            }
        )
    entries.sort(key=lambda e: e["archive_relative_path"].casefold())
    return entries


def _build_manifest(*, package_plan: ArchivePackagePlan, archive_id: str, episode_id: str, created_at_utc: str) -> dict:
    """Return the Archive Manifest Rev1 document for ``package_plan``.

    Field ordering below is for readability only -- ``json.dumps(...,
    sort_keys=True)`` is what actually makes the serialized bytes
    deterministic. ``artifacts[]``/``supplements[]``/``directories[]``
    order is fixed by ``_build_unified_artifact_entries()``/
    ``_build_unified_supplement_entries()``/the plan's already-
    deterministic workspace inventory -- this function never depends on
    dict/set iteration order.

    ``content.content_set_digest`` is the Rev1 package identity authority
    (Mission 15E.2) -- the Mission 15D-era top-level ``source`` block
    (bare workspace-only ``source_set_digest`` as the identity) is
    deliberately not carried forward unchanged, to avoid two competing
    identity authorities in one document; ``content.workspace_source_set_digest``
    preserves the same information for workspace-only inspection.
    ``content_set_digest`` is computed from ``package_plan.content`` alone
    (see ``redline_core.archive.content.compute_content_set_digest()``) --
    ``supplements`` never participates in it (Mission 15G's identity
    boundary: same preservation content + different supplements yields
    the same ``content_set_digest``/``archive_id`` but a different
    manifest, and therefore a different Archive Manifest SHA-256).

    ``supplements[]`` (Mission 15G) carries production-evidence and
    generated-restore-metadata entries -- sealed, and detected by
    ``archive verify`` exactly like any other package content (see
    ``verify_archive_package()``), but never part of ``content``.
    """
    plan = package_plan.content
    artifacts = _build_unified_artifact_entries(plan)
    supplements = _build_unified_supplement_entries(package_plan.supplements)
    directories = sorted(
        [f"{_WORKSPACE_DIRNAME}/{d.relative_path}" for d in plan.workspace_inventory.directories]
        + list(package_plan.supplement_directories),
        key=lambda d: d.casefold(),
    )
    total_bytes = sum(entry["size_bytes"] for entry in artifacts) + sum(entry["size_bytes"] for entry in supplements)

    return {
        "archive_id": archive_id,
        "artifacts": artifacts,
        "content": {
            "content_set_digest": plan.content_set_digest,
            "workspace_root": str(plan.workspace_inventory.root),
            "workspace_source_set_digest": plan.workspace_inventory.source_set_digest,
        },
        "created_at_utc": created_at_utc,
        "directories": directories,
        "episode_id": episode_id,
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "summary": {
            "directory_count": plan.workspace_inventory.directory_count,
            "file_count": len(artifacts) + len(supplements),
            "total_bytes": total_bytes,
        },
        "supplements": supplements,
        "verification": {
            "algorithm": "sha256",
            "completeness": "verified",
        },
    }


def _canonical_json_bytes(payload: dict) -> bytes:
    """UTF-8, sorted-keys, compact-separator JSON -- the same canonical
    settings used throughout this repository's archive layer."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


# -- staging ------------------------------------------------------------------------


def build_staged_package(
    plan: "ArchiveContentPlan | ArchivePackagePlan",
    *,
    episode_id: str,
    archive_id: str,
    archive_root: str | Path,
    clock: Clock = _default_clock,
) -> StagedPackage:
    """Build and seal a complete Archive Rev1 package at a staging
    location under ``archive_root``. Does not publish it -- call
    ``publish_package()`` on the result to do that.

    Fails closed, before touching any source or copying anything, if the
    final destination (``archive_root/episodes/<episode_id>/<archive_id>``)
    already exists. On any failure raised partway through, the staging
    directory built so far is left exactly as it is -- for forensic
    inspection -- and, critically, will never contain a manifest/sidecar/
    ``PACKAGE_COMPLETE`` unless every step up to and including sealing
    succeeded. No source (workspace or external) is ever written to,
    moved, renamed, or deleted by this function under any outcome.
    """
    package_plan = _coerce_package_plan(plan)
    plan = package_plan.content
    _validate_identity_component(episode_id, "episode_id")
    _validate_identity_component(archive_id, "archive_id")

    root = Path(archive_root)
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()

    final_path = root / _EPISODES_DIRNAME / episode_id / archive_id
    if final_path.exists():
        raise ArchiveDestinationCollisionError(f"archive destination already exists: {final_path}")

    staging_root = root / _STAGING_DIRNAME
    staging_root.mkdir(parents=True, exist_ok=True)
    attempt_id = uuid.uuid4().hex
    staging_path = staging_root / f"{archive_id}.{attempt_id}.partial"
    try:
        staging_path.mkdir()
    except OSError as exc:
        raise ArchivePackageError(f"failed to allocate staging directory: {staging_path}") from exc

    payload_root = staging_path / _PAYLOAD_DIRNAME
    payload_root.mkdir()
    payload_root = payload_root.resolve()
    workspace_root = payload_root / _WORKSPACE_DIRNAME
    workspace_root.mkdir()

    logger.info(
        "Archive package staging begin: archive_id=%s episode_id=%s staging_path=%s final_path=%s "
        "workspace_file_count=%d artifact_count=%d supplement_count=%d",
        archive_id,
        episode_id,
        staging_path,
        final_path,
        plan.workspace_inventory.file_count,
        len(plan.artifacts),
        len(package_plan.supplements),
    )

    _copy_and_verify_workspace_files(plan, workspace_root)
    _copy_and_verify_external_artifacts(plan, payload_root)
    _stage_supplements(package_plan, payload_root)

    _verify_payload_completeness(package_plan, payload_root)
    _reconcile_complete_content_plan(plan)
    _reconcile_supplements(package_plan.supplements)

    created_at_utc = _format_utc(clock())
    manifest = _build_manifest(
        package_plan=package_plan, archive_id=archive_id, episode_id=episode_id, created_at_utc=created_at_utc
    )
    canonical_bytes = _canonical_json_bytes(manifest)

    manifest_path = staging_path / _MANIFEST_FILENAME
    manifest_path.write_bytes(canonical_bytes)
    manifest_sha256, _ = integrity.hash_stable_file(manifest_path)

    manifest_sha256_path = staging_path / _MANIFEST_SHA256_FILENAME
    manifest_sha256_path.write_text(manifest_sha256 + "\n", encoding="utf-8")

    marker_path = staging_path / _MARKER_FILENAME
    marker_path.write_bytes(b"")

    logger.info(
        "Archive package sealed: archive_id=%s episode_id=%s staging_path=%s content_set_digest=%s manifest_sha256=%s",
        archive_id,
        episode_id,
        staging_path,
        plan.content_set_digest,
        manifest_sha256,
    )

    return StagedPackage(
        archive_id=archive_id,
        episode_id=episode_id,
        staging_path=staging_path,
        payload_root=payload_root,
        final_path=final_path,
        manifest_path=manifest_path,
        manifest_sha256_path=manifest_sha256_path,
        marker_path=marker_path,
        manifest_sha256=manifest_sha256,
        content_plan=plan,
        package_plan=package_plan,
        content_set_digest=plan.content_set_digest,
        workspace_source_set_digest=plan.workspace_inventory.source_set_digest,
        file_count=manifest["summary"]["file_count"],
        directory_count=manifest["summary"]["directory_count"],
        total_bytes=manifest["summary"]["total_bytes"],
        supplement_count=len(package_plan.supplements),
    )


# -- publication ----------------------------------------------------------------------


def publish_package(staged: StagedPackage) -> PackageResult:
    """Re-verify ``staged`` one more time (trusting nothing from the
    build call's in-memory state), then atomically publish it: a single
    same-filesystem directory rename from the staging path to the final
    destination.

    Uses ``os.rename()``, deliberately not ``os.replace()`` -- on this
    repository's target Windows filesystem, ``os.rename()`` raises rather
    than silently replacing an existing destination directory; a
    destination existence recheck immediately beforehand additionally
    fails closed with a precise error rather than relying on that OS
    behavior alone. On any failure, the staging directory is left exactly
    as it is -- no partial or renamed-away state, no source mutation, no
    DB write (this module never touches SQLite).
    """
    _verify_sealed_staging_package(staged)

    staged.final_path.parent.mkdir(parents=True, exist_ok=True)
    if staged.final_path.exists():
        raise ArchiveDestinationCollisionError(
            f"archive destination appeared before publication: {staged.final_path}"
        )

    try:
        os.rename(staged.staging_path, staged.final_path)
    except OSError as exc:
        raise ArchivePublicationError(
            f"atomic publication failed: {staged.staging_path} -> {staged.final_path}"
        ) from exc

    logger.info(
        "Archive package published: archive_id=%s episode_id=%s final_path=%s file_count=%d "
        "directory_count=%d total_bytes=%d content_set_digest=%s manifest_sha256=%s",
        staged.archive_id,
        staged.episode_id,
        staged.final_path,
        staged.file_count,
        staged.directory_count,
        staged.total_bytes,
        staged.content_set_digest,
        staged.manifest_sha256,
    )

    return PackageResult(
        archive_id=staged.archive_id,
        episode_id=staged.episode_id,
        final_path=staged.final_path,
        manifest_path=staged.final_path / _MANIFEST_FILENAME,
        manifest_sha256=staged.manifest_sha256,
        content_set_digest=staged.content_set_digest,
        workspace_source_set_digest=staged.workspace_source_set_digest,
        supplement_count=staged.supplement_count,
        file_count=staged.file_count,
        directory_count=staged.directory_count,
        total_bytes=staged.total_bytes,
    )


def build_archive_package(
    plan: "ArchiveContentPlan | ArchivePackagePlan",
    *,
    episode_id: str,
    archive_id: str,
    archive_root: str | Path,
    clock: Clock = _default_clock,
) -> PackageResult:
    """Convenience wrapper: ``build_staged_package()`` immediately
    followed by ``publish_package()``."""
    staged = build_staged_package(
        plan,
        episode_id=episode_id,
        archive_id=archive_id,
        archive_root=archive_root,
        clock=clock,
    )
    return publish_package(staged)


# -- finalized-package verification (read-only) ------------------------------------
#
# Phase 15 Mission 15F: the canonical `archive verify` transport needs to prove an
# *already-published* Rev1 package is still intact, without a `StagedPackage` (that
# object only ever exists transiently during `build_staged_package()`, in the same
# process, immediately before publication) and without any database knowledge --
# this module remains filesystem-only, exactly as it was for Mission 15D/15E.2. The
# reconciliation algorithm itself (`_reconcile_payload_contents()`) is the same one
# `_verify_payload_completeness()` already uses at staging time; only the source of
# *expectations* differs: a sealed package's own `archive_manifest.json` stands in
# for the in-memory `ArchiveContentPlan` that no longer exists once the process that
# built the package has exited.


def _read_safe_file_bytes(path: Path) -> bytes:
    """Read the complete contents of a required package control file
    through the same safe-open primitive every other file read in this
    module uses (never a plain, unverified ``Path.read_bytes()``) --
    proves ``path`` is a genuine regular file, not a symlink/junction/
    reparse point substituted after publication, and that its content did
    not change while being read. Raises ``ArchivePathError`` (missing/
    unreadable) or ``ArchiveUnsafeFilesystemObjectError`` (unsafe object)
    via ``integrity.open_stable_source()`` -- both already ``ArchiveError``
    subclasses, propagated unchanged."""
    with integrity.open_stable_source(path) as (fh, size_bytes):
        data = fh.read()
    if len(data) != size_bytes:
        raise ArchivePackageVerificationError(f"file size changed while reading: {path}")
    return data


def _require_hex64(value: object, field_name: str, *, context: str) -> None:
    if not isinstance(value, str) or not _HEX64_RE.match(value):
        raise ArchivePackageVerificationError(f"{context}: {field_name!r} is not a 64-character lowercase hex digest: {value!r}")


def _require_non_empty_str(value: object, field_name: str, *, context: str) -> None:
    if not isinstance(value, str) or not value:
        raise ArchivePackageVerificationError(f"{context}: {field_name!r} must be a non-empty string: {value!r}")


def _parse_manifest_sha256_sidecar(sidecar_bytes: bytes, *, sidecar_path: Path) -> str:
    """Require the sidecar to hold exactly the canonical writer format
    (``build_staged_package()``: ``manifest_sha256_path.write_text(manifest_sha256
    + "\\n", ...)``) -- a lowercase 64-character hex digest and a single
    trailing newline, nothing else. ``Path.write_text()`` applies the
    platform's universal-newline translation (``newline=None``), so the
    writer's own real on-disk bytes end in ``\\r\\n`` on Windows and
    ``\\n`` on POSIX -- both accepted here as "one trailing newline";
    anything else (a second line, missing terminator, uppercase hex,
    non-hex content) fails closed rather than being leniently parsed."""
    try:
        text = sidecar_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchivePackageVerificationError(f"manifest SHA-256 sidecar is not valid UTF-8: {sidecar_path}") from exc
    if not text.endswith("\n"):
        raise ArchivePackageVerificationError(f"manifest SHA-256 sidecar is not in the expected single-line format: {sidecar_path}")
    digest = text[:-1]
    if digest.endswith("\r"):
        digest = digest[:-1]
    if "\n" in digest or "\r" in digest:
        raise ArchivePackageVerificationError(f"manifest SHA-256 sidecar is not in the expected single-line format: {sidecar_path}")
    if not _HEX64_RE.match(digest):
        raise ArchivePackageVerificationError(
            f"manifest SHA-256 sidecar does not contain a 64-character lowercase hex digest: {sidecar_path}"
        )
    return digest


def _validate_sealed_manifest_structure(manifest: object, *, expected_episode_id: str, expected_archive_id: str) -> dict:
    """Structurally validate a parsed ``archive_manifest.json`` document
    against the exact shape ``_build_manifest()`` produces -- a
    malicious or corrupted-but-consistently-rehashed file must still fail
    here even though its bytes already matched the sidecar/DB SHA-256
    (Mission 15F item 27: hash equality alone is never treated as
    structural proof). Does not trust arbitrary JSON merely because its
    hash matches."""
    context = "sealed archive manifest"
    if not isinstance(manifest, dict):
        raise ArchivePackageVerificationError(f"{context} is not a JSON object")

    if manifest.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise ArchivePackageVerificationError(
            f"{context}: unsupported schema_version {manifest.get('schema_version')!r} (expected {_MANIFEST_SCHEMA_VERSION})"
        )

    _require_non_empty_str(manifest.get("archive_id"), "archive_id", context=context)
    _require_non_empty_str(manifest.get("episode_id"), "episode_id", context=context)
    _require_non_empty_str(manifest.get("created_at_utc"), "created_at_utc", context=context)

    if manifest["archive_id"] != expected_archive_id:
        raise ArchivePackageVerificationError(
            f"{context}: archive_id {manifest['archive_id']!r} does not match expected {expected_archive_id!r}"
        )
    if manifest["episode_id"] != expected_episode_id:
        raise ArchivePackageVerificationError(
            f"{context}: episode_id {manifest['episode_id']!r} does not match expected {expected_episode_id!r}"
        )

    content = manifest.get("content")
    if not isinstance(content, dict):
        raise ArchivePackageVerificationError(f"{context}: 'content' must be an object")
    _require_hex64(content.get("content_set_digest"), "content.content_set_digest", context=context)
    _require_hex64(content.get("workspace_source_set_digest"), "content.workspace_source_set_digest", context=context)
    _require_non_empty_str(content.get("workspace_root"), "content.workspace_root", context=context)

    directories = manifest.get("directories")
    if not isinstance(directories, list) or not all(isinstance(d, str) and d for d in directories):
        raise ArchivePackageVerificationError(f"{context}: 'directories' must be a list of non-empty strings")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ArchivePackageVerificationError(f"{context}: 'artifacts' must be a non-empty list")
    seen_paths: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ArchivePackageVerificationError(f"{context}: artifact entry is not an object: {entry!r}")
        _require_non_empty_str(entry.get("archive_relative_path"), "artifacts[].archive_relative_path", context=context)
        path = entry["archive_relative_path"]
        if path in seen_paths:
            raise ArchivePackageVerificationError(f"{context}: duplicate artifact archive_relative_path: {path!r}")
        seen_paths.add(path)
        classifications = entry.get("classifications")
        if not isinstance(classifications, list) or not classifications or not all(isinstance(c, str) and c for c in classifications):
            raise ArchivePackageVerificationError(f"{context}: artifact {path!r} has an invalid classifications list")
        _require_hex64(entry.get("sha256"), f"artifacts[{path!r}].sha256", context=context)
        size_bytes = entry.get("size_bytes")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise ArchivePackageVerificationError(f"{context}: artifact {path!r} has an invalid size_bytes: {size_bytes!r}")
        if entry.get("source_kind") not in _ARTIFACT_SOURCE_KINDS:
            raise ArchivePackageVerificationError(f"{context}: artifact {path!r} has an invalid source_kind: {entry.get('source_kind')!r}")
        source_root = entry.get("source_root")
        if source_root is not None and not isinstance(source_root, str):
            raise ArchivePackageVerificationError(f"{context}: artifact {path!r} has an invalid source_root: {source_root!r}")
        source_relative_path = entry.get("source_relative_path")
        if source_relative_path is not None and not isinstance(source_relative_path, str):
            raise ArchivePackageVerificationError(
                f"{context}: artifact {path!r} has an invalid source_relative_path: {source_relative_path!r}"
            )

    supplements = manifest.get("supplements")
    if not isinstance(supplements, list):
        raise ArchivePackageVerificationError(f"{context}: 'supplements' must be a list")
    for entry in supplements:
        if not isinstance(entry, dict):
            raise ArchivePackageVerificationError(f"{context}: supplement entry is not an object: {entry!r}")
        _require_non_empty_str(entry.get("archive_relative_path"), "supplements[].archive_relative_path", context=context)
        path = entry["archive_relative_path"]
        if path in seen_paths:
            raise ArchivePackageVerificationError(f"{context}: duplicate/colliding supplement archive_relative_path: {path!r}")
        seen_paths.add(path)
        classifications = entry.get("classifications")
        if not isinstance(classifications, list) or not classifications or not all(isinstance(c, str) and c for c in classifications):
            raise ArchivePackageVerificationError(f"{context}: supplement {path!r} has an invalid classifications list")
        _require_hex64(entry.get("sha256"), f"supplements[{path!r}].sha256", context=context)
        size_bytes = entry.get("size_bytes")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise ArchivePackageVerificationError(f"{context}: supplement {path!r} has an invalid size_bytes: {size_bytes!r}")
        if entry.get("supplement_kind") not in ("file", "generated"):
            raise ArchivePackageVerificationError(
                f"{context}: supplement {path!r} has an invalid supplement_kind: {entry.get('supplement_kind')!r}"
            )
        _require_non_empty_str(entry.get("source_kind"), f"supplements[{path!r}].source_kind", context=context)
        original_absolute_path = entry.get("original_absolute_path")
        if original_absolute_path is not None and not isinstance(original_absolute_path, str):
            raise ArchivePackageVerificationError(
                f"{context}: supplement {path!r} has an invalid original_absolute_path: {original_absolute_path!r}"
            )

    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        raise ArchivePackageVerificationError(f"{context}: 'summary' must be an object")
    for field_name in ("directory_count", "file_count", "total_bytes"):
        value = summary.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ArchivePackageVerificationError(f"{context}: summary.{field_name} is invalid: {value!r}")

    verification = manifest.get("verification")
    if not isinstance(verification, dict) or verification.get("algorithm") != "sha256" or verification.get("completeness") != "verified":
        raise ArchivePackageVerificationError(f"{context}: 'verification' block is missing or does not match the expected contract")

    return manifest


def _expected_payload_contents_from_manifest(manifest: dict) -> tuple[dict[str, tuple[int, str]], set[str]]:
    """Derive the same ``(expected_files, expected_dirs)`` shape
    ``_expected_payload_contents(plan)`` computes at staging time, but
    from a sealed package's own already-structurally-validated manifest
    document instead of an in-memory ``ArchiveContentPlan`` -- the two
    are equivalent by construction (the manifest's ``artifacts``/
    ``directories`` were themselves derived from the plan when the
    package was built), so this reuses the identical parent-directory
    inference every artifact path implies, generalized (not just for
    external artifacts) since a manifest has no in-memory plan to fall
    back on for workspace directories."""
    expected_files: dict[str, tuple[int, str]] = {}
    expected_dirs: set[str] = {_WORKSPACE_DIRNAME}

    for entry in manifest["artifacts"]:
        expected_files[entry["archive_relative_path"]] = (entry["size_bytes"], entry["sha256"])
    for entry in manifest["supplements"]:
        expected_files[entry["archive_relative_path"]] = (entry["size_bytes"], entry["sha256"])
    for directory in manifest["directories"]:
        expected_dirs.add(directory)
    for path in expected_files:
        parts = path.split("/")
        for i in range(1, len(parts)):
            expected_dirs.add("/".join(parts[:i]))

    return expected_files, expected_dirs


def verify_archive_package(
    archive_path: str | Path, *, expected_episode_id: str, expected_archive_id: str
) -> PackageResult:
    """Read-only, filesystem-only verification of an already-published,
    finalized Archive Rev1 package -- the canonical `archive verify`
    transport's core primitive (Phase 15 Mission 15F). Requires only a
    path plus the identity the caller expects to find there (from a
    committed DB row, or any other authority outside this module); needs
    no ``StagedPackage``, no database access, and no Resolve.

    Verifies, in order, fully re-deriving trust from the filesystem at
    every step (never assuming a prior success implies a later one still
    holds):

      1. ``archive_path`` itself is a genuine, existing directory -- not
         a symlink/junction/reparse point.
      2. The package root contains only the permitted control entries
         (``archive_manifest.json``, ``archive_manifest.sha256``,
         ``PACKAGE_COMPLETE``, ``payload/``) -- no unexpected root-level
         content.
      3. Each control file is a safe regular file: ``PACKAGE_COMPLETE``
         is present and empty; ``archive_manifest.json``/
         ``archive_manifest.sha256`` are present and readable.
      4. The manifest SHA-256 sidecar is in the exact writer format (one
         lowercase 64-hex-character line) and matches the manifest's
         actual on-disk SHA-256.
      5. The manifest is structurally valid (schema_version, required
         fields, well-formed ``artifacts``/``summary``/``content``/
         ``verification`` -- never trusted merely because its hash
         matched) and its ``archive_id``/``episode_id`` match what the
         caller expects.
      6. The complete ``payload/`` tree reconciles exactly against the
         manifest's own ``artifacts``/``directories`` -- zero missing,
         zero unexpected, zero hash mismatches, zero size mismatches,
         via the same reconciliation algorithm staging-time verification
         uses (``_reconcile_payload_contents()``); this walk itself fails
         closed on any symlink/junction/reparse point encountered inside
         the payload (Mission 15C's own ``integrity.build_source_inventory()``
         safety policy, reused unchanged).
      7. The manifest's own ``summary`` counts (file_count,
         directory_count, total_bytes) match what was actually,
         independently verified in step 6 -- a corrupted-but-internally-
         consistent summary block does not pass merely because the
         payload itself is intact.

    Never repairs, rewrites, or deletes anything. Raises
    ``ArchivePathError``/``ArchiveUnsafeFilesystemObjectError``/
    ``ArchivePackageVerificationError`` (all ``ArchiveError`` subclasses)
    on any divergence; returns a ``PackageResult`` only when every check
    above passes.
    """
    root = integrity.validate_source_root(archive_path)

    actual_root_entries = {p.name for p in root.iterdir()}
    unexpected_root_entries = sorted(actual_root_entries - _PERMITTED_PACKAGE_ROOT_ENTRIES)
    if unexpected_root_entries:
        raise ArchivePackageVerificationError(f"unexpected root-level package content: {unexpected_root_entries} in {root}")

    marker_path = root / _MARKER_FILENAME
    marker_bytes = _read_safe_file_bytes(marker_path)
    if marker_bytes != b"":
        raise ArchivePackageVerificationError(f"{_MARKER_FILENAME} is expected to be empty: {marker_path}")

    manifest_path = root / _MANIFEST_FILENAME
    manifest_bytes = _read_safe_file_bytes(manifest_path)
    actual_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    sidecar_path = root / _MANIFEST_SHA256_FILENAME
    sidecar_bytes = _read_safe_file_bytes(sidecar_path)
    recorded_manifest_sha256 = _parse_manifest_sha256_sidecar(sidecar_bytes, sidecar_path=sidecar_path)
    if recorded_manifest_sha256 != actual_manifest_sha256:
        raise ArchivePackageVerificationError(
            f"manifest hash mismatch: on-disk={actual_manifest_sha256} sidecar={recorded_manifest_sha256}"
        )

    try:
        parsed_manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ArchivePackageVerificationError(f"sealed archive manifest is not valid JSON: {manifest_path}") from exc

    manifest = _validate_sealed_manifest_structure(
        parsed_manifest, expected_episode_id=expected_episode_id, expected_archive_id=expected_archive_id
    )

    # validate_source_root() lstat's before resolving, so a missing
    # payload/, or one replaced with a symlink/junction after
    # publication, is rejected here rather than silently followed the way
    # a bare Path.is_dir() check would (is_dir() follows symlinks and
    # would happily report True for a link pointing at a real directory).
    payload_root = integrity.validate_source_root(root / _PAYLOAD_DIRNAME)

    expected_files, expected_dirs = _expected_payload_contents_from_manifest(manifest)
    payload_inventory = _reconcile_payload_contents(
        expected_files, expected_dirs, payload_root, error_context="finalized package payload verification failed"
    )

    actual_file_count = len(expected_files)
    actual_total_bytes = sum(size for size, _ in expected_files.values())
    actual_workspace_dir_count = sum(
        1 for d in payload_inventory.directories if d.relative_path.startswith(f"{_WORKSPACE_DIRNAME}/")
    )
    summary = manifest["summary"]
    if (
        summary["file_count"] != actual_file_count
        or summary["directory_count"] != actual_workspace_dir_count
        or summary["total_bytes"] != actual_total_bytes
    ):
        raise ArchivePackageVerificationError(
            "sealed manifest summary does not match independently verified payload content: "
            f"manifest_summary={summary} "
            f"actual={{'file_count': {actual_file_count}, 'directory_count': {actual_workspace_dir_count}, "
            f"'total_bytes': {actual_total_bytes}}}"
        )

    logger.info(
        "Archive package verified: archive_id=%s episode_id=%s archive_path=%s content_set_digest=%s manifest_sha256=%s",
        manifest["archive_id"],
        manifest["episode_id"],
        root,
        manifest["content"]["content_set_digest"],
        actual_manifest_sha256,
    )

    return PackageResult(
        archive_id=manifest["archive_id"],
        episode_id=manifest["episode_id"],
        final_path=root,
        manifest_path=manifest_path,
        manifest_sha256=actual_manifest_sha256,
        content_set_digest=manifest["content"]["content_set_digest"],
        workspace_source_set_digest=manifest["content"]["workspace_source_set_digest"],
        supplement_count=len(manifest["supplements"]),
        file_count=actual_file_count,
        directory_count=actual_workspace_dir_count,
        total_bytes=actual_total_bytes,
    )
