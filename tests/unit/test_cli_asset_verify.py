"""Tests for the CLI's `asset verify` command.

Read-only wrapper over the existing, already-tested
AssetManager.verify_assets_for_episode(). verify_assets_for_episode() has
no episode parameter and no episode-aware call site anywhere in this repo
(confirmed by architecture review) — Mission 6's original "asset verify
<episode_number>" framing was corrected to `asset verify [asset_id ...]`,
matching the manager's real contract. Routed through CoreServices, same as
`asset list` — no DB, no Resolve.

Every test uses an in-memory RedlineConfig scoped under tmp_path, never
config/assets.yaml directly, so nothing here depends on or writes to the
real repo tree.
"""
from pathlib import Path

import yaml

from redline_core.asset.manager import AssetManager
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
from redline_core.runtime.composition import CoreServices

from cli import main as cli_main
from cli.asset_commands import _print_asset_verify_result, _run_asset_verify
from cli.main import _build_parser


def make_core_services(tmp_path: Path, assets: list[AssetDefinition], required_for_episode: list[str]) -> CoreServices:
    assets_path = tmp_path / "_assets"
    assets_path.mkdir()
    config = RedlineConfig(
        naming=NamingConfig(episode_id_pattern="RLC-E{episode_number:03d}", project_name_pattern="{episode_id}_MASTER"),
        folder_structure=FolderStructureConfig(root_path=str(tmp_path / "_episodes")),
        render_presets=RenderPresetsConfig(presets=[]),
        paths=PathsConfig(
            ingest_path=str(tmp_path / "_ingest"),
            archive_path=str(tmp_path / "_archive"),
            assets_path=str(assets_path),
            master_project_template="RLC_MASTER_TEMPLATE",
        ),
        assets=AssetsConfig(assets=assets, required_for_episode=required_for_episode),
        timeline=TimelineTemplateConfig(timeline_name_pattern="{episode_id}_TIMELINE", markers=[]),
    )
    return CoreServices(config=config, asset_manager=AssetManager(config))


ASSETS = [
    AssetDefinition(asset_id="RLG-001", description="Lower third", filename="lower_third.png"),
    AssetDefinition(asset_id="RLG-002", description="Show open bumper", filename="show_open.mov"),
    AssetDefinition(asset_id="RLG-003", description="Sponsor bug", filename="sponsor_bug.png"),
]


# -- _run_asset_verify -----------------------------------------------------------

def test_verify_default_set_uses_required_for_episode(tmp_path):
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=["RLG-001", "RLG-003"])
    Path(services.config.paths.assets_path, "lower_third.png").write_bytes(b"x")

    result = _run_asset_verify(services, None)

    assert result["success"] is True
    assert [c["asset_id"] for c in result["checked"]] == ["RLG-001", "RLG-003"]
    assert result["checked"][0]["status"] == "found"
    assert result["checked"][1]["status"] == "missing"
    assert result["all_present"] is False


def test_verify_explicit_override_list_and_order(tmp_path):
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=["RLG-001", "RLG-003"])
    Path(services.config.paths.assets_path, "show_open.mov").write_bytes(b"x")

    result = _run_asset_verify(services, ["RLG-002", "RLG-001"])

    # Explicit order preserved, not re-sorted, and not the config default order.
    assert [c["asset_id"] for c in result["checked"]] == ["RLG-002", "RLG-001"]
    assert result["checked"][0]["status"] == "found"
    assert result["checked"][1]["status"] == "missing"


def test_verify_all_present(tmp_path):
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=["RLG-001", "RLG-003"])
    Path(services.config.paths.assets_path, "lower_third.png").write_bytes(b"x")
    Path(services.config.paths.assets_path, "sponsor_bug.png").write_bytes(b"x")

    result = _run_asset_verify(services, None)

    assert result["all_present"] is True
    assert all(c["status"] == "found" for c in result["checked"])


def test_verify_unregistered_asset_id_shows_no_path(tmp_path):
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=[])

    result = _run_asset_verify(services, ["RLG-999"])

    assert result["checked"] == [{"asset_id": "RLG-999", "status": "missing", "path": None}]
    assert result["all_present"] is False


def test_verify_duplicate_ids_preserved_not_collapsed(tmp_path):
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=[])
    Path(services.config.paths.assets_path, "lower_third.png").write_bytes(b"x")

    result = _run_asset_verify(services, ["RLG-001", "RLG-001"])

    assert [c["asset_id"] for c in result["checked"]] == ["RLG-001", "RLG-001"]
    assert len(result["checked"]) == 2
    assert result["found"] == ["RLG-001", "RLG-001"]


