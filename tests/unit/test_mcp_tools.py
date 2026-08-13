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
from redline_core.build.manifest_provenance import persist_manifest_provenance
from redline_core.db.database import Database
from redline_core.db.models import EpisodeStatus, RenderJob, RenderJobStatus
from redline_core.episode.exceptions import EpisodeBuildError
from redline_core.episode.manager import EpisodeManager
from redline_core.episode.models import EpisodeBuildDefinition, EpisodeBuildResult
from redline_core.manifest import ManifestPathError
from redline_core.manifest.models import ValidatedEpisodePlan, ValidatedMarker
from redline_core.media.manager import MediaManager
from redline_core.render.manager import RenderManager
from redline_core.resolve.exceptions import (
    RenderJobError,
    RenderQueueAcceptanceNotObservedError,
    RenderQueueIdentityUnresolvedError,
    ResolveError,
    TimelineOperationError,
)
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder
from mcp_server.context import build_context

from mcp_server.tools import archive_tools, asset_tools, episode_tools, media_tools, render_tools, timeline_tools


def make_config(tmp_path: Path) -> RedlineConfig:
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    evidence_root = tmp_path / "_evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(
            presets=[
                RenderPreset(
                    name="broadcast_master",
                    resolve_preset_name="Redline Broadcast Master",
                    output_subfolder="exports",
                    filename_template="{episode_id}",
                    file_extension=".mov",
                    collision_policy="reject",
                ),
            ]
        ),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(assets_path),
            master_project_template="RLC_MASTER_TEMPLATE",
            evidence_path=str(evidence_root),
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


def _write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _valid_manifest_body(media_path: str) -> str:
    return f"""\
schema_version: 1
episode:
  id: RLC-E025
assembly:
  bin_name: selects
  media:
    - path: {media_path}
  markers:
    - frame: 0
      color: Blue
      name: Start
      note: Opening
"""


def test_validate_manifest_tool_delegates_exact_path_and_serializes_plan(monkeypatch, tmp_path):
    m = make_managers(tmp_path)
    manifest_path = str(tmp_path / "episode.yaml")
    manifest = object()
    plan = ValidatedEpisodePlan(
        episode_id="RLC-E025",
        bin_name="selects",
        media_paths=("C:/media/clip.wav",),
        markers=(ValidatedMarker(frame=0, color="Blue", name="Start", note="Opening"),),
    )
    load_manifest = Mock(return_value=manifest)
    validate_manifest = Mock(return_value=plan)
    monkeypatch.setattr(episode_tools, "load_manifest", load_manifest)
    monkeypatch.setattr(episode_tools, "validate_episode_manifest", validate_manifest)

    result = episode_tools._validate_manifest(m["config"], manifest_path)

    load_manifest.assert_called_once_with(manifest_path)
    validate_manifest.assert_called_once_with(manifest, manifest_path=manifest_path, config=m["config"])
    assert result == {
        "success": True,
        "manifest_path": manifest_path,
        "valid": True,
        "episode_id": "RLC-E025",
        "bin_name": "selects",
        "media_paths": ["C:/media/clip.wav"],
        "media_count": 1,
        "markers": [{"frame": 0, "color": "Blue", "name": "Start", "note": "Opening"}],
        "marker_count": 1,
    }


def test_validate_manifest_tool_accepts_valid_manifest(tmp_path):
    m = make_managers(tmp_path)
    ingest = Path(m["config"].paths.ingest_path)
    ingest.mkdir()
    media_file = ingest / "clip.wav"
    media_file.write_bytes(b"x")
    manifest_path = _write_manifest(tmp_path / "episode.yaml", _valid_manifest_body(str(media_file)))

    result = episode_tools._validate_manifest(m["config"], str(manifest_path))

    assert result["success"] is True
    assert result["valid"] is True
    assert result["episode_id"] == "RLC-E025"
    assert result["bin_name"] == "selects"
    assert result["media_paths"] == [str(media_file.resolve())]
    assert result["media_count"] == 1
    assert result["markers"] == [{"frame": 0, "color": "Blue", "name": "Start", "note": "Opening"}]
    assert result["marker_count"] == 1


