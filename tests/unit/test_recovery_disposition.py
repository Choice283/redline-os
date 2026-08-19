"""Tests for redline_core.restore.recovery_disposition (Mission 1B-A2-3):
move-aside disposition of an existing live object.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from redline_core.restore.exceptions import RecoveryDispositionFailedError
from redline_core.restore.recovery_disposition import DISPOSITION_ORDER, dispose_target, superseded_disposition_path


def test_disposition_order_is_fixed_and_exact():
    assert DISPOSITION_ORDER == ("database", "config", "-journal", "-wal", "-shm")


# -- superseded_disposition_path() ---------------------------------------------------


def test_superseded_disposition_path_is_restore_id_scoped(tmp_path: Path):
    source = tmp_path / "redline.db"
    source.write_bytes(b"x")
    destination = superseded_disposition_path(source, restore_id="r1-20260819T000000Z-abcdef012345")
    assert destination.name == "redline.db__superseded-r1-20260819T000000Z-abcdef012345"
    assert destination.parent == source.parent


def test_superseded_disposition_path_collision_raises(tmp_path: Path):
    source = tmp_path / "redline.db"
    source.write_bytes(b"x")
    destination = tmp_path / "redline.db__superseded-rid"
    destination.write_bytes(b"already here")
    with pytest.raises(RecoveryDispositionFailedError):
        superseded_disposition_path(source, restore_id="rid")


# -- dispose_target(): wrong-type directory (mirrors the Prep DB-directory proof) ----


def test_dispose_target_moves_wrong_type_directory_aside(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()
    (db_path / "nested.txt").write_text("preserved")

    result = dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid1")

    assert not db_path.exists()
    assert result.superseded_path.is_dir()
    assert (result.superseded_path / "nested.txt").read_text() == "preserved"


def test_dispose_target_frees_source_path_for_reuse(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()
    dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid1")
    db_path.write_bytes(b"a fresh regular file can now be created here")
    assert db_path.is_file()


# -- dispose_target(): evidence-preservation regular file ----------------------------


def test_dispose_target_moves_regular_file_aside(tmp_path: Path):
    config_path = tmp_path / "config"
    config_path.write_bytes(b"a regular file where a directory belongs")

    result = dispose_target(config_path, target_kind="config", expected_regular=True, restore_id="rid2")

    assert not config_path.exists()
    assert result.superseded_path.read_bytes() == b"a regular file where a directory belongs"


# -- collision semantics ---------------------------------------------------------------


def test_dispose_target_destination_collision_refuses_overwrite(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()
    destination = tmp_path / "redline.db__superseded-rid3"
    destination.write_bytes(b"pre-existing")

    with pytest.raises(RecoveryDispositionFailedError):
        dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid3")

    # neither source nor destination was touched
    assert db_path.is_dir()
    assert destination.read_bytes() == b"pre-existing"


# -- re-derived type mismatch: never trusts an earlier classification alone ---------


def test_dispose_target_refuses_when_re_derived_type_no_longer_matches(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"actually a regular file now")

    with pytest.raises(RecoveryDispositionFailedError):
        dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid4")

    assert db_path.is_file()  # untouched


# -- unsafe-object gate -----------------------------------------------------------------


def test_dispose_target_refuses_unsafe_object(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"pretend-unsafe")
    monkeypatch.setattr("redline_core.restore.recovery_disposition.fsutil.is_unsafe_link", lambda st: True)

    with pytest.raises(RecoveryDispositionFailedError, match="symlink, junction"):
        dispose_target(db_path, target_kind="database", expected_regular=True, restore_id="rid5")

    assert db_path.is_file()  # never moved


# -- same-volume gate ---------------------------------------------------------------------


def test_dispose_target_refuses_cross_volume(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()
    monkeypatch.setattr("redline_core.restore.recovery_disposition.same_volume", lambda a, b: False)

    with pytest.raises(RecoveryDispositionFailedError, match="same volume"):
        dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid6")

    assert db_path.is_dir()


# -- missing source -------------------------------------------------------------------------


def test_dispose_target_missing_source_raises(tmp_path: Path):
    db_path = tmp_path / "does-not-exist"
    with pytest.raises(RecoveryDispositionFailedError):
        dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid7")


# -- open-handle / rename failure -----------------------------------------------------------


def test_dispose_target_rename_failure_leaves_filesystem_untouched(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()

    def _boom(src, dst):
        raise PermissionError("simulated open-handle failure")

    monkeypatch.setattr("redline_core.restore.recovery_disposition.os.rename", _boom)

    with pytest.raises(RecoveryDispositionFailedError, match="disposition move-aside failed"):
        dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid8")

    assert db_path.is_dir()
    assert not (tmp_path / "redline.db__superseded-rid8").exists()


# -- post-move verification -----------------------------------------------------------------


def test_dispose_target_post_move_verification_detects_source_still_present(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "redline.db"
    db_path.mkdir()

    real_rename = os.rename

    def _fake_rename(src, dst):
        real_rename(src, dst)
        # simulate the source reappearing immediately after a "successful" rename
        os.mkdir(src)

    monkeypatch.setattr("redline_core.restore.recovery_disposition.os.rename", _fake_rename)

    with pytest.raises(RecoveryDispositionFailedError, match="post-move verification failed"):
        dispose_target(db_path, target_kind="database", expected_regular=False, restore_id="rid9")
