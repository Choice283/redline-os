"""Tests for RestoreManager (Mission 1B-A1: HEALTHY_SOURCE Restore)
end-to-end orchestration, against real, temporary SQLite databases and real
six-file config directories -- no mocking of SQLite itself, mirroring
tests/unit/test_backup_manager.py's own established convention. No Resolve
involved anywhere in this file.
"""
from __future__ import annotations

import ast
import hashlib
import sqlite3
from pathlib import Path

import pytest

from redline_core.backup.exceptions import BackupError
from redline_core.config.loader import REQUIRED_FILES
from redline_core.db.database import Database
from redline_core.restore.exceptions import (
    RestoreAttestationMissingError,
    RestoreConfirmationError,
    RestorePreRestoreSnapshotFailedError,
    RestoreQuiescenceFailedError,
    RestoreSchemaIncompatibleError,
    RestoreSidecarPresentError,
    RestoreTargetUnavailableError,
    RestoreVerificationFailedError,
)
from redline_core.restore.journal import discover_journal_chain
from redline_core.restore.models import QuiescenceAttestations

from tests.unit._restore_test_helpers import make_environment, make_target_backup

_ALL_TRUE = QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True)


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_hashes(config_dir: Path) -> dict[str, str]:
    return {filename: _sha256_bytes(config_dir / filename) for filename in REQUIRED_FILES.values()}


def _query_episode_ids(db_path: Path) -> list[str]:
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT episode_id FROM episodes ORDER BY episode_id").fetchall()]
    finally:
        conn.close()


# -- restore_plan(): read-only ------------------------------------------------------


