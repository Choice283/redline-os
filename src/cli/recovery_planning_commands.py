"""Recovery-planning CLI command (Mission 1B-A2-1) -- read-only only.

Registers `redline backup restore-recovery-plan <backup_id>` onto the
existing `backup` resource's subparsers, mirroring `cli.restore_commands.
register_parser()`'s exact registration shape. Dispatched through the same
`RestoreServices` composition tier `restore-plan`/`restore` already use
(never opens a live `Database` connection, never constructs or connects a
Resolve adapter) -- this module only reads `services.backup_manager` and
the already-resolved `db_path`/`config_dir` off `services.restore_manager`;
it never constructs a new `RestoreManager`, never calls `.restore_plan()`
or `.restore()`, and exercises none of Mission 1B-A1's destructive path.

DEGRADED_SOURCE/MISSING_SOURCE recovery EXECUTION -- degraded-source
capture, disposition, staging, replacement, or any live mutation
whatsoever -- is explicitly out of scope for Mission 1B-A2-1 and is not
implemented here or anywhere in this repository yet. No `restore-recovery`
(destructive) action exists. This command only classifies and reports; see
`docs/BACKUP_RECOVERY_ARCHITECTURE.md` for the full Mission 1B-A2 scope
boundary and the accepted architecture this implementation follows.
"""
from __future__ import annotations

import argparse

from redline_core.restore.recovery_models import RecoveryPlanResult, SourceSideAssessment
from redline_core.restore.recovery_planning import build_recovery_plan
from redline_core.runtime.composition import RestoreServices

_BANNER = "=" * 61


def _assessment_to_dict(assessment: SourceSideAssessment) -> dict:
    return {
        "condition": assessment.condition.value,
        "feasibility": assessment.feasibility.value,
        "blocking_reason": assessment.blocking_reason,
        "capture_required": assessment.capture_required,
        "disposition_required": assessment.disposition_required,
        "disposition_description": assessment.disposition_description,
        "details": list(assessment.details),
    }


def _plan_result_to_dict(result: RecoveryPlanResult) -> dict:
    return {
        "backup_id": result.backup_id,
        "target_verified": result.target_verified,
        "schema_compatible": result.schema_compatible,
        "database": _assessment_to_dict(result.database),
        "config": _assessment_to_dict(result.config),
        "sidecars_present": list(result.sidecars_present),
        "quiescence_implication": result.quiescence_implication,
        "blocking_issues": list(result.blocking_issues),
        "would_proceed": result.would_proceed,
    }


def _run_backup_restore_recovery_plan(services: RestoreServices, backup_id: str) -> dict:
    """Read-only: classify the live database/config and report whether a
    future, not-yet-implemented Mission 1B-A2 recovery execution would be
    architecturally eligible to proceed for `backup_id`. Never mutates
    anything -- see `build_recovery_plan()` for the exact guarantee."""
    try:
        result = build_recovery_plan(
            backup_manager=services.backup_manager,
            db_path=services.restore_manager.db_path,
            config_dir=services.restore_manager.config_dir,
            backup_id=backup_id,
        )
        return {"success": True, "plan": _plan_result_to_dict(result)}
    except ValueError as exc:
        return {"success": False, "error": str(exc), "error_type": type(exc).__name__}


def _print_side_assessment(label: str, side: dict) -> None:
    print(f"{label} condition:              {side['condition']}")
    print(f"{label} recovery feasibility:    {side['feasibility']}")
    if side["blocking_reason"]:
        print(f"{label} blocking reason:        {side['blocking_reason']}")
    print(f"{label} capture would be required:     {side['capture_required']}")
    print(f"{label} disposition would be required: {side['disposition_required']}")
    if side["disposition_description"]:
        print(f"{label} disposition note:            {side['disposition_description']}")
    for detail in side["details"]:
        print(f"  - {detail}")


def _print_backup_restore_recovery_plan_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Recovery Plan (Mission 1B-A2-1, READ-ONLY)".center(61))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Recovery plan failed: {result['error']}")
        return

    plan = result["plan"]
    print(f"Backup ID:               {plan['backup_id']}")
    print(f"Target verified:         {'yes' if plan['target_verified'] else 'no'}")
    print(f"Schema compatible:       {'yes' if plan['schema_compatible'] else 'no'}")
    print()
    _print_side_assessment("Database", plan["database"])
    print()
    _print_side_assessment("Config", plan["config"])
    print()
    print(f"Quiescence implication:  {plan['quiescence_implication']}")
    if plan["sidecars_present"]:
        print(f"Sidecars present:        {plan['sidecars_present']}")
    print()
    print(
        "Would proceed (architecturally eligible for a FUTURE, not-yet-implemented recovery "
        "execution -- NOT an indication that recovery execution exists or was performed):"
    )
    print(f"  {'yes' if plan['would_proceed'] else 'NO'}")
    if plan["blocking_issues"]:
        print()
        print("Blocking issue(s):")
        for issue in plan["blocking_issues"]:
            print(f"  - {issue}")
    print()
    print(
        "Note: Mission 1B-A2-2 (degraded-source capture) and Mission 1B-A2-3 (recovery "
        "execution) are unauthorized and unimplemented. This command performs classification "
        "and prediction only; it never creates a capture, journal, or mutation of any kind."
    )


def register_parser(backup_subparsers: argparse._SubParsersAction) -> None:
    """Attach `restore-recovery-plan` onto the *existing* `backup`
    resource's subparsers (called from `cli.backup_commands.
    register_parser()`) -- not a separate top-level resource, and not a
    modification of the existing `restore-plan`/`restore` actions'
    registration or semantics. Read-only only: no destructive
    `restore-recovery` action is registered here or anywhere in this
    repository."""
    plan_parser = backup_subparsers.add_parser(
        "restore-recovery-plan",
        help="Read-only (Mission 1B-A2-1): classify live database/config health (HEALTHY/"
        "DEGRADED/MISSING) and report whether a future recovery execution would be "
        "architecturally eligible for <backup_id>. No recovery execution exists yet.",
    )
    plan_parser.add_argument("backup_id", help="The backup_id to plan a recovery for, from `backup list`.")


def run(args: argparse.Namespace, services: RestoreServices) -> int | None:
    """Dispatch a parsed `backup restore-recovery-plan ...` command.
    Returns an exit code, or None if `args.action` isn't one this module
    handles (in which case the caller tries another handler, mirroring
    `cli.restore_commands.run()`'s own convention)."""
    if args.action == "restore-recovery-plan":
        result = _run_backup_restore_recovery_plan(services, args.backup_id)
        _print_backup_restore_recovery_plan_result(result)
        return 0 if result["success"] and result["plan"]["would_proceed"] else 1

    return None
