"""Episode MCP tools — thin wrappers around EpisodeManager.

The underscore-prefixed functions are the actual, unit-testable logic and
have no dependency on the `mcp` package — they run in the standard test
suite without the optional [mcp] extra installed. `register()` attaches
them to a FastMCP server instance as MCP tools with clean, LLM-facing names.
"""
from __future__ import annotations

from redline_core.config.schema import RedlineConfig
from redline_core.db.models import Episode
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeNotFoundError
from redline_core.episode.manager import EpisodeManager
from redline_core.manifest import ManifestError, load_manifest, validate_manifest as validate_episode_manifest


def _episode_to_dict(episode: Episode) -> dict:
    return {
        "episode_number": episode.episode_number,
        "episode_id": episode.episode_id,
        "project_name": episode.project_name,
        "project_path": episode.project_path,
        "folder_path": episode.folder_path,
        "status": episode.status.value,
    }


def _create_episode(manager: EpisodeManager, episode_number: int) -> dict:
    try:
        episode = manager.create_episode(episode_number)
        return {"success": True, "episode": _episode_to_dict(episode)}
    except EpisodeAlreadyExistsError as exc:
        return {"success": False, "error": str(exc)}


def _get_episode_status(manager: EpisodeManager, episode_number: int) -> dict:
    try:
        episode = manager.get_episode_status(episode_number)
        return {"success": True, "episode": _episode_to_dict(episode)}
    except EpisodeNotFoundError as exc:
        return {"success": False, "error": str(exc)}


def _list_episodes(manager: EpisodeManager) -> dict:
    episodes = manager.list_episodes()
    return {"success": True, "episodes": [_episode_to_dict(e) for e in episodes]}


def _validate_manifest(config: RedlineConfig, manifest_path: str) -> dict:
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ValueError("manifest_path must be a non-empty string.")

    try:
        manifest = load_manifest(manifest_path)
        plan = validate_episode_manifest(manifest, manifest_path=manifest_path, config=config)
    except ManifestError as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "manifest_path": manifest_path,
        "valid": True,
        "episode_id": plan.episode_id,
        "bin_name": plan.bin_name,
        "media_paths": list(plan.media_paths),
        "media_count": len(plan.media_paths),
        "markers": [
            {"frame": marker.frame, "color": marker.color, "name": marker.name, "note": marker.note}
            for marker in plan.markers
        ],
        "marker_count": len(plan.markers),
    }


def register(mcp, ctx) -> None:
    """Attach episode tools to `mcp`, bound to ctx.episode_manager."""

    @mcp.tool()
    def create_episode(episode_number: int) -> dict:
        """Create a new Redline episode: DB record, working folder, and a duplicated Resolve project."""
        return _create_episode(ctx.episode_manager, episode_number)

    @mcp.tool()
    def get_episode_status(episode_number: int) -> dict:
        """Get the current pipeline status of a tracked episode."""
        return _get_episode_status(ctx.episode_manager, episode_number)

    @mcp.tool()
    def list_episodes() -> dict:
        """List every tracked episode, ordered by episode number."""
        return _list_episodes(ctx.episode_manager)

    @mcp.tool()
    def validate_manifest(manifest_path: str) -> dict:
        """Validate an Episode Manifest V1 file without touching Resolve or SQLite."""
        return _validate_manifest(ctx.config, manifest_path)