def test_restore_plan_reports_would_proceed_for_a_healthy_target(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    plan = env.restore_manager.restore_plan(target_id)

    assert plan.target_verified is True
    assert plan.schema_compatible is True
    assert plan.quiescence_probe_passed is True
    assert plan.sidecar_check_passed is True
    assert plan.blocking_issues == ()
    assert plan.would_proceed is True


def test_restore_plan_never_mutates_anything(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    db_hash_before = _sha256_bytes(env.db_path)
    config_hashes_before = _config_hashes(env.config_dir)
    backups_before = set((env.backup_root / "system_backups").iterdir())

    env.restore_manager.restore_plan(target_id)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert _config_hashes(env.config_dir) == config_hashes_before
    assert set((env.backup_root / "system_backups").iterdir()) == backups_before


def test_restore_plan_reports_missing_backup_id(tmp_path: Path):
    env = make_environment(tmp_path)
    make_target_backup(tmp_path, env)  # ensure backup_path exists at all

    plan = env.restore_manager.restore_plan("b1-20260817T000000Z-000000000000")

    assert plan.target_verified is False
    assert plan.would_proceed is False
    assert any("verification failed" in issue for issue in plan.blocking_issues)


def test_restore_plan_reports_schema_incompatible_target(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(
        tmp_path,
        env,
        db_statements=["CREATE TABLE wrong_shape (id INTEGER PRIMARY KEY)"],
        unique_dir="bad_schema_source",
    )

    plan = env.restore_manager.restore_plan(target_id)

    assert plan.target_verified is True
    assert plan.schema_compatible is False
    assert plan.would_proceed is False


def test_restore_plan_reports_sidecar_present(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    (Path(str(env.db_path) + "-wal")).write_bytes(b"")

    plan = env.restore_manager.restore_plan(target_id)

    assert plan.sidecar_check_passed is False
    assert plan.would_proceed is False


# -- restore(): happy path -----------------------------------------------------------


def test_restore_full_flow_reaches_verified_success(tmp_path: Path):
    env = make_environment(tmp_path)
    original_config_hashes = _config_hashes(env.config_dir)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E777")

    result = env.restore_manager.restore(
        target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE, reason="unit test restore"
    )

    assert result.backup_id == target_id
    assert _query_episode_ids(env.db_path) == ["RLC-E777"]

    # journal reaches VERIFIED_SUCCESS as the final, gap-free transition
    chain = discover_journal_chain(result.journal_dir)
    states = [t.state for t in chain]
    assert states[0] == "RESTORE_INITIATED"
    assert states[-1] == "VERIFIED_SUCCESS"
    assert "DB_REPLACED" in states
    assert "CONFIG_REPLACED" in states
    assert "PRE_RESTORE_SNAPSHOT_COMPLETE" in states

    # pre-restore safety backup independently verifies and holds the *old* state
    pre_restore_verification = env.backup_manager.verify_backup(result.pre_restore_backup_id)
    assert pre_restore_verification.verified is True

    # superseded config preserved, holding the *old* config content
    assert result.superseded_config_path.is_dir()
    for filename, old_hash in original_config_hashes.items():
        assert _sha256_bytes(result.superseded_config_path / filename) == old_hash

    # target backup itself still verifies, untouched by being restored
    assert env.backup_manager.verify_backup(target_id).verified is True


def test_restore_leaves_no_staging_artifacts_behind_on_success(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    result = env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    from redline_core.restore.staging import STAGING_DIRNAME

    staging_root = env.db_path.parent / STAGING_DIRNAME / result.restore_id
    # The staged database *file* was moved out by os.replace(); the staged
    # config *directory* was moved out by os.rename() to become the live
    # config dir itself. Neither staged payload remains at its staging path.
    assert not (staging_root / "db" / env.db_path.name).exists()
    assert not (staging_root / "config").exists()


# -- restore(): confirmation / attestation gating (before any mutation) -------------


def test_restore_rejects_mismatched_confirm_backup_id_before_any_mutation(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    db_hash_before = _sha256_bytes(env.db_path)

    with pytest.raises(RestoreConfirmationError):
        env.restore_manager.restore(target_id, confirm_backup_id="b1-not-the-same", attestations=_ALL_TRUE)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert not (env.backup_root / "restore_journal").exists()


def test_restore_rejects_missing_attestations_before_any_mutation(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    db_hash_before = _sha256_bytes(env.db_path)

    incomplete = QuiescenceAttestations(mcp_stopped=True, control_room_stopped=False, no_other_cli_operation=True)
    with pytest.raises(RestoreAttestationMissingError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=incomplete)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert not (env.backup_root / "restore_journal").exists()


# -- restore(): target unavailable ----------------------------------------------------


def test_restore_rejects_missing_backup_id(tmp_path: Path):
    env = make_environment(tmp_path)
    make_target_backup(tmp_path, env)
    missing_id = "b1-20260817T000000Z-000000000000"
    db_hash_before = _sha256_bytes(env.db_path)

    with pytest.raises(RestoreTargetUnavailableError):
        env.restore_manager.restore(missing_id, confirm_backup_id=missing_id, attestations=_ALL_TRUE)

    assert _sha256_bytes(env.db_path) == db_hash_before


def test_restore_rejects_corrupt_target(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    target_package_dir = env.backup_root / "system_backups" / target_id
    snapshot_path = target_package_dir / "payload" / "database" / "redline.db"
    data = bytearray(snapshot_path.read_bytes())
    data[0] ^= 0xFF
    snapshot_path.write_bytes(bytes(data))
    db_hash_before = _sha256_bytes(env.db_path)

    with pytest.raises(RestoreTargetUnavailableError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    assert _sha256_bytes(env.db_path) == db_hash_before


def test_restore_rejects_missing_backup_path_configuration(tmp_path: Path):
    env = make_environment(tmp_path, configure_backup_path=False)
    with pytest.raises(BackupError):
        env.restore_manager.restore(
            "b1-20260817T000000Z-000000000000", confirm_backup_id="b1-20260817T000000Z-000000000000", attestations=_ALL_TRUE
        )


# -- restore(): schema incompatible ----------------------------------------------------


def test_restore_rejects_schema_incompatible_target_before_pre_restore_snapshot(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(
        tmp_path, env, db_statements=["CREATE TABLE wrong_shape (id INTEGER PRIMARY KEY)"], unique_dir="bad_schema_source"
    )
    db_hash_before = _sha256_bytes(env.db_path)
    backups_before = set((env.backup_root / "system_backups").iterdir())

    with pytest.raises(RestoreSchemaIncompatibleError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    assert _sha256_bytes(env.db_path) == db_hash_before
    # no pre-restore safety backup was created -- schema check happens first
    assert set((env.backup_root / "system_backups").iterdir()) == backups_before


# -- restore(): pre-restore safety backup failure aborts before mutation -------------


def test_restore_aborts_before_live_mutation_when_pre_restore_snapshot_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    db_hash_before = _sha256_bytes(env.db_path)
    config_hashes_before = _config_hashes(env.config_dir)

    def _boom(*args, **kwargs):
        raise BackupError("simulated pre-restore snapshot failure")

    monkeypatch.setattr(env.backup_manager, "create_backup", _boom)

    with pytest.raises(RestorePreRestoreSnapshotFailedError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert _config_hashes(env.config_dir) == config_hashes_before


# -- restore(): quiescence ---------------------------------------------------------------


def test_restore_aborts_when_live_database_is_not_quiescent(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    db_hash_before = _sha256_bytes(env.db_path)

    writer = sqlite3.connect(str(env.db_path), timeout=0)
    try:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(RestoreQuiescenceFailedError):
            env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)
    finally:
        writer.rollback()
        writer.close()

    assert _sha256_bytes(env.db_path) == db_hash_before


# -- restore(): sidecar gate ------------------------------------------------------------


def test_restore_aborts_when_sidecar_present_before_replacement(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    db_hash_before = _sha256_bytes(env.db_path)
    (Path(str(env.db_path) + "-journal")).write_bytes(b"")

    with pytest.raises(RestoreSidecarPresentError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    assert _sha256_bytes(env.db_path) == db_hash_before
    assert Path(str(env.db_path) + "-journal").exists()  # sidecar never deleted


# -- post-restore verification: byte-identity, isolated -----------------------------


def test_verify_restore_rejects_wrong_but_same_schema_live_database(tmp_path: Path):
    """A database that is a structurally valid, schema-compatible SQLite
    file -- but is NOT byte-identical to the target backup's payload --
    must be rejected by verification's byte-identity check even though it
    would pass schema compatibility and integrity_check on its own."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E555")
    verification = env.backup_manager.verify_backup(target_id)
    manifest_path = verification.backup_path / "backup_manifest.json"
    import json

    manifest = json.loads(manifest_path.read_bytes())

    # Simulate the live db having been "replaced" by a different, but
    # still schema-valid and structurally-sound, database.
    Database(env.db_path).connect().close()  # ensure any handle is closed
    env.db_path.unlink()
    db = Database(env.db_path).connect()
    db.init_schema()
    db.create_episode(1, "RLC-E000-DIFFERENT", "RLC-E000-DIFFERENT_MASTER")
    db.close()

    with pytest.raises(RestoreVerificationFailedError, match="does not byte-match"):
        env.restore_manager._verify_restore(manifest=manifest, backup_id=target_id)


def test_verify_restore_rejects_wrong_but_valid_config_content(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    verification = env.backup_manager.verify_backup(target_id)
    manifest_path = verification.backup_path / "backup_manifest.json"
    import json

    manifest = json.loads(manifest_path.read_bytes())

    # Live config is still valid YAML, still parses -- just not byte-identical.
    (env.config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: ['RLG-999']\n", encoding="utf-8")

    with pytest.raises(RestoreVerificationFailedError, match="does not byte-match"):
        env.restore_manager._verify_restore(manifest=manifest, backup_id=target_id)


# -- boundaries -------------------------------------------------------------------------


def _imported_module_names(file_path: Path) -> set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_restore_subsystem_source_never_imports_resolve():
    repo_root = Path(__file__).resolve().parents[2]
    restore_src_dir = repo_root / "src" / "redline_core" / "restore"
    cli_file = repo_root / "src" / "cli" / "restore_commands.py"
    files = sorted(restore_src_dir.glob("*.py")) + [cli_file]
    assert len(files) >= 8, f"expected the full restore module set to exist, found: {files}"

    for file_path in files:
        imported = _imported_module_names(file_path)
        offending = {name for name in imported if "resolve" in name.lower()}
        assert not offending, f"{file_path} imports Resolve-related module(s): {offending}"


def test_restore_subsystem_source_never_imports_mcp_or_control_room():
    repo_root = Path(__file__).resolve().parents[2]
    restore_src_dir = repo_root / "src" / "redline_core" / "restore"
    cli_file = repo_root / "src" / "cli" / "restore_commands.py"
    files = sorted(restore_src_dir.glob("*.py")) + [cli_file]

    for file_path in files:
        imported = _imported_module_names(file_path)
        offending = {name for name in imported if "mcp" in name.lower() or "control_room" in name.lower()}
        assert not offending, f"{file_path} imports MCP/Control Room module(s): {offending}"


def test_no_restore_degraded_action_registered():
    import argparse

    from cli import backup_commands

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="resource")
    backup_commands.register_parser(subparsers)

    with pytest.raises(SystemExit):
        parser.parse_args(["backup", "restore-degraded", "b1-x"])


def test_restore_full_flow_never_calls_database_init_schema_on_live_or_target_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    calls: list[Path] = []
    real_init_schema = Database.init_schema

    def _tracking_init_schema(self):
        calls.append(Path(self.db_path).resolve())
        return real_init_schema(self)

    monkeypatch.setattr(Database, "init_schema", _tracking_init_schema)

    env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    forbidden = {env.db_path.resolve()}
    target_payload_db = env.backup_root / "system_backups" / target_id / "payload" / "database" / "redline.db"
    forbidden.add(target_payload_db.resolve())
    for called_path in calls:
        assert called_path not in forbidden, f"Database.init_schema() was called against a forbidden path: {called_path}"


def test_restore_does_not_roll_back_a_completed_database_replacement_when_config_replacement_later_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Proves locked scope item 18 (no automatic rollback): once
    DB_REPLACED has happened, a later failure does not revert it."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E321")

    import os
    from redline_core.restore.exceptions import RestoreConfigReplacementFailedError

    real_rename = os.rename

    def _fail_installing_staged_config(src, dst):
        # Only the "install staged config over the live config dir" step
        # targets `env.config_dir` itself as `dst` -- every other os.rename
        # call in this flow (journal transitions, rename-aside) must be
        # left alone, or this test would fail for the wrong reason.
        if Path(dst) == env.config_dir:
            raise OSError("simulated failure installing staged config")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", _fail_installing_staged_config)

    with pytest.raises(RestoreConfigReplacementFailedError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    # database replacement is NOT rolled back even though the overall restore failed
    assert _query_episode_ids(env.db_path) == ["RLC-E321"]
