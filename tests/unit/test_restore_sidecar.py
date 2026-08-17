"""Tests for the Mission 1B-A1 SQLite sidecar gate
(redline_core.restore.sidecar): -journal/-wal/-shm presence always fails
closed, is never deleted/renamed, and a sealed backup payload cannot smuggle
one in (Mission 1A's own exact-payload-contents check already guarantees
this; this file proves it end-to-end from Restore's point of view).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from redline_core.backup.exceptions import BackupVerificationFailedError
from redline_core.restore.exceptions import RestoreSidecarPresentError
from redline_core.restore.sidecar import find_present_sidecars, require_no_sidecars

from tests.unit._restore_test_helpers import make_environment


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_require_no_sidecars_fails_closed_on_each_suffix(tmp_path: Path, suffix: str):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"not a real db, presence is all that matters")
    sidecar_path = Path(str(db_path) + suffix)
    sidecar_path.write_bytes(b"")

    with pytest.raises(RestoreSidecarPresentError):
        require_no_sidecars(db_path, when="test")

    assert sidecar_path.exists(), "sidecar must never be deleted by the gate check"


def test_require_no_sidecars_passes_when_none_present(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"db")
    require_no_sidecars(db_path, when="test")  # must not raise


def test_find_present_sidecars_never_deletes_anything(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    db_path.write_bytes(b"db")
    for suffix in ("-journal", "-wal", "-shm"):
        (Path(str(db_path) + suffix)).write_bytes(b"x")

    found = find_present_sidecars(db_path)
    assert len(found) == 3
    for suffix in ("-journal", "-wal", "-shm"):
        assert Path(str(db_path) + suffix).exists()


def test_sealed_backup_package_cannot_smuggle_a_sidecar(tmp_path: Path):
    """Mission 1A's own exact-payload-contents check
    (_require_exact_payload_contents) already rejects any file beyond the
    manifested single database file under payload/database/ -- planting a
    sidecar there must make the *backup itself* fail verification, not
    silently pass through to Restore."""
    env = make_environment(tmp_path)
    result = env.backup_manager.create_backup(reason="sidecar smuggling test")

    payload_db_dir = result.backup_path / "payload" / "database"
    (payload_db_dir / "redline.db-wal").write_bytes(b"smuggled")

    with pytest.raises(BackupVerificationFailedError):
        env.backup_manager.verify_backup(result.backup_id)
