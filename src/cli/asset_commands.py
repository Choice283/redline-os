"""Asset CLI commands — the second resource group, same shape as
episode_commands.py: `_run_*`/`_print_*` handler pairs with no argparse/
stdout dependency, subparser registration, and a dispatch entrypoint.

Asset commands are routed through `CoreServices`
(redline_core.runtime.composition.build_core_services()), not the full
`ApplicationServices` episode commands use — list_available_assets() needs
nothing but config, so this resource group genuinely never touches SQLite
or Resolve. See composition.py for the rationale.
"""
from __future__ import annotations

import argparse

from redline_core.config.schema import AssetDefinition
from redline_core.runtime.composition import CoreServices

_BANNER = "=" * 49


def _asset_to_dict(asset: AssetDefinition) -> dict:
    """Same three-field shape as the existing, already-committed MCP tool
    (mcp_server/tools/asset_tools.py._list_available_assets) — reused
    rather than reinvented."""
    return {
        "asset_id": asset.asset_id,
        "description": asset.description,
        "filename": asset.filename,
    }


def _run_asset_list(services: CoreServices) -> dict:
    """List every asset registered in config/assets.yaml. Read-only, no
    arguments: a thin wrapper over the existing, already-tested
    AssetManager.list_available_assets(), which has no filtering,
    pagination, or on-disk verification of its own (that's the separate
    verify_assets_for_episode(), a future command) — none is added here
    either. Order is whatever the manager returns (config declaration
    order); this command doesn't re-sort it.
    """
    assets = services.asset_manager.list_available_assets()
    return {"success": True, "assets": [_asset_to_dict(a) for a in assets]}


def _print_asset_list_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Assets".center(49))
    print(_BANNER)
    print()

    assets = result["assets"]
    if not assets:
        print("No assets found.")
        return

    print(f"{'ASSET ID':<12}{'DESCRIPTION':<32}{'FILENAME'}")
    for asset in assets:
        print(f"{asset['asset_id']:<12}{asset['description']:<32}{asset['filename']}")
    print()
    print(f"{len(assets)} asset(s).")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `asset` resource and its actions to the top-level subparsers."""
    asset_parser = subparsers.add_parser("asset", help="Asset registry commands.")
    asset_subparsers = asset_parser.add_subparsers(dest="action", required=True)

    asset_subparsers.add_parser("list", help="List every asset registered in config/assets.yaml (read-only).")


def run(args: argparse.Namespace, services: CoreServices) -> int | None:
    """Dispatch a parsed `asset ...` command. Returns an exit code, or None
    if args.action isn't one this module handles."""
    if args.action == "list":
        result = _run_asset_list(services)
        _print_asset_list_result(result)
        return 0 if result["success"] else 1

    return None
