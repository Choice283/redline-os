"""Tests for Phase 3 Slice 6 trusted-ID and exact-path matching."""
from __future__ import annotations

import dataclasses
import os
import random
import re
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
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    ConflictKind,
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
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


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


def make_observation(
    observation_id: str,
    *,
    source_id: str = "scan-a",
    normalized_path: str | None = None,
    claimed_asset_id: str | None = None,
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
    observations: tuple[AssetObservation, ...] = (),
    trusted_asset_id_source_ids: tuple[str, ...] = (),
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.ALLOW_LISTED_SOURCES,
) -> tuple[MatchingState, object]:
    snapshot = RegistrySnapshot(
        records=records,
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
        observations=observations,
        scopes=(make_scope(),),
        trusted_asset_id_source_ids=trusted_asset_id_source_ids,
        asset_id_trust_policy=asset_id_trust_policy,
    )
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    return build_matching_state(inputs, indexes), inputs


# ---------------------------------------------------------------------------
# Trusted-ID success
# ---------------------------------------------------------------------------


def test_trusted_id_and_exact_path_agree():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation(
        "obs-1", source_id="trusted-scan", claimed_asset_id="A-1", normalized_path="c:/assets/a.mov"
    )
    state, _ = make_state(
        records=(record,), observations=(observation,), trusted_asset_id_source_ids=("trusted-scan",)
    )

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1",
            observation_id="obs-1",
            association_kind="trusted_asset_id_and_exact_path",
            evidence_facts=("trusted_asset_id_exact_path_agreement",),
        ),
    )
    assert state.consumed.asset_ids == frozenset({"A-1"})
    assert state.consumed.observation_ids == frozenset({"obs-1"})


def test_trusted_id_succeeds_without_path_signal():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    state, _ = make_state(
        records=(record,), observations=(observation,), trusted_asset_id_source_ids=("trusted-scan",)
    )

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1",
            observation_id="obs-1",
            association_kind="trusted_asset_id",
            evidence_facts=("trusted_asset_id",),
        ),
    )
    assert state.conflict_groups == ()
    assert state.blocked_observations == ()


# ---------------------------------------------------------------------------
# Unknown trusted ID blocks fallback
# ---------------------------------------------------------------------------


def test_unknown_trusted_id_blocks_fallback():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation(
        "obs-1", source_id="trusted-scan", claimed_asset_id="A-999", normalized_path="c:/assets/a.mov"
    )
    state, _ = make_state(
        records=(record,), observations=(observation,), trusted_asset_id_source_ids=("trusted-scan",)
    )

    assert state.blocked_observations == (
        BlockedObservation(
            observation_id="obs-1",
            blocking_code="unknown_trusted_asset_id",
            evidence_facts=("unknown_trusted_asset_id",),
        ),
    )
    assert state.definitive_associations == ()
    assert "obs-1" not in state.consumed.observation_ids
    assert "A-1" not in state.consumed.asset_ids


# ---------------------------------------------------------------------------
# Trusted-ID / path disagreement
# ---------------------------------------------------------------------------


def test_trusted_id_path_disagreement():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    observation = make_observation(
        "obs-1", source_id="trusted-scan", claimed_asset_id="A-1", normalized_path="c:/assets/b.mov"
    )
    state, _ = make_state(
        records=(record_a, record_b),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    assert state.definitive_associations == ()
    assert len(state.conflict_groups) == 1
    conflict = state.conflict_groups[0]
    assert conflict.conflict_kind == ConflictKind.AUTHORITATIVE_IDENTITY
    assert conflict.asset_ids == ("A-1", "A-2")
    assert conflict.observation_ids == ("obs-1",)
    assert conflict.evidence_facts == ("trusted_asset_id_exact_path_conflict",)
    assert conflict.proposal_blocked is True
    assert state.consumed.asset_ids == frozenset()
    assert state.consumed.observation_ids == frozenset()


# ---------------------------------------------------------------------------
# Exact path without trusted signal
# ---------------------------------------------------------------------------


def test_exact_path_match_no_trusted_claim():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a.mov")
    state, _ = make_state(records=(record,), observations=(observation,))

    assert state.definitive_associations == (
        DefinitiveAssociation(
            asset_id="A-1", observation_id="obs-1", association_kind="exact_path", evidence_facts=("exact_path",)
        ),
    )
    assert state.consumed.asset_ids == frozenset({"A-1"})
    assert state.consumed.observation_ids == frozenset({"obs-1"})


def test_exact_path_match_untrusted_source_excluded_from_trust():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation(
        "obs-1", source_id="untrusted-scan", claimed_asset_id="A-1", normalized_path="c:/assets/a.mov"
    )
    state, _ = make_state(
        records=(record,), observations=(observation,), trusted_asset_id_source_ids=("trusted-scan",)
    )

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].association_kind == "exact_path"


