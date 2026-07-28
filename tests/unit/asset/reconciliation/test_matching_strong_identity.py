"""Tests for Phase 3 Slice 7 strong-identity matching.

Strong identity runs strictly after trusted-ID and exact-path matching
(Slice 6) inside the same ``build_matching_state`` call. These tests never
modify or weaken the existing Slice 6 test expectations
(``test_matching_trusted_ids_and_paths.py``, verified unchanged and passing
separately) -- every fixture here that only exercises Slice 6 behavior
carries no registry identity evidence and no observation content hashes,
fingerprints, or filesystem identity, so Slice 7's stage is a no-op for it.
"""
from __future__ import annotations

import dataclasses
import os
import random
import re
import subprocess
import sys
import time
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
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    ConflictKind,
    EvidenceKind,
    ObservationKind,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.indexes import build_indexes
from redline_core.asset.reconciliation.matching import (
    BlockedObservation,
    BlockedRecord,
    ConflictGroup,
    ConsumedIds,
    DefinitiveAssociation,
    MatchingState,
    build_matching_state,
)
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ObservationRootScope,
    ObservationScope,
    ReconciliationRequest,
    RegistryIdentityEvidence,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

_ALLOWED_EVIDENCE_FACTS = frozenset(
    {
        "duplicate_observation_path",
        "registry_path_collision",
        "unknown_trusted_asset_id",
        "trusted_asset_id_claimed_by_multiple_observations",
        "trusted_asset_id",
        "exact_path",
        "trusted_asset_id_exact_path_agreement",
        "trusted_asset_id_exact_path_conflict",
        "cross_observation_asset_id_conflict",
        "unique_strong_identity",
        "registry_identity_collision",
        "observation_identity_collision",
        "mixed_identity_collision",
        "strong_identity_conflicting_candidates",
        "strong_identity_authoritative_conflict",
        "strong_identity_content_conflict",
    }
)


def make_record(asset_id: str, *, normalized_path: str | None = None) -> AssetRegistryRecord:
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
        source_detail=None,
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_evidence(
    asset_id: str,
    *,
    evidence_kind: EvidenceKind = EvidenceKind.FULL_CONTENT_HASH,
    algorithm: str | None = "sha256",
    normalized_value: str,
    normalization_format: str = "lowercase_hex",
    scope_id: str | None = None,
    source_id: str = "registry-scan",
) -> RegistryIdentityEvidence:
    return RegistryIdentityEvidence(
        asset_id=asset_id,
        evidence_kind=evidence_kind,
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
    content_hashes: tuple[tuple[str, str], ...] = (),
    partial_fingerprints: tuple[str, ...] = (),
    filesystem_identity: str | None = None,
) -> AssetObservation:
    return AssetObservation(
        observation_id=observation_id,
        source_id=source_id,
        source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW,
        observation_scope_id="scope-1",
        availability=AssetAvailability.AVAILABLE if normalized_path is not None else AssetAvailability.UNKNOWN,
        verification=AssetVerificationState.VERIFIED if normalized_path is not None else AssetVerificationState.UNVERIFIED,
        normalized_resolved_path=normalized_path,
        claimed_asset_id=claimed_asset_id,
        content_hashes=content_hashes,
        partial_fingerprints=partial_fingerprints,
        filesystem_identity=filesystem_identity,
    )


def make_scope() -> ObservationScope:
    return ObservationScope(
        scope_id="scope-1",
        observed_at=NOW,
        source_id="scan-a",
        roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
    )


def make_state(
    *,
    records: tuple[AssetRegistryRecord, ...] = (),
    identity_evidence: tuple[RegistryIdentityEvidence, ...] = (),
    observations: tuple[AssetObservation, ...] = (),
    trusted_asset_id_source_ids: tuple[str, ...] = (),
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
) -> tuple[MatchingState, object]:
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
    return build_matching_state(inputs, indexes), inputs


def _conflicts_of_kind(state: MatchingState, kind: ConflictKind) -> tuple[ConflictGroup, ...]:
    return tuple(c for c in state.conflict_groups if c.conflict_kind is kind)


# ---------------------------------------------------------------------------
# 1-2. Unique strong identity through the reduced bridge
# ---------------------------------------------------------------------------


def test_unique_strong_identity_produces_one_association():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1",
            observation_id="obs-1",
            association_kind="unique_strong_identity",
            evidence_facts=("unique_strong_identity",),
        ),
    )
    assert state.consumed.asset_ids == frozenset({"A-1"})
    assert state.consumed.observation_ids == frozenset({"obs-1"})
    assert state.conflict_groups == ()
    assert state.blocked_observations == ()
    assert state.blocked_records == ()


