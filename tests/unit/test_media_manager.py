"""Tests for MediaManager, against a temp ingest folder + MockResolveAdapter."""
from pathlib import Path

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.media.manager import MediaManager
from redline_core.resolve.mock import MockResolveAdapter


def make_config(tmp_path: Path) -> RedlineConfig:
    return RedlineConfig(
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


def test_scan_ingest_missing_folder_returns_empty(tmp_path):
    manager = MediaManager(make_config(tmp_path), MockResolveAdapter())
    assert manager.scan_ingest_for_episode("RLC-E025") == []


def test_scan_ingest_matches_by_episode_id(tmp_path):
    config = make_config(tmp_path)
    ingest = Path(config.paths.ingest_path)
    ingest.mkdir()
    (ingest / "RLC-E025_camA_001.mov").write_bytes(b"x")
    (ingest / "RLC-E025_camB_001.mov").write_bytes(b"x")
    (ingest / "RLC-E026_camA_001.mov").write_bytes(b"x")  # different episode, should not match

    manager = MediaManager(config, MockResolveAdapter())
    matches = manager.scan_ingest_for_episode("RLC-E025")
    assert {p.name for p in matches} == {"RLC-E025_camA_001.mov", "RLC-E025_camB_001.mov"}


def test_organize_bins_imports_matched_media(tmp_path):
    config = make_config(tmp_path)
    ingest = Path(config.paths.ingest_path)
    ingest.mkdir()
    (ingest / "RLC-E025_camA_001.mov").write_bytes(b"x")

    resolve = MockResolveAdapter()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    manager = MediaManager(config, resolve)
    clip_ids = manager.organize_bins("RLC-E025_MASTER", "RLC-E025", bin_name="footage")

    assert len(clip_ids) == 1
    assert resolve.media["RLC-E025_MASTER"] == clip_ids


def test_organize_bins_no_matches_returns_empty_without_calling_resolve(tmp_path):
    config = make_config(tmp_path)
    Path(config.paths.ingest_path).mkdir()

    resolve = MockResolveAdapter()
    resolve.connect()
    resolve.duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    manager = MediaManager(config, resolve)
    clip_ids = manager.organize_bins("RLC-E025_MASTER", "RLC-E025")
    assert clip_ids == []
