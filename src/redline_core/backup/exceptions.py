"""Exceptions raised by Backup Manager (Mission 1A: Backup + Verification).

Restore-specific exceptions (e.g. an eventual ``BackupRestoreConfirmation
RequiredError``) are explicitly out of scope for Mission 1A and are not
defined here -- see docs/BACKUP_RECOVERY_ARCHITECTURE.md and Mission 1B.
"""
from __future__ import annotations


class BackupError(Exception):
    """Base class for all Mission 1A backup/verification failures."""


class BackupConfigurationError(BackupError):
    """``paths.backup_path`` is not configured. Backup creation fails
    closed before any staging, snapshot, or filesystem mutation -- mirrors
    ``ArchiveEvidenceConfigurationError``'s "no configured authority is
    never an authoritative zero-evidence result" pattern: a missing
    backup destination is a configuration failure, not "nothing to back
    up"."""


class BackupPathContainmentError(BackupError):
    """The resolved backup root equals the live database path, equals or
    contains/`is-contained-by the active configuration directory, or
    equals/contains/is-contained-by the live database's parent directory
    -- any arrangement under which a backup could capture itself or a
    prior backup. Checked via structural resolved-path containment
    (``Path.is_relative_to()``), never string-prefix matching."""


class BackupUnsafeFilesystemObjectError(BackupError):
    """A symlink, Windows junction/reparse point, or other non-regular
    filesystem object was encountered where a plain file or directory was
    required (the live database file, a required config file, or the
    backup root itself). Rejected unconditionally, mirroring
    ``redline_core.archive.integrity``'s policy (both are backed by the
    same domain-neutral ``redline_core.fsutil`` safety primitives)."""


class BackupSourceUnavailableError(BackupError):
    """The live database file, or a file named in
    ``redline_core.config.loader.REQUIRED_FILES``, is missing or
    unreadable at backup time. Fails closed before any staging directory
    is created."""


class BackupDatabaseSnapshotError(BackupError):
    """The SQLite Online Backup API (or its documented fallback) failed to
    produce a destination snapshot from the live database."""


class BackupIntegrityCheckFailedError(BackupError):
    """``PRAGMA integrity_check`` against the backup database copy did not
    return exactly the single row ``('ok',)``."""


class BackupCopyVerificationError(BackupError):
    """A copied configuration file's freshly-computed destination SHA-256
    does not match the hash computed while streaming its source. No
    package is ever published with a file that failed this check."""


class BackupDestinationCollisionError(BackupError):
    """The computed ``backup_id`` already exists at the destination.
    Mission 1A never overwrites, merges, or repairs an existing backup --
    every attempt uses its own staging identity, and the final publish
    step fails closed on collision rather than replacing anything."""


class BackupPublicationError(BackupError):
    """Atomic publication (staging directory -> ``system_backups/<backup_
    id>/``) failed for a reason other than a destination collision (that
    raises ``BackupDestinationCollisionError`` instead). Staging is left
    in place for forensic inspection; nothing is deleted automatically."""


class BackupNotFoundError(BackupError):
    """``verify_backup()`` was given a ``backup_id`` with no corresponding
    sealed package directory under ``system_backups/``."""


class BackupVerificationFailedError(BackupError):
    """An at-rest backup no longer matches its own sealed manifest:
    corruption, tampering, or an incomplete/never-fully-published package
    masquerading as one. Every verification failure mode raises this (or
    a more specific subclass) rather than returning a result with
    ``verified=False`` -- matching Archive Rev1's existing fail-closed
    convention."""
