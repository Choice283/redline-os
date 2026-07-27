"""Exceptions raised by the Episode Manager."""


class EpisodeError(Exception):
    """Base class for all episode lifecycle errors."""


class EpisodeAlreadyExistsError(EpisodeError):
    """An episode with this episode_number already exists in the database."""


class EpisodeNotFoundError(EpisodeError):
    """No episode with this episode_number exists in the database."""


class EpisodeBuildError(EpisodeError):
    """Raised when V1 episode assembly fails at a known orchestration stage."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        episode_id: str,
        completed_stages: tuple[str, ...] = (),
        project_name: str | None = None,
        timeline_name: str | None = None,
        imported_count: int = 0,
        markers_applied: int = 0,
        placed_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.episode_id = episode_id
        self.completed_stages = completed_stages
        self.project_name = project_name
        self.timeline_name = timeline_name
        self.imported_count = imported_count
        self.markers_applied = markers_applied
        self.placed_count = placed_count
