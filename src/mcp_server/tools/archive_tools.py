"""Archive MCP tools — thin wrappers around ArchiveManager."""
from __future__ import annotations

from redline_core.archive.exceptions import ArchiveError, EpisodeAlreadyArchivedError
from redline_core.archive.manager import ArchiveManager, ArchiveResult
from redline_core.db.models import ArchiveRecord
from redline_core.episode.exceptions import EpisodeNotFoundError


def _archive_to_dict(record: ArchiveRecord) -> dict:
    """Used only by `list_archives()` — ArchiveManager.list_archives()
    still returns raw ArchiveRecord rows (legacy and Rev1 alike),
    unchanged by Phase 15 Mission 15E."""
    return {
        "episode_id": record.episode_id,
        "archive_path": record.archive_path,
        "archived_at": record.archived_at,
    }


def _archive_result_to_dict(result: ArchiveResult) -> dict:
    """Same three-field shape as _archive_to_dict(), sourced from a
    Mission 15E ArchiveResult instead: archive_episode() (Mission 15E's
    temporary compatibility wrapper over create_archive()) returns the
    former, not a raw ArchiveRecord. `archived_at` is sourced from
    `result.verified_at`, the same UTC instant recorded as the committed
    archive's verified_at in the database."""
    return {
        "episode_id": result.episode_id,
        "archive_path": str(result.archive_path),
        "archived_at": result.verified_at,
    }


def _archive_episode(manager: ArchiveManager, episode_id: str) -> dict:
    try:
        result = manager.archive_episode(episode_id)
        return {"success": True, "archive": _archive_result_to_dict(result)}
    except (EpisodeNotFoundError, EpisodeAlreadyArchivedError, ArchiveError) as exc:
        return {"success": False, "error": str(exc)}


def _list_archives(manager: ArchiveManager) -> dict:
    archives = manager.list_archives()
    return {"success": True, "archives": [_archive_to_dict(a) for a in archives]}


def register(mcp, ctx) -> None:
    """Attach archive tools to `mcp`, bound to ctx.archive_manager."""

    @mcp.tool()
    def archive_episode(episode_id: str) -> dict:
        """Archive a finished, rendered episode: builds a verified Rev1
        package and commits it to the database (temporary compatibility
        wrapper over ArchiveManager.create_archive(); does not move or
        delete the working folder)."""
        return _archive_episode(ctx.archive_manager, episode_id)

    @mcp.tool()
    def list_archives() -> dict:
        """List every archived episode."""
        return _list_archives(ctx.archive_manager)
