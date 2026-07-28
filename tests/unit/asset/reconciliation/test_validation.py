"""Tests for the pure reconciliation input validation pipeline."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

import pytest

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    EvidenceKind,
    ObservationKind,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.exceptions import (
    AmbiguousEquivalentRootError,
    DuplicateObservationIdError,
    InvalidReconciliationRequestError,
    InvalidRegistrySnapshotError,
    ReconciliationLimitExceededError,
    UnsupportedReconciliationVersionError,
)
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS, ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ExplicitAssetAccessFailure,
    ObservationFilters,
    ObservationRootScope,
    ObservationScope,
    ReconciliationRequest,
    RegistryIdentityEvidence,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.validation import (
    ValidatedReconciliationInputs,
    validate_reconciliation_inputs,
)


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def error_surfaces(error: Exception) -> tuple[str, ...]:
    return str(error), repr(error), repr(error.args), repr(vars(error))


def make_record(
    asset_id: str = "RLG-001",
    *,
    record_id: int = 1,
    normalized_path: str | None = "c:/assets/logos/lower_third.png",
) -> AssetRegistryRecord:
    return AssetRegistryRecord(
        record_id=record_id,
        asset_id=asset_id,
        declared_path=f"assets/{asset_id}.mov",
        resolved_path=f"C:/assets/{asset_id}.mov" if normalized_path is not None else None,
        normalized_resolved_path=normalized_path,
        approved_root_id="assets_path",
        lifecycle=AssetLifecycle.DECLARED,
        availability=AssetAvailability.UNKNOWN,
        verification=AssetVerificationState.UNVERIFIED,
        file_size_bytes=None,
        file_modified_at=None,
        last_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
        source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail="config/assets.yaml",
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_evidence(
    asset_id: str = "RLG-001",
    *,
    value: str = "abc",
    observed_at: datetime = NOW,
    source_id: str = "scan-a",
) -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=EvidenceKind.FULL_CONTENT_HASH,
        algorithm="sha256",
        normalized_value=value,
        normalization_format="hex",
        scope_id=None,
        source_id=source_id,
        observed_at=observed_at,
    )


def make_metadata_evidence(
    asset_id: str = "RLG-001",
    *,
    value: str = "metadata-value",
    algorithm: str | None = None,
    normalization_format: str = "text",
    scope_id: str | None = None,
    observed_at: datetime = NOW,
    source_id: str = "scan-a",
) -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=EvidenceKind.METADATA,
        algorithm=algorithm,
        normalized_value=value,
        normalization_format=normalization_format,
        scope_id=scope_id,
        source_id=source_id,
        observed_at=observed_at,
    )


def make_scope(scope_id: str = "scope-1", *, roots: tuple[ObservationRootScope, ...] | None = None) -> ObservationScope:
    return ObservationScope(
        scope_id=scope_id,
        observed_at=NOW,
        source_id="scan-a",
        roots=roots
        if roots is not None
        else (
            ObservationRootScope(
                normalized_root_key="c:/assets",
                completeness=ScopeCompleteness.COMPLETE,
            ),
        ),
    )


def make_observation(
    observation_id: str = "obs-1",
    *,
    scope_id: str = "scope-1",
    normalized_path: str | None = "c:/assets/logos/lower_third.png",
) -> AssetObservation:
    return AssetObservation(
        observation_id=observation_id,
        source_id="scan-a",
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id=scope_id,
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        normalized_resolved_path=normalized_path,
    )


def make_request(
    *,
    observations: tuple[AssetObservation, ...] = (),
    scopes: tuple[ObservationScope, ...] = (),
    limits: ReconciliationLimitPolicy = DEFAULT_LIMITS,
) -> ReconciliationRequest:
    return ReconciliationRequest(
        request_id="request-1",
        schema_version="1",
        created_at=NOW,
        observations=observations,
        scopes=scopes,
        limit_policy=limits,
    )


def make_snapshot(
    *,
    records: tuple[AssetRegistryRecord, ...] = (),
    evidence: tuple[RegistryIdentityEvidence, ...] = (),
) -> RegistrySnapshot:
    return RegistrySnapshot(
        records=records,
        identity_evidence=evidence,
        schema_version="1",
        snapshot_id="snapshot-1",
        snapshot_created_at=NOW,
        registry_id="registry-1",
        approved_root_context="root-context-1",
    )


def test_validate_accepts_minimal_empty_inputs():
    request = make_request()
    snapshot = make_snapshot()

    result = validate_reconciliation_inputs(request, snapshot)

    assert result == ValidatedReconciliationInputs(request=request, snapshot=snapshot)


def test_validate_accepts_representative_request_and_deduplicates_registry_evidence():
    older = make_evidence(observed_at=NOW.replace(hour=11))
    newer = make_evidence(observed_at=NOW)
    request = make_request(observations=(make_observation(),), scopes=(make_scope(),))
    snapshot = make_snapshot(records=(make_record(),), evidence=(older, newer))

    result = validate_reconciliation_inputs(request, snapshot)

    assert result.request is request
    assert result.snapshot.identity_evidence == (newer,)
    assert snapshot.identity_evidence == (older, newer)


@pytest.mark.parametrize("bad_input", [None, {}, [], object()])
def test_validate_rejects_non_request_inputs_without_repr(bad_input):
    with pytest.raises(InvalidReconciliationRequestError) as error_info:
        validate_reconciliation_inputs(bad_input, make_snapshot())  # type: ignore[arg-type]

    assert error_info.value.error_code == "invalid_reconciliation_request"


def test_validate_rejects_hostile_input_without_invoking_repr_or_str():
    class Hostile:
        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

        def __str__(self) -> str:
            raise AssertionError("str must not be called")

    with pytest.raises(InvalidReconciliationRequestError) as error_info:
        validate_reconciliation_inputs(Hostile(), make_snapshot())  # type: ignore[arg-type]

    for surface in error_surfaces(error_info.value):
        assert "Hostile" not in surface
        assert "repr must not be called" not in surface
        assert "str must not be called" not in surface
        assert "0x" not in surface


def test_validate_rejects_request_subclasses():
    class EvilRequest(ReconciliationRequest):
        pass

    request = EvilRequest(request_id="request-1", schema_version="1", created_at=NOW, observations=(), scopes=())

    with pytest.raises(InvalidReconciliationRequestError):
        validate_reconciliation_inputs(request, make_snapshot())


def test_validate_rejects_invalid_snapshot_inputs_with_snapshot_error():
    @dataclass(frozen=True)
    class SnapshotLookalike:
        records: tuple[AssetRegistryRecord, ...] = ()
        identity_evidence: tuple[RegistryIdentityEvidence, ...] = ()
        schema_version: str = "1"
        snapshot_id: str = "payload-secret"
        snapshot_created_at: datetime = NOW
        registry_id: str = "registry-1"
        approved_root_context: str = "root-context-1"

    class HostileSnapshot:
        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

        def __str__(self) -> str:
            raise AssertionError("str must not be called")

    invalid_snapshots = (
        None,
        {"snapshot_id": "payload-secret"},
        object(),
        SnapshotLookalike(),
        HostileSnapshot(),
    )
    for invalid_snapshot in invalid_snapshots:
        with pytest.raises(InvalidRegistrySnapshotError) as error_info:
            validate_reconciliation_inputs(make_request(), invalid_snapshot)  # type: ignore[arg-type]

        assert not isinstance(error_info.value, InvalidReconciliationRequestError)
        assert error_info.value.error_code == "registry_snapshot_invalid"
        assert error_info.value.context == {
            "field_name": "snapshot",
            "reason_code": "invalid_input_type",
        }
        for surface in error_surfaces(error_info.value):
            assert "SnapshotLookalike" not in surface
            assert "HostileSnapshot" not in surface
            assert "payload-secret" not in surface
            assert "repr must not be called" not in surface
            assert "str must not be called" not in surface
            assert "0x" not in surface


def test_validate_rejects_snapshot_subclasses_with_snapshot_error():
    class DirectSnapshotSubclass(RegistrySnapshot):
        pass

    class EmptySnapshotSubclass(RegistrySnapshot):
        pass

    class GrandchildSnapshotSubclass(DirectSnapshotSubclass):
        pass

    for snapshot_type in (DirectSnapshotSubclass, EmptySnapshotSubclass, GrandchildSnapshotSubclass):
        snapshot = snapshot_type(
            records=(),
            identity_evidence=(),
            schema_version="1",
            snapshot_id="snapshot-1",
            snapshot_created_at=NOW,
            registry_id="registry-1",
            approved_root_context="root-context-1",
        )
        with pytest.raises(InvalidRegistrySnapshotError) as error_info:
            validate_reconciliation_inputs(make_request(), snapshot)

        assert not isinstance(error_info.value, InvalidReconciliationRequestError)
        assert error_info.value.context["reason_code"] == "invalid_input_type"


def test_validate_preserves_type_check_fail_fast_order():
    invalid_request = object()
    invalid_snapshot = object()
    invalid_request_with_defect = make_request(
        observations=(make_observation("obs-1"), make_observation("obs-1")),
        scopes=(make_scope(),),
    )

    with pytest.raises(InvalidReconciliationRequestError):
        validate_reconciliation_inputs(invalid_request, invalid_snapshot)  # type: ignore[arg-type]

    with pytest.raises(InvalidRegistrySnapshotError):
        validate_reconciliation_inputs(make_request(), invalid_snapshot)  # type: ignore[arg-type]

    with pytest.raises(InvalidRegistrySnapshotError):
        validate_reconciliation_inputs(invalid_request_with_defect, invalid_snapshot)  # type: ignore[arg-type]


def test_validate_rejects_unsupported_request_and_snapshot_versions():
    with pytest.raises(UnsupportedReconciliationVersionError):
        validate_reconciliation_inputs(replace(make_request(), schema_version="2"), make_snapshot())

    with pytest.raises(InvalidRegistrySnapshotError):
        validate_reconciliation_inputs(make_request(), replace(make_snapshot(), schema_version="2"))


def test_validate_enforces_top_level_collection_limits():
    limits = ReconciliationLimitPolicy(
        max_observations_per_request=1,
        max_registry_records_per_snapshot=1,
        max_registry_evidence_rows=1,
    )
    scope = make_scope()
    observations = (
        make_observation("obs-1"),
        make_observation("obs-2"),
    )
    records = (make_record("RLG-001", record_id=1), make_record("RLG-002", record_id=2))
    evidence = (make_evidence("RLG-001"), make_evidence("RLG-001", source_id="scan-b"))

    with pytest.raises(ReconciliationLimitExceededError, match="Reconciliation limit"):
        validate_reconciliation_inputs(make_request(observations=observations, scopes=(scope,), limits=limits), make_snapshot())
    with pytest.raises(ReconciliationLimitExceededError):
        validate_reconciliation_inputs(make_request(limits=limits), make_snapshot(records=records))
    with pytest.raises(ReconciliationLimitExceededError):
        validate_reconciliation_inputs(make_request(limits=limits), make_snapshot(records=(make_record(),), evidence=evidence))


def test_validate_enforces_scope_collection_limits():
    limits = ReconciliationLimitPolicy(
        max_roots_per_scope=1,
        max_inaccessible_subtrees_per_root=1,
        max_access_failures_per_root=1,
        max_inclusion_filter_values=1,
        max_exclusion_filter_values=1,
        max_explicit_asset_ids=1,
    )

    with pytest.raises(ReconciliationLimitExceededError):
        validate_reconciliation_inputs(
            make_request(scopes=(make_scope(roots=(
                ObservationRootScope("c:/assets/a", ScopeCompleteness.COMPLETE),
                ObservationRootScope("c:/assets/b", ScopeCompleteness.COMPLETE),
            )),), limits=limits),
            make_snapshot(),
        )

    oversized_root = ObservationRootScope(
        "c:/assets",
        ScopeCompleteness.COMPLETE,
        inaccessible_subtrees=("a", "b"),
        access_failures=("a", "b"),
    )
    with pytest.raises(ReconciliationLimitExceededError):
        validate_reconciliation_inputs(make_request(scopes=(make_scope(roots=(oversized_root,)),), limits=limits), make_snapshot())

    filtered = ObservationScope(
        scope_id="scope-1",
        observed_at=NOW,
        source_id="scan-a",
        roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
        explicit_asset_ids=("RLG-001", "RLG-002"),
        inclusion_filters=ObservationFilters(included_extensions=("mov", "mp4")),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("a", "b")),
    )
    with pytest.raises(ReconciliationLimitExceededError):
        validate_reconciliation_inputs(make_request(scopes=(filtered,), limits=limits), make_snapshot())


def test_validate_rejects_duplicate_observation_ids_deterministically():
    request = make_request(
        observations=(
            make_observation("obs-1"),
            make_observation("obs-2"),
            make_observation("obs-1"),
            make_observation("obs-3"),
            make_observation("obs-2"),
        ),
        scopes=(make_scope(),),
    )

    errors = []
    for _ in range(2):
        with pytest.raises(DuplicateObservationIdError) as error_info:
            validate_reconciliation_inputs(request, make_snapshot())
        errors.append(error_info.value)

    assert [str(error) for error in errors] == [
        "Reconciliation request contains duplicate observation IDs.",
        "Reconciliation request contains duplicate observation IDs.",
    ]
    assert errors[0].context["observation_id"] == "obs-1"
    assert errors[0].context == errors[1].context


def test_validate_preserves_duplicate_observation_paths_for_later_matching():
    request = make_request(
        observations=(
            make_observation("obs-1", normalized_path="c:/assets/same.mov"),
            make_observation("obs-2", normalized_path="c:/assets/same.mov"),
        ),
        scopes=(make_scope(),),
    )

    result = validate_reconciliation_inputs(request, make_snapshot())

    assert tuple(observation.normalized_resolved_path for observation in result.request.observations) == (
        "c:/assets/same.mov",
        "c:/assets/same.mov",
    )


def test_validate_rejects_duplicate_scope_ids_and_unknown_observation_scope():
    with pytest.raises(InvalidReconciliationRequestError) as duplicate_scope:
        validate_reconciliation_inputs(
            make_request(scopes=(make_scope("scope-1"), make_scope("scope-1"))),
            make_snapshot(),
        )
    assert duplicate_scope.value.context["reason_code"] == "duplicate_scope_id"

    with pytest.raises(InvalidReconciliationRequestError) as unknown_scope:
        validate_reconciliation_inputs(
            make_request(observations=(make_observation(scope_id="missing-scope"),), scopes=(make_scope(),)),
            make_snapshot(),
        )
    assert unknown_scope.value.context["reason_code"] == "unknown_observation_scope"


def test_validate_rejects_empty_scopes_duplicate_roots_and_duplicate_explicit_failures():
    with pytest.raises(InvalidReconciliationRequestError) as empty_scope:
        validate_reconciliation_inputs(
            make_request(scopes=(ObservationScope("scope-1", NOW, "scan-a"),)),
            make_snapshot(),
        )
    assert empty_scope.value.context["reason_code"] == "empty_scope"

    duplicate_roots = make_scope(
        roots=(
            ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),
            ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),
        )
    )
    with pytest.raises(AmbiguousEquivalentRootError):
        validate_reconciliation_inputs(make_request(scopes=(duplicate_roots,)), make_snapshot())

    duplicate_failures = ObservationScope(
        scope_id="scope-1",
        observed_at=NOW,
        source_id="scan-a",
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_failures=(
            ExplicitAssetAccessFailure("RLG-001", "access_denied", "Denied."),
            ExplicitAssetAccessFailure("RLG-001", "access_denied", "Denied."),
        ),
    )
    with pytest.raises(InvalidReconciliationRequestError) as failure_error:
        validate_reconciliation_inputs(make_request(scopes=(duplicate_failures,)), make_snapshot())
    assert failure_error.value.context["reason_code"] == "duplicate_explicit_failure"


def test_validate_rejects_duplicate_registry_asset_ids_but_preserves_duplicate_registry_paths():
    duplicate_asset_snapshot = make_snapshot(
        records=(make_record("RLG-001", record_id=1), make_record("RLG-001", record_id=2, normalized_path="c:/assets/b.mov"))
    )
    with pytest.raises(InvalidRegistrySnapshotError) as error_info:
        validate_reconciliation_inputs(make_request(), duplicate_asset_snapshot)
    assert error_info.value.context["reason_code"] == "duplicate_registry_asset_id"

    duplicate_path_snapshot = make_snapshot(
        records=(
            make_record("RLG-001", record_id=1, normalized_path="c:/assets/same.mov"),
            make_record("RLG-002", record_id=2, normalized_path="c:/assets/same.mov"),
        )
    )
    result = validate_reconciliation_inputs(make_request(), duplicate_path_snapshot)
    assert tuple(record.normalized_resolved_path for record in result.snapshot.records) == (
        "c:/assets/same.mov",
        "c:/assets/same.mov",
    )


def test_validate_registry_evidence_reference_and_structure_rules():
    with pytest.raises(InvalidRegistrySnapshotError) as orphan_error:
        validate_reconciliation_inputs(
            make_request(),
            make_snapshot(records=(make_record(),), evidence=(make_evidence("RLG-404"),)),
        )
    assert orphan_error.value.context["reason_code"] == "orphaned_registry_evidence"

    malformed = replace(make_evidence("RLG-001"), algorithm=None)
    with pytest.raises(InvalidRegistrySnapshotError) as malformed_error:
        validate_reconciliation_inputs(
            make_request(),
            make_snapshot(records=(make_record(),), evidence=(malformed,)),
        )
    assert malformed_error.value.context["reason_code"] == "invalid_registry_evidence"


def test_validate_registry_evidence_deduplication_is_order_independent():
    older = make_evidence("RLG-001", observed_at=NOW.replace(hour=10))
    newer = make_evidence("RLG-001", observed_at=NOW.replace(hour=11))
    record = make_record()

    first = validate_reconciliation_inputs(make_request(), make_snapshot(records=(record,), evidence=(older, newer)))
    second = validate_reconciliation_inputs(make_request(), make_snapshot(records=(record,), evidence=(newer, older)))

    assert first.snapshot.identity_evidence == (newer,)
    assert second.snapshot.identity_evidence == (newer,)


def test_validate_registry_evidence_mixed_optional_keys_are_deterministic():
    older_duplicate = make_metadata_evidence(
        value="windows:C:/Users/Paul/secret.mov",
        algorithm=None,
        scope_id=None,
        observed_at=NOW.replace(hour=8),
    )
    newer_duplicate = replace(older_duplicate, observed_at=NOW.replace(hour=9))
    latest_duplicate = replace(older_duplicate, observed_at=NOW.replace(hour=10))
    mixed_evidence = (
        older_duplicate,
        make_metadata_evidence(value="uri:file:///tmp/private.mov", algorithm="sha256", scope_id=None),
        make_metadata_evidence(value=r"unc:\\server\share\clip.mov", algorithm=None, scope_id="scope-a"),
        make_metadata_evidence(value="sk-test-secret", algorithm="sha256", scope_id="scope-a"),
        make_metadata_evidence(value="line-one\nline-two", algorithm="sha512", scope_id="scope-a"),
        make_metadata_evidence(value="a" * 64, algorithm="sha256", scope_id="scope-b"),
        newer_duplicate,
        latest_duplicate,
    )
    reversed_evidence = tuple(reversed(mixed_evidence))
    snapshot = make_snapshot(records=(make_record(),), evidence=mixed_evidence)
    before_snapshot = repr(snapshot)

    first = validate_reconciliation_inputs(make_request(), snapshot)
    second = validate_reconciliation_inputs(make_request(), make_snapshot(records=(make_record(),), evidence=reversed_evidence))
    third = validate_reconciliation_inputs(make_request(), snapshot)

    first_keys = tuple(evidence.canonical_identity_key() for evidence in first.snapshot.identity_evidence)
    second_keys = tuple(evidence.canonical_identity_key() for evidence in second.snapshot.identity_evidence)
    assert first_keys == second_keys
    assert first == third
    assert len(first.snapshot.identity_evidence) == 6
    assert latest_duplicate in first.snapshot.identity_evidence
    assert older_duplicate not in first.snapshot.identity_evidence
    assert newer_duplicate not in first.snapshot.identity_evidence
    assert len({evidence.canonical_identity_key() for evidence in first.snapshot.identity_evidence}) == 6
    assert repr(snapshot) == before_snapshot


def test_validate_registry_evidence_equal_timestamp_tie_break_is_canonical():
    lower = make_metadata_evidence(value="same-value", normalization_format="format-a")
    upper = make_metadata_evidence(value="same-value", normalization_format="format-z")
    snapshot_a = make_snapshot(records=(make_record(),), evidence=(lower, upper))
    snapshot_b = make_snapshot(records=(make_record(),), evidence=(upper, lower))
    before_a = repr(snapshot_a)
    before_b = repr(snapshot_b)

    first = validate_reconciliation_inputs(make_request(), snapshot_a)
    second = validate_reconciliation_inputs(make_request(), snapshot_b)

    assert first == second
    assert first.snapshot.identity_evidence == (upper,)
    assert second.snapshot.identity_evidence == (upper,)
    assert repr(snapshot_a) == before_a
    assert repr(snapshot_b) == before_b


def test_validate_registry_evidence_equal_timestamp_multirow_permutations_choose_same_winner():
    lowest = make_metadata_evidence(value="same-value", normalization_format="format-a")
    middle = make_metadata_evidence(value="same-value", normalization_format="format-m")
    highest = make_metadata_evidence(value="same-value", normalization_format="format-z")
    representative_orders = (
        (lowest, middle, highest),
        (highest, lowest, middle),
        (middle, highest, lowest),
    )

    results = tuple(
        validate_reconciliation_inputs(
            make_request(),
            make_snapshot(records=(make_record(),), evidence=evidence_order),
        )
        for evidence_order in representative_orders
    )

    assert all(result.snapshot.identity_evidence == (highest,) for result in results)
    assert results[0] == results[1] == results[2]


def test_validate_registry_evidence_latest_timestamp_precedes_canonical_tie_break():
    earlier_canonical_winner = make_metadata_evidence(
        value="same-value",
        normalization_format="format-z",
        observed_at=NOW.replace(hour=10),
    )
    later_timestamp = make_metadata_evidence(
        value="same-value",
        normalization_format="format-a",
        observed_at=NOW.replace(hour=11),
    )

    result = validate_reconciliation_inputs(
        make_request(),
        make_snapshot(records=(make_record(),), evidence=(earlier_canonical_winner, later_timestamp)),
    )

    assert result.snapshot.identity_evidence == (later_timestamp,)


def test_validate_registry_evidence_distinct_identity_fields_remain_distinct():
    evidence = (
        make_metadata_evidence("RLG-001", value="same-value"),
        make_metadata_evidence("RLG-002", value="same-value"),
        RegistryIdentityEvidence(
            asset_id="RLG-001",
            evidence_kind=EvidenceKind.DIAGNOSTIC,
            algorithm=None,
            normalized_value="same-value",
            normalization_format="text",
            scope_id=None,
            source_id="scan-a",
            observed_at=NOW,
        ),
        make_metadata_evidence("RLG-001", value="different-value"),
        make_metadata_evidence("RLG-001", value="same-value", algorithm="algo-a"),
        make_metadata_evidence("RLG-001", value="same-value", scope_id="scope-a"),
        make_metadata_evidence("RLG-001", value="same-value", source_id="scan-b"),
    )

    result = validate_reconciliation_inputs(
        make_request(),
        make_snapshot(records=(make_record("RLG-001"), make_record("RLG-002", record_id=2)), evidence=evidence),
    )

    assert len(result.snapshot.identity_evidence) == len(evidence)
    assert {item.canonical_identity_key() for item in result.snapshot.identity_evidence} == {
        item.canonical_identity_key() for item in evidence
    }


def test_validate_sanitizes_path_digest_token_and_control_payloads():
    hostile_id = "sk-test-secret"
    request = make_request(
        observations=(
            make_observation(hostile_id),
            make_observation(hostile_id),
        ),
        scopes=(make_scope(),),
    )

    with pytest.raises(DuplicateObservationIdError) as error_info:
        validate_reconciliation_inputs(request, make_snapshot())

    for surface in error_surfaces(error_info.value):
        assert "sk-test-secret" not in surface
        assert r"C:\Users\Paul\secret.mov" not in surface
        assert "/home/paul/secret.mov" not in surface
        assert "a" * 64 not in surface
        assert "line-one\nline-two" not in surface
        assert "0x" not in surface


def test_validate_does_not_mutate_inputs_and_repeated_output_is_equal():
    request = make_request(observations=(make_observation(),), scopes=(make_scope(),))
    snapshot = make_snapshot(records=(make_record(),), evidence=(make_evidence(),))
    before_request = repr(request)
    before_snapshot = repr(snapshot)

    first = validate_reconciliation_inputs(request, snapshot)
    second = validate_reconciliation_inputs(request, snapshot)

    assert first == second
    assert repr(request) == before_request
    assert repr(snapshot) == before_snapshot


def test_validate_handles_large_unique_inputs_with_indexed_duplicate_checks():
    count = 200
    observations = tuple(
        make_observation(f"obs-{index:03d}", normalized_path=f"c:/assets/{index:03d}.mov") for index in range(count)
    )
    records = tuple(
        make_record(f"RLG-{index:03d}", record_id=index, normalized_path=f"c:/assets/{index:03d}.mov")
        for index in range(count)
    )

    result = validate_reconciliation_inputs(
        make_request(observations=observations, scopes=(make_scope(),)),
        make_snapshot(records=records),
    )

    assert len(result.request.observations) == count
    assert len(result.snapshot.records) == count


def test_unknown_trusted_asset_id_is_preserved_for_later_matching():
    observation = AssetObservation(
        observation_id="obs-1",
        source_id="scan-a",
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        normalized_resolved_path="c:/assets/unknown.mov",
        claimed_asset_id="RLG-404",
    )
    request = ReconciliationRequest(
        request_id="request-1",
        schema_version="1",
        created_at=NOW,
        observations=(observation,),
        scopes=(make_scope(),),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )
    snapshot = make_snapshot(records=(make_record("RLG-001"),))

    result = validate_reconciliation_inputs(request, snapshot)

    assert result.request.asset_id_trust_policy is AssetIdTrustPolicy.ALLOW_LISTED_SOURCES
    assert result.request.observations[0].claimed_asset_id == "RLG-404"
    assert result.snapshot.records[0].asset_id == "RLG-001"


def test_validate_rejects_duplicate_trusted_sources():
    request = ReconciliationRequest(
        request_id="request-1",
        schema_version="1",
        created_at=NOW,
        observations=(),
        scopes=(),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a", "scan-a"),
    )

    with pytest.raises(InvalidReconciliationRequestError) as error_info:
        validate_reconciliation_inputs(request, make_snapshot())

    assert error_info.value.context["reason_code"] == "duplicate_trusted_source"
