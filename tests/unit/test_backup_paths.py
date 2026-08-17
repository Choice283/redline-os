"""Tests for redline_core.backup.paths: backup_id validation, structural
path-containment safety, and unsafe-filesystem-object rejection. Pure path
logic and synthetic stat results -- no real database, no Resolve, no real
symlink/junction creation (which can require elevated privileges on
Windows); unsafe-object rejection is exercised by monkeypatching
`redline_core.fsutil.is_unsafe_link()`, the same test-friendly indirection
`redline_core.archive.integrity` itself already relies on being patchable.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core import fsutil
from redline_core.backup.exceptions import BackupPathContainmentError, BackupSourceUnavailableError, BackupUnsafeFilesystemObjectError
from redline_core.backup.paths import (
    build_backup_id,
    format_utc_iso,
    require_safe_directory,
    require_safe_regular_file,
    validate_backup_id,
    validate_backup_root_containment,
)

_FIXED_MOMENT = datetime(2026, 8, 16, 19, 30, 0, tzinfo=timezone.utc)


# -- backup_id -----------------------------------------------------------------


def test_build_backup_id_shape():
    backup_id = build_backup_id(_FIXED_MOMENT, "79c948abf73d0000000000000000000000000000000000000000000000000")
    assert backup_id == "b1-20260816T193000Z-79c948abf73d"


def test_validate_backup_id_accepts_well_formed_id():
    assert validate_backup_id("b1-20260816T193000Z-79c948abf73d") == "b1-20260816T193000Z-79c948abf73d"


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "not-a-backup-id",
        "b1-20260816T193000Z-79C948ABF73D",  # uppercase hex rejected
        "b1-2026-08-16T19:30:00Z-79c948abf73d",  # wrong timestamp shape
        "a1-20260816T193000Z-79c948abf73d",  # wrong schema tag
        "b1-20260816T193000Z-79c948abf73",  # 11 hex chars, not 12
        "../../etc/passwd",
        "b1-20260816T193000Z-79c948abf73d/../escape",
    ],
)
def test_validate_backup_id_rejects_malformed_input(candidate):
    with pytest.raises(ValueError):
        validate_backup_id(candidate)


def test_format_utc_iso_normalizes_naive_datetime_to_utc():
    naive = datetime(2026, 8, 16, 19, 30, 0)
    assert format_utc_iso(naive) == "2026-08-16T19:30:00Z"


# -- containment ----------------------------------------------------------------


def test_containment_accepts_sibling_directories(tmp_path: Path):
    db_path = tmp_path / "runtime" / "redline.db"
    config_dir = tmp_path / "config"
    backup_root = tmp_path / "backups"
    resolved = validate_backup_root_containment(backup_root=backup_root, db_path=db_path, config_dir=config_dir)
    assert resolved == backup_root.resolve()


def test_containment_rejects_backup_root_equal_to_db_path(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    with pytest.raises(BackupPathContainmentError):
        validate_backup_root_containment(backup_root=db_path, db_path=db_path, config_dir=tmp_path / "config")


def test_containment_rejects_backup_root_inside_config_dir(tmp_path: Path):
    config_dir = tmp_path / "config"
    backup_root = config_dir / "backups"
    with pytest.raises(BackupPathContainmentError):
        validate_backup_root_containment(backup_root=backup_root, db_path=tmp_path / "runtime" / "redline.db", config_dir=config_dir)


def test_containment_rejects_config_dir_inside_backup_root(tmp_path: Path):
    backup_root = tmp_path / "backups"
    config_dir = backup_root / "config"
    with pytest.raises(BackupPathContainmentError):
        validate_backup_root_containment(backup_root=backup_root, db_path=tmp_path / "runtime" / "redline.db", config_dir=config_dir)


def test_containment_rejects_backup_root_inside_db_directory(tmp_path: Path):
    db_dir = tmp_path / "runtime"
    db_path = db_dir / "redline.db"
    backup_root = db_dir / "backups"
    with pytest.raises(BackupPathContainmentError):
        validate_backup_root_containment(backup_root=backup_root, db_path=db_path, config_dir=tmp_path / "config")


def test_containment_rejects_db_directory_inside_backup_root(tmp_path: Path):
    backup_root = tmp_path / "backups"
    db_path = backup_root / "runtime" / "redline.db"
    with pytest.raises(BackupPathContainmentError):
        validate_backup_root_containment(backup_root=backup_root, db_path=db_path, config_dir=tmp_path / "config")


# -- unsafe filesystem objects ----------------------------------------------------


def test_require_safe_regular_file_accepts_real_file(tmp_path: Path):
    target = tmp_path / "naming.yaml"
    target.write_text("episode_id_pattern: RLC-E{episode_number:03d}\n", encoding="utf-8")
    require_safe_regular_file(target, description="test file")  # must not raise


def test_require_safe_regular_file_rejects_missing_file(tmp_path: Path):
    with pytest.raises(BackupSourceUnavailableError):
        require_safe_regular_file(tmp_path / "does_not_exist.yaml", description="test file")


def test_require_safe_regular_file_rejects_directory(tmp_path: Path):
    directory = tmp_path / "a_directory"
    directory.mkdir()
    with pytest.raises(BackupUnsafeFilesystemObjectError):
        require_safe_regular_file(directory, description="test file")


def test_require_safe_regular_file_rejects_reported_unsafe_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "naming.yaml"
    target.write_text("x: 1\n", encoding="utf-8")
    monkeypatch.setattr(fsutil, "is_unsafe_link", lambda st: True)
    with pytest.raises(BackupUnsafeFilesystemObjectError):
        require_safe_regular_file(target, description="test file")


def test_require_safe_directory_accepts_real_directory(tmp_path: Path):
    directory = tmp_path / "a_directory"
    directory.mkdir()
    require_safe_directory(directory, description="test dir", must_exist=True)  # must not raise


def test_require_safe_directory_missing_and_not_required_is_ok(tmp_path: Path):
    require_safe_directory(tmp_path / "not_yet_created", description="test dir", must_exist=False)  # must not raise


def test_require_safe_directory_missing_and_required_raises(tmp_path: Path):
    with pytest.raises(BackupUnsafeFilesystemObjectError):
        require_safe_directory(tmp_path / "not_yet_created", description="test dir", must_exist=True)


def test_require_safe_directory_rejects_reported_unsafe_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    directory = tmp_path / "a_directory"
    directory.mkdir()
    monkeypatch.setattr(fsutil, "is_unsafe_link", lambda st: True)
    with pytest.raises(BackupUnsafeFilesystemObjectError):
        require_safe_directory(directory, description="test dir", must_exist=True)


def test_require_safe_directory_rejects_a_file(tmp_path: Path):
    target = tmp_path / "a_file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(BackupUnsafeFilesystemObjectError):
        require_safe_directory(target, description="test dir", must_exist=True)
