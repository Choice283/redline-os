"""Episode CLI commands.

Everything episode-related that used to live directly in cli/main.py: the
argparse subparser registration, the testable `_run_*`/`_print_*` handler
pairs (same split as mcp_server/tools/*.py — no argparse/stdout dependency
in the `_run_*` half), and the dispatch entrypoint main.py calls into.

This module holds only episode command logic — no new abstractions (no
generic command registry, base command classes, shared result dataclasses,
or printer frameworks). If a second resource group (e.g. `asset`) is added
later, it gets its own sibling module of the same shape, not a shared
framework retrofitted onto this one.
"""
from __future__ import annotations

import argparse

from redline_core.db.models import Episode
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeNotFoundError
from redline_core.runtime.composition import ApplicationServices

_BANNER = "=" * 49


def _episode_to_dict(episode: Episode) -> dict:
    """episode.created_at/updated_at are already TEXT columns (SQLite's
    datetime('now'), e.g. "2026-07-29 09:41:18") by the time they reach the
    Episode dataclass — plain deterministic strings already, not Python
    datetime objects, so no reformatting is introduced here. That's the
    same representation used everywhere else in redline_core; inventing a
    second datetime string format for just this dict would be new,
    undemonstrated complexity, not reuse.
    """
    return {
        "id": episode.id,
        "episode_number": episode.episode_number,
        "episode_id": episode.episode_id,
        "project_name": episode.project_name,
        "project_path": episode.project_path,
        "folder_path": episode.folder_path,
        "status": episode.status.value,
        "created_at": episode.created_at,
        "updated_at": episode.updated_at,
    }


def _run_episode_create(services: ApplicationServices, episode_number: int) -> dict:
    """Create an episode and return a plain result dict.

    No printing here — this is the testable core, mirroring the pattern in
    mcp_server/tools/episode_tools.py._create_episode. Deliberately a
    separate implementation rather than importing that MCP-transport
    module: the CLI is a sibling transport, not a consumer of the MCP one.
    """
    try:
        episode = services.episode_manager.create_episode(episode_number)
        return {"success": True, "episode": _episode_to_dict(episode)}
    except EpisodeAlreadyExistsError as exc:
        return {"success": False, "error": str(exc)}


def _print_episode_create_result(result: dict) -> None:
    """Render the checklist. Deliberately post-hoc, not a live progress bar:

    EpisodeManager.create_episode() has no per-step callback, and adding one
    is out of scope for this slice (see docs/ARCHITECTURE.md). By the time
    we have a successful result, every step below has already happened.
    """
    print(_BANNER)
    print("REDLINE OS — Episode Creation".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Episode creation failed: {result['error']}")
        return

    episode = result["episode"]
    print(f"Episode: {episode['episode_id']}")
    print()
    print("✓ Configuration loaded")
    print("✓ Connected to Resolve")
    print("✓ Episode record created")
    print(f"✓ Working folder created: {episode['folder_path']}")
    print(f"✓ Resolve project initialized: {episode['project_path']}")
    print()
    print(f"Episode {episode['episode_id']} is ready.")


def _run_episode_scan_ingest(services: ApplicationServices, episode_number: int) -> dict:
    """Scan the shared ingest folder for files matching one episode.

    Read-only: no classification, deduplication, copying, moving,
    importing, or registration — purely a thin wrapper over the existing,
    already-tested MediaManager.scan_ingest_for_episode(), which matches by
    episode-ID substring in the filename regardless of extension. A missing
    ingest folder is not distinguished from "no matches" — that's the
    existing method's behavior (a logged warning, not an exception), and
    this CLI slice doesn't invent a new distinction it doesn't have.
    """
    try:
        episode = services.episode_manager.get_episode_status(episode_number)
    except EpisodeNotFoundError as exc:
        return {"success": False, "error": str(exc)}

    matched_paths = services.media_manager.scan_ingest_for_episode(episode.episode_id)
    return {
        "success": True,
        "episode_id": episode.episode_id,
        "ingest_path": str(services.config.paths.ingest_path),
        "matched_files": [p.name for p in matched_paths],
    }


def _print_episode_scan_ingest_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Ingest Scan".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Ingest scan failed: {result['error']}")
        return

    print(f"Episode: {result['episode_id']}")
    print(f"Ingest path: {result['ingest_path']}")
    print()
    print(f"Matched files: {len(result['matched_files'])}")
    print()
    for filename in result["matched_files"]:
        print(f"✓ {filename}")
    if result["matched_files"]:
        print()
    print("Scan complete. No files were classified, deduplicated, copied, moved, imported, or registered.")


