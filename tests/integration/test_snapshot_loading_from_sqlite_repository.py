"""Integration tests: RegistrySnapshot loading from SQLiteAssetRepository reads.

Implements the approved "Phase 3 Slice 11 Implementation Contract --
Integration Compatibility (Roadmap Row 13), Revision 3 (final)", test
matrix entries 1-5 and 17 (numbered in each test's docstring below for
traceability). Proves that a ``RegistrySnapshot`` built from records read
out of a real (temporary) SQLite database, via the existing
``SQLiteAssetRepository`` read API, is accepted by the reconciliation
package exactly as one built from in-memory ``AssetRegistryRecord``
literals already is.

This file introduces no production code. It only exercises existing,
unmodified APIs on both sides of the repository/reconciliation boundary:
``SQLiteAssetRepository`` (Phase 1/2) and ``RegistrySnapshot`` (Phase 3).
Builder functions are local to this file, matching the established
per-file convention elsewhere in this test suite (e.g.
``test_serialization.py`` does not import from ``test_planner.py``).

Tests 2, 5, and 17 are lightweight bridge assertions, not full-weight
compatibility proofs -- see each docstring for what it does and does not
prove, and the approved contract's Section 14 for the full rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone

from redline_core.asset.models import (
    AssetAvailability,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.reconciliation import RegistrySnapshot
from redline_core.asset.sqlite_repository import SQLiteAssetRepository, initialize_asset_registry_database

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def make_repo(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    initialize_asset_registry_database(database_path)
    return SQLiteAssetRepository(database_path), database_path


def make_record(
    asset_id,
    *,
    record_id=None,
    declared_path=None,
    resolved_path=None,
    normalized_resolved_path=None,
    lifecycle=AssetLifecycle.ACTIVE,
    availability=AssetAvailability.AVAILABLE,
    verification=AssetVerificationState.VERIFIED,
    file_size_bytes=1024,
    file_modified_at=NOW,
    last_verified_at=NOW,
    created_at=NOW,
    updated_at=NOW,
    diagnostic_code=None,
    diagnostic_message=None,
    source_detail=None,
):
    if declared_path is None:
        declared_path = f"assets/{asset_id}.mov"
    if normalized_resolved_path is not None and resolved_path is None:
        resolved_path = f"C:/assets/{asset_id}.mov"
    return AssetRegistryRecord(
        record_id=record_id,
        asset_id=asset_id,
        declared_path=declared_path,
        resolved_path=resolved_path,
        normalized_resolved_path=normalized_resolved_path,
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
        source_detail=source_detail,
        diagnostic_code=diagnostic_code,
        diagnostic_message=diagnostic_message,
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


def test_01_snapshot_loads_from_sqlite_list_records(tmp_path):
    """Test 1: a RegistrySnapshot accepts, without error, a tuple of
    AssetRegistryRecord values that actually came from a live SQLite read,
    not just hand-built literals."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1"))
    repo.insert(make_record("A-2"))
    repo.insert(make_record("A-3"))

    loaded = repo.list_records()
    snapshot = make_snapshot(loaded)

    assert {record.asset_id for record in snapshot.records} == {"A-1", "A-2", "A-3"}
    assert len(snapshot.records) == 3


def test_02_list_records_read_order_is_ascending_by_asset_id(tmp_path):
    """Test 2 (bridge assertion): confirms the ordering precondition Test 1
    and Section 7's determinism argument depend on, at the exact call site
    this slice uses. Full repository-ordering coverage belongs to
    test_asset_sqlite_repository.py; this only reconfirms the specific
    guarantee this slice relies on."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("Z-9"))
    repo.insert(make_record("A-1"))
    repo.insert(make_record("M-5"))

    loaded = repo.list_records()

    assert [record.asset_id for record in loaded] == ["A-1", "M-5", "Z-9"]


def test_03_sqlite_round_trip_equals_inserted_record_with_assigned_record_id(tmp_path):
    """Test 3: true field-for-field round-trip equality once the comparison
    side uses the actual record_id SQLite assigned (contract Section 4a --
    this is the round-trip check, distinct from the cross-domain
    equivalence check in test_reconciliation_repository_compatibility.py's
    test 7, which deliberately uses a *different* record_id)."""
    repo, _ = make_repo(tmp_path)
    inserted = repo.insert(make_record("A-1", normalized_resolved_path="c:/assets/a1.mov"))

    (loaded,) = repo.list_records()

    expected = make_record(
        "A-1", record_id=inserted.record_id, normalized_resolved_path="c:/assets/a1.mov"
    )
    assert loaded == expected


def test_04_empty_registry_constructs_valid_empty_snapshot(tmp_path):
    """Test 4: a RegistrySnapshot accepts a zero-length tuple sourced from a
    real (empty) SQLite read."""
    repo, _ = make_repo(tmp_path)

    loaded = repo.list_records()
    snapshot = make_snapshot(loaded)

    assert snapshot.records == ()


def test_05_insert_requires_none_record_id_and_assigns_one(tmp_path):
    """Test 5 (bridge assertion): confirms the specific insert() precondition
    every other test in this file depends on -- record_id must be None
    going in, and insert() returns a record with record_id assigned. Full
    insert-behavior coverage belongs to test_asset_sqlite_repository.py."""
    repo, _ = make_repo(tmp_path)

    inserted = repo.insert(make_record("A-1", record_id=None))

    assert inserted.record_id is not None
    assert isinstance(inserted.record_id, int)
    assert inserted.record_id > 0

    snapshot = make_snapshot((inserted,))
    assert snapshot.records == (inserted,)


def test_17_get_by_normalized_path_results_are_valid_snapshot_input(tmp_path):
    """Test 17 (bridge assertion only, added in Revision 3 to replace the
    conflated part of the original test 10): get_by_normalized_path()'s
    filtered result set is itself a valid RegistrySnapshot.records input.
    This does NOT claim to exercise reconciliation scope resolution -- see
    test_10_path_scope_resolves_against_complete_sqlite_registry in
    test_reconciliation_repository_compatibility.py for the real
    scope-resolution compatibility test, which is built from
    list_records() so the repository never pre-filters what reconciliation
    sees."""
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("A-1", normalized_resolved_path="c:/assets/a1.mov"))
    repo.insert(make_record("A-2", normalized_resolved_path=None))

    matched = repo.get_by_normalized_path("c:/assets/a1.mov")

    snapshot = make_snapshot(matched)
    assert {record.asset_id for record in snapshot.records} == {"A-1"}
