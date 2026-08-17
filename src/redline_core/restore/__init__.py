"""Redline OS V2 Mission 1B-A1: HEALTHY_SOURCE Restore.

Restores a previously-created, independently re-verified Mission 1A backup
(``redline_core.backup``) to the live system: the SQLite database at
``REDLINE_DB_PATH`` and the active configuration directory at
``REDLINE_CONFIG_DIR``. HEALTHY_SOURCE only -- DEGRADED_SOURCE and
MISSING_SOURCE recovery are explicitly out of scope and not implemented
here; see ``docs/BACKUP_RECOVERY_ARCHITECTURE.md``.

Public surface: ``RestoreManager.restore_plan()`` (read-only) and
``RestoreManager.restore()`` (destructive, requires repeated backup_id
confirmation and itemized quiescence attestations). No MCP tool, no
Control Room mutation, no DEGRADED/MISSING recovery, and no automatic
rollback/resume/repair exists anywhere in this package.
"""
from __future__ import annotations

from redline_core.restore.journal import RestoreState
from redline_core.restore.manager import RestoreManager
from redline_core.restore.models import QuiescenceAttestations, RestorePlanResult, RestoreResult

__all__ = [
    "RestoreManager",
    "RestorePlanResult",
    "RestoreResult",
    "QuiescenceAttestations",
    "RestoreState",
]
