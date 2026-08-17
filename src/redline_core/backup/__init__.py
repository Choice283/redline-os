"""Redline OS V2 Mission 1A: System-of-Record Backup + Verification.

Protects the two files/directories that together define Redline OS's
pipeline system of record: the SQLite database at ``REDLINE_DB_PATH`` and
the active configuration directory at ``REDLINE_CONFIG_DIR``. This package
implements *backup and verification only* -- see
``docs/BACKUP_RECOVERY_ARCHITECTURE.md`` for the full architecture and for
why restore is a separate, not-yet-authorized Mission 1B.

Public surface: ``BackupManager.create_backup()`` / ``.list_backups()`` /
``.verify_backup()``. No restore method, no restore result type, and no
MCP tool exists anywhere in this package by design.
"""
from __future__ import annotations

from redline_core.backup.manager import BackupManager
from redline_core.backup.models import BackupRecord, BackupResult, BackupVerificationResult

__all__ = [
    "BackupManager",
    "BackupResult",
    "BackupRecord",
    "BackupVerificationResult",
]
