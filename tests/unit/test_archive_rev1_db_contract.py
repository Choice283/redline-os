"""Phase 15 Mission 15B — Archive Manager Rev1 database contract tests.

Scope: the SQLite/model foundation only (schema migration,
ArchiveRecord/ArchiveState, and Database.commit_verified_archive()). No
filesystem copying, hashing, staging, or ArchiveManager behavior is
exercised here -- those remain out of scope until later Phase 15 missions.
"""
from __future__ import annotations

import sqlite3

import pytest

from redline_core.db.database import ArchiveCommitError, Database
from redline_core.db.models import ArchiveState, EpisodeStatus, RenderJobStatus


# -- helpers ------------------------------------------------------------------


def make_db(tmp_path):
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    return db


def seed_rendered_episode_with_completed_render_job(
    db: Database, episode_number: int = 25, episode_id: str = "RLC-E025"
):
    db.create_episode(episode_number, episode_id, f"{episode_id}_MASTER")
    db.update_episode_status(episode_id, EpisodeStatus.RENDERED)
    render_job = db.create_render_job(
        episode_id,
        "broadcast_master",
        resolve_job_id="resolve-job-1",
        project_name=f"{episode_id}_MASTER",
        timeline_name=f"{episode_id}_TIMELINE",
        output_path=f"C:/episodes/{episode_id}/exports/{episode_id}_MASTER.mov",
        status=RenderJobStatus.COMPLETE,
    )
    return render_job


def commit_kwargs(episode_id: str, render_job_id: int, **overrides) -> dict:
    kwargs = {
        "episode_id": episode_id,
        "render_job_id": render_job_id,
        "archive_id": f"ARCHIVE-{episode_id}",
        "archive_path": f"C:/archive/{episode_id}",
        "manifest_path": f"C:/archive/{episode_id}/archive_manifest.json",
        "manifest_sha256": "a" * 64,
        "verified_at": "2026-08-11 20:00:00",
    }
    kwargs.update(overrides)
    return kwargs


class _FailOnceAfterMarkerConnProxy:
    """Wraps a real sqlite3.Connection so a specific later statement can be
    made to raise -- sqlite3.Connection itself is an immutable extension
    type (its methods cannot be monkeypatched directly), so this proxy is
    substituted for Database._conn instead. Every call not explicitly
    intercepted is forwarded unchanged to the real connection, including
    __enter__/__exit__, so real transaction commit/rollback semantics are
    preserved for both the marker statement and the intercepted one.
    """

    def __init__(self, real_conn, *, marker: str, fail_when: str):
        self._real = real_conn
        self._marker = marker
        self._fail_when = fail_when
        self._marker_seen = False

    def execute(self, sql, *args, **kwargs):
        if self._marker in sql:
            self._marker_seen = True
            return self._real.execute(sql, *args, **kwargs)
        if self._marker_seen and sql.strip().startswith(self._fail_when):
            raise sqlite3.OperationalError("simulated failure between archive insert and episode transition")
        return self._real.execute(sql, *args, **kwargs)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._real.__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._real, name)


# -- migration: fresh database -------------------------------------------------


def test_fresh_database_has_complete_rev1_archive_schema(tmp_path):
    db = make_db(tmp_path)
    try:
        columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(archives)").fetchall()}
        assert columns == {
            "id",
            "episode_id",
            "archive_path",
            "archive_id",
            "archive_schema_version",
            "archive_state",
            "manifest_path",
            "manifest_sha256",
            "render_job_id",
            "verified_at",
            "archived_at",
        }
    finally:
        db.close()


# -- migration: legacy database -------------------------------------------------


