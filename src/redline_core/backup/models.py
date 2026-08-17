"""Result/record dataclasses for Backup Manager (Mission 1A).

Frozen and slotted, carrying no mutable manager/DB state -- mirrors
``redline_core.archive.manager``'s ``ArchiveResult``/``ArchiveVerification
Result`` convention: success is a typed, immutable value; every failure
mode is a distinct exception (see ``redline_core.backup.exceptions``), never
a "success with a false flag" shape. No restore result type exists here --
that is Mission 1B's concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupResult:
    """The result of a successfully created and verified Mission 1A backup."""

    backup_id: str
    backup_path: Path
    manifest_path: Path
    manifest_sha256: str
    database_sha256: str
    database_size_bytes: int
    config_file_count: int
    total_bytes: int
    content_set_digest: str
    created_at: str


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """One entry in ``BackupManager.list_backups()`` -- identity fields read
    directly from a sealed package's manifest, without re-verifying its
    content (that is ``verify_backup()``'s job). Only sealed packages with
    a valid completion marker and a manifest whose sidecar hash matches are
    listed at all; an incomplete or corrupt package is silently excluded
    from listing, never reported as a usable backup."""

    backup_id: str
    backup_path: Path
    created_at: str
    reason: str | None
    database_size_bytes: int
    config_file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class BackupVerificationResult:
    """The result of a successful ``BackupManager.verify_backup()`` call.
    ``verified`` is always ``True`` on a returned result -- every failure
    mode raises a typed exception instead (see ``BackupVerificationFailed
    Error`` and friends), matching this module's fail-closed convention.
    The field is still carried explicitly so CLI serialization has one
    self-describing field to report, not an implicit "no exception was
    raised" convention."""

    backup_id: str
    backup_path: Path
    verified: bool
    database_integrity_check: str
    database_sha256: str
    config_file_count: int
    total_bytes: int
