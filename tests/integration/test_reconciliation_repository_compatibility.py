"""Integration tests: full reconciliation pipeline compatibility with SQLite.

Implements the approved "Phase 3 Slice 11 Implementation Contract --
Integration Compatibility (Roadmap Row 13), Revision 3 (final)", test
matrix entries 6-16 (numbered in each test's docstring below for
traceability). Proves the full, unmodified reconciliation chain --

    validate_reconciliation_inputs -> build_indexes -> build_matching_state
    -> evaluate_record_observability (per record) -> classify_reconciliation
    -> plan_reconciliation -> serialize_public_plan

-- succeeds end to end when its ``RegistrySnapshot`` originates from a real
(temporary) SQLite database read via ``SQLiteAssetRepository``, and
produces output equivalent to the same chain run against in-memory
``AssetRegistryRecord`` literals.

This file introduces no production code and does not duplicate the
existing unit-test matrices for the individual pipeline stages
(``test_planner.py``, ``test_serialization.py``, ``test_classification.py``,
etc.) or the repository's own CRUD/schema tests
(``test_asset_sqlite_repository.py``,
``test_asset_database_initialization.py``). It asserts only
cross-component compatibility that none of those can prove alone.

Builder functions are local to this file, matching the established
per-file convention elsewhere in this test suite. Tests 11 and 12 assert
data-level before/after invariants only (contract Sections 8-9) -- neither
claims to prove that a specific repository write method was never called,
since the reconciliation pipeline never holds a reference to the
repository object in the first place. Test 12 is a lightweight bridge
assertion narrowly scoped to this slice's own fixtures, not a re-run of
``test_asset_database_initialization.py``'s full schema-validation
coverage.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation import (
    DEFAULT_LIMITS,
    ObservationRootScope,
    ObservationScope,
    PrimaryClassification,
    ReconciliationLimitPolicy,
    ReconciliationRequest,
    RegistrySnapshot,
    ScopeCompleteness,
    validate_reconciliation_inputs,
)
from redline_core.asset.reconciliation.classification import classify_reconciliation
from redline_core.asset.reconciliation.indexes import build_indexes
from redline_core.asset.reconciliation.matching import build_matching_state
from redline_core.asset.reconciliation.planner import plan_reconciliation
from redline_core.asset.reconciliation.scope import evaluate_record_observability
from redline_core.asset.reconciliation.serialization import serialize_public_plan
from redline_core.asset.sqlite_repository import SQLiteAssetRepository, initialize_asset_registry_database

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
PLAN_CREATED_AT = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)

_SCHEMA_TABLES = ("asset_registry", "asset_registry_schema_metadata")


def make_repo(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    initialize_asset_registry_database(database_path)
    return SQLiteAssetRepository(database_path), database_path


def make_record(
    asset_id,
    *,
    record_id=None,
    normalized_path=None,
    lifecycle=AssetLifecycle.ACTIVE,
    availability=AssetAvailability.AVAILABLE,
    verification=AssetVerificationState.VERIFIED,
    file_size_bytes=1024,
    file_modified_at=NOW,
    last_verified_at=NOW,
    created_at=NOW,
    updated_at=NOW,
):
    return AssetRegistryRecord(
        record_id=record_id,
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
        created_at=created_at,
        updated_at=updated_at,
        source_kind=AssetSourceKind.CONFIG_RECONCILIATION,
        source_detail=None,
        diagnostic_code=None,
        diagnostic_message=None,
    )


def make_snapshot(records, *, snapshot_id="snap-1"):
    return RegistrySnapshot(
        records=records,
        identity_evidence=(),
        schema_version="1",
        snapshot_id=snapshot_id,
        snapshot_created_at=NOW,
        registry_id="reg-1",
        approved_root_context="assets_path",
    )


def make_scope(
    *,
    roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
    explicit_asset_ids=(),
    explicit_asset_id_completeness=ScopeCompleteness.UNKNOWN,
):
    return ObservationScope(
        scope_id="scope-1",
        observed_at=NOW,
        source_id="scan-a",
        roots=roots,
        explicit_asset_ids=explicit_asset_ids,
        explicit_asset_id_completeness=explicit_asset_id_completeness,
    )


def make_request(*, scope, request_id="req-1", limit_policy: ReconciliationLimitPolicy = DEFAULT_LIMITS):
    return ReconciliationRequest(
        request_id=request_id,
        schema_version="1",
        created_at=NOW,
        observations=(),
        scopes=(scope,),
        limit_policy=limit_policy,
    )


def run_full_pipeline(
    request,
    snapshot,
    *,
    created_at: datetime = PLAN_CREATED_AT,
    limit_policy: ReconciliationLimitPolicy = DEFAULT_LIMITS,
):
    """Drive the real, unmodified production chain end to end.

    Builds ``observability_by_asset_id`` using exactly the membership rule
    ``classify_reconciliation``'s own contract already expects (contract
    Section 4b) -- one entry per asset_id present in
    ``indexes.registry.asset_id_to_record`` that is not already present in
    ``matching_state.consumed.asset_ids`` -- via the real
    ``evaluate_record_observability`` production function, never a
    hand-built ``ObservabilityDecision``.
    """
    inputs = validate_reconciliation_inputs(request, snapshot)
    indexes = build_indexes(inputs)
    matching_state = build_matching_state(inputs, indexes)

    scope = request.scopes[0]
    observability_by_asset_id = {
        asset_id: evaluate_record_observability(record, scope)
        for asset_id, record in indexes.registry.asset_id_to_record.items()
        if asset_id not in matching_state.consumed.asset_ids
    }

    state = classify_reconciliation(inputs, indexes, matching_state, observability_by_asset_id)
    plan = plan_reconciliation(inputs, state, created_at=created_at)
    serialized = serialize_public_plan(plan, limit_policy=limit_policy)
    return plan, serialized


def canonical_bytes(serialized) -> bytes:
    return json.dumps(serialized, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_master(database_path):
    """Direct, read-only sqlite_master + schema-version snapshot (contract
    Section 9). Filters by tbl_name (not just object name) so uq_/idx_
    -prefixed named indexes and SQLite auto-generated
    sqlite_autoindex_-prefixed indexes are captured, not just objects
    literally named 'asset_registry...'."""
    connection = sqlite3.connect(str(database_path))
    try:
        placeholders = ", ".join("?" for _ in _SCHEMA_TABLES)
        rows = connection.execute(
            f"""
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE tbl_name IN ({placeholders})
               OR name IN ({placeholders})
            ORDER BY type, name
            """,
            (*_SCHEMA_TABLES, *_SCHEMA_TABLES),
        ).fetchall()
        version_row = connection.execute(
            "SELECT value FROM asset_registry_schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        return tuple(rows), (version_row[0] if version_row is not None else None)
    finally:
        connection.close()


def test_06_full_chain_succeeds_with_sqlite_sourced_snapshot(tmp_path):
    """Test 6: the full, real production chain succeeds end to end when its
    RegistrySnapshot originates from SQLite reads -- the core compatibility
    claim of this entire slice."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))
    repo.insert(make_record("A-2", normalized_path="c:/assets/a2.mov"))

    snapshot = make_snapshot(repo.list_records())
    request = make_request(scope=make_scope())

    plan, serialized = run_full_pipeline(request, snapshot)

    assert {item.subject.asset_id for item in plan.items} == {"A-1", "A-2"}
    assert serialized["items"]


