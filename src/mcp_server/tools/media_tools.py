"""Media MCP tools — thin wrappers around MediaManager."""
from __future__ import annotations

from redline_core.media.manager import MediaManager


def _scan_ingest_for_episode(manager: MediaManager, episode_id: str) -> dict:
    matches = manager.scan_ingest_for_episode(episode_id)
    return {"success": True, "matches": [str(p) for p in matches]}


def _organize_bins(manager: MediaManager, project_name: str, episode_id: str, bin_name: str = "footage") -> dict:
    clip_ids = manager.organize_bins(project_name, episode_id, bin_name)
    return {"success": True, "clip_ids": clip_ids, "clip_count": len(clip_ids)}


def register(mcp, ctx) -> None:
    """Attach media tools to `mcp`, bound to ctx.media_manager."""

    @mcp.tool()
    def scan_ingest_for_episode(episode_id: str) -> dict:
        """Preview which ingest files match an episode ID, without importing anything."""
        return _scan_ingest_for_episode(ctx.media_manager, episode_id)

    @mcp.tool()
    def organize_bins(project_name: str, episode_id: str, bin_name: str = "footage") -> dict:
        """Scan ingest for this episode's media and import matches into the Resolve project's media pool bin."""
        return _organize_bins(ctx.media_manager, project_name, episode_id, bin_name)
