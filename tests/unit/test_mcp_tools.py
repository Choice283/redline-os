"""Tests for the MCP tool handler functions — the underscore-prefixed `_*`
functions in each src/mcp_server/tools/*.py module. These are plain Python
with no FastMCP/`mcp` package dependency, so they run in the standard unit
test suite without the optional [mcp] extra installed. `register()` (which
does need `mcp`) is exercised separately, manually, once the extra is
installed — see docs/MCP_TOOLS.md.
"""
from pathlib import Path
from unittest.mock import Mock

import pytest

from redline_core.archive.manager import ArchiveManager
from redline_core.asset.manager import AssetManager
from redline_core.config.schema import (
    AssetDefinition,
    AssetsConfig,
    FolderStructureConfig,
    MarkerDefinition,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPreset,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.db.database import Database
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.render.manager import RenderManager
from redline_core.resolve.exceptions import TimelineOperationError
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder
from mcp_server.context import build_context

from mcp_server.tools import archive_tools, asset_tools, episode_tools, media_tools, render_tools, timeline_tools


def make_config(tmp_path: Path) -> RedlineConfig:
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(
            presets=[
                RenderPreset(name="broadcast_master", resolve_preset_name="Redline Broadcast Master", output_subfolder="exports"),
            ]
        ),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(assets_path),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(
            assets=[AssetDefinition(asset_id="RLG-001", description="Lower third", filename="lower_third.png")],
            required_for_episode=["RLG-001"],
        ),
        timeline=TimelineTemplateConfig(
            timeline_name_pattern="{episode_id}_TIMELINE",
            markers=[MarkerDefinition(frame=0, color="Blue", name="Cold Open")],
        ),
    )


def make_managers(tmp_path):
    config = make_config(tmp_path)
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    resolve = MockResolveAdapter()
    resolve.connect()
    media = MediaManager(config, resolve)
    timeline = TimelineBuilder(config, resolve)
    return {
        "config": config,
        "db": db,
        "resolve": resolve,
        "episode": EpisodeManager(config, db, resolve, media, timeline),
        "asset": AssetManager(config),
        "media": media,
        "timeline": timeline,
        "render": RenderManager(config, db, resolve),
        "archive": ArchiveManager(config, db),
    }


def test_build_context_passes_shared_media_and_timeline_managers_to_episode_manager(tmp_path):
    resolve = MockResolveAdapter()

    ctx = build_context(config_dir="config", db_path=tmp_path / "context.db", resolve_adapter=resolve)

    assert ctx.episode_manager.resolve is ctx.resolve
    assert ctx.episode_manager.media_manager is ctx.media_manager
    assert ctx.episode_manager.timeline_builder is ctx.timeline_builder
    assert ctx.media_manager.resolve is ctx.resolve
    assert ctx.timeline_builder.resolve is ctx.resolve


# -- episode_tools -----------------------------------------------------------

def test_create_episode_tool_success(tmp_path):
    m = make_managers(tmp_path)
    result = episode_tools._create_episode(m["episode"], 25)
    assert result["success"] is True
    assert result["episode"]["episode_id"] == "RLC-E025"


def test_create_episode_tool_conflict(tmp_path):
    m = make_managers(tmp_path)
    episode_tools._create_episode(m["episode"], 25)
    result = episode_tools._create_episode(m["episode"], 25)
    assert result["success"] is False
    assert "already exists" in result["error"]


def test_get_episode_status_tool_not_found(tmp_path):
    m = make_managers(tmp_path)
    result = episode_tools._get_episode_status(m["episode"], 999)
    assert result["success"] is False


def test_list_episodes_tool(tmp_path):
    m = make_managers(tmp_path)
    episode_tools._create_episode(m["episode"], 1)
    episode_tools._create_episode(m["episode"], 2)
    result = episode_tools._list_episodes(m["episode"])
    assert result["success"] is True
    assert [e["episode_number"] for e in result["episodes"]] == [1, 2]


# -- asset_tools ---------------------------------------------------------------

