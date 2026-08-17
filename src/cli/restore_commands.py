"""Restore CLI commands (Mission 1B-A1) -- `_run_*`/`_print_*` handler pairs
returning `{"success": bool, ...}` dicts, the same shape as
`backup_commands.py`. Registers two actions onto the *existing* `backup`
resource's subparsers (called from `backup_commands.register_parser()`),
matching the locked CLI surface: `redline backup restore-plan <backup_id>`
(read-only) and `redline backup restore <backup_id>` (destructive).

Routed through `RestoreServices`
(`redline_core.runtime.composition.build_restore_services()`) -- a
composition tier scoped exactly like `BackupServices`: it never opens a
live `Database` connection, never calls `Database.init_schema()` against
the pipeline database, and never constructs or connects a Resolve adapter.

No `backup restore-degraded` action exists here or anywhere in this
repository -- DEGRADED_SOURCE/MISSING_SOURCE recovery is explicitly out of
Mission 1B-A1's scope. `redline backup restore --latest` also does not
exist: `backup_id` is always a required, explicit positional argument.
"""
from __future__ import annotations

import argparse

from redline_core.backup.exceptions import BackupError
from redline_core.restore.exceptions import RestoreError
from redline_core.restore.models import QuiescenceAttestations, RestorePlanResult, RestoreResult
from redline_core.runtime.composition import RestoreServices

_BANNER = "=" * 49


def _plan_result_to_dict(result: RestorePlanResult) -> dict:
    return {
        "backup_id": result.backup_id,
        "target_verified": result.target_verified,
        "schema_compatible": result.schema_compatible,
        "quiescence_probe_passed": result.quiescence_probe_passed,
        "sidecar_check_passed": result.sidecar_check_passed,
        "sidecars_present": list(result.sidecars_present),
        "blocking_issues": list(result.blocking_issues),
        "would_proceed": result.would_proceed,
    }


def _restore_result_to_dict(result: RestoreResult) -> dict:
    return {
        "restore_id": result.restore_id,
        "backup_id": result.backup_id,
        "pre_restore_backup_id": result.pre_restore_backup_id,
        "journal_dir": str(result.journal_dir),
        "database_sha256": result.database_sha256,
        "database_size_bytes": result.database_size_bytes,
        "config_file_count": result.config_file_count,
        "superseded_config_path": str(result.superseded_config_path),
        "completed_at": result.completed_at,
    }


def _run_backup_restore_plan(services: RestoreServices, backup_id: str) -> dict:
    """Read-only preview of whether `restore(backup_id)` would currently
    be able to proceed. Never mutates anything."""
    try:
        result = services.restore_manager.restore_plan(backup_id)
        return {"success": True, "plan": _plan_result_to_dict(result)}
    except (RestoreError, BackupError, ValueError) as exc:
        return {"success": False, "error": str(exc), "error_type": type(exc).__name__}


def _print_backup_restore_plan_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Restore Plan (Mission 1B-A1)".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Restore plan failed: {result['error']}")
        return

    plan = result["plan"]
    print(f"Backup ID:            {plan['backup_id']}")
    print(f"Target verified:      {'yes' if plan['target_verified'] else 'no'}")
    print(f"Schema compatible:    {'yes' if plan['schema_compatible'] else 'no'}")
    print(f"Quiescence probe:     {'passed' if plan['quiescence_probe_passed'] else 'failed'}")
    print(f"Sidecar check:        {'passed' if plan['sidecar_check_passed'] else 'failed'}")
    if plan["sidecars_present"]:
        print(f"Sidecars present:     {plan['sidecars_present']}")
    print(f"Would proceed:        {'yes' if plan['would_proceed'] else 'NO'}")
    if plan["blocking_issues"]:
        print()
        print("Blocking issue(s):")
        for issue in plan["blocking_issues"]:
            print(f"  - {issue}")


