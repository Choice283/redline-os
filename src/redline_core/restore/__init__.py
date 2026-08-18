"""Redline OS V2 Mission 1B-A1 (HEALTHY_SOURCE Restore) + Mission 1B-A2-1
(read-only source classification and recovery planning).

Mission 1B-A1 restores a previously-created, independently re-verified
Mission 1A backup (``redline_core.backup``) to the live system: the SQLite
database at ``REDLINE_DB_PATH`` and the active configuration directory at
``REDLINE_CONFIG_DIR``. HEALTHY_SOURCE only -- DEGRADED_SOURCE and
MISSING_SOURCE recovery *execution* is explicitly out of scope and not
implemented here; see ``docs/BACKUP_RECOVERY_ARCHITECTURE.md``.

Mission 1B-A1 public surface: ``RestoreManager.restore_plan()`` (read-only)
and ``RestoreManager.restore()`` (destructive, requires repeated backup_id
confirmation and itemized quiescence attestations). No MCP tool, no
Control Room mutation, and no automatic rollback/resume/repair exists
anywhere in this package.

Mission 1B-A2-1 adds ``build_recovery_plan()`` -- a strictly read-only
classification of the live database and required configuration
(``HEALTHY``/``DEGRADED``/``MISSING``, plus an independent
``RECOVERY_FEASIBILITY``: ``NOT_APPLICABLE``/``RECOVERABLE``/
``RECOVERY_BLOCKED``) and a prediction of what a future, not-yet-authorized
Mission 1B-A2-2 (degraded-source capture) / Mission 1B-A2-3 (recovery
execution) would need to do. It creates no capture, no journal, and
performs no disposition, staging, or replacement of any kind -- there is
still no degraded/missing-source recovery *execution* capability anywhere
in this repository.
"""
from __future__ import annotations

from redline_core.restore.journal import RestoreState
from redline_core.restore.manager import RestoreManager
from redline_core.restore.models import QuiescenceAttestations, RestorePlanResult, RestoreResult
from redline_core.restore.recovery_models import RecoveryFeasibility, RecoveryPlanResult, SourceCondition, SourceSideAssessment
from redline_core.restore.recovery_planning import build_recovery_plan

__all__ = [
    "RestoreManager",
    "RestorePlanResult",
    "RestoreResult",
    "QuiescenceAttestations",
    "RestoreState",
    "build_recovery_plan",
    "RecoveryPlanResult",
    "SourceSideAssessment",
    "SourceCondition",
    "RecoveryFeasibility",
]