def test_verify_path_built_from_config_not_a_second_filesystem_check(tmp_path):
    """The `path` field must come from config.assets.get(asset_id).filename,
    not a fresh .is_file() call — a found asset's path should be shown even
    if this test never creates the file, since status is decided solely by
    the manager's own result, not by this function re-checking disk."""
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=[])

    result = _run_asset_verify(services, ["RLG-001"])

    expected_path = str(Path(services.config.paths.assets_path) / "lower_third.png")
    assert result["checked"] == [{"asset_id": "RLG-001", "status": "missing", "path": expected_path}]


def test_verify_success_is_always_true_even_when_missing(tmp_path):
    services = make_core_services(tmp_path, assets=ASSETS, required_for_episode=["RLG-001"])

    result = _run_asset_verify(services, None)

    assert result["success"] is True
    assert result["all_present"] is False


# -- _print_asset_verify_result ---------------------------------------------------

def test_print_asset_verify_result(capsys):
    _print_asset_verify_result(
        {
            "success": True,
            "all_present": False,
            "found": ["RLG-001"],
            "missing": ["RLG-003"],
            "checked": [
                {"asset_id": "RLG-001", "status": "found", "path": "/assets/lower_third.png"},
                {"asset_id": "RLG-003", "status": "missing", "path": "/assets/sponsor_bug.png"},
                {"asset_id": "RLG-999", "status": "missing", "path": None},
            ],
        }
    )

    out = capsys.readouterr().out
    assert "RLG-001" in out
    assert "Found" in out
    assert "Missing" in out
    assert "(not registered)" in out
    assert "1 found, 2 missing. Verification completed." in out


def test_print_asset_verify_result_empty(capsys):
    _print_asset_verify_result({"success": True, "all_present": True, "found": [], "missing": [], "checked": []})

    out = capsys.readouterr().out
    assert "No assets to verify." in out


# -- argument parsing -----------------------------------------------------------

def test_parser_asset_verify_no_arguments():
    parser = _build_parser()
    args = parser.parse_args(["asset", "verify"])
    assert args.resource == "asset"
    assert args.action == "verify"
    assert args.asset_ids == []


def test_parser_asset_verify_with_ids():
    parser = _build_parser()
    args = parser.parse_args(["asset", "verify", "RLG-001", "RLG-003"])
    assert args.asset_ids == ["RLG-001", "RLG-003"]


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
    (config_dir / "assets.yaml").write_text(
        "assets:\n"
        '  - asset_id: "RLG-001"\n'
        '    description: "Lower third"\n'
        '    filename: "lower_third.png"\n'
        '  - asset_id: "RLG-003"\n'
        '    description: "Sponsor bug"\n'
        '    filename: "sponsor_bug.png"\n'
        "required_for_episode:\n"
        '  - "RLG-001"\n'
        '  - "RLG-003"\n'
    )
    (config_dir / "timeline_template.yaml").write_text(
        'timeline_name_pattern: "{episode_id}_TIMELINE"\nmarkers: []\n'
    )
    return config_dir, assets_path


def test_main_asset_verify_no_arguments_uses_default_set(tmp_path, monkeypatch, capsys):
    """The critical [] -> None conversion, exercised through the real CLI
    entrypoint: no positional args means the configured default set is
    checked, not zero assets."""
    config_dir, assets_path = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    (assets_path / "lower_third.png").write_bytes(b"x")

    exit_code = cli_main.main(["asset", "verify"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLG-001" in out
    assert "RLG-003" in out
    assert "1 found, 1 missing." in out


def test_main_asset_verify_with_explicit_ids(tmp_path, monkeypatch, capsys):
    config_dir, assets_path = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))
    (assets_path / "lower_third.png").write_bytes(b"x")
    (assets_path / "sponsor_bug.png").write_bytes(b"x")

    exit_code = cli_main.main(["asset", "verify", "RLG-001"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "RLG-001" in out
    assert "RLG-003" not in out  # not requested, must not appear
    assert "1 found, 0 missing." in out


def test_main_asset_verify_missing_assets_still_exits_zero(tmp_path, monkeypatch, capsys):
    config_dir, _assets_path = write_isolated_config_dir(tmp_path)
    monkeypatch.setenv("REDLINE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("REDLINE_LOG_DIR", str(tmp_path / "logs"))

    exit_code = cli_main.main(["asset", "verify"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "0 found, 2 missing." in out
