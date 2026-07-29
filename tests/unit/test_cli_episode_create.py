"""Tests for the CLI's `episode create` command.

Mirrors the split used everywhere else in this codebase: the underscore
functions in cli.main are plain, testable logic with no argparse/stdout
dependency; main() is exercised end-to-end separately, via env-var
injection, the same way a real `redline episode create N --mock-resolve`
invocation would work.

Every test here uses an in-memory RedlineConfig scoped under tmp_path
(mirroring test_mcp_tools.make_config), never load_config("config") — the
real config/folder_structure.yaml's root_path is a relative "./_episodes",
and create_episode() really creates that folder on disk. Loading the real
config directory in a test that calls create_episode() would write into
the actual repo working tree.
"""
from pathlib import Path

import pytest

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
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder

from cli import main as cli_main
from cli.main import _build_parser, _print_episode_create_result, _run_episode_create


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
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
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
    return services


# -- _run_episode_create -------------------------------------------------------

def test_run_episode_create_success(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_create(services, 42)

    assert result["success"] is True
    assert result["episode"]["episode_id"] == "RLC-E042"
    assert Path(result["episode"]["folder_path"]).is_relative_to(tmp_path)
    assert result["episode"]["project_path"]


def test_run_episode_create_duplicate(tmp_path):
    services = make_services(tmp_path)
    _run_episode_create(services, 42)

    result = _run_episode_create(services, 42)

    assert result["success"] is False
    assert "already exists" in result["error"]


# -- _print_episode_create_result ---------------------------------------------

def test_print_episode_create_result_success(tmp_path, capsys):
    services = make_services(tmp_path)
    result = _run_episode_create(services, 3)

    _print_episode_create_result(result)

    out = capsys.readouterr().out
    assert "Episode: RLC-E003" in out
    assert "Resolve project initialized:" in out
    assert "Resolve project duplicated" not in out
    assert "Episode RLC-E003 is ready." in out


def test_print_episode_create_result_failure(capsys):
    _print_episode_create_result({"success": False, "error": "Episode 3 already exists (episode_id=RLC-E003)."})

    out = capsys.readouterr().out
    assert "Episode creation failed:" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_episode_create_parses_episode_number():
    parser = _build_parser()
    args = parser.parse_args(["episode", "create", "9"])
    assert args.resource == "episode"
    assert args.action == "create"
    assert args.episode_number == 9
    assert args.mock_resolve is False


def test_parser_episode_create_rejects_non_integer():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["episode", "create", "not-a-number"])


def test_parser_mock_resolve_flag():
    parser = _build_parser()
    args = parser.parse_args(["--mock-resolve", "episode", "create", "1"])
    assert args.mock_resolve is True


# -- main() end-to-end, via env-var injection ----------------------------------
#
# These point REDLINE_CONFIG_DIR at a tmp_path-scoped config directory
# (real YAML files, isolated root_path) rather than the repo's real
# config/, since main() genuinely calls create_episode() end to end.

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
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_episode_create_end_to_end(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    exit_code = cli_main.main(["--mock-resolve", "episode", "create", "11"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Episode: RLC-E011" in out
    assert "Episode RLC-E011 is ready." in out
    assert (tmp_path / "_episodes" / "RLC-E011").is_dir()


def test_main_episode_create_duplicate_is_clean_error(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e_dup.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    cli_main.main(["--mock-resolve", "episode", "create", "12"])
    exit_code = cli_main.main(["--mock-resolve", "episode", "create", "12"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Episode creation failed:" in out
    assert "already exists" in out
