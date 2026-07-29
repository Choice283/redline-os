"""Tests for the CLI's `asset list` command.

Read-only wrapper over the existing, already-tested
AssetManager.list_available_assets(), routed through CoreServices
(config-only composition — no SQLite, no Resolve). These tests also prove
that independence at the CLI-invocation level: main() runs `asset list`
successfully with no REDLINE_DB_PATH set and no --mock-resolve flag, which
would fail for any `episode` command.
"""
from pathlib import Path

from redline_core.config.schema import (
    AssetDefinition,
    AssetsConfig,
    FolderStructureConfig,
    NamingConfig,
    PathsConfig,
    RedlineConfig,
    RenderPresetsConfig,
    TimelineTemplateConfig,
)
from redline_core.asset.manager import AssetManager
from redline_core.runtime.composition import CoreServices

from cli import main as cli_main
from cli.asset_commands import _print_asset_list_result, _run_asset_list
from cli.main import _build_parser


def make_core_services(tmp_path: Path, assets: list[AssetDefinition]) -> CoreServices:
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
        assets=AssetsConfig(assets=assets, required_for_episode=[]),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    return CoreServices(config=config, asset_manager=AssetManager(config))


# -- _run_asset_list --------------------------------------------------------------

def test_run_asset_list_empty(tmp_path):
    services = make_core_services(tmp_path, assets=[])

    result = _run_asset_list(services)

    assert result["success"] is True
    assert result["assets"] == []


def test_run_asset_list_preserves_config_declaration_order(tmp_path):
    services = make_core_services(
        tmp_path,
        assets=[
            AssetDefinition(asset_id="RLG-003", description="Sponsor bug", filename="sponsor_bug.png"),
            AssetDefinition(asset_id="RLG-001", description="Lower third", filename="lower_third.png"),
        ],
    )

    result = _run_asset_list(services)

    # Declared RLG-003 first, RLG-001 second — the CLI must not re-sort.
    assert [a["asset_id"] for a in result["assets"]] == ["RLG-003", "RLG-001"]


def test_run_asset_list_serializes_all_three_fields(tmp_path):
    services = make_core_services(
        tmp_path,
        assets=[AssetDefinition(asset_id="RLG-001", description="Lower third", filename="lower_third.png")],
    )

    result = _run_asset_list(services)

    assert result["assets"] == [
        {"asset_id": "RLG-001", "description": "Lower third", "filename": "lower_third.png"}
    ]


# -- _print_asset_list_result ------------------------------------------------------

def test_print_asset_list_result_empty(capsys):
    _print_asset_list_result({"success": True, "assets": []})

    out = capsys.readouterr().out
    assert "No assets found." in out


def test_print_asset_list_result_multiple(capsys):
    _print_asset_list_result(
        {
            "success": True,
            "assets": [
                {"asset_id": "RLG-001", "description": "Lower third", "filename": "lower_third.png"},
                {"asset_id": "RLG-002", "description": "Show open bumper", "filename": "show_open.mov"},
            ],
        }
    )

    out = capsys.readouterr().out
    assert "RLG-001" in out
    assert "RLG-002" in out
    assert "Lower third" in out
    assert "2 asset(s)." in out


# -- argument parsing -----------------------------------------------------------

def test_parser_asset_list_takes_no_arguments():
    parser = _build_parser()
    args = parser.parse_args(["asset", "list"])
    assert args.resource == "asset"
    assert args.action == "list"


# -- main() end-to-end: proves genuine Resolve/DB independence -----------------

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
    (config_dir / "assets.yaml").write_text(
        "assets:\n"
        '  - asset_id: "RLG-001"\n'
        '    description: "Lower third"\n'
        '    filename: "lower_third.png"\n'
        "required_for_episode: []\n"
    )
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir


def test_main_asset_list_end_to_end_without_mock_resolve_or_db_path(tmp_path, monkeypatch, capsys):
    """No --mock-resolve, no REDLINE_DB_PATH set at all — an `episode`
    command in this same environment would either fail (real Resolve not
    running in this sandbox) or create a stray redline.db. `asset list`
    must do neither, because it's routed through CoreServices, which never
    touches Resolve or SQLite.
    """
    config_dir = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("REDLINE_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["asset", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLG-001" in out
    assert "Lower third" in out
    assert not (tmp_path / "redline.db").exists()


def test_main_asset_list_empty_is_success(tmp_path, monkeypatch, capsys):
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
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("REDLINE_DB_PATH", raising=False)

    exit_code = cli_main.main(["asset", "list"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No assets found." in out
