"""Exceptions raised by Restore Manager (Mission 1B-A1: HEALTHY_SOURCE Restore).

Mirrors ``redline_core.backup.exceptions``'s fail-closed convention: every
failure mode is a distinct, typed exception, never a raw OS/SQLite exception
leaking through the public Restore contract and never a "success with a
false flag" result shape. DEGRADED_SOURCE/MISSING_SOURCE-specific exceptions
are explicitly out of scope for Mission 1B-A1 and are not defined here.
"""
from __future__ import annotations


class RestoreError(Exception):
    """Base class for all Mission 1B-A1 restore failures."""


class RestoreConfirmationError(RestoreError):
    """The operator-supplied repeated ``confirm_backup_id`` does not match
    the ``backup_id`` being restored. Checked before any live mutation, and
    before the pre-restore safety backup is even attempted."""


class RestoreAttestationMissingError(RestoreError):
    """One or more of the required, itemized quiescence attestations (MCP
    stopped, Control Room stopped, no other Redline CLI operation in
    flight) was not explicitly given. Checked before any live mutation."""


class RestoreTargetUnavailableError(RestoreError):
    """The target backup could not be found, or failed its fresh,
    immediately-pre-restore ``BackupManager.verify_backup()`` re-check.
    Restore never proceeds against a target it has not just independently
    re-verified."""


class RestoreSchemaIncompatibleError(RestoreError):
    """The target backup's database schema does not structurally match the
    current application schema (built fresh via ``Database.init_schema()``
    against a disposable comparison database) -- table inventory, column
    shape, or index structure differs."""


class RestoreUnsupportedSchemaObjectError(RestoreError):
    """The reference schema or the target backup's database contains a
    view or trigger. Mission 1B-A1's schema-compatibility check does not
    attempt to validate view/trigger semantics and fails closed rather
    than silently ignoring them."""


class RestorePreRestoreSnapshotFailedError(RestoreError):
    """The mandatory pre-restore safety backup (Mission 1A's own
    ``BackupManager.create_backup()``, used unmodified) could not be
    created and verified. Restore aborts before any live mutation --
    Mission 1B-A1 does not implement degraded/missing-source recovery, so
    a failed safety snapshot is always a hard stop, never a
    proceed-anyway option."""


class RestoreQuiescenceFailedError(RestoreError):
    """The ``BEGIN IMMEDIATE`` quiescence probe against the live database
    could not acquire an immediate write lock -- another connection
    appears to hold it. No process-supervision framework is implemented;
    this is the only quiescence *proof*, distinct from the separate
    operator attestations (see ``RestoreAttestationMissingError``)."""


class RestoreSidecarPresentError(RestoreError):
    """A SQLite sidecar file (``-journal``, ``-wal``, or ``-shm``) was
    found next to the live database, either immediately before database
    replacement or immediately after it (before any SQLite connection is
    opened to the replaced file). Sidecars are never deleted, renamed, or
    recovered automatically -- their presence is always a fail-closed
    stop."""


class RestoreStagingFailedError(RestoreError):
    """Copying the target backup's database or config payload into
    same-volume staging failed, or the staged copy's independently
    recomputed hash/size did not match the target backup's manifest."""


class RestorePathCollisionError(RestoreError):
    """A restore-ID-scoped staging path, superseded-config path, or
    journal transition path already exists. Restore never overwrites an
    existing path at any of these boundaries; every attempt fails
    closed on collision instead."""


class RestoreJournalError(RestoreError):
    """The restore transaction journal could not be created or a
    transition could not be durably recorded (write, flush, fsync, or the
    final collision-refusing rename failed)."""


class RestoreDatabaseReplacementFailedError(RestoreError):
    """The single ``os.replace()`` publishing the staged database over the
    live database path failed."""


class RestoreConfigReplacementFailedError(RestoreError):
    """Either step of the two-step config replacement (renaming the live
    config directory aside to its restore-ID-scoped superseded path, or
    renaming the staged config directory into the canonical live config
    path) failed. The two steps are never claimed to be atomic together --
    see the exception message for which step failed and what state the
    filesystem was left in."""


class RestoreVerificationFailedError(RestoreError):
    """Post-restore verification (sidecar absence, byte identity, integrity
    check, schema compatibility, config load/path-safety, application-level
    reads, or target-backup preservation) failed at any step. No rollback,
    no retry, and no success marker is ever produced on this path."""