def test_registry_five_tuple_joins_observation_three_tuple_through_bridge():
    """The registry key carries normalization_format/scope_id that the observation
    key structurally cannot -- a direct 5-tuple-to-3-tuple dict lookup would never
    find this pair. Only the reduced bridge makes the join possible."""
    record = make_record("A-1")
    evidence = make_evidence(
        "A-1", normalized_value="digest-1", normalization_format="lowercase_hex", scope_id="scope-x"
    )
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].association_kind == "unique_strong_identity"


# ---------------------------------------------------------------------------
# 4-5. scope_id / normalization_format collapse into the same reduced key
# ---------------------------------------------------------------------------


def test_different_scope_id_reduces_to_same_cross_reference_key():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1", scope_id="scope-only-here")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].asset_id == "A-1"


def test_different_normalization_format_reduces_to_same_cross_reference_key():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1", normalization_format="uppercase_hex")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].asset_id == "A-1"


def test_reduction_does_not_alter_registry_internal_full_key_collision_semantics():
    """Two registry rows for *different* assets, same (kind, algorithm, value),
    different scope_id: Slice 5's full 5-tuple index keeps them as two distinct
    keys (no registry-internal collision), but Slice 7's reduced bridge must
    treat them as one ambiguous group against a shared observation."""
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1", scope_id="scope-a")
    evidence_b = make_evidence("A-2", normalized_value="digest-1", scope_id="scope-b")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, inputs = make_state(
        records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=(observation,)
    )
    indexes = build_indexes(inputs)

    # Full 5-tuple registry index: two distinct keys, no registry-internal collision.
    assert len(indexes.registry.identity_key_to_asset_ids) == 2
    assert indexes.registry.identity_collision_groups == ()

    # Reduced cross-side view: ambiguous -- REGISTRY_IDENTITY_COLLISION, no association.
    assert state.definitive_associations == ()
    collisions = _conflicts_of_kind(state, ConflictKind.REGISTRY_IDENTITY_COLLISION)
    assert len(collisions) == 1
    assert collisions[0].asset_ids == ("A-1", "A-2")
    assert collisions[0].observation_ids == ("obs-1",)
    assert collisions[0].evidence_facts == ("registry_identity_collision",)
    assert collisions[0].proposal_blocked is True


# ---------------------------------------------------------------------------
# 6-8. Collision classifications
# ---------------------------------------------------------------------------


def test_multiple_assets_one_observation_is_registry_identity_collision():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1")
    evidence_b = make_evidence("A-2", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(
        records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=(observation,)
    )

    collisions = _conflicts_of_kind(state, ConflictKind.REGISTRY_IDENTITY_COLLISION)
    assert len(collisions) == 1
    assert collisions[0].asset_ids == ("A-1", "A-2")
    assert collisions[0].observation_ids == ("obs-1",)
    assert state.definitive_associations == ()
    assert state.consumed.asset_ids == frozenset()
    assert state.consumed.observation_ids == frozenset()


def test_one_asset_multiple_observations_is_observation_identity_collision():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(obs_a, obs_b))

    collisions = _conflicts_of_kind(state, ConflictKind.OBSERVATION_IDENTITY_COLLISION)
    assert len(collisions) == 1
    assert collisions[0].asset_ids == ("A-1",)
    assert collisions[0].observation_ids == ("obs-1", "obs-2")
    assert state.definitive_associations == ()


def test_multiple_assets_multiple_observations_is_mixed_identity_collision_bounded():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1")
    evidence_b = make_evidence("A-2", normalized_value="digest-1")
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(
        records=(record_a, record_b),
        identity_evidence=(evidence_a, evidence_b),
        observations=(obs_a, obs_b),
    )

    collisions = _conflicts_of_kind(state, ConflictKind.MIXED_IDENTITY_COLLISION)
    assert len(collisions) == 1
    assert collisions[0].asset_ids == ("A-1", "A-2")
    assert collisions[0].observation_ids == ("obs-1", "obs-2")
    assert state.definitive_associations == ()


# ---------------------------------------------------------------------------
# 9-11. Different kind / algorithm / value do not match
# ---------------------------------------------------------------------------


