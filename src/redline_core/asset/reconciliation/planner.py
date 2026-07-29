"""planner.py -- Phase 3 Slice 9: final plan assembly.

Implements the approved "Phase 3 Slice 9 Implementation Contract --
planner.py, Revision 4 (final)". Consumes one already-validated
``ValidatedReconciliationInputs`` and one already-classified
``ClassificationState`` (Slice 8) for one reconciliation call, and produces
one immutable, public ``ReconciliationPlan``.

This module performs no filesystem, SQLite, network, or Resolve access, no
re-classification, no re-matching, and no re-validation. It never accesses
the clock -- ``created_at`` is always the caller-supplied parameter.

Per the approved contract, Slice 9 deliberately does not invent any domain
policy that has not been separately approved:

- ``ReconciliationPlanItem.findings`` and ``.actions`` are always ``()``
  for every item, for every classification, with no exceptions. No
  ``Finding`` object and no classification-to-action mapping exist anywhere
  in this repository yet (``findings.py``/``actions.py`` are future /
  re-evaluate, per the "Phase 3 Documentation Reconciliation Contract,
  Revision 2"); this module does not choose one on their behalf, not even
  for classifications where a mapping might look mechanical.
- ``PlanSummary.severities`` and ``PlanSummary.action_kinds`` are always
  empty mappings for the same reason -- no severity concept and no action
  concept exist in the current pipeline to aggregate.
- ``evidence_refs`` carries ``ClassificationDecision.evidence_facts``
  forward unchanged. Despite the field name (an already-committed Slice 1
  model field, unchanged here), these are bounded evidence *codes*, not IDs
  or object references -- the same convention ``classification.py``'s own
  docstring already documents for ``evidence_facts``.
- Plan item order is exactly ``classification_state.decisions`` order,
  index-for-index. No classification "rank" is invented or stored; the
  architecture document's "Determinism" section describes a rank-based
  ordering that exists nowhere as data in this repository -- that is a
  separately recorded documentation staleness (same disposition as the
  "Tagged Plan Subjects" note), not something this module works around.
- No ``ReconciliationPlanner`` class exists. ``plan_reconciliation`` is a
  bare function, matching every other Slice 5-8 module's convention
  (``build_indexes``, ``build_matching_state``, ``classify_reconciliation``).
- ``_limit_policy_fingerprint`` is private and local to this module, not
  added to ``canonical.py`` -- this module is its only caller today.
"""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime
import hashlib

from redline_core.asset.reconciliation.classification import ClassificationState
from redline_core.asset.reconciliation.enums import PrimaryClassification
from redline_core.asset.reconciliation.exceptions import ReconciliationInvariantError
from redline_core.asset.reconciliation.limits import ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import (
    RECONCILIATION_PLAN_SCHEMA_VERSION,
    PlanSummary,
    ReconciliationPlan,
    ReconciliationPlanItem,
)
from redline_core.asset.reconciliation.validation import ValidatedReconciliationInputs


_CONFLICT_CLASSIFICATIONS = frozenset(
    {
        PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT,
        PrimaryClassification.REGISTRY_IDENTITY_COLLISION,
        PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT,
        PrimaryClassification.CONTENT_CONFLICT,
        PrimaryClassification.DUPLICATE_PATH_CONFLICT,
        PrimaryClassification.AMBIGUOUS_MATCH,
        PrimaryClassification.UNKNOWN_AUTHORITATIVE_ASSET_ID,
        PrimaryClassification.LIFECYCLE_CONFLICT,
    }
)
"""The eight conflict-shaped classifications counted by
``PlanSummary.conflict_count`` (contract section 6, step 5)."""


def plan_reconciliation(
    inputs: ValidatedReconciliationInputs,
    classification_state: ClassificationState,
    *,
    created_at: datetime,
) -> ReconciliationPlan:
    """Assemble the final immutable plan for one already-classified reconciliation call.

    Pure function: does not mutate ``inputs``, ``classification_state``, or
    any nested object. Never accesses the clock -- ``created_at`` is always
    the caller-supplied parameter. Raises ``ReconciliationInvariantError``
    if a plan invariant fails to hold before returning (defensive only --
    unreachable by construction for valid input); raises nothing else for
    already-validated, already-classified input.
    """
    if type(inputs) is not ValidatedReconciliationInputs:
        raise ReconciliationInvariantError(
            "invalid planner input type",
            context={"field_name": "inputs"},
            reason_code="planner_invalid_input_type",
        )
    if type(classification_state) is not ClassificationState:
        raise ReconciliationInvariantError(
            "invalid planner input type",
            context={"field_name": "classification_state"},
            reason_code="planner_invalid_input_type",
        )

    items = _assemble_items(classification_state)
    evidence = _assemble_plan_evidence(items)
    summary = _assemble_summary(items)

    plan = ReconciliationPlan(
        plan_id=f"plan-{inputs.request.request_id}-{inputs.snapshot.snapshot_id}",
        schema_version=RECONCILIATION_PLAN_SCHEMA_VERSION,
        request_id=inputs.request.request_id,
        snapshot_id=inputs.snapshot.snapshot_id,
        registry_id=inputs.snapshot.registry_id,
        created_at=created_at,
        items=items,
        evidence=evidence,
        summary=summary,
        limit_policy_fingerprint=_limit_policy_fingerprint(inputs.request.limit_policy),
        approved_root_context=inputs.snapshot.approved_root_context,
        repository_revision=inputs.snapshot.repository_revision,
    )

    _verify_plan_invariants(plan, classification_state)
    return plan


# ---------------------------------------------------------------------------
# Item assembly (contract section 6, steps 2-3)
# ---------------------------------------------------------------------------


