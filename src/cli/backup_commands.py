"""Backup CLI commands (Mission 1A) -- `_run_*`/`_print_*` handler pairs
returning `{"success": bool, ...}` dicts with no argparse/stdout
dependency, subparser registration, and a `run()` dispatch entrypoint
mapping actions to exit codes, the same shape as archive_commands.py.

Backup commands are routed through `BackupServices`
(redline_core.runtime.composition.build_backup_services()) -- a
composition tier scoped narrower than `PersistenceServices`: it resolves
config and the database *path* for `BackupManager` without ever opening a
live `Database` connection or calling `Database.init_schema()` against the
pipeline database, and without ever constructing or connecting a Resolve
adapter. See `redline_core.runtime.composition.BackupServices` for the
rationale (Mission 1A correction pass: Backup Manager must not share a
composition tier with a builder that mutates/initializes the live DB).

`restore-plan`/`restore` (Mission 1B-A1, HEALTHY_SOURCE only) are
registered onto this module's `backup` subparsers by
`cli.restore_commands.register_parser()`, but are dispatched separately by
`cli.main` through `RestoreServices`/`build_restore_services()` -- a
narrower composition tier than `BackupServices` -- never through this
module's own `run()`. See `cli/restore_commands.py` and
`docs/BACKUP_RECOVERY_ARCHITECTURE.md`.

`restore-recovery-plan` (Mission 1B-A2-1, read-only source classification +
recovery planning) is likewise registered onto this module's `backup`
subparsers by `cli.recovery_planning_commands.register_parser()`, and is
also dispatched separately by `cli.main` through `RestoreServices`. See
`cli/recovery_planning_commands.py`.

`restore-recovery` (Mission 1B-A2-3, DESTRUCTIVE recovery execution) is
likewise registered onto this module's `backup` subparsers by
`cli.recovery_execution_commands.register_parser()`, and is also
dispatched separately by `cli.main` through `RestoreServices`. Every
attempt builds its own fresh degraded-source capture; there is no
`--capture-id` anywhere. See `cli/recovery_execution_commands.py`.
"""
from __future__ import annotations

import argparse

from redline_core.backup.exceptions import BackupError
from redline_core.backup.models import BackupRecord, BackupResult, BackupVerificationResult
from redline_core.runtime.composition import BackupServices

from cli import recovery_execution_commands, recovery_planning_commands, restore_commands

_BANNER = "=" * 49


def _backup_result_to_dict(result: BackupResult) -> dict:
    return {
        "backup_id": result.backup_id,
        "backup_path": str(result.backup_path),
        "manifest_path": str(result.manifest_path),
        "manifest_sha256": result.manifest_sha256,
        "database_sha256": result.database_sha256,
        "database_size_bytes": result.database_size_bytes,
        "config_file_count": result.config_file_count,
        "total_bytes": result.total_bytes,
        "content_set_digest": result.content_set_digest,
        "created_at": result.created_at,
    }


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


def _run_backup_create(services: BackupServices, *, reason: str | None) -> dict:
    """Create, seal, independently verify, and atomically publish one new
    system-of-record backup -- the canonical create transport, calling
    `BackupManager.create_backup()` directly. Never contacts Resolve;
    never mutates the live database or active configuration."""
    manager = services.backup_manager
    try:
        result = manager.create_backup(reason=reason)
        return {"success": True, "backup": _backup_result_to_dict(result)}
    except BackupError as exc:
        return {"success": False, "error": str(exc)}


def _print_backup_create_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Backup Create".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Backup create failed: {result['error']}")
        return

    backup = result["backup"]
    print(f"Backup ID:        {backup['backup_id']}")
    print(f"Backup path:      {backup['backup_path']}")
    print(f"Manifest SHA-256: {backup['manifest_sha256']}")
    print(f"Database SHA-256: {backup['database_sha256']}")
    print(f"Database size:    {backup['database_size_bytes']} bytes")
    print(f"Config files:     {backup['config_file_count']}")
    print(f"Total size:       {backup['total_bytes']} bytes")
    print(f"Content digest:   {backup['content_set_digest']}")
    print(f"Created at:       {backup['created_at']}")


