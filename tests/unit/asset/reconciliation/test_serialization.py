"""Tests for Phase 3 Slice 10 public plan serialization (``serialization.py``).

Implements the exhaustive test matrix from the approved "Phase 3 Slice 10
Implementation Contract -- serialization.py, Revision 3 (final)", section
10 (tests 1-20). Each test below is numbered in its docstring to match
that contract for traceability.

Builder helpers below are deliberately local to this module rather than
imported from ``test_planner.py`` -- local duplication is preferable to
cross-test-module coupling per the approved contract's testing guidance.
Unlike ``test_planner.py``, these builders construct ``ReconciliationPlan``
directly via its own constructor rather than driving the full validate ->
index -> match -> classify -> plan pipeline, since ``serialize_public_plan``
operates on an already-built plan and does not need the upstream pipeline
to produce one.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from redline_core.asset.reconciliation.enums import ConflictKind, PrimaryClassification
from redline_core.asset.reconciliation.exceptions import (
    ReconciliationInvariantError,
    ReconciliationLimitExceededError,
)
from redline_core.asset.reconciliation.limits import DEFAULT_LIMITS, ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import (
    RECONCILIATION_PLAN_SCHEMA_VERSION,
    PlanSummary,
    ReconciliationPlan,
    ReconciliationPlanItem,
)
from redline_core.asset.reconciliation.serialization import serialize_public_plan
from redline_core.asset.reconciliation.subjects import (
    MixedConflictSubject,
    ObservationGroupSubject,
    ObservationSubject,
    RegistryRecordGroupSubject,
    RegistryRecordSubject,
)


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Local fixture builders (deliberately not imported from test_planner.py)
# ---------------------------------------------------------------------------


def make_summary(**overrides) -> PlanSummary:
    defaults = dict(
        classifications={},
        severities={},
        action_kinds={},
        review_required_count=0,
        proposal_blocked_count=0,
        invalid_observation_count=0,
        conflict_count=0,
        unmatched_count=0,
    )
    defaults.update(overrides)
    return PlanSummary(**defaults)


def make_item(
    *,
    item_id: str = "item-000001",
    subject=None,
    primary_classification: PrimaryClassification = PrimaryClassification.UNCHANGED,
    findings: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    actions: tuple[str, ...] = (),
    requires_review: bool = False,
    proposal_blocked: bool = False,
) -> ReconciliationPlanItem:
    if subject is None:
        subject = RegistryRecordSubject(asset_id="A-1")
    return ReconciliationPlanItem(
        item_id=item_id,
        subject=subject,
        primary_classification=primary_classification,
        findings=findings,
        evidence_refs=evidence_refs,
        actions=actions,
        requires_review=requires_review,
        proposal_blocked=proposal_blocked,
    )


def make_plan(
    *,
    items: tuple[ReconciliationPlanItem, ...] = (),
    evidence: tuple[str, ...] = (),
    summary: PlanSummary | None = None,
    plan_id: str = "plan-req-1-snap-1",
    schema_version: str = RECONCILIATION_PLAN_SCHEMA_VERSION,
    request_id: str = "req-1",
    snapshot_id: str = "snap-1",
    registry_id: str = "reg-1",
    created_at: datetime = NOW,
    limit_policy_fingerprint: str = "fingerprint-abc",
    approved_root_context: str = "assets_path",
    repository_revision: str | None = None,
) -> ReconciliationPlan:
    if summary is None:
        summary = make_summary()
    return ReconciliationPlan(
        plan_id=plan_id,
        schema_version=schema_version,
        request_id=request_id,
        snapshot_id=snapshot_id,
        registry_id=registry_id,
        created_at=created_at,
        items=items,
        evidence=evidence,
        summary=summary,
        limit_policy_fingerprint=limit_policy_fingerprint,
        approved_root_context=approved_root_context,
        repository_revision=repository_revision,
    )


def canonical_bytes(result: dict) -> bytes:
    """Mirror the exact canonical representation defined by the contract."""
    return json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Test 1: exact top-level (and item) key set
# ---------------------------------------------------------------------------


def test_01_top_level_and_item_key_sets_are_exact():
    plan = make_plan(items=(make_item(),))

    result = serialize_public_plan(plan)

    assert set(result.keys()) == {
        "approved_root_context",
        "created_at",
        "evidence",
        "items",
        "limit_policy_fingerprint",
        "plan_id",
        "registry_id",
        "repository_revision",
        "request_id",
        "schema_version",
        "snapshot_id",
        "summary",
    }
    assert set(result["items"][0].keys()) == {
        "actions",
        "evidence_refs",
        "findings",
        "item_id",
        "primary_classification",
        "proposal_blocked",
        "requires_review",
        "subject",
    }


# ---------------------------------------------------------------------------
# Test 2: every PlanSubject variant, correct subject_type and field set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject,expected",
    [
        (
            RegistryRecordSubject(asset_id="A-1"),
            {"asset_id": "A-1", "subject_type": "registry_record"},
        ),
        (
            ObservationSubject(observation_id="obs-1"),
            {"observation_id": "obs-1", "subject_type": "observation"},
        ),
        (
            RegistryRecordGroupSubject(asset_ids=("A-1", "A-2")),
            {"asset_ids": ["A-1", "A-2"], "subject_type": "registry_record_group"},
        ),
        (
            ObservationGroupSubject(observation_ids=("obs-1", "obs-2")),
            {"observation_ids": ["obs-1", "obs-2"], "subject_type": "observation_group"},
        ),
        (
            MixedConflictSubject(
                asset_ids=("A-1",), observation_ids=("obs-1",), conflict_kind=ConflictKind.CONTENT
            ),
            {
                "asset_ids": ["A-1"],
                "conflict_kind": "content",
                "observation_ids": ["obs-1"],
                "subject_type": "mixed_conflict",
            },
        ),
    ],
)
def test_02_every_subject_variant_serializes_with_correct_shape(subject, expected):
    plan = make_plan(items=(make_item(subject=subject),))

    result = serialize_public_plan(plan)

    assert result["items"][0]["subject"] == expected


# ---------------------------------------------------------------------------
# Test 3: enum values serialize to .value strings
# ---------------------------------------------------------------------------


def test_03_enum_values_serialize_as_value_strings_not_repr():
    subject = MixedConflictSubject(
        asset_ids=("A-1",), observation_ids=("obs-1",), conflict_kind=ConflictKind.CONTENT
    )
    item = make_item(primary_classification=PrimaryClassification.CONTENT_CONFLICT, subject=subject)
    plan = make_plan(items=(item,))

    result = serialize_public_plan(plan)

    assert result["items"][0]["primary_classification"] == "content_conflict"
    assert result["items"][0]["subject"]["conflict_kind"] == "content"


# ---------------------------------------------------------------------------
# Test 4: created_at serializes to isoformat
# ---------------------------------------------------------------------------


def test_04_created_at_serializes_to_isoformat():
    plan = make_plan(items=(make_item(),), created_at=NOW)

    result = serialize_public_plan(plan)

    assert result["created_at"] == NOW.isoformat()


# ---------------------------------------------------------------------------
# Test 5: tuple fields serialize as list, not tuple
# ---------------------------------------------------------------------------


def test_05_tuple_fields_serialize_as_lists():
    item = make_item(
        evidence_refs=("fact-a",),
        subject=RegistryRecordGroupSubject(asset_ids=("A-1", "A-2")),
    )
    plan = make_plan(items=(item,), evidence=("fact-a",))

    result = serialize_public_plan(plan)
    serialized_item = result["items"][0]

    assert type(result["evidence"]) is list
    assert type(serialized_item["actions"]) is list
    assert type(serialized_item["evidence_refs"]) is list
    assert type(serialized_item["findings"]) is list
    assert type(serialized_item["subject"]["asset_ids"]) is list


# ---------------------------------------------------------------------------
# Test 6: PlanSummary mappings serialize as plain dict, not MappingProxyType
# ---------------------------------------------------------------------------


def test_06_summary_mappings_serialize_as_plain_dict():
    summary = make_summary(classifications={"unchanged": 1})
    plan = make_plan(items=(make_item(),), summary=summary)

    result = serialize_public_plan(plan)

    assert type(result["summary"]["classifications"]) is dict
    assert type(result["summary"]["severities"]) is dict
    assert type(result["summary"]["action_kinds"]) is dict


# ---------------------------------------------------------------------------
# Test 7: no dangling evidence references survive serialization
# ---------------------------------------------------------------------------


def test_07_no_dangling_evidence_refs_in_serialized_output():
    item = make_item(evidence_refs=("fact-a", "fact-b"))
    plan = make_plan(items=(item,), evidence=("fact-a", "fact-b"))

    result = serialize_public_plan(plan)

    evidence_set = set(result["evidence"])
    for ref in result["items"][0]["evidence_refs"]:
        assert ref in evidence_set


# ---------------------------------------------------------------------------
# Test 8: deterministic canonical bytes, not dict equality alone
# ---------------------------------------------------------------------------


def test_08_deterministic_canonical_bytes_across_repeated_calls():
    plan = make_plan(items=(make_item(),))

    result_a = serialize_public_plan(plan)
    result_b = serialize_public_plan(plan)

    # Dict equality alone would not prove byte-identical canonical JSON
    # encoding (separators, key sorting, UTF-8 encoding, byte length) --
    # compare the exact canonical bytes, per the contract's definition.
    assert canonical_bytes(result_a) == canonical_bytes(result_b)


# ---------------------------------------------------------------------------
# Test 9: record_id never appears, whether set or None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("record_id", [None, 42])
def test_09_record_id_never_appears_in_public_subject(record_id):
    subject = RegistryRecordSubject(asset_id="A-1", record_id=record_id)
    plan = make_plan(items=(make_item(subject=subject),))

    result = serialize_public_plan(plan)
    serialized_subject = result["items"][0]["subject"]

    assert "record_id" not in serialized_subject
    assert set(serialized_subject.keys()) == {"asset_id", "subject_type"}


# ---------------------------------------------------------------------------
# Test 10: repository_revision present and absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repository_revision", [None, "rev-abc123"])
def test_10_repository_revision_present_and_absent(repository_revision):
    plan = make_plan(items=(make_item(),), repository_revision=repository_revision)

    result = serialize_public_plan(plan)

    assert result["repository_revision"] == repository_revision


# ---------------------------------------------------------------------------
# Test 11-13: size guard
# ---------------------------------------------------------------------------


def test_11_size_guard_at_exact_limit_succeeds():
    plan = make_plan(items=(make_item(),))
    baseline = serialize_public_plan(plan)
    exact_limit = len(canonical_bytes(baseline))
    tight_policy = ReconciliationLimitPolicy(max_serialized_public_plan_bytes=exact_limit)

    result = serialize_public_plan(plan, limit_policy=tight_policy)

    assert result == baseline


def test_12_size_guard_one_byte_over_limit_raises():
    plan = make_plan(items=(make_item(),))
    baseline = serialize_public_plan(plan)
    exact_limit = len(canonical_bytes(baseline))
    tight_policy = ReconciliationLimitPolicy(max_serialized_public_plan_bytes=exact_limit - 1)

    with pytest.raises(ReconciliationLimitExceededError) as error_info:
        serialize_public_plan(plan, limit_policy=tight_policy)

    assert error_info.value.context["limit_name"] == "max_serialized_public_plan_bytes"
    assert error_info.value.context["limit_value"] == exact_limit - 1


def test_13_caller_supplied_limit_policy_is_honored_not_always_default():
    plan = make_plan(items=(make_item(),))
    tiny_policy = ReconciliationLimitPolicy(max_serialized_public_plan_bytes=10)

    with pytest.raises(ReconciliationLimitExceededError):
        serialize_public_plan(plan, limit_policy=tiny_policy)

    # Confirms DEFAULT_LIMITS alone would not have raised for this plan --
    # the override, not a hardcoded default, is what triggered the failure.
    serialize_public_plan(plan, limit_policy=DEFAULT_LIMITS)


# ---------------------------------------------------------------------------
# Test 14: no mutation
# ---------------------------------------------------------------------------


def test_14_plan_is_not_mutated():
    def build() -> ReconciliationPlan:
        return make_plan(items=(make_item(evidence_refs=("fact-a",)),), evidence=("fact-a",))

    plan = build()
    expected = build()

    serialize_public_plan(plan)

    assert plan == expected


# ---------------------------------------------------------------------------
# Test 15-16: defensive type checks
# ---------------------------------------------------------------------------


def test_15_non_reconciliation_plan_raises():
    with pytest.raises(ReconciliationInvariantError) as error_info:
        serialize_public_plan("not-a-plan")

    assert error_info.value.context["reason_code"] == "serialization_invalid_input_type"


def test_16_non_limit_policy_raises():
    plan = make_plan(items=(make_item(),))

    with pytest.raises(ReconciliationInvariantError) as error_info:
        serialize_public_plan(plan, limit_policy="not-a-policy")

    assert error_info.value.context["reason_code"] == "serialization_invalid_input_type"


# ---------------------------------------------------------------------------
# Test 17: empty plan
# ---------------------------------------------------------------------------


def test_17_empty_plan_serializes_successfully():
    plan = make_plan(items=(), evidence=())

    result = serialize_public_plan(plan)

    assert result["items"] == []
    assert result["evidence"] == []
    assert result["summary"]["classifications"] == {}
    assert result["summary"]["severities"] == {}
    assert result["summary"]["action_kinds"] == {}


# ---------------------------------------------------------------------------
# Test 18: multi-item plan, order preserved, full shape
# ---------------------------------------------------------------------------


def test_18_multi_item_plan_preserves_order_and_full_shape():
    items = (
        make_item(
            item_id="item-000001",
            subject=RegistryRecordSubject(asset_id="A-1"),
            primary_classification=PrimaryClassification.UNCHANGED,
        ),
        make_item(
            item_id="item-000002",
            subject=RegistryRecordSubject(asset_id="A-2"),
            primary_classification=PrimaryClassification.METADATA_DRIFT,
            evidence_refs=("fact-a",),
        ),
        make_item(
            item_id="item-000003",
            subject=RegistryRecordSubject(asset_id="A-3"),
            primary_classification=PrimaryClassification.RECORD_NOT_OBSERVED,
        ),
        make_item(
            item_id="item-000004",
            subject=ObservationSubject(observation_id="obs-4"),
            primary_classification=PrimaryClassification.NEW_UNREGISTERED_OBSERVATION,
        ),
    )
    plan = make_plan(items=items, evidence=("fact-a",))

    result = serialize_public_plan(plan)

    assert [entry["item_id"] for entry in result["items"]] == [
        "item-000001",
        "item-000002",
        "item-000003",
        "item-000004",
    ]
    assert [entry["primary_classification"] for entry in result["items"]] == [
        "unchanged",
        "metadata_drift",
        "record_not_observed",
        "new_unregistered_observation",
    ]


# ---------------------------------------------------------------------------
# Test 19: not exported from the reconciliation package root
# ---------------------------------------------------------------------------


def test_19_serialize_public_plan_not_exported_from_package_root():
    import redline_core.asset.reconciliation as reconciliation

    assert not hasattr(reconciliation, "serialize_public_plan")


# ---------------------------------------------------------------------------
# Test 20: no PublicPlanSerializer symbol
# ---------------------------------------------------------------------------


def test_20_no_public_plan_serializer_symbol():
    from redline_core.asset.reconciliation import serialization as serialization_module

    assert not hasattr(serialization_module, "PublicPlanSerializer")
