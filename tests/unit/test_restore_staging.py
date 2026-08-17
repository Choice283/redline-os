"""Tests for Mission 1B-A1 same-volume staging and live replacement
(redline_core.restore.staging).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from redline_core.restore.exceptions import (
    RestoreConfigReplacementFailedError,
    RestoreDatabaseReplacementFailedError,
    RestorePathCollisionError,
    RestoreStagingFailedError,
)
from redline_core.restore.staging import (
    STAGING_DIRNAME,
    install_staged_config,
    rename_config_aside,
    replace_database,
    same_volume,
    stage_config,
    stage_database,
    superseded_config_path,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_stage_database_is_same_volume_as_live_db_parent(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    live_db_path = runtime_dir / "redline.db"

    target_db_path = tmp_path / "some_other_volume_dir" / "redline.db"
    target_db_path.parent.mkdir()
    payload = b"database payload bytes"
    target_db_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    staged = stage_database(
        target_db_path=target_db_path,
        db_manifest_entry={"sha256": digest, "size_bytes": len(payload)},
        live_db_path=live_db_path,
        restore_id="r1-test",
    )

    assert staged.parent.parent.parent.parent == runtime_dir  # <runtime>/.redline_restore_staging/r1-test/db/
    assert same_volume(staged, runtime_dir)
    assert _sha256(staged) == digest
    assert not live_db_path.exists()  # staging never touches the live path


def test_stage_database_rejects_hash_mismatch_against_manifest(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    target_db_path = tmp_path / "target" / "redline.db"
    target_db_path.parent.mkdir()
    target_db_path.write_bytes(b"actual bytes")

    with pytest.raises(RestoreStagingFailedError):
        stage_database(
            target_db_path=target_db_path,
            db_manifest_entry={"sha256": "0" * 64, "size_bytes": 999},
            live_db_path=runtime_dir / "redline.db",
            restore_id="r1-test",
        )


def test_stage_database_fails_closed_on_staging_collision(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    target_db_path = tmp_path / "target" / "redline.db"
    target_db_path.parent.mkdir()
    payload = b"db"
    target_db_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    (runtime_dir / STAGING_DIRNAME / "r1-dup" / "db").mkdir(parents=True)

    with pytest.raises(RestorePathCollisionError):
        stage_database(
            target_db_path=target_db_path,
            db_manifest_entry={"sha256": digest, "size_bytes": len(payload)},
            live_db_path=runtime_dir / "redline.db",
            restore_id="r1-dup",
        )


def test_stage_config_copies_and_verifies_every_manifested_file(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    target_config_dir = tmp_path / "target_config"
    target_config_dir.mkdir()
    entries = []
    for filename, content in [("a.yaml", b"aaa"), ("b.yaml", b"bbbbb")]:
        (target_config_dir / filename).write_bytes(content)
        entries.append(
            {"relative_path": f"payload/config/{filename}", "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
        )

    staged_dir = stage_config(
        target_config_dir=target_config_dir,
        config_manifest_entries=entries,
        live_config_dir=config_dir,
        restore_id="r1-test",
    )

    assert (staged_dir / "a.yaml").read_bytes() == b"aaa"
    assert (staged_dir / "b.yaml").read_bytes() == b"bbbbb"
    assert same_volume(staged_dir, config_dir.parent)
    assert not (config_dir / "a.yaml").exists()  # live config untouched


def test_stage_config_fails_closed_on_staging_collision(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir.parent / STAGING_DIRNAME / "r1-dup" / "config").mkdir(parents=True)

    with pytest.raises(RestorePathCollisionError):
        stage_config(
            target_config_dir=tmp_path / "nonexistent",
            config_manifest_entries=[],
            live_config_dir=config_dir,
            restore_id="r1-dup",
        )


def test_superseded_config_path_is_restore_id_scoped_not_fixed(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    path_a = superseded_config_path(config_dir, "r1-aaaa")
    path_b = superseded_config_path(config_dir, "r1-bbbb")

    assert path_a != path_b
    assert "r1-aaaa" in path_a.name
    assert "r1-bbbb" in path_b.name
    assert path_a.parent == config_dir.parent


def test_superseded_config_path_fails_closed_on_collision(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    colliding = config_dir.parent / f"{config_dir.name}__superseded-r1-dup"
    colliding.mkdir()

    with pytest.raises(RestorePathCollisionError):
        superseded_config_path(config_dir, "r1-dup")


# -- replacement semantics -----------------------------------------------------------


def test_replace_database_is_a_single_os_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staged = tmp_path / "staged.db"
    staged.write_bytes(b"new content")
    live = tmp_path / "live.db"
    live.write_bytes(b"old content")

    calls = []
    real_replace = os.replace

    def _tracking_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _tracking_replace)
    replace_database(staged, live)

    assert calls == [(str(staged), str(live))]
    assert live.read_bytes() == b"new content"
    assert not staged.exists()


def test_replace_database_failure_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staged = tmp_path / "staged.db"
    staged.write_bytes(b"x")
    live = tmp_path / "live.db"

    def _boom(src, dst):
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(RestoreDatabaseReplacementFailedError):
        replace_database(staged, live)


def test_config_replacement_is_two_non_atomic_steps(tmp_path: Path):
    live_config = tmp_path / "config"
    live_config.mkdir()
    (live_config / "old.yaml").write_bytes(b"old")

    staged_config = tmp_path / "staged_config"
    staged_config.mkdir()
    (staged_config / "new.yaml").write_bytes(b"new")

    superseded = superseded_config_path(live_config, "r1-test")

    rename_config_aside(live_config, superseded)
    assert not live_config.exists()
    assert (superseded / "old.yaml").read_bytes() == b"old"

    install_staged_config(staged_config, live_config, superseded_path=superseded)
    assert (live_config / "new.yaml").read_bytes() == b"new"
    assert not staged_config.exists()
    assert (superseded / "old.yaml").read_bytes() == b"old"  # superseded config preserved, untouched


def test_install_staged_config_failure_preserves_both_superseded_and_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If the second rename fails, the live config directory is genuinely
    missing -- both the superseded copy and the still-present staging
    directory must survive untouched (no automatic recovery)."""
    live_config = tmp_path / "config"
    live_config.mkdir()
    (live_config / "old.yaml").write_bytes(b"old")

    staged_config = tmp_path / "staged_config"
    staged_config.mkdir()
    (staged_config / "new.yaml").write_bytes(b"new")

    superseded = superseded_config_path(live_config, "r1-test")
    rename_config_aside(live_config, superseded)

    def _boom(src, dst):
        raise OSError("simulated failure installing staged config")

    monkeypatch.setattr(os, "rename", _boom)
    with pytest.raises(RestoreConfigReplacementFailedError):
        install_staged_config(staged_config, live_config, superseded_path=superseded)

    assert not live_config.exists()
    assert (superseded / "old.yaml").read_bytes() == b"old"
    assert (staged_config / "new.yaml").read_bytes() == b"new"


def test_rename_config_aside_failure_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    live_config = tmp_path / "config"
    live_config.mkdir()
    superseded = superseded_config_path(live_config, "r1-test")

    def _boom(src, dst):
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "rename", _boom)
    with pytest.raises(RestoreConfigReplacementFailedError):
        rename_config_aside(live_config, superseded)
    assert live_config.exists()  # untouched on failure
