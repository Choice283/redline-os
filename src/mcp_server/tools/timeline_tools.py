"""Timeline MCP tools — thin wrappers around TimelineBuilder."""
from __future__ import annotations

from redline_core.config.schema import MarkerDefinition
from redline_core.timeline.builder import TimelineBuilder


def _build_timeline(builder: TimelineBuilder, project_name: str, episode_id: str) -> dict:
    result = builder.build_timeline_for_episode(project_name, episode_id)
    return {
        "success": True,
        "timeline_id": result.timeline_id,
        "timeline_name": result.timeline_name,
        "markers_applied": result.markers_applied,
    }


def _add_markers(
    builder: TimelineBuilder, project_name: str, timeline_name: str, markers: list[dict] | None = None
) -> dict:
    marker_defs = [MarkerDefinition(**m) for m in markers] if markers is not None else None
    count = builder.apply_markers(project_name, timeline_name, marker_defs)
    return {"success": True, "markers_applied": count}


def register(mcp, ctx) -> None:
    """Attach timeline tools to `mcp`, bound to ctx.timeline_builder."""

    @mcp.tool()
    def build_timeline(project_name: str, episode_id: str) -> dict:
        """Build the episode's timeline and apply the standard marker set from config/timeline_template.yaml."""
        return _build_timeline(ctx.timeline_builder, project_name, episode_id)

    @mcp.tool()
    def add_markers(project_name: str, timeline_name: str, markers: list[dict] | None = None) -> dict:
        """Apply markers to an existing timeline. Each marker needs frame/color/name (note optional).
        Omit markers to reapply the configured default set."""
        return _add_markers(ctx.timeline_builder, project_name, timeline_name, markers)
