"""Exceptions raised by the Episode Manager."""


class EpisodeError(Exception):
    """Base class for all episode lifecycle errors."""


class EpisodeAlreadyExistsError(EpisodeError):
    """An episode with this episode_number already exists in the database."""


class EpisodeNotFoundError(EpisodeError):
    """No episode with this episode_number exists in the database."""