@pytest.mark.parametrize(
    "body, expected",
    [
        ("schema_version: 1\n  bad: true\n", "YAML parse failed"),
        ("schema_version: 1\nschema_version: 1\n", "duplicate key"),
        ("schema_version: 1\nepisode:\n  id: RLC-E025\nassembly:\n  media: []\n", "schema validation failed"),
    ],
)
def test_validate_manifest_tool_returns_structured_manifest_failures(tmp_path, body, expected):
    m = make_managers(tmp_path)
    manifest_path = _write_manifest(tmp_path / "episode.yaml", body)

    result = episode_tools._validate_manifest(m["config"], str(manifest_path))

    assert result["success"] is False
    assert expected in result["error"]


def test_validate_manifest_tool_missing_manifest_is_structured_failure(tmp_path):
    m = make_managers(tmp_path)

    result = episode_tools._validate_manifest(m["config"], str(tmp_path / "missing.yaml"))

    assert result["success"] is False
    assert "unable to read manifest file" in result["error"]


def test_validate_manifest_tool_path_containment_violation_is_structured_failure(tmp_path):
    m = make_managers(tmp_path)
    ingest = Path(m["config"].paths.ingest_path)
    ingest.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    manifest_path = _write_manifest(tmp_path / "episode.yaml", _valid_manifest_body(str(outside)))

    result = episode_tools._validate_manifest(m["config"], str(manifest_path))

    assert result["success"] is False
    assert "outside approved media roots" in result["error"]


def test_validate_manifest_tool_unc_path_behavior_follows_manifest_policy(tmp_path):
    m = make_managers(tmp_path)
    manifest_path = _write_manifest(
        tmp_path / "episode.yaml",
        _valid_manifest_body(r"\\unapproved-server\share\clip.mov"),
    )

    result = episode_tools._validate_manifest(m["config"], str(manifest_path))

    assert result["success"] is False
    assert result["error"]


def test_validate_manifest_tool_rejects_malformed_transport_shape(tmp_path):
    m = make_managers(tmp_path)

    with pytest.raises(ValueError):
        episode_tools._validate_manifest(m["config"], "")


