"""Tests for the packaged core database schema resource."""
from importlib.resources import files

import pytest

import redline_core.db.database as database_module
from redline_core.db.database import Database


def test_core_schema_is_available_as_package_resource():
    schema_resource = files("redline_core.db").joinpath("schema.sql")

    assert schema_resource.is_file()


def test_core_schema_resource_reads_expected_schema_sql():
    schema_sql = files("redline_core.db").joinpath("schema.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS episodes" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS render_jobs" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS archives" in schema_sql


def test_init_schema_uses_packaged_resource_from_any_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    db = Database(tmp_path / "redline.db").connect()
    try:
        db.init_schema()

        table_names = {
            row["name"]
            for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert {"episodes", "render_jobs", "archives"}.issubset(table_names)
    finally:
        db.close()


def test_init_schema_remains_idempotent_with_packaged_resource(tmp_path):
    db = Database(tmp_path / "redline.db").connect()
    try:
        db.init_schema()
        db.init_schema()

        episode_count = db.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        assert episode_count == 0
    finally:
        db.close()


def test_schema_resource_read_failure_remains_visible(tmp_path, monkeypatch):
    class MissingSchemaResource:
        def joinpath(self, resource_name):
            assert resource_name == "schema.sql"
            return self

        def read_text(self, *, encoding):
            assert encoding == "utf-8"
            raise FileNotFoundError("schema.sql missing")

    monkeypatch.setattr(database_module, "files", lambda package_name: MissingSchemaResource())

    db = Database(tmp_path / "redline.db").connect()
    try:
        with pytest.raises(FileNotFoundError, match="schema.sql missing"):
            db.init_schema()
    finally:
        db.close()
