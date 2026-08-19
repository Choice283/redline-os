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

from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.sidecar_classification import SidecarAssessment


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

    ``sidecars_present`` is preserved unchanged (Mission 1B-A2-1 original,
    ``Path.exists()``-based presence only via
    ``redline_core.restore.sidecar.find_present_sidecars()``) for backward
    compatibility with existing callers. ``sidecar_assessments`` (Mission
    1B-A2-3-Prep2, additive) is the authoritative, ``os.lstat()``-based
    classification of every recognized sidecar suffix
    (``redline_core.restore.sidecar_classification.classify_sidecars()``)
    -- MISSING/SAFE_REGULAR/WRONG_TYPE/UNSAFE -- always exactly
    ``len(SIDECAR_SUFFIXES)`` entries. A WRONG_TYPE or UNSAFE sidecar is
    reflected in ``blocking_issues`` (and therefore ``would_proceed``);
    MISSING and SAFE_REGULAR never block by themselves.
    """

    backup_id: str
    target_verified: bool
    schema_compatible: bool
    database: SourceSideAssessment
    config: SourceSideAssessment
    sidecars_present: tuple[str, ...]
    sidecar_assessments: tuple[SidecarAssessment, ...]
    quiescence_implication: str
    blocking_issues: tuple[str, ...]

    @property
    def would_proceed(self) -> bool:
        return not self.blocking_issues


@dataclass(frozen=True, slots=True)
class RecoveryAuthorization:
    """Mission 1B-A2-3: the escalated, itemized authorization required
    before ``recovery_execution.execute_recovery()`` may perform any live
    mutation. Mirrors ``QuiescenceAttestations``'s "itemized, no blanket
    --yes" convention exactly, plus two recovery-specific attestations
    neither Mission 1A backup nor Mission 1B-A1 restore requires: a
    recovery attempt performs a fresh degraded-source capture and
    (potentially) a disposition move-aside of an existing live object, and
    -- like Mission 1B-A1 -- never rolls back automatically on failure.

    Validation order (``recovery_execution.require_recovery_authorization()``):
    1. ``backup_id`` itself is validated (``validate_backup_id()``).
    2. ``confirm_backup_id`` must exactly equal ``backup_id``
       (``RecoveryConfirmationError`` otherwise).
    3. ``quiescence``'s existing three itemized attestations are checked
       via the locked, unmodified ``redline_core.restore.quiescence.
       require_attestations()``.
    4. The two recovery-specific attestations below are checked.

    ``RECOVERY_BLOCKED`` (the fresh, post-capture source/sidecar
    reclassification outcome) is absolutely non-overridable -- no field on
    this type, and no CLI flag anywhere in this repository, can bypass
    it."""

    confirm_backup_id: str
    quiescence: QuiescenceAttestations
    disposition_understood: bool
    no_automatic_rollback_understood: bool

    def missing_recovery_attestations(self) -> tuple[str, ...]:
        names = []
        if not self.disposition_understood:
            names.append("disposition_understood")
        if not self.no_automatic_rollback_understood:
            names.append("no_automatic_rollback_understood")
        return tuple(names)