def test_legacy_database_migrates_preserving_historical_row_as_legacy(tmp_path):
    db_path = tmp_path / "legacy.db"

    # Build a pre-Rev1 database by hand: the exact old archives shape
    # (id, episode_id, archive_path, archived_at) plus the minimal episodes
    # table it references, with one historical archive row already present.
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "CREATE TABLE episodes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, episode_number INTEGER NOT NULL UNIQUE, "
            "episode_id TEXT NOT NULL UNIQUE, project_name TEXT NOT NULL, project_path TEXT, "
            "folder_path TEXT, status TEXT NOT NULL DEFAULT 'created', "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        raw.execute(
            "CREATE TABLE render_jobs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL, preset_name TEXT NOT NULL, "
            "resolve_job_id TEXT, status TEXT NOT NULL DEFAULT 'queued', output_path TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        raw.execute(
            "CREATE TABLE archives ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "episode_id TEXT NOT NULL UNIQUE REFERENCES episodes(episode_id), "
            "archive_path TEXT NOT NULL, "
            "archived_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        raw.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name, status) "
            "VALUES (25, 'RLC-E025', 'RLC-E025_MASTER', 'archived')"
        )
        raw.execute(
            "INSERT INTO archives (episode_id, archive_path, archived_at) "
            "VALUES ('RLC-E025', 'D:/cold_storage/RLC-E025', '2025-01-01 00:00:00')"
        )
        raw.commit()
    finally:
        raw.close()

    db = Database(db_path).connect()
    try:
        db.init_schema()  # the migration under test

        row = db.conn.execute("SELECT * FROM archives WHERE episode_id = 'RLC-E025'").fetchone()
        assert row is not None
        assert row["archive_path"] == "D:/cold_storage/RLC-E025"
        assert row["archived_at"] == "2025-01-01 00:00:00"
        assert row["archive_schema_version"] == 0
        assert row["archive_state"] == "legacy"
        # New nullable Rev1 fields must not fabricate any Rev1 metadata for
        # a historical row -- no archive_id/manifest/render linkage/verification
        # exists for something Rev1 never built or verified.
        assert row["archive_id"] is None
        assert row["manifest_path"] is None
        assert row["manifest_sha256"] is None
        assert row["render_job_id"] is None
        assert row["verified_at"] is None

        record = db.get_archive_by_episode_id("RLC-E025")
        assert record.archive_state == ArchiveState.LEGACY
        assert record.archive_schema_version == 0
    finally:
        db.close()


# -- commit_verified_archive: success -------------------------------------------


def test_commit_verified_archive_success(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)

        record = db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id))

        assert record.episode_id == "RLC-E025"
        assert record.archive_id == "ARCHIVE-RLC-E025"
        assert record.archive_path == "C:/archive/RLC-E025"
        assert record.archive_schema_version == 1
        assert record.archive_state == ArchiveState.COMPLETE
        assert record.manifest_path == "C:/archive/RLC-E025/archive_manifest.json"
        assert record.manifest_sha256 == "a" * 64
        assert record.render_job_id == render_job.id
        assert record.verified_at == "2026-08-11 20:00:00"
        assert record.archived_at is not None

        archives = db.list_archives()
        assert len(archives) == 1
        assert archives[0].episode_id == "RLC-E025"

        episode = db.get_episode_by_episode_id("RLC-E025")
        assert episode.status == EpisodeStatus.ARCHIVED
        # The DB method must never touch folder_path -- Rev1 keeps it
        # pointed at the original active workspace.
        assert episode.folder_path is None
    finally:
        db.close()


def test_commit_verified_archive_preserves_existing_folder_path(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)
        db.update_episode_paths("RLC-E025", folder_path="C:/episodes/RLC-E025")

        db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id))

        episode = db.get_episode_by_episode_id("RLC-E025")
        assert episode.folder_path == "C:/episodes/RLC-E025"
    finally:
        db.close()


# -- commit_verified_archive: eligibility rejections ----------------------------


