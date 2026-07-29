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
from pathlib import Path

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


def _run_asset_verify(services: CoreServices, asset_ids: list[str] | None) -> dict:
    """Verify that requested assets are registered and present on disk.

    Read-only: a thin wrapper over the existing, already-tested
    AssetManager.verify_assets_for_episode(). Despite the manager method's
    name, it has no episode parameter and no episode-aware call site
    anywhere in this repo — see docs/CHANGELOG.md for the architecture
    review that corrected this mission's original "asset verify
    <episode_number>" framing. `asset_ids=None` means "use the configured
    required_for_episode default set," exactly the manager's own contract
    — the CLI's dispatch layer is responsible for converting an
    argparse-empty list to None before this function ever sees it (`[]`
    and `None` are NOT equivalent to the manager: `[]` means "verify zero
    assets," not "use the default").

    verify_assets_for_episode() is called exactly once. The manager's
    returned found/missing lists are the sole authority on each asset's
    status — this function does not re-check the filesystem itself. The
    per-row `path` is a display-only enrichment built from
    config.assets.get(asset_id).filename, never from a second `.is_file()`
    check.
    """
    result = services.asset_manager.verify_assets_for_episode(asset_ids)

    effective_ids = asset_ids if asset_ids is not None else list(services.config.assets.required_for_episode)
    found_ids = {a.asset_id for a in result.found}
    assets_path = Path(services.config.paths.assets_path)

    checked = []
    for asset_id in effective_ids:
        definition = services.config.assets.get(asset_id)
        path = str(assets_path / definition.filename) if definition is not None else None
        status = "found" if asset_id in found_ids else "missing"
        checked.append({"asset_id": asset_id, "status": status, "path": path})

    return {
        "success": True,
        "all_present": result.all_present,
        "found": [a.asset_id for a in result.found],
        "missing": result.missing,
        "checked": checked,
    }


def _print_asset_verify_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Asset Verification".center(49))
    print(_BANNER)
    print()

    checked = result["checked"]
    if not checked:
        print("No assets to verify.")
        return

    print(f"{'ASSET ID':<12}{'STATUS':<10}{'PATH'}")
    found_count = 0
    for item in checked:
        if item["status"] == "found":
            found_count += 1
            status_label = "Found"
        else:
            status_label = "Missing"
        path_label = item["path"] if item["path"] is not None else "(not registered)"
        print(f"{item['asset_id']:<12}{status_label:<10}{path_label}")

    missing_count = len(checked) - found_count
    print()
    print(f"{found_count} found, {missing_count} missing. Verification completed.")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `asset` resource and its actions to the top-level subparsers."""
    asset_parser = subparsers.add_parser("asset", help="Asset registry commands.")
    asset_subparsers = asset_parser.add_subparsers(dest="action", required=True)

    asset_subparsers.add_parser("list", help="List every asset registered in config/assets.yaml (read-only).")

    verify_parser = asset_subparsers.add_parser(
        "verify", help="Verify requested assets are registered and present on disk (read-only)."
    )
    verify_parser.add_argument(
        "asset_ids",
        nargs="*",
        metavar="asset_id",
        help="Asset IDs to verify, e.g. RLG-001 RLG-003. Omit to use config/assets.yaml's required_for_episode set.",
    )


def run(args: argparse.Namespace, services: CoreServices) -> int | None:
    """Dispatch a parsed `asset ...` command. Returns an exit code, or None
    if args.action isn't one this module handles."""
    if args.action == "list":
        result = _run_asset_list(services)
        _print_asset_list_result(result)
        return 0 if result["success"] else 1

    if args.action == "verify":
        # argparse's nargs="*" gives [] when no asset_id is passed, but the
        # manager distinguishes [] ("verify zero assets") from None ("use
        # the configured default") — this conversion is what makes
        # `redline asset verify` with no arguments do the useful thing.
        asset_ids = args.asset_ids if args.asset_ids else None
        result = _run_asset_verify(services, asset_ids)
        _print_asset_verify_result(result)
        return 0 if result["success"] else 1

    return None
