"""BackupManager (Mission 1A): System-of-Record Backup + Verification.

Public surface is deliberately narrow: ``create_backup()``, ``list_backups
()``, ``verify_backup()``. No restore method, no restore result type, and
no MCP tool exists anywhere in this package -- Mission 1B (restore) is a
separate, not-yet-authorized architecture. Never contacts DaVinci Resolve;
never mutates the live database or the active configuration directory --
every operation here either reads the live system (through an independent,
read-only SQLite connection for the database) or writes new, additively-
named files under the configured backup root.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from redline_core.backup.exceptions import (
    BackupConfigurationError,
    BackupNotFoundError,
    BackupVerificationFailedError,
)
from redline_core.backup.models import BackupRecord, BackupResult, BackupVerificationResult
from redline_core.backup.package import (
    MANIFEST_FILENAME,
    MANIFEST_SHA256_FILENAME,
    MARKER_FILENAME,
    STAGING_DIRNAME,
    SYSTEM_BACKUPS_DIRNAME,
    build_staged_backup,
    publish_staged_backup,
    verify_payload_against_manifest,
)
from redline_core.backup.paths import require_safe_regular_file, validate_backup_id, validate_backup_root_containment
from redline_core.backup.sqlite_snapshot import run_integrity_check
from redline_core.config.loader import REQUIRED_FILES
from redline_core.config.schema import RedlineConfig

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class BackupManager:
    def __init__(self, config: RedlineConfig, config_dir: Path, db_path: Path, *, clock: Clock = _default_clock):
        self.config = config
        self.config_dir = Path(config_dir)
        self.db_path = Path(db_path)
        self._clock = clock

    # -- shared preconditions ----------------------------------------------

    def _resolve_backup_root(self) -> Path:
        backup_path = self.config.paths.backup_path
        if not backup_path:
            raise BackupConfigurationError(
                "paths.backup_path is not configured. A missing backup destination is a "
                "configuration failure, not \"nothing to back up\" -- set paths.backup_path "
                "before calling create_backup()."
            )
        return validate_backup_root_containment(
            backup_root=Path(backup_path), db_path=self.db_path, config_dir=self.config_dir
        )

    def _require_sources_available(self) -> None:
        require_safe_regular_file(self.db_path, description="live Redline OS database")
        for filename in REQUIRED_FILES.values():
            require_safe_regular_file(self.config_dir / filename, description=f"required config file {filename!r}")

    # -- create --------------------------------------------------------------

    def create_backup(self, *, reason: str | None = None) -> BackupResult:
        """Create, seal, independently verify, and atomically publish one
        new backup package containing the live database (via SQLite's
        Online Backup API, never a raw copy) and the exact files named by
        ``redline_core.config.loader.REQUIRED_FILES``.

        Fails closed before creating any staging directory if
        ``paths.backup_path`` is not configured, if the resolved backup
        root overlaps the live database or config directory, or if the
        live database / any required config file is missing or unsafe. On
        any failure after staging begins, the incomplete staging directory
        is left in place under ``<backup_path>/.staging/`` for forensic
        inspection -- never auto-deleted, matching Archive Rev1's
        publication-failure doctrine.
        """
        backup_root = self._resolve_backup_root()
        self._require_sources_available()

        staging_parent = backup_root / STAGING_DIRNAME
        staging_parent.mkdir(parents=True, exist_ok=True)

        staged = build_staged_backup(
            db_path=self.db_path,
            config_dir=self.config_dir,
            required_config_files=REQUIRED_FILES,
            staging_parent=staging_parent,
            clock=self._clock,
            reason=reason,
        )
        final_dir = publish_staged_backup(staged, backup_root=backup_root)

        manifest = staged.manifest
        db_entry = manifest["database"]
        total_bytes = db_entry["size_bytes"] + sum(e["size_bytes"] for e in manifest["config_files"])
        return BackupResult(
            backup_id=staged.backup_id,
            backup_path=final_dir,
            manifest_path=final_dir / MANIFEST_FILENAME,
            manifest_sha256=staged.manifest_sha256,
            database_sha256=db_entry["sha256"],
            database_size_bytes=db_entry["size_bytes"],
            config_file_count=len(manifest["config_files"]),
            total_bytes=total_bytes,
            content_set_digest=manifest["content_set_digest"],
            created_at=manifest["created_at"],
        )

    # -- list ------------------------------------------------------------------

    def list_backups(self) -> list[BackupRecord]:
        """List sealed, complete backups under the configured backup root,
        newest first by ``backup_id`` (lexicographic == chronological,
        since ``backup_id`` is timestamp-prefixed).

        Derives its listing entirely from sealed packages on disk -- there
        is no "backups" table in ``redline.db`` (deliberately: tracking
        backups of the database inside the database being protected is
        circular). An incomplete package (no completion marker), a
        manifest whose sidecar hash does not match its own bytes, a
        directory that otherwise fails to parse as a valid manifest, or a
        package directory whose name no longer equals its own manifest's
        ``backup_id`` (Mission 1A correction pass -- a structural identity
        check only, not a content re-verification: see
        ``_try_read_record()``) is silently excluded from the listing,
        never reported as a usable backup -- ``verify_backup()`` is the
        tool for diagnosing why a specific ``backup_id`` looks wrong;
        ``list_backups()`` only ever reports what is genuinely usable.
        """
        backup_path = self.config.paths.backup_path
        if not backup_path:
            return []
        system_backups_dir = Path(backup_path) / SYSTEM_BACKUPS_DIRNAME
        if not system_backups_dir.is_dir():
            return []

        records: list[BackupRecord] = []
        for entry in sorted(system_backups_dir.iterdir(), key=lambda p: p.name, reverse=True):
            if not entry.is_dir():
                continue
            record = self._try_read_record(entry)
            if record is not None:
                records.append(record)
        return records

    def _try_read_record(self, package_dir: Path) -> BackupRecord | None:
        if not (package_dir / MARKER_FILENAME).is_file():
            return None
        manifest, ok = self._try_read_sealed_manifest(package_dir)
        if not ok:
            return None
        if manifest["backup_id"] != package_dir.name:
            # Structural identity check only (Mission 1A correction pass) --
            # not a re-verification of package content. A directory that
            # was manually renamed or copied after publication now
            # disagrees with the backup_id its own sealed manifest claims;
            # verify_backup() reconstructs its lookup path purely from the
            # requested backup_id, so a mismatched-name package could never
            # actually be found and verified under the id this would
            # otherwise report -- excluded here for the same reason an
            # incomplete or tampered package already is.
            return None
        return BackupRecord(
            backup_id=manifest["backup_id"],
            backup_path=package_dir,
            created_at=manifest["created_at"],
            reason=manifest.get("reason"),
            database_size_bytes=manifest["database"]["size_bytes"],
            config_file_count=len(manifest["config_files"]),
            total_bytes=manifest["database"]["size_bytes"] + sum(e["size_bytes"] for e in manifest["config_files"]),
        )

    @staticmethod
    def _try_read_sealed_manifest(package_dir: Path) -> tuple[dict | None, bool]:
        manifest_path = package_dir / MANIFEST_FILENAME
        sidecar_path = package_dir / MANIFEST_SHA256_FILENAME
        if not manifest_path.is_file() or not sidecar_path.is_file():
            return None, False
        try:
            manifest_bytes = manifest_path.read_bytes()
            expected_sha256 = sidecar_path.read_text(encoding="ascii").strip()
        except OSError:
            return None, False
        if hashlib.sha256(manifest_bytes).hexdigest() != expected_sha256:
            return None, False
        try:
            manifest = json.loads(manifest_bytes)
        except ValueError:
            return None, False
        if not isinstance(manifest, dict) or "backup_id" not in manifest:
            return None, False
        return manifest, True

    # -- verify ------------------------------------------------------------------

    def verify_backup(self, backup_id: str) -> BackupVerificationResult:
        """Independently re-verify a sealed backup at rest: re-derive the
        manifest sidecar hash, re-hash the database snapshot and every
        config file against the manifest's recorded values, and re-run
        ``PRAGMA integrity_check`` against the backup copy -- never trusts
        a prior success or the manifest's own claims at face value. Safe
        to call any number of times; performs no writes.

        Raises ``BackupNotFoundError`` if no package directory exists for
        ``backup_id`` at all. Raises ``BackupVerificationFailedError`` (or
        a more specific ``BackupError`` subclass) for every other failure
        mode -- an incomplete package, a corrupted manifest/sidecar, or
        content that no longer matches the manifest. Never returns a
        result with ``verified=False``.
        """
        validate_backup_id(backup_id)
        backup_path = self.config.paths.backup_path
        if not backup_path:
            raise BackupNotFoundError(f"paths.backup_path is not configured; no backup {backup_id!r} can exist.")

        package_dir = Path(backup_path) / SYSTEM_BACKUPS_DIRNAME / backup_id
        if not package_dir.is_dir():
            raise BackupNotFoundError(f"no backup found with backup_id={backup_id!r} at {package_dir}")

        manifest, sealed_ok = self._try_read_sealed_manifest(package_dir)
        if not sealed_ok:
            raise BackupVerificationFailedError(
                f"backup {backup_id!r} at {package_dir} has a missing, unreadable, or tampered "
                "manifest/sidecar and cannot be verified."
            )
        if not (package_dir / MARKER_FILENAME).is_file():
            raise BackupVerificationFailedError(
                f"backup {backup_id!r} at {package_dir} has no completion marker; it was never "
                "fully published and is not a valid backup."
            )
        if manifest["backup_id"] != backup_id:
            raise BackupVerificationFailedError(
                f"backup {backup_id!r} manifest records a different backup_id "
                f"({manifest['backup_id']!r}); refusing to treat this as a match."
            )

        verify_payload_against_manifest(package_dir, manifest)

        db_entry = manifest["database"]
        db_path = package_dir / db_entry["relative_path"]
        integrity_result = run_integrity_check(db_path)

        return BackupVerificationResult(
            backup_id=backup_id,
            backup_path=package_dir,
            verified=True,
            database_integrity_check=integrity_result,
            database_sha256=db_entry["sha256"],
            config_file_count=len(manifest["config_files"]),
            total_bytes=db_entry["size_bytes"] + sum(e["size_bytes"] for e in manifest["config_files"]),
        )
