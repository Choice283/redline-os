"""Tests for the CLI's `episode list` command.

Read-only wrapper over the existing, already-tested
EpisodeManager.list_episodes(), which has no filtering, pagination, or
alternate ordering of its own (always every episode, by episode_number
ascending) — these tests confirm the CLI doesn't add any either. Same
tmp-path-isolated-config discipline as Missions 1-3.
"""
from pathlib import Path

import yaml

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
from cli.episode_commands import _print_episode_list_result, _run_episode_list
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
    services.media_manager = media
    return services


# -- _run_episode_list -----------------------------------------------------------

def test_run_episode_list_empty(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_list(services)

    assert result["success"] is True
    assert result["episodes"] == []


def test_run_episode_list_returns_all_ordered_by_episode_number(tmp_path):
    services = make_services(tmp_path)
    # Create out of numeric order to prove the CLI doesn't re-sort by
    # creation order or insertion order — it must reflect whatever
    # list_episodes() itself returns (ORDER BY episode_number).
    services.episode_manager.create_episode(3)
    services.episode_manager.create_episode(1)
    services.episode_manager.create_episode(2)

    result = _run_episode_list(services)

    assert result["success"] is True
    assert [e["episode_number"] for e in result["episodes"]] == [1, 2, 3]
    assert [e["episode_id"] for e in result["episodes"]] == ["RLC-E001", "RLC-E002", "RLC-E003"]


def test_run_episode_list_single_episode(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(1)

    result = _run_episode_list(services)

    assert len(result["episodes"]) == 1
    assert result["episodes"][0]["episode_id"] == "RLC-E001"


# -- _print_episode_list_result ---------------------------------------------------

def test_print_episode_list_result_empty(capsys):
    _print_episode_list_result({"success": True, "episodes": []})

    out = capsys.readouterr().out
    assert "No episodes found." in out


def test_print_episode_list_result_multiple(capsys):
    _print_episode_list_result(
        {
            "success": True,
            "episodes": [
                {"episode_id": "RLC-E001", "status": "created", "created_at": "2026-07-29 09:41:18"},
                {"episode_id": "RLC-E002", "status": "created", "created_at": "2026-07-29 10:02:11"},
            ],
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E001" in out
    assert "RLC-E002" in out
    assert "Created" in out
    assert "2 episode(s)." in out


# -- argument parsing -----------------------------------------------------------

def test_parser_episode_list_takes_no_arguments():
    parser = _build_parser()
    args = parser.parse_args(["episode", "list"])
    assert args.resource == "episode"
    assert args.action == "list"


# -- main() end-to-end -----------------------------------------------------------

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
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_episode_list_end_to_end(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    cli_main.main(["--mock-resolve", "episode", "create", "1"])
    cli_main.main(["--mock-resolve", "episode", "create", "2"])
    exit_code = cli_main.main(["--mock-resolve", "episode", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E001" in out
    assert "RLC-E002" in out
    assert "2 episode(s)." in out


def test_main_episode_list_empty_is_success(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e_empty.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    exit_code = cli_main.main(["--mock-resolve", "episode", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No episodes found." in out
