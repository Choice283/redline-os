"""Tests for the CLI's `episode status` command.

Read-only wrapper over the existing, already-tested
EpisodeManager.get_episode_status(), serialized through the shared
_episode_to_dict() helper (extended in this mission to add id/created_at/
updated_at — these tests also cover that extension doesn't disturb the
existing `episode create` output). Same tmp-path-isolated-config discipline
as Missions 1-2.
"""
from pathlib import Path

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
from cli.main import (
    _build_parser,
    _episode_to_dict,
    _print_episode_create_result,
    _print_episode_status_result,
    _run_episode_create,
    _run_episode_status,
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


# -- _episode_to_dict extension -------------------------------------------------

def test_episode_to_dict_includes_new_fields(tmp_path):
    services = make_services(tmp_path)
    episode = services.episode_manager.create_episode(1)

    result = _episode_to_dict(episode)

    assert result["id"] == episode.id
    assert result["created_at"] == episode.created_at
    assert result["updated_at"] == episode.updated_at
    assert isinstance(result["created_at"], str)
    assert isinstance(result["updated_at"], str)


def test_episode_create_output_unaffected_by_new_fields(tmp_path, capsys):
    services = make_services(tmp_path)
    result = _run_episode_create(services, 1)

    _print_episode_create_result(result)

    out = capsys.readouterr().out
    assert "Episode RLC-E001 is ready." in out
    assert "Database ID" not in out  # create's own printer doesn't use the new fields


# -- _run_episode_status ---------------------------------------------------------

def test_run_episode_status_success(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(1)

    result = _run_episode_status(services, 1)

    assert result["success"] is True
    assert result["episode"]["episode_id"] == "RLC-E001"
    assert result["episode"]["status"] == "created"
    assert result["episode"]["id"] is not None
    assert result["episode"]["created_at"]
    assert result["episode"]["updated_at"]


def test_run_episode_status_unknown_episode(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_status(services, 999)

    assert result["success"] is False
    assert "999" in result["error"]


# -- _print_episode_status_result -----------------------------------------------

def test_print_episode_status_result_success(capsys):
    _print_episode_status_result(
        {
            "success": True,
            "episode": {
                "id": 1,
                "episode_id": "RLC-E001",
                "status": "created",
                "folder_path": "/episodes/RLC-E001",
                "project_path": "/mock/projects/RLC-E001_MASTER.drp",
                "created_at": "2026-07-29 09:41:18",
                "updated_at": "2026-07-29 09:41:18",
            },
        }
    )

    out = capsys.readouterr().out
    assert "Episode: RLC-E001" in out
    assert "Status: Created" in out
    assert "Database ID: 1" in out
    assert "Created: 2026-07-29 09:41:18" in out
    assert "Last updated: 2026-07-29 09:41:18" in out


def test_print_episode_status_result_failure(capsys):
    _print_episode_status_result({"success": False, "error": "No episode with episode_number=999."})

    out = capsys.readouterr().out
    assert "Episode status lookup failed:" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_episode_status_parses_episode_number():
    parser = _build_parser()
    args = parser.parse_args(["episode", "status", "1"])
    assert args.resource == "episode"
    assert args.action == "status"
    assert args.episode_number == 1


# -- main() end-to-end -----------------------------------------------------------

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


def test_main_episode_status_end_to_end(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    cli_main.main(["--mock-resolve", "episode", "create", "7"])
    exit_code = cli_main.main(["--mock-resolve", "episode", "status", "7"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Episode: RLC-E007" in out
    assert "Status: Created" in out


def test_main_episode_status_unknown_episode_is_clean_error(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e_missing.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    exit_code = cli_main.main(["--mock-resolve", "episode", "status", "42"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Episode status lookup failed:" in out