def test_list_available_assets_tool(tmp_path):
    m = make_managers(tmp_path)
    result = asset_tools._list_available_assets(m["asset"])
    assert result["success"] is True
    assert result["assets"][0]["asset_id"] == "RLG-001"


def test_verify_assets_tool_missing(tmp_path):
    m = make_managers(tmp_path)
    result = asset_tools._verify_assets_for_episode(m["asset"])
    assert result["all_present"] is False
    assert result["missing"] == ["RLG-001"]


def test_verify_assets_tool_present(tmp_path):
    m = make_managers(tmp_path)
    Path(m["config"].paths.assets_path, "lower_third.png").write_bytes(b"x")
    result = asset_tools._verify_assets_for_episode(m["asset"])
    assert result["all_present"] is True
    assert result["found"] == ["RLG-001"]


# -- media_tools -----------------------------------------------------------------

def test_scan_ingest_tool(tmp_path):
    m = make_managers(tmp_path)
    ingest = Path(m["config"].paths.ingest_path)
    ingest.mkdir()
    (ingest / "RLC-E025_camA.mov").write_bytes(b"x")

    result = media_tools._scan_ingest_for_episode(m["media"], "RLC-E025")
    assert result["success"] is True
    assert len(result["matches"]) == 1


def test_organize_bins_tool(tmp_path):
    m = make_managers(tmp_path)
    ingest = Path(m["config"].paths.ingest_path)
    ingest.mkdir()
    (ingest / "RLC-E025_camA.mov").write_bytes(b"x")
    m["resolve"].duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    result = media_tools._organize_bins(m["media"], "RLC-E025_MASTER", "RLC-E025")
    assert result["success"] is True
    assert result["clip_count"] == 1


# -- timeline_tools ----------------------------------------------------------------

def test_build_timeline_tool(tmp_path):
    m = make_managers(tmp_path)
    m["resolve"].duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")

    result = timeline_tools._build_timeline(m["timeline"], "RLC-E025_MASTER", "RLC-E025")
    assert result["success"] is True
    assert result["timeline_name"] == "RLC-E025_TIMELINE"
    assert result["markers_applied"] == 1


def test_add_markers_tool_with_override(tmp_path):
    m = make_managers(tmp_path)
    m["resolve"].duplicate_project("RLC-E025_MASTER", "RLC_MASTER_TEMPLATE")
    timeline_tools._build_timeline(m["timeline"], "RLC-E025_MASTER", "RLC-E025")

    result = timeline_tools._add_markers(
        m["timeline"],
        "RLC-E025_MASTER",
        "RLC-E025_TIMELINE",
        markers=[{"frame": 100, "color": "Red", "name": "Custom"}],
    )
    assert result["success"] is True
    assert result["markers_applied"] == 1