# ---------------------------------------------------------------------------
# Duplicate observation path
# ---------------------------------------------------------------------------


def test_duplicate_observation_path_blocks_trusted_id_too():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    obs_a = make_observation(
        "obs-1", source_id="trusted-scan", claimed_asset_id="A-1", normalized_path="c:/assets/shared.mov"
    )
    obs_b = make_observation("obs-2", normalized_path="c:/assets/shared.mov")
    state, _ = make_state(
        records=(record,), observations=(obs_a, obs_b), trusted_asset_id_source_ids=("trusted-scan",)
    )

    blocked_ids = {b.observation_id for b in state.blocked_observations}
    assert blocked_ids == {"obs-1", "obs-2"}
    for blocked in state.blocked_observations:
        assert blocked.blocking_code == "duplicate_observation_path"
        assert blocked.evidence_facts == ("duplicate_observation_path",)
    assert state.definitive_associations == ()
    assert state.consumed.observation_ids == frozenset()


# ---------------------------------------------------------------------------
# Duplicate registry path
# ---------------------------------------------------------------------------


def test_duplicate_registry_path_blocks_trusted_claim_on_that_record():
    record_a = make_record("A-1", normalized_path="c:/assets/shared.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/shared.mov")
    observation = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    state, _ = make_state(
        records=(record_a, record_b),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    blocked_record_ids = {r.asset_id for r in state.blocked_records}
    assert blocked_record_ids == {"A-1", "A-2"}
    for blocked in state.blocked_records:
        assert blocked.blocking_code == "registry_path_collision"
        assert blocked.evidence_facts == ("registry_path_collision",)
    assert len(state.blocked_observations) == 1
    assert state.blocked_observations[0].observation_id == "obs-1"
    assert state.blocked_observations[0].blocking_code == "registry_path_collision"
    assert state.definitive_associations == ()
    assert state.consumed.asset_ids == frozenset()
    assert state.consumed.observation_ids == frozenset()


# ---------------------------------------------------------------------------
# Multiple trusted observations claim one Asset ID
# ---------------------------------------------------------------------------


def test_multiple_trusted_observations_claim_one_asset_id():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    obs_a = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    obs_b = make_observation("obs-2", source_id="trusted-scan", claimed_asset_id="A-1")
    state, _ = make_state(
        records=(record,), observations=(obs_a, obs_b), trusted_asset_id_source_ids=("trusted-scan",)
    )

    blocked_ids = {b.observation_id for b in state.blocked_observations}
    assert blocked_ids == {"obs-1", "obs-2"}
    for blocked in state.blocked_observations:
        assert blocked.blocking_code == "trusted_asset_id_claimed_by_multiple_observations"
    assert state.definitive_associations == ()
    assert "A-1" not in state.consumed.asset_ids


# ---------------------------------------------------------------------------
# Cross-observation double target
# ---------------------------------------------------------------------------


def test_cross_observation_double_target_becomes_conflict():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    trusted_obs = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    path_obs = make_observation("obs-2", normalized_path="c:/assets/a.mov")
    state, _ = make_state(
        records=(record,),
        observations=(trusted_obs, path_obs),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    assert state.definitive_associations == ()
    assert len(state.conflict_groups) == 1
    conflict = state.conflict_groups[0]
    assert conflict.asset_ids == ("A-1",)
    assert conflict.observation_ids == ("obs-1", "obs-2")
    assert conflict.conflict_kind == ConflictKind.AUTHORITATIVE_IDENTITY
    assert conflict.evidence_facts == ("cross_observation_asset_id_conflict",)
    assert state.consumed.asset_ids == frozenset()
    assert state.consumed.observation_ids == frozenset()


# ---------------------------------------------------------------------------
# REJECT_ALL policy
# ---------------------------------------------------------------------------


def test_reject_all_policy_ignores_claim_with_no_path():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    state, _ = make_state(
        records=(record,),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
        asset_id_trust_policy=AssetIdTrustPolicy.REJECT_ALL,
    )

    assert state.definitive_associations == ()
    assert state.blocked_observations == ()
    assert state.conflict_groups == ()
    assert state.consumed.observation_ids == frozenset()


def test_reject_all_policy_still_allows_exact_path_matching():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation(
        "obs-1", source_id="trusted-scan", claimed_asset_id="A-1", normalized_path="c:/assets/a.mov"
    )
    state, _ = make_state(
        records=(record,),
        observations=(observation,),
        trusted_asset_id_source_ids=("trusted-scan",),
        asset_id_trust_policy=AssetIdTrustPolicy.REJECT_ALL,
    )

    assert len(state.definitive_associations) == 1
    assert state.definitive_associations[0].association_kind == "exact_path"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_repeated_calls_return_equal_state():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a.mov")
    snapshot = RegistrySnapshot(
        records=(record,), identity_evidence=(), schema_version="1", snapshot_id="snap-1",
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


def test_ordering_independent_of_record_and_observation_declaration_order():
    records_forward = (
        make_record("A-1", normalized_path="c:/assets/a.mov"),
        make_record("A-2", normalized_path="c:/assets/b.mov"),
        make_record("A-3", normalized_path="c:/assets/c.mov"),
    )
    observations_forward = (
        make_observation("obs-1", normalized_path="c:/assets/a.mov"),
        make_observation("obs-2", normalized_path="c:/assets/b.mov"),
        make_observation("obs-3", normalized_path="c:/assets/c.mov"),
    )
    shuffled_records = list(records_forward)
    shuffled_observations = list(observations_forward)
    random.Random(5).shuffle(shuffled_records)
    random.Random(9).shuffle(shuffled_observations)

    forward, _ = make_state(records=records_forward, observations=observations_forward)
    shuffled, _ = make_state(records=tuple(shuffled_records), observations=tuple(shuffled_observations))

    assert forward.definitive_associations == shuffled.definitive_associations
    assert forward.blocked_observations == shuffled.blocked_observations
    assert forward.blocked_records == shuffled.blocked_records
    assert forward.conflict_groups == shuffled.conflict_groups


def test_blocked_and_conflict_ordering_deterministic_with_multiple_entries():
    record_a = make_record("A-1", normalized_path="c:/assets/shared1.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/shared1.mov")
    record_c = make_record("A-3", normalized_path="c:/assets/shared2.mov")
    record_d = make_record("A-4", normalized_path="c:/assets/shared2.mov")
    state, _ = make_state(records=(record_d, record_c, record_b, record_a))

    asset_ids_in_order = [b.asset_id for b in state.blocked_records]
    assert asset_ids_in_order == sorted(asset_ids_in_order)


def test_evidence_facts_are_sorted_and_deduplicated():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    trusted_obs = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    path_obs = make_observation("obs-2", normalized_path="c:/assets/a.mov")
    state, _ = make_state(
        records=(record_a, record_b),
        observations=(trusted_obs, path_obs),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    for conflict in state.conflict_groups:
        assert conflict.evidence_facts == tuple(sorted(set(conflict.evidence_facts)))
        assert conflict.asset_ids == tuple(sorted(conflict.asset_ids))
        assert conflict.observation_ids == tuple(sorted(conflict.observation_ids))
    for association in state.definitive_associations:
        assert association.evidence_facts == tuple(sorted(set(association.evidence_facts)))


# ---------------------------------------------------------------------------
# Hash-seed independence
# ---------------------------------------------------------------------------


_HASH_SEED_PROBE = """
import sys
sys.path.insert(0, "src")
from datetime import datetime, timezone
from redline_core.asset.models import (
    AssetAvailability, AssetLifecycle, AssetRegistryRecord, AssetSourceKind, AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import AssetIdTrustPolicy, ObservationKind, ScopeCompleteness
from redline_core.asset.reconciliation.models import AssetObservation, ObservationScope, ObservationRootScope, ReconciliationRequest, RegistrySnapshot
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs
from redline_core.asset.reconciliation.indexes import build_indexes
from redline_core.asset.reconciliation.matching import build_matching_state

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
records = tuple(
    AssetRegistryRecord(
        record_id=i, asset_id=f"A-{i}", declared_path=f"assets/A-{i}.mov",
        resolved_path=f"C:/assets/{i}.mov", normalized_resolved_path=f"c:/assets/{i}.mov",
        approved_root_id="assets_path", lifecycle=AssetLifecycle.DECLARED,
        availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED,
        file_size_bytes=None, file_modified_at=None, last_verified_at=None,
        created_at=NOW, updated_at=NOW, source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail=None, diagnostic_code=None, diagnostic_message=None,
    )
    for i in range(5)
)
observations = tuple(
    AssetObservation(
        observation_id=f"obs-{i}", source_id="scan-a", source_kind=ObservationKind.FILESYSTEM_SCAN,
        observed_at=NOW, observation_scope_id="scope-1", availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED, normalized_resolved_path=f"c:/assets/{i}.mov",
    )
    for i in range(5)
)
scope = ObservationScope(
    scope_id="scope-1", observed_at=NOW, source_id="scan-a",
    roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
)
snapshot = RegistrySnapshot(
    records=records, identity_evidence=(), schema_version="1", snapshot_id="snap-1",
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
# Immutability
# ---------------------------------------------------------------------------


def test_inputs_and_indexes_unchanged_after_build_matching_state():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    observation = make_observation("obs-1", normalized_path="c:/assets/a.mov")
    snapshot = RegistrySnapshot(
        records=(record,), identity_evidence=(), schema_version="1", snapshot_id="snap-1",
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
    before_registry_asset_ids = dict(indexes.registry.asset_id_to_record)
    before_observation_ids = dict(indexes.observations.observation_id_to_observation)

    build_matching_state(inputs, indexes)

    assert inputs.request == before_request
    assert inputs.snapshot == before_snapshot
    assert dict(indexes.registry.asset_id_to_record) == before_registry_asset_ids
    assert dict(indexes.observations.observation_id_to_observation) == before_observation_ids


# ---------------------------------------------------------------------------
# Dataclass immutability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [DefinitiveAssociation, BlockedObservation, BlockedRecord, ConflictGroup, ConsumedIds, MatchingState],
)
def test_public_dataclasses_are_frozen_and_slotted(cls):
    assert cls.__dataclass_params__.frozen is True
    assert "__slots__" in cls.__dict__


def test_frozen_dataclass_rejects_direct_assignment():
    consumed = ConsumedIds(asset_ids=frozenset({"A-1"}), observation_ids=frozenset({"obs-1"}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        consumed.asset_ids = frozenset()


# ---------------------------------------------------------------------------
# No duplicate final ownership invariant
# ---------------------------------------------------------------------------


def test_no_duplicate_ownership_in_definitive_associations():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    record_c = make_record("A-3", normalized_path="c:/assets/shared.mov")
    record_d = make_record("A-4", normalized_path="c:/assets/shared.mov")
    trusted_only = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    path_only_cross = make_observation("obs-2", normalized_path="c:/assets/a.mov")
    unknown_trusted = make_observation("obs-3", source_id="trusted-scan", claimed_asset_id="A-999")
    dup_path_obs = make_observation("obs-4", normalized_path="c:/assets/shared.mov")

    state, _ = make_state(
        records=(record_a, record_b, record_c, record_d),
        observations=(trusted_only, path_only_cross, unknown_trusted, dup_path_obs),
        trusted_asset_id_source_ids=("trusted-scan",),
    )

    asset_ids = [a.asset_id for a in state.definitive_associations]
    observation_ids = [a.observation_id for a in state.definitive_associations]
    assert len(asset_ids) == len(set(asset_ids))
    assert len(observation_ids) == len(set(observation_ids))

    blocked_observation_ids = {b.observation_id for b in state.blocked_observations}
    blocked_asset_ids = {b.asset_id for b in state.blocked_records}
    conflicted_asset_ids = {a for c in state.conflict_groups for a in c.asset_ids}
    conflicted_observation_ids = {o for c in state.conflict_groups for o in c.observation_ids}

    for association in state.definitive_associations:
        assert association.asset_id not in blocked_asset_ids
        assert association.observation_id not in blocked_observation_ids
        assert association.asset_id not in conflicted_asset_ids
        assert association.observation_id not in conflicted_observation_ids


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def test_module_contains_no_prohibited_implementation():
    import redline_core.asset.reconciliation.matching as matching_module

    raw_source = Path(matching_module.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', "", raw_source)
    code = "\n".join(
        line for line in code.splitlines() if not line.strip().startswith("#")
    )

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
        "_match_identity_evidence",
        "_weak_candidates",
        "content_hashes",
        "partial_fingerprints",
        "filesystem_identity",
        "weak_candidate_buckets",
    )
    for term in forbidden:
        assert term not in code, f"forbidden term found in matching.py code: {term}"
