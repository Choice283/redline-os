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


def _place_clips(builder: TimelineBuilder, project_name: str, timeline_name: str, clip_ids: list[str]) -> dict:
    if not isinstance(project_name, str) or not project_name:
        raise ValueError("project_name must be a non-empty string.")
    if not isinstance(timeline_name, str) or not timeline_name:
        raise ValueError("timeline_name must be a non-empty string.")
    if not isinstance(clip_ids, list):
        raise ValueError("clip_ids must be a list of strings.")
    invalid_indexes = [
        index for index, clip_id in enumerate(clip_ids) if not isinstance(clip_id, str) or not clip_id
    ]
    if invalid_indexes:
        indexes = ", ".join(str(index) for index in invalid_indexes)
        raise ValueError(f"clip_ids must contain only non-empty strings; invalid index(es): {indexes}.")

    timeline_item_ids = builder.place_clips(
        project_name=project_name,
        timeline_name=timeline_name,
        clip_ids=clip_ids,
    )
    return {
        "success": True,
        "project_name": project_name,
        "timeline_name": timeline_name,
        "clip_ids": clip_ids,
        "timeline_item_ids": timeline_item_ids,
        "placed_count": len(timeline_item_ids),
    }


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

    @mcp.tool()
    def place_clips(project_name: str, timeline_name: str, clip_ids: list[str]) -> dict:
        """Place already-imported clips on an existing timeline."""
        return _place_clips(ctx.timeline_builder, project_name, timeline_name, clip_ids)
