"""Tests for the CLI's `episode assemble <manifest_path> [--force]` command.

A thin, mutating wrapper over the existing, already-tested
load_manifest() -> validate_manifest() -> .to_build_definition() ->
EpisodeManager.build_episode() pipeline, routed through
ApplicationServices (full DB + Resolve runtime, same as every other
`episode` action). `--force` maps directly onto
EpisodeManager.build_episode()'s transport-neutral `allow_unsafe_retry`
keyword -- this CLI layer performs no eligibility check, status
inspection, or retry-policy decision of its own (ADR-0001,
"Episode Assembly Retry Policy": EpisodeManager is the sole authority).

No manager-level retry-policy tests are added here -- the full status
matrix (blocked/allowed/always-blocked, dangling claims, forced retry)
already has complete, independent coverage in test_episode_manager.py.
This file is CLI transport coverage only: argument parsing, the
success/failure dict shapes, the --force warning banner, and one
end-to-end main() smoke test proving --force actually unblocks a
FAILED episode through the real CLI entry point.
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
from redline_core.db.models import EpisodeStatus
from redline_core.episode.manager import EpisodeManager
from redline_core.media.manager import MediaManager
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.timeline.builder import TimelineBuilder

from cli import main as cli_main
from cli.episode_commands import (
    _print_episode_assemble_result,
    _run_episode_assemble,
)
from cli.main import _build_parser


def make_config(tmp_path: Path) -> RedlineConfig:
    ingest_path = tmp_path / "_ingest"
    ingest_path.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
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


def make_services(tmp_path: Path):
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


def write_media_file(config: RedlineConfig, name: str) -> Path:
    media_path = Path(config.paths.ingest_path) / name
    media_path.write_bytes(b"fake media bytes")
    return media_path


def write_manifest(tmp_path: Path, *, media_path: Path, episode_id: str = "RLC-E025") -> Path:
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(
        "schema_version: 1\n"
        f'episode:\n  id: "{episode_id}"\n'
        "assembly:\n"
        f'  media:\n    - path: "{media_path.as_posix()}"\n'
        '  bin_name: "footage"\n'
        "  markers:\n"
        '    - frame: 0\n      color: "Blue"\n      name: "Cold Open"\n'
    )
    return manifest_path


# -- _run_episode_assemble ------------------------------------------------------

def test_run_assemble_success(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    result = _run_episode_assemble(services, str(manifest_path), force=False)

    assert result["success"] is True
    assert result["episode_id"] == "RLC-E025"
    assert result["project_name"] == "RLC-E025_MASTER"
    assert result["timeline_name"] == "RLC-E025_TIMELINE"
    assert result["media_paths"] == [str(media_path.resolve())]
    assert len(result["media_ids"]) == 1
    assert result["markers_applied"] == 1
    assert len(result["timeline_item_ids"]) == 1
    assert services.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_run_assemble_invalid_manifest_fails_before_build(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)

    result = _run_episode_assemble(services, str(tmp_path / "does_not_exist.yaml"), force=False)

    assert result["success"] is False
    assert "does_not_exist.yaml" in result["error"]


def test_run_assemble_nonexistent_episode_fails(tmp_path):
    services = make_services(tmp_path)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    result = _run_episode_assemble(services, str(manifest_path), force=False)

    assert result["success"] is False
    assert "No existing episode" in result["error"]


def test_run_assemble_failed_episode_is_rejected_without_force(tmp_path):
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)
    services.db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    result = _run_episode_assemble(services, str(manifest_path), force=False)

    assert result["success"] is False
    assert "marked failed" in result["error"]


def test_run_assemble_failed_episode_succeeds_with_force(tmp_path):
    """The one place this mission's CLI layer must prove --force actually
    reaches EpisodeManager: force=True maps to allow_unsafe_retry=True,
    which is the only thing that lets a FAILED episode be retried."""
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)
    services.db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    result = _run_episode_assemble(services, str(manifest_path), force=True)

    assert result["success"] is True
    assert services.db.get_episode_by_episode_id("RLC-E025").status == EpisodeStatus.ASSEMBLED


def test_run_assemble_already_assembled_is_rejected_even_with_force(tmp_path):
    """Terminal statuses are never overridable, regardless of --force
    (ADR-0001 invariant 5) -- this is the CLI-level proof that force=True
    does not somehow bypass that."""
    services = make_services(tmp_path)
    services.episode_manager.create_episode(25)
    services.db.update_episode_status("RLC-E025", EpisodeStatus.ASSEMBLED)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    result = _run_episode_assemble(services, str(manifest_path), force=True)

    assert result["success"] is False
    assert "already assembled" in result["error"]


# -- _print_episode_assemble_result ----------------------------------------------

def test_print_assemble_result_success_no_force(capsys):
    _print_episode_assemble_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "timeline_name": "RLC-E025_TIMELINE",
            "media_paths": ["/abs/a.wav"],
            "media_ids": ["clip-1"],
            "markers_applied": 1,
            "timeline_item_ids": ["item-1"],
        },
        force=False,
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "Media imported:   1" in out
    assert "Markers applied:  1" in out
    assert "Clips placed:     1" in out
    assert "/abs/a.wav -> clip-1 -> item-1" in out
    assert "WARNING: --force" not in out


def test_print_assemble_result_prints_force_warning_even_on_failure(capsys):
    """The warning is printed whenever force=True was passed, unconditionally
    -- including on failure, since determining whether force was actually
    needed would require CLI-side eligibility inspection, which this
    mission's design explicitly forbids (EpisodeManager is sole authority)."""
    _print_episode_assemble_result(
        {"success": False, "error": "Episode RLC-E025 is already assembled."},
        force=True,
    )

    out = capsys.readouterr().out
    assert "WARNING: --force overrides Redline OS's normal retry protection" in out
    assert "Assemble failed: Episode RLC-E025 is already assembled." in out