def test_validate_manifest_tool_propagates_unexpected_errors(monkeypatch, tmp_path):
    m = make_managers(tmp_path)
    monkeypatch.setattr(episode_tools, "load_manifest", Mock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        episode_tools._validate_manifest(m["config"], str(tmp_path / "episode.yaml"))


def test_validate_manifest_tool_is_registered_without_manager_database_or_resolve_dependency(tmp_path):
    m = make_managers(tmp_path)
    marker_plan = ValidatedEpisodePlan(episode_id="RLC-E025", media_paths=(), markers=())
    builder = Mock(return_value=object())
    validator = Mock(return_value=marker_plan)

    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorate(func):
                self.tools[func.__name__] = func
                return func

            return decorate

    class FakeContext:
        config = m["config"]
        episode_manager = Mock()

    original_loader = episode_tools.load_manifest
    original_validator = episode_tools.validate_episode_manifest
    try:
        episode_tools.load_manifest = builder
        episode_tools.validate_episode_manifest = validator
        mcp = FakeMCP()
        episode_tools.register(mcp, FakeContext())

        assert "validate_manifest" in mcp.tools
        result = mcp.tools["validate_manifest"]("episode.yaml")
    finally:
        episode_tools.load_manifest = original_loader
        episode_tools.validate_episode_manifest = original_validator

    assert result["success"] is True
    FakeContext.episode_manager.assert_not_called()
    builder.assert_called_once_with("episode.yaml")
    validator.assert_called_once()


def test_validate_manifest_tool_translates_manifest_exception(monkeypatch, tmp_path):
    m = make_managers(tmp_path)
    monkeypatch.setattr(episode_tools, "load_manifest", Mock(side_effect=ManifestPathError("bad path")))

    result = episode_tools._validate_manifest(m["config"], str(tmp_path / "episode.yaml"))

    assert result == {"success": False, "error": "bad path"}


def _build_result() -> EpisodeBuildResult:
    return EpisodeBuildResult(
        episode_id="RLC-E025",
        project_name="RLC-E025_MASTER",
        timeline_id="timeline-id",
        timeline_name="RLC-E025_TIMELINE",
        media_paths=["C:/media/a.wav", "C:/media/b.png"],
        media_ids=["clip-a", "clip-b"],
        markers_applied=1,
        timeline_item_ids=["item-a", "item-b"],
        video_item_count=1,
    )


def test_assemble_episode_tool_delegates_once_and_serializes_result():
    manager = Mock()
    manager.build_episode.return_value = _build_result()
    markers = [{"frame": 0, "color": "Blue", "name": "Start", "note": "Opening"}]

    result = episode_tools._assemble_episode(
        manager,
        "RLC-E025",
        ["C:/media/a.wav", "C:/media/b.png"],
        markers=markers,
        bin_name="selects",
        allow_unsafe_retry=True,
    )

    manager.build_episode.assert_called_once()
    definition = manager.build_episode.call_args.args[0]
    assert definition == EpisodeBuildDefinition(
        episode_id="RLC-E025",
        media_paths=["C:/media/a.wav", "C:/media/b.png"],
        markers=[MarkerDefinition(frame=0, color="Blue", name="Start", note="Opening")],
        bin_name="selects",
    )
    assert manager.build_episode.call_args.kwargs == {"allow_unsafe_retry": True}
    assert result == {
        "success": True,
        "episode_id": "RLC-E025",
        "project_name": "RLC-E025_MASTER",
        "timeline_name": "RLC-E025_TIMELINE",
        "media_paths": ["C:/media/a.wav", "C:/media/b.png"],
        "media_ids": ["clip-a", "clip-b"],
        "markers_applied": 1,
        "timeline_item_ids": ["item-a", "item-b"],
    }


def test_assemble_episode_tool_forwards_default_optional_arguments():
    manager = Mock()
    manager.build_episode.return_value = _build_result()

    episode_tools._assemble_episode(manager, "RLC-E025", ["C:/media/a.wav"])

    definition = manager.build_episode.call_args.args[0]
    assert definition == EpisodeBuildDefinition(
        episode_id="RLC-E025",
        media_paths=["C:/media/a.wav"],
        markers=[],
        bin_name="footage",
    )
    assert manager.build_episode.call_args.kwargs == {"allow_unsafe_retry": False}


@pytest.mark.parametrize(
    ("episode_id", "media_paths", "markers", "bin_name", "allow_unsafe_retry"),
    [
        ("", ["C:/media/a.wav"], None, "footage", False),
        ("RLC-E025", "C:/media/a.wav", None, "footage", False),
        ("RLC-E025", ["C:/media/a.wav"], {}, "footage", False),
        ("RLC-E025", ["C:/media/a.wav"], None, "", False),
        ("RLC-E025", ["C:/media/a.wav"], None, "footage", "yes"),
    ],
)
def test_assemble_episode_tool_rejects_malformed_transport_shape(
    episode_id, media_paths, markers, bin_name, allow_unsafe_retry
):
    manager = Mock()

    with pytest.raises(ValueError):
        episode_tools._assemble_episode(
            manager,
            episode_id,
            media_paths,
            markers=markers,
            bin_name=bin_name,
            allow_unsafe_retry=allow_unsafe_retry,
        )

    manager.build_episode.assert_not_called()


def test_assemble_episode_tool_returns_structured_episode_build_failure():
    manager = Mock()
    manager.build_episode.side_effect = EpisodeBuildError(
        "Episode RLC-E025 is already assembled.",
        stage="episode_lookup",
        episode_id="RLC-E025",
    )

    result = episode_tools._assemble_episode(manager, "RLC-E025", ["C:/media/a.wav"])

    assert result == {"success": False, "error": "Episode RLC-E025 is already assembled."}


def test_assemble_episode_tool_propagates_unexpected_errors():
    manager = Mock()
    manager.build_episode.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        episode_tools._assemble_episode(manager, "RLC-E025", ["C:/media/a.wav"])


def test_assemble_episode_tool_does_not_call_manifest_loader(monkeypatch):
    manager = Mock()
    manager.build_episode.return_value = _build_result()
    loader = Mock(side_effect=AssertionError("manifest loader should not be called"))
    validator = Mock(side_effect=AssertionError("manifest validator should not be called"))
    monkeypatch.setattr(episode_tools, "load_manifest", loader)
    monkeypatch.setattr(episode_tools, "validate_episode_manifest", validator)

    result = episode_tools._assemble_episode(manager, "RLC-E025", ["C:/media/a.wav"])

    assert result["success"] is True
    loader.assert_not_called()
    validator.assert_not_called()
    manager.build_episode.assert_called_once()


def test_assemble_episode_tool_is_registered_without_subordinate_manager_calls():
    episode_manager = Mock()
    episode_manager.build_episode.return_value = _build_result()

    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorate(func):
                self.tools[func.__name__] = func
                return func

            return decorate

    class FakeContext:
        pass

    FakeContext.episode_manager = episode_manager
    FakeContext.media_manager = Mock()
    FakeContext.timeline_builder = Mock()
    FakeContext.render_manager = Mock()
    FakeContext.db = Mock()
    FakeContext.resolve = Mock()
    FakeContext.config = Mock()

    mcp = FakeMCP()
    episode_tools.register(mcp, FakeContext())

    assert "assemble_episode" in mcp.tools
    result = mcp.tools["assemble_episode"]("RLC-E025", ["C:/media/a.wav"], allow_unsafe_retry=True)

    assert result["success"] is True
    episode_manager.build_episode.assert_called_once()
    FakeContext.media_manager.assert_not_called()
    FakeContext.timeline_builder.assert_not_called()
    FakeContext.render_manager.assert_not_called()
    FakeContext.db.assert_not_called()
    FakeContext.resolve.assert_not_called()


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
    m["resolve"].build_timeline("RLC-E025_MASTER", "RLC-E025_TIMELINE")


def _create_and_render_episode(m, tmp_path):
    """Extends _create_and_prep_episode(): also records a real, complete
    render job and canonical manifest provenance (Phase 15 Mission 15E.2)
    so the episode is Rev1-eligible for
    ArchiveManager.create_archive()/archive_episode(). Seeds the DB/
    filesystem directly rather than driving the full RenderManager/
    Resolve queue-and-complete flow -- consistent with this suite's
    existing style of direct-DB fixture setup elsewhere."""
    _create_and_prep_episode(m, tmp_path)
    episode = m["db"].get_episode_by_episode_id("RLC-E025")
    output_path = Path(episode.folder_path) / "exports" / "RLC-E025_MASTER.mov"
    output_path.write_bytes(b"rendered-master-bytes")
    m["db"].create_render_job(
        "RLC-E025",
        "broadcast_master",
        resolve_job_id="resolve-RLC-E025",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        output_path=str(output_path),
        status=RenderJobStatus.COMPLETE,
    )
    m["db"].update_episode_status("RLC-E025", EpisodeStatus.RENDERED)

    ingest_file = tmp_path / "_ingest" / "RLC-E025" / "camera.mov"
    ingest_file.parent.mkdir(parents=True, exist_ok=True)
    ingest_file.write_bytes(b"ingest-bytes")
    asset_file = tmp_path / "_assets" / "graphics" / "RLC-E025_logo.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"asset-bytes")

    manifest_src = tmp_path / "_source_manifests" / "RLC-E025.yaml"
    manifest_src.parent.mkdir(parents=True, exist_ok=True)
    manifest_src.write_text("schema_version: 1\nepisode:\n  id: RLC-E025\n", encoding="utf-8", newline="")
    plan = ValidatedEpisodePlan(episode_id="RLC-E025", media_paths=(str(ingest_file), str(asset_file)))
    persist_manifest_provenance(
        original_manifest_path=manifest_src, plan=plan, config=m["config"], episode_folder_path=Path(episode.folder_path)
    )


def test_queue_render_tool_success(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)

    result = render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")
    assert result["success"] is True
    assert result["job"]["status"] == "queued"
    assert result["job"]["resolve_job_id"] is not None
    assert result["job"]["project_name"] == "RLC-E025_MASTER"
    assert result["job"]["timeline_name"] == "RLC-E025_TIMELINE"


def test_render_job_serialization_includes_project_and_timeline_names():
    job = RenderJob(
        id=7,
        episode_id="RLC-E025",
        preset_name="broadcast_master",
        project_name="RLC-E025_MASTER",
        timeline_name="RLC-E025_TIMELINE",
        resolve_job_id="resolve-7",
        status=RenderJobStatus.QUEUED,
        output_path="C:/renders/RLC-E025.mov",
    )

    result = render_tools._job_to_dict(job)

    assert result["project_name"] == "RLC-E025_MASTER"
    assert result["timeline_name"] == "RLC-E025_TIMELINE"


def test_queue_render_tool_unknown_preset(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)

    result = render_tools._queue_render(m["render"], "RLC-E025", "does_not_exist")
    assert result["success"] is False


def test_queue_render_tool_returns_structured_resolve_error():
    manager = Mock()
    manager.queue_render.side_effect = RenderJobError("Resolve queue failed")

    result = render_tools._queue_render(manager, "RLC-E025", "broadcast_master")

    assert result == {
        "success": False,
        "category": "render queue failed",
        "error": "Resolve queue failed",
    }


def test_queue_render_tool_maps_acceptance_not_observed_category():
    manager = Mock()
    manager.queue_render.side_effect = RenderQueueAcceptanceNotObservedError("No accepted render job observed")

    result = render_tools._queue_render(manager, "RLC-E025", "broadcast_master")

    assert result == {
        "success": False,
        "category": "render queue acceptance not observed",
        "error": "No accepted render job observed",
    }


def test_queue_render_tool_maps_identity_unresolved_category():
    manager = Mock()
    manager.queue_render.side_effect = RenderQueueIdentityUnresolvedError("Resolve job identity unresolved")

    result = render_tools._queue_render(manager, "RLC-E025", "broadcast_master")

    assert result == {
        "success": False,
        "category": "render queue identity unresolved",
        "error": "Resolve job identity unresolved",
    }


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


def test_get_render_status_tool_returns_structured_resolve_error():
    manager = Mock()
    manager.get_render_status.side_effect = ResolveError("Resolve status failed")

    result = render_tools._get_render_status(manager, 7)

    assert result == {"success": False, "error": "Resolve status failed"}


def test_cancel_render_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)
    queued = render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")

    result = render_tools._cancel_render(m["render"], queued["job"]["id"])
    assert result["success"] is True
    assert result["job"]["status"] == "cancelled"