def test_commit_verified_archive_rejects_non_rendered_episode(tmp_path):
    db = make_db(tmp_path)
    try:
        db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")  # status stays CREATED
        render_job = db.create_render_job(
            "RLC-E025",
            "broadcast_master",
            resolve_job_id="resolve-job-1",
            project_name="RLC-E025_MASTER",
            timeline_name="RLC-E025_TIMELINE",
            output_path="C:/episodes/RLC-E025/exports/RLC-E025_MASTER.mov",
            status=RenderJobStatus.COMPLETE,
        )

        with pytest.raises(ArchiveCommitError):
            db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id))

        assert db.get_archive_by_episode_id("RLC-E025") is None
        assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.CREATED
    finally:
        db.close()


def test_commit_verified_archive_rejects_wrong_render_job_ownership(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job_a = seed_rendered_episode_with_completed_render_job(db, 25, "RLC-E025")
        db.create_episode(26, "RLC-E026", "RLC-E026_MASTER")
        db.update_episode_status("RLC-E026", EpisodeStatus.RENDERED)

        with pytest.raises(ArchiveCommitError):
            db.commit_verified_archive(**commit_kwargs("RLC-E026", render_job_a.id))

        assert db.get_archive_by_episode_id("RLC-E026") is None
        assert db.get_episode_by_episode_id("RLC-E026").status == EpisodeStatus.RENDERED
    finally:
        db.close()


@pytest.mark.parametrize(
    "status",
    [
        RenderJobStatus.CLAIMING,
        RenderJobStatus.QUEUED,
        RenderJobStatus.RENDERING,
        RenderJobStatus.FAILED,
        RenderJobStatus.CANCELLED,
    ],
)
def test_commit_verified_archive_rejects_incomplete_render_job(tmp_path, status):
    db = make_db(tmp_path)
    try:
        db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
        db.update_episode_status("RLC-E025", EpisodeStatus.RENDERED)
        render_job = db.create_render_job(
            "RLC-E025",
            "broadcast_master",
            resolve_job_id="resolve-job-1",
            project_name="RLC-E025_MASTER",
            timeline_name="RLC-E025_TIMELINE",
            output_path="C:/episodes/RLC-E025/exports/RLC-E025_MASTER.mov",
            status=status,
        )

        with pytest.raises(ArchiveCommitError):
            db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id))

        assert db.get_archive_by_episode_id("RLC-E025") is None
        assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    finally:
        db.close()


def test_commit_verified_archive_rejects_existing_archive(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)
        db.create_archive_record("RLC-E025", "D:/cold_storage/RLC-E025")  # legacy pre-existing row

        with pytest.raises(ArchiveCommitError):
            db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id))

        archives = db.list_archives()
        assert len(archives) == 1
        assert archives[0].archive_state == ArchiveState.LEGACY
        assert archives[0].archive_path == "D:/cold_storage/RLC-E025"
    finally:
        db.close()


def test_archives_episode_id_unique_constraint_rejects_duplicate_insert(tmp_path):
    """Direct proof that the pre-existing UNIQUE constraint -- not just
    application logic -- still backs the one-archive-per-episode invariant."""
    db = make_db(tmp_path)
    try:
        db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
        db.create_archive_record("RLC-E025", "D:/cold_storage/RLC-E025")

        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute(
                "INSERT INTO archives (episode_id, archive_path) VALUES (?, ?)",
                ("RLC-E025", "D:/cold_storage/RLC-E025-again"),
            )
    finally:
        db.close()


# -- commit_verified_archive: atomicity -----------------------------------------


def test_commit_verified_archive_rolls_back_on_episode_transition_failure(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)

        real_conn = db.conn
        db._conn = _FailOnceAfterMarkerConnProxy(
            real_conn,
            marker="INSERT INTO archives",
            fail_when="UPDATE episodes SET status = ?",
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id))
        finally:
            db._conn = real_conn

        # The archive insert must not have survived the episode-transition
        # failure that came after it in the same transaction.
        assert db.get_archive_by_episode_id("RLC-E025") is None
        assert db.list_archives() == []
        assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    finally:
        db.close()


# -- ArchiveRecord round-trip ----------------------------------------------------


