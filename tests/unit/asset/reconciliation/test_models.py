"""Tests for reconciliation immutable foundational models."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
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
    PrimaryClassification,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ExplicitAssetAccessFailure,
    ObservationFilters,
    ObservationRootScope,
    ObservationScope,
    PlanSummary,
    ReconciliationPlan,
    ReconciliationPlanItem,
    ReconciliationRequest,
    RegistryIdentityEvidence,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.subjects import ObservationSubject


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def exception_surfaces(error: Exception) -> tuple[str, ...]:
    return (str(error), repr(error), repr(error.args), repr(vars(error)))


def make_record(asset_id: str = "RLG-001") -> AssetRegistryRecord:
    return AssetRegistryRecord(
        record_id=1,
        asset_id=asset_id,
        declared_path="logos/lower_third.png",
        resolved_path="C:/assets/logos/lower_third.png",
        normalized_resolved_path="c:/assets/logos/lower_third.png",
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


def make_observation() -> AssetObservation:
    return AssetObservation(
        observation_id="obs-1",
        source_id="scan-a",
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        normalized_resolved_path="c:/assets/logos/lower_third.png",
        file_size_bytes=10,
        file_modified_at=NOW,
        content_hashes=[("sha256", "abc")],  # type: ignore[arg-type]
        diagnostics=["ok"],  # type: ignore[arg-type]
        metadata={"safe": "value"},
    )


def make_scope() -> ObservationScope:
    return ObservationScope(
        scope_id="scope-1",
        observed_at=NOW,
        source_id="scan-a",
        roots=[
            ObservationRootScope(
                normalized_root_key="c:/assets",
                completeness=ScopeCompleteness.COMPLETE,
                inaccessible_subtrees=["c:/assets/private"],  # type: ignore[arg-type]
            )
        ],  # type: ignore[arg-type]
        explicit_asset_ids=["RLG-001"],  # type: ignore[arg-type]
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
        explicit_asset_id_failures=[
            ExplicitAssetAccessFailure("RLG-002", "access_denied", "Access denied.")
        ],  # type: ignore[arg-type]
        inclusion_filters=ObservationFilters(included_lifecycle_states=[AssetLifecycle.ACTIVE]),  # type: ignore[arg-type]
    )


def make_evidence() -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id="RLG-001",
        evidence_kind=EvidenceKind.FULL_CONTENT_HASH,
        algorithm="SHA256",
        normalized_value="abc",
        normalization_format="hex",
        scope_id=None,
        source_id="scan-a",
        observed_at=NOW,
    )


def make_plan_item(item_id: str = "item-000001") -> ReconciliationPlanItem:
    return ReconciliationPlanItem(
        item_id=item_id,
        subject=ObservationSubject("obs-1"),
        primary_classification=PrimaryClassification.DIAGNOSTIC_ONLY,
        findings=["finding-000001"],  # type: ignore[arg-type]
        evidence_refs=["evidence-000001"],  # type: ignore[arg-type]
        actions=["action-000001"],  # type: ignore[arg-type]
    )


def assert_exact_type_error_is_sanitized(error: Exception) -> None:
    for surface in exception_surfaces(error):
        assert "Evil" not in surface
        assert "Grandchild" not in surface
        assert "repr must not be called" not in surface
        assert "str must not be called" not in surface
        assert "secret-list-payload" not in surface
        assert "sk-test-subclass-secret" not in surface
        assert "0x" not in surface


def test_observation_models_are_frozen_and_convert_sequences_to_tuples():
    observation = make_observation()

    assert observation.content_hashes == (("sha256", "abc"),)
    assert observation.diagnostics == ("ok",)
    assert observation.metadata["safe"] == "value"
    assert observation.canonical_key() == ("obs-1",)
    with pytest.raises(FrozenInstanceError):
        observation.observation_id = "obs-2"  # type: ignore[misc]
    with pytest.raises(TypeError):
        observation.metadata["safe"] = "changed"  # type: ignore[index]


def test_scope_models_are_frozen_and_convert_sequences_to_tuples():
    scope = make_scope()

    assert scope.roots[0].inaccessible_subtrees == ("c:/assets/private",)
    assert scope.explicit_asset_ids == ("RLG-001",)
    assert scope.explicit_asset_id_failures[0].canonical_key() == ("RLG-002", "access_denied")
    assert scope.inclusion_filters.included_lifecycle_states == (AssetLifecycle.ACTIVE,)
    assert scope.roots[0].canonical_key() == ("c:", "assets")


def test_registry_snapshot_and_identity_evidence_are_immutable():
    evidence = make_evidence()
    snapshot = RegistrySnapshot(
        records=[make_record()],  # type: ignore[arg-type]
        identity_evidence=[evidence],  # type: ignore[arg-type]
        schema_version="1",
        snapshot_id="snapshot-1",
        snapshot_created_at=NOW,
        registry_id="registry-1",
        approved_root_context="root-context-1",
    )

    assert evidence.canonical_identity_key() == ("RLG-001", "full_content_hash", "sha256", "abc", None, "scan-a")
    assert snapshot.records == (make_record(),)
    assert snapshot.identity_evidence == (evidence,)
    assert snapshot.canonical_key() == ("registry-1", "1", "snapshot-1")


def test_request_model_is_immutable_and_uses_default_trust_policy_and_limits():
    request = ReconciliationRequest(
        request_id="request-1",
        schema_version="1",
        created_at=NOW,
        observations=[make_observation()],  # type: ignore[arg-type]
        scopes=[make_scope()],  # type: ignore[arg-type]
        trusted_asset_id_source_ids=["scan-b", "scan-a"],  # type: ignore[arg-type]
        request_metadata={"operator": "test"},
    )

    assert request.asset_id_trust_policy is AssetIdTrustPolicy.REJECT_ALL
    assert request.limit_policy is DEFAULT_LIMITS
    assert request.observations == (make_observation(),)
    assert request.scopes == (make_scope(),)
    assert request.trusted_asset_id_source_ids == ("scan-a", "scan-b")
    assert request.request_metadata["operator"] == "test"
    assert request.canonical_key() == ("1", "request-1")


def test_request_can_enable_allowlisted_asset_id_policy_without_global_state():
    request = ReconciliationRequest(
        request_id="request-1",
        schema_version="1",
        created_at=NOW,
        observations=(),
        scopes=(),
        asset_id_trust_policy=AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
        trusted_asset_id_source_ids=("scan-a",),
    )

    assert request.asset_id_trust_policy is AssetIdTrustPolicy.ALLOW_LISTED_SOURCES
    assert request.trusted_asset_id_source_ids == ("scan-a",)


def test_models_reject_non_utc_timestamps_and_invalid_enums():
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        AssetObservation(
            observation_id="obs-1",
            source_id="scan-a",
            source_kind=ObservationKind.FILESYSTEM_SCAN,
            observed_at=datetime(2026, 7, 27, 12, 0),
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
        )

    with pytest.raises(ValueError, match="source_kind"):
        AssetObservation(
            observation_id="obs-1",
            source_id="scan-a",
            source_kind="filesystem_scan",  # type: ignore[arg-type]
            observed_at=NOW,
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
        )


def test_plan_output_shapes_are_immutable_without_planner_logic():
    item = make_plan_item()
    summary = PlanSummary(
        classifications={"diagnostic_only": 1},
        severities={"info": 1},
        action_kinds={"diagnostic_only": 1},
    )
    plan = ReconciliationPlan(
        plan_id="plan-1",
        schema_version="asset_reconciliation_plan.v1",
        request_id="request-1",
        snapshot_id="snapshot-1",
        registry_id="registry-1",
        created_at=NOW,
        items=[item],  # type: ignore[arg-type]
        evidence=["evidence-000001"],  # type: ignore[arg-type]
        summary=summary,
        limit_policy_fingerprint="limits-1",
        approved_root_context="root-context-1",
    )

    assert plan.items == (item,)
    assert plan.evidence == ("evidence-000001",)
    assert summary.classifications["diagnostic_only"] == 1
    with pytest.raises(TypeError):
        summary.classifications["diagnostic_only"] = 2  # type: ignore[index]


def test_request_observations_reject_subclasses_without_leaking_or_invoking_repr():
    class EvilObservation(AssetObservation):
        __slots__ = ("payload",)

        def __init__(self, payload: list[str]) -> None:
            super().__init__(
                observation_id="obs-evil",
                source_id="scan-a",
                source_kind=ObservationKind.FILESYSTEM_SCAN,
                observed_at=NOW,
                observation_scope_id="scope-1",
                availability=AssetAvailability.AVAILABLE,
                verification=AssetVerificationState.VERIFIED,
            )
            object.__setattr__(self, "payload", payload)

        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

        def __str__(self) -> str:
            raise AssertionError("str must not be called")

    observations = [make_observation()]
    request = ReconciliationRequest(
        request_id="request-base-observation",
        schema_version="1",
        created_at=NOW,
        observations=observations,  # type: ignore[arg-type]
        scopes=[],
    )
    observations.append(make_observation())
    assert request.observations == (make_observation(),)

    payload = ["secret-list-payload", "sk-test-subclass-secret"]
    with pytest.raises(ValueError) as error_info:
        ReconciliationRequest(
            request_id="request-evil-observation",
            schema_version="1",
            created_at=NOW,
            observations=[EvilObservation(payload)],  # type: ignore[list-item]
            scopes=[],
        )

    payload.append("mutated")
    assert_exact_type_error_is_sanitized(error_info.value)


def test_request_scopes_reject_empty_and_deep_subclasses():
    class EvilScope(ObservationScope):
        pass

    class GrandchildScope(EvilScope):
        pass

    request = ReconciliationRequest(
        request_id="request-base-scope",
        schema_version="1",
        created_at=NOW,
        observations=[],
        scopes=[make_scope()],  # type: ignore[arg-type]
    )
    assert request.scopes == (make_scope(),)

    for scope in [
        EvilScope(scope_id="evil-scope", observed_at=NOW, source_id="scan-a"),
        GrandchildScope(scope_id="grandchild-scope", observed_at=NOW, source_id="scan-a"),
    ]:
        with pytest.raises(ValueError) as error_info:
            ReconciliationRequest(
                request_id="request-subclass-scope",
                schema_version="1",
                created_at=NOW,
                observations=[],
                scopes=[scope],  # type: ignore[list-item]
            )
        assert_exact_type_error_is_sanitized(error_info.value)


def test_registry_snapshot_records_reject_subclasses():
    class EvilRecord(AssetRegistryRecord):
        pass

    record = make_record()
    records = [record]
    snapshot = RegistrySnapshot(
        records=records,  # type: ignore[arg-type]
        identity_evidence=[],
        schema_version="1",
        snapshot_id="snapshot-base-record",
        snapshot_created_at=NOW,
        registry_id="registry-1",
        approved_root_context="root-context-1",
    )
    records.append(make_record("RLG-002"))
    assert snapshot.records == (record,)

    evil_record = EvilRecord(
        record_id=2,
        asset_id="RLG-099",
        declared_path="logos/evil.png",
        resolved_path="C:/assets/logos/evil.png",
        normalized_resolved_path="c:/assets/logos/evil.png",
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
    object.__setattr__(evil_record, "payload", ["secret-list-payload"])

    with pytest.raises(ValueError) as error_info:
        RegistrySnapshot(
            records=[evil_record],  # type: ignore[list-item]
            identity_evidence=[],
            schema_version="1",
            snapshot_id="snapshot-evil-record",
            snapshot_created_at=NOW,
            registry_id="registry-1",
            approved_root_context="root-context-1",
        )
    assert_exact_type_error_is_sanitized(error_info.value)


def test_registry_snapshot_identity_evidence_rejects_subclasses():
    class EvilEvidence(RegistryIdentityEvidence):
        __slots__ = ("payload",)

        def __init__(self) -> None:
            super().__init__(
                asset_id="RLG-001",
                evidence_kind=EvidenceKind.FULL_CONTENT_HASH,
                algorithm="SHA256",
                normalized_value="abc",
                normalization_format="hex",
                scope_id=None,
                source_id="scan-a",
                observed_at=NOW,
            )
            object.__setattr__(self, "payload", ["secret-list-payload"])

    evidence = make_evidence()
    snapshot = RegistrySnapshot(
        records=[],
        identity_evidence=[evidence],  # type: ignore[arg-type]
        schema_version="1",
        snapshot_id="snapshot-base-evidence",
        snapshot_created_at=NOW,
        registry_id="registry-1",
        approved_root_context="root-context-1",
    )
    assert snapshot.identity_evidence == (evidence,)

    with pytest.raises(ValueError) as error_info:
        RegistrySnapshot(
            records=[],
            identity_evidence=[EvilEvidence()],  # type: ignore[list-item]
            schema_version="1",
            snapshot_id="snapshot-evil-evidence",
            snapshot_created_at=NOW,
            registry_id="registry-1",
            approved_root_context="root-context-1",
        )
    assert_exact_type_error_is_sanitized(error_info.value)


def test_observation_scope_roots_reject_subclasses():
    class EvilRoot(ObservationRootScope):
        __slots__ = ("payload",)

        def __init__(self) -> None:
            super().__init__("c:/assets", ScopeCompleteness.COMPLETE)
            object.__setattr__(self, "payload", ["secret-list-payload"])

    root = ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE)
    scope = ObservationScope(
        scope_id="scope-base-root",
        observed_at=NOW,
        source_id="scan-a",
        roots=[root],  # type: ignore[arg-type]
    )
    assert scope.roots == (root,)

    with pytest.raises(ValueError) as error_info:
        ObservationScope(
            scope_id="scope-evil-root",
            observed_at=NOW,
            source_id="scan-a",
            roots=[EvilRoot()],  # type: ignore[list-item]
        )
    assert_exact_type_error_is_sanitized(error_info.value)


def test_observation_scope_failures_reject_subclasses():
    class EvilFailure(ExplicitAssetAccessFailure):
        __slots__ = ("payload",)

        def __init__(self) -> None:
            super().__init__("RLG-002", "access_denied", "Access denied.")
            object.__setattr__(self, "payload", ["secret-list-payload"])

    failure = ExplicitAssetAccessFailure("RLG-002", "access_denied", "Access denied.")
    scope = ObservationScope(
        scope_id="scope-base-failure",
        observed_at=NOW,
        source_id="scan-a",
        explicit_asset_id_failures=[failure],  # type: ignore[arg-type]
    )
    assert scope.explicit_asset_id_failures == (failure,)

    with pytest.raises(ValueError) as error_info:
        ObservationScope(
            scope_id="scope-evil-failure",
            observed_at=NOW,
            source_id="scan-a",
            explicit_asset_id_failures=[EvilFailure()],  # type: ignore[list-item]
        )
    assert_exact_type_error_is_sanitized(error_info.value)


def test_reconciliation_plan_items_reject_subclasses_without_changing_order_or_duplicates():
    class EvilPlanItem(ReconciliationPlanItem):
        __slots__ = ("payload",)

        def __init__(self) -> None:
            super().__init__(
                item_id="item-evil",
                subject=ObservationSubject("obs-1"),
                primary_classification=PrimaryClassification.DIAGNOSTIC_ONLY,
            )
            object.__setattr__(self, "payload", ["secret-list-payload"])

    first = make_plan_item("item-000001")
    second = make_plan_item("item-000002")
    items = [first, second, first]
    plan = ReconciliationPlan(
        plan_id="plan-base-items",
        schema_version="asset_reconciliation_plan.v1",
        request_id="request-1",
        snapshot_id="snapshot-1",
        registry_id="registry-1",
        created_at=NOW,
        items=items,  # type: ignore[arg-type]
        evidence=[],
        summary=PlanSummary(classifications={}, severities={}, action_kinds={}),
        limit_policy_fingerprint="limits-1",
        approved_root_context="root-context-1",
    )
    items.append(second)
    assert plan.items == (first, second, first)

    with pytest.raises(ValueError) as error_info:
        ReconciliationPlan(
            plan_id="plan-evil-items",
            schema_version="asset_reconciliation_plan.v1",
            request_id="request-1",
            snapshot_id="snapshot-1",
            registry_id="registry-1",
            created_at=NOW,
            items=[EvilPlanItem()],  # type: ignore[list-item]
            evidence=[],
            summary=PlanSummary(classifications={}, severities={}, action_kinds={}),
            limit_policy_fingerprint="limits-1",
            approved_root_context="root-context-1",
        )
    assert_exact_type_error_is_sanitized(error_info.value)


def test_observation_metadata_is_deeply_frozen_against_caller_mutation():
    inner_list = ["one"]
    inner_dict = {"child": inner_list}
    list_of_dicts = [{"name": "first"}]
    metadata = {
        "nested_list": inner_list,
        "nested_dict": inner_dict,
        "list_of_dicts": list_of_dicts,
        "set_values": {"b", "a"},
    }

    observation = AssetObservation(
        observation_id="obs-deep",
        source_id="scan-a",
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        metadata=metadata,
    )
    before = repr(observation.metadata)

    metadata["outer"] = "changed"
    inner_list.append("two")
    inner_dict["new"] = "changed"
    list_of_dicts[0]["name"] = "changed"

    assert repr(observation.metadata) == before
    assert observation.metadata["nested_list"] == ("one",)
    assert observation.metadata["nested_dict"]["child"] == ("one",)
    assert observation.metadata["list_of_dicts"][0]["name"] == "first"
    assert observation.metadata["set_values"] == ("a", "b")
    with pytest.raises(TypeError):
        observation.metadata["outer"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        observation.metadata["nested_dict"]["child"] = "changed"  # type: ignore[index]


def test_observation_sequence_fields_are_deeply_frozen_against_caller_mutation():
    content_hash = ["sha256", "abc"]
    fingerprint = ["fp-a"]
    diagnostic = {"code": ["ok"]}
    content_hashes = [content_hash]
    fingerprints = [fingerprint]
    diagnostics = [diagnostic]

    observation = AssetObservation(
        observation_id="obs-sequences",
        source_id="scan-a",
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        content_hashes=content_hashes,  # type: ignore[arg-type]
        partial_fingerprints=fingerprints,  # type: ignore[arg-type]
        diagnostics=diagnostics,  # type: ignore[arg-type]
    )
    before = repr(observation)

    content_hash.append("mutated")
    fingerprint.append("mutated")
    diagnostic["code"].append("mutated")
    content_hashes.append(["sha256", "def"])
    fingerprints.append(["fp-b"])
    diagnostics.append({"code": ["bad"]})

    assert repr(observation) == before
    assert observation.content_hashes == (("sha256", "abc"),)
    assert observation.partial_fingerprints == (("fp-a",),)
    assert observation.diagnostics[0]["code"] == ("ok",)
    with pytest.raises(TypeError):
        observation.diagnostics[0]["code"] = "changed"  # type: ignore[index]


def test_scope_filters_and_request_metadata_are_deeply_frozen():
    extensions = {"mov", "mp4"}
    lifecycle_states = [AssetLifecycle.ACTIVE]
    root_failures = [["access-denied"]]
    request_metadata = {"nested": {"values": ["one"]}}

    scope = ObservationScope(
        scope_id="scope-deep",
        observed_at=NOW,
        source_id="scan-a",
        roots=[
            ObservationRootScope(
                normalized_root_key="c:/assets",
                completeness=ScopeCompleteness.COMPLETE,
                access_failures=root_failures,  # type: ignore[arg-type]
            )
        ],  # type: ignore[arg-type]
        inclusion_filters=ObservationFilters(
            included_extensions=extensions,  # type: ignore[arg-type]
            included_lifecycle_states=lifecycle_states,  # type: ignore[arg-type]
        ),
    )
    request = ReconciliationRequest(
        request_id="request-deep",
        schema_version="1",
        created_at=NOW,
        observations=[],
        scopes=[scope],  # type: ignore[arg-type]
        request_metadata=request_metadata,
    )
    before_scope = repr(scope)
    before_request_metadata = repr(request.request_metadata)

    extensions.add("avi")
    lifecycle_states.append(AssetLifecycle.DECLARED)
    root_failures[0].append("mutated")
    request_metadata["nested"]["values"].append("two")

    assert repr(scope) == before_scope
    assert scope.inclusion_filters.included_extensions == ("mov", "mp4")
    assert scope.inclusion_filters.included_lifecycle_states == (AssetLifecycle.ACTIVE,)
    assert scope.roots[0].access_failures == (("access-denied",),)
    assert repr(request.request_metadata) == before_request_metadata
    assert request.request_metadata["nested"]["values"] == ("one",)


def test_plan_summary_mappings_are_deeply_frozen_and_detached():
    classifications = {"diagnostic_only": 1}
    severities = {"info": 1}
    action_kinds = {"diagnostic_only": 1}
    summary = PlanSummary(classifications=classifications, severities=severities, action_kinds=action_kinds)

    classifications["changed"] = 2
    severities["warning"] = 1
    action_kinds["require_review"] = 1

    assert dict(summary.classifications) == {"diagnostic_only": 1}
    assert dict(summary.severities) == {"info": 1}
    assert dict(summary.action_kinds) == {"diagnostic_only": 1}
    with pytest.raises(TypeError):
        summary.action_kinds["changed"] = 2  # type: ignore[index]


def test_models_reject_cyclic_or_unsupported_nested_values_and_non_string_mapping_keys():
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(ValueError, match="cyclic"):
        AssetObservation(
            observation_id="obs-cycle",
            source_id="scan-a",
            source_kind=ObservationKind.FILESYSTEM_SCAN,
            observed_at=NOW,
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            metadata={"cyclic": cyclic},
        )

    with pytest.raises(ValueError, match="unsupported"):
        AssetObservation(
            observation_id="obs-object",
            source_id="scan-a",
            source_kind=ObservationKind.FILESYSTEM_SCAN,
            observed_at=NOW,
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            metadata={"object": object()},
        )

    with pytest.raises(ValueError, match="mapping keys"):
        AssetObservation(
            observation_id="obs-key",
            source_id="scan-a",
            source_kind=ObservationKind.FILESYSTEM_SCAN,
            observed_at=NOW,
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            metadata={1: "value"},  # type: ignore[dict-item]
        )


def test_models_reject_arbitrary_frozen_dataclass_with_list_without_leaking_payload():
    @dataclass(frozen=True)
    class MutableFrozen:
        values: list[str]

    payload = MutableFrozen([r"C:\sensitive\clip.mov", "sk-test-secret"])

    with pytest.raises(ValueError) as error_info:
        AssetObservation(
            observation_id="obs-frozen-list",
            source_id="scan-a",
            source_kind=ObservationKind.FILESYSTEM_SCAN,
            observed_at=NOW,
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            metadata={"payload": payload},
        )

    assert str(error_info.value) == "dataclass values are not supported."
    for surface in exception_surfaces(error_info.value):
        assert "MutableFrozen" not in surface
        assert r"C:\sensitive\clip.mov" not in surface
        assert "sk-test-secret" not in surface
        assert "0x" not in surface


def test_models_reject_arbitrary_frozen_dataclass_with_dictionary_without_leaking_payload():
    @dataclass(frozen=True)
    class MutableFrozen:
        values: dict[str, str]

    payload = MutableFrozen({"path": "/home/paul/private.mov", "digest": "a" * 64})

    with pytest.raises(ValueError) as error_info:
        ReconciliationRequest(
            request_id="request-dataclass",
            schema_version="1",
            created_at=NOW,
            observations=[],
            scopes=[],
            request_metadata={"payload": payload},
        )

    assert str(error_info.value) == "dataclass values are not supported."
    for surface in exception_surfaces(error_info.value):
        assert "MutableFrozen" not in surface
        assert "/home/paul/private.mov" not in surface
        assert "a" * 64 not in surface
        assert "0x" not in surface


def test_models_reject_nested_arbitrary_dataclasses_without_reconstruction():
    @dataclass
    class MutableInner:
        values: list[str]

    @dataclass(frozen=True)
    class FrozenOuter:
        inner: MutableInner

    inner_values = ["password=example"]
    payload = FrozenOuter(MutableInner(inner_values))

    with pytest.raises(ValueError) as error_info:
        AssetObservation(
            observation_id="obs-nested-dataclass",
            source_id="scan-a",
            source_kind=ObservationKind.FILESYSTEM_SCAN,
            observed_at=NOW,
            observation_scope_id="scope-1",
            availability=AssetAvailability.AVAILABLE,
            verification=AssetVerificationState.VERIFIED,
            diagnostics=[payload],  # type: ignore[list-item]
        )

    inner_values.append("mutated")
    assert str(error_info.value) == "dataclass values are not supported."
    for surface in exception_surfaces(error_info.value):
        assert "FrozenOuter" not in surface
        assert "MutableInner" not in surface
        assert "password=example" not in surface
        assert "mutated" not in surface


def test_models_reject_arbitrary_non_frozen_dataclass_and_custom_object():
    @dataclass
    class MutableDataclass:
        value: str

    unsupported_values = [
        MutableDataclass("Bearer test-token"),
        object(),
    ]

    for value in unsupported_values:
        with pytest.raises(ValueError) as error_info:
            AssetObservation(
                observation_id="obs-unsupported",
                source_id="scan-a",
                source_kind=ObservationKind.FILESYSTEM_SCAN,
                observed_at=NOW,
                observation_scope_id="scope-1",
                availability=AssetAvailability.AVAILABLE,
                verification=AssetVerificationState.VERIFIED,
                metadata={"value": value},
            )
        for surface in exception_surfaces(error_info.value):
            assert "Bearer test-token" not in surface
            assert "0x" not in surface


def test_deep_freeze_still_accepts_approved_scalars_and_nested_containers():
    metadata = {
        "none": None,
        "bool": True,
        "int": 1,
        "float": 1.5,
        "str": "safe",
        "bytes": b"safe",
        "enum": ObservationKind.MANUAL,
        "timestamp": NOW,
        "mapping": {"items": ["one"]},
        "tuple_with_list": (["two"],),
        "set": {"b", "a"},
    }

    observation = AssetObservation(
        observation_id="obs-approved-scalars",
        source_id="scan-a",
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        metadata=metadata,
    )
    metadata["mapping"]["items"].append("mutated")  # type: ignore[index]
    metadata["tuple_with_list"][0].append("mutated")  # type: ignore[index]
    metadata["set"].add("c")  # type: ignore[union-attr]

    assert observation.metadata["none"] is None
    assert observation.metadata["bool"] is True
    assert observation.metadata["int"] == 1
    assert observation.metadata["float"] == 1.5
    assert observation.metadata["str"] == "safe"
    assert observation.metadata["bytes"] == b"safe"
    assert observation.metadata["enum"] is ObservationKind.MANUAL
    assert observation.metadata["timestamp"] == NOW
    assert observation.metadata["mapping"]["items"] == ("one",)
    assert observation.metadata["tuple_with_list"] == (("two",),)
    assert observation.metadata["set"] == ("a", "b")
