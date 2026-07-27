"""Tests for TimelineBuilder, against MockResolveAdapter."""
from pathlib import Path

from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    MarkerDefinition,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder


def make_config(tmp_path: Path, markers=None) -> RedlineConfig:
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
        timeline=TimelineTemplateConfig(
            timeline_name_pattern="{episode_id}_TIMELINE",
            markers=markers if markers is not None else [
                MarkerDefinition(frame=0, color="Blue", name="Cold Open", note="Episode start"),
                MarkerDefinition(frame=1800, color="Yellow", name="Ad Break 1"),
            ],
        ),
    )


def connected_mock_with_project(project_name: str) -> MockResolveAdapter:
    resolve = MockResolveAdapter()
    resolve.connect()
    resolve.duplicate_project(project_name, "RLC_MASTER_TEMPLATE")
    return resolve


def test_build_timeline_for_episode(tmp_path):
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")

    builder = TimelineBuilder(config, resolve)
    result = builder.build_timeline_for_episode("RLC-E025_MASTER", "RLC-E025")

    assert result.timeline_name == "RLC-E025_TIMELINE"
    assert result.timeline_id == "RLC-E025_TIMELINE"
    assert result.markers_applied == 2
    assert resolve.timelines["RLC-E025_MASTER"] == "RLC-E025_TIMELINE"


def test_build_timeline_applies_configured_markers(tmp_path):
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")

    builder = TimelineBuilder(config, resolve)
    builder.build_timeline_for_episode("RLC-E025_MASTER", "RLC-E025")

    applied = resolve.markers["RLC-E025_MASTER:RLC-E025_TIMELINE"]
    assert [m["name"] for m in applied] == ["Cold Open", "Ad Break 1"]
    assert applied[0]["frame"] == 0
    assert applied[1]["color"] == "Yellow"


def test_build_timeline_with_no_markers_applies_zero(tmp_path):
    config = make_config(tmp_path, markers=[])
    resolve = connected_mock_with_project("RLC-E025_MASTER")

    builder = TimelineBuilder(config, resolve)
    result = builder.build_timeline_for_episode("RLC-E025_MASTER", "RLC-E025")

    assert result.markers_applied == 0
    assert "RLC-E025_MASTER:RLC-E025_TIMELINE" not in resolve.markers


def test_apply_markers_can_override_default_set(tmp_path):
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")
    builder = TimelineBuilder(config, resolve)
    builder.build_timeline_for_episode("RLC-E025_MASTER", "RLC-E025")

    custom = [MarkerDefinition(frame=500, color="Red", name="Custom Beat")]
    count = builder.apply_markers("RLC-E025_MASTER", "RLC-E025_TIMELINE", custom)

    assert count == 1
    applied = resolve.markers["RLC-E025_MASTER:RLC-E025_TIMELINE"]
    # Original 2 + 1 custom, since MockResolveAdapter.add_markers appends.
    assert len(applied) == 3
    assert applied[-1]["name"] == "Custom Beat"
