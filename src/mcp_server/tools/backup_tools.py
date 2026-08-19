"""Backup MCP tools — thin, read-only wrappers around BackupManager.

Mission 1B-B: exposes only `BackupManager.list_backups()` and
`BackupManager.verify_backup()` — the two Mission 1A methods that touch
neither the live database nor Resolve (see `docs/BACKUP_RECOVERY_
ARCHITECTURE.md`'s Mission 1B-B section). `BackupManager.create_backup()`
is explicitly out of scope for Mission 1B-B and is never imported, called,
or reachable from this module.
"""
from __future__ import annotations

from redline_core.backup.exceptions import BackupError
from redline_core.backup.manager import BackupManager
from redline_core.backup.models import BackupRecord, BackupVerificationResult


def _backup_record_to_dict(record: BackupRecord) -> dict:
    return {
        "backup_id": record.backup_id,
        "backup_path": str(record.backup_path),
        "created_at": record.created_at,
        "reason": record.reason,
        "database_size_bytes": record.database_size_bytes,
        "config_file_count": record.config_file_count,
        "total_bytes": record.total_bytes,
    }


def _verification_result_to_dict(result: BackupVerificationResult) -> dict:
    return {
        "backup_id": result.backup_id,
        "backup_path": str(result.backup_path),
        "verified": result.verified,
        "database_integrity_check": result.database_integrity_check,
        "database_sha256": result.database_sha256,
        "config_file_count": result.config_file_count,
        "total_bytes": result.total_bytes,
    }


def _backup_list(manager: BackupManager) -> dict:
    records = manager.list_backups()
    return {"success": True, "backups": [_backup_record_to_dict(r) for r in records]}


def _backup_verify(manager: BackupManager, backup_id: str) -> dict:
    try:
        result = manager.verify_backup(backup_id)
    except (BackupError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "verification": _verification_result_to_dict(result)}


def register(mcp, restore_ctx) -> None:
    """Attach Backup read-only tools to `mcp`, bound to
    `restore_ctx.backup_manager`. `backup_create` is deliberately never
    registered here."""

    @mcp.tool()
    def backup_list() -> dict:
        """List every sealed Mission 1A backup on disk, newest first (read-only)."""
        return _backup_list(restore_ctx.backup_manager)

    @mcp.tool()
    def backup_verify(backup_id: str) -> dict:
        """Independently re-verify a sealed backup at rest (read-only): re-derives the
        manifest hash, re-hashes payload content, and re-runs PRAGMA integrity_check
        against the backup's own database copy. Never touches the live database."""
        return _backup_verify(restore_ctx.backup_manager, backup_id)
