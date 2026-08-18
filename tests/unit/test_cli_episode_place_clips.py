"""Tests for the CLI's `episode place-clips <episode_number> [clip_id ...]` command.

A thin, mutating wrapper over the existing, already-tested
TimelineBuilder.place_clips(), routed through ApplicationServices (full
DB + Resolve runtime, same as every other `episode` action).
episode_number is resolved via the same get_episode_status() call every
other episode action uses; timeline_name is resolved via the pure
TimelineBuilder.timeline_name_for_episode() helper added in Mission 11A —
never by calling build_timeline_for_episode() again, which would silently
re-apply (duplicate) markers as an unrelated side effect. clip_ids are
passed through unchanged; zero clip IDs is a successful no-op, matching
the existing manager/adapter contract rather than inventing new CLI
behavior.

No manager-level tests are added here — place_clips() and
timeline_name_for_episode() both already have complete, independent
coverage from Missions 10 and 11A. This file is CLI transport coverage
only.
"""
from pathlib import Path

import pytest
import yaml

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
from redline_core.db.database import Database
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.resolve.exceptions import ProjectNotFoundError, TimelineOperationError
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder

from cli import main as cli_main
from cli.episode_commands import (
    _print_episode_place_clips_result,
    _run_episode_organize_bins,
    _run_episode_place_clips,
)
from cli.main import _build_parser


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
        assets=AssetsConfig(assets=[], required_for_episode=[]),
        timeline=TimelineTemplateConfig(
            timeline_name_pattern="{episode_id}_TIMELINE",
            markers=[MarkerDefinition(frame=0, color="Blue", name="Cold Open")],
        ),
    )


def make_services(tmp_path):
    config = make_config(tmp_path)
    db = Database(tmp_path / "cli_test.db").connect()
    db.init_schema()
    resolve = MockResolveAdapter()
    resolve.connect()
    media = MediaManager(config, resolve)
    timeline = TimelineBuilder(config, resolve)
    episode_manager = EpisodeManager(config, db, resolve, media, timeline)

    class _Services:
        pass

    services = _Services()
    services.config = config
    services.db = db
    services.resolve = resolve
    services.episode_manager = episode_manager
    services.media_manager = media
    services.timeline_builder = timeline
    return services


def seed_episode_with_built_timeline(services, episode_number: int = 25) -> None:
    """Deterministic setup mechanism used by every test in this file that
    needs a real timeline to place clips onto: create the episode, then
    build its timeline for real (through the same TimelineBuilder the CLI
    action itself uses), so `timeline_name_for_episode()`'s returned name
    actually exists in the mock's Resolve state.
    """
    services.episode_manager.create_episode(episode_number)
    episode = services.episode_manager.get_episode_status(episode_number)
    services.timeline_builder.build_timeline_for_episode(episode.project_name, episode.episode_id)


def seed_episode_with_clips(services, tmp_path: Path, episode_number: int = 25) -> list[str]:
    """The one deterministic source of real mock clip IDs used throughout
    this file: create the episode, build its timeline, drop a matching
    ingest file, then run the CLI's own `organize-bins` action to import
    it — returning the real clip_ids MockResolveAdapter assigned. No
    alternative "manual clip import" path is used anywhere in this file.
    """
    seed_episode_with_built_timeline(services, episode_number)
    ingest = Path(services.config.paths.ingest_path)
    ingest.mkdir(parents=True, exist_ok=True)
    episode_id = services.config.naming.episode_id_pattern.format(episode_number=episode_number)
    (ingest / f"{episode_id}_camA_001.mov").write_bytes(b"x")
    (ingest / f"{episode_id}_camB_001.mov").write_bytes(b"x")

    organize_result = _run_episode_organize_bins(services, episode_number, "footage")
    assert organize_result["success"] is True
    assert organize_result["clip_count"] == 2
    return organize_result["clip_ids"]


# -- _run_episode_place_clips ---------------------------------------------------------

def test_run_place_clips_success(tmp_path):
    services = make_services(tmp_path)
    clip_ids = seed_episode_with_clips(services, tmp_path)

    result = _run_episode_place_clips(services, 25, clip_ids)

    assert result["success"] is True
    assert result["episode_id"] == "RLC-E025"
    assert result["project_name"] == "RLC-E025_MASTER"
    assert result["timeline_name"] == "RLC-E025_TIMELINE"
    assert result["clip_ids"] == clip_ids
    assert result["placed_count"] == 2
    assert len(result["timeline_item_ids"]) == 2


def test_run_place_clips_zero_clip_ids_is_success(tmp_path):
    services = make_services(tmp_path)
    seed_episode_with_built_timeline(services)

    result = _run_episode_place_clips(services, 25, [])

    assert result["success"] is True
    assert result["placed_count"] == 0
    assert result["clip_ids"] == []
    assert result["timeline_item_ids"] == []