def test_different_evidence_kinds_do_not_match():
    record = make_record("A-1")
    evidence = make_evidence("A-1", evidence_kind=EvidenceKind.FULL_CONTENT_HASH, normalized_value="value-1")
    observation = make_observation("obs-1", partial_fingerprints=("value-1",))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


def test_different_algorithms_do_not_match():
    record = make_record("A-1")
    evidence = make_evidence("A-1", algorithm="sha256", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("md5", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


def test_different_normalized_values_do_not_match():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-2"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


# ---------------------------------------------------------------------------
# 12. Moved-file identity
# ---------------------------------------------------------------------------


def test_moved_file_strong_identity_match_without_path_agreement():
    record = make_record("A-1", normalized_path="c:/assets/old.mov")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", normalized_path="c:/assets/new.mov", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1",
            observation_id="obs-1",
            association_kind="unique_strong_identity",
            evidence_facts=("unique_strong_identity",),
        ),
    )
    # Slice 7 records the association only -- no path mutation, action, or
    # proposal is produced by this module.
    assert state.conflict_groups == ()


# ---------------------------------------------------------------------------
# 13-14. Disagreement with existing authoritative associations
# ---------------------------------------------------------------------------


def test_strong_identity_disagrees_with_trusted_id_produces_authoritative_conflict():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence = make_evidence("A-2", normalized_value="digest-1")
    observation = make_observation(
        "obs-1",
        source_id="trusted-scan",
        claimed_asset_id="A-1",
        content_hashes=(("sha256", "digest-1"),),
    )
    state, _ = make_state(
        records=(record_a, record_b),
        identity_evidence=(evidence,),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    # Trusted association preserved untouched.
    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1", observation_id="obs-1", association_kind="trusted_asset_id", evidence_facts=("trusted_asset_id",)
        ),
    )
    conflicts = _conflicts_of_kind(state, ConflictKind.AUTHORITATIVE_IDENTITY)
    assert len(conflicts) == 1
    assert conflicts[0].asset_ids == ("A-1", "A-2")
    assert conflicts[0].observation_ids == ("obs-1",)
    assert conflicts[0].evidence_facts == ("strong_identity_authoritative_conflict",)
    assert state.consumed.asset_ids == frozenset({"A-1"})
    assert state.consumed.observation_ids == frozenset({"obs-1"})


def test_strong_identity_disagrees_with_exact_path_only_produces_content_conflict():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2")
    evidence = make_evidence("A-2", normalized_value="digest-1")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a.mov", content_hashes=(("sha256", "digest-1"),)
    )
    state, _ = make_state(records=(record_a, record_b), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1", observation_id="obs-1", association_kind="exact_path", evidence_facts=("exact_path",)
        ),
    )
    conflicts = _conflicts_of_kind(state, ConflictKind.CONTENT)
    assert len(conflicts) == 1
    assert conflicts[0].asset_ids == ("A-1", "A-2")
    assert conflicts[0].observation_ids == ("obs-1",)
    assert conflicts[0].evidence_facts == ("strong_identity_content_conflict",)


# ---------------------------------------------------------------------------
# 15. Already-agreeing pair does not duplicate
# ---------------------------------------------------------------------------


def test_strong_identity_agreeing_with_trusted_id_does_not_duplicate_association():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation(
        "obs-1", source_id="trusted-scan", claimed_asset_id="A-1", content_hashes=(("sha256", "digest-1"),)
    )
    state, _ = make_state(
        records=(record,),
        identity_evidence=(evidence,),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].association_kind == "trusted_asset_id"
    assert state.conflict_groups == ()


# ---------------------------------------------------------------------------
# 16-17. Already-consumed IDs are not re-matched
# ---------------------------------------------------------------------------


def test_already_consumed_asset_id_not_matched_again():
    # A-1 is consumed via trusted-ID by obs-1; a second observation (obs-2)
    # independently strong-identity-matches A-1 via content hash -- must
    # conflict, not silently re-associate.
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    trusted_obs = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    strong_obs = make_observation("obs-2", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(
        records=(record,),
        identity_evidence=(evidence,),
        observations=(trusted_obs, strong_obs),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1", observation_id="obs-1", association_kind="trusted_asset_id", evidence_facts=("trusted_asset_id",)
        ),
    )
    conflicts = _conflicts_of_kind(state, ConflictKind.AUTHORITATIVE_IDENTITY)
    assert len(conflicts) == 1
    assert conflicts[0].asset_ids == ("A-1",)
    assert conflicts[0].observation_ids == ("obs-1", "obs-2")
    assert "obs-2" not in state.consumed.observation_ids