def test_archive_record_round_trip_insert_reload_list(tmp_path):
    db = make_db(tmp_path)
    try:
        # Legacy row.
        db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
        legacy = db.create_archive_record("RLC-E025", "D:/cold_storage/RLC-E025")
        assert legacy.archive_state == ArchiveState.LEGACY
        assert legacy.archive_schema_version == 0
        assert legacy.archive_id is None
        assert legacy.manifest_path is None
        assert legacy.manifest_sha256 is None
        assert legacy.render_job_id is None
        assert legacy.verified_at is None

        # Rev1 row.
        render_job = seed_rendered_episode_with_completed_render_job(db, 26, "RLC-E026")
        committed = db.commit_verified_archive(**commit_kwargs("RLC-E026", render_job.id))

        reloaded_legacy = db.get_archive_by_episode_id("RLC-E025")
        reloaded_rev1 = db.get_archive_by_episode_id("RLC-E026")
        assert reloaded_legacy == legacy
        assert reloaded_rev1 == committed

        archives = {a.episode_id: a for a in db.list_archives()}
        assert archives["RLC-E025"].archive_state == ArchiveState.LEGACY
        assert archives["RLC-E026"].archive_state == ArchiveState.COMPLETE
    finally:
        db.close()


# -- correction 1: manifest_sha256 validation / canonicalization ----------------


def test_commit_verified_archive_accepts_valid_lowercase_manifest_sha256(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)
        digest = "0123456789abcdef" * 4
        assert len(digest) == 64

        record = db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id, manifest_sha256=digest))

        assert record.manifest_sha256 == digest
    finally:
        db.close()


def test_commit_verified_archive_accepts_uppercase_manifest_sha256_and_stores_lowercase(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)
        uppercase_digest = "0123456789ABCDEF" * 4
        assert len(uppercase_digest) == 64

        record = db.commit_verified_archive(
            **commit_kwargs("RLC-E025", render_job.id, manifest_sha256=uppercase_digest)
        )

        assert record.manifest_sha256 == uppercase_digest.lower()

        reloaded = db.get_archive_by_episode_id("RLC-E025")
        assert reloaded.manifest_sha256 == uppercase_digest.lower()
    finally:
        db.close()


@pytest.mark.parametrize(
    "invalid_digest",
    [
        "",
        "a" * 63,
        "a" * 65,
        "g" * 64,  # non-hex character, correct length
        "not a sha256 digest at all",
        "a" * 32,  # plausible-looking but wrong length (16 bytes, not 32)
    ],
    ids=["empty", "63_chars", "65_chars", "non_hex_64_chars", "arbitrary_text", "32_chars"],
)
def test_commit_verified_archive_rejects_invalid_manifest_sha256(tmp_path, invalid_digest):
    db = make_db(tmp_path)
    try:
        render_job = seed_rendered_episode_with_completed_render_job(db)

        with pytest.raises(ArchiveCommitError):
            db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job.id, manifest_sha256=invalid_digest))

        # Rejection must create no archive row and must not change episode status.
        assert db.get_archive_by_episode_id("RLC-E025") is None
        assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDERED
    finally:
        db.close()


# -- correction 2: archive_id uniqueness -----------------------------------------


def test_fresh_database_has_archive_id_unique_index(tmp_path):
    db = make_db(tmp_path)
    try:
        indexes = {row["name"] for row in db.conn.execute("PRAGMA index_list(archives)").fetchall()}
        assert "idx_archives_archive_id_unique" in indexes
    finally:
        db.close()


