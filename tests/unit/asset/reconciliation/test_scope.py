"""Tests for Phase 3 Slice 4 deterministic scope evaluation."""
from __future__ import annotations

import dataclasses
import os
import random
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import ScopeCompleteness
from redline_core.asset.reconciliation.models import (
    ExplicitAssetAccessFailure,
    ObservationFilters,
    ObservationRootScope,
    ObservationScope,
)
from redline_core.asset.reconciliation.scope import (
    ObservabilityDecision,
    _containing_roots,
    _most_specific_root,
    _normalized_key_components,
    evaluate_record_observability,
)


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def make_record(
    asset_id: str = "RLG-001",
    *,
    normalized_path: str | None = "c:/assets/logos/lower_third.png",
) -> AssetRegistryRecord:
    return AssetRegistryRecord(
        record_id=1,
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


def make_root(
    normalized_root_key: str,
    *,
    completeness: ScopeCompleteness = ScopeCompleteness.COMPLETE,
    inaccessible_subtrees: tuple[str, ...] = (),
    access_failures: tuple[str, ...] = (),
) -> ObservationRootScope:
    return ObservationRootScope(
        normalized_root_key=normalized_root_key,
        completeness=completeness,
        inaccessible_subtrees=inaccessible_subtrees,
        access_failures=access_failures,
    )


def make_scope(
    scope_id: str = "scope-1",
    *,
    roots: tuple[ObservationRootScope, ...] = (),
    explicit_asset_ids: tuple[str, ...] = (),
    explicit_asset_id_completeness: ScopeCompleteness = ScopeCompleteness.UNKNOWN,
    explicit_asset_id_failures: tuple[ExplicitAssetAccessFailure, ...] = (),
    inclusion_filters: ObservationFilters = ObservationFilters(),
    exclusion_filters: ObservationFilters = ObservationFilters(),
) -> ObservationScope:
    return ObservationScope(
        scope_id=scope_id,
        observed_at=NOW,
        source_id="scan-a",
        roots=roots,
        explicit_asset_ids=explicit_asset_ids,
        explicit_asset_id_completeness=explicit_asset_id_completeness,
        explicit_asset_id_failures=explicit_asset_id_failures,
        inclusion_filters=inclusion_filters,
        exclusion_filters=exclusion_filters,
    )


# ---------------------------------------------------------------------------
# Root containment
# ---------------------------------------------------------------------------


def test_exact_root_match_is_containing():
    root = make_root("c:/assets/logos/lower_third.png")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logos/lower_third.png")

    decision = evaluate_record_observability(record, scope)

    assert "path" in decision.applicable_channels


def test_descendant_path_is_containing():
    root = make_root("c:/assets")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logos/deep/lower_third.png")

    decision = evaluate_record_observability(record, scope)

    assert "path" in decision.applicable_channels


def test_sibling_path_does_not_match_component_wise():
    """`c:/assets/a` must not falsely contain `c:/assets/ab/...` via raw string prefix."""
    root = make_root("c:/assets/a")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/ab/file.mov")

    decision = evaluate_record_observability(record, scope)

    assert "path" not in decision.applicable_channels
    assert decision.expected_observable is False


def test_component_safe_containment_helper_directly():
    components = _normalized_key_components("c:/assets/ab/file.mov")
    root = make_root("c:/assets/a")

    assert root.canonical_key() not in (components[: len(root.canonical_key())],)  # sanity: not equal
    assert _containing_roots(components, make_scope(roots=(root,))) == ()


def test_no_usable_record_path_is_not_applicable():
    root = make_root("c:/assets")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert "path" not in decision.applicable_channels
    assert decision.expected_observable is False
    assert decision.missing_eligible is False


def test_no_containing_roots_is_not_applicable():
    root = make_root("c:/archive")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert "path" not in decision.applicable_channels


# ---------------------------------------------------------------------------
# Most-specific root
# ---------------------------------------------------------------------------


def test_most_specific_root_helper_picks_greatest_depth():
    parent = make_root("c:/assets")
    child = make_root("c:/assets/logos")

    assert _most_specific_root((parent, child)) is child
    assert _most_specific_root((child, parent)) is child


def test_complete_parent_incomplete_child_child_controls():
    parent = make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE)
    child = make_root("c:/assets/logos", completeness=ScopeCompleteness.INCOMPLETE)
    scope = make_scope(roots=(parent, child))
    record = make_record(normalized_path="c:/assets/logos/lower_third.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is False
    assert decision.missing_eligible is False


def test_incomplete_parent_complete_child_child_controls():
    parent = make_root("c:/assets", completeness=ScopeCompleteness.INCOMPLETE)
    child = make_root("c:/assets/logos", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(roots=(parent, child))
    record = make_record(normalized_path="c:/assets/logos/lower_third.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True
    assert decision.missing_eligible is True


def test_reversed_root_order_same_result():
    parent = make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE)
    child = make_root("c:/assets/logos", completeness=ScopeCompleteness.INCOMPLETE)
    record = make_record(normalized_path="c:/assets/logos/lower_third.png")

    forward = evaluate_record_observability(record, make_scope(roots=(parent, child)))
    reversed_ = evaluate_record_observability(record, make_scope(roots=(child, parent)))

    assert forward == reversed_


def test_shuffled_root_order_same_result():
    roots = [
        make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE),
        make_root("c:/assets/logos", completeness=ScopeCompleteness.INCOMPLETE),
        make_root("c:/assets/logos/archive", completeness=ScopeCompleteness.COMPLETE),
    ]
    record = make_record(normalized_path="c:/assets/logos/archive/old.png")

    baseline = evaluate_record_observability(record, make_scope(roots=tuple(roots)))

    shuffled_roots = list(roots)
    random.Random(7).shuffle(shuffled_roots)
    shuffled = evaluate_record_observability(record, make_scope(roots=tuple(shuffled_roots)))

    assert baseline == shuffled


def test_longest_component_depth_not_longest_string():
    """A shorter-looking key with more components must win over a longer raw string."""
    short_but_deeper = make_root("c:/a/b/c", completeness=ScopeCompleteness.INCOMPLETE)
    long_but_shallower = make_root("c:/aaaaaaaaaa", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(roots=(long_but_shallower, short_but_deeper))
    record = make_record(normalized_path="c:/a/b/c/file.mov")

    decision = evaluate_record_observability(record, scope)

    # Only "c:/a/b/c" contains the record at all; longer string root is irrelevant.
    assert decision.expected_observable is False  # selected root (deeper) is INCOMPLETE


# ---------------------------------------------------------------------------
# Inaccessible subtrees
# ---------------------------------------------------------------------------


def test_selected_root_inaccessible_subtree_blocks_path_channel():
    root = make_root(
        "c:/assets",
        completeness=ScopeCompleteness.COMPLETE,
        inaccessible_subtrees=("c:/assets/locked",),
    )
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/locked/file.mov")

    decision = evaluate_record_observability(record, scope)

    assert "path" in decision.applicable_channels
    assert "path" in decision.blocked_channels
    assert "path" not in decision.complete_channels
    assert decision.expected_observable is False
    assert decision.missing_eligible is False
    assert "path_inaccessible_subtree" in decision.access_failure_reasons


def test_parent_inaccessible_does_not_affect_clean_selected_child():
    parent = make_root(
        "c:/assets",
        completeness=ScopeCompleteness.COMPLETE,
        inaccessible_subtrees=("c:/assets/locked",),
    )
    child = make_root("c:/assets/logos", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(roots=(parent, child))
    record = make_record(normalized_path="c:/assets/logos/lower_third.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True
    assert "path" not in decision.blocked_channels


def test_inaccessible_path_is_not_missing_eligible():
    root = make_root(
        "c:/assets",
        inaccessible_subtrees=("c:/assets/locked",),
    )
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/locked/deep/file.mov")

    decision = evaluate_record_observability(record, scope)

    assert decision.missing_eligible is False


def test_stable_access_failure_reason_no_raw_path_leakage():
    root = make_root(
        "c:/assets",
        inaccessible_subtrees=("c:/assets/very/secret/subtree",),
    )
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/very/secret/subtree/file.mov")

    decision = evaluate_record_observability(record, scope)

    assert decision.access_failure_reasons == ("path_inaccessible_subtree",)
    assert "secret" not in repr(decision)
    assert "c:/assets" not in repr(decision)


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------


def test_selected_root_exclusion_prevents_expected_observability():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/deprecated",)),
    )
    record = make_record(normalized_path="c:/assets/deprecated/old.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is False
    assert "path_excluded_subtree" in decision.exclusion_reasons


def test_excluded_record_is_not_missing_eligible():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/deprecated",)),
    )
    record = make_record(normalized_path="c:/assets/deprecated/old.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.missing_eligible is False


def test_exclusion_precedence_is_deterministic_across_root_order():
    roots = (
        make_root("c:/assets"),
        make_root("c:/assets/deprecated"),
    )
    scope = make_scope(
        roots=roots,
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/deprecated",)),
    )
    record = make_record(normalized_path="c:/assets/deprecated/old.png")

    forward = evaluate_record_observability(record, make_scope(
        roots=roots,
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/deprecated",)),
    ))
    backward = evaluate_record_observability(record, make_scope(
        roots=tuple(reversed(roots)),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/deprecated",)),
    ))

    assert forward == backward


def test_stable_exclusion_reason_no_raw_path_leakage():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/topsecret",)),
    )
    record = make_record(normalized_path="c:/assets/topsecret/file.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.exclusion_reasons == ("path_excluded_subtree",)
    assert "topsecret" not in repr(decision)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_one_inclusion_dimension_matching_record_passes():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        inclusion_filters=ObservationFilters(included_lifecycle_states=(AssetLifecycle.DECLARED,)),
    )
    record = make_record(normalized_path="c:/assets/logo.png")  # DECLARED lifecycle

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True


def test_multiple_inclusion_dimensions_use_and():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        inclusion_filters=ObservationFilters(
            included_lifecycle_states=(AssetLifecycle.ACTIVE,),  # record is DECLARED -> fails
            included_asset_ids=("RLG-001",),  # record matches this one
        ),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    # AND across dimensions: lifecycle dimension fails, so overall inclusion fails.
    assert decision.expected_observable is False


def test_multiple_values_within_one_dimension_use_or():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        inclusion_filters=ObservationFilters(included_asset_ids=("OTHER-ID", "RLG-001")),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True


def test_exclusion_match_rejects_record():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/logo.png",)),
    )
    record = make_record(normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is False


def test_non_matching_exclusion_does_not_reject():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/other",)),
    )
    record = make_record(normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True


def test_combined_inclusion_and_exclusion_behavior():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        inclusion_filters=ObservationFilters(included_lifecycle_states=(AssetLifecycle.DECLARED,)),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets/quarantine",)),
    )
    included_record = make_record(normalized_path="c:/assets/logo.png")
    excluded_record = make_record(normalized_path="c:/assets/quarantine/logo.png")

    included_decision = evaluate_record_observability(included_record, scope)
    excluded_decision = evaluate_record_observability(excluded_record, scope)

    assert included_decision.expected_observable is True
    assert excluded_decision.expected_observable is False


def test_no_undocumented_case_normalization():
    """Filters must not silently case-fold asset IDs beyond what the model defines."""
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        inclusion_filters=ObservationFilters(included_asset_ids=("rlg-001",)),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is False


# ---------------------------------------------------------------------------
# Explicit Asset-ID channel
# ---------------------------------------------------------------------------


def test_listed_id_with_complete_channel():
    scope = make_scope(
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert "explicit_asset_id" in decision.complete_channels
    assert decision.expected_observable is True
    assert decision.missing_eligible is True


def test_unlisted_id_not_applicable():
    scope = make_scope(
        explicit_asset_ids=("OTHER-ID",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert "explicit_asset_id" not in decision.applicable_channels
    assert decision.expected_observable is False


def test_listed_id_with_access_failure_is_blocked():
    scope = make_scope(
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
        explicit_asset_id_failures=(ExplicitAssetAccessFailure("RLG-001", "access_denied", "Denied."),),
    )
    record = make_record(asset_id="RLG-001", normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert "explicit_asset_id" in decision.blocked_channels
    assert "explicit_asset_id" not in decision.complete_channels
    assert decision.expected_observable is False
    assert decision.missing_eligible is False
    assert "explicit_access_failure" in decision.access_failure_reasons


def test_null_path_plus_complete_explicit_channel_is_observable():
    scope = make_scope(
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True
    assert decision.missing_eligible is True


def test_no_containing_root_plus_complete_explicit_channel_is_observable():
    root = make_root("c:/archive")
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert "path" not in decision.applicable_channels
    assert decision.expected_observable is True


def test_incomplete_path_plus_complete_explicit_channel_is_observable():
    root = make_root("c:/assets", completeness=ScopeCompleteness.INCOMPLETE)
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert "path" in decision.applicable_channels
    assert "path" not in decision.complete_channels
    assert "explicit_asset_id" in decision.complete_channels
    assert decision.expected_observable is True


def test_complete_path_plus_explicit_access_failure_path_still_controls():
    root = make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
        explicit_asset_id_failures=(ExplicitAssetAccessFailure("RLG-001", "access_denied", "Denied."),),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert "path" in decision.complete_channels
    assert "explicit_asset_id" in decision.blocked_channels
    assert decision.expected_observable is True
    assert decision.missing_eligible is True


def test_both_channels_complete():
    root = make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.complete_channels == ("path", "explicit_asset_id")


def test_both_channels_incomplete():
    root = make_root("c:/assets", completeness=ScopeCompleteness.INCOMPLETE)
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.INCOMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.complete_channels == ()
    assert decision.expected_observable is False
    assert decision.missing_eligible is False


def test_both_channels_blocked():
    root = make_root("c:/assets", inaccessible_subtrees=("c:/assets",))
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
        explicit_asset_id_failures=(ExplicitAssetAccessFailure("RLG-001", "access_denied", "Denied."),),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert set(decision.blocked_channels) == {"path", "explicit_asset_id"}
    assert decision.expected_observable is False
    assert decision.missing_eligible is False


# ---------------------------------------------------------------------------
# Combined decision
# ---------------------------------------------------------------------------


def test_one_complete_channel_makes_expected_observable_true():
    scope = make_scope(
        explicit_asset_ids=("RLG-001",), explicit_asset_id_completeness=ScopeCompleteness.COMPLETE
    )
    record = make_record(asset_id="RLG-001", normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert decision.expected_observable is True


def test_one_complete_channel_makes_missing_eligible_true():
    scope = make_scope(
        explicit_asset_ids=("RLG-001",), explicit_asset_id_completeness=ScopeCompleteness.COMPLETE
    )
    record = make_record(asset_id="RLG-001", normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert decision.missing_eligible is True


def test_incomplete_only_never_missing_eligible():
    root = make_root("c:/assets", completeness=ScopeCompleteness.INCOMPLETE)
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.missing_eligible is False


def test_excluded_only_never_missing_eligible():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        exclusion_filters=ObservationFilters(excluded_normalized_subtrees=("c:/assets",)),
    )
    record = make_record(normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.missing_eligible is False


def test_blocked_only_never_missing_eligible():
    root = make_root("c:/assets", inaccessible_subtrees=("c:/assets",))
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.missing_eligible is False


def test_no_applicable_channels():
    scope = make_scope()
    record = make_record(normalized_path=None)

    decision = evaluate_record_observability(record, scope)

    assert decision.applicable_channels == ()
    assert decision.expected_observable is False
    assert decision.missing_eligible is False


def test_deterministic_channel_tuple_ordering():
    root = make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.applicable_channels == ("path", "explicit_asset_id")
    assert decision.complete_channels == ("path", "explicit_asset_id")


def test_deterministic_reason_tuple_ordering():
    root = make_root("c:/assets", inaccessible_subtrees=("c:/assets",))
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
        explicit_asset_id_failures=(ExplicitAssetAccessFailure("RLG-001", "access_denied", "Denied."),),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    first = evaluate_record_observability(record, scope)
    second = evaluate_record_observability(record, scope)

    assert first.access_failure_reasons == second.access_failure_reasons
    assert first.access_failure_reasons == tuple(sorted(first.access_failure_reasons))


def test_deterministic_evidence_fact_ordering():
    root = make_root("c:/assets", completeness=ScopeCompleteness.COMPLETE)
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert decision.evidence_facts == tuple(sorted(decision.evidence_facts))
    assert decision.evidence_facts == tuple(sorted(set(decision.evidence_facts)))  # no duplicates


# ---------------------------------------------------------------------------
# Safety and immutability
# ---------------------------------------------------------------------------


def test_record_unchanged_after_evaluation():
    root = make_root("c:/assets")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logo.png")
    before = replace(record)

    evaluate_record_observability(record, scope)

    assert record == before


def test_scope_unchanged_after_evaluation():
    root = make_root("c:/assets", inaccessible_subtrees=("c:/assets/locked",))
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")
    before_roots = scope.roots
    before_explicit_ids = scope.explicit_asset_ids

    evaluate_record_observability(record, scope)

    assert scope.roots == before_roots
    assert scope.explicit_asset_ids == before_explicit_ids


def test_nested_scope_data_unchanged():
    root = make_root(
        "c:/assets",
        inaccessible_subtrees=("c:/assets/locked",),
        access_failures=(),
    )
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/locked/file.mov")
    before = replace(root)

    evaluate_record_observability(record, scope)

    assert root == before
    assert scope.roots[0] == before


def test_repeated_calls_return_equal_decisions():
    root = make_root("c:/assets")
    scope = make_scope(roots=(root,))
    record = make_record(normalized_path="c:/assets/logo.png")

    first = evaluate_record_observability(record, scope)
    second = evaluate_record_observability(record, scope)

    assert first == second


def test_hostile_safe_message_does_not_leak_via_repr():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
        explicit_asset_id_failures=(
            ExplicitAssetAccessFailure("RLG-001", "access_denied", "hostile-marker-value"),
        ),
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    decision = evaluate_record_observability(record, scope)

    assert "hostile-marker-value" not in repr(decision)


def test_no_raw_builtin_exception_for_valid_inputs():
    root = make_root("c:/assets")
    scope = make_scope(
        roots=(root,),
        explicit_asset_ids=("RLG-001",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    record = make_record(asset_id="RLG-001", normalized_path="c:/assets/logo.png")

    # Should not raise for any well-formed valid model input.
    evaluate_record_observability(record, scope)
    evaluate_record_observability(make_record(normalized_path=None), make_scope())


def test_observability_decision_is_frozen_and_slotted():
    decision = evaluate_record_observability(make_record(), make_scope())

    assert ObservabilityDecision.__dataclass_params__.frozen is True
    with pytest.raises(AttributeError):
        decision.__dict__  # slotted dataclasses have no __dict__
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.expected_observable = False  # frozen: direct assignment must raise


# ---------------------------------------------------------------------------
# Hash-seed determinism
# ---------------------------------------------------------------------------


_HASH_SEED_PROBE = """
import sys
sys.path.insert(0, "src")
from datetime import datetime, timezone
from redline_core.asset.models import (
    AssetAvailability, AssetLifecycle, AssetRegistryRecord, AssetSourceKind, AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import ScopeCompleteness
from redline_core.asset.reconciliation.models import ObservationRootScope, ObservationScope
from redline_core.asset.reconciliation.scope import evaluate_record_observability

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
record = AssetRegistryRecord(
    record_id=1, asset_id="RLG-001", declared_path="assets/RLG-001.mov",
    resolved_path="C:/assets/RLG-001.mov", normalized_resolved_path="c:/assets/logos/lower_third.png",
    approved_root_id="assets_path", lifecycle=AssetLifecycle.DECLARED,
    availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED,
    file_size_bytes=None, file_modified_at=None, last_verified_at=None,
    created_at=NOW, updated_at=NOW, source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
    source_detail=None, diagnostic_code=None, diagnostic_message=None,
)
scope = ObservationScope(
    scope_id="scope-1", observed_at=NOW, source_id="scan-a",
    roots=(
        ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),
        ObservationRootScope("c:/assets/logos", ScopeCompleteness.INCOMPLETE),
    ),
    explicit_asset_ids=("RLG-001",),
    explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
)
decision = evaluate_record_observability(record, scope)
print((
    decision.applicable_channels,
    decision.complete_channels,
    decision.blocked_channels,
    decision.exclusion_reasons,
    decision.access_failure_reasons,
    decision.expected_observable,
    decision.missing_eligible,
    decision.evidence_facts,
))
"""


_REPO_ROOT = Path(__file__).resolve().parents[4]


def _run_hash_seed_probe(seed: str) -> str:
    probe_env = dict(os.environ)
    probe_env["PYTHONHASHSEED"] = seed
    result = subprocess.run(
        [sys.executable, "-c", _HASH_SEED_PROBE],
        cwd=str(_REPO_ROOT),
        env=probe_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("seed", ["1", "99"])
def test_hash_seed_independence(seed: str):
    baseline = _run_hash_seed_probe("0")
    probed = _run_hash_seed_probe(seed)

    assert probed == baseline
