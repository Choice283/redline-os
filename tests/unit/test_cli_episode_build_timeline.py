"""Tests for the CLI's `episode build-timeline <episode_number>` command.

A thin, mutating wrapper over the existing, already-tested
TimelineBuilder.build_timeline_for_episode(), routed through
ApplicationServices (full DB + Resolve runtime, same as every other
`episode` action). episode_number is resolved via the same
get_episode_status() call every other episode action uses; no markers
override is ever passed — TimelineBuilder owns timeline naming and
configured marker selection entirely on its own. Zero configured markers
is a successful result, not an error. No timeline_id is exposed anywhere
in the result or printed output.
"""
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
from redline_core.db.database import Database
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.resolve.exceptions import ProjectNotFoundError, TimelineOperationError
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder

from cli import main as cli_main
from cli.episode_commands import (
    _print_episode_build_timeline_result,
    _run_episode_build_timeline,
)
from cli.main import _build_parser


def make_config(tmp_path: Path, markers=None) -> RedlineConfig:
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
            markers=markers if markers is not None else [
                MarkerDefinition(frame=0, color="Blue", name="Cold Open"),
                MarkerDefinition(frame=1800, color="Yellow", name="Ad Break 1"),
            ],
        ),
    )


def make_services(tmp_path, markers=None):
    config = make_config(tmp_path, markers=markers)
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
    services.timeline_builder = timeline
    return services


# -- _run_episode_build_timeline -----------------------------------------------------

def test_run_build_timeline_success(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    result = _run_episode_build_timeline(services, 25)

    assert result == {
        "success": True,
        "episode_id": "RLC-E025",
        "project_name": "RLC-E025_MASTER",
        "timeline_name": "RLC-E025_TIMELINE",
        "markers_applied": 2,
    }


def test_run_build_timeline_no_timeline_id_in_result(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    result = _run_episode_build_timeline(services, 25)

    assert "timeline_id" not in result


def test_run_build_timeline_zero_configured_markers_is_success(tmp_path):
    services = make_services(tmp_path, markers=[])
    services.episode_manager.create_episode(25)

    result = _run_episode_build_timeline(services, 25)

    assert result["success"] is True
    assert result["markers_applied"] == 0


def test_run_build_timeline_unknown_episode(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_build_timeline(services, 999)

    assert result["success"] is False
    assert "999" in result["error"]


def test_run_build_timeline_project_not_found_passthrough(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    def _boom(self, project_name, timeline_name):
        raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

    monkeypatch.setattr(MockResolveAdapter, "build_timeline", _boom)

    result = _run_episode_build_timeline(services, 25)

    assert result["success"] is False
    assert "RLC-E025_MASTER" in result["error"]


def test_run_build_timeline_timeline_operation_error_passthrough(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    def _boom(self, project_name, timeline_name):
        raise TimelineOperationError("Resolve failed to create timeline.")

    monkeypatch.setattr(MockResolveAdapter, "build_timeline", _boom)

    result = _run_episode_build_timeline(services, 25)

    assert result["success"] is False
    assert "Resolve failed to create timeline." in result["error"]


def test_run_build_timeline_manager_receives_stored_project_name_and_episode_id(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    calls = []
    original = TimelineBuilder.build_timeline_for_episode

    def _spy(self, project_name, episode_id, markers=None):
        calls.append((project_name, episode_id, markers))
        return original(self, project_name, episode_id, markers)

    monkeypatch.setattr(TimelineBuilder, "build_timeline_for_episode", _spy)

    _run_episode_build_timeline(services, 25)

    assert calls == [("RLC-E025_MASTER", "RLC-E025", None)]


# -- _print_episode_build_timeline_result -------------------------------------------

def test_print_build_timeline_result_success(capsys):
    _print_episode_build_timeline_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "timeline_name": "RLC-E025_TIMELINE",
            "markers_applied": 2,
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "RLC-E025_MASTER" in out
    assert "RLC-E025_TIMELINE" in out
    assert "Markers applied:  2" in out
    assert "timeline_id" not in out.lower().replace(" ", "")


def test_print_build_timeline_result_zero_markers(capsys):
    _print_episode_build_timeline_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "timeline_name": "RLC-E025_TIMELINE",
            "markers_applied": 0,
        }
    )

    out = capsys.readouterr().out
    assert "Markers applied:  0" in out
    assert "warning" not in out.lower()


def test_print_build_timeline_result_failure(capsys):
    _print_episode_build_timeline_result({"success": False, "error": "No episode with episode_number=999."})

    out = capsys.readouterr().out
    assert "Build timeline failed:" in out
    assert "999" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_build_timeline_parses_episode_number():
    parser = _build_parser()
    args = parser.parse_args(["episode", "build-timeline", "25"])
    assert args.resource == "episode"
    assert args.action == "build-timeline"
    assert args.episode_number == 25


def test_parser_build_timeline_rejects_non_integer():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["episode", "build-timeline", "not-a-number"])


# -- main() end-to-end, via env-var injection ----------------------------------

def write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    (config_dir / "naming.yaml").write_text(
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    )
    (config_dir / "folder_structure.yaml").write_text(f'root_path: "{tmp_path / "_episodes"}"\n')
    (config_dir / "render_presets.yaml").write_text("presets: []\n")
    (config_dir / "paths.yaml").write_text(
        f'ingest_path: "{tmp_path / "_ingest"}"\n'
        f'archive_path: "{tmp_path / "_archive"}"\n'
        f'assets_path: "{assets_path}"\n'
        'master_project_template: "RLC_MASTER_TEMPLATE"\n'
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n")
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\n'
        "markers:\n"
        '  - frame: 0\n    color: "Blue"\n    name: "Cold Open"\n'
    )
    return config_dir


def test_main_build_timeline_end_to_end(tmp_path, monkeypatch, capsys):
    """Shares one MockResolveAdapter across two main() calls, the same
    technique test_cli_episode_organize_bins.py uses — main() builds a
    fresh mock adapter on every invocation, so a Resolve project created
    by one call doesn't exist for a separately-invoked one.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    shared_resolve = MockResolveAdapter()
    monkeypatch.setattr(cli_main, "MockResolveAdapter", lambda: shared_resolve)

    cli_main.main(["--mock-resolve", "episode", "create", "25"])
    exit_code = cli_main.main(["--mock-resolve", "episode", "build-timeline", "25"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "RLC-E025_TIMELINE" in out
    assert "Markers applied:  1" in out
