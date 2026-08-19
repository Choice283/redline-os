"""Shared Restore verification authority (Mission 1B-A2-3 extraction).

``verify_restore()`` is the exact behavior-preserving extraction of what
was ``RestoreManager._verify_restore()`` (Mission 1B-A1) -- the smallest
possible function boundary, moved here unchanged so a future recovery
attempt (Mission 1B-A2-3's ``recovery_execution.py``) calls the identical
verification steps 0-6, never a duplicated or approximated copy.
``RestoreManager._verify_restore()`` is now a thin wrapper around this
function; Mission 1B-A1's own observable behavior (proven by its locked
184-test regression gate) is unchanged.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from redline_core import fsutil
from redline_core.backup.exceptions import BackupError
from redline_core.backup.manager import BackupManager
from redline_core.backup.paths import require_safe_regular_file
from redline_core.config.loader import REQUIRED_FILES, ConfigError, load_config
from redline_core.restore.exceptions import RestoreError, RestoreVerificationFailedError
from redline_core.restore.schema_fingerprint import (
    build_reference_schema_fingerprint,
    build_schema_fingerprint,
    compare_schema_fingerprints,
)
from redline_core.restore.sidecar import require_no_sidecars

_PIPELINE_TABLES = ("episodes", "render_jobs", "archives")


def verify_restore(*, db_path: Path, config_dir: Path, backup_manager: BackupManager, manifest: dict, backup_id: str) -> None:
    """STEP 0 - STEP 6 of post-restore verification, in order. Raises
    ``RestoreVerificationFailedError`` (or a more specific subclass whose
    message is reused) on any failure. STEP 7 (``VERIFIED_SUCCESS``) is
    recorded by the caller once this function returns without raising --
    exactly as it always was."""
    db_path = Path(db_path)
    config_dir = Path(config_dir)

    # STEP 0: SQLite sidecar absence, before ANY sqlite3 connection to the
    # restored database.
    try:
        require_no_sidecars(db_path, when="after database replacement, before opening the restored database")
    except RestoreError as exc:
        raise RestoreVerificationFailedError(str(exc)) from exc

    # STEP 1: exact byte identity and size -- live DB and six live config
    # files against the target backup's own manifest-recorded hashes.
    exceptions = fsutil.SafeFileExceptions(
        path_error=RestoreVerificationFailedError,
        unsafe_object=RestoreVerificationFailedError,
        source_changed=RestoreVerificationFailedError,
    )
    db_entry = manifest["database"]
    db_sha256, db_size = fsutil.hash_stable_file(db_path, exceptions=exceptions)
    if db_sha256 != db_entry["sha256"] or db_size != db_entry["size_bytes"]:
        raise RestoreVerificationFailedError(
            f"restored live database at {db_path} does not byte-match the target backup payload: "
            f"expected sha256={db_entry['sha256']} size={db_entry['size_bytes']}, got sha256={db_sha256} "
            f"size={db_size}"
        )
    for entry in manifest["config_files"]:
        filename = Path(entry["relative_path"]).name
        live_path = config_dir / filename
        file_sha256, file_size = fsutil.hash_stable_file(live_path, exceptions=exceptions)
        if file_sha256 != entry["sha256"] or file_size != entry["size_bytes"]:
            raise RestoreVerificationFailedError(
                f"restored live config file {live_path} does not byte-match the target backup payload: "
                f"expected sha256={entry['sha256']} size={entry['size_bytes']}, got sha256={file_sha256} "
                f"size={file_size}"
            )

    # STEP 2: PRAGMA integrity_check == ok.
    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise RestoreVerificationFailedError(f"could not run PRAGMA integrity_check against restored database: {exc}") from exc
    if not (len(rows) == 1 and rows[0][0] == "ok"):
        raise RestoreVerificationFailedError(f"restored database failed PRAGMA integrity_check: {rows!r}")

    # STEP 3: exact schema compatibility, re-checked against the now-live
    # restored database (never via Database.init_schema()).
    try:
        reference = build_reference_schema_fingerprint()
        target = build_schema_fingerprint(db_path, read_only=True)
        compare_schema_fingerprints(reference, target)
    except RestoreError as exc:
        raise RestoreVerificationFailedError(f"restored database failed post-restore schema compatibility re-check: {exc}") from exc

    # STEP 4: config loader parse + path-safety validation.
    try:
        load_config(config_dir)
    except ConfigError as exc:
        raise RestoreVerificationFailedError(f"restored config directory failed to parse/validate: {exc}") from exc
    for filename in REQUIRED_FILES.values():
        try:
            require_safe_regular_file(config_dir / filename, description=f"restored config file {filename!r}")
        except BackupError as exc:
            raise RestoreVerificationFailedError(str(exc)) from exc

    # STEP 5: approved non-mutating application-level reads. A plain,
    # read-only sqlite3 connection -- never Database.init_schema() against
    # the restored database.
    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            for table in _PIPELINE_TABLES:
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise RestoreVerificationFailedError(f"application-level read against restored database failed: {exc}") from exc

    # STEP 6: source target backup verify/preservation -- prove the target
    # backup itself is unaffected and still verifies.
    try:
        backup_manager.verify_backup(backup_id)
    except BackupError as exc:
        raise RestoreVerificationFailedError(f"target backup {backup_id!r} no longer verifies after restore: {exc}") from exc
