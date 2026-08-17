"""Backup package construction: stage, seal, verify, and atomically publish
(Mission 1A).

Mirrors ``redline_core.archive.package``'s proven shape deliberately (stage
-> independently re-verify -> atomic publish; a sealed manifest + SHA-256
sidecar; never overwrite) rather than inventing a different pipeline for a
structurally identical problem. This module does not decide *what* belongs
in a backup (that is ``BackupManager`` orchestration, mirroring how
``redline_core.archive.package`` never decides archive content either) --
it only builds package mechanics from an already-resolved database path,
config directory, and required-config-file list.

Software/runtime identity here is deliberately a small, local, ~10-line
helper rather than an import of
``redline_core.archive.metadata_snapshot.resolve_software_identity()``:
that function is real and correct, but importing it would make
``redline_core.backup`` depend on ``redline_core.archive`` for a generic
utility -- exactly the backward, cross-domain layering dependency
``redline_core.fsutil``'s own module docstring documents being extracted
specifically to avoid. Backups and archives are separate responsibilities
(per this mission's own locked direction); this module does not redesign
or depend on Archive Manager. Like the archive precedent it mirrors, there
is no git-shelling repository-revision discovery mechanism anywhere in
this repository, so ``repository_revision`` is always recorded as
``null`` here too -- not fabricated, not silently omitted.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat as stat_module
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Callable, Mapping

from redline_core import fsutil
from redline_core.backup.exceptions import (
    BackupCopyVerificationError,
    BackupDestinationCollisionError,
    BackupError,
    BackupPublicationError,
    BackupSourceUnavailableError,
    BackupUnsafeFilesystemObjectError,
    BackupVerificationFailedError,
)
from redline_core.backup.paths import (
    build_backup_id,
    format_utc_iso,
    require_safe_directory,
    require_safe_regular_file,
)
from redline_core.backup.sqlite_snapshot import probe_schema, require_integrity_ok, run_integrity_check, snapshot_database

Clock = Callable[[], datetime]

MANIFEST_FILENAME = "backup_manifest.json"
MANIFEST_SHA256_FILENAME = "backup_manifest.sha256"
MARKER_FILENAME = "BACKUP_COMPLETE"
STAGING_DIRNAME = ".staging"
SYSTEM_BACKUPS_DIRNAME = "system_backups"
_COPY_CHUNK_SIZE = 1024 * 1024  # 1 MiB; matches fsutil's/archive's streaming chunk size.
_DISTRIBUTION_NAME = "redline-os"

_BACKUP_SAFE_FILE_EXCEPTIONS = fsutil.SafeFileExceptions(
    path_error=BackupSourceUnavailableError,
    unsafe_object=BackupUnsafeFilesystemObjectError,
    source_changed=BackupSourceUnavailableError,
)


@dataclass(frozen=True, slots=True)
class StagedBackup:
    """A fully built, sealed, self-verified backup package still sitting in
    ``.staging/`` -- not yet published to ``system_backups/``."""

    staging_dir: Path
    manifest: dict
    manifest_path: Path
    manifest_sha256: str
    backup_id: str


def _resolve_redline_os_version() -> str | None:
    try:
        return importlib_metadata.version(_DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError:
        return None


def _resolve_python_version() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def _canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _copy_and_verify_config_file(source_path: Path, destination_path: Path) -> tuple[str, int]:
    """Stream ``source_path`` through ``fsutil.open_stable_source()``
    (proving it did not change mid-read) while writing it to
    ``destination_path``, then independently re-read the just-written
    destination and compare hashes/sizes. Raises
    ``BackupCopyVerificationError`` on any mismatch -- no package is ever
    published with a config file that failed this check."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_digest = hashlib.sha256()
    with fsutil.open_stable_source(source_path, exceptions=_BACKUP_SAFE_FILE_EXCEPTIONS) as (fh, size_bytes):
        with destination_path.open("wb") as out:
            while True:
                chunk = fh.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                source_digest.update(chunk)
                out.write(chunk)
    source_sha256 = source_digest.hexdigest()

    dest_digest = hashlib.sha256()
    dest_size = 0
    with destination_path.open("rb") as verify_fh:
        while True:
            chunk = verify_fh.read(_COPY_CHUNK_SIZE)
            if not chunk:
                break
            dest_digest.update(chunk)
            dest_size += len(chunk)

    if dest_digest.hexdigest() != source_sha256 or dest_size != size_bytes:
        raise BackupCopyVerificationError(
            f"copied config file content does not match its verified source: "
            f"{source_path} -> {destination_path}"
        )
    return source_sha256, size_bytes


