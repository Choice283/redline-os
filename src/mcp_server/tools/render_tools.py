"""Render MCP tools — thin wrappers around RenderManager.

queue_render is async by design: it returns a job ID immediately rather
than blocking for the render to finish (see docs/ARCHITECTURE.md §5/§9).
Poll get_render_status separately.
"""
from __future__ import annotations

from redline_core.db.models import RenderJob
from redline_core.episode.exceptions import EpisodeNotFoundError
from redline_core.render.exceptions import RenderJobNotFoundError, RenderPresetNotFoundError
from redline_core.render.manager import RenderManager


def _job_to_dict(job: RenderJob) -> dict:
    return {
        "id": job.id,
        "episode_id": job.episode_id,
        "preset_name": job.preset_name,
        "resolve_job_id": job.resolve_job_id,
        "status": job.status.value,
        "output_path": job.output_path,
    }


def _queue_render(manager: RenderManager, episode_id: str, preset_name: str) -> dict:
    try:
        job = manager.queue_render(episode_id, preset_name)
        return {"success": True, "job": _job_to_dict(job)}
    except (EpisodeNotFoundError, RenderPresetNotFoundError) as exc:
        return {"success": False, "error": str(exc)}


def _get_render_status(manager: RenderManager, job_id: int) -> dict:
    try:
        job = manager.get_render_status(job_id)
        return {"success": True, "job": _job_to_dict(job)}
    except RenderJobNotFoundError as exc:
        return {"success": False, "error": str(exc)}


def _cancel_render(manager: RenderManager, job_id: int) -> dict:
    try:
        job = manager.cancel_render(job_id)
        return {"success": True, "job": _job_to_dict(job)}
    except RenderJobNotFoundError as exc:
        return {"success": False, "error": str(exc)}


def _list_render_jobs_for_episode(manager: RenderManager, episode_id: str) -> dict:
    jobs = manager.list_render_jobs_for_episode(episode_id)
    return {"success": True, "jobs": [_job_to_dict(j) for j in jobs]}


def register(mcp, ctx) -> None:
    """Attach render tools to `mcp`, bound to ctx.render_manager."""

    @mcp.tool()
    def queue_render(episode_id: str, preset_name: str) -> dict:
        """Queue a render for an episode using a named preset from config/render_presets.yaml.
        Returns immediately with a job ID — use get_render_status to poll for completion."""
        return _queue_render(ctx.render_manager, episode_id, preset_name)

    @mcp.tool()
    def get_render_status(job_id: int) -> dict:
        """Get the current status of a render job, syncing from Resolve's render queue."""
        return _get_render_status(ctx.render_manager, job_id)

    @mcp.tool()
    def cancel_render(job_id: int) -> dict:
        """Cancel a queued or in-progress render job."""
        return _cancel_render(ctx.render_manager, job_id)

    @mcp.tool()
    def list_render_jobs_for_episode(episode_id: str) -> dict:
        """List every render job queued for an episode."""
        return _list_render_jobs_for_episode(ctx.render_manager, episode_id)