def test_place_clips_tool_delegates_and_serializes_result():
    builder = Mock()
    builder.place_clips.return_value = ["item-1", "item-2"]
    clip_ids = ["clip-b", "clip-a"]

    result = timeline_tools._place_clips(builder, "RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)

    builder.place_clips.assert_called_once_with(
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        clip_ids=clip_ids,
    )
    assert result == {
        "success": True,
        "project_name": "RLC-E025_MASTER",
        "timeline_name": "RLC-E025_TIMELINE",
        "clip_ids": ["clip-b", "clip-a"],
        "timeline_item_ids": ["item-1", "item-2"],
        "placed_count": 2,
    }


def test_place_clips_tool_preserves_empty_clip_list_builder_policy():
    builder = Mock()
    builder.place_clips.return_value = []

    result = timeline_tools._place_clips(builder, "RLC-E025_MASTER", "RLC-E025_TIMELINE", [])

    builder.place_clips.assert_called_once_with(
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        clip_ids=[],
    )
    assert result["timeline_item_ids"] == []
    assert result["placed_count"] == 0


@pytest.mark.parametrize(
    ("project_name", "timeline_name", "clip_ids"),
    [
        ("", "RLC-E025_TIMELINE", ["clip-1"]),
        ("RLC-E025_MASTER", "", ["clip-1"]),
        ("RLC-E025_MASTER", "RLC-E025_TIMELINE", "clip-1"),
        ("RLC-E025_MASTER", "RLC-E025_TIMELINE", ["clip-1", ""]),
        ("RLC-E025_MASTER", "RLC-E025_TIMELINE", ["clip-1", 123]),
    ],
)
def test_place_clips_tool_rejects_malformed_transport_shape(project_name, timeline_name, clip_ids):
    builder = Mock()

    with pytest.raises(ValueError):
        timeline_tools._place_clips(builder, project_name, timeline_name, clip_ids)

    builder.place_clips.assert_not_called()


def test_place_clips_tool_propagates_timeline_domain_exceptions():
    builder = Mock()
    builder.place_clips.side_effect = TimelineOperationError("Timeline missing")

    with pytest.raises(TimelineOperationError, match="Timeline missing"):
        timeline_tools._place_clips(builder, "RLC-E025_MASTER", "RLC-E025_TIMELINE", ["clip-1"])


def test_place_clips_tool_is_registered_without_direct_adapter_dependency():
    builder = Mock()
    builder.place_clips.return_value = ["item-1"]

    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorate(func):
                self.tools[func.__name__] = func
                return func

            return decorate

    class FakeContext:
        timeline_builder = builder

    mcp = FakeMCP()
    timeline_tools.register(mcp, FakeContext())

    assert "place_clips" in mcp.tools
    result = mcp.tools["place_clips"]("RLC-E025_MASTER", "RLC-E025_TIMELINE", ["clip-1"])
    assert result["timeline_item_ids"] == ["item-1"]
    builder.place_clips.assert_called_once_with(
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        clip_ids=["clip-1"],
    )


# -- render_tools ---------------------------------------------------------------

def _create_and_prep_episode(m, tmp_path):
    """Shared setup: create episode 25 via the real episode tool + mock project."""
    episode_tools._create_episode(m["episode"], 25)


def test_queue_render_tool_success(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)

    result = render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")
    assert result["success"] is True
    assert result["job"]["status"] == "queued"
    assert result["job"]["resolve_job_id"] is not None


def test_queue_render_tool_unknown_preset(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)

    result = render_tools._queue_render(m["render"], "RLC-E025", "does_not_exist")
    assert result["success"] is False


def test_get_render_status_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)
    queued = render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")
    job_id = queued["job"]["id"]

    m["resolve"].simulate_render_complete(queued["job"]["resolve_job_id"])
    result = render_tools._get_render_status(m["render"], job_id)
    assert result["success"] is True
    assert result["job"]["status"] == "complete"


def test_get_render_status_tool_not_found(tmp_path):
    m = make_managers(tmp_path)
    result = render_tools._get_render_status(m["render"], 999)
    assert result["success"] is False


def test_cancel_render_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)
    queued = render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")

    result = render_tools._cancel_render(m["render"], queued["job"]["id"])
    assert result["success"] is True
    assert result["job"]["status"] == "cancelled"


def test_list_render_jobs_for_episode_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)
    render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")

    result = render_tools._list_render_jobs_for_episode(m["render"], "RLC-E025")
    assert result["success"] is True
    assert len(result["jobs"]) == 1


# -- archive_tools --------------------------------------------------------------

def test_archive_episode_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)

    result = archive_tools._archive_episode(m["archive"], "RLC-E025")
    assert result["success"] is True
    assert result["archive"]["episode_id"] == "RLC-E025"


def test_archive_episode_tool_unknown_episode(tmp_path):
    m = make_managers(tmp_path)
    result = archive_tools._archive_episode(m["archive"], "RLC-E999")
    assert result["success"] is False


def test_list_archives_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)
    archive_tools._archive_episode(m["archive"], "RLC-E025")

    result = archive_tools._list_archives(m["archive"])
    assert result["success"] is True
    assert len(result["archives"]) == 1
