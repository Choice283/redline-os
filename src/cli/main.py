"""Redline OS CLI entrypoint.

Run it with:
    redline episode create 1                       # real Resolve Studio connection
    redline episode create 1 --mock-resolve        # MockResolveAdapter, no Studio needed
    redline episode scan-ingest 1 --mock-resolve   # read-only ingest-folder scan

The underscore-prefixed functions are the actual, unit-testable logic and
have no dependency on argparse or stdout — same split used in
mcp_server/tools/*.py. `main()` is the thin argparse wiring on top.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from redline_core.db.models import Episode
from redline_core.episode.exceptions import EpisodeAlreadyExistsError, EpisodeNotFoundError
from redline_core.logging.setup import configure_logging
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.runtime.composition import ApplicationServices, build_application_services

logger = logging.getLogger(__name__)

_BANNER = "=" * 49


def _episode_to_dict(episode: Episode) -> dict:
    return {
        "episode_number": episode.episode_number,
        "episode_id": episode.episode_id,
        "project_name": episode.project_name,
        "project_path": episode.project_path,
        "folder_path": episode.folder_path,
        "status": episode.status.value,
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="redline", description="Redline OS command-line interface.")
    parser.add_argument(
        "--mock-resolve",
        action="store_true",
        help="Use MockResolveAdapter instead of a real Resolve Studio connection "
        "(for trying commands out before you have Studio installed).",
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)

    episode_parser = subparsers.add_parser("episode", help="Episode lifecycle commands.")
    episode_subparsers = episode_parser.add_subparsers(dest="action", required=True)

    create_parser = episode_subparsers.add_parser("create", help="Create a new episode.")
    create_parser.add_argument("episode_number", type=int, help="Episode number, e.g. 1 for RLC-E001.")

    scan_ingest_parser = episode_subparsers.add_parser(
        "scan-ingest", help="List ingest-folder files matching an episode (read-only)."
    )
    scan_ingest_parser.add_argument("episode_number", type=int, help="Episode number, e.g. 1 for RLC-E001.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    configure_logging(
        log_dir=os.environ.get("REDLINE_LOG_DIR", "./logs"),
        level=os.environ.get("REDLINE_LOG_LEVEL", "INFO"),
    )
    logger.info("Starting Redline OS CLI (mock_resolve=%s)", args.mock_resolve)

    resolve_adapter = MockResolveAdapter() if args.mock_resolve else None

    try:
        services = build_application_services(resolve_adapter=resolve_adapter)

        if args.resource == "episode" and args.action == "create":
            result = _run_episode_create(services, args.episode_number)
            _print_episode_create_result(result)
            return 0 if result["success"] else 1

        if args.resource == "episode" and args.action == "scan-ingest":
            result = _run_episode_scan_ingest(services, args.episode_number)
            _print_episode_scan_ingest_result(result)
            return 0 if result["success"] else 1

        parser.print_help()
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level transport boundary: never leak a raw traceback
        logger.error("Redline OS CLI command failed.", exc_info=True)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
