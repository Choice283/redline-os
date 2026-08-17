"""Redline OS CLI entrypoint.

Run it with:
    redline episode create 1                       # real Resolve Studio connection
    redline episode create 1 --mock-resolve        # MockResolveAdapter, no Studio needed
    redline episode scan-ingest 1 --mock-resolve   # read-only ingest-folder scan
    redline episode status 1 --mock-resolve        # read-only persisted-state lookup
    redline episode list --mock-resolve            # read-only list of every episode
    redline episode organize-bins 1 --mock-resolve # scan ingest + import matches into a Resolve media pool bin
    redline episode build-timeline 1 --mock-resolve # build the episode's timeline and apply configured markers
    redline episode place-clips 1 clip-1 clip-2 --mock-resolve # place already-imported clips onto the timeline
    redline episode validate-manifest episode.yaml  # validate an Episode Manifest V1 file (read-only, no Resolve/DB needed)
    redline --mock-resolve build Episode_0001       # canonical build command, assembly only
    redline --mock-resolve render queue RLC-E001 broadcast_master # queue render only
    redline asset list                              # read-only, config-only, no Resolve/DB needed
    redline asset verify RLG-001 RLG-003            # verify specific assets (omit for the default set)
    redline archive list                            # read-only, config+DB, no Resolve needed
    redline archive episode RLC-E025                # move episode's working folder to archive storage
    redline backup create --reason "pre-maintenance" # Mission 1A: system-of-record backup, no Resolve needed
    redline backup list                              # read-only, config+DB, no Resolve needed
    redline backup verify <backup_id>                 # read-only re-verification, no Resolve needed

This module is a thin entry point only: build the top-level parser,
register each resource group's subparser, configure logging, build
whichever composition path that resource group actually needs, dispatch,
and translate the result into an exit code. All episode-specific logic
lives in episode_commands.py; build-specific logic lives in
build_commands.py; render-specific logic lives in render_commands.py; all
asset-specific logic lives in asset_commands.py; all archive-specific logic
lives in archive_commands.py; all backup-specific logic (Mission 1A;
create/list/verify only -- no restore) lives in backup_commands.py
(mirroring mcp_server/tools/*.py's one-module-per-resource-group shape).

Resource groups don't all share one composition path: `episode` commands
need the full ApplicationServices (DB + Resolve); `asset` commands need
only CoreServices (config only); `archive` commands need PersistenceServices
(config + DB, no Resolve) — see redline_core.runtime.composition for why.
main.py's job is just knowing which builder each resource group needs, not
building any of them twice.

One exception as of Mission 12: `episode validate-manifest` needs only
CoreServices, not the ApplicationServices every other `episode` action
uses — validate_manifest() touches only config, never Resolve or SQLite.
main.py branches on args.action within the `episode` resource for this one
case and dispatches to episode_commands.run_validate_manifest() instead of
episode_commands.run(); see docs/ARCHITECTURE.md for why this stayed a
single targeted branch rather than a general per-action dispatch registry.

One exception as of Mission 38A.1: `build` delays file-backed logging until
after read-only build preflight succeeds, so malformed build requests can fail
without creating SQLite, Resolve connections, or persistent logging artifacts.

The `_run_episode_*`/`_print_episode_*`/`_episode_to_dict` names are
re-exported below for backward compatibility with tests written against
`cli.main` before the Mission 4 split — they're thin aliases for the real
implementations in episode_commands.py, not duplicated code.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from redline_core.logging.setup import configure_logging
from redline_core.resolve.mock import MockResolveAdapter
from redline_core.runtime.composition import (
    build_application_services,
    build_backup_services,
    build_core_services,
    build_persistence_services,
)

from cli import archive_commands, asset_commands, backup_commands, build_commands, episode_commands, render_commands
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


def _configure_cli_logging(args: argparse.Namespace) -> None:
    configure_logging(
        log_dir=os.environ.get("REDLINE_LOG_DIR", "./logs"),
        level=os.environ.get("REDLINE_LOG_LEVEL", "INFO"),
    )
    logger.info("Starting Redline OS CLI (mock_resolve=%s)", args.mock_resolve)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="redline", description="Redline OS command-line interface.")
    parser.add_argument(
        "--mock-resolve",
        action="store_true",
        help="Use MockResolveAdapter instead of a real Resolve Studio connection "
        "(for trying commands out before you have Studio installed). Ignored by "
        "commands that don't touch Resolve at all, e.g. `asset list`.",
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)
    episode_commands.register_parser(subparsers)
    asset_commands.register_parser(subparsers)
    archive_commands.register_parser(subparsers)
    backup_commands.register_parser(subparsers)
    build_commands.register_parser(subparsers)
    render_commands.register_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.resource == "build":
            core_services = build_core_services()
            preflight_result = build_commands.prepare_build(args, core_services)
            if not preflight_result["success"]:
                build_commands._print_build_result(preflight_result)
                return preflight_result["exit_code"]

            _configure_cli_logging(args)
            resolve_adapter = MockResolveAdapter() if args.mock_resolve else None
            services = build_application_services(
                resolve_adapter=resolve_adapter,
                config=core_services.config,
            )
            exit_code = build_commands.run(
                args,
                services,
                prepared_request=preflight_result["prepared_request"],
            )
            if exit_code is not None:
                return exit_code
            parser.print_help()
            return 1

        _configure_cli_logging(args)

        if args.resource == "episode":
            if args.action == "validate-manifest":
                core_services = build_core_services()
                exit_code = episode_commands.run_validate_manifest(args, core_services)
            else:
                resolve_adapter = MockResolveAdapter() if args.mock_resolve else None
                services = build_application_services(resolve_adapter=resolve_adapter)
                exit_code = episode_commands.run(args, services)
            if exit_code is not None:
                return exit_code

        if args.resource == "asset":
            core_services = build_core_services()
            exit_code = asset_commands.run(args, core_services)
            if exit_code is not None:
                return exit_code

        if args.resource == "archive":
            persistence_services = build_persistence_services()
            exit_code = archive_commands.run(args, persistence_services)
            if exit_code is not None:
                return exit_code

        if args.resource == "backup":
            backup_services = build_backup_services()
            exit_code = backup_commands.run(args, backup_services)
            if exit_code is not None:
                return exit_code

        if args.resource == "render":
            resolve_adapter = MockResolveAdapter() if args.mock_resolve else None
            services = build_application_services(resolve_adapter=resolve_adapter)
            exit_code = render_commands.run(args, services)
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