def _run_backup_restore(
    services: RestoreServices,
    backup_id: str,
    *,
    confirm_backup_id: str,
    attest_mcp_stopped: bool,
    attest_control_room_stopped: bool,
    attest_no_other_cli_operation: bool,
    reason: str | None,
) -> dict:
    """Destructive HEALTHY_SOURCE restore of `backup_id`. Requires the
    operator to repeat `backup_id` exactly via `--confirm-backup-id` and to
    explicitly set all three itemized quiescence attestation flags -- there
    is no single blanket "--yes" shortcut."""
    attestations = QuiescenceAttestations(
        mcp_stopped=attest_mcp_stopped,
        control_room_stopped=attest_control_room_stopped,
        no_other_cli_operation=attest_no_other_cli_operation,
    )
    try:
        result = services.restore_manager.restore(
            backup_id,
            confirm_backup_id=confirm_backup_id,
            attestations=attestations,
            reason=reason,
        )
        return {"success": True, "restore": _restore_result_to_dict(result)}
    except (RestoreError, BackupError, ValueError) as exc:
        return {"success": False, "error": str(exc), "error_type": type(exc).__name__}


def _print_backup_restore_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Restore (Mission 1B-A1)".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Restore failed [{result.get('error_type', 'RestoreError')}]: {result['error']}")
        return

    restore = result["restore"]
    print(f"Restore ID:              {restore['restore_id']}")
    print(f"Backup ID restored:      {restore['backup_id']}")
    print(f"Pre-restore backup ID:   {restore['pre_restore_backup_id']}")
    print(f"Journal directory:       {restore['journal_dir']}")
    print(f"Database SHA-256:        {restore['database_sha256']}")
    print(f"Database size:           {restore['database_size_bytes']} bytes")
    print(f"Config files:            {restore['config_file_count']}")
    print(f"Superseded config path:  {restore['superseded_config_path']}")
    print(f"Completed at:            {restore['completed_at']}")
    print()
    print("VERIFIED_SUCCESS.")


def register_parser(backup_subparsers: argparse._SubParsersAction) -> None:
    """Attach `restore-plan` and `restore` onto the *existing* `backup`
    resource's subparsers (called from
    `cli.backup_commands.register_parser()`) -- not a separate top-level
    resource. `backup_id` is always a required positional argument on
    both; there is no `--latest` option anywhere in this module."""
    plan_parser = backup_subparsers.add_parser(
        "restore-plan",
        help="Read-only: report whether restoring <backup_id> would currently be able to proceed (Mission 1B-A1).",
    )
    plan_parser.add_argument("backup_id", help="The backup_id to plan a restore for, from `backup list`.")

    restore_parser = backup_subparsers.add_parser(
        "restore",
        help="DESTRUCTIVE: restore <backup_id> to the live database and configuration (Mission 1B-A1, "
        "HEALTHY_SOURCE only).",
    )
    restore_parser.add_argument("backup_id", help="The exact backup_id to restore. Never accepts \"latest\".")
    restore_parser.add_argument(
        "--confirm-backup-id",
        required=True,
        help="Repeat the exact backup_id being restored, as an explicit destructive-action confirmation.",
    )
    restore_parser.add_argument(
        "--attest-mcp-stopped",
        action="store_true",
        help="Itemized attestation: the MCP server is stopped. Required.",
    )
    restore_parser.add_argument(
        "--attest-control-room-stopped",
        action="store_true",
        help="Itemized attestation: Control Room is stopped. Required.",
    )
    restore_parser.add_argument(
        "--attest-no-other-cli-operation",
        action="store_true",
        help="Itemized attestation: no other Redline CLI operation is in flight. Required.",
    )
    restore_parser.add_argument(
        "--reason", dest="reason", default=None, help="Optional operator-supplied reason for this restore."
    )


def run(args: argparse.Namespace, services: RestoreServices) -> int | None:
    """Dispatch a parsed `backup restore-plan ...` / `backup restore ...`
    command. Returns an exit code, or None if args.action isn't one this
    module handles."""
    if args.action == "restore-plan":
        result = _run_backup_restore_plan(services, args.backup_id)
        _print_backup_restore_plan_result(result)
        return 0 if result["success"] and result["plan"]["would_proceed"] else 1

    if args.action == "restore":
        result = _run_backup_restore(
            services,
            args.backup_id,
            confirm_backup_id=args.confirm_backup_id,
            attest_mcp_stopped=args.attest_mcp_stopped,
            attest_control_room_stopped=args.attest_control_room_stopped,
            attest_no_other_cli_operation=args.attest_no_other_cli_operation,
            reason=args.reason,
        )
        _print_backup_restore_result(result)
        return 0 if result["success"] else 1

    return None