def test_07_sqlite_and_in_memory_runs_produce_identical_canonical_bytes(tmp_path):
    """Test 7: cross-domain reconciliation equivalence, deliberately using a
    *different* record_id on the in-memory side to exercise the contract
    Section 4a proof directly rather than assume it."""
    repo, _ = make_repo(tmp_path)
    inserted = repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))

    sqlite_snapshot = make_snapshot(repo.list_records())

    in_memory_record = make_record("A-1", record_id=999999, normalized_path="c:/assets/a1.mov")
    assert in_memory_record.record_id != inserted.record_id
    in_memory_snapshot = make_snapshot((in_memory_record,))

    request = make_request(scope=make_scope())

    _, sqlite_serialized = run_full_pipeline(request, sqlite_snapshot)
    _, in_memory_serialized = run_full_pipeline(request, in_memory_snapshot)

    assert canonical_bytes(sqlite_serialized) == canonical_bytes(in_memory_serialized)


def test_08_empty_sqlite_registry_produces_valid_empty_plan(tmp_path):
    """Test 8: the full chain, not just RegistrySnapshot construction,
    succeeds end to end for a genuinely empty SQLite-sourced registry."""
    repo, _ = make_repo(tmp_path)
    snapshot = make_snapshot(repo.list_records())
    request = make_request(scope=make_scope())

    plan, serialized = run_full_pipeline(request, snapshot)

    assert plan.items == ()
    assert serialized["items"] == []


