"""Tests for Phase 3 Slice 9 plan assembly (``planner.py``).

Implements the exhaustive test matrix from the approved "Phase 3 Slice 9
Implementation Contract -- planner.py, Revision 4 (final)", section 11
(tests 1-32). Each test below is numbered in its docstring to match that
contract for traceability.

Tests for the four currently non-executable ``PrimaryClassification``
members (``REGISTRY_SNAPSHOT_INVALID``, ``INVALID_OBSERVATION``,
``UNSUPPORTED_OBSERVATION``, ``DIAGNOSTIC_ONLY``) validate planner
pass-through behavior only, via hand-built ``ClassificationDecision``
instances -- they do not change or imply any change to Slice 8
classification reachability. ``classify_reconciliation`` still never
produces these members.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import subprocess
import sys

import pytest

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation import planner as planner_module
from redline_core.asset.reconciliation.classification import (
    ClassificationDecision,
    ClassificationState,
    classify_reconciliation,
)
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    ObservationKind,
    PrimaryClassification,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.exceptions import ReconciliationInvariantError
from redline_core.asset.reconciliation.indexes import build_indexes
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS, ReconciliationLimitPolicy
from redline_core.asset.reconciliation.matching import build_matching_state
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ObservationRootScope,
    ObservationScope,
    ReconciliationRequest,
    RegistryIdentityEvidence,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.planner import plan_reconciliation
from redline_core.asset.reconciliation.scope import ObservabilityDecision
from redline_core.asset.reconciliation.subjects import RegistryRecordSubject
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
PLAN_CREATED_AT = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixture builders (mirrors tests/unit/asset/reconciliation/test_classification.py)
# ---------------------------------------------------------------------------


def make_record(
    asset_id: str,
    *,
    normalized_path: str | None = None,
    lifecycle: AssetLifecycle = AssetLifecycle.ACTIVE,
    availability: AssetAvailability = AssetAvailability.AVAILABLE,
    verification: AssetVerificationState = AssetVerificationState.VERIFIED,
    file_size_bytes: int | None = 1024,
    file_modified_at: datetime | None = NOW,
) -> AssetRegistryRecord:
    if availability is not AssetAvailability.AVAILABLE:
        file_size_bytes = None
        file_modified_at = None
    last_verified_at = None if verification is AssetVerificationState.UNVERIFIED else NOW
    return AssetRegistryRecord(
        record_id=1,
        asset_id=asset_id,
        declared_path=f"assets/{asset_id}.mov",
        resolved_path=f"C:/assets/{asset_id}.mov" if normalized_path is not None else None,
        normalized_resolved_path=normalized_path,
        approved_root_id="assets_path",
        lifecycle=lifecycle,
        availability=availability,
        verification=verification,
        file_size_bytes=file_size_bytes,
        file_modified_at=file_modified_at,
        last_verified_at=last_verified_at,
        created_at=NOW,
        updated_at=NOW,
        source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail=None,
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_evidence(
    asset_id: str,
    *,
    algorithm: str | None = "sha256",
    normalized_value: str,
    normalization_format: str = "lowercase_hex",
    scope_id: str | None = None,
    source_id: str = "registry-scan",
) -> RegistryIdentityEvidence:
    from redline_core.asset.reconciliation.enums import EvidenceKind

    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=EvidenceKind.FULL_CONTENT_HASH,
        algorithm=algorithm,
        normalized_value=normalized_value,
        normalization_format=normalization_format,
        scope_id=scope_id,
        source_id=source_id,
        observed_at=NOW,
    )


def make_observation(
    observation_id: str,
    *,
    source_id: str = "scan-a",
    normalized_path: str | None = None,
    claimed_asset_id: str | None = None,
    availability: AssetAvailability = AssetAvailability.AVAILABLE,
    verification: AssetVerificationState = AssetVerificationState.VERIFIED,
    file_size_bytes: int | None = 1024,
    file_modified_at: datetime | None = NOW,
    content_hashes: tuple[tuple[str, str], ...] = (),
) -> AssetObservation:
    return AssetObservation(
        observation_id=observation_id,
        source_id=source_id,
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=availability,
        verification=verification,
        normalized_resolved_path=normalized_path,
        claimed_asset_id=claimed_asset_id,
        file_size_bytes=file_size_bytes if availability is AssetAvailability.AVAILABLE else None,
        file_modified_at=file_modified_at if availability is AssetAvailability.AVAILABLE else None,
        content_hashes=content_hashes,
    )


def make_scope() -> ObservationScope:
    return ObservationScope(
        scope_id="scope-1",
        observed_at=NOW,
        source_id="scan-a",
        roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
    )


def make_observability(asset_id: str, *, expected_observable: bool) -> ObservabilityDecision:
    return ObservabilityDecision(
        asset_id=asset_id,
        applicable_channels=("path",) if expected_observable else (),
        complete_channels=("path",) if expected_observable else (),
        blocked_channels=(),
        exclusion_reasons=(),
        access_failure_reasons=(),
        expected_observable=expected_observable,
        missing_eligible=expected_observable,
        evidence_facts=(),
    )


def make_request_and_snapshot(
    *,
    records: tuple[AssetRegistryRecord, ...] = (),
    identity_evidence: tuple[RegistryIdentityEvidence, ...] = (),
    observations: tuple[AssetObservation, ...] = (),
    trusted_asset_id_source_ids: tuple[str, ...] = (),
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
    request_id: str = "req-1",
    snapshot_id: str = "snap-1",
    limit_policy: ReconciliationLimitPolicy = DEFAULT_LIMITS,
) -> tuple[ReconciliationRequest, RegistrySnapshot]:
    snapshot = RegistrySnapshot(
        records=records,
        identity_evidence=identity_evidence,
        schema_version="1",
        snapshot_id=snapshot_id,
        snapshot_created_at=NOW,
        registry_id="reg-1",
        approved_root_context="assets_path",
    )
    request = ReconciliationRequest(
        request_id=request_id,
        schema_version="1",
        created_at=NOW,
        observations=observations,
        scopes=(make_scope(),),
        trusted_asset_id_source_ids=trusted_asset_id_source_ids,
        asset_id_trust_policy=asset_id_trust_policy,
        limit_policy=limit_policy,
    )
    return request, snapshot


def run_planner(
    *,
    records: tuple[AssetRegistryRecord, ...] = (),
    identity_evidence: tuple[RegistryIdentityEvidence, ...] = (),
    observations: tuple[AssetObservation, ...] = (),
    trusted_asset_id_source_ids: tuple[str, ...] = (),
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
    observability: dict[str, bool] | None = None,
    request_id: str = "req-1",
    snapshot_id: str = "snap-1",
    limit_policy: ReconciliationLimitPolicy = DEFAULT_LIMITS,
    created_at: datetime = PLAN_CREATED_AT,
):
    """Drive the full pipeline end to end: validate -> index -> match ->
    classify -> plan. Returns (plan, inputs, classification_state)."""
    request, snapshot = make_request_and_snapshot(
        records=records,
        identity_evidence=identity_evidence,
        observations=observations,
        trusted_asset_id_source_ids=trusted_asset_id_source_ids,
        asset_id_trust_policy=asset_id_trust_policy,
        request_id=request_id,
        snapshot_id=snapshot_id,
        limit_policy=limit_policy,
    )
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    matching_state = build_matching_state(inputs, indexes)

    observability = observability or {}
    observability_by_asset_id = {
        asset_id: make_observability(asset_id, expected_observable=observability.get(asset_id, True))
        for asset_id in indexes.registry.asset_id_to_record
        if asset_id not in matching_state.consumed.asset_ids
    }

    state = classify_reconciliation(inputs, indexes, matching_state, observability_by_asset_id)
    plan = plan_reconciliation(inputs, state, created_at=created_at)
    return plan, inputs, state


def only(plan) -> object:
    assert len(plan.items) == 1, plan.items
    return plan.items[0]


# ---------------------------------------------------------------------------
# Tests 1-8: single-decision pass-through per classification
# ---------------------------------------------------------------------------


def test_01_unchanged_decision_produces_empty_actions_and_findings():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    plan, _, _ = run_planner(records=(record,), observations=(observation,))

    item = only(plan)
    assert item.primary_classification is PrimaryClassification.UNCHANGED
    assert item.actions == ()
    assert item.findings == ()
    assert item.requires_review is False


def test_02_metadata_drift_decision():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov", file_modified_at=NOW)
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", file_modified_at=NOW.replace(hour=13)
    )
    plan, _, state = run_planner(records=(record,), observations=(observation,))

    item = only(plan)
    decision = state.decisions[0]
    assert item.primary_classification is PrimaryClassification.METADATA_DRIFT
    assert item.actions == ()
    assert item.findings == ()
    assert item.evidence_refs == decision.evidence_facts


def test_03_path_changed_decision():
    record = make_record("A-1", normalized_path="c:/assets/old.mov")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/new.mov", content_hashes=(("sha256", "digest-1"),)
    )
    plan, _, _ = run_planner(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    item = only(plan)
    assert item.primary_classification is PrimaryClassification.PATH_CHANGED
    assert item.actions == ()
    assert item.requires_review is True


def test_04_availability_changed_decision():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov", availability=AssetAvailability.AVAILABLE)
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", availability=AssetAvailability.NON_FILE
    )
    plan, _, _ = run_planner(records=(record,), observations=(observation,))

    item = only(plan)
    assert item.primary_classification is PrimaryClassification.AVAILABILITY_CHANGED
    assert item.actions == ()


def test_05_record_not_observed_decision():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    plan, _, _ = run_planner(records=(record,), observability={"A-1": True})

    item = only(plan)
    assert item.primary_classification is PrimaryClassification.RECORD_NOT_OBSERVED
    assert item.actions == ()
    assert item.requires_review is False


def test_06_new_unregistered_observation_decision():
    observation = make_observation("obs-1", normalized_path="c:/assets/new.mov")
    plan, _, _ = run_planner(observations=(observation,))

    item = only(plan)
    assert item.primary_classification is PrimaryClassification.NEW_UNREGISTERED_OBSERVATION
    assert item.actions == ()


def test_07_insufficient_scope_decision():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    plan, _, _ = run_planner(records=(record,), observability={"A-1": False})

    item = only(plan)
    assert item.primary_classification is PrimaryClassification.INSUFFICIENT_SCOPE
    assert item.actions == ()
    assert item.requires_review is False


def test_08_ambiguous_match_decision():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    obs1 = make_observation("obs-1", claimed_asset_id="A-1", source_id="scan-a")
    obs2 = make_observation("obs-2", claimed_asset_id="A-1", source_id="scan-a")
    plan, _, _ = run_planner(
        records=(record,),
        observations=(obs1, obs2),
        trusted_asset_id_source_ids=("scan-a",),
    )

    ambiguous = [item for item in plan.items if item.primary_classification is PrimaryClassification.AMBIGUOUS_MATCH]
    assert len(ambiguous) == 1
    assert ambiguous[0].actions == ()
    assert ambiguous[0].proposal_blocked is True


# ---------------------------------------------------------------------------
# Test 9: every conflict-shaped classification -> actions=() (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classification",
    [
        PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT,
        PrimaryClassification.REGISTRY_IDENTITY_COLLISION,
        PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT,
        PrimaryClassification.CONTENT_CONFLICT,
        PrimaryClassification.DUPLICATE_PATH_CONFLICT,
        PrimaryClassification.AMBIGUOUS_MATCH,
        PrimaryClassification.UNKNOWN_AUTHORITATIVE_ASSET_ID,
        PrimaryClassification.LIFECYCLE_CONFLICT,
    ],
)
def test_09_conflict_shaped_classifications_have_empty_actions(classification):
    decision = ClassificationDecision(
        subject=RegistryRecordSubject(asset_id="A-1"),
        primary_classification=classification,
        evidence_facts=("some_fact",),
        requires_review=True,
        proposal_blocked=True,
    )
    state = ClassificationState(decisions=(decision,))
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot(records=(make_record("A-1"),)))
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.items[0].actions == ()


# ---------------------------------------------------------------------------
# Test 10: every classification (15 reachable + 4 non-executable) -> actions/findings empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("classification", list(PrimaryClassification))
def test_10_every_classification_has_empty_actions_and_findings(classification):
    """Hand-built decisions for all 19 members, including the four
    non-executable ones (``classify_reconciliation`` never produces them --
    this only validates planner pass-through, not Slice 8 reachability)."""
    decision = ClassificationDecision(
        subject=RegistryRecordSubject(asset_id="A-1"),
        primary_classification=classification,
        evidence_facts=(),
        requires_review=False,
        proposal_blocked=False,
    )
    state = ClassificationState(decisions=(decision,))
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot(records=(make_record("A-1"),)))
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.items[0].actions == ()
    assert plan.items[0].findings == ()


# ---------------------------------------------------------------------------
# Test 11-12: deterministic item order and IDs
# ---------------------------------------------------------------------------


def test_11_item_ids_assigned_in_decision_order():
    decisions = tuple(
        ClassificationDecision(
            subject=RegistryRecordSubject(asset_id=f"A-{i}"),
            primary_classification=PrimaryClassification.UNCHANGED,
            evidence_facts=(),
        )
        for i in range(3)
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert [item.item_id for item in plan.items] == ["item-000001", "item-000002", "item-000003"]
    assert [item.subject for item in plan.items] == [d.subject for d in decisions]


def test_12_item_id_sequence_is_stable_across_repeated_calls():
    decisions = tuple(
        ClassificationDecision(
            subject=RegistryRecordSubject(asset_id=f"A-{i}"),
            primary_classification=PrimaryClassification.UNCHANGED,
            evidence_facts=(),
        )
        for i in range(3)
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())

    plan_a = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)
    plan_b = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert [item.item_id for item in plan_a.items] == [item.item_id for item in plan_b.items]


# ---------------------------------------------------------------------------
# Test 13-15: evidence_refs / findings / plan-level evidence
# ---------------------------------------------------------------------------


def test_13_evidence_refs_carries_facts_findings_stays_empty():
    decision = ClassificationDecision(
        subject=RegistryRecordSubject(asset_id="A-1"),
        primary_classification=PrimaryClassification.CONTENT_CONFLICT,
        evidence_facts=("content_hash_mismatch",),
    )
    state = ClassificationState(decisions=(decision,))
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot(records=(make_record("A-1"),)))
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    item = only(plan)
    assert item.evidence_refs == ("content_hash_mismatch",)
    assert item.findings == ()


def test_14_plan_level_evidence_is_sorted_deduplicated_union():
    decisions = (
        ClassificationDecision(
            subject=RegistryRecordSubject(asset_id="A-1"),
            primary_classification=PrimaryClassification.CONTENT_CONFLICT,
            evidence_facts=("shared_fact", "fact_a"),
        ),
        ClassificationDecision(
            subject=RegistryRecordSubject(asset_id="A-2"),
            primary_classification=PrimaryClassification.CONTENT_CONFLICT,
            evidence_facts=("shared_fact", "fact_b"),
        ),
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.evidence == ("fact_a", "fact_b", "shared_fact")


def test_15_no_dangling_evidence_refs():
    decisions = (
        ClassificationDecision(
            subject=RegistryRecordSubject(asset_id="A-1"),
            primary_classification=PrimaryClassification.CONTENT_CONFLICT,
            evidence_facts=("fact_a",),
        ),
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    evidence_set = set(plan.evidence)
    for item in plan.items:
        for ref in item.evidence_refs:
            assert ref in evidence_set


# ---------------------------------------------------------------------------
# Test 16-22: PlanSummary derivation
# ---------------------------------------------------------------------------


def _decision(asset_id, classification, *, requires_review=False, proposal_blocked=False, evidence_facts=()):
    return ClassificationDecision(
        subject=RegistryRecordSubject(asset_id=asset_id),
        primary_classification=classification,
        evidence_facts=evidence_facts,
        requires_review=requires_review,
        proposal_blocked=proposal_blocked,
    )


def test_16_plan_summary_classifications_counts():
    decisions = (
        _decision("A-1", PrimaryClassification.UNCHANGED),
        _decision("A-2", PrimaryClassification.UNCHANGED),
        _decision("A-3", PrimaryClassification.METADATA_DRIFT),
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.classifications == {"unchanged": 2, "metadata_drift": 1}


def test_17_plan_summary_severities_always_empty():
    decisions = tuple(
        _decision(f"A-{i}", classification)
        for i, classification in enumerate(planner_module._CONFLICT_CLASSIFICATIONS)
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.severities == {}


def test_18_plan_summary_action_kinds_always_empty():
    decisions = tuple(
        _decision(f"A-{i}", classification)
        for i, classification in enumerate(planner_module._CONFLICT_CLASSIFICATIONS)
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.action_kinds == {}


def test_19_review_required_and_proposal_blocked_counts():
    decisions = (
        _decision("A-1", PrimaryClassification.UNCHANGED, requires_review=False, proposal_blocked=False),
        _decision("A-2", PrimaryClassification.PATH_CHANGED, requires_review=True, proposal_blocked=False),
        _decision("A-3", PrimaryClassification.CONTENT_CONFLICT, requires_review=True, proposal_blocked=True),
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.review_required_count == 2
    assert plan.summary.proposal_blocked_count == 1


def test_20_invalid_observation_count_always_zero_for_real_pipeline():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    plan, _, _ = run_planner(records=(record,), observations=(observation,))

    assert plan.summary.invalid_observation_count == 0


def test_20a_invalid_observation_count_reflects_a_present_decision():
    """Hand-built decision (bypassing ``classify_reconciliation``, which never
    produces ``INVALID_OBSERVATION`` today) confirms the counting logic
    itself actually increments -- not just that it stays zero when the real
    pipeline can't produce this classification. Does not change or imply any
    change to Slice 8 classification reachability."""
    decisions = (
        _decision("A-1", PrimaryClassification.INVALID_OBSERVATION),
        _decision("A-2", PrimaryClassification.UNCHANGED),
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.invalid_observation_count == 1


def test_21_conflict_count_matches_eight_member_set_exactly():
    conflict_decisions = tuple(
        _decision(f"C-{i}", classification)
        for i, classification in enumerate(planner_module._CONFLICT_CLASSIFICATIONS)
    )
    non_conflict_classifications = [
        member for member in PrimaryClassification if member not in planner_module._CONFLICT_CLASSIFICATIONS
    ]
    non_conflict_decisions = tuple(
        _decision(f"N-{i}", classification) for i, classification in enumerate(non_conflict_classifications)
    )
    state = ClassificationState(decisions=conflict_decisions + non_conflict_decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.conflict_count == len(planner_module._CONFLICT_CLASSIFICATIONS)


def test_22_unmatched_count_matches_new_unregistered_observation_only():
    decisions = (
        _decision("A-1", PrimaryClassification.NEW_UNREGISTERED_OBSERVATION),
        _decision("A-2", PrimaryClassification.RECORD_NOT_OBSERVED),
    )
    state = ClassificationState(decisions=decisions)
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.summary.unmatched_count == 1


# ---------------------------------------------------------------------------
# Test 23: empty plan
# ---------------------------------------------------------------------------


def test_23_empty_classification_state_produces_valid_empty_plan():
    state = ClassificationState(decisions=())
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.items == ()
    assert plan.evidence == ()
    assert plan.summary.classifications == {}
    assert plan.summary.severities == {}
    assert plan.summary.action_kinds == {}
    assert plan.summary.review_required_count == 0
    assert plan.summary.proposal_blocked_count == 0
    assert plan.summary.invalid_observation_count == 0
    assert plan.summary.conflict_count == 0
    assert plan.summary.unmatched_count == 0


# ---------------------------------------------------------------------------
# Test 24: plan_id
# ---------------------------------------------------------------------------


def test_24_plan_id_derived_from_request_and_snapshot_ids():
    state = ClassificationState(decisions=())
    inputs = validate_reconciliation_inputs(
        *make_request_and_snapshot(request_id="req-known", snapshot_id="snap-known")
    )
    plan = plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert plan.plan_id == "plan-req-known-snap-known"


# ---------------------------------------------------------------------------
# Test 25-26: limit_policy_fingerprint
# ---------------------------------------------------------------------------


def test_25_limit_policy_fingerprint_stable_and_field_sensitive():
    state = ClassificationState(decisions=())
    policy_a = ReconciliationLimitPolicy()
    policy_b = ReconciliationLimitPolicy()
    inputs_a = validate_reconciliation_inputs(*make_request_and_snapshot(limit_policy=policy_a))
    inputs_b = validate_reconciliation_inputs(*make_request_and_snapshot(limit_policy=policy_b))

    plan_a = plan_reconciliation(inputs_a, state, created_at=PLAN_CREATED_AT)
    plan_b = plan_reconciliation(inputs_b, state, created_at=PLAN_CREATED_AT)
    assert plan_a.limit_policy_fingerprint == plan_b.limit_policy_fingerprint

    policy_c = ReconciliationLimitPolicy(max_observations_per_request=5000)
    inputs_c = validate_reconciliation_inputs(*make_request_and_snapshot(limit_policy=policy_c))
    plan_c = plan_reconciliation(inputs_c, state, created_at=PLAN_CREATED_AT)
    assert plan_c.limit_policy_fingerprint != plan_a.limit_policy_fingerprint


def test_26_limit_policy_fingerprint_is_hash_seed_independent():
    script = (
        "from redline_core.asset.reconciliation.limits import ReconciliationLimitPolicy\n"
        "from redline_core.asset.reconciliation.planner import _limit_policy_fingerprint\n"
        "print(_limit_policy_fingerprint(ReconciliationLimitPolicy()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    outputs = []
    for seed in ("1", "987654321"):
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )
        outputs.append(completed.stdout.strip())

    assert outputs[0] == outputs[1]


# ---------------------------------------------------------------------------
# Test 27: caller-supplied created_at
# ---------------------------------------------------------------------------


def test_27_created_at_is_exactly_the_caller_supplied_value():
    state = ClassificationState(decisions=())
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())
    custom_time = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)

    plan = plan_reconciliation(inputs, state, created_at=custom_time)

    assert plan.created_at == custom_time


# ---------------------------------------------------------------------------
# Test 28-29: defensive type checks
# ---------------------------------------------------------------------------


def test_28_non_classification_state_raises():
    inputs = validate_reconciliation_inputs(*make_request_and_snapshot())

    with pytest.raises(ReconciliationInvariantError) as error_info:
        plan_reconciliation(inputs, "not-a-classification-state", created_at=PLAN_CREATED_AT)

    assert error_info.value.context["reason_code"] == "planner_invalid_input_type"


def test_29_non_validated_inputs_raises():
    state = ClassificationState(decisions=())

    with pytest.raises(ReconciliationInvariantError) as error_info:
        plan_reconciliation("not-validated-inputs", state, created_at=PLAN_CREATED_AT)

    assert error_info.value.context["reason_code"] == "planner_invalid_input_type"


# ---------------------------------------------------------------------------
# Test 30: structural non-mutation (equality, not repr())
# ---------------------------------------------------------------------------


def _build_inputs_and_state(record, observation):
    request, snapshot = make_request_and_snapshot(records=(record,), observations=(observation,))
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    matching_state = build_matching_state(inputs, indexes)
    state = classify_reconciliation(inputs, indexes, matching_state, {})
    return inputs, state


def test_30_inputs_and_classification_state_are_not_mutated():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")

    # ``inputs``/``classification_state`` contain ``mappingproxy`` fields
    # (e.g. ``AssetObservation.metadata``), which ``copy.deepcopy`` cannot
    # copy. Per the contract, an independently-constructed, structurally
    # equal copy built via the same builder functions with identical
    # arguments is the alternative to ``copy.deepcopy`` -- used here.
    inputs, state = _build_inputs_and_state(record, observation)
    expected_inputs, expected_state = _build_inputs_and_state(record, observation)

    plan_reconciliation(inputs, state, created_at=PLAN_CREATED_AT)

    assert inputs == expected_inputs
    assert state == expected_state


# ---------------------------------------------------------------------------
# Test 31: no ReconciliationPlanner symbol
# ---------------------------------------------------------------------------


def test_31_no_reconciliation_planner_symbol():
    assert not hasattr(planner_module, "ReconciliationPlanner")


# ---------------------------------------------------------------------------
# Test 32: full end-to-end integration
# ---------------------------------------------------------------------------


def test_32_end_to_end_multi_classification_scenario():
    unchanged_record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    unchanged_observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")

    drift_record = make_record("A-2", normalized_path="c:/assets/a2.mov", file_modified_at=NOW)
    drift_observation = make_observation(
        "obs-2", normalized_path="c:/assets/a2.mov", file_modified_at=NOW.replace(hour=14)
    )

    missing_record = make_record("A-3", normalized_path="c:/assets/a3.mov")

    new_observation = make_observation("obs-4", normalized_path="c:/assets/new.mov")

    plan, inputs, state = run_planner(
        records=(unchanged_record, drift_record, missing_record),
        observations=(unchanged_observation, drift_observation, new_observation),
        observability={"A-3": True},
    )

    assert len(plan.items) == len(state.decisions) == 4
    classifications = {item.primary_classification for item in plan.items}
    assert classifications == {
        PrimaryClassification.UNCHANGED,
        PrimaryClassification.METADATA_DRIFT,
        PrimaryClassification.RECORD_NOT_OBSERVED,
        PrimaryClassification.NEW_UNREGISTERED_OBSERVATION,
    }
    for item in plan.items:
        assert item.actions == ()
        assert item.findings == ()
    assert plan.summary.severities == {}
    assert plan.summary.action_kinds == {}
    assert plan.plan_id == f"plan-{inputs.request.request_id}-{inputs.snapshot.snapshot_id}"
    assert plan.request_id == inputs.request.request_id
    assert plan.snapshot_id == inputs.snapshot.snapshot_id
    assert plan.registry_id == inputs.snapshot.registry_id
    assert plan.created_at == PLAN_CREATED_AT