def _assemble_items(classification_state: ClassificationState) -> tuple[ReconciliationPlanItem, ...]:
    """Return one ``ReconciliationPlanItem`` per decision, in decision order.

    Item order is exactly ``classification_state.decisions`` order,
    index-for-index (Decision 1) -- never re-sorted, never re-derived from a
    classification "rank". Item IDs are assigned sequentially over that same
    order: ``item-000001``, ``item-000002``, ... (contract section 6, step 3).
    """
    return tuple(
        ReconciliationPlanItem(
            item_id=f"item-{index:06d}",
            subject=decision.subject,
            primary_classification=decision.primary_classification,
            findings=(),
            evidence_refs=decision.evidence_facts,
            actions=(),
            requires_review=decision.requires_review,
            proposal_blocked=decision.proposal_blocked,
        )
        for index, decision in enumerate(classification_state.decisions, start=1)
    )


def _assemble_plan_evidence(items: tuple[ReconciliationPlanItem, ...]) -> tuple[str, ...]:
    """Return the sorted, deduplicated union of every item's ``evidence_refs``."""
    facts: set[str] = set()
    for item in items:
        facts.update(item.evidence_refs)
    return tuple(sorted(facts))


# ---------------------------------------------------------------------------
# Summary assembly (contract section 6, step 5)
# ---------------------------------------------------------------------------


def _assemble_summary(items: tuple[ReconciliationPlanItem, ...]) -> PlanSummary:
    """Derive ``PlanSummary`` counts exclusively from ``items``.

    ``severities`` and ``action_kinds`` are always empty mappings -- no
    severity concept and no action-kind concept exist in the current
    pipeline for this module to aggregate (contract Decisions 3 and 5).
    """
    classifications: dict[str, int] = {}
    review_required_count = 0
    proposal_blocked_count = 0
    invalid_observation_count = 0
    conflict_count = 0
    unmatched_count = 0

    for item in items:
        key = item.primary_classification.value
        classifications[key] = classifications.get(key, 0) + 1
        if item.requires_review:
            review_required_count += 1
        if item.proposal_blocked:
            proposal_blocked_count += 1
        if item.primary_classification is PrimaryClassification.INVALID_OBSERVATION:
            invalid_observation_count += 1
        if item.primary_classification in _CONFLICT_CLASSIFICATIONS:
            conflict_count += 1
        if item.primary_classification is PrimaryClassification.NEW_UNREGISTERED_OBSERVATION:
            unmatched_count += 1

    return PlanSummary(
        classifications=classifications,
        severities={},
        action_kinds={},
        review_required_count=review_required_count,
        proposal_blocked_count=proposal_blocked_count,
        invalid_observation_count=invalid_observation_count,
        conflict_count=conflict_count,
        unmatched_count=unmatched_count,
    )


# ---------------------------------------------------------------------------
# limit_policy_fingerprint (contract section 5 -- private, local to this module)
# ---------------------------------------------------------------------------


def _limit_policy_fingerprint(policy: ReconciliationLimitPolicy) -> str:
    """Return a stable SHA-256 fingerprint over every limit field, sorted by name.

    Private to this module (contract Decision 6): ``planner.py`` is the only
    caller today, so this is not added to ``canonical.py``. Independent of
    field construction order and of ``PYTHONHASHSEED`` -- fields are sorted
    by name before hashing, never iterated via set/dict order.
    """
    parts = [f"{field.name}={getattr(policy, field.name)}" for field in sorted(fields(policy), key=lambda f: f.name)]
    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Plan invariants (contract section 8)
# ---------------------------------------------------------------------------


def _verify_plan_invariants(plan: ReconciliationPlan, classification_state: ClassificationState) -> None:
    """Defensively verify the plan invariants required by the contract.

    Every check here is true by construction given ``_assemble_items``,
    ``_assemble_plan_evidence``, and ``_assemble_summary`` above -- this
    mirrors ``classification.py``'s and ``matching.py``'s own "verify rather
    than assume" style for invariants that should never actually fail.
    """
    if len(plan.items) != len(classification_state.decisions):
        raise ReconciliationInvariantError(
            "plan item count does not match classification decision count",
            context={"count": len(plan.items)},
            reason_code="planner_item_count_mismatch",
        )

    for index, item in enumerate(plan.items, start=1):
        expected_item_id = f"item-{index:06d}"
        if item.item_id != expected_item_id:
            raise ReconciliationInvariantError(
                "plan item ID does not match the expected zero-padded sequential ID for its position",
                context={"index": index},
                reason_code="planner_unexpected_item_id",
            )

    evidence_set = set(plan.evidence)
    for item in plan.items:
        if item.findings != ():
            raise ReconciliationInvariantError(
                "plan item findings must be empty in Slice 9",
                reason_code="planner_findings_not_empty",
            )
        if item.actions != ():
            raise ReconciliationInvariantError(
                "plan item actions must be empty in Slice 9",
                reason_code="planner_actions_not_empty",
            )
        for fact in item.evidence_refs:
            if fact not in evidence_set:
                raise ReconciliationInvariantError(
                    "evidence_refs entry missing from plan-level evidence",
                    reason_code="planner_dangling_evidence_ref",
                )

    if plan.summary.severities:
        raise ReconciliationInvariantError(
            "plan summary severities must be empty in Slice 9",
            reason_code="planner_severities_not_empty",
        )
    if plan.summary.action_kinds:
        raise ReconciliationInvariantError(
            "plan summary action_kinds must be empty in Slice 9",
            reason_code="planner_action_kinds_not_empty",
        )