def test_09_explicit_asset_id_scope_resolves_against_sqlite_loaded_records(tmp_path):
    """Test 9: explicit-ID scope resolution -- an existing
    reconciliation-domain behavior -- is unaffected by its record having
    originated from SQLite rather than in-memory construction."""
    repo, _ = make_repo(tmp_path)
    # No normalized path at all: only reachable via the explicit-ID channel.
    repo.insert(make_record("A-1", normalized_path=None))

    snapshot = make_snapshot(repo.list_records())
    scope = make_scope(
        roots=(),
        explicit_asset_ids=("A-1",),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    request = make_request(scope=scope)

    plan, _serialized = run_full_pipeline(request, snapshot)

    assert len(plan.items) == 1
    assert plan.items[0].subject.asset_id == "A-1"
    assert plan.items[0].primary_classification == PrimaryClassification.RECORD_NOT_OBSERVED


def test_10_path_scope_resolves_against_complete_sqlite_registry(tmp_path):
    """Test 10 (corrected in Revision 3): reconciliation's own root/path
    scope logic resolves correctly against a *complete* SQLite-loaded
    registry. The snapshot is built from list_records(), not
    get_by_normalized_path() -- using the latter would let the repository
    pre-filter which records reconciliation ever sees, proving only that
    the repository can filter, not that reconciliation correctly evaluates
    scope over a complete registry. ObservationScope.roots and
    evaluate_record_observability perform the actual scope work here,
    preserving component ownership: the repository loads records,
    reconciliation evaluates scope."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))
    repo.insert(make_record("A-2", normalized_path=None))  # outside any declared root

    snapshot = make_snapshot(repo.list_records())
    assert len(snapshot.records) == 2  # complete registry, not repository-pre-filtered

    request = make_request(
        scope=make_scope(roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),))
    )

    plan, _serialized = run_full_pipeline(request, snapshot)

    classifications_by_asset_id = {item.subject.asset_id: item.primary_classification for item in plan.items}
    assert classifications_by_asset_id["A-1"] == PrimaryClassification.RECORD_NOT_OBSERVED
    assert classifications_by_asset_id["A-2"] == PrimaryClassification.INSUFFICIENT_SCOPE


def test_11_repository_visible_record_data_unchanged_after_pipeline_call(tmp_path):
    """Test 11: repository-visible record data is identical before and
    after the reconciliation pipeline runs. The pipeline receives only a
    detached RegistrySnapshot and does not receive the repository object,
    so this is necessarily a data-level before/after assertion -- it does
    not, and cannot, prove that any specific write method was never
    called, since there is no repository reference in scope for the
    pipeline to call one on (contract Section 8)."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))
    repo.insert(make_record("A-2", normalized_path="c:/assets/a2.mov"))

    before_count = repo.count_records()
    before_records = repo.list_records()

    snapshot = make_snapshot(before_records)
    request = make_request(scope=make_scope())
    run_full_pipeline(request, snapshot)

    after_count = repo.count_records()
    after_records = repo.list_records()

    assert after_count == before_count
    assert after_records == before_records


def test_12_schema_and_index_state_unchanged_after_pipeline_call(tmp_path):
    """Test 12 (bridge assertion): the schema this slice's fixtures depend
    on -- including every index defined on it -- is unchanged after a
    reconciliation run. Uses a direct read-only sqlite_master + schema
    version snapshot (contract Section 9), not
    initialize_asset_registry_database (which is itself a setup-capable
    function and would blur the read-only boundary this check is supposed
    to prove). Filters by tbl_name so uq_/idx_-prefixed and SQLite
    auto-generated indexes are captured, not just objects literally named
    'asset_registry...'. Does not re-verify
    initialize_asset_registry_database's own correctness or the full V1
    schema-validation logic -- test_asset_database_initialization.py
    already owns that."""
    repo, database_path = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))

    before = snapshot_master(database_path)
    before_rows, _before_version = before
    # Sanity check on the check itself: the tbl_name filter must actually
    # capture more than the two bare table definitions (i.e. it must be
    # capturing indexes too), or this comparison would be vacuous.
    assert len(before_rows) > len(_SCHEMA_TABLES)

    snapshot = make_snapshot(repo.list_records())
    request = make_request(scope=make_scope())
    run_full_pipeline(request, snapshot)

    after = snapshot_master(database_path)

    assert before == after