def test_already_consumed_observation_id_not_matched_again():
    # obs-1 is consumed via exact path against A-1; strong identity also
    # proposes obs-1 against a different asset A-2 -- must conflict.
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2")
    evidence = make_evidence("A-2", normalized_value="digest-1")
    observation = make_observation(
        "obs-1", normalized_path="c:/assets/a.mov", content_hashes=(("sha256", "digest-1"),)
    )
    state, _ = make_state(records=(record_a, record_b), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1", observation_id="obs-1", association_kind="exact_path", evidence_facts=("exact_path",)
        ),
    )
    conflicts = _conflicts_of_kind(state, ConflictKind.CONTENT)
    assert len(conflicts) == 1
    assert "A-2" in conflicts[0].asset_ids
    assert "obs-1" in conflicts[0].observation_ids


# ---------------------------------------------------------------------------
# 18-20. Earlier blocks/conflicts are preserved
# ---------------------------------------------------------------------------


def test_earlier_blocked_record_remains_blocked_and_excluded_from_strong_matching():
    record_a = make_record("A-1", normalized_path="c:/assets/shared.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/shared.mov")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record_a, record_b), identity_evidence=(evidence,), observations=(observation,))

    blocked_asset_ids = {b.asset_id for b in state.blocked_records}
    assert blocked_asset_ids == {"A-1", "A-2"}
    for blocked in state.blocked_records:
        assert blocked.blocking_code == "registry_path_collision"
    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


def test_earlier_blocked_observation_remains_blocked_and_excluded_from_strong_matching():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    obs_a = make_observation("obs-1", normalized_path="c:/assets/shared.mov", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", normalized_path="c:/assets/shared.mov")
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(obs_a, obs_b))

    blocked_ids = {b.observation_id for b in state.blocked_observations}
    assert blocked_ids == {"obs-1", "obs-2"}
    for blocked in state.blocked_observations:
        assert blocked.blocking_code == "duplicate_observation_path"
    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


def test_earlier_slice6_conflict_preserved_and_excluded_from_strong_matching():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation(
        "obs-1",
        source_id="trusted-scan",
        claimed_asset_id="A-1",
        normalized_path="c:/assets/b.mov",
        content_hashes=(("sha256", "digest-1"),),
    )
    state, _ = make_state(
        records=(record_a, record_b),
        identity_evidence=(evidence,),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    # Slice 6's own trusted-vs-path conflict is preserved.
    slice6_conflicts = _conflicts_of_kind(state, ConflictKind.AUTHORITATIVE_IDENTITY)
    assert len(slice6_conflicts) == 1
    assert slice6_conflicts[0].evidence_facts == ("trusted_asset_id_exact_path_conflict",)
    # obs-1 is already Slice-6-conflicted, so strong identity does not touch it again.
    assert state.definitive_associations == ()
    assert len(state.conflict_groups) == 1


# ---------------------------------------------------------------------------
# 21-22. One-sided evidence produces no association
# ---------------------------------------------------------------------------


def test_one_sided_registry_identity_produces_no_association():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=())

    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


def test_one_sided_observation_identity_produces_no_association():
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(observations=(observation,))

    assert state.definitive_associations == ()
    assert state.conflict_groups == ()


# ---------------------------------------------------------------------------
# 23. Multiple supporting keys, one association
# ---------------------------------------------------------------------------


def test_multiple_identity_keys_supporting_same_pair_produce_one_association():
    record = make_record("A-1")
    evidence_hash = make_evidence("A-1", evidence_kind=EvidenceKind.FULL_CONTENT_HASH, normalized_value="digest-1")
    evidence_fp = make_evidence(
        "A-1", evidence_kind=EvidenceKind.PARTIAL_FINGERPRINT, algorithm=None, normalized_value="fp-1"
    )
    observation = make_observation(
        "obs-1", content_hashes=(("sha256", "digest-1"),), partial_fingerprints=("fp-1",)
    )
    state, _ = make_state(
        records=(record,), identity_evidence=(evidence_hash, evidence_fp), observations=(observation,)
    )

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].asset_id == "A-1"
    assert state.definitive_associations[0].observation_id == "obs-1"


# ---------------------------------------------------------------------------
# 24. Conflicting strong-identity keys are order-independent
# ---------------------------------------------------------------------------


