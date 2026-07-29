"""serialization.py -- Phase 3 Slice 10: public-safe plan serialization.

Implements the approved "Phase 3 Slice 10 Implementation Contract --
serialization.py, Revision 3 (final)". Converts one already-built,
already-safe ``ReconciliationPlan`` (Slice 9 output) into a stable,
deterministic, JSON-compatible public dictionary, enforcing a maximum
serialized-size limit.

This module performs no filesystem, SQLite, network, or Resolve access, no
re-classification, no re-matching, no re-validation, and no clock access.
It is a pure leaf: it imports ``models.py``/``enums.py``/``limits.py``/
``exceptions.py`` and is imported by nothing upstream.

Per the approved contract, Slice 10 deliberately does not invent any domain
policy that has not been separately approved:

- Redaction is a **structural allowlist**, not a per-fact visibility
  evaluation. ``serialize_public_plan`` walks the known, fixed set of
  fields on ``ReconciliationPlan``/``ReconciliationPlanItem``/
  ``PlanSummary``/``PlanSubject`` explicitly, field by field, and emits
  exactly those fields -- never ``dataclasses.asdict()``, ``vars()``,
  ``__dict__``, or any other reflection-based dump. A future field added
  to a domain model does not automatically appear in public output,
  because this function does not discover fields dynamically.
  ``PublicVisibility`` and the other Slice-1 evidence-model enums remain
  unused by this module, exactly as they are unused by every module built
  so far -- no visibility classification is invented or inferred anywhere
  in this file.
- ``RegistryRecordSubject.record_id`` is never emitted, whether it is
  populated or ``None``. ``asset_id`` is the stable public business
  identifier; ``record_id`` is an optional internal row reference that the
  approved contract deliberately excludes from the public DTO.
- No ``PublicPlanSerializer`` class exists. ``serialize_public_plan`` is a
  bare function, matching every other Slice 5-9 module's convention
  (``build_indexes``, ``build_matching_state``, ``classify_reconciliation``,
  ``plan_reconciliation``).
- This module does not re-run any of ``planner.py``'s invariant checks
  against ``plan``, does not recompute ``PlanSummary`` counts, and does
  not re-derive ``plan.evidence`` -- it projects the already-valid
  structure it is given. The one exception is an output-integrity check
  (not a domain revalidation) confirming that every emitted
  ``evidence_ref`` in the DTO this function itself builds appears in the
  DTO's own top-level ``evidence`` list -- a check against this function's
  own output, not against ``plan``.
"""
from __future__ import annotations

import json
from typing import Any

from redline_core.asset.reconciliation.exceptions import (
    ReconciliationInvariantError,
    ReconciliationLimitExceededError,
)
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS, ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import ReconciliationPlan, ReconciliationPlanItem, PlanSummary
from redline_core.asset.reconciliation.subjects import (
    MixedConflictSubject,
    ObservationGroupSubject,
    ObservationSubject,
    RegistryRecordGroupSubject,
    RegistryRecordSubject,
)


