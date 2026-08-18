"""Tests for the CLI's `episode scan-ingest` command.

Read-only wrapper over the existing, already-tested
MediaManager.scan_ingest_for_episode() — these tests exist to prove the CLI
adds no behavior beyond what that method already does: no media-type
filtering, no deduplication, no import. Every test uses an in-memory
RedlineConfig scoped under tmp_path (never load_config("config")), for the
same reason established in test_cli_episode_create.py: the real
config/folder_structure.yaml has a relative root_path, and running against
it would write into the actual repo working tree.
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
from cli.main import _build_parser, _print_episode_scan_ingest_result, _run_episode_scan_ingest


def make_config(tmp_path: Path) -> RedlineConfig:
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    ingest_path = tmp_path / "_ingest"
    ingest_path.mkdir()
    return RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(ingest_path),
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


# -- _run_episode_scan_ingest ---------------------------------------------------

def test_scan_ingest_matches_regardless_of_extension(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(1)
    ingest_path = Path(services.config.paths.ingest_path)
    (ingest_path / "RLC-E001_CAM-A_001.mov").write_bytes(b"")
    (ingest_path / "RLC-E001_AUDIO_001.wav").write_bytes(b"")
    (ingest_path / "RLC-E001_NOTES.txt").write_bytes(b"")
    (ingest_path / "RLC-E002_UNRELATED.mov").write_bytes(b"")  # different episode, must be excluded

    result = _run_episode_scan_ingest(services, 1)

    assert result["success"] is True
    assert sorted(result["matched_files"]) == [
        "RLC-E001_AUDIO_001.wav",
        "RLC-E001_CAM-A_001.mov",
        "RLC-E001_NOTES.txt",
    ]


def test_scan_ingest_zero_matches_is_success(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(1)

    result = _run_episode_scan_ingest(services, 1)

    assert result["success"] is True
    assert result["matched_files"] == []


def test_scan_ingest_missing_ingest_folder_is_success(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(1)
    # Remove the ingest folder entirely after config was built pointing at it.
    Path(services.config.paths.ingest_path).rmdir()

    result = _run_episode_scan_ingest(services, 1)

    assert result["success"] is True
    assert result["matched_files"] == []


def test_scan_ingest_unknown_episode_is_clean_error(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_scan_ingest(services, 999)

    assert result["success"] is False
    assert "999" in result["error"]


# -- _print_episode_scan_ingest_result ------------------------------------------

def test_print_scan_ingest_result_success(capsys):
    _print_episode_scan_ingest_result(
        {
            "success": True,
            "episode_id": "RLC-E001",
            "ingest_path": "/some/ingest",
            "matched_files": ["RLC-E001_NOTES.txt", "RLC-E001_CAM-A_001.mov"],
        }
    )

    out = capsys.readouterr().out
    assert "Episode: RLC-E001" in out
    assert "Matched files: 2" in out
    assert "RLC-E001_NOTES.txt" in out
    assert "classified, deduplicated, copied, moved, imported, or registered" in out


def test_print_scan_ingest_result_failure(capsys):
    _print_episode_scan_ingest_result({"success": False, "error": "No episode with episode_number=999."})

    out = capsys.readouterr().out
    assert "Ingest scan failed:" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_scan_ingest_parses_episode_number():
    parser = _build_parser()
    args = parser.parse_args(["episode", "scan-ingest", "3"])
    assert args.resource == "episode"
    assert args.action == "scan-ingest"
    assert args.episode_number == 3


# -- main() end-to-end -----------------------------------------------------------

def write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    ingest_path = tmp_path / "_ingest"
    ingest_path.mkdir()
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
                "ingest_path": str(ingest_path),
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


def test_main_scan_ingest_end_to_end(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    cli_main.main(["--mock-resolve", "episode", "create", "5"])
    (tmp_path / "_ingest" / "RLC-E005_CAM-A_001.mov").write_bytes(b"")

    exit_code = cli_main.main(["--mock-resolve", "episode", "scan-ingest", "5"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Episode: RLC-E005" in out
    assert "Matched files: 1" in out
    assert "RLC-E005_CAM-A_001.mov" in out


def test_main_scan_ingest_unknown_episode_is_clean_error(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e_missing.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    exit_code = cli_main.main(["--mock-resolve", "episode", "scan-ingest", "42"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Ingest scan failed:" in out