def _run_episode_status(services: ApplicationServices, episode_number: int) -> dict:
    """Look up an episode's persisted state. Read-only, no computed fields:

    exactly what get_episode_status() (already existing, already tested)
    returns, serialized via the shared _episode_to_dict(). No health
    checks, readiness inference, media counts, asset verification, or
    build validation — those are all separate, future capabilities.
    """
    try:
        episode = services.episode_manager.get_episode_status(episode_number)
    except EpisodeNotFoundError as exc:
        return {"success": False, "error": str(exc)}

    return {"success": True, "episode": _episode_to_dict(episode)}


def _print_episode_status_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Episode Status".center(49))
    print(_BANNER)
    print()

    if not result["success"]:
        print(f"Episode status lookup failed: {result['error']}")
        return

    episode = result["episode"]
    print(f"Episode: {episode['episode_id']}")
    print()
    print(f"Status: {episode['status'].capitalize()}")
    print(f"Database ID: {episode['id']}")
    print(f"Working folder: {episode['folder_path']}")
    print(f"Resolve project: {episode['project_path']}")
    print(f"Created: {episode['created_at']}")
    print(f"Last updated: {episode['updated_at']}")


def _run_episode_list(services: ApplicationServices) -> dict:
    """List every tracked episode. Read-only, no arguments:

    a thin wrapper over the existing, already-tested
    EpisodeManager.list_episodes(), which itself has no filtering,
    pagination, or alternate ordering — it always returns every episode,
    ordered by episode_number. This command doesn't add any of those
    either; none is demonstrated as needed yet.
    """
    episodes = services.episode_manager.list_episodes()
    return {"success": True, "episodes": [_episode_to_dict(e) for e in episodes]}


def _print_episode_list_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS — Episodes".center(49))
    print(_BANNER)
    print()

    episodes = result["episodes"]
    if not episodes:
        print("No episodes found.")
        return

    print(f"{'EPISODE':<13}{'STATUS':<12}{'CREATED'}")
    for episode in episodes:
        print(f"{episode['episode_id']:<13}{episode['status'].capitalize():<12}{episode['created_at']}")
    print()
    print(f"{len(episodes)} episode(s).")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `episode` resource and its actions to the top-level subparsers."""
    episode_parser = subparsers.add_parser("episode", help="Episode lifecycle commands.")
    episode_subparsers = episode_parser.add_subparsers(dest="action", required=True)

    create_parser = episode_subparsers.add_parser("create", help="Create a new episode.")
    create_parser.add_argument("episode_number", type=int, help="Episode number, e.g. 1 for RLC-E001.")

    scan_ingest_parser = episode_subparsers.add_parser(
        "scan-ingest", help="List ingest-folder files matching an episode (read-only)."
    )
    scan_ingest_parser.add_argument("episode_number", type=int, help="Episode number, e.g. 1 for RLC-E001.")

    status_parser = episode_subparsers.add_parser("status", help="Show an episode's persisted state (read-only).")
    status_parser.add_argument("episode_number", type=int, help="Episode number, e.g. 1 for RLC-E001.")

    episode_subparsers.add_parser("list", help="List every tracked episode (read-only).")


def run(args: argparse.Namespace, services: ApplicationServices) -> int | None:
    """Dispatch a parsed `episode ...` command. Returns an exit code, or
    None if args.action isn't one this module handles (shouldn't happen,
    since argparse's subparsers are required=True, but main.py still checks
    for None rather than assuming)."""
    if args.action == "create":
        result = _run_episode_create(services, args.episode_number)
        _print_episode_create_result(result)
        return 0 if result["success"] else 1

    if args.action == "scan-ingest":
        result = _run_episode_scan_ingest(services, args.episode_number)
        _print_episode_scan_ingest_result(result)
        return 0 if result["success"] else 1

    if args.action == "status":
        result = _run_episode_status(services, args.episode_number)
        _print_episode_status_result(result)
        return 0 if result["success"] else 1

    if args.action == "list":
        result = _run_episode_list(services)
        _print_episode_list_result(result)
        return 0 if result["success"] else 1

    return None
