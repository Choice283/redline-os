"""Recovery-planning result/enum models (Mission 1B-A2-1: Source
Classification + Read-Only Recovery Planning).

Read-only classification and planning types only. Mirrors
``redline_core.restore.models``'s frozen/slotted dataclass convention and
``RestorePlanResult``'s own non-raising, "report why not" shape -- a
``RecoveryPlanResult`` is never raised as an exception, always returned.

DEGRADED_SOURCE/MISSING_SOURCE recovery EXECUTION (degraded-source capture,
disposition, staging, replacement, journaling of a recovery attempt) is
explicitly out of scope for Mission 1B-A2-1 and is not implemented here or
anywhere in this repository yet -- that is Mission 1B-A2-2/1B-A2-3, separate,
not-yet-authorized future work. Nothing in this module mutates anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceCondition(str, Enum):
    """Per-side (database or config) observed condition, independent of
    whether recovery from that condition is architecturally feasible --
    see ``RecoveryFeasibility``. Not an ordinal severity scale: ``MISSING``
    is not "worse" than ``DEGRADED``, they are simply different facts, and
    no code anywhere in this package compares these values for ordering.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    MISSING = "MISSING"


class RecoveryFeasibility(str, Enum):
    """Whether a future, not-yet-implemented Mission 1B-A2 recovery
    execution could architecturally proceed for this side, given its
    ``SourceCondition``. Deliberately a second, orthogonal axis:
    ``DEGRADED`` never by itself implies ``RECOVERABLE`` -- a
    ``DEGRADED_SOURCE`` object may still be ``RECOVERY_BLOCKED`` (e.g. an
    unsafe symlink/junction/reparse point, or a missing installation-level
    parent directory)."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """The side is HEALTHY; the ordinary, unmodified Mission 1A / Mission
    1B-A1 path applies, and recovery feasibility is moot."""

    RECOVERABLE = "RECOVERABLE"
    """The side is DEGRADED or MISSING, and a safe path into the existing
    (or a future, disposition-augmented) replacement machinery is believed
    to exist. This is a planning-time prediction only -- Mission 1B-A2-1
    implements no execution and performs no disposition."""

    RECOVERY_BLOCKED = "RECOVERY_BLOCKED"
    """The side is DEGRADED, and no repository-proven safe path exists --
    e.g. an unsafe filesystem object that must never be followed, or a
    structurally missing installation parent that would require
    disaster-bootstrap-style reconstruction, out of Mission 1B-A2's scope.
    Requires Founder/manual intervention, never an operator attestation."""


@dataclass(frozen=True, slots=True)
class SourceSideAssessment:
    """One side's (database or config) read-only classification result.
    Never raised as an exception.

    ``disposition_required``/``disposition_description`` are architectural
    *predictions* of what a future Mission 1B-A2-3 recovery execution would
    need to do -- Mission 1B-A2-1 performs no disposition of any kind."""

    condition: SourceCondition
    feasibility: RecoveryFeasibility
    blocking_reason: str | None
    capture_required: bool
    disposition_required: bool
    disposition_description: str | None
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryPlanResult:
    """Read-only result of a Mission 1B-A2-1 recovery-planning pass against
    one explicitly selected ``backup_id``. Never mutates anything: creates
    no backup, no degraded-source capture, no restore/recovery journal, no
    staging directory, and performs no rename/replace/delete/move-aside of
    any kind.

    ``would_proceed`` means "architecturally eligible for a future,
    not-yet-implemented Mission 1B-A2 recovery execution" -- it never means
    recovery was executed, and no recovery execution exists anywhere in
    this repository yet (Mission 1B-A2-2/1B-A2-3 remain unauthorized and
    unimplemented). Callers (CLI help text, docs) must preserve this
    distinction explicitly to avoid operator confusion.
    """

    backup_id: str
    target_verified: bool
    schema_compatible: bool
    database: SourceSideAssessment
    config: SourceSideAssessment
    sidecars_present: tuple[str, ...]
    quiescence_implication: str
    blocking_issues: tuple[str, ...]

    @property
    def would_proceed(self) -> bool:
        return not self.blocking_issues
