"""Render CLI commands.

Thin transport over redline_core.render.RenderManager. This module owns
argument parsing, output formatting, and exit behavior only.
"""
from __future__ import annotations

import argparse
import sys

from redline_core.db.models import RenderJob
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.render.exceptions import (
    RenderConfigurationError,
    RenderJobNotFoundError,
    RenderOutputCollisionError,
    RenderPersistenceError,
    RenderPresetNotFoundError,
    RenderReconciliationRequiredError,
)
from redline_core.resolve.exceptions import RenderQueueIdentityUnresolvedError, ResolveError
from redline_core.runtime.composition import ApplicationServices

_BANNER = "=" * 49


def _job_to_dict(job: RenderJob) -> dict:
    return {
        "id": job.id,
        "episode_id": job.episode_id,
        "preset_name": job.preset_name,
        "project_name": job.project_name,
        "timeline_name": job.timeline_name,
        "resolve_job_id": job.resolve_job_id,
        "status": job.status.value,
        "output_path": job.output_path,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _run_render_queue(services: ApplicationServices, episode_id: str, preset_name: str) -> dict:
    try:
        job = services.render_manager.queue_render(episode_id, preset_name)
        return {"success": True, "job": _job_to_dict(job)}
    except EpisodeNotFoundError as exc:
        return _failure("episode not found", exc)
    except RenderPresetNotFoundError as exc:
        return _failure("render preset not found", exc)
    except RenderConfigurationError as exc:
        return _failure("render configuration failed", exc)
    except RenderOutputCollisionError as exc:
        return _failure("render collision", exc)
    except (RenderPersistenceError, RenderReconciliationRequiredError) as exc:
        return _failure("render persistence failed", exc)
    except RenderQueueIdentityUnresolvedError as exc:
        return _failure("render queue identity unresolved", exc)
    except ResolveError as exc:
        return _failure("render queue failed", exc)


def _run_render_status(services: ApplicationServices, job_id: int) -> dict:
    try:
        job = services.render_manager.get_render_status(job_id)
        return {"success": True, "job": _job_to_dict(job)}
    except RenderJobNotFoundError as exc:
        return _failure("render job not found", exc)
    except ResolveError as exc:
        return _failure("render status failed", exc)


def _run_render_list(services: ApplicationServices, episode_id: str) -> dict:
    jobs = services.render_manager.list_render_jobs_for_episode(episode_id)
    return {"success": True, "episode_id": episode_id, "jobs": [_job_to_dict(j) for j in jobs]}


def _run_render_cancel(services: ApplicationServices, job_id: int) -> dict:
    try:
        job = services.render_manager.cancel_render(job_id)
        return {"success": True, "job": _job_to_dict(job)}
    except RenderJobNotFoundError as exc:
        return _failure("render job not found", exc)
    except ResolveError as exc:
        return _failure("render cancel failed", exc)


def _failure(category: str, exc: Exception) -> dict:
    return {"success": False, "category": category, "error": str(exc), "exit_code": 1}


def _print_job(job: dict) -> None:
    print(f"Job ID: {job['id']}")
    print(f"Episode ID: {job['episode_id']}")
    print(f"Preset: {job['preset_name']}")
    if job.get("project_name") is not None:
        print(f"Project: {job['project_name']}")
    if job.get("timeline_name") is not None:
        print(f"Timeline: {job['timeline_name']}")
    print(f"Resolve Job ID: {job['resolve_job_id']}")
    print(f"Status: {job['status']}")
    print(f"Output: {job['output_path']}")
    if job.get("created_at") is not None:
        print(f"Created: {job['created_at']}")
    if job.get("updated_at") is not None:
        print(f"Last updated: {job['updated_at']}")


def _print_render_queue_result(result: dict) -> None:
    if not result["success"]:
        print(f"Render queue failed ({result['category']}): {result['error']}", file=sys.stderr)
        return

    print(_BANNER)
    print("REDLINE OS - Render Queue".center(49))
    print(_BANNER)
    print()
    print("Render queued")
    print()
    _print_job(result["job"])
    print()
    print("Rendering started: no")
    print("Archive performed: no")


def _print_render_status_result(result: dict) -> None:
    if not result["success"]:
        print(f"Render status failed ({result['category']}): {result['error']}", file=sys.stderr)
        return

    print(_BANNER)
    print("REDLINE OS - Render Status".center(49))
    print(_BANNER)
    print()
    _print_job(result["job"])


def _print_render_list_result(result: dict) -> None:
    print(_BANNER)
    print("REDLINE OS - Render Jobs".center(49))
    print(_BANNER)
    print()
    print(f"Episode ID: {result['episode_id']}")
    print()

    jobs = result["jobs"]
    if not jobs:
        print("No render jobs found.")
        return

    for job in jobs:
        print(f"Job ID: {job['id']}")
        print(f"Status: {job['status']}")
        print(f"Preset: {job['preset_name']}")
        print(f"Resolve Job ID: {job['resolve_job_id']}")
        print(f"Output path: {job['output_path']}")
        print()
    print(f"{len(jobs)} render job(s).")


def _print_render_cancel_result(result: dict) -> None:
    if not result["success"]:
        print(f"Render cancel failed ({result['category']}): {result['error']}", file=sys.stderr)
        return

    print(_BANNER)
    print("REDLINE OS - Render Cancel".center(49))
    print(_BANNER)
    print()
    print("Render cancelled")
    print()
    _print_job(result["job"])
    print()
    print("Build was not performed.")
    print("Archive was not performed.")


def register_parser(subparsers: argparse._SubParsersAction) -> None:
    """Attach the `render` resource and its actions to the top-level subparsers."""
    render_parser = subparsers.add_parser("render", help="Render commands.")
    render_subparsers = render_parser.add_subparsers(dest="action", required=True)

    queue_parser = render_subparsers.add_parser("queue", help="Queue a render for an episode.")
    queue_parser.add_argument("episode_id", help="Episode ID to render, e.g. RLC-E025.")
    queue_parser.add_argument("preset_name", help="Render preset name from config/render_presets.yaml.")

    status_parser = render_subparsers.add_parser("status", help="Get a render job's current status.")
    status_parser.add_argument("job_id", type=int, help="Redline render job database ID.")

    list_parser = render_subparsers.add_parser("list", help="List render jobs for an episode.")
    list_parser.add_argument("episode_id", help="Episode ID whose render jobs should be listed, e.g. RLC-E025.")

    cancel_parser = render_subparsers.add_parser("cancel", help="Cancel a queued or in-progress render job.")
    cancel_parser.add_argument("job_id", type=int, help="Redline render job database ID.")


def run(args: argparse.Namespace, services: ApplicationServices) -> int | None:
    """Dispatch a parsed `render ...` command. Returns an exit code, or None for other resources."""
    if args.resource != "render":
        return None

    if args.action == "queue":
        result = _run_render_queue(services, args.episode_id, args.preset_name)
        _print_render_queue_result(result)
        return 0 if result["success"] else result["exit_code"]

    if args.action == "status":
        result = _run_render_status(services, args.job_id)
        _print_render_status_result(result)
        return 0 if result["success"] else result["exit_code"]

    if args.action == "list":
        result = _run_render_list(services, args.episode_id)
        _print_render_list_result(result)
        return 0 if result["success"] else 1

    if args.action == "cancel":
        result = _run_render_cancel(services, args.job_id)
        _print_render_cancel_result(result)
        return 0 if result["success"] else result["exit_code"]

    return None