def test_conflicting_strong_identity_keys_produce_conflict_not_arbitrary_pick():
    """Asset A-1 matches obs-1 via a content hash and obs-2 via a *different*
    content hash -- two distinct reduced keys propose different partners for
    the same asset. This must become a conflict, never an arbitrary pick."""
    record = make_record("A-1")
    evidence_a = make_evidence("A-1", normalized_value="digest-1", source_id="src-a")
    evidence_b = make_evidence("A-1", normalized_value="digest-2", source_id="src-b")
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-2"),))
    state, _ = make_state(
        records=(record,), identity_evidence=(evidence_a, evidence_b), observations=(obs_a, obs_b)
    )

    assert state.definitive_associations == ()
    conflicts = _conflicts_of_kind(state, ConflictKind.MIXED_IDENTITY_COLLISION)
    assert len(conflicts) == 1
    assert conflicts[0].asset_ids == ("A-1",)
    assert conflicts[0].observation_ids == ("obs-1", "obs-2")
    assert conflicts[0].evidence_facts == ("strong_identity_conflicting_candidates",)


def test_conflicting_strong_identity_keys_order_independent():
    record = make_record("A-1")
    evidence_a = make_evidence("A-1", normalized_value="digest-1", source_id="src-a")
    evidence_b = make_evidence("A-1", normalized_value="digest-2", source_id="src-b")
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-2"),))

    forward, _ = make_state(
        records=(record,), identity_evidence=(evidence_a, evidence_b), observations=(obs_a, obs_b)
    )
    reversed_state, _ = make_state(
        records=(record,), identity_evidence=(evidence_b, evidence_a), observations=(obs_b, obs_a)
    )

    assert forward.definitive_associations == reversed_state.definitive_associations
    assert forward.conflict_groups == reversed_state.conflict_groups


# ---------------------------------------------------------------------------
# 25-27. Ownership invariant and consumed-ID rebuilding
# ---------------------------------------------------------------------------


def test_no_asset_id_appears_in_more_than_one_definitive_association():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1")
    evidence_b = make_evidence("A-2", normalized_value="digest-2")
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-2"),))
    state, _ = make_state(
        records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=(obs_a, obs_b)
    )

    asset_ids = [a.asset_id for a in state.definitive_associations]
    assert len(asset_ids) == len(set(asset_ids))


def test_no_observation_id_appears_in_more_than_one_definitive_association():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1")
    evidence_b = make_evidence("A-2", normalized_value="digest-2")
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-2"),))
    state, _ = make_state(
        records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=(obs_a, obs_b)
    )

    observation_ids = [a.observation_id for a in state.definitive_associations]
    assert len(observation_ids) == len(set(observation_ids))


def test_consumed_ids_rebuilt_from_final_surviving_associations_only():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1")
    evidence_b = make_evidence("A-2", normalized_value="digest-1")  # collides with A-1's key
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(
        records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=(observation,)
    )

    assert state.definitive_associations == ()
    assert state.consumed.asset_ids == frozenset()
    assert state.consumed.observation_ids == frozenset()


# ---------------------------------------------------------------------------
# 28. ConsumedIds remains frozenset-based
# ---------------------------------------------------------------------------


def test_consumed_ids_fields_remain_frozensets():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record,), identity_evidence=(evidence,), observations=(observation,))

    assert isinstance(state.consumed.asset_ids, frozenset)
    assert isinstance(state.consumed.observation_ids, frozenset)


# ---------------------------------------------------------------------------
# 29-31. Immutability
# ---------------------------------------------------------------------------


def test_inputs_and_indexes_unchanged_after_strong_identity_matching():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    snapshot = RegistrySnapshot(
        records=(record,), identity_evidence=(evidence,), schema_version="1", snapshot_id="snap-1",
        snapshot_created_at=NOW, registry_id="reg-1", approved_root_context="assets_path",
    )
    request = ReconciliationRequest(
        request_id="req-1", schema_version="1", created_at=NOW,
        observations=(observation,), scopes=(make_scope(),),
    )
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    before_request = replace(inputs.request)
    before_snapshot = replace(inputs.snapshot)
    before_registry_identity_index = dict(indexes.registry.identity_key_to_asset_ids)
    before_observation_identity_index = dict(indexes.observations.identity_key_to_observation_ids)

    build_matching_state(inputs, indexes)

    assert inputs.request == before_request
    assert inputs.snapshot == before_snapshot
    assert dict(indexes.registry.identity_key_to_asset_ids) == before_registry_identity_index
    assert dict(indexes.observations.identity_key_to_observation_ids) == before_observation_identity_index


