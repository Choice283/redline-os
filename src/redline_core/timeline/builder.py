"""Timeline Builder — builds an episode's timeline and applies its markers.

Scope is deliberately narrow: this module does NOT duplicate the Resolve
project (that's Episode Manager, Phase 2) and does NOT import media (that's
Media Manager, Phase 3). It only calls ResolveAdapter.build_timeline() and
.add_markers(), using the data-driven template in config/timeline_template.yaml
— never hardcoded marker frames/colors, since those come from the Broadcast
Package spec owned by the Universe project.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from redline_core.config.schema import MarkerDefinition, RedlineConfig
from redline_core.resolve.adapter import ResolveAdapter

logger = logging.getLogger(__name__)


@dataclass
class TimelineBuildResult:
    timeline_id: str
    timeline_name: str
    markers_applied: int


class TimelineBuilder:
    def __init__(self, config: RedlineConfig, resolve: ResolveAdapter):
        self.config = config
        self.resolve = resolve

    def build_timeline_for_episode(
        self, project_name: str, episode_id: str, markers: list[MarkerDefinition] | None = None
    ) -> TimelineBuildResult:
        """Build the episode's timeline and apply the standard marker set.

        `markers` can be overridden per-call (e.g. a special episode with a
        different marker layout); defaults to config.timeline.markers.
        """
        timeline_name = self.config.timeline.timeline_name_pattern.format(episode_id=episode_id)
        logger.info("Building timeline '%s' in project '%s'", timeline_name, project_name)

        timeline_id = self.resolve.build_timeline(project_name, timeline_name)
        markers_applied = self.apply_markers(project_name, timeline_name, markers)

        return TimelineBuildResult(
            timeline_id=timeline_id, timeline_name=timeline_name, markers_applied=markers_applied
        )

    def apply_markers(
        self, project_name: str, timeline_name: str, markers: list[MarkerDefinition] | None = None
    ) -> int:
        """Apply markers to an already-built timeline. Returns how many were applied."""
        marker_defs = markers if markers is not None else self.config.timeline.markers
        if not marker_defs:
            return 0
        marker_dicts = [m.model_dump() for m in marker_defs]
        self.resolve.add_markers(project_name, timeline_name, marker_dicts)
        logger.info("Applied %d marker(s) to '%s'", len(marker_dicts), timeline_name)
        return len(marker_dicts)

    def place_clips(self, project_name: str, timeline_name: str, clip_ids: list[str]) -> list[str]:
        """Place already-imported clips on an existing timeline. Returns TimelineItem IDs."""
        timeline_item_ids = self.resolve.place_clips(project_name, timeline_name, clip_ids)
        logger.info("Placed %d clip(s) on '%s'", len(timeline_item_ids), timeline_name)
        return timeline_item_ids
