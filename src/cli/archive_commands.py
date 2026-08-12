"""Archive CLI commands — the third resource group, same shape as
episode_commands.py and asset_commands.py: `_run_*`/`_print_*` handler
pairs with no argparse/stdout dependency, subparser registration, and a
dispatch entrypoint.

Archive commands are routed through `PersistenceServices`
(redline_core.runtime.composition.build_persistence_services()), not the
full `ApplicationServices` episode commands use, nor the config-only
`CoreServices` asset commands use — list_archives()/archive_episode() need
a connected Database but never touch Resolve. See composition.py for the
rationale.

Mission 7 added `archive list` (read-only). Mission 8 added the mutating
`archive episode <episode_id>` as a thin wrapper over
ArchiveManager.archive_episode(). As of Phase 15 Mission 15E,
archive_episode() is itself a temporary, non-destructive compatibility
wrapper over the new Rev1 orchestration entry point
(ArchiveManager.create_archive()) — this command still calls it by name
and still reports only the returned result's three fields (episode_id/
archive_path/archived_at), not the manager's internal steps, deliberately
unchanged so this CLI stays correct regardless of ArchiveManager's
internals. Migrating this command to call create_archive() directly (and
adding `archive create`/`archive verify`) is Mission 15F's job, not this
one's.
"""
from __future__ import annotations

import argparse

from redline_core.archive.exceptions import ArchiveError, EpisodeAlreadyArchivedError
from redline_core.archive.manager import ArchiveResult
from redline_core.db.models import ArchiveRecord
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.runtime.composition import PersistenceServices

_BANNER = "=" * 49


def _archive_to_dict(record: ArchiveRecord) -> dict:
    """Same three-field shape as the existing, already-committed MCP tool
    (mcp_server/tools/archive_tools.py._archive_to_dict) — reused rather
    than reinvented. Used only by `archive list` (`ArchiveManager.list_archives()`
    still returns raw `ArchiveRecord` rows — legacy and Rev1 alike — unchanged
    by Mission 15E)."""
    return {
        "episode_id": record.episode_id,
        "archive_path": record.archive_path,
        "archived_at": record.archived_at,
    }


def _archive_result_to_dict(result: ArchiveResult) -> dict:
    """Same three-field output shape as `_archive_to_dict()` above, sourced
    from a Mission 15E `ArchiveResult` instead of a raw `ArchiveRecord` --
    `archive_episode()` (Mission 15E's temporary compatibility wrapper
    over `create_archive()`) returns the former, not the latter, so this
    command needs its own small mapping rather than reusing
    `_archive_to_dict()` unchanged. `archived_at` is sourced from
    `result.verified_at`: the same UTC instant Mission 15E recorded as the
    committed archive's `verified_at` in the database."""
    return {
        "episode_id": result.episode_id,
        "archive_path": str(result.archive_path),
        "archived_at": result.verified_at,
    }


def _run_archive_list(services: PersistenceServices) -> dict:
    """List every archived episode. Read-only, no arguments: a thin
    wrapper over the existing, already-tested ArchiveManager.list_archives(),
    which has no filtering or pagination of its own. Order is whatever the
    manager/DB returns (ORDER BY archived_at, per database.py); this
    command doesn't re-sort it.
    """
    archives = services.archive_manager.list_archives()
    return {"success": True, "archives": [_archive_to_dict(a) for a in archives]}


def _print_archive_list_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Archives".center(49))
    print(_BANNER)
    print()

    archives = result["archives"]
    if not archives:
        print("No archives found.")
        return

    print(f"{'EPISODE ID':<14}{'ARCHIVE PATH':<40}{'ARCHIVED AT'}")
    for archive in archives:
        print(f"{archive['episode_id']:<14}{archive['archive_path']:<40}{archive['archived_at']}")
    print()
    print(f"{len(archives)} archive(s).")


def _run_archive_episode(services: PersistenceServices, episode_id: str) -> dict:
    """Archive one episode via ArchiveManager.archive_episode() — Mission
    15E's temporary, non-destructive compatibility wrapper over
    create_archive(): builds a verified Rev1 filesystem package and
    commits it to the database, leaving the source workspace and
    `folder_path` untouched. `episode_id` is passed through completely
    unchanged (no type coercion, no episode_number-to-episode_id
    translation; the manager has always taken a raw string identifier,
    and no such translation exists anywhere in redline_core).

    On success, the result dict is built from the manager's returned
    ArchiveResult via _archive_result_to_dict — no additional Database or
    filesystem reads are performed here; the result already carries
    everything this command needs to report.

    On failure, the exact exception tuple the existing MCP tool
    (mcp_server/tools/archive_tools.py._archive_episode) already catches is
    mirrored here, and `str(exc)` is returned completely unchanged — no
    translation, no enrichment. The manager stays the sole authority on
    both what failed and how to describe it.
    """
    try:
        result = services.archive_manager.archive_episode(episode_id)
        return {"success": True, "archive": _archive_result_to_dict(result)}
    except (EpisodeNotFoundError, EpisodeAlreadyArchivedError, ArchiveError) as exc:
        return {"success": False, "error": str(exc)}


def _print_archive_episode_result(result: dict) -> None:
    """Report the outcome, not the algorithm: only the three fields on the
    returned ArchiveRecord are shown. No per-step progress/checklist output
    is printed — deliberately, so this stays correct even if
    ArchiveManager's internal steps change later.
    """
    print(_BANNER)
    print("REDLINE OS — Archive Episode".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Archive failed: {result['error']}")
        return

    archive = result["archive"]
    print(f"Episode:      {archive['episode_id']}")
    print(f"Archive path: {archive['archive_path']}")
    print(f"Archived at:  {archive['archived_at']}")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `archive` resource and its actions to the top-level subparsers."""
    archive_parser = subparsers.add_parser("archive", help="Archive commands.")
    archive_subparsers = archive_parser.add_subparsers(dest="action", required=True)

    archive_subparsers.add_parser("list", help="List every archived episode (read-only).")

    episode_parser = archive_subparsers.add_parser(
        "episode", help="Move a finished episode's working folder to archive storage and mark it archived."
    )
    episode_parser.add_argument("episode_id", help="Episode ID to archive, e.g. RLC-E025.")


def run(args: argparse.Namespace, services: PersistenceServices) -> int | None:
    """Dispatch a parsed `archive ...` command. Returns an exit code, or
    None if args.action isn't one this module handles."""
    if args.action == "list":
        result = _run_archive_list(services)
        _print_archive_list_result(result)
        return 0 if result["success"] else 1

    if args.action == "episode":
        result = _run_archive_episode(services, args.episode_id)
        _print_archive_episode_result(result)
        return 0 if result["success"] else 1

    return None
