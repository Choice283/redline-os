"""Tests for the CLI's `episode validate-manifest <manifest_path>` command.

A thin, read-only wrapper over the existing, already-tested
redline_core.manifest.load_manifest() + .validate_manifest(). Routed
through CoreServices (config-only) rather than the ApplicationServices
every other `episode` action uses -- this is the first `episode` action
that never touches SQLite or Resolve, confirmed at the CLI-invocation
level below the same way test_cli_asset_list.py already proves it for
`asset list`: main() must succeed with no REDLINE_DB_PATH set and no
--mock-resolve flag, which would fail for any other `episode` command.
"""
from pathlib import Path

import pytest
import yaml

from redline_core.asset.manager import AssetManager
from redline_core.config.schema import (
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.runtime.composition import CoreServices

from cli import main as cli_main
from cli.episode_commands import (
    _print_episode_validate_manifest_result,
    _run_episode_validate_manifest,
    run_validate_manifest,
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


def make_core_services(tmp_path: Path) -> CoreServices:
    config = make_config(tmp_path)
    return CoreServices(config=config, asset_manager=AssetManager(config))


def write_media_file(config: RedlineConfig, name: str) -> Path:
    media_path = Path(config.paths.ingest_path) / name
    media_path.write_bytes(b"fake media bytes")
    return media_path


def write_manifest(tmp_path: Path, *, media_path: Path, markers_yaml: str = "", schema_version: int = 1) -> Path:
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(
        f'schema_version: {schema_version}\n'
        f'episode:\n  id: "RLC-E025"\n'
        f"assembly:\n"
        f'  media:\n    - path: "{media_path.as_posix()}"\n'
        f'  bin_name: "footage"\n'
        f"{markers_yaml}"
    )
    return manifest_path


# -- _run_episode_validate_manifest ------------------------------------------------

def test_run_validate_manifest_success(tmp_path):
    services = make_core_services(tmp_path)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(
        tmp_path,
        media_path=media_path,
        markers_yaml=(
            "  markers:\n"
            '    - frame: 0\n      color: "Blue"\n      name: "Cold Open"\n'
            '    - frame: 1800\n      color: "Yellow"\n      name: "Ad Break 1"\n'
        ),
    )

    result = _run_episode_validate_manifest(services, str(manifest_path))

    assert result["success"] is True
    assert result["episode_id"] == "RLC-E025"
    assert result["bin_name"] == "footage"
    assert result["media_count"] == 1
    assert result["media_paths"] == [str(media_path.resolve())]
    assert result["marker_count"] == 2
    assert result["markers"] == [
        {"frame": 0, "color": "Blue", "name": "Cold Open", "note": ""},
        {"frame": 1800, "color": "Yellow", "name": "Ad Break 1", "note": ""},
    ]


def test_run_validate_manifest_zero_markers_is_success(tmp_path):
    services = make_core_services(tmp_path)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    result = _run_episode_validate_manifest(services, str(manifest_path))

    assert result["success"] is True
    assert result["marker_count"] == 0
    assert result["markers"] == []


def test_run_validate_manifest_missing_file(tmp_path):
    services = make_core_services(tmp_path)

    result = _run_episode_validate_manifest(services, str(tmp_path / "does_not_exist.yaml"))

    assert result["success"] is False
    assert "does_not_exist.yaml" in result["error"]


def test_run_validate_manifest_malformed_yaml(tmp_path):
    services = make_core_services(tmp_path)
    manifest_path = tmp_path / "bad.yaml"
    manifest_path.write_text("schema_version: 1\nepisode: [this is not, a mapping\n")

    result = _run_episode_validate_manifest(services, str(manifest_path))

    assert result["success"] is False
    assert result["error"]


def test_run_validate_manifest_unsupported_schema_version(tmp_path):
    services = make_core_services(tmp_path)
    media_path = write_media_file(services.config, "a.wav")
    manifest_path = write_manifest(tmp_path, media_path=media_path, schema_version=2)

    result = _run_episode_validate_manifest(services, str(manifest_path))

    assert result["success"] is False
    assert "schema_version" in result["error"]


def test_run_validate_manifest_media_path_outside_approved_roots(tmp_path):
    services = make_core_services(tmp_path)
    outside_dir = tmp_path / "_outside"
    outside_dir.mkdir()
    outside_media = outside_dir / "a.wav"
    outside_media.write_bytes(b"fake media bytes")
    manifest_path = write_manifest(tmp_path, media_path=outside_media)

    result = _run_episode_validate_manifest(services, str(manifest_path))

    assert result["success"] is False
    assert "approved media roots" in result["error"]


# -- _print_episode_validate_manifest_result ---------------------------------------

def test_print_validate_manifest_result_success(capsys):
    _print_episode_validate_manifest_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "bin_name": "footage",
            "media_paths": ["/abs/a.wav"],
            "media_count": 1,
            "markers": [{"frame": 0, "color": "Blue", "name": "Cold Open", "note": ""}],
            "marker_count": 1,
        }
    )

    out = capsys.readouterr().out
    assert "RLC-E025" in out
    assert "Media files:   1" in out
    assert "Markers:       1" in out
    assert "/abs/a.wav" in out
    assert "frame=0 color=Blue name='Cold Open'" in out
    assert "Manifest is valid. No Resolve or database changes were made." in out


