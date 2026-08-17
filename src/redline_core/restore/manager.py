"""RestoreManager (Mission 1B-A1): HEALTHY_SOURCE Restore.

Public surface is deliberately narrow: ``restore_plan()`` (read-only) and
``restore()`` (destructive, gated by repeated backup-ID confirmation and
three itemized quiescence attestations). DEGRADED_SOURCE/MISSING_SOURCE
recovery, ``backup restore-degraded``, MCP Restore, Control Room mutation,
and any Resolve dependency are all explicitly out of scope and not
implemented here or anywhere in this package.

``restore()`` always starts a brand-new restore attempt with its own fresh
restore_id and journal -- it never inspects, resumes, or repairs a prior
attempt's journal. On any failure after a live mutation has begun, the
exception propagates and the process stops; Mission 1B-A1 implements no
automatic rollback, retry, or cleanup.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from redline_core import fsutil
from redline_core.backup.exceptions import BackupConfigurationError, BackupError
from redline_core.backup.manager import BackupManager
from redline_core.backup.package import MANIFEST_FILENAME
from redline_core.backup.paths import (
    format_utc_iso,
    require_safe_regular_file,
    validate_backup_id,
    validate_backup_root_containment,
)
from redline_core.config.loader import REQUIRED_FILES, ConfigError, load_config
from redline_core.restore.exceptions import (
    RestoreConfirmationError,
    RestoreError,
    RestorePreRestoreSnapshotFailedError,
    RestoreTargetUnavailableError,
    RestoreVerificationFailedError,
)
from redline_core.restore.journal import JOURNAL_DIRNAME, RestoreJournal, RestoreState, build_restore_id
from redline_core.restore.models import QuiescenceAttestations, RestorePlanResult, RestoreResult
from redline_core.restore.quiescence import probe_quiescence, require_attestations
from redline_core.restore.schema_fingerprint import (
    build_reference_schema_fingerprint,
    build_schema_fingerprint,
    compare_schema_fingerprints,
)
from redline_core.restore.sidecar import find_present_sidecars, require_no_sidecars
from redline_core.restore.staging import (
    install_staged_config,
    rename_config_aside,
    replace_database,
    stage_config,
    stage_database,
    superseded_config_path,
)

_PIPELINE_TABLES = ("episodes", "render_jobs", "archives")

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _load_manifest(package_dir: Path) -> dict:
    """Re-read a sealed backup package's manifest JSON for its data (e.g.
    per-file relative paths and recorded hashes). Only ever called
    immediately after ``BackupManager.verify_backup()`` has just
    independently re-proven that manifest's sidecar hash and payload
    content -- this is data extraction from an already-trusted manifest,
    not a new trust decision."""
    return json.loads((package_dir / MANIFEST_FILENAME).read_bytes())


class RestoreManager:
    def __init__(self, backup_manager: BackupManager, *, clock: Clock = _default_clock):
        self.backup_manager = backup_manager
        self.config = backup_manager.config
        self.config_dir = Path(backup_manager.config_dir)
        self.db_path = Path(backup_manager.db_path)
        self._clock = clock

    # -- shared preconditions ------------------------------------------------

    def _resolve_backup_root(self) -> Path:
        backup_path = self.config.paths.backup_path
        if not backup_path:
            raise BackupConfigurationError(
                "paths.backup_path is not configured; Restore requires the same configured backup "
                "destination Mission 1A backups use, both to find the target backup and to hold the "
                "restore transaction journal."
            )
        return validate_backup_root_containment(
            backup_root=Path(backup_path), db_path=self.db_path, config_dir=self.config_dir
        )

    def _check_schema_compatible(self, target_db_path: Path):
        reference = build_reference_schema_fingerprint()
        target = build_schema_fingerprint(Path(target_db_path), read_only=True)
        compare_schema_fingerprints(reference, target)

    # -- restore-plan (read-only) ---------------------------------------------

    def restore_plan(self, backup_id: str) -> RestorePlanResult:
        """Read-only report of whether ``restore(backup_id)`` would
        currently be able to proceed. Creates no pre-restore safety
        backup, stages nothing, replaces nothing, and writes no journal
        entries -- ``restore()`` always re-runs every one of these checks
        itself immediately before acting on them; this is a preview, not
        an authorization."""
        validate_backup_id(backup_id)
        blocking: list[str] = []

        target_verified = False
        try:
            verification = self.backup_manager.verify_backup(backup_id)
            target_verified = True
        except BackupError as exc:
            blocking.append(f"target backup verification failed: {exc}")
            verification = None

        schema_compatible = False
        if target_verified:
            try:
                package_dir = verification.backup_path
                manifest = _load_manifest(package_dir)
                target_db_path = package_dir / manifest["database"]["relative_path"]
                self._check_schema_compatible(target_db_path)
                schema_compatible = True
            except (RestoreError, OSError, ValueError, KeyError) as exc:
                blocking.append(f"schema incompatible: {exc}")
        else:
            blocking.append("schema compatibility not checked: target backup did not verify")

        quiescence_probe_passed = False
        try:
            probe_quiescence(self.db_path)
            quiescence_probe_passed = True
        except RestoreError as exc:
            blocking.append(f"quiescence probe failed: {exc}")

        sidecars_present = find_present_sidecars(self.db_path)
        sidecar_check_passed = not sidecars_present
        if not sidecar_check_passed:
            blocking.append(f"SQLite sidecar file(s) present next to the live database: {sidecars_present}")

        return RestorePlanResult(
            backup_id=backup_id,
            target_verified=target_verified,
            schema_compatible=schema_compatible,
            quiescence_probe_passed=quiescence_probe_passed,
            sidecar_check_passed=sidecar_check_passed,
            sidecars_present=tuple(str(p) for p in sidecars_present),
            blocking_issues=tuple(blocking),
        )

    # -- restore (destructive) -------------------------------------------------

    def restore(
        self,
        backup_id: str,
        *,
        confirm_backup_id: str,
        attestations: QuiescenceAttestations,
        reason: str | None = None,
    ) -> RestoreResult:
        """Restore ``backup_id`` to the live system. Always a brand-new
        restore attempt -- never resumes, repairs, or continues a prior
        one. See the module docstring and
        ``docs/BACKUP_RECOVERY_ARCHITECTURE.md`` for the full ordering
        this method implements.
        """
        validate_backup_id(backup_id)
        if confirm_backup_id != backup_id:
            raise RestoreConfirmationError(
                f"confirm_backup_id {confirm_backup_id!r} does not match backup_id {backup_id!r}; refusing "
                "to proceed with a destructive restore."
            )
        require_attestations(attestations)

        backup_root = self._resolve_backup_root()
        restore_id = build_restore_id(self._clock())
        journal = RestoreJournal.create(backup_root / JOURNAL_DIRNAME, restore_id, backup_id, clock=self._clock)
        journal.record(RestoreState.RESTORE_INITIATED, {"reason": reason, "db_path": str(self.db_path), "config_dir": str(self.config_dir)})

        # -- fresh target re-verification, immediately before restore ---------
        try:
            verification = self.backup_manager.verify_backup(backup_id)
        except BackupError as exc:
            journal.record(RestoreState.TARGET_VERIFICATION_FAILED, {"error": str(exc)})
            raise RestoreTargetUnavailableError(
                f"target backup {backup_id!r} failed fresh verification immediately before restore: {exc}"
            ) from exc
        journal.record(
            RestoreState.TARGET_VERIFIED,
            {"database_sha256": verification.database_sha256, "config_file_count": verification.config_file_count},
        )

        package_dir = verification.backup_path
        manifest = _load_manifest(package_dir)
        db_entry = manifest["database"]
        target_db_path = package_dir / db_entry["relative_path"]
        target_config_dir = package_dir / "payload" / "config"

        # -- full application-schema compatibility -----------------------------
        try:
            self._check_schema_compatible(target_db_path)
        except RestoreError as exc:
            journal.record(RestoreState.SCHEMA_INCOMPATIBLE, {"error": str(exc)})
            raise
        journal.record(RestoreState.SCHEMA_COMPATIBLE, {})

        # -- mandatory pre-restore safety backup (Mission 1A, unmodified) -----
        try:
            pre_restore_backup = self.backup_manager.create_backup(
                reason=f"Mission 1B-A1 automatic pre-restore safety snapshot before restoring "
                f"{backup_id} (restore_id={restore_id})"
            )
        except BackupError as exc:
            journal.record(RestoreState.PRE_RESTORE_SNAPSHOT_FAILED, {"error": str(exc)})
            raise RestorePreRestoreSnapshotFailedError(
                f"mandatory pre-restore safety backup failed; restore aborted before any live mutation: {exc}"
            ) from exc
        journal.record(RestoreState.PRE_RESTORE_SNAPSHOT_COMPLETE, {"pre_restore_backup_id": pre_restore_backup.backup_id})

        # -- quiescence: proved probe, then rollback/close before replacement -
        try:
            probe_quiescence(self.db_path)
        except RestoreError as exc:
            journal.record(RestoreState.QUIESCENCE_FAILED, {"error": str(exc)})
            raise
        journal.record(RestoreState.QUIESCENCE_CONFIRMED, {"attestations": asdict(attestations)})

        # -- sidecar gate, pre-replacement --------------------------------------
        try:
            require_no_sidecars(self.db_path, when="before database replacement")
        except RestoreError as exc:
            journal.record(RestoreState.SIDECAR_PRESENT_PRE, {"error": str(exc)})
            raise
        journal.record(RestoreState.SIDECAR_CHECK_PASSED_PRE, {})

        # -- staging: same-volume, independently verified against manifest -----
        journal.record(RestoreState.STAGING_INTENT, {})
        try:
            staged_db_path = stage_database(
                target_db_path=target_db_path, db_manifest_entry=db_entry, live_db_path=self.db_path, restore_id=restore_id
            )
            staged_config_dir = stage_config(
                target_config_dir=target_config_dir,
                config_manifest_entries=manifest["config_files"],
                live_config_dir=self.config_dir,
                restore_id=restore_id,
            )
        except RestoreError as exc:
            journal.record(RestoreState.STAGING_FAILED, {"error": str(exc)})
            raise
        journal.record(
            RestoreState.STAGING_COMPLETE, {"staged_db_path": str(staged_db_path), "staged_config_dir": str(staged_config_dir)}
        )

        # -- database replacement: single os.replace() --------------------------
        journal.record(RestoreState.DB_REPLACE_INTENT, {})
        try:
            replace_database(staged_db_path, self.db_path)
        except RestoreError as exc:
            journal.record(RestoreState.DB_REPLACE_FAILED, {"error": str(exc)})
            raise
        journal.record(RestoreState.DB_REPLACED, {})

        # -- config replacement: two-step, non-atomic ---------------------------
        superseded_path = superseded_config_path(self.config_dir, restore_id)
        journal.record(RestoreState.CONFIG_RENAME_ASIDE_INTENT, {"superseded_path": str(superseded_path)})
        try:
            rename_config_aside(self.config_dir, superseded_path)
        except RestoreError as exc:
            journal.record(RestoreState.CONFIG_REPLACE_FAILED, {"phase": "rename_aside", "error": str(exc)})
            raise
        journal.record(RestoreState.CONFIG_RENAMED_ASIDE, {})

        journal.record(RestoreState.CONFIG_INSTALL_INTENT, {})
        try:
            install_staged_config(staged_config_dir, self.config_dir, superseded_path=superseded_path)
        except RestoreError as exc:
            journal.record(RestoreState.CONFIG_REPLACE_FAILED, {"phase": "install", "error": str(exc)})
            raise
        journal.record(RestoreState.CONFIG_REPLACED, {})

        # -- post-restore verification, in order ---------------------------------
        journal.record(RestoreState.VERIFICATION_INTENT, {})
        try:
            self._verify_restore(manifest=manifest, backup_id=backup_id)
        except RestoreError as exc:
            journal.record(RestoreState.VERIFICATION_FAILED, {"error": str(exc)})
            raise
        journal.record(RestoreState.VERIFIED_SUCCESS, {})

        return RestoreResult(
            restore_id=restore_id,
            backup_id=backup_id,
            pre_restore_backup_id=pre_restore_backup.backup_id,
            journal_dir=journal.journal_dir,
            database_sha256=db_entry["sha256"],
            database_size_bytes=db_entry["size_bytes"],
            config_file_count=len(manifest["config_files"]),
            superseded_config_path=superseded_path,
            completed_at=format_utc_iso(self._clock()),
        )

    # -- post-restore verification, STEP 0 - STEP 7 ----------------------------

    def _verify_restore(self, *, manifest: dict, backup_id: str) -> None:
        # STEP 0: SQLite sidecar absence, before ANY sqlite3 connection to the
        # restored database.
        try:
            require_no_sidecars(self.db_path, when="after database replacement, before opening the restored database")
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
        db_sha256, db_size = fsutil.hash_stable_file(self.db_path, exceptions=exceptions)
        if db_sha256 != db_entry["sha256"] or db_size != db_entry["size_bytes"]:
            raise RestoreVerificationFailedError(
                f"restored live database at {self.db_path} does not byte-match the target backup payload: "
                f"expected sha256={db_entry['sha256']} size={db_entry['size_bytes']}, got sha256={db_sha256} "
                f"size={db_size}"
            )
        for entry in manifest["config_files"]:
            filename = Path(entry["relative_path"]).name
            live_path = self.config_dir / filename
            file_sha256, file_size = fsutil.hash_stable_file(live_path, exceptions=exceptions)
            if file_sha256 != entry["sha256"] or file_size != entry["size_bytes"]:
                raise RestoreVerificationFailedError(
                    f"restored live config file {live_path} does not byte-match the target backup payload: "
                    f"expected sha256={entry['sha256']} size={entry['size_bytes']}, got sha256={file_sha256} "
                    f"size={file_size}"
                )

        # STEP 2: PRAGMA integrity_check == ok.
        try:
            conn = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)
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
            self._check_schema_compatible(self.db_path)
        except RestoreError as exc:
            raise RestoreVerificationFailedError(f"restored database failed post-restore schema compatibility re-check: {exc}") from exc

        # STEP 4: config loader parse + path-safety validation.
        try:
            load_config(self.config_dir)
        except ConfigError as exc:
            raise RestoreVerificationFailedError(f"restored config directory failed to parse/validate: {exc}") from exc
        for filename in REQUIRED_FILES.values():
            try:
                require_safe_regular_file(self.config_dir / filename, description=f"restored config file {filename!r}")
            except BackupError as exc:
                raise RestoreVerificationFailedError(str(exc)) from exc

        # STEP 5: approved non-mutating application-level reads. A plain,
        # read-only sqlite3 connection -- never Database.init_schema()
        # against the restored database.
        try:
            conn = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)
            try:
                for table in _PIPELINE_TABLES:
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RestoreVerificationFailedError(f"application-level read against restored database failed: {exc}") from exc

        # STEP 6: source target backup verify/preservation -- prove the
        # target backup itself is unaffected and still verifies.
        try:
            self.backup_manager.verify_backup(backup_id)
        except BackupError as exc:
            raise RestoreVerificationFailedError(f"target backup {backup_id!r} no longer verifies after restore: {exc}") from exc

        # STEP 7: VERIFIED_SUCCESS -- recorded by the caller (restore()) once
        # this method returns without raising.