def test_repeated_calls_return_equal_state():
    record = make_record("A-1")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    snapshot = RegistrySnapshot(
        records=(record,), identity_evidence=(evidence,), schema_version="1", snapshot_id="snap-1",
        snapshot_created_at=NOW, registry_id="reg-1", approved_root_context="assets_path",
    )
    request = ReconciliationRequest(
        request_id="req-1", schema_version="1", created_at=NOW,
        observations=(observation,), scopes=(make_scope(),),
    )
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)

    first = build_matching_state(inputs, indexes)
    second = build_matching_state(inputs, indexes)

    assert first == second


# ---------------------------------------------------------------------------
# 32-34. Deterministic ordering
# ---------------------------------------------------------------------------


def test_association_and_conflict_ordering_independent_of_declaration_order():
    records_forward = (
        make_record("A-1"),
        make_record("A-2"),
        make_record("A-3"),
    )
    evidence_forward = (
        make_evidence("A-1", normalized_value="digest-1"),
        make_evidence("A-2", normalized_value="digest-2"),
        make_evidence("A-3", normalized_value="digest-3"),
    )
    observations_forward = (
        make_observation("obs-1", content_hashes=(("sha256", "digest-1"),)),
        make_observation("obs-2", content_hashes=(("sha256", "digest-2"),)),
        make_observation("obs-3", content_hashes=(("sha256", "digest-3"),)),
    )
    shuffled_records = list(records_forward)
    shuffled_evidence = list(evidence_forward)
    shuffled_observations = list(observations_forward)
    random.Random(3).shuffle(shuffled_records)
    random.Random(7).shuffle(shuffled_evidence)
    random.Random(11).shuffle(shuffled_observations)

    forward, _ = make_state(records=records_forward, identity_evidence=evidence_forward, observations=observations_forward)
    shuffled, _ = make_state(
        records=tuple(shuffled_records),
        identity_evidence=tuple(shuffled_evidence),
        observations=tuple(shuffled_observations),
    )

    assert forward.definitive_associations == shuffled.definitive_associations
    assert forward.conflict_groups == shuffled.conflict_groups


