"""Tests for Mission 1B-A1 schema-compatibility fingerprinting
(redline_core.restore.schema_fingerprint) against real, temporary SQLite
databases -- the reference fingerprint is always built via the real,
current Database.init_schema(); target fingerprints under test are built
either the same way (accept case) or via raw sqlite3 DDL (every reject
case), proving the comparison is genuinely structural, not a rubber stamp.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from redline_core.db.database import Database
from redline_core.restore.exceptions import RestoreSchemaIncompatibleError, RestoreUnsupportedSchemaObjectError
from redline_core.restore.schema_fingerprint import (
    build_reference_schema_fingerprint,
    build_schema_fingerprint,
    compare_schema_fingerprints,
    require_schema_compatible,
)

from tests.unit._restore_test_helpers import make_raw_sqlite_db, make_real_schema_db


def _dump_statements(db_path: Path) -> tuple[list[str], list[str]]:
    """Return (table_statements, index_statements) from a real,
    init_schema()'d database's own sqlite_master -- the exact DDL the
    running application code actually produces, not a hand-copied guess."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    tables = [sql for (typ, name, sql) in rows if typ == "table" and not name.startswith("sqlite_")]
    indexes = [sql for (typ, name, sql) in rows if typ == "index" and not name.startswith("sqlite_")]
    return tables, indexes


@pytest.fixture()
def real_ddl(tmp_path: Path) -> tuple[list[str], list[str]]:
    ref_db = tmp_path / "_schema_dump.db"
    make_real_schema_db(ref_db, with_episode=False)
    return _dump_statements(ref_db)


# -- accept: exact current schema ---------------------------------------------


def test_exact_current_schema_accepts(tmp_path: Path):
    target_db = tmp_path / "target.db"
    make_real_schema_db(target_db, with_episode=True)
    require_schema_compatible(target_db)  # must not raise


def test_two_independently_built_reference_fingerprints_are_identical():
    a = build_reference_schema_fingerprint()
    b = build_reference_schema_fingerprint()
    compare_schema_fingerprints(a, b)  # must not raise
    assert a == b


# -- table inventory -----------------------------------------------------------


def test_unexpected_table_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + indexes + ["CREATE TABLE extra_widgets (id INTEGER PRIMARY KEY)"])
    with pytest.raises(RestoreSchemaIncompatibleError, match="table inventory mismatch"):
        require_schema_compatible(target_db)


def test_missing_table_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    tables_missing_one = [t for t in tables if "archives" not in t]
    indexes_for_remaining = [i for i in indexes if "archives" not in i]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables_missing_one + indexes_for_remaining)
    with pytest.raises(RestoreSchemaIncompatibleError, match="table inventory mismatch"):
        require_schema_compatible(target_db)


# -- column shape ----------------------------------------------------------------


def test_extra_column_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    mutated = [t.replace("project_name TEXT NOT NULL,", "project_name TEXT NOT NULL, extra_col TEXT,") for t in tables]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, mutated + indexes)
    with pytest.raises(RestoreSchemaIncompatibleError, match="column shape mismatch"):
        require_schema_compatible(target_db)


def test_missing_column_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    mutated = [t.replace("resolve_job_id TEXT,", "") for t in tables]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, mutated + indexes)
    with pytest.raises(RestoreSchemaIncompatibleError, match="column shape mismatch"):
        require_schema_compatible(target_db)


# -- index inventory / structure --------------------------------------------------


def test_missing_required_explicit_index_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    remaining = [i for i in indexes if "idx_render_jobs_episode_id" not in i]
    assert len(remaining) < len(indexes)
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + remaining)
    with pytest.raises(RestoreSchemaIncompatibleError, match="index inventory mismatch"):
        require_schema_compatible(target_db)


def test_unexpected_index_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    extra_index = ["CREATE INDEX idx_episodes_status ON episodes(status)"]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + indexes + extra_index)
    with pytest.raises(RestoreSchemaIncompatibleError, match="index inventory mismatch"):
        require_schema_compatible(target_db)


def test_wrong_uniqueness_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    mutated = [
        i.replace(
            "CREATE UNIQUE INDEX idx_render_jobs_active_output_path",
            "CREATE INDEX idx_render_jobs_active_output_path",
        )
        for i in indexes
    ]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + mutated)
    with pytest.raises(RestoreSchemaIncompatibleError, match="structural mismatch"):
        require_schema_compatible(target_db)