def test_cancel_render_tool_returns_structured_resolve_error():
    manager = Mock()
    manager.cancel_render.side_effect = ResolveError("Resolve cancel failed")

    result = render_tools._cancel_render(manager, 7)

    assert result == {"success": False, "error": "Resolve cancel failed"}


def test_list_render_jobs_for_episode_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_prep_episode(m, tmp_path)
    render_tools._queue_render(m["render"], "RLC-E025", "broadcast_master")

    result = render_tools._list_render_jobs_for_episode(m["render"], "RLC-E025")
    assert result["success"] is True
    assert len(result["jobs"]) == 1


# -- archive_tools --------------------------------------------------------------
#
# Phase 15 Mission 15F: canonical archive_create/archive_verify tools calling
# ArchiveManager.create_archive()/verify_archive() directly. The legacy
# archive_episode tool (a thin wrapper over the now-retired
# ArchiveManager.archive_episode() bridge) is no longer registered at all --
# test_archive_tools_register_exposes_exactly_the_canonical_set() proves it.


def test_archive_create_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)

    result = archive_tools._archive_create(m["archive"], "RLC-E025")
    assert result["success"] is True
    assert result["archive"]["episode_id"] == "RLC-E025"
    assert result["archive"]["archive_id"] is not None
    assert result["archive"]["status"] == "complete"


