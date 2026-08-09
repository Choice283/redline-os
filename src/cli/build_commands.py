"""Build CLI command.

Thin transport over redline_core.build.BuildOrchestrator. This module owns
argument parsing, output formatting, and exit behavior only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from redline_core.build import (
    BuildPreflight,
    BuildOrchestrator,
    BuildResult,
    BuildTargetError,
    ManifestIdentityMismatchError,
    ManifestResolutionError,
    PreparedBuildRequest,
)
from redline_core.episode.exceptions import EpisodeError
from redline_core.manifest import ManifestError
from redline_core.resolve.exceptions import ResolveError
from redline_core.runtime.composition import ApplicationServices, CoreServices

_BANNER = "=" * 49


def _run_build(
    orchestrator: BuildOrchestrator,
    target: str,
    *,
    working_directory: Path,
    manifest_path: str | Path | None,
    force: bool,
    prepared_request: PreparedBuildRequest | None = None,
) -> dict:
    """Invoke the build orchestrator exactly once and return a transport result."""
    try:
        if prepared_request is None:
            result = orchestrator.build(
                target,
                working_directory=working_directory,
                manifest_path=manifest_path,
                allow_unsafe_retry=force,
            )
        else:
            result = orchestrator.build_prepared(
                prepared_request,
                allow_unsafe_retry=force,
            )
    except BuildTargetError as exc:
        return _failure("invalid target", exc)
    except ManifestResolutionError as exc:
        return _failure("manifest resolution failed", exc)
    except ManifestError as exc:
        return _failure("manifest failed", exc)
    except ManifestIdentityMismatchError as exc:
        return _failure("manifest identity mismatch", exc)
    except (EpisodeError, ResolveError) as exc:
        return _failure("episode assembly failed", exc)

    return {"success": True, "result": result}


def _failure(category: str, exc: Exception) -> dict:
    return {"success": False, "category": category, "error": str(exc), "exit_code": 1}


def prepare_build(
    args: argparse.Namespace,
    services: CoreServices,
    *,
    working_directory: Path | None = None,
    preflight: BuildPreflight | None = None,
) -> dict:
    """Run config-only build preflight before full mutable composition."""
    selected_preflight = preflight or BuildPreflight(config=services.config)
    try:
        prepared_request = selected_preflight.prepare(
            args.target,
            working_directory=working_directory or Path.cwd(),
            manifest_path=args.manifest_path,
        )
    except BuildTargetError as exc:
        return _failure("invalid target", exc)
    except ManifestResolutionError as exc:
        return _failure("manifest resolution failed", exc)
    except ManifestError as exc:
        return _failure("manifest failed", exc)
    except ManifestIdentityMismatchError as exc:
        return _failure("manifest identity mismatch", exc)

    return {"success": True, "prepared_request": prepared_request}


def _print_build_result(result: dict) -> None:
    if not result["success"]:
        print(f"Build failed ({result['category']}): {result['error']}", file=sys.stderr)
        return

    build_result: BuildResult = result["result"]
    target = build_result.target

    print(_BANNER)
    print("REDLINE OS - Build".center(49))
    print(_BANNER)
    print()
    print("Build complete")
    print()
    print(f"Target: {target.original_target}")
    print(f"Episode number: {target.episode_number}")
    print(f"Episode ID: {target.episode_id}")
    print(f"Manifest: {build_result.manifest_path}")
    print(f"Episode: {'created' if build_result.episode_created else 'reused'}")
    print(f"Final state: {build_result.final_state.value}")
    print(f"Project: {build_result.project_name}")
    print(f"Timeline: {build_result.timeline_name}")
    print(f"Media count: {build_result.media_count}")
    print(f"Markers applied: {build_result.markers_applied}")
    print(f"Clips placed: {build_result.clips_placed}")
    print(f"Video item count: {build_result.video_item_count}")
    if build_result.warnings:
        print("Warnings:")
        for warning in build_result.warnings:
            print(f"  - {warning}")
    else:
        print("Warnings: none")
    print()
    print("Build completed through assembly.")
    print("Render queued: no")
    print("Archive performed: no")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the top-level `build` command."""
    build_parser = subparsers.add_parser(
        "build",
        help="Build an episode through assembly from a canonical target.",
    )
    build_parser.add_argument("target", help="Canonical build target, e.g. Episode_0001.")
    build_parser.add_argument(
        "--manifest",
        dest="manifest_path",
        help="Explicit Episode Manifest V1 path. Passed through to build orchestration unchanged.",
    )
    build_parser.add_argument(
        "--force",
        action="store_true",
        help="Pass allow_unsafe_retry=True to EpisodeManager assembly policy. Does not overwrite, repair, render, or archive.",
    )


def run(
    args: argparse.Namespace,
    services: ApplicationServices,
    *,
    working_directory: Path | None = None,
    orchestrator: BuildOrchestrator | None = None,
    prepared_request: PreparedBuildRequest | None = None,
) -> int | None:
    """Dispatch `redline build`. Returns an exit code, or None for other resources."""
    if args.resource != "build":
        return None

    selected_orchestrator = orchestrator or BuildOrchestrator(
        config=services.config,
        episode_manager=services.episode_manager,
    )
    result = _run_build(
        selected_orchestrator,
        args.target,
        working_directory=working_directory or Path.cwd(),
        manifest_path=args.manifest_path,
        force=args.force,
        prepared_request=prepared_request,
    )
    _print_build_result(result)
    return 0 if result["success"] else result["exit_code"]
