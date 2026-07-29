"""Tests for the CLI's `archive episode <episode_id>` command.

A thin, mutating wrapper over the existing, already-tested
ArchiveManager.archive_episode(), routed through PersistenceServices
(config + DB composition — no Resolve). Success output reports only the
returned ArchiveRecord's fields (episode_id/archive_path/archived_at) —
no progress checklist, no additional DB or filesystem reads. Failure
messages are the manager's own, passed through unchanged.

The "destination already exists" case is tested at two independent
levels, per explicit instruction: tests/unit/test_archive_manager.py
proves ArchiveManager itself raises ArchiveError for that condition; the
tests below prove only that the CLI passes that manager error through
unchanged and exits 1 — this file is not that branch's only coverage.
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
from redline_core.db.models import EpisodeStatus
from redline_core.runtime.composition import PersistenceServices

from cli import main as cli_main
from cli.archive_commands import _print_archive_episode_result, _run_archive_episode
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


def seed_episode_with_folder(services: PersistenceServices, tmp_path: Path, episode_number: int, episode_id: str) -> Path:
    services.db.create_episode(episode_number, episode_id, f"{episode_id}_MASTER")
    folder = tmp_path / "_episodes" / episode_id
    folder.mkdir(parents=True)
    services.db.update_episode_paths(episode_id, folder_path=str(folder))
    return folder


# -- _run_archive_episode -----------------------------------------------------------

def test_run_archive_episode_success(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_episode_with_folder(services, tmp_path, 25, "RLC-E025")

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is True
    assert result["archive"]["episode_id"] == "RLC-E025"
    assert result["archive"]["archive_path"] == str(tmp_path / "_archive" / "RLC-E025")
    assert result["archive"]["archived_at"] is not None

    episode = services.db.get_episode_by_episode_id("RLC-E025")
    assert episode.status == EpisodeStatus.ARCHIVED


def test_run_archive_episode_unknown_episode(tmp_path):
    services = make_persistence_services(tmp_path)

    result = _run_archive_episode(services, "RLC-E999")

    assert result["success"] is False
    assert "RLC-E999" in result["error"]


def test_run_archive_episode_already_archived(tmp_path):
    services = make_persistence_services(tmp_path)
    seed_episode_with_folder(services, tmp_path, 25, "RLC-E025")
    _run_archive_episode(services, "RLC-E025")

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is False
    assert "already archived" in result["error"]


def test_run_archive_episode_missing_folder_path(tmp_path):
    services = make_persistence_services(tmp_path)
    services.db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    # No update_episode_paths() call: folder_path stays None.

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is False
    assert "no working folder" in result["error"]


def test_run_archive_episode_destination_already_exists(tmp_path):
    """Proves only that the CLI passes ArchiveManager's ArchiveError through
    unchanged for this condition — the manager-level branch itself is
    proven separately in test_archive_manager.py."""
    services = make_persistence_services(tmp_path)
    seed_episode_with_folder(services, tmp_path, 25, "RLC-E025")
    (tmp_path / "_archive" / "RLC-E025").mkdir(parents=True)

    result = _run_archive_episode(services, "RLC-E025")

    assert result["success"] is False
    assert "already exists" in result["error"]


# -- _print_archive_episode_result --------------------------------------------------

def test_print_archive_episode_result_success(capsys):
    _print_archive_episode_result(
        {
            "success": True,
            "archive": {
                "episode_id": "RLC-E025",
                "archive_path": "/archive/RLC-E025",
                "archived_at": "2026-07-29 19:00:47",
            },
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "/archive/RLC-E025" in out
    assert "2026-07-29 19:00:47" in out
    # No progress/checklist narration.
    assert "✓" not in out


def test_print_archive_episode_result_failure(capsys):
    _print_archive_episode_result({"success": False, "error": "No episode with episode_id=RLC-E999."})

    out = capsys.readouterr().out
    assert "Archive failed:" in out
    assert "RLC-E999" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_archive_episode_parses_episode_id():
    parser = _build_parser()
    args = parser.parse_args(["archive", "episode", "RLC-E025"])
    assert args.resource == "archive"
    assert args.action == "episode"
    assert args.episode_id == "RLC-E025"


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


def test_main_archive_episode_end_to_end_without_mock_resolve(tmp_path, monkeypatch, capsys):
    """No --mock-resolve set at all — an `episode` command in this same
    environment would either fail (real Resolve not running in this
    sandbox) or require the flag. `archive episode` must do neither,
    because it's routed through PersistenceServices, which never touches
    Resolve.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    db_path = tmp_path / "redline.db"
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    # Seed the episode+folder through the same DB main() will open.
    from redline_core.config.loader import load_config

    config = load_config(config_dir)
    db = Database(db_path).connect()
    db.init_schema()
    db.create_episode(25, "RLC-E025", "RLC-E025_MASTER")
    folder = tmp_path / "_episodes" / "RLC-E025"
    folder.mkdir(parents=True)
    db.update_episode_paths("RLC-E025", folder_path=str(folder))

    exit_code = cli_main.main(["archive", "episode", "RLC-E025"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert not folder.exists()
    assert (tmp_path / "_archive" / "RLC-E025").is_dir()


def test_main_archive_episode_unknown_is_clean_error(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "redline.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["archive", "episode", "RLC-E999"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Archive failed:" in out
