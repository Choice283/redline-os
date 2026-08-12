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


class ArchivePackageError(ArchiveError):
    """Base class for Archive Rev1 package-construction failures (Phase 15
    Mission 15D): staging allocation, copy I/O, completeness verification,
    manifest sealing, and atomic publication. Raised directly only for a
    generic/defensive failure that does not fit one of the more specific
    subclasses below; callers should prefer catching a specific subclass
    where one applies."""


class ArchiveDestinationCollisionError(ArchivePackageError):
    """The final archive destination (or, in one defensive case, a staging
    allocation) already exists. Archive Rev1 never overwrites, merges,
    deletes, or repairs an existing destination -- every attempt uses a
    distinct staging identity, and both the pre-copy check and the
    immediately-pre-rename recheck fail closed rather than replace
    anything already there."""


class ArchiveCopyVerificationError(ArchivePackageError):
    """A just-copied file's destination content does not match its
    verified source: destination SHA-256 or size differs from the
    inventory (and re-verified post-copy source) values. No package is
    ever published with a file that failed this check."""


class ArchivePackageVerificationError(ArchivePackageError):
    """An independent re-enumeration of the staging payload -- run once
    right after copying, and again on the fully sealed package immediately
    before publication -- found a discrepancy: a missing or unexpected
    file/directory, a hash/size mismatch, a missing manifest/sidecar/
    completion marker, or a manifest whose sidecar hash no longer matches
    its on-disk bytes (e.g. tampering after sealing)."""


class ArchivePublicationError(ArchivePackageError):
    """Atomic publication (staging directory -> final destination rename)
    failed for a reason other than a destination collision caught by the
    immediately-pre-rename recheck (that raises
    ArchiveDestinationCollisionError instead). Staging is left in place
    for forensic inspection; nothing is overwritten."""
