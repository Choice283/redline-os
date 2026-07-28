"""Tests for Phase 3 Slice 5 deterministic index construction."""
from __future__ import annotations

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
from redline_core.asset.reconciliation.enums import (
    AssetIdTrustPolicy,
    EvidenceKind,
    ObservationKind,
    ScopeCompleteness,
)
from redline_core.asset.reconciliation.exceptions import ReconciliationLimitExceededError
from redline_core.asset.reconciliation.indexes import build_indexes
from redline_core.asset.reconciliation.limits import ReconciliationLimitPolicy
from redline_core.asset.reconciliation.models import (
    AssetObservation,
    ObservationRootScope,
    ObservationScope,
    RegistryIdentityEvidence,
    ReconciliationRequest,
    RegistrySnapshot,
)
from redline_core.asset.reconciliation.subjects import ObservationGroupSubject, RegistryRecordGroupSubject
from redline_core.asset.reconciliation.validation import ValidatedReconciliationInputs, validate_reconciliation_inputs


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def make_record(
    asset_id: str,
    *,
    normalized_path: str | None = None,
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
        source_detail=None,
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_evidence(
    asset_id: str,
    *,
    evidence_kind: EvidenceKind = EvidenceKind.FULL_CONTENT_HASH,
    algorithm: str | None = "sha256",
    normalized_value: str = "abc123",
    normalization_format: str = "hex_lower",
    scope_id: str | None = None,
    source_id: str = "scan-a",
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
    file_name: str | None = None,
    file_size_bytes: int | None = None,
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
        file_name=file_name,
        file_size_bytes=file_size_bytes,
        claimed_asset_id=claimed_asset_id,
        content_hashes=content_hashes,
        partial_fingerprints=partial_fingerprints,
        filesystem_identity=filesystem_identity,
    )


def make_root(
    normalized_root_key: str,
    *,
    completeness: ScopeCompleteness = ScopeCompleteness.COMPLETE,
) -> ObservationRootScope:
    return ObservationRootScope(normalized_root_key=normalized_root_key, completeness=completeness)


def make_scope(
    scope_id: str = "scope-1",
    *,
    roots: tuple[ObservationRootScope, ...] = (),
    explicit_asset_ids: tuple[str, ...] = (),
) -> ObservationScope:
    return ObservationScope(
        scope_id=scope_id,
        observed_at=NOW,
        source_id="scan-a",
        roots=roots,
        explicit_asset_ids=explicit_asset_ids,
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE if explicit_asset_ids else ScopeCompleteness.UNKNOWN,
    )


def make_inputs(
    *,
    records: tuple[AssetRegistryRecord, ...] = (),
    identity_evidence: tuple[RegistryIdentityEvidence, ...] = (),
    observations: tuple[AssetObservation, ...] = (),
    scopes: tuple[ObservationScope, ...] = (make_scope(roots=(make_root("c:/assets"),)),),
    trusted_asset_id_source_ids: tuple[str, ...] = (),
    asset_id_trust_policy: AssetIdTrustPolicy = AssetIdTrustPolicy.REJECT_ALL,
    limit_policy: ReconciliationLimitPolicy = ReconciliationLimitPolicy(),
) -> ValidatedReconciliationInputs:
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
        scopes=scopes,
        trusted_asset_id_source_ids=trusted_asset_id_source_ids,
        asset_id_trust_policy=asset_id_trust_policy,
        limit_policy=limit_policy,
    )
    return validate_reconciliation_inputs(request, snapshot)


# ---------------------------------------------------------------------------
# Registry indexes
# ---------------------------------------------------------------------------


def test_asset_id_to_record_lookup():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    inputs = make_inputs(records=(record,))

    indexes = build_indexes(inputs)

    assert indexes.registry.asset_id_to_record["A-1"] == record


def test_registry_path_collision_two_records():
    record_a = make_record("A-1", normalized_path="c:/assets/shared.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/shared.mov")
    inputs = make_inputs(records=(record_a, record_b))

    indexes = build_indexes(inputs)

    assert indexes.registry.path_key_to_asset_ids["c:/assets/shared.mov"] == ("A-1", "A-2")
    assert indexes.registry.path_collision_groups == (RegistryRecordGroupSubject(asset_ids=("A-1", "A-2")),)


def test_registry_path_collision_three_records():
    records = tuple(make_record(f"A-{i}", normalized_path="c:/assets/shared.mov") for i in range(3))
    inputs = make_inputs(records=records)

    indexes = build_indexes(inputs)

    assert indexes.registry.path_key_to_asset_ids["c:/assets/shared.mov"] == ("A-0", "A-1", "A-2")
    assert len(indexes.registry.path_collision_groups) == 1
    assert indexes.registry.path_collision_groups[0].asset_ids == ("A-0", "A-1", "A-2")