def _compute_content_set_digest(*, db_sha256: str, db_size: int, config_entries: list[dict]) -> str:
    payload = {
        "database": {"sha256": db_sha256, "size_bytes": db_size},
        "config_files": sorted(
            (
                {"relative_path": e["relative_path"], "sha256": e["sha256"], "size_bytes": e["size_bytes"]}
                for e in config_entries
            ),
            key=lambda e: e["relative_path"],
        ),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _build_manifest(
    *,
    backup_id: str,
    created_at: str,
    reason: str | None,
    db_path: Path,
    config_dir: Path,
    db_relative_path: str,
    db_sha256: str,
    db_size: int,
    integrity_result: str,
    schema_probe: dict,
    config_entries: list[dict],
    content_set_digest: str,
) -> dict:
    return {
        "schema_tag": "b1",
        "backup_id": backup_id,
        "created_at": created_at,
        "reason": reason,
        "source": {
            "redline_db_path": str(db_path),
            "redline_config_dir": str(config_dir),
            "redline_os_version": _resolve_redline_os_version(),
            "repository_revision": None,
            "python_version": _resolve_python_version(),
        },
        "database": {
            "relative_path": db_relative_path,
            "sha256": db_sha256,
            "size_bytes": db_size,
            "integrity_check": integrity_result,
            "schema_probe": schema_probe,
        },
        "config_files": sorted(config_entries, key=lambda e: e["relative_path"]),
        "content_set_digest": content_set_digest,
    }


def _require_exact_payload_contents(directory: Path, expected_files: set[Path], *, description: str) -> None:
    """Fail closed if ``directory`` contains anything beyond exactly
    ``expected_files``: an unmanifested file, any nested directory, or an
    unsafe filesystem object.

    Deliberately a **single-level scan, never a recursive crawler**
    (Mission 1A correction pass, second round). An earlier version used
    ``Path.rglob("*")`` and was empirically shown to traverse *into* a
    Windows junction's target directory before its own per-entry safety
    check ever ran against the junction entry itself -- Python's own
    symlink-loop protection does not help here, since ``Path.is_symlink()``
    reports ``False`` for Windows junctions/reparse points. Mission 1A's
    approved payload structure is always flat (``payload/database/``
    holds exactly one file, ``payload/config/`` holds exactly six), so no
    legitimate nested directory can ever exist here at all -- the correct
    fix is not "recurse more carefully," it is "never recurse": every
    directory entry found at this single level is rejected immediately,
    safe or not, junction or ordinary, without this function ever calling
    anything that would enumerate its contents. ``Path.iterdir()`` (a thin
    wrapper over ``os.scandir()``) lists only immediate children and has no
    recursive-descent logic at all, so it cannot be tricked into following
    a junction the way ``rglob()`` was.

    The ``directory`` argument itself is checked the same way, via
    ``require_safe_directory(..., must_exist=False)``, before anything is
    listed -- so a payload directory itself replaced by a symlink/junction
    is rejected before it is ever enumerated, not just its contents. A
    missing ``directory`` is not itself an error here -- required-file
    absence is already reported per-file by the caller's own
    ``require_safe_regular_file()`` checks; this only guards against
    *extra* content once the directory exists.

    This helper is shared by both the database and config verification
    paths so there is exactly one real implementation of "does this
    payload directory contain only what the manifest says it should," not
    two slightly different ones.
    """
    require_safe_directory(directory, description=description, must_exist=False)
    if not directory.is_dir():
        return
    for entry in sorted(directory.iterdir()):
        st = os.lstat(entry)
        if fsutil.is_unsafe_link(st):
            raise BackupUnsafeFilesystemObjectError(
                f"{description} contains a symlink, junction, or reparse point, which is never "
                f"permitted in a sealed backup payload: {entry}"
            )
        if stat_module.S_ISDIR(st.st_mode):
            raise BackupVerificationFailedError(f"{description} contains an unexpected nested directory: {entry}")
        if not stat_module.S_ISREG(st.st_mode):
            raise BackupUnsafeFilesystemObjectError(f"{description} contains a non-regular filesystem object: {entry}")
        if entry.resolve() not in expected_files:
            raise BackupVerificationFailedError(f"{description} contains file(s) not listed in the manifest: {entry}")


def _verify_database_against_manifest(root: Path, database_entry: dict) -> None:
    db_path = root / database_entry["relative_path"]
    require_safe_regular_file(db_path, description="backup database snapshot")
    actual_sha256, actual_size = fsutil.hash_stable_file(db_path, exceptions=_BACKUP_SAFE_FILE_EXCEPTIONS)
    if actual_sha256 != database_entry["sha256"] or actual_size != database_entry["size_bytes"]:
        raise BackupVerificationFailedError(f"backup database snapshot content does not match manifest: {db_path}")
    actual_integrity = run_integrity_check(db_path)
    if actual_integrity != database_entry["integrity_check"]:
        raise BackupVerificationFailedError(
            f"backup database snapshot integrity_check ({actual_integrity!r}) does not match "
            f"manifest-recorded value ({database_entry['integrity_check']!r}): {db_path}"
        )

    _require_exact_payload_contents(db_path.parent, {db_path.resolve()}, description="backup database payload")


def _verify_config_files_against_manifest(root: Path, config_entries: list[dict]) -> None:
    expected_paths: set[Path] = set()
    for entry in config_entries:
        config_path = root / entry["relative_path"]
        expected_paths.add(config_path.resolve())
        require_safe_regular_file(config_path, description=f"backed-up config file {entry['relative_path']!r}")
        actual_sha256, actual_size = fsutil.hash_stable_file(config_path, exceptions=_BACKUP_SAFE_FILE_EXCEPTIONS)
        if actual_sha256 != entry["sha256"] or actual_size != entry["size_bytes"]:
            raise BackupVerificationFailedError(f"backed-up config file content does not match manifest: {config_path}")

    actual_config_dir = root / "payload" / "config"
    _require_exact_payload_contents(actual_config_dir, expected_paths, description="backed-up config payload")


def verify_payload_against_manifest(root: Path, manifest: dict) -> None:
    """Independently re-enumerate and re-hash everything under ``root``
    (a staging directory pre-publish, or a sealed ``system_backups/<backup
    _id>/`` directory at rest) and confirm it matches ``manifest`` exactly.
    Used both immediately after staging (before the completion marker is
    written), again immediately before publication, and by
    ``BackupManager.verify_backup()`` for at-rest re-verification -- one
    real implementation of this check, not three.

    Every failure mode -- a missing file, a hash mismatch, a corrupted
    integrity_check result, an unsafe filesystem object, an unexpected
    extra file -- is normalized to ``BackupVerificationFailedError`` here,
    so every caller gets one predictable exception type; the original,
    more specific failure is preserved as ``__cause__``.
    """
    try:
        _verify_database_against_manifest(root, manifest["database"])
        _verify_config_files_against_manifest(root, manifest["config_files"])
    except BackupVerificationFailedError:
        raise
    except BackupError as exc:
        raise BackupVerificationFailedError(f"backup payload verification failed under {root}: {exc}") from exc


def build_staged_backup(
    *,
    db_path: Path,
    config_dir: Path,
    required_config_files: Mapping[str, str],
    staging_parent: Path,
    clock: Clock,
    reason: str | None,
) -> StagedBackup:
    """Build one complete, sealed, self-verified backup package inside a
    fresh staging directory under ``staging_parent`` (``<backup_path>/.
    staging/``). Raises before creating anything if the live database or
    any required config file is missing/unsafe (see ``BackupManager`` for
    those preconditions) -- this function assumes its caller already
    validated source availability and backup-root containment.
    """
    staging_dir = staging_parent / uuid.uuid4().hex
    staging_dir.mkdir(parents=True)

    payload_root = staging_dir / "payload"
    db_dest = payload_root / "database" / "redline.db"
    snapshot_database(db_path, db_dest)
    db_sha256, db_size = fsutil.hash_stable_file(db_dest, exceptions=_BACKUP_SAFE_FILE_EXCEPTIONS)
    integrity_result = require_integrity_ok(db_dest)
    schema_probe = probe_schema(db_dest)

    config_dest_root = payload_root / "config"
    config_entries: list[dict] = []
    for filename in sorted(required_config_files.values()):
        source_path = config_dir / filename
        require_safe_regular_file(source_path, description=f"required config file {filename!r}")
        sha256, size_bytes = _copy_and_verify_config_file(source_path, config_dest_root / filename)
        config_entries.append(
            {"relative_path": f"payload/config/{filename}", "sha256": sha256, "size_bytes": size_bytes}
        )

    content_set_digest = _compute_content_set_digest(db_sha256=db_sha256, db_size=db_size, config_entries=config_entries)
    moment = clock()
    backup_id = build_backup_id(moment, content_set_digest)

    manifest = _build_manifest(
        backup_id=backup_id,
        created_at=format_utc_iso(moment),
        reason=reason,
        db_path=db_path,
        config_dir=config_dir,
        db_relative_path="payload/database/redline.db",
        db_sha256=db_sha256,
        db_size=db_size,
        integrity_result=integrity_result,
        schema_probe=schema_probe,
        config_entries=config_entries,
        content_set_digest=content_set_digest,
    )
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_path = staging_dir / MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    (staging_dir / MANIFEST_SHA256_FILENAME).write_text(manifest_sha256, encoding="ascii")

    # Verify once, immediately after writing everything -- before the
    # completion marker exists, so a failure here never leaves a
    # marker-bearing (i.e. "complete") package behind.
    verify_payload_against_manifest(staging_dir, manifest)

    (staging_dir / MARKER_FILENAME).write_bytes(b"")

    return StagedBackup(
        staging_dir=staging_dir,
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        backup_id=backup_id,
    )


def publish_staged_backup(staged: StagedBackup, *, backup_root: Path) -> Path:
    """Independently re-verify the sealed staging package one more time,
    then atomically publish it to ``<backup_root>/system_backups/<backup_
    id>/``. Never overwrites: the rename itself fails atomically if the
    destination already exists (``os.rename`` raises rather than
    replacing), so there is no separate check-then-act race window."""
    verify_payload_against_manifest(staged.staging_dir, staged.manifest)
    if not (staged.staging_dir / MARKER_FILENAME).is_file():
        raise BackupPublicationError(f"staged backup {staged.backup_id!r} has no completion marker; refusing to publish.")

    final_parent = backup_root / SYSTEM_BACKUPS_DIRNAME
    final_parent.mkdir(parents=True, exist_ok=True)
    final_dir = final_parent / staged.backup_id

    if final_dir.exists():
        raise BackupDestinationCollisionError(f"a backup already exists at {final_dir}; refusing to overwrite.")
    try:
        os.rename(staged.staging_dir, final_dir)
    except FileExistsError as exc:
        raise BackupDestinationCollisionError(f"a backup already exists at {final_dir}; refusing to overwrite.") from exc
    except OSError as exc:
        raise BackupPublicationError(f"could not publish staged backup to {final_dir}: {exc}") from exc

    return final_dir
