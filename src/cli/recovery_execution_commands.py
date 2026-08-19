"""Recovery execution CLI command (Mission 1B-A2-3) -- DESTRUCTIVE.

Registers `redline backup restore-recovery <backup_id>` onto the existing
`backup` resource's subparsers, mirroring `cli.restore_commands.
register_parser()`'s exact registration shape. Dispatched through the
same `RestoreServices` composition tier `restore-plan`/`restore`/
`restore-recovery-plan` already use.

Non-interactive. No `--capture-id`/`--confirm-capture-id` flag exists --
every attempt builds its own fresh, brand-new degraded-source capture; a
pre-existing capture is never an execution input. No blanket `--yes`.
"""
from __future__ import annotations

import argparse

from redline_core.backup.exceptions import BackupError
from redline_core.restore.capture_exceptions import CaptureError
from redline_core.restore.exceptions import RestoreError
from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.recovery_execution import RecoveryResult, execute_recovery
from redline_core.restore.recovery_models import RecoveryAuthorization
from redline_core.runtime.composition import RestoreServices

_BANNER = "=" * 61


def _recovery_result_to_dict(result: RecoveryResult) -> dict:
    return {
        "restore_id": result.restore_id,
        "backup_id": result.backup_id,
        "capture_id": result.capture_id,
        "capture_path": str(result.capture_path),
        "journal_dir": str(result.journal_dir),
        "disposed_targets": list(result.disposed_targets),
        "database_sha256": result.database_sha256,
        "database_size_bytes": result.database_size_bytes,
        "config_file_count": result.config_file_count,
        "superseded_config_path": str(result.superseded_config_path),
        "completed_at": result.completed_at,
    }


def _run_backup_restore_recovery(
    services: RestoreServices,
    backup_id: str,
    *,
    confirm_backup_id: str,
    attest_mcp_stopped: bool,
    attest_control_room_stopped: bool,
    attest_no_other_cli_operation: bool,
    attest_disposition_understood: bool,
    attest_no_automatic_rollback: bool,
    reason: str | None,
) -> dict:
    """DESTRUCTIVE Mission 1B-A2-3 recovery execution for `backup_id`.
    Requires the operator to repeat `backup_id` exactly via
    `--confirm-backup-id` and to explicitly attest every itemized
    quiescence and recovery-specific flag -- there is no blanket `--yes`
    shortcut anywhere in this command."""
    authorization = RecoveryAuthorization(
        confirm_backup_id=confirm_backup_id,
        quiescence=QuiescenceAttestations(
            mcp_stopped=attest_mcp_stopped,
            control_room_stopped=attest_control_room_stopped,
            no_other_cli_operation=attest_no_other_cli_operation,
        ),
        disposition_understood=attest_disposition_understood,
        no_automatic_rollback_understood=attest_no_automatic_rollback,
    )
    try:
        result = execute_recovery(
            backup_manager=services.backup_manager,
            db_path=services.restore_manager.db_path,
            config_dir=services.restore_manager.config_dir,
            backup_id=backup_id,
            authorization=authorization,
            reason=reason,
        )
        return {"success": True, "recovery": _recovery_result_to_dict(result)}
    except (RestoreError, CaptureError, BackupError, ValueError) as exc:
        return {"success": False, "error": str(exc), "error_type": type(exc).__name__}


def _print_backup_restore_recovery_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Recovery Execution (Mission 1B-A2-3, DESTRUCTIVE)".center(61))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Recovery execution failed [{result.get('error_type', 'RestoreError')}]: {result['error']}")
        return

    recovery = result["recovery"]
    print(f"Restore ID:              {recovery['restore_id']}")
    print(f"Backup ID recovered:     {recovery['backup_id']}")
    print(f"Fresh capture ID:        {recovery['capture_id']}")
    print(f"Fresh capture path:      {recovery['capture_path']}")
    print(f"Journal directory:       {recovery['journal_dir']}")
    print(f"Disposed target(s):      {recovery['disposed_targets'] or 'none'}")
    print(f"Database SHA-256:        {recovery['database_sha256']}")
    print(f"Database size:           {recovery['database_size_bytes']} bytes")
    print(f"Config files:            {recovery['config_file_count']}")
    print(f"Superseded config path:  {recovery['superseded_config_path']}")
    print(f"Completed at:            {recovery['completed_at']}")
    print()
    print("VERIFIED_SUCCESS.")


def register_parser(backup_subparsers: argparse._SubParsersAction) -> None:
    """Attach `restore-recovery` onto the *existing* `backup` resource's
    subparsers (called from `cli.backup_commands.register_parser()`) --
    not a separate top-level resource. `backup_id` is always a required
    positional argument. No `--capture-id`/`--confirm-capture-id` exists
    anywhere in this module."""
    recovery_parser = backup_subparsers.add_parser(
        "restore-recovery",
        help="DESTRUCTIVE (Mission 1B-A2-3): execute degraded/missing-source recovery for <backup_id> -- "
        "fresh capture, fresh reclassification, stability-checked disposition, and staged replacement.",
    )
    recovery_parser.add_argument("backup_id", help="The exact backup_id to recover to. Never accepts \"latest\".")
    recovery_parser.add_argument(
        "--confirm-backup-id",
        required=True,
        help="Repeat the exact backup_id being recovered, as an explicit destructive-action confirmation.",
    )
    recovery_parser.add_argument(
        "--attest-mcp-stopped", action="store_true", help="Itemized attestation: the MCP server is stopped. Required."
    )
    recovery_parser.add_argument(
        "--attest-control-room-stopped", action="store_true", help="Itemized attestation: Control Room is stopped. Required."
    )
    recovery_parser.add_argument(
        "--attest-no-other-cli-operation",
        action="store_true",
        help="Itemized attestation: no other Redline CLI operation is in flight. Required.",
    )
    recovery_parser.add_argument(
        "--attest-disposition-understood",
        action="store_true",
        help="Itemized attestation: the operator understands this attempt may move an existing live object "
        "aside (never delete it) before replacement. Required.",
    )
    recovery_parser.add_argument(
        "--attest-no-automatic-rollback",
        action="store_true",
        help="Itemized attestation: the operator understands there is no automatic rollback, retry, or "
        "resume on failure. Required.",
    )
    recovery_parser.add_argument(
        "--reason", dest="reason", default=None, help="Optional operator-supplied reason for this recovery attempt."
    )


def run(args: argparse.Namespace, services: RestoreServices) -> int | None:
    """Dispatch a parsed `backup restore-recovery ...` command. Returns an
    exit code, or None if `args.action` isn't one this module handles."""
    if args.action == "restore-recovery":
        result = _run_backup_restore_recovery(
            services,
            args.backup_id,
            confirm_backup_id=args.confirm_backup_id,
            attest_mcp_stopped=args.attest_mcp_stopped,
            attest_control_room_stopped=args.attest_control_room_stopped,
            attest_no_other_cli_operation=args.attest_no_other_cli_operation,
            attest_disposition_understood=args.attest_disposition_understood,
            attest_no_automatic_rollback=args.attest_no_automatic_rollback,
            reason=args.reason,
        )
        _print_backup_restore_recovery_result(result)
        return 0 if result["success"] else 1

    return None
