"""Asset MCP tools — thin wrappers around AssetManager."""
from __future__ import annotations

from redline_core.asset.manager import AssetManager


def _list_available_assets(manager: AssetManager) -> dict:
    assets = manager.list_available_assets()
    return {
        "success": True,
        "assets": [
            {"asset_id": a.asset_id, "description": a.description, "filename": a.filename} for a in assets
        ],
    }


def _verify_assets_for_episode(manager: AssetManager, asset_ids: list[str] | None = None) -> dict:
    result = manager.verify_assets_for_episode(asset_ids)
    return {
        "success": True,
        "all_present": result.all_present,
        "found": [a.asset_id for a in result.found],
        "missing": result.missing,
    }


def register(mcp, ctx) -> None:
    """Attach asset tools to `mcp`, bound to ctx.asset_manager."""

    @mcp.tool()
    def list_available_assets() -> dict:
        """List every asset registered in config/assets.yaml (not necessarily present on disk)."""
        return _list_available_assets(ctx.asset_manager)

    @mcp.tool()
    def verify_assets_for_episode(asset_ids: list[str] | None = None) -> dict:
        """Check whether required assets exist on disk. Omit asset_ids to use the configured default set."""
        return _verify_assets_for_episode(ctx.asset_manager, asset_ids)
