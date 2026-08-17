"""Integration tests (Mission 1A, correction pass): prove -- with real,
concurrently writing SQLite connections, never a mock and never an assertion
of documented SQLite behavior -- that BackupManager.create_backup() produces
a verified, internally consistent snapshot while another connection is
actively INSERTing and committing against the same live database file.

Mirrors this project's own established "integration" convention (see
tests/integration/test_asset_sqlite_repository.py): real filesystem/SQLite
I/O, no Resolve dependency. Not collected by a bare `pytest` run --
`pyproject.toml`'s `testpaths = ["tests/unit"]` excludes `tests/
integration/` from the default invocation; run explicitly via
`pytest tests/unit tests/integration`.

--------------------------------------------------------------------------
Two tests, two distinct proofs (do not conflate them)
--------------------------------------------------------------------------

This file's second independent review found the first test below proves
concurrent-writer *semantics of the genuine SQLite Online Backup API*, but
-- because it necessarily monkeypatches `package.snapshot_database` with a
test-local function in order to get a synchronization hook -- does not
directly exercise Redline OS's own, entirely unmodified, shipped
`redline_core.backup.sqlite_snapshot.snapshot_database()` wrapper under
concurrency. Two tests now cover the two distinct claims, honestly scoped:

  1. `test_backup_created_while_writer_actively_commits_is_verified_
     consistent` (below): **deterministic** proof that SQLite's Online
     Backup API (`sqlite3.Connection.backup()`) itself tolerates a real,
     concurrently committing writer -- proven via test-local instrumentation
     around the real API call, not the production wrapper itself.

  2. `test_backup_created_by_real_production_wrapper_while_writer_
     actively_commits` (below, second test): direct, unmocked exercise of
     the actual shipped `snapshot_database()` wrapper -- zero monkeypatching
     of it anywhere in that test -- with a real writer thread committing
     repeatedly throughout the whole `create_backup()` operation window.
     This test does **not** claim to deterministically prove a specific
     commit landed strictly between the production `backup()` call's entry
     and return (that would require instrumenting the production wrapper
     itself, which this correction pass deliberately avoids doing merely to
     make the proof prettier). It proves, on direct observation rather than
     inference: the real wrapper, exercised through its real call site,
     produces a valid, independently-verified snapshot while a writer
     commits continuously throughout, and the live source database remains
     intact and writable afterward.

Test 1 is the deterministic API-semantics proof. Test 2 is the production-
wrapper coverage. Neither substitutes for the other; both are kept.

--------------------------------------------------------------------------
Test 1: Deterministic overlap proof (Mission 1A correction pass)
--------------------------------------------------------------------------

An earlier version of this test asserted only `write_count[0] > 0` after
`create_backup()` returned, and inferred that a committed write "must have"
overlapped the actual `sqlite3.Connection.backup()` (Online Backup API)
invocation. Independent review reproduced a failure proving that inference
false: under load, the writer's first successful commit can land *after*
the Online Backup API call has already finished copying pages, during one
of `create_backup()`'s later stages (config file copy/hash/verify/publish)
-- `write_count[0] > 0` was satisfied without any real overlap with the
backup() call itself, and the snapshot (seeded with zero rows in that
version) reflected exactly that.

This version seeds one known, committed episode row *before* any
concurrency activity starts, so every content/consistency assertion below
holds regardless of timing -- no assertion here depends on a race winning.

To prove genuine overlap deterministically (not probabilistically), this
test does not touch BackupManager/package/sqlite_snapshot production code
at all. Instead it monkeypatches `redline_core.backup.package.
snapshot_database` -- the single call site `BackupManager.create_backup()`
uses to invoke the Online Backup API -- with a test-local function that:

  1. Opens the exact same read-only source connection and plain
     destination connection production code would (same URI construction,
     reusing `redline_core.backup.sqlite_snapshot._read_only_uri()`).
  2. Calls the *real* `sqlite3.Connection.backup()` -- the genuine Online
     Backup API, not a mock or stand-in -- but with `pages=1` (forcing
     incremental, multi-step copying instead of one single-shot internal
     step) and a `progress` callback.

`sqlite3.Connection.backup()` invokes its `progress` callback *synchronously,
from within the still-executing C call*, once per internal step; the
Python call has not returned control to its caller at the moment a
`progress` invocation is running. This test's `progress` callback:

  - signals `backup_call_in_progress` the first time it fires (proving the
    real Online Backup API call has genuinely begun copying pages), then
  - blocks (bounded by a timeout, never indefinitely) until
    `writer_committed_during_backup_call` is set.

The writer thread waits for `backup_call_in_progress` before attempting its
first write, then INSERTs and commits, and only *after that commit
succeeds* sets `writer_committed_during_backup_call`.

Because the `progress` callback is synchronously blocking `sqlite3.
Connection.backup()`'s return at the exact moment `writer_committed_
during_backup_call` is set, the writer's commit is provably bracketed
between the backup() call's start and its return -- real overlap with the
real Online Backup API invocation, not inferred from wall-clock proximity
or `write_count[0] > 0` at the end of a multi-stage operation. If overlap
does not occur (e.g. a future refactor stops routing through `pages`/
`progress`, or the writer thread never gets scheduled), the bounded waits
time out and the test fails explicitly rather than hanging or passing on
weak evidence.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from redline_core.backup.exceptions import BackupDatabaseSnapshotError
from redline_core.backup.manager import BackupManager
from redline_core.backup.sqlite_snapshot import _read_only_uri
from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import Database

_FIXED_MOMENT = datetime(2026, 8, 16, 19, 30, 0, tzinfo=timezone.utc)
_SYNC_TIMEOUT_SECONDS = 15.0
_REQUIRED_CONFIG_FILES = {
    "naming.yaml": (
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    ),
    "folder_structure.yaml": 'root_path: "./_episodes"\n',
    "render_presets.yaml": "presets: []\n",
    "paths.yaml": (
        'ingest_path: "./_ingest"\narchive_path: "./_archive"\nassets_path: "./_assets"\n'
        'master_project_template: "RLC_MASTER_TEMPLATE"\n'
    ),
    "assets.yaml": "assets: []\nrequired_for_episode: []\n",
    "timeline_template.yaml": 'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n',
}


def _make_synchronized_snapshot_database(
    backup_call_in_progress: threading.Event,
    writer_committed_during_backup_call: threading.Event,
):
    """Return a drop-in replacement for
    `redline_core.backup.sqlite_snapshot.snapshot_database()` that performs
    the exact same real work (read-only source connection, real Online
    Backup API call) but with `pages=1` + a synchronizing `progress`
    callback -- see module docstring for exactly what this proves."""

    def _synchronized_snapshot_database(source_db_path: Path, destination_db_path: Path) -> None:
        destination_db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            source_conn = sqlite3.connect(_read_only_uri(source_db_path), uri=True)
        except sqlite3.Error as exc:
            raise BackupDatabaseSnapshotError(
                f"could not open live database read-only for snapshot: {source_db_path}"
            ) from exc

        def _progress(status, remaining, total) -> None:  # noqa: ANN001 - sqlite3 callback signature
            # This function runs synchronously *inside* the still-executing
            # sqlite3.Connection.backup() call below; backup() has not
            # returned to _synchronized_snapshot_database while we are in
            # here. Blocking here is what makes the writer's subsequent
            # commit provably concurrent with the real Online Backup API
            # invocation, not merely nearby in wall-clock time.
            backup_call_in_progress.set()
            writer_committed_during_backup_call.wait(timeout=_SYNC_TIMEOUT_SECONDS)

        try:
            try:
                destination_conn = sqlite3.connect(str(destination_db_path))
            except sqlite3.Error as exc:
                raise BackupDatabaseSnapshotError(
                    f"could not open backup snapshot destination: {destination_db_path}"
                ) from exc
            try:
                # sleep=0.0: the only intentional pause between steps is
                # this test's own Event-based synchronization inside
                # _progress() above -- sqlite3's own default 0.250s
                # inter-step sleep would otherwise add multiple seconds of
                # pure overhead for a many-page-stepped backup with no
                # bearing on what this test is proving.
                source_conn.backup(destination_conn, pages=1, progress=_progress, sleep=0.0)
            except sqlite3.Error as exc:
                raise BackupDatabaseSnapshotError(
                    f"SQLite Online Backup API failed for {source_db_path} -> {destination_db_path}"
                ) from exc
            finally:
                destination_conn.close()
        finally:
            source_conn.close()

    return _synchronized_snapshot_database


def _continuous_writer(
    db_path: Path,
    stop_event: threading.Event,
    write_count: list[int],
    backup_call_in_progress: threading.Event,
    writer_committed_during_backup_call: threading.Event,
) -> None:
    """Runs on a background thread with its own independent connection --
    never the one BackupManager/Database under test uses. Waits for proof
    that the real Online Backup API call has genuinely begun before
    committing its first row (so that first commit is deterministically
    inside the call's execution window, not merely racing to get there
    first), then keeps writing in a tight loop until told to stop -- the
    real-world shape of a live `redline`/`redline-mcp` process mutating
    pipeline state while a backup runs concurrently."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        episode_number = 2000
        if not backup_call_in_progress.wait(timeout=_SYNC_TIMEOUT_SECONDS):
            return  # backup() never started; let the main thread's own assertions report this cleanly
        while not stop_event.is_set():
            conn.execute(
                "INSERT INTO episodes (episode_number, episode_id, project_name) VALUES (?, ?, ?)",
                (episode_number, f"RLC-E{episode_number}", f"RLC-E{episode_number}_MASTER"),
            )
            conn.commit()
            write_count[0] += 1
            if not writer_committed_during_backup_call.is_set():
                writer_committed_during_backup_call.set()
            episode_number += 1
    finally:
        conn.close()