def test_print_assemble_result_zero_media_no_media_section(capsys):
    _print_episode_assemble_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "project_name": "RLC-E025_MASTER",
            "timeline_name": "RLC-E025_TIMELINE",
            "media_paths": [],
            "media_ids": [],
            "markers_applied": 0,
            "timeline_item_ids": [],
        },
        force=False,
    )

    out = capsys.readouterr().out
    assert "Media imported:   0" in out
    assert "->" not in out


# -- argument parsing -----------------------------------------------------------

def test_parser_assemble_parses_manifest_path():
    parser = _build_parser()
    args = parser.parse_args(["episode", "assemble", "some/path.yaml"])
    assert args.resource == "episode"
    assert args.action == "assemble"
    assert args.manifest_path == "some/path.yaml"
    assert args.force is False


def test_parser_assemble_parses_force_flag():
    parser = _build_parser()
    args = parser.parse_args(["episode", "assemble", "some/path.yaml", "--force"])
    assert args.force is True


def test_parser_assemble_requires_manifest_path():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["episode", "assemble"])


# -- main() end-to-end, via env-var injection ------------------------------------

def write_isolated_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    ingest_path = tmp_path / "_ingest"
    ingest_path.mkdir()
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    (config_dir / "naming.yaml").write_text(
        'episode_id_pattern: "RLC-E{episode_number:03d}"\nproject_name_pattern: "{episode_id}_MASTER"\n'
    )
    (config_dir / "folder_structure.yaml").write_text(f'root_path: "{tmp_path / "_episodes"}"\n')
    (config_dir / "render_presets.yaml").write_text("presets: []\n")
    (config_dir / "paths.yaml").write_text(
        f'ingest_path: "{ingest_path}"\n'
        f'archive_path: "{tmp_path / "_archive"}"\n'
        f'assets_path: "{assets_path}"\n'
        'master_project_template: "RLC_MASTER_TEMPLATE"\n'
    )
    (config_dir / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n")
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_assemble_end_to_end_success(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_DB_PATH", str(tmp_path / "main_e2e.db"))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    shared_resolve = MockResolveAdapter()
    monkeypatch.setattr(cli_main, "MockResolveAdapter", lambda: shared_resolve)

    cli_main.main(["--mock-resolve", "episode", "create", "25"])

    media_path = Path(tmp_path / "_ingest" / "a.wav")
    media_path.write_bytes(b"fake media bytes")
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(
        "schema_version: 1\n"
        'episode:\n  id: "RLC-E025"\n'
        "assembly:\n"
        f'  media:\n    - path: "{media_path.as_posix()}"\n'
        '  bin_name: "footage"\n'
    )

    exit_code = cli_main.main(["--mock-resolve", "episode", "assemble", str(manifest_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "Clips placed:     1" in out
    assert "WARNING: --force" not in out


def test_main_assemble_end_to_end_force_unblocks_failed_episode(tmp_path, monkeypatch, capsys):
    """The gating proof for this mission: a FAILED episode is rejected by a
    plain `episode assemble`, but `episode assemble --force` (through the
    real CLI entry point, not a direct manager call) successfully retries
    it -- proving --force actually reaches EpisodeManager's
    allow_unsafe_retry parameter end-to-end."""
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    db_path = tmp_path / "main_e2e.db"
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    shared_resolve = MockResolveAdapter()
    monkeypatch.setattr(cli_main, "MockResolveAdapter", lambda: shared_resolve)

    cli_main.main(["--mock-resolve", "episode", "create", "25"])

    media_path = Path(tmp_path / "_ingest" / "a.wav")
    media_path.write_bytes(b"fake media bytes")
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(
        "schema_version: 1\n"
        'episode:\n  id: "RLC-E025"\n'
        "assembly:\n"
        f'  media:\n    - path: "{media_path.as_posix()}"\n'
        '  bin_name: "footage"\n'
    )

    # Force the episode into FAILED directly against the same on-disk DB
    # main() itself will connect to.
    failing_db = Database(db_path).connect()
    failing_db.update_episode_status("RLC-E025", EpisodeStatus.FAILED)
    failing_db.close()

    blocked_exit_code = cli_main.main(["--mock-resolve", "episode", "assemble", str(manifest_path)])
    blocked_out = capsys.readouterr().out
    assert blocked_exit_code == 1
    assert "marked failed" in blocked_out

    forced_exit_code = cli_main.main(["--mock-resolve", "episode", "assemble", str(manifest_path), "--force"])
    forced_out = capsys.readouterr().out
    assert forced_exit_code == 0
    assert "WARNING: --force overrides Redline OS's normal retry protection" in forced_out
    assert "Clips placed:     1" in forced_out
