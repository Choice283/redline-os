"""Tests for ArchiveManager, against a temp DB and temp folders (no Resolve involved)."""
from pathlib import Path

import pytest

from redline_core.archive.exceptions import ArchiveError, EpisodeAlreadyArchivedError
from redline_core.archive.manager import ArchiveManager
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
from redline_core.episode.exceptions import EpisodeNotFoundError


def make_manager(tmp_path: Path, with_folder: bool = True):
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
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
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")

    folder = None
    if with_folder:
        folder = tmp_path / "_episodes" / "RLC-E025"
        folder.mkdir(parents=True)
        (folder / "exports").mkdir()
        (folder / "exports" / "ep025.mov").write_bytes(b"x")
        db.update_episode_paths("RLC-E025", folder_path=str(folder))

    return ArchiveManager(config, db), db, folder


def test_archive_episode_moves_folder(tmp_path):
    manager, db, folder = make_manager(tmp_path)
    record = manager.archive_episode("RLC-E025")

    assert not folder.exists()
    assert Path(record.archive_path).is_dir()
    assert (Path(record.archive_path) / "exports" / "ep025.mov").is_file()

    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.ARCHIVED
    assert episode.folder_path == record.archive_path


def test_archive_episode_twice_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    manager.archive_episode("RLC-E025")
    with pytest.raises(EpisodeAlreadyArchivedError):
        manager.archive_episode("RLC-E025")


def test_archive_unknown_episode_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path)
    with pytest.raises(EpisodeNotFoundError):
        manager.archive_episode("RLC-E999")


def test_archive_episode_without_folder_raises(tmp_path):
    manager, _, _ = make_manager(tmp_path, with_folder=False)
    with pytest.raises(ArchiveError):
        manager.archive_episode("RLC-E025")


def test_archive_episode_destination_already_exists_raises(tmp_path):
    """Covers the one previously-untested ArchiveManager branch: a folder
    already sitting at the destination path (archive_path/episode_id)
    that has no matching archive record. This is a manager-level behavior
    proof, independent of any CLI test — the CLI test for this same
    condition (tests/unit/test_cli_archive_episode.py) only proves the CLI
    passes this manager error through unchanged; it is not this branch's
    only coverage.
    """
    manager, db, folder = make_manager(tmp_path)

    # Pre-create the destination the manager will try to move into.
    dest = tmp_path / "_archive" / "RLC-E025"
    dest.mkdir(parents=True)

    with pytest.raises(ArchiveError):
        manager.archive_episode("RLC-E025")

    # The source folder must be untouched: shutil.move() never ran because
    # the destination check raises before it.
    assert folder.is_dir()
    episode = db.get_episode_by_episode_id("RLC-E025")
    assert episode.status != EpisodeStatus.ARCHIVED


def test_list_archives(tmp_path):
    manager, db, _ = make_manager(tmp_path)
    db.create_episode(26, "RLC-E026", "RLC-E026_MASTER")
    folder2 = tmp_path / "_episodes" / "RLC-E026"
    folder2.mkdir(parents=True)
    db.update_episode_paths("RLC-E026", folder_path=str(folder2))

    manager.archive_episode("RLC-E025")
    manager.archive_episode("RLC-E026")

    archives = manager.list_archives()
    assert {a.episode_id for a in archives} == {"RLC-E025", "RLC-E026"}
