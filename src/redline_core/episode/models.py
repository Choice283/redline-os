"""Application-layer models for episode assembly."""
from __future__ import annotations

from dataclasses import dataclass, field

from redline_core.config.schema import MarkerDefinition


@dataclass(frozen=True)
class EpisodeBuildDefinition:
    """Input for assembling media onto an already-created episode."""

    episode_id: str
    media_paths: list[str]
    markers: list[MarkerDefinition] = field(default_factory=list)
    bin_name: str = "footage"


@dataclass(frozen=True)
class EpisodeBuildResult:
    """Structured result for a completed V1 episode assembly.

    `video_item_count` is a read-only, post-placement observation of the
    actual video TimelineItem count on the assembled timeline (the same
    inspection `RenderManager`'s renderability preflight uses) — not a
    count of requested/imported/placed media. Episode Manifest V1 has no
    media-role or track-placement contract, so a value of 0 is a valid,
    non-rejecting observation here: it does not mean assembly failed, only
    that this timeline is not renderable under presets that require video
    (enforced independently by `RenderManager`).
    """

    episode_id: str
    project_name: str
    timeline_id: str
    timeline_name: str
    media_paths: list[str]
    media_ids: list[str]
    markers_applied: int
    timeline_item_ids: list[str]
    video_item_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "media_paths", list(self.media_paths))
        object.__setattr__(self, "media_ids", list(self.media_ids))
        object.__setattr__(self, "timeline_item_ids", list(self.timeline_item_ids))