def test_13_repeated_runs_against_unmodified_database_are_deterministic(tmp_path):
    """Test 13: identical canonical serialized bytes across repeated runs
    against the same unmodified SQLite-backed database -- determinism
    holds for a SQLite-sourced plan too, not just hand-built ones."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))
    repo.insert(make_record("A-2", normalized_path="c:/assets/a2.mov"))

    request = make_request(scope=make_scope())

    _, serialized_a = run_full_pipeline(request, make_snapshot(repo.list_records()))
    _, serialized_b = run_full_pipeline(request, make_snapshot(repo.list_records()))

    assert canonical_bytes(serialized_a) == canonical_bytes(serialized_b)


def test_14_reversed_insertion_order_across_two_databases_yields_identical_canonical_bytes(tmp_path):
    """Test 14: seeds two temporary databases with the same logical records
    inserted in reversed order. Each database independently auto-assigns
    record_id starting from its own sequence, so this setup guarantees at
    least one shared asset_id receives a *different* record_id across the
    two databases -- asserted directly below, before relying on the
    contract Section 4a proof that record_id cannot influence any
    serialized plan field to justify the canonical-byte equality
    assertion. Also directly proves reconciliation output does not depend
    on SQLite insertion or read order (contract Section 7)."""
    repo_forward, _ = make_repo(tmp_path / "forward")
    repo_forward.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))
    repo_forward.insert(make_record("A-2", normalized_path="c:/assets/a2.mov"))

    repo_reversed, _ = make_repo(tmp_path / "reversed")
    repo_reversed.insert(make_record("A-2", normalized_path="c:/assets/a2.mov"))
    repo_reversed.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))

    forward_by_asset_id = {record.asset_id: record for record in repo_forward.list_records()}
    reversed_by_asset_id = {record.asset_id: record for record in repo_reversed.list_records()}

    # Precondition (not an assumption): reversed insertion order guarantees
    # a differing record_id for at least one shared asset_id.
    assert forward_by_asset_id["A-1"].record_id != reversed_by_asset_id["A-1"].record_id

    request = make_request(scope=make_scope())

    _, serialized_forward = run_full_pipeline(request, make_snapshot(repo_forward.list_records()))
    _, serialized_reversed = run_full_pipeline(request, make_snapshot(repo_reversed.list_records()))

    assert canonical_bytes(serialized_forward) == canonical_bytes(serialized_reversed)


def test_15_explicit_scope_requesting_nonexistent_asset_id_does_not_error(tmp_path):
    """Test 15: the existing "unmatched" handling behaves identically when
    the rest of the registry is SQLite-sourced and an explicitly requested
    asset ID has no corresponding record at all -- no new error type is
    introduced by the SQLite path."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))

    snapshot = make_snapshot(repo.list_records())
    scope = make_scope(
        roots=(ObservationRootScope("c:/assets", ScopeCompleteness.COMPLETE),),
        explicit_asset_ids=("A-1", "A-999-DOES-NOT-EXIST"),
        explicit_asset_id_completeness=ScopeCompleteness.COMPLETE,
    )
    request = make_request(scope=scope)

    plan, _serialized = run_full_pipeline(request, snapshot)

    asset_ids = {item.subject.asset_id for item in plan.items}
    assert asset_ids == {"A-1"}
    assert "A-999-DOES-NOT-EXIST" not in asset_ids


def test_16_serialized_output_never_contains_record_id(tmp_path):
    """Test 16: Slice 10's record_id-exclusion guarantee holds for a *real*,
    SQLite-assigned record_id value, not just a hand-picked one in
    test_serialization.py's unit tests -- a strictly stronger check than
    Slice 10 alone could run."""
    repo, _ = make_repo(tmp_path)
    inserted = repo.insert(make_record("A-1", normalized_path="c:/assets/a1.mov"))
    assert inserted.record_id is not None

    snapshot = make_snapshot(repo.list_records())
    request = make_request(scope=make_scope())

    _, serialized = run_full_pipeline(request, snapshot)

    assert "record_id" not in json.dumps(serialized)