def test_archive_create_tool_unknown_episode(tmp_path):
    m = make_managers(tmp_path)
    result = archive_tools._archive_create(m["archive"], "RLC-E999")
    assert result["success"] is False
    assert result["classification"] == "error"


def test_archive_create_tool_passes_render_job_id_and_manifest_path_through(tmp_path):
    """The MCP tool must not reimplement render selection or provenance
    fallback -- both parameters are passed straight to
    ArchiveManager.create_archive()."""
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    episode = m["db"].get_episode_by_episode_id("RLC-E025")
    render_job = m["db"].list_render_jobs_for_episode("RLC-E025")[0]

    result = archive_tools._archive_create(m["archive"], "RLC-E025", render_job.id, None)

    assert result["success"] is True
    assert result["archive"]["render_job_id"] == render_job.id


def test_archive_create_tool_verified_unregistered_is_classified_distinctly(tmp_path, monkeypatch):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)

    from redline_core.db.database import ArchiveCommitError

    def _forced_failure(*args, **kwargs):
        raise ArchiveCommitError("simulated DB commit failure")

    monkeypatch.setattr(m["db"], "commit_verified_archive", _forced_failure)

    result = archive_tools._archive_create(m["archive"], "RLC-E025")

    assert result["success"] is False
    assert result["classification"] == "verified_unregistered"
    assert Path(result["archive_path"]).is_dir()


def test_archive_verify_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    archive_tools._archive_create(m["archive"], "RLC-E025")

    result = archive_tools._archive_verify(m["archive"], "RLC-E025")

    assert result["success"] is True
    assert result["verification"]["episode_id"] == "RLC-E025"
    assert result["verification"]["verified"] is True


def test_archive_verify_tool_no_archive_row(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)

    result = archive_tools._archive_verify(m["archive"], "RLC-E025")

    assert result["success"] is False