def test_print_validate_manifest_result_zero_markers_no_marker_section(capsys):
    _print_episode_validate_manifest_result(
        {
            "success": True,
            "episode_id": "RLC-E025",
            "bin_name": "footage",
            "media_paths": ["/abs/a.wav"],
            "media_count": 1,
            "markers": [],
            "marker_count": 0,
        }
    )

    out = capsys.readouterr().out
    assert "Markers:       0" in out
    assert "\nMarkers:\n" not in out


def test_print_validate_manifest_result_failure(capsys):
    _print_episode_validate_manifest_result({"success": False, "error": "manifest schema validation failed: boom"})

    out = capsys.readouterr().out
    assert "Manifest validation failed: manifest schema validation failed: boom" in out


# -- run_validate_manifest dispatch --------------------------------------------------

def test_run_validate_manifest_dispatch_ignores_other_actions(tmp_path):
    services = make_core_services(tmp_path)

    class _Args:
        action = "create"

    assert run_validate_manifest(_Args(), services) is None


# -- argument parsing -----------------------------------------------------------

def test_parser_validate_manifest_parses_manifest_path():
    parser = _build_parser()
    args = parser.parse_args(["episode", "validate-manifest", "some/path.yaml"])
    assert args.resource == "episode"
    assert args.action == "validate-manifest"
    assert args.manifest_path == "some/path.yaml"


def test_parser_validate_manifest_requires_manifest_path():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["episode", "validate-manifest"])


# -- main() end-to-end: the gating no-DB, no-Resolve proof --------------------------

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


def test_main_validate_manifest_end_to_end_success_no_db_no_mock_resolve(tmp_path, monkeypatch, capsys):
    """The gating proof for this mission: main() must succeed with neither
    REDLINE_DB_PATH set nor --mock-resolve passed. If cli/main.py's new
    action-branch fell through to build_application_services() instead of
    build_core_services(), this would fail trying to connect to a real
    Resolve Studio instance (unavailable in this sandbox), proving the
    CoreServices routing genuinely took effect rather than merely looking
    correct.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("REDLINE_DB_PATH", raising=False)

    media_path = Path(tmp_path / "_ingest" / "a.wav")
    media_path.write_bytes(b"fake media bytes")
    manifest_path = write_manifest(tmp_path, media_path=media_path)

    exit_code = cli_main.main(["episode", "validate-manifest", str(manifest_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLC-E025" in out
    assert "Manifest is valid. No Resolve or database changes were made." in out


def test_main_validate_manifest_end_to_end_failure(tmp_path, monkeypatch, capsys):
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("REDLINE_DB_PATH", raising=False)

    exit_code = cli_main.main(["episode", "validate-manifest", str(tmp_path / "missing.yaml")])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Manifest validation failed:" in out
