"""Archive CLI commands — the third resource group, same shape as
episode_commands.py and asset_commands.py: `_run_*`/`_print_*` handler
pairs with no argparse/stdout dependency, subparser registration, and a
dispatch entrypoint.

Archive commands are routed through `PersistenceServices`
(redline_core.runtime.composition.build_persistence_services()), not the
full `ApplicationServices` episode commands use, nor the config-only
`CoreServices` asset commands use — list_archives() needs a connected
Database but never touches Resolve. See composition.py for the rationale.

Mission 7 adds `archive list` only. The mutating `archive episode
<episode_id>` command is deliberately deferred to Mission 8 — it's a
different, mutating operation (moves a folder, writes three DB records)
with its own failure modes and its own contract review, sequenced after
this strictly-smaller read-only command per the same "smallest capability
first" discipline every prior mission followed.
"""
from __future__ import annotations

import argparse

from redline_core.db.models import ArchiveRecord
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


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `archive` resource and its actions to the top-level subparsers."""
    archive_parser = subparsers.add_parser("archive", help="Archive commands.")
    archive_subparsers = archive_parser.add_subparsers(dest="action", required=True)

    archive_subparsers.add_parser("list", help="List every archived episode (read-only).")


def run(args: argparse.Namespace, services: PersistenceServices) -> int | None:
    """Dispatch a parsed `archive ...` command. Returns an exit code, or
    None if args.action isn't one this module handles."""
    if args.action == "list":
        result = _run_archive_list(services)
        _print_archive_list_result(result)
        return 0 if result["success"] else 1

    return None