def serialize_public_plan(
    plan: ReconciliationPlan,
    *,
    limit_policy: ReconciliationLimitPolicy = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Return a stable, deterministic, size-guarded public dict for ``plan``.

    Pure function: does not mutate ``plan``, ``limit_policy``, or any
    nested object. Never accesses the clock. Does not re-run any
    ``planner.py`` invariant check or recompute plan state -- it projects
    the already-valid structure it is given. Raises
    ``ReconciliationInvariantError`` for invalid input types (defensive
    only) and ``ReconciliationLimitExceededError`` if the serialized
    output exceeds ``limit_policy.max_serialized_public_plan_bytes``.
    """
    if type(plan) is not ReconciliationPlan:
        raise ReconciliationInvariantError(
            "invalid serializer input type",
            context={"field_name": "plan"},
            reason_code="serialization_invalid_input_type",
        )
    if type(limit_policy) is not ReconciliationLimitPolicy:
        raise ReconciliationInvariantError(
            "invalid serializer input type",
            context={"field_name": "limit_policy"},
            reason_code="serialization_invalid_input_type",
        )

    result = _serialize_plan(plan)
    _verify_output_invariants(result)

    canonical_bytes = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(canonical_bytes) > limit_policy.max_serialized_public_plan_bytes:
        raise ReconciliationLimitExceededError(
            "serialized public plan exceeds the configured size limit",
            context={
                "limit_name": "max_serialized_public_plan_bytes",
                "limit_value": limit_policy.max_serialized_public_plan_bytes,
            },
        )

    return result


# ---------------------------------------------------------------------------
# Explicit field-by-field DTO mapping (contract section 5)
# ---------------------------------------------------------------------------


def _serialize_plan(plan: ReconciliationPlan) -> dict[str, Any]:
    """Return the top-level public dict for ``plan``, per the approved shape."""
    return {
        "approved_root_context": plan.approved_root_context,
        "created_at": plan.created_at.isoformat(),
        "evidence": list(plan.evidence),
        "items": [_serialize_item(item) for item in plan.items],
        "limit_policy_fingerprint": plan.limit_policy_fingerprint,
        "plan_id": plan.plan_id,
        "registry_id": plan.registry_id,
        "repository_revision": plan.repository_revision,
        "request_id": plan.request_id,
        "schema_version": plan.schema_version,
        "snapshot_id": plan.snapshot_id,
        "summary": _serialize_summary(plan.summary),
    }


def _serialize_item(item: ReconciliationPlanItem) -> dict[str, Any]:
    """Return the public dict for one ``ReconciliationPlanItem``.

    ``plan.items`` order is preserved exactly by the caller
    (``_serialize_plan``'s list comprehension) -- this function never
    sorts or ranks items.
    """
    return {
        "actions": list(item.actions),
        "evidence_refs": list(item.evidence_refs),
        "findings": list(item.findings),
        "item_id": item.item_id,
        "primary_classification": item.primary_classification.value,
        "proposal_blocked": item.proposal_blocked,
        "requires_review": item.requires_review,
        "subject": _serialize_subject(item.subject),
    }


def _serialize_subject(subject: Any) -> dict[str, Any]:
    """Return the public dict for one ``PlanSubject`` variant.

    ``subject_type`` tags reuse the same tag strings each variant's own
    ``canonical_key()`` already emits (``subjects.py``) -- existing
    vocabulary, not invented here.
    """
    if type(subject) is RegistryRecordSubject:
        return {
            "asset_id": subject.asset_id,
            "subject_type": "registry_record",
        }
    if type(subject) is ObservationSubject:
        return {
            "observation_id": subject.observation_id,
            "subject_type": "observation",
        }
    if type(subject) is RegistryRecordGroupSubject:
        return {
            "asset_ids": list(subject.asset_ids),
            "subject_type": "registry_record_group",
        }
    if type(subject) is ObservationGroupSubject:
        return {
            "observation_ids": list(subject.observation_ids),
            "subject_type": "observation_group",
        }
    if type(subject) is MixedConflictSubject:
        return {
            "asset_ids": list(subject.asset_ids),
            "conflict_kind": subject.conflict_kind.value,
            "observation_ids": list(subject.observation_ids),
            "subject_type": "mixed_conflict",
        }
    raise ReconciliationInvariantError(
        "unrecognized plan subject variant",
        context={"field_name": "subject"},
        reason_code="serialization_invalid_input_type",
    )


def _serialize_summary(summary: PlanSummary) -> dict[str, Any]:
    """Return the public dict for one ``PlanSummary``. Never recomputes values."""
    return {
        "action_kinds": dict(summary.action_kinds),
        "classifications": dict(summary.classifications),
        "conflict_count": summary.conflict_count,
        "invalid_observation_count": summary.invalid_observation_count,
        "proposal_blocked_count": summary.proposal_blocked_count,
        "review_required_count": summary.review_required_count,
        "severities": dict(summary.severities),
        "unmatched_count": summary.unmatched_count,
    }


# ---------------------------------------------------------------------------
# Output-integrity check (contract section 7, invariant 4) -- not a
# re-run of planner.py's domain validation; this checks the DTO this
# function itself just built, not ``plan``.
# ---------------------------------------------------------------------------


def _verify_output_invariants(result: dict[str, Any]) -> None:
    """Verify the just-built public DTO is internally consistent.

    Confirms every emitted ``evidence_refs`` entry on every serialized item
    appears in the serialized top-level ``evidence`` list. This is an
    output-integrity check against ``result`` (the dict just built), not a
    re-run of ``planner.py``'s ``_verify_plan_invariants`` against ``plan``
    -- the underlying fact is already guaranteed by construction (both
    lists are projected from the same already-invariant-checked ``plan``),
    but the check is asserted defensively before returning, matching the
    "verify rather than assume" style already used by
    ``classification.py``/``matching.py``/``planner.py``.
    """
    evidence_set = set(result["evidence"])
    for item in result["items"]:
        for evidence_ref in item["evidence_refs"]:
            if evidence_ref not in evidence_set:
                raise ReconciliationInvariantError(
                    "serialized evidence_refs entry missing from serialized evidence",
                    reason_code="serialization_dangling_evidence_ref",
                )
