"""Tests for redline_core.db.Database against a temporary SQLite file."""
import pytest

from redline_core.db.database import AssemblyClaimReleaseError, Database
from redline_core.db.models import EpisodeStatus, RenderJobStatus


def make_db(tmp_path):
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    return db


def test_init_schema_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    db.init_schema()  # should not raise on second call
    db.close()


def test_create_and_fetch_episode(tmp_path):
    db = make_db(tmp_path)
    episode = db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")

    assert episode.id is not None
    assert episode.episode_number == 25
    assert episode.episode_id == "RLC-E025"
    assert episode.status == EpisodeStatus.CREATED

    fetched = db.get_episode_by_number(25)
    assert fetched is not None
    assert fetched.episode_id == "RLC-E025"
    db.close()


def test_list_episodes_ordered_by_number(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(2, "RLC-E002", "RLC-E002_MASTER")
    db.create_episode(1, "RLC-E001", "RLC-E001_MASTER")

    episodes = db.list_episodes()
    assert [e.episode_number for e in episodes] == [1, 2]
    db.close()


def test_update_episode_status(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.TIMELINE_BUILT)

    updated = db.get_episode_by_number(25)
    assert updated.status == EpisodeStatus.TIMELINE_BUILT
    db.close()


def test_get_missing_episode_returns_none(tmp_path):
    db = make_db(tmp_path)
    assert db.get_episode_by_number(999) is None
    db.close()


def test_create_accepted_render_job_persists_identity_and_status_atomically(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")

    job = db.create_accepted_render_job(
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        resolve_job_id="resolve-job-1",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path="C:/episodes/RLC-E025/exports/RLC-E025.mov",
    )

    reloaded = db.get_render_job_by_id(job.id)
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert reloaded.status == RenderJobStatus.QUEUED
    assert reloaded.resolve_job_id == "resolve-job-1"
    assert reloaded.project_name == "RLC-E025_MASTER"
    assert reloaded.timeline_name == "RLC-E025_TIMELINE"
    assert reloaded.output_path == "C:/episodes/RLC-E025/exports/RLC-E025.mov"
    assert episode.status == EpisodeStatus.RENDER_QUEUED
    db.close()


def test_init_schema_migrates_render_job_identity_columns_without_losing_rows(tmp_path):
    db = Database(tmp_path / "legacy.db").connect()
    db.conn.executescript(
        """
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_number INTEGER NOT NULL UNIQUE,
            episode_id TEXT NOT NULL UNIQUE,
            project_name TEXT NOT NULL,
            project_path TEXT,
            folder_path TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            assembly_claim_token TEXT,
            assembly_claimed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE render_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
            preset_name TEXT NOT NULL,
            resolve_job_id TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            output_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO episodes (episode_number, episode_id, project_name)
        VALUES (25, 'RLC-E025', 'RLC-E025_MASTER');
        INSERT INTO render_jobs (episode_id, preset_name, resolve_job_id, status, output_path)
        VALUES ('RLC-E025', 'broadcast_master', 'old-job', 'queued', 'C:/old.mov');
        """
    )
    db.conn.commit()

    db.init_schema()

    columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(render_jobs)").fetchall()}
    assert "project_name" in columns
    assert "timeline_name" in columns
    old_job = db.get_render_job_by_id(1)
    assert old_job.resolve_job_id == "old-job"
    assert old_job.project_name is None
    assert old_job.timeline_name is None

    new_job = db.create_accepted_render_job(
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        resolve_job_id="new-job",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path="C:/new.mov",
    )

    reloaded = db.get_render_job_by_id(new_job.id)
    assert reloaded.project_name == "RLC-E025_MASTER"
    assert reloaded.timeline_name == "RLC-E025_TIMELINE"
    assert db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.RENDER_QUEUED
    db.close()


# -- Episode assembly claim (ADR-0001) -------------------------------------


def test_claim_episode_for_assembly_succeeds_from_created(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")

    claimed = db.claim_episode_for_assembly("RLC-E025", "token-a")

    assert claimed is True
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-a"
    assert episode.assembly_claimed_at is not None
    db.close()


def test_claim_episode_for_assembly_fails_when_already_claimed(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    assert db.claim_episode_for_assembly("RLC-E025", "token-a") is True

    # Second claim attempt (e.g. a concurrent process) must not acquire the
    # claim while the first is still active -- this is the core atomicity
    # guarantee ADR-0001 requires.
    claimed_again = db.claim_episode_for_assembly("RLC-E025", "token-b")

    assert claimed_again is False
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-a"  # unchanged
    db.close()


def test_claim_episode_for_assembly_fails_for_terminal_status_even_with_force(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.ASSEMBLED)

    claimed = db.claim_episode_for_assembly("RLC-E025", "token-a", allow_unsafe_retry=True)

    assert claimed is False


def test_claim_episode_for_assembly_fails_for_failed_status_without_force(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)

    claimed = db.claim_episode_for_assembly("RLC-E025", "token-a")

    assert claimed is False


def test_claim_episode_for_assembly_succeeds_for_failed_status_with_force(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)

    claimed = db.claim_episode_for_assembly("RLC-E025", "token-a", allow_unsafe_retry=True)

    assert claimed is True


def test_claim_episode_for_assembly_with_force_still_bypasses_dangling_claim(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)
    assert db.claim_episode_for_assembly("RLC-E025", "token-a", allow_unsafe_retry=True) is True

    # A second, forced claim attempt (simulating retry after a crash mid-attempt,
    # before the first claim was ever released) must still be able to acquire --
    # allow_unsafe_retry drops the "claim token is NULL" guard entirely.
    claimed_again = db.claim_episode_for_assembly("RLC-E025", "token-b", allow_unsafe_retry=True)

    assert claimed_again is True
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-b"
    db.close()


def test_release_assembly_claim_sets_status_and_clears_claim(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.claim_episode_for_assembly("RLC-E025", "token-a")

    db.release_assembly_claim("RLC-E025", "token-a", EpisodeStatus.ASSEMBLED)

    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.ASSEMBLED
    assert episode.assembly_claim_token is None
    assert episode.assembly_claimed_at is None
    db.close()


def test_release_assembly_claim_is_token_owned(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.claim_episode_for_assembly("RLC-E025", "token-a")

    # A release with the wrong token must not touch a claim it doesn't own
    # (ADR-0001 refinement 1) -- e.g. a stale/superseded attempt trying to
    # release a claim a newer attempt now holds. This must be a hard
    # failure, not a log-and-continue: a caller ignoring the exception and
    # proceeding as if it succeeded is exactly the bug this release-failure
    # correction closes.
    with pytest.raises(AssemblyClaimReleaseError, match="RLC-E025"):
        db.release_assembly_claim("RLC-E025", "token-wrong", EpisodeStatus.FAILED)

    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-a"  # untouched
    assert episode.status == EpisodeStatus.CREATED  # untouched
    db.close()


def test_release_assembly_claim_stale_token_cannot_release_newer_claim(tmp_path):
    """Distinct from the "wrong token" case above: here token-a legitimately
    held the claim, was properly released, and a *different, later* claim
    (token-b) has since taken ownership. The original (now-stale) caller,
    unaware ownership moved on, must not be able to release token-b's
    active claim using its old token."""
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.claim_episode_for_assembly("RLC-E025", "token-a")
    db.release_assembly_claim("RLC-E025", "token-a", EpisodeStatus.FAILED)
    assert db.claim_episode_for_assembly("RLC-E025", "token-b", allow_unsafe_retry=True) is True

    with pytest.raises(AssemblyClaimReleaseError):
        db.release_assembly_claim("RLC-E025", "token-a", EpisodeStatus.ASSEMBLED)

    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-b"  # untouched by the stale release
    assert episode.status == EpisodeStatus.FAILED  # untouched by the stale release
    db.close()


# -- Forced-claim compare-and-swap (correctness fix) -----------------------


def test_forced_claim_cas_two_racers_on_same_dangling_claim_only_one_wins(tmp_path):
    """The specific race the original forced-claim SQL was vulnerable to:
    two callers both observe the SAME dangling claim (identical status +
    claim_token) before either has written. The fix must guarantee exactly
    one of them acquires the claim, even though both started from
    identical observed state -- a normal sequential "claim, then claim
    again" test does not exercise this, since the second call would
    naturally observe the first call's already-committed new token, not
    the original shared stale state.

    This calls the real, non-test-only CAS helper
    (_claim_episode_for_assembly_cas) directly with two independently
    "observed" (status, token) pairs pinned to the identical pre-race
    values -- deterministically reproducing the race without depending on
    real thread/process scheduling.
    """
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)
    db.claim_episode_for_assembly("RLC-E025", "dangling-token", allow_unsafe_retry=True)

    # Both "racers" observed the identical pre-race state: status=failed,
    # assembly_claim_token="dangling-token".
    result_a = db._claim_episode_for_assembly_cas(
        "RLC-E025", "token-a", observed_status="failed", observed_token="dangling-token"
    )
    result_b = db._claim_episode_for_assembly_cas(
        "RLC-E025", "token-b", observed_status="failed", observed_token="dangling-token"
    )

    assert sorted([result_a, result_b]) == [False, True]
    episode = db.get_episode_by_episode_id("RLC-E025")
    # Ownership changed exactly once, to whichever racer's UPDATE committed
    # first -- never corrupted, never both, never neither.
    winning_token = "token-a" if result_a else "token-b"
    assert episode.assembly_claim_token == winning_token
    db.close()


def test_forced_claim_cas_second_racer_cannot_also_win_against_updated_state(tmp_path):
    """Companion assertion to the race test above, stated the other way:
    once one CAS attempt commits, a second attempt pinned to the
    now-superseded observed values must fail outright (rowcount 0), not
    merely "usually" fail. Runs the two calls in a fixed, deterministic
    order (rather than asserting on the sorted pair) to pin down exactly
    which one is expected to lose."""
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)
    db.claim_episode_for_assembly("RLC-E025", "dangling-token", allow_unsafe_retry=True)

    first = db._claim_episode_for_assembly_cas(
        "RLC-E025", "token-a", observed_status="failed", observed_token="dangling-token"
    )
    assert first is True

    # Second racer's CAS is pinned to the SAME stale observed values the
    # first racer used -- must fail now that the token has moved on.
    second = db._claim_episode_for_assembly_cas(
        "RLC-E025", "token-b", observed_status="failed", observed_token="dangling-token"
    )
    assert second is False

    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-a"
    db.close()


def test_forced_claim_cas_uses_is_null_for_observed_null_token(tmp_path):
    """A fresh, never-claimed episode has assembly_claim_token = NULL --
    the CAS helper must match that with `IS NULL`, not `= NULL` (which
    would never match in SQL)."""
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)

    claimed = db._claim_episode_for_assembly_cas(
        "RLC-E025", "token-a", observed_status="failed", observed_token=None
    )

    assert claimed is True
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token == "token-a"
    db.close()


def test_forced_claim_cas_rejects_terminal_status_without_attempting_update(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.update_episode_status("RLC-E025", EpisodeStatus.ASSEMBLED)

    claimed = db._claim_episode_for_assembly_cas(
        "RLC-E025", "token-a", observed_status="assembled", observed_token=None
    )

    assert claimed is False
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.assembly_claim_token is None
    db.close()


def test_claim_after_release_can_be_reacquired(tmp_path):
    db = make_db(tmp_path)
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    db.claim_episode_for_assembly("RLC-E025", "token-a")
    db.release_assembly_claim("RLC-E025", "token-a", EpisodeStatus.FAILED)

    # After a proper release, ordinary (non-forced) reclaiming is still
    # blocked because status is now FAILED -- but forced reclaiming works.
    assert db.claim_episode_for_assembly("RLC-E025", "token-b") is False
    assert db.claim_episode_for_assembly("RLC-E025", "token-b", allow_unsafe_retry=True) is True
    db.close()


def test_migrate_add_assembly_claim_columns_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    # init_schema() already ran the migration once (via make_db); calling it
    # again directly must be a safe no-op, not raise on duplicate ALTER TABLE.
    db._migrate_add_assembly_claim_columns()
    db.close()


def test_migrate_add_assembly_claim_columns_upgrades_pre_mission_13_table(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_number INTEGER NOT NULL UNIQUE,
            episode_id TEXT NOT NULL UNIQUE,
            project_name TEXT NOT NULL,
            project_path TEXT,
            folder_path TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path).connect()
    db.init_schema()  # must not raise, and must add the missing columns

    columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(episodes)").fetchall()}
    assert "assembly_claim_token" in columns
    assert "assembly_claimed_at" in columns

    # And the upgraded table must actually be usable by the new claim logic.
    db.create_episode(1, "RLC-E001", "RLC-E001_MASTER")
    assert db.claim_episode_for_assembly("RLC-E001", "token-a") is True
    db.close()