def test_backup_created_while_writer_actively_commits_is_verified_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()
    seed_db.init_schema()
    # Seed one known, committed row *before* any concurrency activity
    # starts, so snapshot-content assertions below hold regardless of
    # whether a concurrent write happened to land inside the copied pages
    # -- unlike an earlier version of this test, nothing here depends on
    # race timing to be true.
    seed_db.create_episode(1, "RLC-E001", "RLC-E001_MASTER")
    seed_db.close()

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for filename, text in _REQUIRED_CONFIG_FILES.items():
        (config_dir / filename).write_text(text, encoding="utf-8")

    backup_root = tmp_path / "backups"
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path="./_episodes"),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path="./_ingest",
            archive_path="./_archive",
            assets_path="./_assets",
            master_project_template="RLC_MASTER_TEMPLATE",
            backup_path=str(backup_root),
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    manager = BackupManager(config, config_dir, db_path, clock=lambda: _FIXED_MOMENT)

    backup_call_in_progress = threading.Event()
    writer_committed_during_backup_call = threading.Event()

    # Test-only instrumentation around the real backup call (see module
    # docstring): still real SQLite, still the real Online Backup API,
    # never a mock of either. Scoped to this test only via monkeypatch.
    monkeypatch.setattr(
        "redline_core.backup.package.snapshot_database",
        _make_synchronized_snapshot_database(backup_call_in_progress, writer_committed_during_backup_call),
    )

    stop_event = threading.Event()
    write_count = [0]
    writer_thread = threading.Thread(
        target=_continuous_writer,
        args=(db_path, stop_event, write_count, backup_call_in_progress, writer_committed_during_backup_call),
        daemon=True,
    )
    writer_thread.start()

    try:
        result = manager.create_backup(reason="concurrent-writer integration test")
    finally:
        stop_event.set()
        writer_thread.join(timeout=30.0)

    assert not writer_thread.is_alive(), "writer thread did not stop cleanly"

    # The deterministic overlap proof itself (see module docstring): the
    # real Online Backup API call genuinely started, and a real committed
    # write landed strictly while sqlite3.Connection.backup() was still
    # executing (synchronously blocked inside its own progress callback).
    assert backup_call_in_progress.is_set(), "the real Online Backup API call never started"
    assert writer_committed_during_backup_call.is_set(), (
        "no committed write was proven to overlap the real Online Backup API invocation -- "
        "this is exactly the gap the mission's correction pass required closing"
    )
    assert write_count[0] > 0

    # The backup itself must independently re-verify clean.
    verification = manager.verify_backup(result.backup_id)
    assert verification.verified is True
    assert verification.database_integrity_check == "ok"

    # The snapshot must be a genuinely valid, queryable SQLite database on
    # its own -- not merely bytes that happen to pass integrity_check. The
    # seed row guarantees this holds regardless of whether any concurrent
    # write happened to land inside the pages already copied.
    snapshot_path = result.backup_path / "payload" / "database" / "redline.db"
    conn = sqlite3.connect(f"{snapshot_path.as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        assert count >= 1  # the seed row, guaranteed; more if concurrent inserts landed before their page copied
    finally:
        conn.close()

    # The live source database must still be fully intact and still being
    # written to correctly -- backup must never have blocked, corrupted, or
    # otherwise interfered with the concurrent writer.
    source_conn = sqlite3.connect(db_path)
    try:
        assert source_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        live_count = source_conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        assert live_count >= write_count[0] + 1  # +1 for the seed row

        # Prove the source remains writable after the backup has fully
        # completed, not merely readable.
        source_conn.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name) VALUES (?, ?, ?)",
            (9999, "RLC-E9999", "RLC-E9999_MASTER"),
        )
        source_conn.commit()
        assert source_conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == live_count + 1
    finally:
        source_conn.close()