def test_list_archives_tool(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    archive_tools._archive_create(m["archive"], "RLC-E025")

    result = archive_tools._list_archives(m["archive"])
    assert result["success"] is True
    assert len(result["archives"]) == 1


class _FakeMCP:
    """Minimal `mcp.server.fastmcp.FastMCP.tool()` stand-in -- matches the
    identical pattern `test_validate_manifest_tool_is_registered_...`
    already uses above, so archive_tools.register() can be exercised
    without the optional `mcp` extra installed."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorate(func):
            self.tools[func.__name__] = func
            return func

        return decorate


def test_archive_tools_register_exposes_exactly_the_canonical_set(tmp_path):
    """Phase 15 Mission 15F/15H: the registered archive tool set is
    exactly {archive_create, archive_verify, list_archives, archive_recover}
    -- the legacy archive_episode tool must not be registered/exposed, and
    no canonical tool is missing."""
    m = make_managers(tmp_path)

    class FakeContext:
        archive_manager = m["archive"]

    mcp = _FakeMCP()
    archive_tools.register(mcp, FakeContext())

    assert set(mcp.tools.keys()) == {"archive_create", "archive_verify", "list_archives", "archive_recover"}


def test_archive_tools_registered_create_tool_calls_manager(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)

    class FakeContext:
        archive_manager = m["archive"]

    mcp = _FakeMCP()
    archive_tools.register(mcp, FakeContext())

    result = mcp.tools["archive_create"]("RLC-E025")

    assert result["success"] is True


def test_archive_tools_registered_verify_tool_calls_manager(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    m["archive"].create_archive("RLC-E025")

    class FakeContext:
        archive_manager = m["archive"]

    mcp = _FakeMCP()
    archive_tools.register(mcp, FakeContext())

    result = mcp.tools["archive_verify"]("RLC-E025")

    assert result["success"] is True
    assert result["verification"]["verified"] is True


def _force_verified_unregistered_mcp(m, episode_id: str) -> dict:
    """Phase 15 Mission 15H: force a real archive_create MCP call through
    to VERIFIED_UNREGISTERED by injecting a DB commit failure after
    publication."""
    from redline_core.db.database import ArchiveCommitError

    original_commit = m["db"].commit_verified_archive

    def _raise_commit_error(**kwargs):
        raise ArchiveCommitError("simulated database failure after publication")

    m["db"].commit_verified_archive = _raise_commit_error
    try:
        result = archive_tools._archive_create(m["archive"], episode_id)
    finally:
        m["db"].commit_verified_archive = original_commit
    assert result["success"] is False
    assert result["classification"] == "verified_unregistered"
    return result


def test_archive_tools_registered_recover_tool_calls_manager(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    unregistered = _force_verified_unregistered_mcp(m, "RLC-E025")

    class FakeContext:
        archive_manager = m["archive"]

    mcp = _FakeMCP()
    archive_tools.register(mcp, FakeContext())

    result = mcp.tools["archive_recover"]("RLC-E025", unregistered["archive_id"])

    assert result["success"] is True
    assert result["recovery"]["classification"] == "recovered"
    assert result["recovery"]["episode_id"] == "RLC-E025"
    assert result["recovery"]["archive_id"] == unregistered["archive_id"]


def test_archive_recover_structured_success_result(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    unregistered = _force_verified_unregistered_mcp(m, "RLC-E025")

    result = archive_tools._archive_recover(m["archive"], "RLC-E025", unregistered["archive_id"])

    assert result["success"] is True
    recovery = result["recovery"]
    assert set(recovery.keys()) == {
        "episode_id",
        "archive_id",
        "archive_path",
        "manifest_sha256",
        "render_job_id",
        "classification",
    }


def test_archive_recover_structured_failure_result(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)

    result = archive_tools._archive_recover(m["archive"], "RLC-E025", "RLC-E025-a1-000000000000")

    assert result["success"] is False
    assert "classification" in result
    assert "error" in result


def test_archive_recover_second_call_already_registered(tmp_path):
    m = make_managers(tmp_path)
    _create_and_render_episode(m, tmp_path)
    unregistered = _force_verified_unregistered_mcp(m, "RLC-E025")

    first = archive_tools._archive_recover(m["archive"], "RLC-E025", unregistered["archive_id"])
    second = archive_tools._archive_recover(m["archive"], "RLC-E025", unregistered["archive_id"])

    assert first["success"] is True and first["recovery"]["classification"] == "recovered"
    assert second["success"] is True and second["recovery"]["classification"] == "already_registered"
