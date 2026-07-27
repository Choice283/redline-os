"""Integration tests for asset registry SQLite initialization."""
from __future__ import annotations

import sqlite3

import pytest

from redline_core.asset.exceptions import AssetPersistenceError
from redline_core.asset import sqlite_repository
from redline_core.asset.sqlite_repository import (
    ASSET_REGISTRY_SCHEMA_VERSION,
    initialize_asset_registry_database,
)


def object_names(database_path):
    with sqlite3.connect(database_path) as connection:
        return tuple(
            connection.execute(
                """
                SELECT type, name
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            ).fetchall()
        )


def create_database_from_schema(database_path, schema_sql):
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema_sql)


def asset_schema_sql():
    return sqlite_repository._read_schema_sql()


def schema_with_normalized_path_predicate(predicate):
    return asset_schema_sql().replace(
        "lifecycle != 'deprecated'\n  AND normalized_resolved_path IS NOT NULL",
        predicate,
    )


def test_initialize_new_database_creates_schema_version_tables_and_indexes(tmp_path):
    database_path = tmp_path / "asset_registry.db"

    initialize_asset_registry_database(database_path)

    objects = object_names(database_path)
    assert ("table", "asset_registry") in objects
    assert ("table", "asset_registry_schema_metadata") in objects
    assert ("index", "uq_asset_registry_non_deprecated_normalized_path") in objects
    assert ("index", "idx_asset_registry_lifecycle") in objects
    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT value FROM asset_registry_schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert version == ASSET_REGISTRY_SCHEMA_VERSION


def test_initialize_database_is_idempotent(tmp_path):
    database_path = tmp_path / "asset_registry.db"

    initialize_asset_registry_database(database_path)
    before = object_names(database_path)
    initialize_asset_registry_database(database_path)

    assert object_names(database_path) == before


def test_initialize_accepts_valid_schema_with_harmless_extra_table(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    initialize_asset_registry_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE operator_notes (id INTEGER PRIMARY KEY, note TEXT)")

    initialize_asset_registry_database(database_path)

    assert ("table", "operator_notes") in object_names(database_path)


def test_initialize_rejects_wrong_metadata_primary_key(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace("key TEXT PRIMARY KEY", "key TEXT")
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="primary key"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_missing_required_column_not_null(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace("declared_path TEXT NOT NULL", "declared_path TEXT")
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="nullability"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_missing_unique_asset_id_constraint(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace("asset_id TEXT NOT NULL UNIQUE", "asset_id TEXT NOT NULL")
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="unique constraint"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_non_unique_normalized_path_index(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace(
        "CREATE UNIQUE INDEX uq_asset_registry_non_deprecated_normalized_path",
        "CREATE INDEX uq_asset_registry_non_deprecated_normalized_path",
    )
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="index uniqueness"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_wrong_normalized_path_index_columns(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace(
        "ON asset_registry(normalized_resolved_path)",
        "ON asset_registry(asset_id)",
    )
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="index columns"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_wrong_normalized_path_partial_predicate(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = schema_with_normalized_path_predicate(
        "lifecycle = 'deprecated'\n  AND normalized_resolved_path IS NOT NULL"
    )
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="predicate"):
        initialize_asset_registry_database(database_path)


@pytest.mark.parametrize(
    "predicate",
    [
        "lifecycle != 'deprecated'\n  OR normalized_resolved_path IS NOT NULL",
        "lifecycle = 'active'\n  AND normalized_resolved_path IS NOT NULL",
        "lifecycle != 'deprecated'\n  AND normalized_resolved_path IS NULL",
        "lifecycle != 'deprecated'",
        "normalized_resolved_path IS NOT NULL",
        "NOT (lifecycle = 'deprecated' AND normalized_resolved_path IS NULL)",
        "(lifecycle != 'deprecated' AND normalized_resolved_path IS NOT NULL) OR lifecycle = 'active'",
    ],
)
def test_initialize_rejects_materially_different_normalized_path_predicates(tmp_path, predicate):
    database_path = tmp_path / "asset_registry.db"
    create_database_from_schema(database_path, schema_with_normalized_path_predicate(predicate))

    with pytest.raises(AssetPersistenceError, match="predicate"):
        initialize_asset_registry_database(database_path)


@pytest.mark.parametrize(
    "predicate",
    [
        "(lifecycle <> 'deprecated')\n  AND (normalized_resolved_path IS NOT NULL)",
        "normalized_resolved_path IS NOT NULL\n  AND lifecycle != 'deprecated'",
        '( "lifecycle" != \'deprecated\' ) AND ( "normalized_resolved_path" IS NOT NULL )',
    ],
)
def test_initialize_accepts_equivalent_normalized_path_predicates(tmp_path, predicate):
    database_path = tmp_path / "asset_registry.db"
    create_database_from_schema(database_path, schema_with_normalized_path_predicate(predicate))

    initialize_asset_registry_database(database_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute(
            "SELECT value FROM asset_registry_schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert version == ASSET_REGISTRY_SCHEMA_VERSION


def test_initialize_rejects_missing_required_enum_check_constraint(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace(
        "lifecycle TEXT NOT NULL CHECK (lifecycle IN ('declared', 'active', 'deprecated')),",
        "lifecycle TEXT NOT NULL,",
    )
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="CHECK constraints"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_missing_non_negative_size_check_constraint(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    schema_sql = asset_schema_sql().replace(
        "file_size_bytes INTEGER CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),",
        "file_size_bytes INTEGER,",
    )
    create_database_from_schema(database_path, schema_sql)

    with pytest.raises(AssetPersistenceError, match="CHECK constraints"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_unsupported_newer_schema_version(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    initialize_asset_registry_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE asset_registry_schema_metadata SET value = '2' WHERE key = 'schema_version'"
        )

    with pytest.raises(AssetPersistenceError, match="Unsupported"):
        initialize_asset_registry_database(database_path)


def test_initialize_rejects_malformed_schema_version(tmp_path):
    database_path = tmp_path / "asset_registry.db"
    initialize_asset_registry_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE asset_registry_schema_metadata SET value = ' 1 ' WHERE key = 'schema_version'"
        )

    with pytest.raises(AssetPersistenceError, match="malformed"):
        initialize_asset_registry_database(database_path)


def test_initialize_rolls_back_partial_schema_on_failure(tmp_path, monkeypatch):
    database_path = tmp_path / "asset_registry.db"

    def failing_schema(connection, schema_sql):
        connection.execute("CREATE TABLE asset_registry_schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raise sqlite3.OperationalError("synthetic schema failure")

    monkeypatch.setattr(sqlite_repository, "_execute_schema", failing_schema)

    with pytest.raises(AssetPersistenceError):
        initialize_asset_registry_database(database_path)

    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'asset_registry_schema_metadata'"
        ).fetchone()
    assert table is None


def test_initialize_rejects_directory_database_path(tmp_path):
    with pytest.raises(AssetPersistenceError):
        initialize_asset_registry_database(tmp_path)


def test_initialize_creates_parent_directory_and_closes_connection(tmp_path):
    database_path = tmp_path / "nested" / "asset_registry.db"

    initialize_asset_registry_database(database_path)
    database_path.unlink()

    assert not database_path.exists()


def test_schema_resource_loading_reads_packaged_utf8_text(monkeypatch):
    class FakeResource:
        def __init__(self):
            self.encoding = None

        def joinpath(self, name):
            assert name == "schema.sql"
            return self

        def is_file(self):
            return True

        def read_text(self, *, encoding):
            self.encoding = encoding
            return "CREATE TABLE example (name TEXT);"

    resource = FakeResource()
    monkeypatch.setattr(sqlite_repository, "files", lambda package: resource)

    assert sqlite_repository._read_schema_sql() == "CREATE TABLE example (name TEXT);"
    assert resource.encoding == "utf-8"


def test_missing_schema_resource_becomes_persistence_error(monkeypatch):
    class MissingResource:
        def joinpath(self, name):
            return self

        def is_file(self):
            return False

    monkeypatch.setattr(sqlite_repository, "files", lambda package: MissingResource())

    with pytest.raises(AssetPersistenceError, match="schema resource"):
        sqlite_repository._read_schema_sql()


def test_schema_resource_read_failure_becomes_persistence_error(monkeypatch):
    class FailingResource:
        def joinpath(self, name):
            return self

        def is_file(self):
            return True

        def read_text(self, *, encoding):
            raise OSError("C:/secret/install/path/schema.sql")

    monkeypatch.setattr(sqlite_repository, "files", lambda package: FailingResource())

    with pytest.raises(AssetPersistenceError, match="schema resource") as exc_info:
        sqlite_repository._read_schema_sql()

    assert isinstance(exc_info.value.__cause__, OSError)
    assert "C:/secret/install/path" not in str(exc_info.value)