def _continuous_writer_unsynchronized(db_path: Path, stop_event: threading.Event, write_count: list[int]) -> None:
    """Runs on a background thread with its own independent connection --
    never the one BackupManager/Database under test uses. Unlike
    `_continuous_writer` above, this does not wait for any synchronization
    signal: it starts committing immediately and keeps going until told to
    stop, exactly the real-world shape of a live `redline`/`redline-mcp`
    process mutating pipeline state with no awareness that a backup is
    running concurrently -- which is the point of this second test: no
    special hooks, on either side."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        episode_number = 3000
        while not stop_event.is_set():
            conn.execute(
                "INSERT INTO episodes (episode_number, episode_id, project_name) VALUES (?, ?, ?)",
                (episode_number, f"RLC-E{episode_number}", f"RLC-E{episode_number}_MASTER"),
            )
            conn.commit()
            write_count[0] += 1
            episode_number += 1
    finally:
        conn.close()


def test_backup_created_by_real_production_wrapper_while_writer_actively_commits(tmp_path: Path):
    """Test 2 (see module docstring): direct, unmocked exercise of the real
    `redline_core.backup.sqlite_snapshot.snapshot_database()` wrapper --
    zero monkeypatching of it, or of anything else in `redline_core.backup`,
    anywhere in this test -- while a real writer thread commits repeatedly
    and continuously throughout the entire `create_backup()` operation
    window (not just around a single instrumented call).

    This does not claim to deterministically prove a specific commit landed
    strictly between the production `backup()` call's entry and return --
    only Test 1 above makes that specific, narrower claim, and it does so by
    instrumenting around the real API rather than the production wrapper.
    What this test proves instead: the actual shipped wrapper, exercised
    exactly as `BackupManager.create_backup()` calls it in production,
    tolerates genuine sustained concurrent write activity and still produces
    a valid, independently-verified snapshot, while the live source database
    remains intact and writable afterward.
    """
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    db_path = runtime_dir / "redline.db"
    seed_db = Database(db_path).connect()
    seed_db.init_schema()
    # Seed one known, committed row so snapshot-content assertions below
    # hold regardless of whether any concurrent write happened to land
    # inside pages already copied by the (unsynchronized, real-world-shaped)
    # writer -- this test makes no timing claims, so no assertion here may
    # depend on one.
    seed_db.create_episode(1, "RLC-E001", "RLC-E001_MASTER")
    seed_db.close()

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for filename, text in _REQUIRED_CONFIG_FILES.items():
        (config_dir / filename).write_text(text, encoding="utf-8")

    backup_root = tmp_path / "backups"
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path="./_episodes"),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path="./_ingest",
            archive_path="./_archive",
            assets_path="./_assets",
            master_project_template="RLC_MASTER_TEMPLATE",
            backup_path=str(backup_root),
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    # No monkeypatch anywhere in this test: manager.create_backup() below
    # calls the real, entirely unmodified redline_core.backup.package.
    # build_staged_backup(), which calls the real, entirely unmodified
    # redline_core.backup.sqlite_snapshot.snapshot_database().
    manager = BackupManager(config, config_dir, db_path, clock=lambda: _FIXED_MOMENT)

    stop_event = threading.Event()
    write_count = [0]
    writer_thread = threading.Thread(
        target=_continuous_writer_unsynchronized, args=(db_path, stop_event, write_count), daemon=True
    )
    writer_thread.start()

    try:
        result = manager.create_backup(reason="production-wrapper concurrent-writer coverage")
    finally:
        stop_event.set()
        writer_thread.join(timeout=30.0)

    assert not writer_thread.is_alive(), "writer thread did not stop cleanly"
    assert write_count[0] > 0, "writer thread never got a chance to commit -- test did not exercise real concurrency"

    # The backup itself must independently re-verify clean.
    verification = manager.verify_backup(result.backup_id)
    assert verification.verified is True
    assert verification.database_integrity_check == "ok"

    # The snapshot produced by the real, unmocked production wrapper must be
    # a genuinely valid, queryable SQLite database on its own.
    snapshot_path = result.backup_path / "payload" / "database" / "redline.db"
    conn = sqlite3.connect(f"{snapshot_path.as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        assert count >= 1  # the seed row, guaranteed
    finally:
        conn.close()

    # The live source database must still be fully intact and still being
    # written to correctly.
    source_conn = sqlite3.connect(db_path)
    try:
        assert source_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        live_count = source_conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        assert live_count >= write_count[0] + 1  # +1 for the seed row

        source_conn.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name) VALUES (?, ?, ?)",
            (8888, "RLC-E8888", "RLC-E8888_MASTER"),
        )
        source_conn.commit()
        assert source_conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == live_count + 1
    finally:
        source_conn.close()
