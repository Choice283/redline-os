"""Tests for the CLI's `archive list` command.

Read-only wrapper over the existing, already-tested
ArchiveManager.list_archives(), routed through PersistenceServices
(config + DB composition — no Resolve). These tests also prove that
independence at the CLI-invocation level: main() runs `archive list`
successfully with no --mock-resolve flag, which an `episode` command in
this same environment would need.
"""
from pathlib import Path

from redline_core.archive.manager import ArchiveManager
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
from redline_core.runtime.composition import PersistenceServices

from cli import main as cli_main
from cli.archive_commands import _print_archive_list_result, _run_archive_list
from cli.main import _build_parser


def make_persistence_services(tmp_path: Path) -> PersistenceServices:
    config = RedlineConfig(
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
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    db = Database(tmp_path / "test.db").connect()
    db.init_schema()
    return PersistenceServices(config=config, db=db, archive_manager=ArchiveManager(config, db))


def archive_episode(services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str) -> None:
    services.db.create_episode(episode_number, episode_id, f"{episode_id}_MASTER")
    folder = tmp_path / "_episodes" / episode_id
    folder.mkdir(parents=True)
    services.db.update_episode_paths(episode_id, folder_path=str(folder))
    services.archive_manager.archive_episode(episode_id)


# -- _run_archive_list -------------------------------------------------------------

def test_run_archive_list_empty(tmp_path):
    services = make_persistence_services(tmp_path)

    result = _run_archive_list(services)

    assert result["success"] is True
    assert result["archives"] == []


def test_run_archive_list_serializes_all_three_fields(tmp_path):
    services = make_persistence_services(tmp_path)
    archive_episode(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_list(services)

    assert len(result["archives"]) == 1
    archive = result["archives"][0]
    assert archive["episode_id"] == "RLC-E025"
    assert archive["archive_path"] == str(tmp_path / "_archive" / "RLC-E025")
    assert archive["archived_at"] is not None


def test_run_archive_list_multiple_by_membership(tmp_path):
    # Mirrors test_archive_manager.test_list_archives: assert set membership,
    # not order — database.py's ORDER BY archived_at has no secondary sort
    # key, so two archives created in the same instant are not guaranteed a
    # stable relative order. This command doesn't re-sort the manager's result.
    services = make_persistence_services(tmp_path)
    archive_episode(services, tmp_path, 25, "RLC-E025")
    archive_episode(services, tmp_path, 26, "RLC-E026")

    result = _run_archive_list(services)

    assert {a["episode_id"] for a in result["archives"]} == {"RLC-E025", "RLC-E026"}


# -- _print_archive_list_result -----------------------------------------------------

def test_print_archive_list_result_empty(capsys):
    _print_archive_list_result({"success": True, "archives": []})

    out = capsys.readouterr().out
    assert "No archives found." in out


def test_print_archive_list_result_multiple(capsys):
    _print_archive_list_result(
        {
            "success": True,
            "archives": [
                {"episode_id": "RLC-E025", "archive_path": "/archive/RLC-E025", "archived_at": "2026-01-01 00:00:00"},
                {"episode_id": "RLC-E026", "archive_path": "/archive/RLC-E026", "archived_at": "2026-01-02 00:00:00"},
            ],
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "RLC-E026" in out
    assert "/archive/RLC-E025" in out
    assert "2 archive(s)." in out


# -- argument parsing -----------------------------------------------------------

def test_parser_archive_list_takes_no_arguments():
    parser = _build_parser()
    args = parser.parse_args(["archive", "list"])
    assert args.resource == "archive"
    assert args.action == "list"


# -- main() end-to-end: proves genuine Resolve independence ---------------------

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


def test_main_archive_list_end_to_end_without_mock_resolve(tmp_path, monkeypatch, capsys):
    """No --mock-resolve set at all — an `episode` command in this same
    environment would either fail (real Resolve not running in this
    sandbox) or require the flag. `archive list` must do neither, because
    it's routed through PersistenceServices, which never touches Resolve.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["archive", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No archives found." in out


def test_main_archive_list_shows_archived_episode(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    db_path = tmp_path / "redline.db"
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    services = make_persistence_services_from_env(config_dir, db_path, tmp_path)
    archive_episode(services, tmp_path, 25, "RLC-E025")

    exit_code = cli_main.main(["archive", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "1 archive(s)." in out


def make_persistence_services_from_env(config_dir: Path, db_path: Path, tmp_path: Path) -> PersistenceServices:
    """Builds a PersistenceServices pointed at the same config dir and DB
    path main() will use, so the pre-seeded archive is visible to it.
    Loads config via the real loader (not an in-memory RedlineConfig) to
    guarantee it matches what main() itself will load."""
    from redline_core.config.loader import load_config

    config = load_config(config_dir)
    db = Database(db_path).connect()
    db.init_schema()
    return PersistenceServices(config=config, db=db, archive_manager=ArchiveManager(config, db))
