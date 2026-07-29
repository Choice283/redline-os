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

Mission 7 added `archive list` (read-only). Mission 8 adds the mutating
`archive episode <episode_id>` — a thin wrapper over the existing,
already-tested ArchiveManager.archive_episode(). This command reports the
returned ArchiveRecord, not the manager's internal steps: no progress
checklist is printed, deliberately, so this CLI output stays correct even
if ArchiveManager's internal implementation (validation order, whether
the three DB writes become transactional, etc.) changes later. That
non-transactional behavior is a documented property of ArchiveManager
itself (see docs/ARCHITECTURE.md) — not part of this CLI's contract, and
not mentioned in README's user-facing usage.
"""
from __future__ import annotations

import argparse

from redline_core.archive.exceptions import ArchiveError, EpisodeAlreadyArchivedError
from redline_core.db.models import ArchiveRecord
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.runtime.composition import PersistenceServices

_BANNER = "=" * 49


def _archive_to_dict(record: ArchiveRecord) -> dict:
    """Same three-field shape as the existing, already-committed MCP tool
    (mcp_server/tools/archive_tools.py._archive_to_dict) — reused rather
    than reinvented."""
    return {
        "episode_id": record.episode_id,
        "archive_path": record.archive_path,
        "archived_at": record.archived_at,
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
    """Archive one episode: move its working folder to cold storage, record
    it, and mark the episode ARCHIVED. A thin wrapper over the existing,
    already-tested ArchiveManager.archive_episode() — `episode_id` is passed
    through completely unchanged (no type coercion, no
    episode_number-to-episode_id translation; the manager has always taken
    a raw string identifier, and no such translation exists anywhere in
    redline_core).

    On success, the result dict carries the manager's own returned
    ArchiveRecord, serialized via the existing _archive_to_dict — no
    additional Database or filesystem reads are performed here; the record
    already carries everything this command needs to report.

    On failure, the exact exception tuple the existing MCP tool
    (mcp_server/tools/archive_tools.py._archive_episode) already catches is
    mirrored here, and `str(exc)` is returned completely unchanged — no
    translation, no enrichment. The manager stays the sole authority on
    both what failed and how to describe it.
    """
    try:
        record = services.archive_manager.archive_episode(episode_id)
        return {"success": True, "archive": _archive_to_dict(record)}
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
