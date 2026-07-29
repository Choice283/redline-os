"""Tests for TimelineBuilder, against MockResolveAdapter."""
import logging
from pathlib import Path

import pytest

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
    assert resolve.timelines["RLC-E025_MASTER"] == ["RLC-E025_TIMELINE"]


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


def test_build_timeline_for_episode_repeated_call_reuses_timeline_but_duplicates_markers(tmp_path):
    """Documents existing, tested behavior — not a defect to be fixed here:

    build_timeline_for_episode() reuses an already-existing Resolve
    timeline by name rather than creating a duplicate (both at the adapter
    layer, see test_resolve_script_adapter_timeline.py, and reproduced by
    MockResolveAdapter here), but it always reapplies the configured
    marker set on every call regardless of whether the timeline was newly
    created or reused. Calling it twice against the same episode therefore
    duplicates markers on the timeline. This test exists specifically to
    make that real, previously-uncovered behavior explicit and provable at
    the TimelineBuilder layer, independent of any CLI test — no
    deduplication is introduced to make this test pass.
    """
    config = make_config(tmp_path)  # 2 configured markers: "Cold Open", "Ad Break 1"
    resolve = connected_mock_with_project("RLC-E025_MASTER")
    builder = TimelineBuilder(config, resolve)

    first_result = builder.build_timeline_for_episode("RLC-E025_MASTER", "RLC-E025")
    second_result = builder.build_timeline_for_episode("RLC-E025_MASTER", "RLC-E025")

    # 1 & 2: the second call returns the same timeline name as the first.
    assert first_result.timeline_name == "RLC-E025_TIMELINE"
    assert second_result.timeline_name == first_result.timeline_name

    # 3: only one timeline with that name exists in the mock — no duplicate
    # timeline object was created on the second call.
    assert resolve.timelines["RLC-E025_MASTER"] == ["RLC-E025_TIMELINE"]

    # 4 & 6: each call reports markers_applied == N (the configured count),
    # not a running total — the manager reports what it just applied, not
    # a cumulative count.
    configured_marker_count = len(config.timeline.markers)
    assert configured_marker_count == 2
    assert first_result.markers_applied == configured_marker_count
    assert second_result.markers_applied == configured_marker_count

    # 5: the Resolve mock's stored marker list for this timeline has grown
    # to exactly 2N — the configured set was applied twice, duplicated.
    applied = resolve.markers["RLC-E025_MASTER:RLC-E025_TIMELINE"]
    assert len(applied) == configured_marker_count * 2


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


def test_place_clips_delegates_project_timeline_and_clip_ids_exactly(tmp_path):
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")
    clip_ids = resolve.import_media("RLC-E025_MASTER", ["/x/a.mov", "/x/b.mov"], "footage")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    builder = TimelineBuilder(config, resolve)

    builder.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", [clip_ids[1], clip_ids[0]])

    records = resolve.timeline_items["RLC-E025_MASTER:RLC-E025_TIMELINE"]
    assert [record["clip_id"] for record in records] == [clip_ids[1], clip_ids[0]]


def test_place_clips_returns_adapter_timeline_item_ids(tmp_path):
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")
    clip_ids = resolve.import_media("RLC-E025_MASTER", ["/x/a.mov"], "footage")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    builder = TimelineBuilder(config, resolve)

    timeline_item_ids = builder.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)

    assert timeline_item_ids == [
        resolve.timeline_items["RLC-E025_MASTER:RLC-E025_TIMELINE"][0]["timeline_item_id"]
    ]


def test_place_clips_logs_successful_count(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")
    clip_ids = resolve.import_media("RLC-E025_MASTER", ["/x/a.mov"], "footage")
    resolve.build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")
    builder = TimelineBuilder(config, resolve)

    builder.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)

    assert "Placed 1 clip(s)" in caplog.text


class FailingPlacementAdapter(MockResolveAdapter):
    def place_clips(self, project_name: str, timeline_name: str, clip_ids: list[str]) -> list[str]:
        raise ValueError("adapter failure")


def test_place_clips_adapter_exception_propagates_unchanged(tmp_path):
    config = make_config(tmp_path)
    builder = TimelineBuilder(config, FailingPlacementAdapter())

    with pytest.raises(ValueError, match="adapter failure"):
        builder.place_clips("project", "timeline", ["clip-1"])


def test_place_clips_empty_input_behavior_matches_adapter(tmp_path):
    config = make_config(tmp_path)
    resolve = connected_mock_with_project("RLC-E025_MASTER")
    builder = TimelineBuilder(config, resolve)

    assert builder.place_clips("RLC-E025_MASTER", "RLC-E025_TIMELINE", []) == []
