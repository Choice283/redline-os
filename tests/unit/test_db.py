"""Tests for redline_core.db.Database against a temporary SQLite file."""
from redline_core.db.database import Database
from redline_core.db.models import EpisodeStatus


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
