"""Restore/Recovery MCP tools — thin, read-only wrappers around
`RestoreManager.restore_plan()` and `build_recovery_plan()`.

Mission 1B-B: exposes only the two read-only planning capabilities.
`RestoreManager.restore()` (destructive) and `execute_recovery()`
(destructive) are never imported, called, or reachable from this module —
see `docs/BACKUP_RECOVERY_ARCHITECTURE.md`'s Mission 1B-B section for why
an MCP-originated call can never truthfully satisfy the
`QuiescenceAttestations`/`RecoveryAuthorization` ceremony those two methods
require (both need `attest_mcp_stopped`, which no call arriving through a
running MCP server can ever truthfully assert).
"""
from __future__ import annotations

from redline_core.restore.manager import RestoreManager
from redline_core.restore.models import RestorePlanResult
from redline_core.restore.recovery_models import RecoveryPlanResult, SourceSideAssessment
from redline_core.restore.recovery_planning import build_recovery_plan
from redline_core.restore.sidecar_classification import SidecarAssessment


def _restore_plan_result_to_dict(result: RestorePlanResult) -> dict:
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


def _source_side_assessment_to_dict(assessment: SourceSideAssessment) -> dict:
    return {
        "condition": assessment.condition.value,
        "feasibility": assessment.feasibility.value,
        "blocking_reason": assessment.blocking_reason,
        "capture_required": assessment.capture_required,
        "disposition_required": assessment.disposition_required,
        "disposition_description": assessment.disposition_description,
        "details": list(assessment.details),
    }


def _sidecar_assessment_to_dict(assessment: SidecarAssessment) -> dict:
    return {
        "suffix": assessment.suffix,
        "path": assessment.path,
        "condition": assessment.condition.value,
        "detail": assessment.detail,
    }


def _recovery_plan_result_to_dict(result: RecoveryPlanResult) -> dict:
    return {
        "backup_id": result.backup_id,
        "target_verified": result.target_verified,
        "schema_compatible": result.schema_compatible,
        "database": _source_side_assessment_to_dict(result.database),
        "config": _source_side_assessment_to_dict(result.config),
        "sidecars_present": list(result.sidecars_present),
        "sidecar_assessments": [_sidecar_assessment_to_dict(a) for a in result.sidecar_assessments],
        "quiescence_implication": result.quiescence_implication,
        "blocking_issues": list(result.blocking_issues),
        "would_proceed": result.would_proceed,
    }


def _restore_plan(manager: RestoreManager, backup_id: str) -> dict:
    try:
        result = manager.restore_plan(backup_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "plan": _restore_plan_result_to_dict(result)}


def _restore_recovery_plan(manager: RestoreManager, backup_id: str) -> dict:
    try:
        result = build_recovery_plan(
            backup_manager=manager.backup_manager,
            db_path=manager.db_path,
            config_dir=manager.config_dir,
            backup_id=backup_id,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "plan": _recovery_plan_result_to_dict(result)}


def register(mcp, restore_ctx) -> None:
    """Attach Restore/Recovery read-only planning tools to `mcp`, bound to
    `restore_ctx.restore_manager`. `RestoreManager.restore()` and
    `execute_recovery()` are deliberately never registered here."""

    @mcp.tool()
    def restore_plan(backup_id: str) -> dict:
        """Read-only preview of whether restoring backup_id would currently be able to
        proceed (HEALTHY_SOURCE only). Creates no pre-restore safety backup, stages
        nothing, replaces nothing."""
        return _restore_plan(restore_ctx.restore_manager, backup_id)

    @mcp.tool()
    def restore_recovery_plan(backup_id: str) -> dict:
        """Read-only classification of whether a DEGRADED_SOURCE/MISSING_SOURCE recovery
        against backup_id would be architecturally eligible to proceed. Creates no
        degraded-source capture, no journal, and performs no disposition."""
        return _restore_recovery_plan(restore_ctx.restore_manager, backup_id)
