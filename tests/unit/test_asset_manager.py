"""Tests for AssetManager. Everything is disk-based (no Resolve involved)."""
from pathlib import Path

import pytest

from redline_core.asset.manager import AssetManager, MissingAssetsError
from redline_core.config.schema import (
    AssetDefinition,
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)


def make_config(tmp_path: Path) -> RedlineConfig:
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()

    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(assets_path),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(
            assets=[
                AssetDefinition(asset_id="RLG-001", description="Lower third", filename="lower_third.png"),
                AssetDefinition(asset_id="RLG-003", description="Sponsor bug", filename="sponsor_bug.png"),
            ],
            required_for_episode=["RLG-001", "RLG-003"],
        ),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )


def test_list_available_assets(tmp_path):
    manager = AssetManager(make_config(tmp_path))
    ids = {a.asset_id for a in manager.list_available_assets()}
    assert ids == {"RLG-001", "RLG-003"}


def test_verify_assets_all_missing_when_no_files(tmp_path):
    manager = AssetManager(make_config(tmp_path))
    result = manager.verify_assets_for_episode()
    assert result.all_present is False
    assert set(result.missing) == {"RLG-001", "RLG-003"}
    assert result.found == []


def test_verify_assets_all_present(tmp_path):
    config = make_config(tmp_path)
    Path(config.paths.assets_path, "lower_third.png").write_bytes(b"x")
    Path(config.paths.assets_path, "sponsor_bug.png").write_bytes(b"x")

    manager = AssetManager(config)
    result = manager.verify_assets_for_episode()
    assert result.all_present is True
    assert {a.asset_id for a in result.found} == {"RLG-001", "RLG-003"}
    assert result.missing == []


def test_verify_assets_partial(tmp_path):
    config = make_config(tmp_path)
    Path(config.paths.assets_path, "lower_third.png").write_bytes(b"x")  # only this one exists

    manager = AssetManager(config)
    result = manager.verify_assets_for_episode()
    assert result.all_present is False
    assert result.missing == ["RLG-003"]


def test_verify_assets_unregistered_id_counts_as_missing(tmp_path):
    manager = AssetManager(make_config(tmp_path))
    result = manager.verify_assets_for_episode(["RLG-999"])
    assert result.missing == ["RLG-999"]


def test_ensure_assets_raises_when_missing(tmp_path):
    manager = AssetManager(make_config(tmp_path))
    with pytest.raises(MissingAssetsError):
        manager.ensure_assets_for_episode()


def test_ensure_assets_passes_when_present(tmp_path):
    config = make_config(tmp_path)
    Path(config.paths.assets_path, "lower_third.png").write_bytes(b"x")
    Path(config.paths.assets_path, "sponsor_bug.png").write_bytes(b"x")

    manager = AssetManager(config)
    result = manager.ensure_assets_for_episode()
    assert result.all_present is True