def test_run_place_clips_unknown_episode(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_place_clips(services, 999, ["clip-1"])

    assert result["success"] is False
    assert "999" in result["error"]


def test_run_place_clips_timeline_not_found(tmp_path):
    """place-clips called before build-timeline: the episode and project
    exist, but no timeline has ever been built, so
    TimelineBuilder.place_clips() (via the adapter) raises
    TimelineOperationError, passed through unchanged."""
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    result = _run_episode_place_clips(services, 25, ["clip-1"])

    assert result["success"] is False
    assert "RLC-E025_TIMELINE" in result["error"]


def test_run_place_clips_project_not_found_passthrough(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    seed_episode_with_built_timeline(services)

    def _boom(self, project_name, timeline_name, clip_ids):
        raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

    monkeypatch.setattr(MockResolveAdapter, "place_clips", _boom)

    result = _run_episode_place_clips(services, 25, ["clip-1"])

    assert result["success"] is False
    assert "RLC-E025_MASTER" in result["error"]


def test_run_place_clips_manager_receives_resolved_arguments_unchanged(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    clip_ids = seed_episode_with_clips(services, tmp_path)

    calls = []
    original = TimelineBuilder.place_clips

    def _spy(self, project_name, timeline_name, passed_clip_ids):
        calls.append((project_name, timeline_name, list(passed_clip_ids)))
        return original(self, project_name, timeline_name, passed_clip_ids)

    monkeypatch.setattr(TimelineBuilder, "place_clips", _spy)

    _run_episode_place_clips(services, 25, clip_ids)

    assert calls == [("RLC-E025_MASTER", "RLC-E025_TIMELINE", clip_ids)]


# -- _print_episode_place_clips_result --------------------------------------------

def test_print_place_clips_result_with_placements(capsys):
    _print_episode_place_clips_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "timeline_name": "RLC-E025_TIMELINE",
            "clip_ids": ["clip-1", "clip-2"],
            "timeline_item_ids": ["item-1", "item-2"],
            "placed_count": 2,
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "RLC-E025_TIMELINE" in out
    assert "Clips placed:  2" in out
    assert "clip-1 -> item-1" in out
    assert "clip-2 -> item-2" in out


def test_print_place_clips_result_zero_placements(capsys):
    _print_episode_place_clips_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "timeline_name": "RLC-E025_TIMELINE",
            "clip_ids": [],
            "timeline_item_ids": [],
            "placed_count": 0,
        }
    )

    out = capsys.readouterr().out
    assert "Clips placed:  0" in out
    assert "->" not in out


def test_print_place_clips_result_failure(capsys):
    _print_episode_place_clips_result(
        {"success": False, "error": "Timeline 'RLC-E025_TIMELINE' not found in project 'RLC-E025_MASTER'."}
    )

    out = capsys.readouterr().out
    assert "Place clips failed:" in out
    assert "RLC-E025_TIMELINE" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_place_clips_parses_episode_number_and_clip_ids():
    parser = _build_parser()
    args = parser.parse_args(["episode", "place-clips", "25", "clip-2", "clip-1"])
    assert args.resource == "episode"
    assert args.action == "place-clips"
    assert args.episode_number == 25
    assert args.clip_ids == ["clip-2", "clip-1"]


def test_parser_place_clips_allows_zero_clip_ids():
    parser = _build_parser()
    args = parser.parse_args(["episode", "place-clips", "25"])
    assert args.clip_ids == []


def test_parser_place_clips_rejects_non_integer_episode_number():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["episode", "place-clips", "not-a-number", "clip-1"])


# -- main() end-to-end, via env-var injection ----------------------------------

def write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    (config_dir / "naming.yaml").write_text(
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    )
    (config_dir / "folder_structure.yaml").write_text(
        yaml.safe_dump({"root_path": str(tmp_path / "_episodes")})
    )
    (config_dir / "render_presets.yaml").write_text("presets: []\n")
    (config_dir / "paths.yaml").write_text(
        yaml.safe_dump(
            {
                "ingest_path": str(tmp_path / "_ingest"),
                "archive_path": str(tmp_path / "_archive"),
                "assets_path": str(assets_path),
                "master_project_template": "RLC_MASTER_TEMPLATE",
            }
        )
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n")
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\n'
        "markers:\n"
        '  - frame: 0\n    color: "Blue"\n    name: "Cold Open"\n'
    )
    return config_dir


def test_main_place_clips_end_to_end(tmp_path, monkeypatch, capsys):
    """In-process smoke test: main() builds a fresh MockResolveAdapter on
    every invocation, so this shares one instance across the full
    create -> build-timeline -> organize-bins -> place-clips sequence, the
    same technique established in Missions 9-10 for cross-invocation
    Resolve state. The clip IDs placed are the real ones organize-bins
    reports, not invented — the deterministic single source of clip IDs
    for this whole file.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    shared_resolve = MockResolveAdapter()
    monkeypatch.setattr(cli_main, "MockResolveAdapter", lambda: shared_resolve)

    cli_main.main(["--mock-resolve", "episode", "create", "25"])
    cli_main.main(["--mock-resolve", "episode", "build-timeline", "25"])

    ingest = tmp_path / "_ingest"
    ingest.mkdir(parents=True, exist_ok=True)
    (ingest / "RLC-E025_camA_001.mov").write_bytes(b"x")
    cli_main.main(["--mock-resolve", "episode", "organize-bins", "25"])

    # Real clip IDs assigned by the shared mock adapter during organize-bins.
    clip_ids = shared_resolve.media["RLC-E025_MASTER"]
    assert clip_ids  # sanity: organize-bins actually imported something

    exit_code = cli_main.main(["--mock-resolve", "episode", "place-clips", "25", *clip_ids])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "Clips placed:  1" in out
    assert "->" in out
