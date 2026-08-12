"""Archive Rev1 package-construction layer (Phase 15 Mission 15D).

Turns an already-verified Mission 15C ``SourceInventory`` into a sealed,
hash-verified, atomically-published package directory. This module builds
package *mechanics* only -- it does not decide when an episode is eligible
for archiving, does not read or write SQLite, does not talk to Resolve,
and does not choose archive IDs. All of that is Archive Manager Rev1
orchestration (Mission 15E+).

Pipeline (see the module's public functions for the exact contract each
step enforces):

    verified SourceInventory (Mission 15C)
            v
    build_staged_package(): allocate staging, recreate directory
    topology, copy every file (through a safety-proven source
    descriptor), re-verify source stability post-copy, verify
    destination content, independently verify staging completeness,
    reconcile the complete source set against the original inventory's
    digest, write + seal Archive Manifest Rev1, write PACKAGE_COMPLETE
            v
    publish_package(): re-verify the sealed staging package one more
    time, then atomically rename staging -> final destination
            v
    PackageResult

``build_archive_package()`` is a thin convenience wrapper calling both in
sequence for the common case. The two-step split exists so a caller (in
particular, this mission's own failure tests) can inspect or deliberately
tamper with a sealed staging package between sealing and publication --
exactly the boundary several of Mission 15D's required tests exercise.

Every filesystem safety and hashing primitive here is Mission 15C's own
(``redline_core.archive.integrity``) -- this module does not implement a
second, weaker tree walk, a second hashing routine, or a second safe-open
routine. The copy read itself streams from
``integrity.open_stable_source()`` (the same four-checkpoint identity
proof ``hash_stable_file()`` relies on for hashing, extracted so the copy
gets it too); destination hashing and both independent completeness/
reconciliation re-walks reuse ``hash_stable_file()`` and
``build_source_inventory()`` verbatim, which is also how destination
object-safety (a copied file unexpectedly becoming a symlink/junction, or
disappearing) is caught -- those primitives already fail closed on both.

Two source-integrity guarantees compose, deliberately not merged into
one: per-file post-copy re-hashing proves every file the inventory
already knew about is still unchanged, while a final whole-tree
source-set-digest reconciliation (run once, after every file has copied
and completeness has verified, before anything is sealed) proves nothing
was *added*, removed, or renamed in the source tree since the inventory
was built -- a gap per-file re-hashing cannot close by itself, since an
added file has no prior inventory entry to be re-verified against.
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
from redline_core.archive.exceptions import (
    ArchiveCopyVerificationError,
    ArchiveDestinationCollisionError,
    ArchivePackageError,
    ArchivePackageVerificationError,
    ArchivePathError,
    ArchivePublicationError,
    ArchiveSourceChangedError,
)
from redline_core.archive.integrity import SourceInventory

logger = logging.getLogger(__name__)

_COPY_CHUNK_SIZE = 1024 * 1024  # 1 MiB; matches integrity.py's streaming-hash chunk size.
_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_FILENAME = "archive_manifest.json"
_MANIFEST_SHA256_FILENAME = "archive_manifest.sha256"
_MARKER_FILENAME = "PACKAGE_COMPLETE"
_PAYLOAD_DIRNAME = "payload"
_STAGING_DIRNAME = ".staging"
_EPISODES_DIRNAME = "episodes"

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


# -- models ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StagedPackage:
    """A fully copied, verified, and sealed package still at its staging
    location -- not yet published. Returned by ``build_staged_package()``
    and consumed by ``publish_package()``. Exposing this intermediate
    result (rather than only a single build-and-publish call) is what
    lets a caller inspect or tamper with a sealed package before
    publication, which several of Mission 15D's required failure tests
    depend on."""

    archive_id: str
    episode_id: str
    staging_path: Path
    payload_root: Path
    final_path: Path
    manifest_path: Path
    manifest_sha256_path: Path
    marker_path: Path
    manifest_sha256: str
    source_inventory: SourceInventory
    source_set_digest: str
    file_count: int
    directory_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class PackageResult:
    """The result of a successfully published Archive Rev1 package.
    Deliberately carries no database or episode-status field -- filesystem
    package construction and DB registration are distinct boundaries; a
    later Archive Manager Rev1 orchestration mission owns stitching the
    two together."""

    archive_id: str
    episode_id: str
    final_path: Path
    manifest_path: Path
    manifest_sha256: str
    source_set_digest: str
    file_count: int
    directory_count: int
    total_bytes: int


# -- identity / path safety ------------------------------------------------------


def _validate_identity_component(value: str, field_name: str) -> None:
    """Defense-in-depth guard on ``episode_id``/``archive_id``: both
    become literal path-name components (the final destination directory
    name, and part of the staging directory name), so a value containing
    a path separator or a bare ``.``/``..`` is rejected outright rather
    than silently interpreted as a path segment."""
    if not isinstance(value, str) or not value:
        raise ArchivePackageError(f"{field_name} must be a non-empty string.")
    if "/" in value or "\\" in value or value in (".", ".."):
        raise ArchivePackageError(f"{field_name} must not contain path separators: {value!r}")


def _safe_destination_path(payload_root_resolved: Path, relative_path: str) -> Path:
    """Join ``relative_path`` under the staging payload root and require
    the result to still resolve inside it.

    Mission 15C's ``SourceInventory`` already guarantees every
    ``relative_path`` came from ``Path.relative_to(root)`` (so it cannot
    be absolute or contain ``..``) -- this check is deliberate defense in
    depth on top of that guarantee, not a substitute for it, per this
    mission's explicit instruction to fail closed on any impossible/
    path-escape condition even though the source side is already trusted.
    """
    candidate = (payload_root_resolved / relative_path).resolve()
    if not candidate.is_relative_to(payload_root_resolved):
        raise ArchivePathError(f"destination path escapes the staging payload root: {relative_path!r}")
    return candidate


# -- file copy --------------------------------------------------------------------


def _copy_file_chunked(source: Path, destination: Path) -> None:
    """Chunked stdlib copy -- never loads a whole file into memory.

    Reads through `integrity.open_stable_source()`, not a plain
    `Path.open()`: the actual source file descriptor whose bytes are
    streamed into the destination is proven, before a single byte is
    read, to be the same safe regular-file identity the pre-open pathname
    check observed (closing the gap where the pathname could theoretically
    have been swapped for a different object between the original
    inventory and this copy's own open()), and proven stable again once
    every chunk has been streamed. This is the same guarantee
    `hash_stable_file()` already gives a hash -- the copy read gets it
    too, not a second, weaker code path. It is in addition to, not a
    replacement for, the separate full post-copy source re-hash and
    destination hash the caller performs afterward.

    Destination is opened with exclusive-create ('xb') so this can never
    silently overwrite an existing file, even though the caller already
    checked the destination does not exist."""
    try:
        with integrity.open_stable_source(source) as (src_fh, _source_size_bytes):
            with destination.open("xb") as dst_fh:
                shutil.copyfileobj(src_fh, dst_fh, length=_COPY_CHUNK_SIZE)
    except OSError as exc:
        raise ArchivePackageError(f"failed to copy file: {source} -> {destination}") from exc


# -- completeness verification -----------------------------------------------------


def _verify_payload_completeness(inventory: SourceInventory, payload_root: Path) -> SourceInventory:
    """Independently re-enumerate ``payload_root`` (a full Mission 15C
    ``build_source_inventory()`` walk, not a weaker duplicate traversal)
    and require it to exactly match ``inventory``: zero missing files,
    zero unexpected files, zero missing directories, zero unexpected
    directories, zero hash mismatches, zero size mismatches. A copy loop
    that returned successfully for every individual file is not, by
    itself, sufficient evidence of a complete package -- this is the
    independent check. Returns the freshly-built staging inventory so a
    caller that already wants it (there isn't one yet) doesn't have to
    re-walk again.
    """
    staging_inventory = integrity.build_source_inventory(payload_root)

    expected_files = {f.relative_path: f for f in inventory.files}
    actual_files = {f.relative_path: f for f in staging_inventory.files}
    expected_dirs = {d.relative_path for d in inventory.directories}
    actual_dirs = {d.relative_path for d in staging_inventory.directories}

    missing_files = sorted(expected_files.keys() - actual_files.keys())
    unexpected_files = sorted(actual_files.keys() - expected_files.keys())
    missing_dirs = sorted(expected_dirs - actual_dirs)
    unexpected_dirs = sorted(actual_dirs - expected_dirs)

    common_files = expected_files.keys() & actual_files.keys()
    hash_mismatches = sorted(p for p in common_files if expected_files[p].sha256 != actual_files[p].sha256)
    size_mismatches = sorted(p for p in common_files if expected_files[p].size_bytes != actual_files[p].size_bytes)

    if missing_files or unexpected_files or missing_dirs or unexpected_dirs or hash_mismatches or size_mismatches:
        raise ArchivePackageVerificationError(
            "staging payload completeness verification failed: "
            f"missing_files={missing_files} unexpected_files={unexpected_files} "
            f"missing_directories={missing_dirs} unexpected_directories={unexpected_dirs} "
            f"hash_mismatches={hash_mismatches} size_mismatches={size_mismatches}"
        )
    return staging_inventory


def _reconcile_complete_source_set(inventory: SourceInventory) -> None:
    """Re-inventory the entire source root via Mission 15C's own
    build_source_inventory() and require its source_set_digest to still
    equal `inventory.source_set_digest` -- the digest of the
    SourceInventory this package was built from.

    Per-file post-copy re-hashing (see the copy loop in
    build_staged_package()) proves every *expected* file's content is
    unchanged; it cannot, by itself, prove no file or directory was
    *added* to the source tree since the inventory was built, since an
    added entry has nothing in the original inventory to be re-verified
    against. This closes that gap using the same deterministic
    source-set digest Mission 15C already defines (a canonical
    representation of every directory and every file's
    {path, size_bytes, sha256}), not a second, invented tree-comparison
    format -- so it also transitively catches a removal, a rename, or an
    empty-directory add/remove, exactly as `build_source_inventory()`'s
    own digest already reacts to those.

    The freshly-built inventory is used only for this one comparison and
    is then discarded: a digest mismatch fails closed rather than
    silently adopting the fresh inventory or rebuilding the package from
    it. The originally supplied SourceInventory remains the package's
    sole contract."""
    fresh_inventory = integrity.build_source_inventory(inventory.root)
    if fresh_inventory.source_set_digest != inventory.source_set_digest:
        raise ArchiveSourceChangedError(
            "source tree changed since the supplied SourceInventory was built: "
            f"root={inventory.root} original_digest={inventory.source_set_digest} "
            f"current_digest={fresh_inventory.source_set_digest}"
        )


def _verify_sealed_staging_package(staged: StagedPackage) -> None:
    """The pre-publication re-verification (Mission 15D section 15): does
    not trust any earlier in-memory state. Re-runs the full independent
    payload-completeness check again, then confirms the manifest, its
    SHA-256 sidecar, and the completion marker are all present and that
    the sidecar hash still matches the manifest's actual on-disk bytes --
    this is what catches tampering that happened after sealing but before
    publication."""
    _verify_payload_completeness(staged.source_inventory, staged.payload_root)

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


def _build_manifest(*, inventory: SourceInventory, archive_id: str, episode_id: str, created_at_utc: str) -> dict:
    """Return the Archive Manifest Rev1 document for ``inventory``.

    Field ordering below is for readability only -- ``json.dumps(...,
    sort_keys=True)`` is what actually makes the serialized bytes
    deterministic, not dict insertion order. Artifact and directory list
    *order* is preserved exactly from ``inventory.files``/
    ``inventory.directories``, which Mission 15C already returns sorted
    by case-folded relative path -- this function does not re-sort and
    does not rely on set/dict iteration order anywhere.

    Deliberately does not populate (Mission 15G/orchestration scope, not
    yet possessed by this module): a database episode/render-job
    snapshot, production evidence, software/repository identity, or
    effective configuration. Only what this module actually verified
    goes in.
    """
    artifacts = [
        {
            "archive_relative_path": f"{_PAYLOAD_DIRNAME}/{f.relative_path}",
            "sha256": f.sha256,
            "size_bytes": f.size_bytes,
            "source_relative_path": f.relative_path,
        }
        for f in inventory.files
    ]
    directories = [f"{_PAYLOAD_DIRNAME}/{d.relative_path}" for d in inventory.directories]

    return {
        "archive_id": archive_id,
        "artifacts": artifacts,
        "created_at_utc": created_at_utc,
        "directories": directories,
        "episode_id": episode_id,
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "source": {
            "source_root": str(inventory.root),
            "source_set_digest": inventory.source_set_digest,
        },
        "summary": {
            "directory_count": inventory.directory_count,
            "file_count": inventory.file_count,
            "total_bytes": inventory.total_bytes,
        },
        "verification": {
            "algorithm": "sha256",
            "completeness": "verified",
        },
    }


def _canonical_json_bytes(payload: dict) -> bytes:
    """UTF-8, sorted-keys, compact-separator JSON -- the same canonical
    settings ``integrity.py``'s source-set digest and
    ``reconciliation/serialization.py`` already use in this repository."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


# -- staging ------------------------------------------------------------------------


def build_staged_package(
    inventory: SourceInventory,
    *,
    episode_id: str,
    archive_id: str,
    archive_root: str | Path,
    clock: Clock = _default_clock,
) -> StagedPackage:
    """Build and seal a complete Archive Rev1 package at a staging
    location under ``archive_root``. Does not publish it -- call
    ``publish_package()`` on the result to do that.

    Fails closed, before touching the source or copying anything, if the
    final destination (``archive_root/episodes/<episode_id>/<archive_id>``)
    already exists. On any failure raised partway through (a source
    changed since the inventory was built -- whether a single file's
    content, or the source tree gaining/losing an entry entirely, caught
    by the final source-set-digest reconciliation right before sealing --
    a copy verification mismatch, or an incomplete staging payload), the
    staging directory built so far is left exactly as it is -- for
    forensic inspection, per this mission's explicit fail-closed design --
    and, critically, will never contain a manifest/sidecar/
    ``PACKAGE_COMPLETE`` unless every step up to and including sealing
    succeeded. The source tree itself is never written
    to, moved, renamed, or deleted by this function under any outcome.
    """
    if type(inventory) is not SourceInventory:
        raise ArchivePackageError("build_staged_package requires a verified SourceInventory instance.")
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

    logger.info(
        "Archive package staging begin: archive_id=%s episode_id=%s staging_path=%s final_path=%s "
        "file_count=%d directory_count=%d total_bytes=%d",
        archive_id,
        episode_id,
        staging_path,
        final_path,
        inventory.file_count,
        inventory.directory_count,
        inventory.total_bytes,
    )

    for directory in inventory.directories:
        dest_dir = _safe_destination_path(payload_root, directory.relative_path)
        dest_dir.mkdir(parents=True, exist_ok=True)

    for inv_file in inventory.files:
        dest_path = _safe_destination_path(payload_root, inv_file.relative_path)
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

    _verify_payload_completeness(inventory, payload_root)
    _reconcile_complete_source_set(inventory)

    created_at_utc = _format_utc(clock())
    manifest = _build_manifest(
        inventory=inventory, archive_id=archive_id, episode_id=episode_id, created_at_utc=created_at_utc
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
        "Archive package sealed: archive_id=%s episode_id=%s staging_path=%s manifest_sha256=%s",
        archive_id,
        episode_id,
        staging_path,
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
        source_inventory=inventory,
        source_set_digest=inventory.source_set_digest,
        file_count=inventory.file_count,
        directory_count=inventory.directory_count,
        total_bytes=inventory.total_bytes,
    )


# -- publication ----------------------------------------------------------------------


def publish_package(staged: StagedPackage) -> PackageResult:
    """Re-verify ``staged`` one more time (trusting nothing from the
    build call's in-memory state), then atomically publish it: a single
    same-filesystem directory rename from the staging path to the final
    destination.

    Uses ``os.rename()``, deliberately not ``os.replace()`` -- on this
    repository's target Windows filesystem, ``os.rename()`` raises rather
    than silently replacing an existing destination directory, which is
    exactly the never-overwrite guarantee this function must uphold; a
    destination existence recheck immediately beforehand additionally
    fails closed with a precise error rather than relying on that OS
    behavior alone. If the final destination exists (whether it was there
    before this call or appeared in the race window between the recheck
    and the rename), publication fails closed and nothing is overwritten.
    On any failure, the staging directory is left exactly as it is -- no
    partial or renamed-away state, no source mutation, no DB write (this
    module never touches SQLite).
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
        "directory_count=%d total_bytes=%d manifest_sha256=%s",
        staged.archive_id,
        staged.episode_id,
        staged.final_path,
        staged.file_count,
        staged.directory_count,
        staged.total_bytes,
        staged.manifest_sha256,
    )

    return PackageResult(
        archive_id=staged.archive_id,
        episode_id=staged.episode_id,
        final_path=staged.final_path,
        manifest_path=staged.final_path / _MANIFEST_FILENAME,
        manifest_sha256=staged.manifest_sha256,
        source_set_digest=staged.source_set_digest,
        file_count=staged.file_count,
        directory_count=staged.directory_count,
        total_bytes=staged.total_bytes,
    )


def build_archive_package(
    inventory: SourceInventory,
    *,
    episode_id: str,
    archive_id: str,
    archive_root: str | Path,
    clock: Clock = _default_clock,
) -> PackageResult:
    """Convenience wrapper: ``build_staged_package()`` immediately
    followed by ``publish_package()``. Equivalent to calling both
    yourself; provided because it's the common case for a caller that
    does not need to inspect or tamper with the sealed staging package in
    between."""
    staged = build_staged_package(
        inventory,
        episode_id=episode_id,
        archive_id=archive_id,
        archive_root=archive_root,
        clock=clock,
    )
    return publish_package(staged)
