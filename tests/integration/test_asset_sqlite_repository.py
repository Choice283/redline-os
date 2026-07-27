"""Integration tests for the SQLite asset registry repository."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import sqlite3

import pytest

from redline_core.asset.exceptions import (
    AssetConflictError,
    AssetNotFoundError,
    AssetPathConflictError,
    AssetPersistenceError,
    DuplicateAssetIdError,
)
from redline_core.asset.models import (
    AssetAvailability,
    AssetDiagnosticCode,
    AssetLifecycle,
    AssetRegistryRecord,
    AssetSourceKind,
    AssetVerificationState,
)
from redline_core.asset.sqlite_repository import SQLiteAssetRepository, initialize_asset_registry_database


NOW = datetime(2026, 7, 27, 14, 30, 15, 123456, tzinfo=timezone.utc)


def make_repo(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    initialize_asset_registry_database(database_path)
    return SQLiteAssetRepository(database_path), database_path


def make_record(
    asset_id="RLG-001",
    *,
    record_id=None,
    declared_path="logos/lower_third.png",
    resolved_path="C:/assets/logos/lower_third.png",
    normalized_resolved_path="c:/assets/logos/lower_third.png",
    lifecycle=AssetLifecycle.DECLARED,
    availability=AssetAvailability.UNKNOWN,
    verification=AssetVerificationState.UNVERIFIED,
    file_size_bytes=None,
    file_modified_at=None,
    last_verified_at=None,
    created_at=NOW,
    updated_at=NOW,
    diagnostic_code=None,
    diagnostic_message=None,
    source_detail="config/assets.yaml",
):
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


def available_record(asset_id="RLG-001", normalized_path="c:/assets/logos/lower_third.png"):
    return make_record(
        asset_id,
        lifecycle=AssetLifecycle.ACTIVE,
        availability=AssetAvailability.AVAILABLE,
        verification=AssetVerificationState.VERIFIED,
        file_size_bytes=0,
        file_modified_at=NOW,
        last_verified_at=NOW,
        normalized_resolved_path=normalized_path,
    )


def test_insert_assigns_id_round_trips_and_preserves_caller_record(tmp_path):
    repo, _ = make_repo(tmp_path)
    record = make_record()

    inserted = repo.insert(record)

    assert inserted.record_id is not None and inserted.record_id > 0
    assert record.record_id is None
    assert repo.get_by_asset_id("RLG-001") == inserted
    assert repo.get_by_record_id(inserted.record_id) == inserted


def test_insert_rejects_duplicate_asset_id(tmp_path):
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record())

    with pytest.raises(DuplicateAssetIdError):
        repo.insert(make_record(normalized_resolved_path="c:/assets/other.png"))


def test_insert_rejects_non_deprecated_normalized_path_conflict(tmp_path):
    repo, _ = make_repo(tmp_path)
    repo.insert(available_record("RLG-001", "c:/assets/shared.png"))

    with pytest.raises(AssetPathConflictError):
        repo.insert(available_record("RLG-002", "c:/assets/shared.png"))


def test_insert_allows_null_normalized_path_and_deprecated_same_path(tmp_path):
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("RLG-001", resolved_path=None, normalized_resolved_path=None))
    repo.insert(make_record("RLG-002", resolved_path=None, normalized_resolved_path=None))
    repo.insert(available_record("RLG-003", "c:/assets/shared.png"))
    deprecated = repo.insert(
        available_record("RLG-004", "c:/assets/shared.png").__class__(
            **{
                **available_record("RLG-004", "c:/assets/shared.png").__dict__,
                "lifecycle": AssetLifecycle.DEPRECATED,
            }
        )
    )

    assert deprecated.lifecycle is AssetLifecycle.DEPRECATED
    assert repo.count_records() == 4


def test_unicode_values_round_trip(tmp_path):
    repo, _ = make_repo(tmp_path)
    record = make_record(
        "资产-001",
        declared_path="图形/下三分之一.png",
        resolved_path="C:/assets/图形/下三分之一.png",
        normalized_resolved_path="c:/assets/图形/下三分之一.png",
        diagnostic_message="缺失",
    )

    inserted = repo.insert(record)

    assert inserted.asset_id == "资产-001"
    assert inserted.declared_path == "图形/下三分之一.png"
    assert inserted.created_at.microsecond == 123456


def test_update_persists_valid_record_and_preserves_identity(tmp_path):
    repo, _ = make_repo(tmp_path)
    inserted = repo.insert(make_record())
    updated = replace(
        inserted,
        availability=AssetAvailability.MISSING,
        verification=AssetVerificationState.VERIFIED,
        last_verified_at=NOW,
        updated_at=datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc),
        diagnostic_code=AssetDiagnosticCode.FILE_MISSING,
        diagnostic_message="Asset file is missing.",
    )

    stored = repo.update(updated)

    assert stored.record_id == inserted.record_id
    assert stored.asset_id == inserted.asset_id
    assert stored.created_at == inserted.created_at
    assert stored.updated_at == updated.updated_at
    assert stored.availability is AssetAvailability.MISSING


def test_update_missing_record_raises_not_found(tmp_path):
    repo, _ = make_repo(tmp_path)
    record = make_record(record_id=999)

    with pytest.raises(AssetNotFoundError):
        repo.update(record)


def test_update_rejects_asset_id_mutation(tmp_path):
    repo, _ = make_repo(tmp_path)
    inserted = repo.insert(make_record())
    mutated = replace(inserted, asset_id="RLG-999")

    with pytest.raises(AssetConflictError):
        repo.update(mutated)


def test_update_translates_uniqueness_conflict(tmp_path):
    repo, _ = make_repo(tmp_path)
    first = repo.insert(available_record("RLG-001", "c:/assets/one.png"))
    repo.insert(available_record("RLG-002", "c:/assets/two.png"))

    with pytest.raises(AssetPathConflictError):
        repo.update(replace(first, normalized_resolved_path="c:/assets/two.png"))


def test_read_methods_filter_and_order_deterministically(tmp_path):
    repo, _ = make_repo(tmp_path)
    repo.insert(make_record("RLG-002", normalized_resolved_path="c:/assets/two.png"))
    active = repo.insert(available_record("RLG-001", "c:/assets/one.png"))
    deprecated = repo.insert(replace(available_record("RLG-003", "c:/assets/one.png"), lifecycle=AssetLifecycle.DEPRECATED))

    assert repo.get_by_asset_id("missing") is None
    assert [record.asset_id for record in repo.list_records()] == ["RLG-001", "RLG-002", "RLG-003"]
    assert [record.asset_id for record in repo.list_records(include_deprecated=False)] == ["RLG-001", "RLG-002"]
    assert repo.list_records(lifecycle=AssetLifecycle.ACTIVE) == (active,)
    assert repo.get_by_normalized_path("c:/assets/one.png") == (active,)
    assert repo.get_by_normalized_path("c:/assets/one.png", include_deprecated=True) == (active, deprecated)
    assert repo.count_records(include_deprecated=False) == 2
    with pytest.raises(Exception):
        repo.list_records()[0] = active


def test_empty_database_reads_are_empty(tmp_path):
    repo, _ = make_repo(tmp_path)

    assert repo.list_records() == ()
    assert repo.count_records() == 0
    assert repo.get_by_normalized_path("missing") == ()


def test_transaction_commits_multiple_writes_atomically(tmp_path):
    repo, _ = make_repo(tmp_path)

    with repo.transaction() as connection:
        first = repo.insert(make_record("RLG-001", normalized_resolved_path="c:/assets/one.png"), connection=connection)
        repo.insert(make_record("RLG-002", normalized_resolved_path="c:/assets/two.png"), connection=connection)
        repo.update(replace(first, updated_at=datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)), connection=connection)

    assert repo.count_records() == 2
    assert repo.get_by_asset_id("RLG-001").updated_at.hour == 15


def test_transaction_rolls_back_on_exception(tmp_path):
    repo, _ = make_repo(tmp_path)

    with pytest.raises(RuntimeError):
        with repo.transaction() as connection:
            repo.insert(make_record("RLG-001"), connection=connection)
            raise RuntimeError("stop")

    assert repo.count_records() == 0


def test_external_transaction_is_not_committed_by_repository_method(tmp_path):
    repo, database_path = make_repo(tmp_path)

    with repo.transaction() as connection:
        repo.insert(make_record("RLG-001"), connection=connection)
        with sqlite3.connect(database_path) as observer:
            assert observer.execute("SELECT COUNT(*) FROM asset_registry").fetchone()[0] == 0

    assert repo.count_records() == 1


def test_nested_transaction_is_rejected(tmp_path):
    repo, _ = make_repo(tmp_path)

    with pytest.raises(AssetPersistenceError):
        with repo.transaction():
            with repo.transaction():
                pass


def test_locked_database_failure_becomes_persistence_error(tmp_path):
    repo, database_path = make_repo(tmp_path)
    locker = sqlite3.connect(database_path, timeout=0.1)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(AssetPersistenceError):
            SQLiteAssetRepository(database_path, timeout_seconds=0.1).insert(make_record("RLG-001"))
    finally:
        locker.rollback()
        locker.close()


def raw_insert(connection, **overrides):
    values = {
        "asset_id": "RLG-BAD",
        "declared_path": "bad.png",
        "resolved_path": "C:/assets/bad.png",
        "normalized_resolved_path": "c:/assets/bad.png",
        "approved_root_id": "assets_path",
        "lifecycle": "declared",
        "availability": "unknown",
        "verification": "unverified",
        "file_size_bytes": None,
        "file_modified_at": None,
        "last_verified_at": None,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "source_kind": "config_reconciliation",
        "source_detail": None,
        "diagnostic_code": None,
        "diagnostic_message": None,
    }
    values.update(overrides)
    connection.execute("PRAGMA ignore_check_constraints = ON")
    connection.execute(
        """
        INSERT INTO asset_registry (
            asset_id,
            declared_path,
            resolved_path,
            normalized_resolved_path,
            approved_root_id,
            lifecycle,
            availability,
            verification,
            file_size_bytes,
            file_modified_at,
            last_verified_at,
            created_at,
            updated_at,
            source_kind,
            source_detail,
            diagnostic_code,
            diagnostic_message
        ) VALUES (
            :asset_id,
            :declared_path,
            :resolved_path,
            :normalized_resolved_path,
            :approved_root_id,
            :lifecycle,
            :availability,
            :verification,
            :file_size_bytes,
            :file_modified_at,
            :last_verified_at,
            :created_at,
            :updated_at,
            :source_kind,
            :source_detail,
            :diagnostic_code,
            :diagnostic_message
        )
        """,
        values,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"lifecycle": "bad"},
        {"availability": "bad"},
        {"verification": "bad"},
        {"created_at": "not-a-date"},
        {"created_at": "2026-07-27T14:30:00"},
        {"availability": "available", "verification": "verified", "last_verified_at": NOW.isoformat()},
        {"file_size_bytes": -1},
    ],
)
def test_malformed_rows_translate_to_persistence_error(tmp_path, overrides):
    repo, database_path = make_repo(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        raw_insert(connection, **overrides)

    with pytest.raises(AssetPersistenceError):
        repo.get_by_asset_id("RLG-BAD")