def test_legacy_database_migrates_archive_id_unique_index_and_tolerates_multiple_nulls(tmp_path):
    db_path = tmp_path / "legacy_index.db"

    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "CREATE TABLE episodes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, episode_number INTEGER NOT NULL UNIQUE, "
            "episode_id TEXT NOT NULL UNIQUE, project_name TEXT NOT NULL, project_path TEXT, "
            "folder_path TEXT, status TEXT NOT NULL DEFAULT 'created', "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        raw.execute(
            "CREATE TABLE render_jobs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL, preset_name TEXT NOT NULL, "
            "resolve_job_id TEXT, status TEXT NOT NULL DEFAULT 'queued', output_path TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        raw.execute(
            "CREATE TABLE archives ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "episode_id TEXT NOT NULL UNIQUE REFERENCES episodes(episode_id), "
            "archive_path TEXT NOT NULL, "
            "archived_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        raw.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name, status) "
            "VALUES (25, 'RLC-E025', 'RLC-E025_MASTER', 'archived')"
        )
        raw.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name, status) "
            "VALUES (26, 'RLC-E026', 'RLC-E026_MASTER', 'archived')"
        )
        # Two historical rows, both with (implicit, pre-Rev1) archive_id = NULL --
        # must remain valid after the partial unique index is added.
        raw.execute(
            "INSERT INTO archives (episode_id, archive_path) VALUES ('RLC-E025', 'D:/cold_storage/RLC-E025')"
        )
        raw.execute(
            "INSERT INTO archives (episode_id, archive_path) VALUES ('RLC-E026', 'D:/cold_storage/RLC-E026')"
        )
        raw.commit()
    finally:
        raw.close()

    db = Database(db_path).connect()
    try:
        db.init_schema()  # the migration under test

        indexes = {row["name"] for row in db.conn.execute("PRAGMA index_list(archives)").fetchall()}
        assert "idx_archives_archive_id_unique" in indexes

        rows = db.conn.execute("SELECT episode_id, archive_id FROM archives ORDER BY episode_id").fetchall()
        assert [r["archive_id"] for r in rows] == [None, None]
        assert {r["episode_id"] for r in rows} == {"RLC-E025", "RLC-E026"}
    finally:
        db.close()


def test_commit_verified_archive_rejects_duplicate_archive_id(tmp_path):
    db = make_db(tmp_path)
    try:
        render_job_a = seed_rendered_episode_with_completed_render_job(db, 25, "RLC-E025")
        render_job_b = seed_rendered_episode_with_completed_render_job(db, 26, "RLC-E026")

        db.commit_verified_archive(**commit_kwargs("RLC-E025", render_job_a.id, archive_id="ARCHIVE-SHARED"))

        with pytest.raises(ArchiveCommitError):
            db.commit_verified_archive(**commit_kwargs("RLC-E026", render_job_b.id, archive_id="ARCHIVE-SHARED"))

        # The second episode must not have been archived, and must have no archive row.
        assert db.get_archive_by_episode_id("RLC-E026") is None
        assert db.get_episode_by_episode_id("RLC-E026").status == EpisodeStatus.RENDERED

        # The first episode's successful commit must be untouched by the second's failure.
        first = db.get_archive_by_episode_id("RLC-E025")
        assert first is not None
        assert first.archive_id == "ARCHIVE-SHARED"
        assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ARCHIVED

        assert len(db.list_archives()) == 1
    finally:
        db.close()


def test_archives_archive_id_unique_index_rejects_duplicate_direct_insert(tmp_path):
    """Direct proof the partial UNIQUE index -- not just application logic --
    backs the archive_id uniqueness invariant."""
    db = make_db(tmp_path)
    try:
        db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
        db.create_episode(26, "RLC-E026", "RLC-E026_MASTER")
        db.conn.execute(
            "INSERT INTO archives (episode_id, archive_path, archive_id) VALUES (?, ?, ?)",
            ("RLC-E025", "D:/cold_storage/RLC-E025", "ARCHIVE-DUP"),
        )
        db.conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute(
                "INSERT INTO archives (episode_id, archive_path, archive_id) VALUES (?, ?, ?)",
                ("RLC-E026", "D:/cold_storage/RLC-E026", "ARCHIVE-DUP"),
            )
    finally:
        db.close()
