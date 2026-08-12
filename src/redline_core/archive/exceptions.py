"""Exceptions raised by the Archive Manager and the Rev1 filesystem
integrity engine (redline_core.archive.integrity)."""


class ArchiveError(Exception):
    """Generic archive operation failure (missing folder, bad destination, etc.)."""


class EpisodeAlreadyArchivedError(Exception):
    """This episode already has an archive record."""


class ArchivePathError(ArchiveError):
    """A source root or discovered filesystem object failed path/root
    safety validation: missing, not resolvable, wrong type (e.g. a file
    supplied where a directory root is required), or unreadable."""


class ArchiveUnsafeFilesystemObjectError(ArchiveError):
    """A filesystem object was rejected outright because it is not a plain
    regular file or directory: a symlink, a Windows junction/reparse
    point, or any other special object (named pipe, device, socket, etc.).
    Archive Rev1's policy rejects every one of these unconditionally,
    regardless of what a link points to."""


class ArchiveSourceChangedError(ArchiveError):
    """The source tree or a source file did not remain stable during
    inventory/hashing: a file's stat identity changed between the
    before-hash and after-hash observation, or a final tree-reconciliation
    pass found the file/directory set had changed since the initial walk.
    No trusted hash or inventory is ever returned when this is raised."""


class ArchiveInventoryError(ArchiveError):
    """An inventory-level integrity failure not covered by a more specific
    exception above -- currently: two entries whose relative paths collide
    once normalized (case-insensitive, since Archive Rev1 targets a
    Windows production filesystem regardless of the OS building the
    inventory)."""
