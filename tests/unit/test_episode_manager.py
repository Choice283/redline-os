"""Tests for EpisodeManager, built entirely against MockResolveAdapter + a
temp SQLite DB + temp folders — no real Resolve or Studio license needed."""
from pathlib import Path

import pytest

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
from redline_core.db.models import EpisodeStatus
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeNotFoundError
from redline_core.episode.manager import EpisodeManager
from redline_core.resolve.mock import MockResolveAdapter


def make_manager(tmp_path: Path) -> EpisodeManager:
    config = RedlineConfig(
        naming=NamingConfig(
            episode_id_pattern="RLC-E{episode_number:03d}",
            project_name_pattern="{episode_id}_MASTER",
        ),
        folder_structure=FolderStructureConfig(
            root_path=str(tmp_path / "_episodes"),
            subfolders=["footage", "graphics", "audio", "exports", "project"],
        ),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(tmp_path / "_assets"),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    resolve = MockResolveAdapter()
    resolve.connect()
    return EpisodeManager(config=config, db=db, resolve=resolve)


def test_create_episode_success(tmp_path):
    manager = make_manager(tmp_path)
    episode = manager.create_episode(25)

    assert episode.episode_id == "RLC-E025"
    assert episode.project_name == "RLC-E025_MASTER"
    assert episode.status == EpisodeStatus.CREATED
    assert episode.folder_path is not None
    assert episode.project_path is not None

    folder = Path(episode.folder_path)
    assert folder.is_dir()
    for sub in ["footage", "graphics", "audio", "exports", "project"]:
        assert (folder / sub).is_dir()

    # And it actually exists in the mock Resolve backend.
    assert episode.project_name in manager.resolve.projects


def test_create_episode_twice_raises(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_episode(25)
    with pytest.raises(EpisodeAlreadyExistsError):
        manager.create_episode(25)


def test_get_episode_status_not_found(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(EpisodeNotFoundError):
        manager.get_episode_status(999)


def test_get_episode_status_found(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_episode(25)
    episode = manager.get_episode_status(25)
    assert episode.episode_number == 25


def test_list_episodes_ordered(tmp_path):
    manager = make_manager(tmp_path)
    manager.create_episode(2)
    manager.create_episode(1)
    episodes = manager.list_episodes()
    assert [e.episode_number for e in episodes] == [1, 2]
