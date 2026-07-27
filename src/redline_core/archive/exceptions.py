"""Exceptions raised by the Archive Manager."""


class ArchiveError(Exception):
    """Generic archive operation failure (missing folder, bad destination, etc.)."""


class EpisodeAlreadyArchivedError(Exception):
    """This episode already has an archive record."""