def test_wrong_indexed_columns_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    mutated = [i.replace("ON render_jobs(episode_id)", "ON render_jobs(preset_name)") for i in indexes]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + mutated)
    with pytest.raises(RestoreSchemaIncompatibleError, match="structural mismatch"):
        require_schema_compatible(target_db)


def test_partial_index_different_where_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    mutated = [
        i.replace(
            "WHERE output_path IS NOT NULL AND status IN ('claiming', 'queued', 'rendering')",
            "WHERE output_path IS NOT NULL AND status IN ('claiming', 'queued')",
        )
        for i in indexes
    ]
    assert any("WHERE output_path IS NOT NULL AND status IN ('claiming', 'queued')" in m for m in mutated)
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + mutated)
    with pytest.raises(RestoreSchemaIncompatibleError, match="definition mismatch"):
        require_schema_compatible(target_db)


def test_collation_mismatch_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    mutated_tables = [t.replace("episode_id TEXT NOT NULL UNIQUE,", "episode_id TEXT COLLATE NOCASE NOT NULL UNIQUE,") for t in tables]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, mutated_tables + indexes)
    with pytest.raises(RestoreSchemaIncompatibleError):
        require_schema_compatible(target_db)


def test_autoindex_structural_mismatch_rejects(tmp_path: Path, real_ddl):
    """episodes.episode_number's UNIQUE constraint produces a real SQLite
    autoindex (origin='u', no CREATE INDEX text of its own) -- dropping the
    UNIQUE constraint removes that autoindex entirely, which the structural
    (PRAGMA index_xinfo-based) comparison must still catch since there is
    no SQL text to compare for it."""
    tables, indexes = real_ddl
    mutated = [t.replace("episode_number INTEGER NOT NULL UNIQUE,", "episode_number INTEGER NOT NULL,") for t in tables]
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, mutated + indexes)
    with pytest.raises(RestoreSchemaIncompatibleError, match="index inventory mismatch"):
        require_schema_compatible(target_db)


def test_autoindex_present_and_structurally_identical_accepts(tmp_path: Path, real_ddl):
    """The reverse of the above: an unmodified schema's autoindexes (no
    SQL text) must still compare equal via pure structural (index_xinfo)
    comparison alone -- proving autoindex handling isn't simply "always
    reject because there's no SQL to compare"."""
    tables, indexes = real_ddl
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + indexes)
    require_schema_compatible(target_db)  # must not raise


# -- unsupported schema objects ----------------------------------------------------


def test_view_in_target_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(
        target_db, tables + indexes + ["CREATE VIEW episode_summary AS SELECT episode_id FROM episodes"]
    )
    with pytest.raises(RestoreUnsupportedSchemaObjectError):
        require_schema_compatible(target_db)


def test_trigger_in_target_rejects(tmp_path: Path, real_ddl):
    tables, indexes = real_ddl
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(
        target_db,
        tables
        + indexes
        + [
            "CREATE TRIGGER trg_touch_episode AFTER UPDATE ON episodes BEGIN "
            "UPDATE episodes SET updated_at = datetime('now') WHERE id = NEW.id; END"
        ],
    )
    with pytest.raises(RestoreUnsupportedSchemaObjectError):
        require_schema_compatible(target_db)


# -- Database.init_schema() boundary ------------------------------------------------


def test_init_schema_never_called_on_target_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_ddl):
    tables, indexes = real_ddl
    target_db = tmp_path / "target.db"
    make_raw_sqlite_db(target_db, tables + indexes)

    calls: list[Path] = []
    real_init_schema = Database.init_schema

    def _tracking_init_schema(self):
        calls.append(Path(self.db_path))
        return real_init_schema(self)

    monkeypatch.setattr(Database, "init_schema", _tracking_init_schema)

    require_schema_compatible(target_db)

    assert len(calls) == 1, "init_schema() must be called exactly once, for the disposable reference DB only"
    assert calls[0] != target_db
    assert calls[0].parent != target_db.parent


def test_build_schema_fingerprint_target_never_uses_database_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """build_schema_fingerprint() itself (as opposed to
    require_schema_compatible(), which additionally builds a reference)
    must never touch Database at all -- it is a pure PRAGMA/sqlite_master
    reader."""
    target_db = tmp_path / "target.db"
    make_real_schema_db(target_db, with_episode=False)

    def _boom(self):
        raise AssertionError("Database.init_schema() must never be called by build_schema_fingerprint()")

    monkeypatch.setattr(Database, "init_schema", _boom)
    build_schema_fingerprint(target_db, read_only=True)  # must not raise
