"""Tests for redline_core.restore.recovery_classification (Mission 1B-A2-1):
per-side (database, config) read-only source classification, against real,
temporary SQLite databases and real config directories -- no mocking of
SQLite itself, mirroring tests/unit/test_restore_manager.py's own
established convention. Symlink/junction/reparse-point cases are proven by
monkeypatching `fsutil.is_unsafe_link` rather than creating real
symlinks/junctions, matching tests/unit/test_backup_paths.py's own
documented precedent for exactly this reason (elevated privileges may be
required on Windows).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from redline_core import fsutil
from redline_core.config.loader import REQUIRED_FILES
from redline_core.restore import recovery_classification as rc
from redline_core.restore.recovery_models import RecoveryFeasibility, SourceCondition

from tests.unit._restore_test_helpers import make_real_schema_db, write_minimal_config_dir


# -- database classification ---------------------------------------------------------


def test_classify_database_healthy(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    make_real_schema_db(db_path)

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.HEALTHY
    assert result.feasibility is RecoveryFeasibility.NOT_APPLICABLE
    assert result.blocking_reason is None
    assert result.capture_required is False
    assert result.disposition_required is False


def test_classify_database_missing_parent_intact(tmp_path: Path):
    db_path = tmp_path / "redline.db"  # tmp_path (parent) exists; db_path does not

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.MISSING
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True
    assert result.disposition_required is False


def test_classify_database_missing_parent_also_missing_is_recovery_blocked(tmp_path: Path):
    db_path = tmp_path / "does_not_exist_either" / "redline.db"

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.MISSING
    assert result.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED
    assert result.blocking_reason is not None
    assert "parent directory" in result.blocking_reason


def test_classify_database_degraded_not_valid_sqlite(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"this is not a sqlite database at all")

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True
    assert result.disposition_required is False
    assert any("PRAGMA integrity_check" in d or "opened as SQLite" in d for d in result.details)


def test_classify_database_degraded_fails_integrity_check(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    make_real_schema_db(db_path)
    # Corrupt the file after it's a real, opened-at-least-once SQLite file.
    data = bytearray(db_path.read_bytes())
    # Flip bytes well past the header so sqlite3.connect() itself still
    # succeeds lazily, and PRAGMA integrity_check is what actually detects it.
    for i in range(200, min(len(data), 4000)):
        data[i] ^= 0xFF
    db_path.write_bytes(bytes(data))

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True


def test_classify_database_path_is_directory(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True
    assert result.disposition_required is True
    assert result.disposition_description is not None
    assert "Windows" in result.disposition_description


def test_classify_database_unsafe_link_is_recovery_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"stand-in object")  # never actually opened -- unsafe check runs first

    monkeypatch.setattr(fsutil, "is_unsafe_link", lambda st: True)

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED
    assert result.blocking_reason is not None
    assert "symlink" in result.blocking_reason


def test_classify_database_cannot_inspect_is_recovery_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "redline.db"

    def _raise_permission_error(path):
        raise PermissionError("simulated permission denied")

    monkeypatch.setattr(rc.os, "lstat", _raise_permission_error)

    result = rc.classify_database_source(db_path)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED


# -- config classification -------------------------------------------------------------


def test_classify_config_healthy(tmp_path: Path):
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir)

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.HEALTHY
    assert result.feasibility is RecoveryFeasibility.NOT_APPLICABLE
    assert result.capture_required is False


def test_classify_config_healthy_even_with_malformed_yaml_content(tmp_path: Path):
    """Mission 1A's own create_backup() never validates config *content* --
    only existence/safety/read-stability -- so A2-1 must not broaden that
    contract either."""
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir)
    (config_dir / "naming.yaml").write_text("this: is: not: valid: yaml: [[[", encoding="utf-8")

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.HEALTHY
    assert result.feasibility is RecoveryFeasibility.NOT_APPLICABLE


def test_classify_config_missing_parent_intact(tmp_path: Path):
    config_dir = tmp_path / "config"  # never created

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.MISSING
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True
    assert result.disposition_required is False


def test_classify_config_missing_parent_also_missing_is_recovery_blocked(tmp_path: Path):
    config_dir = tmp_path / "nope" / "config"

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.MISSING
    assert result.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED


def test_classify_config_degraded_required_file_missing(tmp_path: Path):
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir, omit="paths.yaml")

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True
    assert any("paths.yaml" in d for d in result.details)


def test_classify_config_degraded_required_file_wrong_type(tmp_path: Path):
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir)
    (config_dir / "assets.yaml").unlink()
    (config_dir / "assets.yaml").mkdir()  # a directory sits where a file should be

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.disposition_required is False  # whole-directory rename-aside handles this


def test_classify_config_path_is_regular_file(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.write_bytes(b"a lone file where a config directory should be")

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert result.capture_required is True
    assert result.disposition_required is True
    assert result.disposition_description is not None


def test_classify_config_unsafe_link_directory_is_recovery_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    monkeypatch.setattr(fsutil, "is_unsafe_link", lambda st: True)

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED


def test_classify_config_unsafe_link_required_file_is_recovery_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir)

    target_file = config_dir / sorted(REQUIRED_FILES.values())[0]
    target_ino_dev = (target_file.stat().st_ino, target_file.stat().st_dev)
    real_is_unsafe_link = fsutil.is_unsafe_link

    def _fake_is_unsafe_link(st):
        if (st.st_ino, st.st_dev) == target_ino_dev:
            return True
        return real_is_unsafe_link(st)

    monkeypatch.setattr(fsutil, "is_unsafe_link", _fake_is_unsafe_link)

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERY_BLOCKED


def test_classify_config_unreadable_required_file_is_degraded_recoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir)

    def _raise_source_changed(path, *, exceptions=None):
        raise fsutil.SourceChangedError("simulated unstable read")

    monkeypatch.setattr(rc.fsutil, "hash_stable_file", _raise_source_changed)

    result = rc.classify_config_source(config_dir)

    assert result.condition is SourceCondition.DEGRADED
    assert result.feasibility is RecoveryFeasibility.RECOVERABLE
    assert any("unreadable or unstable" in d for d in result.details)


# -- read-only guarantee -----------------------------------------------------------


def test_database_classification_creates_no_sidecars(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    make_real_schema_db(db_path)

    rc.classify_database_source(db_path)

    for suffix in ("-journal", "-wal", "-shm"):
        assert not Path(str(db_path) + suffix).exists()


def test_database_classification_leaves_bytes_unchanged(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    make_real_schema_db(db_path)
    before = db_path.read_bytes()

    rc.classify_database_source(db_path)

    assert db_path.read_bytes() == before


def test_config_classification_leaves_directory_inventory_unchanged(tmp_path: Path):
    config_dir = tmp_path / "config"
    write_minimal_config_dir(config_dir)
    before = sorted(p.name for p in config_dir.iterdir())
    before_bytes = {p.name: p.read_bytes() for p in config_dir.iterdir()}

    rc.classify_config_source(config_dir)

    assert sorted(p.name for p in config_dir.iterdir()) == before
    for name, content in before_bytes.items():
        assert (config_dir / name).read_bytes() == content
