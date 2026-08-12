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

Final Rev1 payload layout (Mission 15E.2; supersedes Mission 15D's
bare-``payload/`` layout -- there is one canonical layout, not two):

    payload/
    ├── workspace/
    │   └── <episode workspace subtree, unchanged from Mission 15D>
    └── external/
        ├── episode_manifest/
        │   └── <legacy original manifest filename>.yaml
        └── source_media/
            ├── ingest/<relative-to-ingest-root>
            └── assets/<relative-to-assets-root>

``external/`` may be entirely absent when a content plan has no external
artifacts (e.g. a low-level test exercising the workspace-only case via
``build_content_plan(inventory, ())``) -- the resulting package layout is
then just ``payload/workspace/...``, still under the one canonical
``workspace/`` prefix.

Every filesystem safety and hashing primitive here is Mission 15C's own
(``redline_core.archive.integrity``, itself now backed by the
domain-neutral ``redline_core.fsutil``) -- this module does not implement
a second, weaker tree walk, hashing routine, or safe-open routine for
either the workspace or the external-artifact case.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

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
    content_set_digest: str
    workspace_source_set_digest: str
    file_count: int
    directory_count: int
    total_bytes: int


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
    file_count: int
    directory_count: int
    total_bytes: int


# -- identity / path safety ------------------------------------------------------


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


# -- completeness verification -----------------------------------------------------


def _expected_payload_contents(plan: ArchiveContentPlan) -> tuple[dict[str, tuple[int, str]], set[str]]:
    """Return (expected_files, expected_dirs), both keyed/valued by path
    relative to the *payload root* (i.e. already ``workspace/...`` or
    ``external/...``-prefixed) -- the complete expected filesystem shape
    of a sealed package, derived purely from the plan, no filesystem
    access."""
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

    return expected_files, expected_dirs


def _verify_payload_completeness(plan: ArchiveContentPlan, payload_root: Path) -> None:
    """Independently re-enumerate the *entire* staging ``payload_root``
    (a full Mission 15C ``build_source_inventory()`` walk, not a weaker
    duplicate traversal) and require it to exactly match the plan across
    workspace files, workspace directories, external artifact files, and
    every directory required to contain them: zero missing, zero
    unexpected, zero hash mismatches, zero size mismatches. A copy loop
    that returned successfully for every individual file/artifact is not,
    by itself, sufficient evidence of a complete package -- this is the
    independent check, run once after copying and again (via
    ``_verify_sealed_staging_package()``) immediately before publication.
    """
    staging_inventory = integrity.build_source_inventory(payload_root)
    expected_files, expected_dirs = _expected_payload_contents(plan)

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
            "staging payload completeness verification failed: "
            f"missing_files={missing_files} unexpected_files={unexpected_files} "
            f"missing_directories={missing_dirs} unexpected_directories={unexpected_dirs} "
            f"hash_mismatches={hash_mismatches} size_mismatches={size_mismatches}"
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
    _verify_payload_completeness(staged.content_plan, staged.payload_root)
    _reconcile_complete_content_plan(staged.content_plan)

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


def _build_manifest(*, plan: ArchiveContentPlan, archive_id: str, episode_id: str, created_at_utc: str) -> dict:
    """Return the Archive Manifest Rev1 document for ``plan``.

    Field ordering below is for readability only -- ``json.dumps(...,
    sort_keys=True)`` is what actually makes the serialized bytes
    deterministic. ``artifacts[]``/``directories[]`` order is fixed by
    ``_build_unified_artifact_entries()``/the plan's already-deterministic
    workspace inventory -- this function never depends on dict/set
    iteration order.

    ``content.content_set_digest`` is the Rev1 package identity authority
    (Mission 15E.2) -- the Mission 15D-era top-level ``source`` block
    (bare workspace-only ``source_set_digest`` as the identity) is
    deliberately not carried forward unchanged, to avoid two competing
    identity authorities in one document; ``content.workspace_source_set_digest``
    preserves the same information for workspace-only inspection.

    Deliberately does not populate (Mission 15G/orchestration scope, not
    yet possessed by this module): a database episode/render-job
    snapshot, production evidence, software/repository identity, or
    effective configuration.
    """
    artifacts = _build_unified_artifact_entries(plan)
    directories = [f"{_WORKSPACE_DIRNAME}/{d.relative_path}" for d in plan.workspace_inventory.directories]
    total_bytes = sum(entry["size_bytes"] for entry in artifacts)

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
            "file_count": len(artifacts),
            "total_bytes": total_bytes,
        },
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
    plan: ArchiveContentPlan,
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
    if type(plan) is not ArchiveContentPlan:
        raise ArchivePackageError("build_staged_package requires a resolved ArchiveContentPlan instance.")
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
        "workspace_file_count=%d artifact_count=%d",
        archive_id,
        episode_id,
        staging_path,
        final_path,
        plan.workspace_inventory.file_count,
        len(plan.artifacts),
    )

    _copy_and_verify_workspace_files(plan, workspace_root)
    _copy_and_verify_external_artifacts(plan, payload_root)

    _verify_payload_completeness(plan, payload_root)
    _reconcile_complete_content_plan(plan)

    created_at_utc = _format_utc(clock())
    manifest = _build_manifest(plan=plan, archive_id=archive_id, episode_id=episode_id, created_at_utc=created_at_utc)
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
        content_set_digest=plan.content_set_digest,
        workspace_source_set_digest=plan.workspace_inventory.source_set_digest,
        file_count=manifest["summary"]["file_count"],
        directory_count=manifest["summary"]["directory_count"],
        total_bytes=manifest["summary"]["total_bytes"],
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
        file_count=staged.file_count,
        directory_count=staged.directory_count,
        total_bytes=staged.total_bytes,
    )


def build_archive_package(
    plan: ArchiveContentPlan,
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