def test_registry_unique_path_no_collision():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    inputs = make_inputs(records=(record_a, record_b))

    indexes = build_indexes(inputs)

    assert indexes.registry.path_collision_groups == ()


def test_registry_null_path_excluded_from_path_index():
    record = make_record("A-1", normalized_path=None)
    inputs = make_inputs(records=(record,))

    indexes = build_indexes(inputs)

    assert dict(indexes.registry.path_key_to_asset_ids) == {}


def test_registry_identity_collision_same_digest():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    evidence_a = make_evidence("A-1", normalized_value="digest-x")
    evidence_b = make_evidence("A-2", normalized_value="digest-x")
    inputs = make_inputs(records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b))

    indexes = build_indexes(inputs)

    assert len(indexes.registry.identity_collision_groups) == 1
    assert indexes.registry.identity_collision_groups[0].asset_ids == ("A-1", "A-2")


def test_registry_identity_collision_across_evidence_kinds_does_not_merge():
    """A hash digest and a fingerprint sharing a raw string are different kinds -- no false collision."""
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    record_b = make_record("A-2", normalized_path="c:/assets/b.mov")
    evidence_a = make_evidence("A-1", evidence_kind=EvidenceKind.FULL_CONTENT_HASH, normalized_value="shared-value")
    evidence_b = make_evidence(
        "A-2",
        evidence_kind=EvidenceKind.PARTIAL_FINGERPRINT,
        algorithm=None,
        normalized_value="shared-value",
    )
    inputs = make_inputs(records=(record_a, record_b), identity_evidence=(evidence_a, evidence_b))

    indexes = build_indexes(inputs)

    assert indexes.registry.identity_collision_groups == ()


def test_registry_unique_identity_no_collision():
    record_a = make_record("A-1", normalized_path="c:/assets/a.mov")
    evidence_a = make_evidence("A-1", normalized_value="digest-only")
    inputs = make_inputs(records=(record_a,), identity_evidence=(evidence_a,))

    indexes = build_indexes(inputs)

    assert indexes.registry.identity_collision_groups == ()


def test_record_evidence_by_asset_id_groups_and_sorts():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    evidence_1 = make_evidence("A-1", normalized_value="aaa", source_id="scan-a")
    evidence_2 = make_evidence("A-1", normalized_value="bbb", source_id="scan-b")
    inputs = make_inputs(records=(record,), identity_evidence=(evidence_2, evidence_1))

    indexes = build_indexes(inputs)

    assert len(indexes.registry.record_evidence_by_asset_id["A-1"]) == 2
    values = [row.normalized_value for row in indexes.registry.record_evidence_by_asset_id["A-1"]]
    assert values == sorted(values)


def test_record_state_by_asset_id_projection():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    inputs = make_inputs(records=(record,))

    indexes = build_indexes(inputs)

    state = indexes.registry.record_state_by_asset_id["A-1"]
    assert state.lifecycle is AssetLifecycle.DECLARED
    assert state.availability is AssetAvailability.UNKNOWN
    assert state.verification is AssetVerificationState.UNVERIFIED


def test_registry_group_ordering_independent_of_input_order():
    records_forward = (
        make_record("A-1", normalized_path="c:/assets/shared.mov"),
        make_record("A-2", normalized_path="c:/assets/shared.mov"),
        make_record("A-3", normalized_path="c:/assets/other.mov"),
    )
    records_shuffled = list(records_forward)
    random.Random(11).shuffle(records_shuffled)

    forward = build_indexes(make_inputs(records=records_forward))
    shuffled = build_indexes(make_inputs(records=tuple(records_shuffled)))

    assert forward.registry.path_key_to_asset_ids == shuffled.registry.path_key_to_asset_ids
    assert forward.registry.path_collision_groups == shuffled.registry.path_collision_groups


def test_registry_oversized_path_group_raises():
    limits = ReconciliationLimitPolicy(max_duplicate_group_size=2)
    records = tuple(make_record(f"A-{i}", normalized_path="c:/assets/shared.mov") for i in range(3))
    inputs = make_inputs(records=records, limit_policy=limits)

    with pytest.raises(ReconciliationLimitExceededError):
        build_indexes(inputs)


# ---------------------------------------------------------------------------
# Observation indexes
# ---------------------------------------------------------------------------


def test_observation_id_to_observation_lookup():
    observation = make_observation("obs-1", normalized_path="c:/assets/a.mov")
    inputs = make_inputs(observations=(observation,))

    indexes = build_indexes(inputs)

    assert indexes.observations.observation_id_to_observation["obs-1"] == observation