def test_evidence_facts_are_sorted_and_deduplicated_for_strong_identity_facts():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1")
    evidence_b = make_evidence("A-2", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(
        records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=(observation,)
    )

    for conflict in state.conflict_groups:
        assert conflict.evidence_facts == tuple(sorted(set(conflict.evidence_facts)))
        assert conflict.asset_ids == tuple(sorted(conflict.asset_ids))
        assert conflict.observation_ids == tuple(sorted(conflict.observation_ids))
    for association in state.definitive_associations:
        assert association.evidence_facts == tuple(sorted(set(association.evidence_facts)))


# ---------------------------------------------------------------------------
# 35. Hash-seed independence
# ---------------------------------------------------------------------------


_HASH_SEED_PROBE = """
import sys
sys.path.insert(0, "src")
from datetime import datetime, timezone
from redline_core.asset.models import (
    AssetAvailability, AssetLifecycle, AssetRegistryRecord, AssetSourceKind, AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import EvidenceKind, ObservationKind, ScopeCompleteness
from redline_core.asset.reconciliation.models import (
    AssetObservation, ObservationScope, ObservationRootScope, ReconciliationRequest,
    RegistryIdentityEvidence, RegistrySnapshot,
)
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs
from redline_core.asset.reconciliation.indexes import build_indexes
from redline_core.asset.reconciliation.matching import build_matching_state

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
records = tuple(
    AssetRegistryRecord(
        record_id=i, asset_id=f"A-{i}", declared_path=f"assets/A-{i}.mov",
        resolved_path=None, normalized_resolved_path=None,
        approved_root_id="assets_path", lifecycle=AssetLifecycle.DECLARED,
        availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED,
        file_size_bytes=None, file_modified_at=None, last_verified_at=None,
        created_at=NOW, updated_at=NOW, source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail=None, diagnostic_code=None, diagnostic_message=None,
    )
    for i in range(6)
)
identity_evidence = tuple(
    RegistryIdentityEvidence(
        asset_id=f"A-{i}", evidence_kind=EvidenceKind.FULL_CONTENT_HASH, algorithm="sha256",
        normalized_value=f"digest-{i}", normalization_format="lowercase_hex", scope_id=None,
        source_id="registry-scan", observed_at=NOW,
    )
    for i in range(6)
)
observations = tuple(
    AssetObservation(
        observation_id=f"obs-{i}", source_id="scan-a", source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW, observation_scope_id="scope-1", availability=AssetAvailability.UNKNOWN,
        verification=AssetVerificationState.UNVERIFIED, content_hashes=(("sha256", f"digest-{i}"),),
    )
    for i in range(6)
)
scope = ObservationScope(
    scope_id="scope-1", observed_at=NOW, source_id="scan-a",
    roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
)
snapshot = RegistrySnapshot(
    records=records, identity_evidence=identity_evidence, schema_version="1", snapshot_id="snap-1",
    snapshot_created_at=NOW, registry_id="reg-1", approved_root_context="assets_path",
)
request = ReconciliationRequest(
    request_id="req-1", schema_version="1", created_at=NOW, observations=observations, scopes=(scope,),
)
inputs = validate_reconciliation_inputs(request, snapshot)
indexes = build_indexes(inputs)
state = build_matching_state(inputs, indexes)
print((
    state.definitive_associations,
    state.blocked_observations,
    state.blocked_records,
    state.conflict_groups,
    sorted(state.consumed.asset_ids),
    sorted(state.consumed.observation_ids),
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


# ---------------------------------------------------------------------------
# 36. Collision groups remain bounded, no Cartesian expansion
# ---------------------------------------------------------------------------


def test_mixed_collision_stays_one_bounded_group_not_a_cartesian_product():
    records = tuple(make_record(f"A-{i}") for i in range(3))
    identity_evidence = tuple(make_evidence(f"A-{i}", normalized_value="digest-shared") for i in range(3))
    observations = tuple(
        make_observation(f"obs-{i}", content_hashes=(("sha256", "digest-shared"),)) for i in range(3)
    )
    state, _ = make_state(records=records, identity_evidence=identity_evidence, observations=observations)

    collisions = _conflicts_of_kind(state, ConflictKind.MIXED_IDENTITY_COLLISION)
    assert len(collisions) == 1
    assert collisions[0].asset_ids == ("A-0", "A-1", "A-2")
    assert collisions[0].observation_ids == ("obs-0", "obs-1", "obs-2")
    assert state.definitive_associations == ()


# ---------------------------------------------------------------------------
# 37. Diagnostic safety
# ---------------------------------------------------------------------------


def test_diagnostic_facts_contain_no_raw_hashes_paths_filenames_or_opaque_values():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2")
    evidence = make_evidence("A-2", normalized_value="super-secret-digest-value")
    observation = make_observation(
        "obs-1",
        source_id="trusted-scan",
        claimed_asset_id="A-1",
        normalized_path="c:/assets/a.mov",
        content_hashes=(("sha256", "super-secret-digest-value"),),
    )
    state, _ = make_state(
        records=(record_a, record_b),
        identity_evidence=(evidence,),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    all_facts = set()
    for association in state.definitive_associations:
        all_facts.update(association.evidence_facts)
    for conflict in state.conflict_groups:
        all_facts.update(conflict.evidence_facts)
    for blocked in state.blocked_observations:
        all_facts.update(blocked.evidence_facts)
    for blocked in state.blocked_records:
        all_facts.update(blocked.evidence_facts)

    assert all_facts.issubset(_ALLOWED_EVIDENCE_FACTS)
    for fact in all_facts:
        assert "super-secret-digest-value" not in fact
        assert "c:/assets" not in fact


# ---------------------------------------------------------------------------
# 39. Empty-side reduced-key groups do not create invalid conflicts
# ---------------------------------------------------------------------------


def test_empty_side_after_filtering_produces_no_association_or_conflict():
    # Registry evidence exists for a record whose path collides (blocked),
    # leaving the reduced key with zero eligible asset IDs even though an
    # observation shares it.
    record_a = make_record("A-1", normalized_path="c:/assets/shared.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/shared.mov")
    evidence = make_evidence("A-1", normalized_value="digest-1")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(records=(record_a, record_b), identity_evidence=(evidence,), observations=(observation,))

    assert state.definitive_associations == ()
    # Only the pre-existing registry path-collision blocks exist; no new
    # collision conflict was invented for the now-empty asset side.
    assert state.conflict_groups == ()
    assert {b.asset_id for b in state.blocked_records} == {"A-1", "A-2"}


# ---------------------------------------------------------------------------
# 40. Duplicate memberships deduplicated deterministically
# ---------------------------------------------------------------------------


def test_duplicate_registry_evidence_rows_do_not_duplicate_the_association():
    record = make_record("A-1")
    evidence_a = make_evidence("A-1", normalized_value="digest-1", source_id="scan-1")
    evidence_b = make_evidence("A-1", normalized_value="digest-1", source_id="scan-2")
    observation = make_observation("obs-1", content_hashes=(("sha256", "digest-1"),))
    state, _ = make_state(
        records=(record,), identity_evidence=(evidence_a, evidence_b), observations=(observation,)
    )

    assert len(state.definitive_associations) == 1


# ---------------------------------------------------------------------------
# 41-43. indexes.py untouched / registry-internal indexes / exports
# ---------------------------------------------------------------------------


def test_registry_internal_identity_indexes_unaffected_by_slice7_reduction():
    record_a = make_record("A-1")
    record_b = make_record("A-2")
    evidence_a = make_evidence("A-1", normalized_value="digest-1", scope_id="scope-a")
    evidence_b = make_evidence("A-2", normalized_value="digest-1", scope_id="scope-b")
    _, inputs = make_state(records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b), observations=())
    indexes = build_indexes(inputs)

    # Slice 5's full 5-tuple registry index still distinguishes these two
    # rows by scope_id -- Slice 7's cross-side reduction never touches it.
    assert len(indexes.registry.identity_key_to_asset_ids) == 2
    assert indexes.registry.identity_collision_groups == ()


def test_public_exports_do_not_drift():
    """matching.py's Slice 6/7 symbols are intentionally not part of the
    package's top-level public API, consistent with Slice 5/6 precedent --
    Slice 7 must not add any of them to ``__all__``."""
    import redline_core.asset.reconciliation as reconciliation_package

    slice6_and_7_names = {
        "DefinitiveAssociation",
        "BlockedObservation",
        "BlockedRecord",
        "ConflictGroup",
        "ConsumedIds",
        "MatchingState",
        "build_matching_state",
    }
    assert slice6_and_7_names.isdisjoint(set(reconciliation_package.__all__))

    # The symbols remain directly importable from matching.py itself.
    from redline_core.asset.reconciliation.matching import (  # noqa: F401
        BlockedObservation,
        BlockedRecord,
        ConflictGroup,
        ConsumedIds,
        DefinitiveAssociation,
        MatchingState,
        build_matching_state,
    )


# ---------------------------------------------------------------------------
# 44. Complexity sanity
# ---------------------------------------------------------------------------


def test_large_synthetic_identity_groups_do_not_trigger_nested_full_scans():
    count = 1500
    records = tuple(make_record(f"A-{i}") for i in range(count))
    identity_evidence = tuple(make_evidence(f"A-{i}", normalized_value=f"digest-{i}") for i in range(count))
    observations = tuple(
        make_observation(f"obs-{i}", content_hashes=(("sha256", f"digest-{i}"),)) for i in range(count)
    )

    started = time.perf_counter()
    state, _ = make_state(records=records, identity_evidence=identity_evidence, observations=observations)
    elapsed = time.perf_counter() - started

    assert len(state.definitive_associations) == count
    assert state.conflict_groups == ()
    # Generous ceiling: only meant to catch an accidental O(records x observations)
    # nested scan, not to serve as a tight performance benchmark.
    assert elapsed < 10.0


# ---------------------------------------------------------------------------
# Dataclass immutability (parametrized over all six public dataclasses)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [DefinitiveAssociation, BlockedObservation, BlockedRecord, ConflictGroup, ConsumedIds, MatchingState],
)
def test_public_dataclasses_are_frozen_and_slotted(cls):
    assert cls.__dataclass_params__.frozen is True
    assert "__slots__" in cls.__dict__


def test_frozen_dataclass_rejects_direct_assignment():
    association = DefinitiveAssociation(
        asset_id="A-1", observation_id="obs-1", association_kind="unique_strong_identity", evidence_facts=()
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        association.asset_id = "A-2"


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def test_module_contains_no_prohibited_implementation():
    import redline_core.asset.reconciliation.matching as matching_module

    raw_source = Path(matching_module.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', "", raw_source)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("#"))

    forbidden = (
        "sqlite3",
        "socket",
        "requests",
        "urllib",
        "open(",
        "Path(",
        "ResolveAdapter",
        "classification",
        "findings",
        "actions",
        "planner",
        "serialization",
        "_weak_candidates",
        "weak_candidate_buckets",
    )
    for term in forbidden:
        assert term not in code, f"forbidden term found in matching.py code: {term}"
