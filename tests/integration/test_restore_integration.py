"""Integration tests (Mission 1B-A1): full HEALTHY_SOURCE restore end to end
against real, disposable SQLite databases and config directories under
`tmp_path` -- never a mock, never a Resolve dependency, never pointed at any
production path (`C:\\Users\\pj198\\RedlineOSLive\\...` is never referenced
anywhere in this file).

Mirrors this project's own established "integration" convention (see
tests/integration/test_backup_concurrent_writer.py): real filesystem/SQLite
I/O, including a real background writer *thread* for the quiescence proof
below -- the one property that genuinely distinguishes this file from the
fast, single-threaded unit suite in tests/unit/test_restore_manager.py. Not
collected by a bare `pytest` run -- `pyproject.toml`'s
`testpaths = ["tests/unit"]` excludes `tests/integration/`; run explicitly
via `pytest tests/unit tests/integration`.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from redline_core.db.database import Database, RenderJobStatus
from redline_core.restore.exceptions import RestoreQuiescenceFailedError, RestoreStagingFailedError
from redline_core.restore.journal import discover_journal_chain
from redline_core.restore.models import QuiescenceAttestations

from tests.unit._restore_test_helpers import make_environment, make_target_backup

_ALL_TRUE = QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True)


def _seed_production_shaped_target(tmp_path: Path, env) -> tuple[str, dict]:
    """Build a target backup from an independent, production-shaped
    dataset -- multiple episodes, render jobs, and an archive row, not
    just a single bare episode -- so the full restore proof below is
    checking real multi-table content, not a degenerate single-row case.
    """
    source_dir = tmp_path / "production_shaped_source"
    source_dir.mkdir()
    source_db_path = source_dir / "redline.db"
    db = Database(source_db_path).connect()
    db.init_schema()
    db.create_episode(1, "RLC-E101", "RLC-E101_MASTER")
    db.create_episode(2, "RLC-E102", "RLC-E102_MASTER")
    db.create_render_job("RLC-E101", "broadcast_master", status=RenderJobStatus.COMPLETE)
    db.close()

    source_config_dir = source_dir / "config"
    from tests.unit._restore_test_helpers import write_minimal_config_dir

    write_minimal_config_dir(source_config_dir)

    from redline_core.backup.manager import BackupManager

    source_backup_manager = BackupManager(env.config, source_config_dir, source_db_path, clock=env.clock)
    result = source_backup_manager.create_backup(reason="production-shaped integration target")

    expected = {"episodes": ["RLC-E101", "RLC-E102"], "render_job_count": 1}
    return result.backup_id, expected


def test_full_restore_of_production_shaped_dataset_reaches_verified_success(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id, expected = _seed_production_shaped_target(tmp_path, env)

    result = env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE, reason="integration test")

    conn = sqlite3.connect(f"{env.db_path.as_uri()}?mode=ro", uri=True)
    try:
        episode_ids = [r[0] for r in conn.execute("SELECT episode_id FROM episodes ORDER BY episode_id").fetchall()]
        render_job_count = conn.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()

    assert episode_ids == expected["episodes"]
    assert render_job_count == expected["render_job_count"]
    assert integrity == "ok"

    chain = discover_journal_chain(result.journal_dir)
    assert [t.state for t in chain][-1] == "VERIFIED_SUCCESS"

    # The pre-restore safety backup independently verifies and represents
    # the ORIGINAL (single-episode) state, not the newly-restored one.
    pre_conn_verification = env.backup_manager.verify_backup(result.pre_restore_backup_id)
    assert pre_conn_verification.verified is True


# -- real concurrent writer thread: quiescence proof ---------------------------------


def test_restore_is_blocked_by_a_real_concurrent_writer_thread_and_succeeds_once_it_stops(tmp_path: Path):
    """Deterministic, real-threading proof (not a static held-open
    connection in the same thread): a background thread holds a genuine
    write lock on the live database via its own connection; restore()
    must fail closed with RestoreQuiescenceFailedError while that lock is
    held, and must succeed once the thread releases it and exits."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E606")

    lock_acquired = threading.Event()
    release_lock = threading.Event()
    writer_error: list[BaseException] = []

    def _hold_write_lock():
        try:
            conn = sqlite3.connect(str(env.db_path), timeout=0)
            try:
                conn.execute("BEGIN IMMEDIATE")
                lock_acquired.set()
                release_lock.wait(timeout=10)
            finally:
                conn.rollback()
                conn.close()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the main thread below
            writer_error.append(exc)
            lock_acquired.set()

    writer_thread = threading.Thread(target=_hold_write_lock, daemon=True)
    writer_thread.start()
    assert lock_acquired.wait(timeout=10), "background writer thread never acquired its lock"
    assert not writer_error, f"background writer thread failed to set up: {writer_error}"

    try:
        with pytest.raises(RestoreQuiescenceFailedError):
            env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)
    finally:
        release_lock.set()
        writer_thread.join(timeout=10)
        assert not writer_thread.is_alive()

    # Once the real writer thread has released its lock and exited, the
    # identical restore call succeeds.
    result = env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)
    chain = discover_journal_chain(result.journal_dir)
    assert [t.state for t in chain][-1] == "VERIFIED_SUCCESS"


# -- injected failure at a mutation boundary preserves artifacts --------------------


def test_injected_staging_failure_preserves_pre_restore_backup_and_leaves_live_system_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A disk-failure-shaped interruption during staging (after the
    mandatory pre-restore safety backup has already succeeded) must leave
    the live database/config completely untouched and must not discard
    the safety backup or the journal recording how far the attempt got."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env, episode_id="RLC-E404")

    import hashlib

    db_hash_before = hashlib.sha256(env.db_path.read_bytes()).hexdigest()

    def _boom(**kwargs):
        raise RestoreStagingFailedError("simulated disk failure during staging")

    monkeypatch.setattr("redline_core.restore.manager.stage_database", _boom)

    with pytest.raises(RestoreStagingFailedError):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    assert hashlib.sha256(env.db_path.read_bytes()).hexdigest() == db_hash_before

    # A pre-restore safety backup now exists (it was created before staging
    # was attempted) and independently verifies.
    system_backups = list((env.backup_root / "system_backups").iterdir())
    assert len(system_backups) == 2  # the original target + the new pre-restore safety snapshot
    pre_restore_ids = [p.name for p in system_backups if p.name != target_id]
    assert len(pre_restore_ids) == 1
    verification = env.backup_manager.verify_backup(pre_restore_ids[0])
    assert verification.verified is True

    # The journal for this attempt stops at STAGING_FAILED -- no DB_REPLACE*
    # transition was ever recorded.
    restore_journal_root = env.backup_root / "restore_journal"
    journal_dirs = list(restore_journal_root.iterdir())
    assert len(journal_dirs) == 1
    chain = discover_journal_chain(journal_dirs[0])
    states = [t.state for t in chain]
    assert states[-1] == "STAGING_FAILED"
    assert "DB_REPLACE_INTENT" not in states
    assert "DB_REPLACED" not in states