def test_observation_path_collision():
    obs_a = make_observation("obs-1", normalized_path="c:/assets/shared.mov")
    obs_b = make_observation("obs-2", normalized_path="c:/assets/shared.mov")
    inputs = make_inputs(observations=(obs_a, obs_b))

    indexes = build_indexes(inputs)

    assert indexes.observations.path_key_to_observation_ids["c:/assets/shared.mov"] == ("obs-1", "obs-2")
    assert indexes.observations.path_collision_groups == (
        ObservationGroupSubject(observation_ids=("obs-1", "obs-2")),
    )


def test_observation_identity_collision_same_hash():
    obs_a = make_observation("obs-1", content_hashes=(("sha256", "digest-x"),))
    obs_b = make_observation("obs-2", content_hashes=(("sha256", "digest-x"),))
    inputs = make_inputs(observations=(obs_a, obs_b))

    indexes = build_indexes(inputs)

    assert len(indexes.observations.identity_collision_groups) == 1
    assert indexes.observations.identity_collision_groups[0].observation_ids == ("obs-1", "obs-2")


def test_single_observation_multiple_identity_facts():
    """One observation with two hashes and one fingerprint contributes three distinct facts."""
    obs = make_observation(
        "obs-1",
        content_hashes=(("sha256", "digest-a"), ("sha1", "digest-b")),
        partial_fingerprints=("fp-1",),
    )
    inputs = make_inputs(observations=(obs,))

    indexes = build_indexes(inputs)

    assert len(indexes.observations.identity_key_to_observation_ids) == 3
    for members in indexes.observations.identity_key_to_observation_ids.values():
        assert members == ("obs-1",)


def test_trusted_claimed_asset_id_included_when_source_trusted():
    obs = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id="A-1")
    inputs = make_inputs(observations=(obs,), trusted_asset_id_source_ids=("trusted-scan",))

    indexes = build_indexes(inputs)

    assert indexes.observations.trusted_claimed_asset_id_to_observation_ids["A-1"] == ("obs-1",)


def test_untrusted_source_excluded_from_trusted_index():
    obs = make_observation("obs-1", source_id="untrusted-scan", claimed_asset_id="A-1")
    inputs = make_inputs(observations=(obs,), trusted_asset_id_source_ids=("trusted-scan",))

    indexes = build_indexes(inputs)

    assert dict(indexes.observations.trusted_claimed_asset_id_to_observation_ids) == {}


def test_no_claimed_id_excluded_from_trusted_index():
    obs = make_observation("obs-1", source_id="trusted-scan", claimed_asset_id=None)
    inputs = make_inputs(observations=(obs,), trusted_asset_id_source_ids=("trusted-scan",))

    indexes = build_indexes(inputs)

    assert dict(indexes.observations.trusted_claimed_asset_id_to_observation_ids) == {}


def test_empty_trust_list_excludes_everything():
    obs = make_observation("obs-1", source_id="scan-a", claimed_asset_id="A-1")
    inputs = make_inputs(observations=(obs,), trusted_asset_id_source_ids=())

    indexes = build_indexes(inputs)

    assert dict(indexes.observations.trusted_claimed_asset_id_to_observation_ids) == {}


def test_weak_candidate_bucket_groups_by_name_and_size():
    obs_a = make_observation("obs-1", file_name="Clip.mov", file_size_bytes=100)
    obs_b = make_observation("obs-2", file_name="clip.mov", file_size_bytes=100)
    inputs = make_inputs(observations=(obs_a, obs_b))

    indexes = build_indexes(inputs)

    assert indexes.observations.weak_candidate_buckets[("clip.mov", (1, 100))] == ("obs-1", "obs-2")


def test_weak_candidate_bucket_excludes_missing_file_name():
    obs = make_observation("obs-1", file_name=None)
    inputs = make_inputs(observations=(obs,))

    indexes = build_indexes(inputs)

    assert dict(indexes.observations.weak_candidate_buckets) == {}


def test_observation_group_ordering_independent_of_input_order():
    observations_forward = (
        make_observation("obs-1", normalized_path="c:/assets/shared.mov"),
        make_observation("obs-2", normalized_path="c:/assets/shared.mov"),
        make_observation("obs-3", normalized_path="c:/assets/other.mov"),
    )
    shuffled = list(observations_forward)
    random.Random(13).shuffle(shuffled)

    forward = build_indexes(make_inputs(observations=observations_forward))
    reordered = build_indexes(make_inputs(observations=tuple(shuffled)))

    assert forward.observations.path_key_to_observation_ids == reordered.observations.path_key_to_observation_ids
    assert forward.observations.path_collision_groups == reordered.observations.path_collision_groups


