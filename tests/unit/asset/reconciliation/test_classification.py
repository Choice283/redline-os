"""Tests for Phase 3 Slice 8 classification (``classification.py``).

Implements the exhaustive test matrix from the approved "Slice 8
Implementation Contract -- Revision 3", section 6 (tests 1-32). Each test
below is numbered in its docstring to match that contract for traceability.

``observability_by_asset_id`` decisions are constructed directly rather than
routed through ``scope.evaluate_record_observability`` -- per the contract's
explicit input-contract refinement (section 1.1 / 3.6), classification.py
consumes already-resolved ``ObservabilityDecision`` values and never resolves
scope itself, so injecting them directly here is the correct, most direct way
to unit test this module in isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.classification import (
    ClassificationDecision,
    ClassificationState,
    _MATCHED_PAIR_RULES,
    _MatchedPairContext,
    classify_reconciliation,
)
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    ObservationKind,
    PrimaryClassification,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.exceptions import ReconciliationInvariantError
from redline_core.asset.reconciliation.indexes import ReconciliationIndexes, build_indexes
from redline_core.asset.reconciliation.matching import DefinitiveAssociation, MatchingState, build_matching_state
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ObservationRootScope,
    ObservationScope,
    ReconciliationRequest,
    RegistryIdentityEvidence,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.scope import ObservabilityDecision
from redline_core.asset.reconciliation.subjects import (
    ObservationGroupSubject,
    ObservationSubject,
    RegistryRecordGroupSubject,
    RegistryRecordSubject,
)
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 7, 28, 13, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixture builders (mirrors tests/unit/asset/reconciliation/test_matching_strong_identity.py)
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
    evidence_kind=None,
    algorithm: str | None = "sha256",
    normalized_value: str,
    normalization_format: str = "lowercase_hex",
    scope_id: str | None = None,
    source_id: str = "registry-scan",
) -> RegistryIdentityEvidence:
    from redline_core.asset.reconciliation.enums import EvidenceKind

    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=evidence_kind or EvidenceKind.FULL_CONTENT_HASH,
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


def run_classification(
    *,
    records: tuple[AssetRegistryRecord, ...] = (),
    identity_evidence: tuple[RegistryIdentityEvidence, ...] = (),
    observations: tuple[AssetObservation, ...] = (),
    trusted_asset_id_source_ids: tuple[str, ...] = (),
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
    observability: dict[str, bool] | None = None,
) -> tuple[ClassificationState, ReconciliationIndexes, MatchingState]:
    snapshot = RegistrySnapshot(
        records=records,
        identity_evidence=identity_evidence,
        schema_version="1",
        snapshot_id="snap-1",
        snapshot_created_at=NOW,
        registry_id="reg-1",
        approved_root_context="assets_path",
    )
    request = ReconciliationRequest(
        request_id="req-1",
        schema_version="1",
        created_at=NOW,
        observations=observations,
        scopes=(make_scope(),),
        trusted_asset_id_source_ids=trusted_asset_id_source_ids,
        asset_id_trust_policy=asset_id_trust_policy,
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
    return state, indexes, matching_state


def only(state: ClassificationState) -> ClassificationDecision:
    assert len(state.decisions) == 1, state.decisions
    return state.decisions[0]


def by_classification(state: ClassificationState, classification: PrimaryClassification) -> tuple[ClassificationDecision, ...]:
    return tuple(d for d in state.decisions if d.primary_classification is classification)


# ---------------------------------------------------------------------------
# Test 1-2: registry identity evidence conflict (rank 1)
# ---------------------------------------------------------------------------


def test_01_registry_identity_evidence_conflict_no_observation():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    ev1 = make_evidence("A-1", normalized_value="digest-1")
    ev2 = make_evidence("A-1", normalized_value="digest-2")
    state, _, _ = run_classification(records=(record,), identity_evidence=(ev1, ev2))

    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT
    assert decision.subject == RegistryRecordSubject(asset_id="A-1")
    assert by_classification(state, PrimaryClassification.RECORD_NOT_OBSERVED) == ()


def test_02_registry_identity_evidence_same_value_twice_dedup():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    ev1 = make_evidence("A-1", normalized_value="digest-1")
    ev2 = make_evidence("A-1", normalized_value="digest-1")
    state, _, _ = run_classification(records=(record,), identity_evidence=(ev1, ev2))

    assert by_classification(state, PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT) == ()
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.RECORD_NOT_OBSERVED


# ---------------------------------------------------------------------------
# Test 3-4: matching-derived conflicts pass-through (ranks 2, 3)
# ---------------------------------------------------------------------------


def test_03_registry_identity_collision_pass_through():
    record_a = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    record_b = make_record("A-2", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    ev_a = make_evidence("A-1", normalized_value="digest-1")
    ev_b = make_evidence("A-2", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),), availability=AssetAvailability.AVAILABLE)
    state, _, matching_state = run_classification(
        records=(record_a, record_b), identity_evidence=(ev_a, ev_b), observations=(observation,)
    )

    collisions = by_classification(state, PrimaryClassification.REGISTRY_IDENTITY_COLLISION)
    assert len(collisions) == 1
    matching_subjects = {c.subject for c in matching_state.conflict_groups}
    assert collisions[0].subject in matching_subjects


def test_04_authoritative_identity_conflict_pass_through():
    record_a = make_record("A-1", normalized_path="c:/assets/a1.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/a2.mov")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a2.mov", claimed_asset_id="A-1"
    )
    state, _, _ = run_classification(
        records=(record_a, record_b),
        observations=(observation,),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )

    conflicts = by_classification(state, PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT)
    assert len(conflicts) == 1
    assert by_classification(state, PrimaryClassification.AMBIGUOUS_MATCH) == ()


# ---------------------------------------------------------------------------
# Test 5-6: ambiguous match (rank 6)
# ---------------------------------------------------------------------------


def test_05_trusted_id_claimed_by_multiple_observations():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    obs1 = make_observation("obs-1", claimed_asset_id="A-1", source_id="scan-a")
    obs2 = make_observation("obs-2", claimed_asset_id="A-1", source_id="scan-a")
    state, _, _ = run_classification(
        records=(record,),
        observations=(obs1, obs2),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )

    ambiguous = by_classification(state, PrimaryClassification.AMBIGUOUS_MATCH)
    assert len(ambiguous) == 1
    assert ambiguous[0].subject == ObservationGroupSubject(observation_ids=("obs-1", "obs-2"))
    assert by_classification(state, PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT) == ()


def test_06_observation_identity_collision_routes_to_ambiguous():
    record_a = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    evidence = make_evidence("A-1", normalized_value="digest-1")
    obs1 = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs2 = make_observation("obs-2", content_hashes=(("sha256", "digest-1"),))
    state, _, _ = run_classification(
        records=(record_a,), identity_evidence=(evidence,), observations=(obs1, obs2)
    )

    ambiguous = by_classification(state, PrimaryClassification.AMBIGUOUS_MATCH)
    assert len(ambiguous) == 1
    all_classifications = {member for member in PrimaryClassification}
    assert ambiguous[0].primary_classification in all_classifications


# ---------------------------------------------------------------------------
# Test 7-9: content conflict (rank 10 / 4b)
# ---------------------------------------------------------------------------


def test_07_content_conflict_via_matching_collision():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/other.mov", claimed_asset_id="A-1"
    )
    # Force a strong-identity content conflict against an existing exact-path association:
    # record path matches nothing (exact-path-only association exists elsewhere), and a
    # strong-identity candidate disagrees. Simpler: directly assert via conflict_groups path
    # already covered by test_04's AUTHORITATIVE_IDENTITY case; for CONTENT we build the
    # strong-identity-vs-exact-path disagreement described in matching.py.
    record_path_only = make_record("A-2", normalized_path="c:/assets/other.mov")
    evidence = make_evidence("A-2", normalized_value="digest-1")
    obs_strong = make_observation("obs-2", content_hashes=(("sha256", "digest-1"),))
    state, _, matching_state = run_classification(
        records=(record_path_only,),
        identity_evidence=(evidence,),
        observations=(make_observation("obs-3", normalized_path="c:/assets/other.mov"), obs_strong),
    )
    content_conflicts = by_classification(state, PrimaryClassification.CONTENT_CONFLICT)
    assert len(content_conflicts) == 1


def test_08_content_conflict_via_field_comparison():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    evidence = make_evidence("A-1", normalized_value="digest-registry")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", content_hashes=(("sha256", "digest-observation"),)
    )
    state, _, _ = run_classification(
        records=(record,), identity_evidence=(evidence,), observations=(observation,)
    )
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.CONTENT_CONFLICT
    assert decision.subject == RegistryRecordSubject(asset_id="A-1")


def test_09_no_content_conflict_when_hash_missing_on_one_side():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    assert by_classification(state, PrimaryClassification.CONTENT_CONFLICT) == ()


# ---------------------------------------------------------------------------
# Test 10-11: duplicate path conflict (rank 5)
# ---------------------------------------------------------------------------


def test_10_duplicate_observation_path_group_cardinality():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    obs1 = make_observation("obs-1", normalized_path="c:/assets/dup.mov")
    obs2 = make_observation("obs-2", normalized_path="c:/assets/dup.mov")
    obs3 = make_observation("obs-3", normalized_path="c:/assets/dup.mov")
    state, _, _ = run_classification(records=(record,), observations=(obs1, obs2, obs3))

    duplicates = by_classification(state, PrimaryClassification.DUPLICATE_PATH_CONFLICT)
    assert len(duplicates) == 1
    assert duplicates[0].subject == ObservationGroupSubject(observation_ids=("obs-1", "obs-2", "obs-3"))


def test_11_duplicate_registry_path_group_cardinality():
    record_a = make_record("A-1", normalized_path="c:/assets/dup.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/dup.mov")
    state, _, _ = run_classification(records=(record_a, record_b))

    duplicates = by_classification(state, PrimaryClassification.DUPLICATE_PATH_CONFLICT)
    assert len(duplicates) == 1
    assert duplicates[0].subject == RegistryRecordGroupSubject(asset_ids=("A-1", "A-2"))


# ---------------------------------------------------------------------------
# Test 12: unknown trusted Asset ID (rank 7)
# ---------------------------------------------------------------------------


def test_12_unknown_trusted_asset_id():
    observation = make_observation("obs-1", claimed_asset_id="A-404", source_id="scan-a")
    state, _, _ = run_classification(
        observations=(observation,),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.UNKNOWN_AUTHORITATIVE_ASSET_ID
    assert decision.subject == ObservationSubject(observation_id="obs-1")


# ---------------------------------------------------------------------------
# Test 13-15: path changed (rank 8, Decision 4)
# ---------------------------------------------------------------------------


def test_13_path_changed_unique_strong_identity():
    record = make_record("A-1", normalized_path="c:/assets/old.mov")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/new.mov", content_hashes=(("sha256", "digest-1"),)
    )
    state, _, matching_state = run_classification(
        records=(record,), identity_evidence=(evidence,), observations=(observation,)
    )
    assert matching_state.definitive_associations[0].association_kind == "unique_strong_identity"
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.PATH_CHANGED


def test_14_path_not_changed_trusted_asset_id_kind():
    record = make_record("A-1", normalized_path="c:/assets/old.mov")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/new.mov", claimed_asset_id="A-1", source_id="scan-a"
    )
    state, _, matching_state = run_classification(
        records=(record,),
        observations=(observation,),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )
    assert matching_state.definitive_associations[0].association_kind == "trusted_asset_id"
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.METADATA_DRIFT
    assert decision.primary_classification is not PrimaryClassification.PATH_CHANGED


def test_15_path_changed_trusted_and_exact_path_kind_never_triggers_predicate():
    record = make_record("A-1", normalized_path="c:/assets/same.mov")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/same.mov", claimed_asset_id="A-1", source_id="scan-a"
    )
    state, _, matching_state = run_classification(
        records=(record,),
        observations=(observation,),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )
    assert matching_state.definitive_associations[0].association_kind == "trusted_asset_id_and_exact_path"
    decision = only(state)
    assert decision.primary_classification is not PrimaryClassification.PATH_CHANGED


# ---------------------------------------------------------------------------
# Test 16: lifecycle conflict (rank 9)
# ---------------------------------------------------------------------------


def test_16_lifecycle_conflict_blocks_reactivation():
    record = make_record(
        "A-1",
        normalized_path="c:/assets/a1.mov",
        lifecycle=AssetLifecycle.DEPRECATED,
        availability=AssetAvailability.MISSING,
        verification=AssetVerificationState.VERIFIED,
    )
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    state, _, _ = run_classification(records=(record,), observations=(observation,))

    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.LIFECYCLE_CONFLICT
    assert decision.requires_review is True
    assert by_classification(state, PrimaryClassification.UNCHANGED) == ()
    assert by_classification(state, PrimaryClassification.METADATA_DRIFT) == ()
    assert by_classification(state, PrimaryClassification.AVAILABILITY_CHANGED) == ()


# ---------------------------------------------------------------------------
# Test 17-20: availability transition table (rank 10 / Decision 2)
# ---------------------------------------------------------------------------


def test_17_availability_changed_available_to_missing():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", availability=AssetAvailability.MISSING
    )
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.AVAILABILITY_CHANGED
    assert decision.primary_classification is not PrimaryClassification.METADATA_DRIFT


def test_18_availability_changed_available_to_non_file():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", availability=AssetAvailability.NON_FILE
    )
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.AVAILABILITY_CHANGED


def test_19_availability_recovery_missing_to_available():
    record = make_record(
        "A-1",
        normalized_path="c:/assets/a1.mov",
        availability=AssetAvailability.MISSING,
        verification=AssetVerificationState.VERIFIED,
    )
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.METADATA_DRIFT
    assert decision.primary_classification is not PrimaryClassification.AVAILABILITY_CHANGED


def test_20_availability_recovery_unknown_to_available():
    record = make_record(
        "A-1",
        normalized_path="c:/assets/a1.mov",
        lifecycle=AssetLifecycle.DECLARED,
        availability=AssetAvailability.UNKNOWN,
        verification=AssetVerificationState.UNVERIFIED,
    )
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.METADATA_DRIFT
    assert decision.primary_classification is not PrimaryClassification.AVAILABILITY_CHANGED


# ---------------------------------------------------------------------------
# Test 21-23: unchanged / metadata drift / size interim policy (ranks 13-14)
# ---------------------------------------------------------------------------


def test_21_available_to_available_no_other_diff():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov", file_size_bytes=2048, file_modified_at=NOW)
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", file_size_bytes=2048, file_modified_at=NOW
    )
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.UNCHANGED


def test_22_available_to_available_mtime_differs():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov", file_size_bytes=2048, file_modified_at=NOW)
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", file_size_bytes=2048, file_modified_at=LATER
    )
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.METADATA_DRIFT


def test_23_size_differs_no_comparable_hash_interim_policy():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov", file_size_bytes=2048, file_modified_at=NOW)
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a1.mov", file_size_bytes=4096, file_modified_at=NOW
    )
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.METADATA_DRIFT
    assert decision.requires_review is True
    assert "size_differs_no_comparable_hash" in decision.evidence_facts
    assert not hasattr(PrimaryClassification, "SIZE_CONFLICT")


# ---------------------------------------------------------------------------
# Test 24-25: record not observed / insufficient scope (ranks 11, 15)
# ---------------------------------------------------------------------------


def test_24_record_not_observed_complete_scope():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    state, _, _ = run_classification(records=(record,), observability={"A-1": True})
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.RECORD_NOT_OBSERVED


def test_25_insufficient_scope_incomplete():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    state, _, _ = run_classification(records=(record,), observability={"A-1": False})
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.INSUFFICIENT_SCOPE
    assert by_classification(state, PrimaryClassification.RECORD_NOT_OBSERVED) == ()


# ---------------------------------------------------------------------------
# Test 26: new unregistered observation (rank 12)
# ---------------------------------------------------------------------------


def test_26_new_unregistered_observation():
    observation = make_observation("obs-1", normalized_path="c:/assets/unknown.mov")
    state, _, _ = run_classification(observations=(observation,))
    decision = only(state)
    assert decision.primary_classification is PrimaryClassification.NEW_UNREGISTERED_OBSERVATION
    assert decision.subject == ObservationSubject(observation_id="obs-1")


# ---------------------------------------------------------------------------
# Test 27: dangling association reference (invariant)
# ---------------------------------------------------------------------------


def test_27_dangling_association_reference_raises_invariant():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    snapshot = RegistrySnapshot(
        records=(record,),
        identity_evidence=(),
        schema_version="1",
        snapshot_id="snap-1",
        snapshot_created_at=NOW,
        registry_id="reg-1",
        approved_root_context="assets_path",
    )
    request = ReconciliationRequest(
        request_id="req-1",
        schema_version="1",
        created_at=NOW,
        observations=(observation,),
        scopes=(make_scope(),),
    )
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    matching_state = build_matching_state(inputs, indexes)

    dangling_state = MatchingState(
        definitive_associations=(
            DefinitiveAssociation(
                asset_id="A-404",
                observation_id="obs-1",
                association_kind="exact_path",
                evidence_facts=("exact_path",),
            ),
        ),
        blocked_observations=(),
        blocked_records=(),
        conflict_groups=(),
        consumed=matching_state.consumed,
    )

    with pytest.raises(ReconciliationInvariantError) as exc_info:
        classify_reconciliation(inputs, indexes, dangling_state, {})
    assert exc_info.value.context.get("reason_code") == "classification_dangling_association_reference"


# ---------------------------------------------------------------------------
# Test 28: every enum member accounted for exactly once
# ---------------------------------------------------------------------------


_NON_EXECUTABLE_MEMBERS = frozenset(
    {
        PrimaryClassification.REGISTRY_SNAPSHOT_INVALID,
        PrimaryClassification.INVALID_OBSERVATION,
        PrimaryClassification.UNSUPPORTED_OBSERVATION,
        PrimaryClassification.DIAGNOSTIC_ONLY,
    }
)

_EXECUTABLE_MEMBERS = frozenset(
    {
        PrimaryClassification.REGISTRY_IDENTITY_EVIDENCE_CONFLICT,
        PrimaryClassification.REGISTRY_IDENTITY_COLLISION,
        PrimaryClassification.AUTHORITATIVE_IDENTITY_CONFLICT,
        PrimaryClassification.CONTENT_CONFLICT,
        PrimaryClassification.DUPLICATE_PATH_CONFLICT,
        PrimaryClassification.AMBIGUOUS_MATCH,
        PrimaryClassification.UNKNOWN_AUTHORITATIVE_ASSET_ID,
        PrimaryClassification.PATH_CHANGED,
        PrimaryClassification.LIFECYCLE_CONFLICT,
        PrimaryClassification.AVAILABILITY_CHANGED,
        PrimaryClassification.RECORD_NOT_OBSERVED,
        PrimaryClassification.NEW_UNREGISTERED_OBSERVATION,
        PrimaryClassification.UNCHANGED,
        PrimaryClassification.METADATA_DRIFT,
        PrimaryClassification.INSUFFICIENT_SCOPE,
    }
)


def test_28_every_enum_member_accounted_for_exactly_once():
    all_members = set(PrimaryClassification)
    assert _EXECUTABLE_MEMBERS | _NON_EXECUTABLE_MEMBERS == all_members
    assert _EXECUTABLE_MEMBERS & _NON_EXECUTABLE_MEMBERS == set()
    assert len(_EXECUTABLE_MEMBERS) == 15
    assert len(_NON_EXECUTABLE_MEMBERS) == 4


# ---------------------------------------------------------------------------
# Test 29: Tier 2/3 non-backfill boundary
# ---------------------------------------------------------------------------


def test_29_does_not_construct_invalid_observation():
    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    state, _, _ = run_classification(records=(record,), observations=(observation,))
    assert by_classification(state, PrimaryClassification.INVALID_OBSERVATION) == ()


# ---------------------------------------------------------------------------
# Test 30: indexes.py import boundary (Decision 7)
# ---------------------------------------------------------------------------


def test_30_indexes_does_not_import_classification():
    import ast
    import inspect

    import redline_core.asset.reconciliation.indexes as indexes_module

    source = inspect.getsource(indexes_module)
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
    assert not any("classification" in name for name in imported_modules)


# ---------------------------------------------------------------------------
# Test 31: missing observability decision (invariant, Revision 3 refinement)
# ---------------------------------------------------------------------------


def test_31_missing_observability_decision_raises_invariant():
    record = make_record("A-1", normalized_path=None, availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED, lifecycle=AssetLifecycle.DECLARED)
    snapshot = RegistrySnapshot(
        records=(record,),
        identity_evidence=(),
        schema_version="1",
        snapshot_id="snap-1",
        snapshot_created_at=NOW,
        registry_id="reg-1",
        approved_root_context="assets_path",
    )
    request = ReconciliationRequest(
        request_id="req-1", schema_version="1", created_at=NOW, observations=(), scopes=(make_scope(),)
    )
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    matching_state = build_matching_state(inputs, indexes)

    with pytest.raises(ReconciliationInvariantError) as exc_info:
        classify_reconciliation(inputs, indexes, matching_state, {})
    assert exc_info.value.context.get("reason_code") == "classification_missing_observability_decision"


# ---------------------------------------------------------------------------
# Test 32: no rule matched (invariant, Revision 3 refinement)
# ---------------------------------------------------------------------------


def test_32_no_rule_matched_raises_invariant(monkeypatch):
    import redline_core.asset.reconciliation.classification as classification_module

    monkeypatch.setattr(classification_module, "_MATCHED_PAIR_RULES", ())

    record = make_record("A-1", normalized_path="c:/assets/a1.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a1.mov")
    with pytest.raises(ReconciliationInvariantError) as exc_info:
        run_classification(records=(record,), observations=(observation,))
    assert exc_info.value.context.get("reason_code") == "classification_no_rule_matched"
