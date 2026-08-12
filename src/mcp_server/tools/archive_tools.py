"""Archive MCP tools — thin wrappers around ArchiveManager.

Phase 15 Mission 15F: `archive_create`/`archive_verify` call
`ArchiveManager.create_archive()`/`verify_archive()` directly. The legacy
`archive_episode` tool (a thin wrapper over the now-retired
`ArchiveManager.archive_episode()` compatibility bridge) is no longer
registered here at all -- see docs/CHANGELOG.md's Mission 15F entry for
the full call-site inventory. `archive_create`/`archive_verify`/
`list_archives` are the only archive tools this server exposes.
"""
from __future__ import annotations

from redline_core.archive.exceptions import ArchiveError, ArchiveVerifiedUnregisteredError, EpisodeAlreadyArchivedError
from redline_core.archive.manager import ArchiveManager, ArchiveResult, ArchiveVerificationResult
from redline_core.db.models import ArchiveRecord
from redline_core.episode.exceptions import EpisodeNotFoundError


def _archive_to_dict(record: ArchiveRecord) -> dict:
    """Used only by `list_archives()` — ArchiveManager.list_archives()
    still returns raw ArchiveRecord rows (legacy and Rev1 alike).
    `archive_id`/`archive_state` (Mission 15F) let a caller distinguish a
    legacy row from a Rev1 `complete` row without a second call."""
    return {
        "episode_id": record.episode_id,
        "archive_path": record.archive_path,
        "archived_at": record.archived_at,
        "archive_id": record.archive_id,
        "archive_state": record.archive_state.value,
    }


def _archive_result_to_dict(result: ArchiveResult) -> dict:
    """Serialize a successful `create_archive()` result. `archived_at` is
    sourced from `result.verified_at`, the same UTC instant recorded as
    the committed archive's `verified_at` in the database."""
    return {
        "episode_id": result.episode_id,
        "archive_id": result.archive_id,
        "archive_path": str(result.archive_path),
        "render_job_id": result.render_job_id,
        "manifest_sha256": result.manifest_sha256,
        "archived_at": result.verified_at,
        "status": "complete",
    }


def _verification_result_to_dict(result: ArchiveVerificationResult) -> dict:
    """Serialize a successful `verify_archive()` result -- same shape the
    CLI's `archive verify` command reports."""
    return {
        "episode_id": result.episode_id,
        "archive_id": result.archive_id,
        "archive_path": str(result.archive_path),
        "manifest_sha256": result.manifest_sha256,
        "verified": result.verified,
        "file_count": result.file_count,
        "directory_count": result.directory_count,
        "total_bytes": result.total_bytes,
    }


def _archive_create(
    manager: ArchiveManager,
    episode_id: str,
    render_job_id: int | None = None,
    manifest_path: str | None = None,
) -> dict:
    """Build, verify, and commit a Rev1 archive for `episode_id` --
    `render_job_id`/`manifest_path` are passed through unchanged to
    `ArchiveManager.create_archive()`, never reinterpreted here.

    `ArchiveVerifiedUnregisteredError` is reported with its own distinct
    `classification`, not collapsed into a generic failure: it means a
    fully verified package was published to disk but database
    registration failed afterward, which the caller needs to know
    explicitly rather than believe nothing happened. No recovery is
    attempted here -- that remains Mission 15H's concern.
    """
    try:
        result = manager.create_archive(episode_id, render_job_id=render_job_id, manifest_path=manifest_path)
        return {"success": True, "archive": _archive_result_to_dict(result)}
    except ArchiveVerifiedUnregisteredError as exc:
        return {
            "success": False,
            "classification": "verified_unregistered",
            "error": str(exc),
            "episode_id": exc.episode_id,
            "archive_id": exc.archive_id,
            "archive_path": exc.archive_path,
            "manifest_path": exc.manifest_path,
            "manifest_sha256": exc.manifest_sha256,
        }
    except (EpisodeNotFoundError, EpisodeAlreadyArchivedError, ArchiveError) as exc:
        return {"success": False, "classification": "error", "error": str(exc)}


def _archive_verify(manager: ArchiveManager, episode_id: str) -> dict:
    """Verify a committed Rev1 archive is still intact. Read-only: never
    mutates the episode, the `archives` row, the source workspace, or the
    archive package; never contacts Resolve."""
    try:
        result = manager.verify_archive(episode_id)
        return {"success": True, "verification": _verification_result_to_dict(result)}
    except ArchiveError as exc:
        return {"success": False, "error": str(exc)}


def _list_archives(manager: ArchiveManager) -> dict:
    archives = manager.list_archives()
    return {"success": True, "archives": [_archive_to_dict(a) for a in archives]}


def register(mcp, ctx) -> None:
    """Attach archive tools to `mcp`, bound to ctx.archive_manager."""

    @mcp.tool()
    def archive_create(episode_id: str, render_job_id: int | None = None, manifest_path: str | None = None) -> dict:
        """Build, verify, and commit a Rev1 archive package for a rendered episode.

        render_job_id is required only when the episode has more than one
        completed render job (never guessed); omit to auto-select the
        episode's single completed render job. manifest_path is a legacy
        fallback only, for an episode built before canonical manifest
        provenance existed -- do not supply it for normally-built episodes.
        """
        return _archive_create(ctx.archive_manager, episode_id, render_job_id, manifest_path)

    @mcp.tool()
    def archive_verify(episode_id: str) -> dict:
        """Verify a committed Rev1 archive package is still intact (read-only)."""
        return _archive_verify(ctx.archive_manager, episode_id)

    @mcp.tool()
    def list_archives() -> dict:
        """List every archived episode."""
        return _list_archives(ctx.archive_manager)
