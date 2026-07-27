"""Tests for redline_core.config against the real example files in /config."""
from pathlib import Path

import pytest

from redline_core.config.loader import ConfigError, load_config
from redline_core.config.schema import RedlineConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def test_load_config_from_example_files():
    config = load_config(CONFIG_DIR)
    assert isinstance(config, RedlineConfig)
    assert config.naming.episode_id_pattern == "RLC-E{episode_number:03d}"
    assert "footage" in config.folder_structure.subfolders
    assert config.render_presets.get("broadcast_master") is not None
    assert config.paths.master_project_template == "RLC_MASTER_TEMPLATE"
    assert config.assets.get("RLG-001") is not None
    assert "RLG-001" in config.assets.required_for_episode
    assert config.timeline.timeline_name_pattern == "{episode_id}_TIMELINE"
    assert len(config.timeline.markers) == 4


def test_episode_id_pattern_formats_correctly():
    config = load_config(CONFIG_DIR)
    episode_id = config.naming.episode_id_pattern.format(episode_number=25)
    assert episode_id == "RLC-E025"


def test_missing_config_dir_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does_not_exist")


def test_invalid_config_fails_schema_validation(tmp_path):
    (tmp_path / "naming.yaml").write_text("episode_id_pattern: ''\nproject_name_pattern: 'x'\n")
    (tmp_path / "folder_structure.yaml").write_text("root_path: './x'\n")
    (tmp_path / "render_presets.yaml").write_text("presets: []\n")
    (tmp_path / "paths.yaml").write_text(
        "ingest_path: './i'\narchive_path: './a'\nassets_path: './assets'\nmaster_project_template: 'T'\n"
    )
    (tmp_path / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n")
    (tmp_path / "timeline_template.yaml").write_text("timeline_name_pattern: '{episode_id}_T'\nmarkers: []\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)
