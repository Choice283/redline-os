"""Archive MCP tools — thin wrappers around ArchiveManager."""
from __future__ import annotations

from redline_core.archive.exceptions import ArchiveError, EpisodeAlreadyArchivedError
from redline_core.archive.manager import ArchiveManager
from redline_core.db.models import ArchiveRecord
from redline_core.episode.exceptions import EpisodeNotFoundError


def _archive_to_dict(record: ArchiveRecord) -> dict:
    return {
        "episode_id": record.episode_id,
        "archive_path": record.archive_path,
        "archived_at": record.archived_at,
    }


def _archive_episode(manager: ArchiveManager, episode_id: str) -> dict:
    try:
        record = manager.archive_episode(episode_id)
        return {"success": True, "archive": _archive_to_dict(record)}
    except (EpisodeNotFoundError, EpisodeAlreadyArchivedError, ArchiveError) as exc:
        return {"success": False, "error": str(exc)}


def _list_archives(manager: ArchiveManager) -> dict:
    archives = manager.list_archives()
    return {"success": True, "archives": [_archive_to_dict(a) for a in archives]}


def register(mcp, ctx) -> None:
    """Attach archive tools to `mcp`, bound to ctx.archive_manager."""

    @mcp.tool()
    def archive_episode(episode_id: str) -> dict:
        """Move a finished episode's working folder to archive storage and mark it archived."""
        return _archive_episode(ctx.archive_manager, episode_id)

    @mcp.tool()
    def list_archives() -> dict:
        """List every archived episode."""
        return _list_archives(ctx.archive_manager)
