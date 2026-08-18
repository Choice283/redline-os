"""Tests for redline_core.restore.capture_manager.build_degraded_source_capture()
(Mission 1B-A2-2): the top-level orchestrator. Proves namespace/identity
isolation from Mission 1A, whole-system capture, package success/failure
semantics, immutability, path safety, and the read-only live-source
guarantee. Reuses tests/unit/_restore_test_helpers.py's Environment.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from redline_core.backup.exceptions import BackupError
from redline_core.restore import capture_manager, capture_package, capture_paths
from redline_core.restore.capture_exceptions import (
    CaptureConfigurationError,
    CaptureDestinationUnsafeError,
    CapturePackageCollisionError,
)
from redline_core.restore.capture_manager import build_degraded_source_capture
from redline_core.restore.capture_models import CaptureItemOutcome
from redline_core.restore.capture_paths import validate_capture_id
from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.recovery_classification import classify_config_source, classify_database_source

from tests.unit._restore_test_helpers import make_environment


def _classify(env):
    return classify_database_source(env.db_path), classify_config_source(env.config_dir)


def _capture(env, *, reason=None):
    db_assess, cfg_assess = _classify(env)
    return build_degraded_source_capture(
        db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
        database_assessment=db_assess, config_assessment=cfg_assess, reason=reason,
    )


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- namespace / identity --------------------------------------------------------------


def test_capture_id_matches_dsc1_schema(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")

    result = _capture(env)

    assert validate_capture_id(result.capture_id) == result.capture_id
    assert result.capture_id.startswith("dsc1-")


def test_capture_id_cannot_collide_with_b1_namespace():
    from redline_core.backup.paths import validate_backup_id

    with pytest.raises(ValueError):
        validate_backup_id("dsc1-20260817T120000Z-000000000000")
    with pytest.raises(ValueError):
        validate_capture_id("b1-20260817T120000Z-000000000000")


def test_capture_never_appears_in_backup_list(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")

    before = env.backup_manager.list_backups()
    _capture(env)
    after = env.backup_manager.list_backups()

    assert before == after == []


def test_capture_cannot_pass_mission_1a_backup_verification(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")
    result = _capture(env)

    with pytest.raises((ValueError, BackupError)):
        env.backup_manager.verify_backup(result.capture_id)


def test_capture_cannot_be_restore_target(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")
    result = _capture(env)

    with pytest.raises(ValueError):
        env.restore_manager.restore_plan(result.capture_id)
    with pytest.raises(ValueError):
        env.restore_manager.restore(
            result.capture_id, confirm_backup_id=result.capture_id,
            attestations=QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True),
        )


def test_capture_directory_structurally_distinct_from_backup_directory(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")
    result = _capture(env)

    assert result.capture_path.parent.name == "degraded_source_captures"
    assert result.capture_path.parent != env.backup_root / "system_backups"
    assert not (env.backup_root / "system_backups" / result.capture_id).exists()


# -- whole-system capture ---------------------------------------------------------------


@pytest.mark.parametrize(
    "degrade_db,degrade_config,missing_db,missing_config",
    [
        (True, False, False, False),   # degraded DB + healthy config
        (False, True, False, False),   # healthy DB + degraded config
        (False, False, True, False),   # missing DB + healthy config
        (False, False, False, True),   # healthy DB + missing config
        (True, True, False, False),    # both degraded
        (False, False, True, True),    # both missing
    ],
)
def test_whole_system_capture_accounts_for_both_sides(tmp_path: Path, degrade_db, degrade_config, missing_db, missing_config):
    env = make_environment(tmp_path)

    if missing_db:
        env.db_path.unlink()
    elif degrade_db:
        env.db_path.write_bytes(b"corrupted")

    if missing_config:
        shutil.rmtree(env.config_dir)
    elif degrade_config:
        (env.config_dir / "paths.yaml").unlink()

    result = _capture(env)

    # The database slot is always present in the manifest, regardless of
    # which side triggered the capture.
    assert result.database is not None
    if missing_db:
        assert result.database.outcome is CaptureItemOutcome.MISSING
    else:
        assert result.database.outcome is CaptureItemOutcome.CAPTURED_VERIFIED

    # All six config file slots are always present.
    assert len(result.config_files) == 6
    if missing_config:
        assert result.config_directory is not None
        assert result.config_directory.outcome is CaptureItemOutcome.MISSING
        assert all(r.outcome is CaptureItemOutcome.MISSING for r in result.config_files)
    elif degrade_config:
        assert result.config_directory is None
        missing_file = [r for r in result.config_files if r.item_key == "config:paths.yaml"][0]
        assert missing_file.outcome is CaptureItemOutcome.MISSING
        others = [r for r in result.config_files if r.item_key != "config:paths.yaml"]
        assert all(r.outcome is CaptureItemOutcome.CAPTURED_VERIFIED for r in others)
    else:
        assert result.config_directory is None
        assert all(r.outcome is CaptureItemOutcome.CAPTURED_VERIFIED for r in result.config_files)


def test_healthy_side_still_captured_as_evidence_not_skipped(tmp_path: Path):
    """A healthy surviving component inside a degraded-run capture is
    still capture evidence, never a separate 'partial Mission 1A backup'."""
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")  # only DB is degraded; config is fully healthy

    result = _capture(env)

    assert all(r.outcome is CaptureItemOutcome.CAPTURED_VERIFIED for r in result.config_files)
    assert all(r.captured_relative_path is not None for r in result.config_files)


# -- package success vs. per-item unreadability -----------------------------------------


def test_package_succeeds_even_when_every_item_is_unreadable_or_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    env.db_path.unlink()
    shutil.rmtree(env.config_dir)

    result = _capture(env)  # must not raise

    assert result.database.outcome is CaptureItemOutcome.MISSING
    assert all(r.outcome is CaptureItemOutcome.MISSING for r in result.config_files)
    assert (result.capture_path / "CAPTURE_COMPLETE").exists()


# -- capture system failure: hard stop, no override ---------------------------------------


def test_capture_system_failure_unconfigured_destination(tmp_path: Path):
    env = make_environment(tmp_path, configure_backup_path=False)

    db_assess, cfg_assess = _classify(env)
    with pytest.raises(CaptureConfigurationError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=None,
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


def test_capture_system_failure_unsafe_destination_overlapping_config(tmp_path: Path):
    env = make_environment(tmp_path)
    db_assess, cfg_assess = _classify(env)

    with pytest.raises(CaptureDestinationUnsafeError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.config_dir),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


def test_capture_system_failure_leaves_no_usable_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    db_assess, cfg_assess = _classify(env)

    def _boom(*args, **kwargs):
        raise OSError("simulated disk exhaustion")

    monkeypatch.setattr(capture_manager, "publish_staged_capture", _boom)

    from redline_core.restore.capture_exceptions import CaptureSystemWriteFailedError

    with pytest.raises(CaptureSystemWriteFailedError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )
    # No sealed package exists under the published capture namespace.
    published = env.backup_root / "degraded_source_captures"
    assert not published.exists() or list(published.iterdir()) == []


# -- immutability ------------------------------------------------------------------------


def test_prior_sealed_capture_byte_identical_after_later_attempt(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted-v1")
    result1 = _capture(env)
    manifest1_bytes = (result1.capture_path / "capture_manifest.json").read_bytes()
    db_bytes1 = (result1.capture_path / "payload" / "database" / env.db_path.name).read_bytes()

    env.db_path.write_bytes(b"corrupted-v2-different-content")
    result2 = _capture(env)

    assert result1.capture_id != result2.capture_id
    assert (result1.capture_path / "capture_manifest.json").read_bytes() == manifest1_bytes
    assert (result1.capture_path / "payload" / "database" / env.db_path.name).read_bytes() == db_bytes1


def test_cannot_overwrite_sealed_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    fixed_id = "dsc1-20260817T120000Z-bbbbbbbbbbbb"
    monkeypatch.setattr(capture_package, "build_capture_id", lambda moment: fixed_id)

    result1 = _capture(env)
    assert result1.capture_id == fixed_id

    from redline_core.restore.capture_exceptions import CapturePackageCollisionError

    with pytest.raises(CapturePackageCollisionError):
        _capture(env)


# -- path safety -------------------------------------------------------------------------


def test_capture_destination_cannot_alias_live_db_parent(tmp_path: Path):
    env = make_environment(tmp_path)
    db_assess, cfg_assess = _classify(env)

    with pytest.raises(CaptureDestinationUnsafeError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.db_path.parent),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


# -- capture destination safety (Mission 1B-A2-2 safety correction, Correction 3) -------


def test_capture_root_pre_existing_unsafe_link_hard_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The configured capture root itself (paths.backup_path) is now
    lstat-safety-checked before any staging write -- an unsafe object
    there is a hard package failure, never silently accepted the way
    Path.mkdir(..., exist_ok=True)'s own is_dir() check (which follows
    symlinks) would accept it."""
    env = make_environment(tmp_path)
    env.backup_root.mkdir(parents=True, exist_ok=True)
    root_ino_dev = (env.backup_root.stat().st_ino, env.backup_root.stat().st_dev)
    real_is_unsafe = capture_paths.fsutil.is_unsafe_link

    def _fake(st):
        if (getattr(st, "st_ino", None), getattr(st, "st_dev", None)) == root_ino_dev:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(capture_paths.fsutil, "is_unsafe_link", _fake)

    db_assess, cfg_assess = _classify(env)
    with pytest.raises(CaptureDestinationUnsafeError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


def test_staging_capture_root_pre_existing_unsafe_link_hard_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``.staging_capture`` (the shared staging parent) is safety-checked
    the same way as the capture root itself."""
    env = make_environment(tmp_path)
    staging_parent = env.backup_root / capture_manager.STAGING_DIRNAME
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging_ino_dev = (staging_parent.stat().st_ino, staging_parent.stat().st_dev)
    real_is_unsafe = capture_paths.fsutil.is_unsafe_link

    def _fake(st):
        if (getattr(st, "st_ino", None), getattr(st, "st_dev", None)) == staging_ino_dev:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(capture_paths.fsutil, "is_unsafe_link", _fake)

    db_assess, cfg_assess = _classify(env)
    with pytest.raises(CaptureDestinationUnsafeError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


def test_degraded_source_captures_root_pre_existing_unsafe_link_hard_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``degraded_source_captures/`` (the final-publish parent) is
    safety-checked the same way, at publish time."""
    env = make_environment(tmp_path)
    final_parent = env.backup_root / capture_package.DEGRADED_SOURCE_CAPTURES_DIRNAME
    final_parent.mkdir(parents=True, exist_ok=True)
    final_parent_ino_dev = (final_parent.stat().st_ino, final_parent.stat().st_dev)
    real_is_unsafe = capture_paths.fsutil.is_unsafe_link

    def _fake(st):
        if (getattr(st, "st_ino", None), getattr(st, "st_dev", None)) == final_parent_ino_dev:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(capture_paths.fsutil, "is_unsafe_link", _fake)

    db_assess, cfg_assess = _classify(env)
    with pytest.raises(CaptureDestinationUnsafeError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


def test_degraded_source_captures_root_wrong_type_hard_fails(tmp_path: Path):
    """A plain file sitting where ``degraded_source_captures/`` should be
    a directory is rejected before publish, never silently written
    through."""
    env = make_environment(tmp_path)
    env.backup_root.mkdir(parents=True, exist_ok=True)
    (env.backup_root / capture_package.DEGRADED_SOURCE_CAPTURES_DIRNAME).write_bytes(b"not a directory")

    db_assess, cfg_assess = _classify(env)
    with pytest.raises(CaptureDestinationUnsafeError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )


def test_final_capture_path_dangling_unsafe_object_refuses_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A dangling/unsafe reparse object at the exact final capture-ID path
    is invisible to Path.exists() (it follows symlinks and returns False
    for a broken target) but must still be caught -- lstat() succeeds for
    such an object without ever following it. Simulated here without a
    real privileged symlink: os.lstat() is faked to report *something*
    already occupying the final path, exactly as it would for a genuine
    dangling reparse point, while nothing is actually created on disk
    there -- proving the collision check does not depend on Path.exists()."""
    env = make_environment(tmp_path)
    fixed_id = "dsc1-20260817T120000Z-cccccccccccc"
    monkeypatch.setattr(capture_package, "build_capture_id", lambda moment: fixed_id)

    real_lstat = capture_package.os.lstat
    final_dir = env.backup_root / capture_package.DEGRADED_SOURCE_CAPTURES_DIRNAME / fixed_id

    def _fake_lstat(path, *a, **kw):
        if Path(path) == final_dir:
            return real_lstat(env.backup_root)  # stands in for "something already occupies this name"
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(capture_package.os, "lstat", _fake_lstat)

    db_assess, cfg_assess = _classify(env)
    with pytest.raises(CapturePackageCollisionError):
        build_degraded_source_capture(
            db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
            database_assessment=db_assess, config_assessment=cfg_assess,
        )
    assert not final_dir.exists()  # Path.exists() would report "nothing here" -- exactly the blind spot closed


# -- read-only live-source proof ----------------------------------------------------------


def test_capture_never_mutates_live_source(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")
    Path(str(env.db_path) + "-wal").write_bytes(b"sidecar-content")

    db_hash_before = _sha256_bytes(env.db_path)
    wal_hash_before = _sha256_bytes(Path(str(env.db_path) + "-wal"))
    config_hashes_before = {p.name: p.read_bytes() for p in env.config_dir.iterdir()}
    config_inventory_before = sorted(p.name for p in env.config_dir.iterdir())

    _capture(env)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert _sha256_bytes(Path(str(env.db_path) + "-wal")) == wal_hash_before
    assert {p.name: p.read_bytes() for p in env.config_dir.iterdir()} == config_hashes_before
    assert sorted(p.name for p in env.config_dir.iterdir()) == config_inventory_before
    assert env.db_path.exists()  # never renamed/deleted


def test_capture_creates_no_restore_staging_or_journal(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")

    _capture(env)

    assert not (env.backup_root / "restore_journal").exists()
    from redline_core.restore.staging import STAGING_DIRNAME as RESTORE_STAGING_DIRNAME

    assert not (env.db_path.parent / RESTORE_STAGING_DIRNAME).exists()


def test_capture_creates_no_sqlite_sidecars_for_the_live_db(tmp_path: Path):
    env = make_environment(tmp_path)
    env.db_path.write_bytes(b"corrupted")

    _capture(env)

    for suffix in ("-journal", "-wal", "-shm"):
        assert not Path(str(env.db_path) + suffix).exists()


def test_unsafe_object_not_followed_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    db_ino_dev = (env.db_path.stat().st_ino, env.db_path.stat().st_dev)
    real_is_unsafe = capture_package.fsutil.is_unsafe_link

    # Mission 1B-A2-2 safety correction (Correction 3) note: fsutil is a
    # single shared module, so a blanket `lambda st: True` patch here would
    # also make the new capture-destination safety checks (which reuse the
    # identical fsutil.is_unsafe_link()) see the legitimate backup root
    # itself as unsafe, which is not what this test is proving. Scope the
    # fake to the live database file's own identity only, exactly like
    # test_capture_config_slot_unsafe_link_file_never_followed already does
    # in tests/unit/test_capture_package.py.
    def _fake(st):
        if (getattr(st, "st_ino", None), getattr(st, "st_dev", None)) == db_ino_dev:
            return True
        return real_is_unsafe(st)

    monkeypatch.setattr(capture_package.fsutil, "is_unsafe_link", _fake)

    db_assess, cfg_assess = _classify(env)
    result = build_degraded_source_capture(
        db_path=env.db_path, config_dir=env.config_dir, backup_path=str(env.backup_root),
        database_assessment=db_assess, config_assessment=cfg_assess,
    )

    assert result.database.outcome is CaptureItemOutcome.UNSAFE_OBJECT_RECORDED
    assert result.database.captured_relative_path is None
    assert not (result.capture_path / "payload" / "database").exists()
