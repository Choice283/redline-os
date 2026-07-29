"""Redline OS CLI entrypoint.

Run it with:
    redline episode create 1                       # real Resolve Studio connection
    redline episode create 1 --mock-resolve        # MockResolveAdapter, no Studio needed
    redline episode scan-ingest 1 --mock-resolve   # read-only ingest-folder scan
    redline episode status 1 --mock-resolve        # read-only persisted-state lookup
    redline episode list --mock-resolve            # read-only list of every episode

This module is a thin entry point only: build the top-level parser,
register each resource group's subparser, configure logging, build the
shared ApplicationServices, dispatch to the resource module, and translate
the result into an exit code. All episode-specific logic lives in
episode_commands.py (mirroring mcp_server/tools/*.py's one-module-per-
resource-group shape). A future second resource group (e.g. `asset`) would
get its own sibling module, registered and dispatched the same way.

The `_run_episode_*`/`_print_episode_*`/`_episode_to_dict` names are
re-exported below for backward compatibility with tests written against
`cli.main` before this split (Missions 1-3) — they're now thin aliases for
the real implementations in episode_commands.py, not duplicated code.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from redline_core.logging.setup import configure_logging
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.runtime.composition import build_application_services

from cli import episode_commands
from cli.episode_commands import (  # noqa: F401 - re-exported for pre-split test compatibility
    _episode_to_dict,
    _print_episode_create_result,
    _print_episode_scan_ingest_result,
    _print_episode_status_result,
    _run_episode_create,
    _run_episode_scan_ingest,
    _run_episode_status,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="redline", description="Redline OS command-line interface.")
    parser.add_argument(
        "--mock-resolve",
        action="store_true",
        help="Use MockResolveAdapter instead of a real Resolve Studio connection "
        "(for trying commands out before you have Studio installed).",
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)
    episode_commands.register_parser(subparsers)

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

        if args.resource == "episode":
            exit_code = episode_commands.run(args, services)
            if exit_code is not None:
                return exit_code

        parser.print_help()
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level transport boundary: never leak a raw traceback
        logger.error("Redline OS CLI command failed.", exc_info=True)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