def _run_backup_list(services: BackupServices) -> dict:
    """List every sealed, complete backup -- read-only, no arguments,
    calling `BackupManager.list_backups()` directly."""
    manager = services.backup_manager
    records = manager.list_backups()
    return {"success": True, "backups": [_backup_record_to_dict(r) for r in records]}


def _print_backup_list_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Backups".center(49))
    print(_BANNER)
    print()

    backups = result["backups"]
    if not backups:
        print("No backups found.")
        return

    print(f"{'BACKUP ID':<32}{'CREATED AT':<22}{'DB BYTES':<12}{'CONFIG FILES':<14}REASON")
    for backup in backups:
        print(
            f"{backup['backup_id']:<32}{backup['created_at']:<22}"
            f"{backup['database_size_bytes']:<12}{backup['config_file_count']:<14}{backup['reason']}"
        )
    print()
    print(f"{len(backups)} backup(s).")


def _run_backup_verify(services: BackupServices, backup_id: str) -> dict:
    """Independently re-verify a sealed backup at rest -- read-only,
    calling `BackupManager.verify_backup()` directly. Never mutates the
    backup, the live database, or the active configuration."""
    manager = services.backup_manager
    try:
        result = manager.verify_backup(backup_id)
        return {"success": True, "verification": _verification_result_to_dict(result)}
    except BackupError as exc:
        return {"success": False, "error": str(exc)}


def _print_backup_verify_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Backup Verify".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Backup verify failed: {result['error']}")
        return

    verification = result["verification"]
    print(f"Backup ID:          {verification['backup_id']}")
    print(f"Backup path:        {verification['backup_path']}")
    print(f"Verified:           {'yes' if verification['verified'] else 'no'}")
    print(f"DB integrity_check: {verification['database_integrity_check']}")
    print(f"Database SHA-256:   {verification['database_sha256']}")
    print(f"Config files:       {verification['config_file_count']}")
    print(f"Total bytes:        {verification['total_bytes']}")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `backup` resource and its actions to the top-level
    subparsers. Canonical actions: `create`/`list`/`verify` (Mission 1A)
    only. No `restore` action is registered -- running `redline backup
    restore ...` produces argparse's own standard "invalid choice" error,
    the same clean, unambiguous failure mode as any other never-existed
    subcommand, exactly like `archive episode` after its Mission 15F
    retirement."""
    backup_parser = subparsers.add_parser(
        "backup", help="System-of-record backup and verification commands (Mission 1A)."
    )
    backup_subparsers = backup_parser.add_subparsers(dest="action", required=True)

    create_parser = backup_subparsers.add_parser(
        "create", help="Create, seal, and independently verify a new system-of-record backup."
    )
    create_parser.add_argument(
        "--reason", dest="reason", default=None, help="Optional operator-supplied reason for this backup."
    )

    backup_subparsers.add_parser("list", help="List every sealed, complete backup (read-only).")

    verify_parser = backup_subparsers.add_parser(
        "verify", help="Independently re-verify a sealed backup at rest (read-only)."
    )
    verify_parser.add_argument("backup_id", help="The backup_id to verify, from `backup list`.")

    restore_commands.register_parser(backup_subparsers)
    recovery_planning_commands.register_parser(backup_subparsers)
    recovery_execution_commands.register_parser(backup_subparsers)


def run(args: argparse.Namespace, services: BackupServices) -> int | None:
    """Dispatch a parsed `backup ...` command. Returns an exit code, or
    None if args.action isn't one this module handles."""
    if args.action == "create":
        result = _run_backup_create(services, reason=args.reason)
        _print_backup_create_result(result)
        return 0 if result["success"] else 1

    if args.action == "list":
        result = _run_backup_list(services)
        _print_backup_list_result(result)
        return 0 if result["success"] else 1

    if args.action == "verify":
        result = _run_backup_verify(services, args.backup_id)
        _print_backup_verify_result(result)
        return 0 if result["success"] else 1

    return None