def test_observation_oversized_identity_group_raises():
    limits = ReconciliationLimitPolicy(max_duplicate_group_size=1)
    observations = tuple(
        make_observation(f"obs-{i}", content_hashes=(("sha256", "digest-x"),)) for i in range(2)
    )
    inputs = make_inputs(observations=observations, limit_policy=limits)

    with pytest.raises(ReconciliationLimitExceededError):
        build_indexes(inputs)


# ---------------------------------------------------------------------------
# Scope indexes
# ---------------------------------------------------------------------------


def test_roots_by_scope_id_sorted_most_specific_first():
    parent = make_root("c:/assets")
    child = make_root("c:/assets/logos")
    scope = make_scope(roots=(parent, child))
    inputs = make_inputs(scopes=(scope,))

    indexes = build_indexes(inputs)

    assert indexes.scopes.roots_by_scope_id["scope-1"] == (child, parent)


def test_roots_by_scope_id_ordering_independent_of_declaration_order():
    parent = make_root("c:/assets")
    child = make_root("c:/assets/logos")

    forward = build_indexes(make_inputs(scopes=(make_scope(roots=(parent, child)),)))
    reversed_order = build_indexes(make_inputs(scopes=(make_scope(roots=(child, parent)),)))

    assert forward.scopes.roots_by_scope_id == reversed_order.scopes.roots_by_scope_id


def test_explicit_asset_ids_by_scope_id_reflects_sorted_tuple():
    scope = make_scope(roots=(), explicit_asset_ids=("B-2", "A-1"))
    inputs = make_inputs(scopes=(scope,))

    indexes = build_indexes(inputs)

    assert indexes.scopes.explicit_asset_ids_by_scope_id["scope-1"] == ("A-1", "B-2")


# ---------------------------------------------------------------------------
# Determinism and immutability
# ---------------------------------------------------------------------------


def test_repeated_calls_return_equal_indexes():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    inputs = make_inputs(records=(record,))

    first = build_indexes(inputs)
    second = build_indexes(inputs)

    assert first == second


def test_request_snapshot_unchanged_after_build_indexes():
    record = make_record("A-1", normalized_path="c:/assets/a.mov")
    inputs = make_inputs(records=(record,))
    before_request = replace(inputs.request)
    before_snapshot = replace(inputs.snapshot)

    build_indexes(inputs)

    assert inputs.request == before_request
    assert inputs.snapshot == before_snapshot


_HASH_SEED_PROBE = """
import sys
sys.path.insert(0, "src")
from datetime import datetime, timezone
from redline_core.asset.models import (
    AssetAvailability, AssetLifecycle, AssetRegistryRecord, AssetSourceKind, AssetVerificationState,
)
from redline_core.asset.reconciliation.enums import ScopeCompleteness
from redline_core.asset.reconciliation.models import (
    ObservationRootScope, ObservationScope, ReconciliationRequest, RegistrySnapshot,
)
from redline_core.asset.reconciliation.validation import validate_reconciliation_inputs
from redline_core.asset.reconciliation.indexes import build_indexes

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
records = tuple(
    AssetRegistryRecord(
        record_id=i, asset_id=f"A-{i}", declared_path=f"assets/A-{i}.mov",
        resolved_path="C:/assets/shared.mov", normalized_resolved_path="c:/assets/shared.mov",
        approved_root_id="assets_path", lifecycle=AssetLifecycle.DECLARED,
        availability=AssetAvailability.UNKNOWN, verification=AssetVerificationState.UNVERIFIED,
        file_size_bytes=None, file_modified_at=None, last_verified_at=None,
        created_at=NOW, updated_at=NOW, source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail=None, diagnostic_code=None, diagnostic_message=None,
    )
    for i in range(3)
)
snapshot = RegistrySnapshot(
    records=records, identity_evidence=(), schema_version="1", snapshot_id="snap-1",
    snapshot_created_at=NOW, registry_id="reg-1", approved_root_context="assets_path",
)
scope = ObservationScope(
    scope_id="scope-1", observed_at=NOW, source_id="scan-a",
    roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
)
request = ReconciliationRequest(
    request_id="req-1", schema_version="1", created_at=NOW, observations=(), scopes=(scope,),
)
inputs = validate_reconciliation_inputs(request, snapshot)
indexes = build_indexes(inputs)
print((
    dict(indexes.registry.path_key_to_asset_ids),
    indexes.registry.path_collision_groups,
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
# Boundary
# ---------------------------------------------------------------------------


def test_module_imports_no_filesystem_or_sqlite():
    """Only code is scanned; triple-quoted docstrings are stripped first so
    prose describing what the module does not do cannot trip this check."""
    import re

    import redline_core.asset.reconciliation.indexes as indexes_module

    raw_source = Path(indexes_module.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', "", raw_source)
    for forbidden in ("sqlite3", "socket.", "requests.", "urllib.", "open(", "Path(", "ResolveAdapter"):
        assert forbidden not in code
