"""Tests for the CLI's `episode organize-bins <episode_number>` command.

A thin, mutating wrapper over the existing, already-tested
MediaManager.organize_bins(), routed through ApplicationServices (full
DB + Resolve runtime, same as every other `episode` action).
episode_number is resolved to project_name/episode_id via the same
get_episode_status() call scan-ingest/status already use; bin_name is
passed through unchanged, defaulting to the manager's own literal default
("footage"). Zero matched ingest files is a successful result, not an
error.
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
from redline_core.resolve.exceptions import MediaImportError, ProjectNotFoundError
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder

from cli import main as cli_main
from cli.episode_commands import (
    _print_episode_organize_bins_result,
    _run_episode_organize_bins,
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


def seed_episode_with_media(services, tmp_path: Path, episode_number: int = 25) -> None:
    services.episode_manager.create_episode(episode_number)
    ingest = Path(services.config.paths.ingest_path)
    ingest.mkdir(parents=True, exist_ok=True)
    episode_id = services.config.naming.episode_id_pattern.format(episode_number=episode_number)
    (ingest / f"{episode_id}_camA_001.mov").write_bytes(b"x")


# -- _run_episode_organize_bins ------------------------------------------------------

def test_run_organize_bins_success(tmp_path):
    services = make_services(tmp_path)
    seed_episode_with_media(services, tmp_path)

    result = _run_episode_organize_bins(services, 25, "footage")

    assert result["success"] is True
    assert result["episode_id"] == "RLC-E025"
    assert result["project_name"] == "RLC-E025_MASTER"
    assert result["bin_name"] == "footage"
    assert result["clip_count"] == 1
    assert len(result["clip_ids"]) == 1


def test_run_organize_bins_zero_matches_is_success_and_skips_resolve(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)
    Path(services.config.paths.ingest_path).mkdir(parents=True, exist_ok=True)
    # No matching ingest files created.

    called = []
    original = MockResolveAdapter.import_media

    def _spy(self, project_name, media_paths, bin_name):
        called.append((project_name, media_paths, bin_name))
        return original(self, project_name, media_paths, bin_name)

    monkeypatch.setattr(MockResolveAdapter, "import_media", _spy)

    result = _run_episode_organize_bins(services, 25, "footage")

    assert result["success"] is True
    assert result["clip_count"] == 0
    assert result["clip_ids"] == []
    # Proves media import is skipped after an empty scan — not "Resolve
    # independence": this command still requires Resolve composition and
    # connection, same as every other `episode` action.
    assert called == []


def test_run_organize_bins_unknown_episode(tmp_path):
    services = make_services(tmp_path)

    result = _run_episode_organize_bins(services, 999, "footage")

    assert result["success"] is False
    assert "999" in result["error"]


def test_run_organize_bins_project_not_found_passthrough(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    seed_episode_with_media(services, tmp_path)

    def _boom(self, project_name, media_paths, bin_name):
        raise ProjectNotFoundError(f"Project could not be loaded: {project_name}")

    monkeypatch.setattr(MockResolveAdapter, "import_media", _boom)

    result = _run_episode_organize_bins(services, 25, "footage")

    assert result["success"] is False
    assert "RLC-E025_MASTER" in result["error"]


def test_run_organize_bins_media_import_error_passthrough(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    seed_episode_with_media(services, tmp_path)

    def _boom(self, project_name, media_paths, bin_name):
        raise MediaImportError("Resolve failed to import media.")

    monkeypatch.setattr(MockResolveAdapter, "import_media", _boom)

    result = _run_episode_organize_bins(services, 25, "footage")

    assert result["success"] is False
    assert "Resolve failed to import media." in result["error"]


def test_run_organize_bins_custom_bin_name_passthrough(tmp_path, monkeypatch):
    services = make_services(tmp_path)
    seed_episode_with_media(services, tmp_path)

    calls = []
    original = MockResolveAdapter.import_media

    def _spy(self, project_name, media_paths, bin_name):
        calls.append(bin_name)
        return original(self, project_name, media_paths, bin_name)

    monkeypatch.setattr(MockResolveAdapter, "import_media", _spy)

    result = _run_episode_organize_bins(services, 25, "interviews")

    assert result["bin_name"] == "interviews"
    assert calls == ["interviews"]


# -- _print_episode_organize_bins_result --------------------------------------------

def test_print_organize_bins_result_with_clips(capsys):
    _print_episode_organize_bins_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "bin_name": "footage",
            "clip_ids": ["clip-001", "clip-002"],
            "clip_count": 2,
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "RLC-E025_MASTER" in out
    assert "Clips added:  2" in out
    assert "Clip IDs:" in out
    assert "clip-001" in out
    assert "clip-002" in out


def test_print_organize_bins_result_zero_clips(capsys):
    _print_episode_organize_bins_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "bin_name": "footage",
            "clip_ids": [],
            "clip_count": 0,
        }
    )

    out = capsys.readouterr().out
    assert "Clips added:  0" in out
    assert "Clip IDs:" not in out
    assert "no media" not in out.lower()


def test_print_organize_bins_result_failure(capsys):
    _print_episode_organize_bins_result({"success": False, "error": "No episode with episode_number=999."})

    out = capsys.readouterr().out
    assert "Organize bins failed:" in out
    assert "999" in out


# -- argument parsing -----------------------------------------------------------

def test_parser_organize_bins_default_bin_name():
    parser = _build_parser()
    args = parser.parse_args(["episode", "organize-bins", "25"])
    assert args.resource == "episode"
    assert args.action == "organize-bins"
    assert args.episode_number == 25
    assert args.bin_name == "footage"


def test_parser_organize_bins_custom_bin_name():
    parser = _build_parser()
    args = parser.parse_args(["episode", "organize-bins", "25", "--bin-name", "interviews"])
    assert args.bin_name == "interviews"


def test_parser_organize_bins_rejects_non_integer():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["episode", "organize-bins", "not-a-number"])


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
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_organize_bins_end_to_end(tmp_path, monkeypatch, capsys):
    """main() builds a brand new MockResolveAdapter on every invocation (the
    same way it builds a brand new ApplicationServices every time) — so a
    Resolve project created by one `main()` call doesn't exist for a
    separately-invoked one, exactly as it wouldn't across two real,
    separate `redline ... --mock-resolve` process invocations either. To
    prove organize-bins end to end against a project that already exists,
    this test shares one MockResolveAdapter instance across both `main()`
    calls (monkeypatching cli.main's MockResolveAdapter reference to
    return it) rather than inventing any new persistence the CLI doesn't
    have.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    shared_resolve = MockResolveAdapter()
    monkeypatch.setattr(cli_main, "MockResolveAdapter", lambda: shared_resolve)

    cli_main.main(["--mock-resolve", "episode", "create", "25"])
    ingest = tmp_path / "_ingest"
    ingest.mkdir(parents=True, exist_ok=True)
    (ingest / "RLC-E025_camA_001.mov").write_bytes(b"x")

    exit_code = cli_main.main(["--mock-resolve", "episode", "organize-bins", "25"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "Clips added:  1" in out
