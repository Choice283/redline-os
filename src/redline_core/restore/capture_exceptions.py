"""Exceptions raised by degraded-source capture (Mission 1B-A2-2).

Mirrors ``redline_core.backup.exceptions``'s fail-closed convention: every
capture-*package* failure mode is a distinct, typed exception, never a raw
OS exception leaking through the public boundary of this subsystem.

Deliberately a much narrower taxonomy than it might first appear to need:
per-item read/inspection outcomes -- unreadable, missing, unsafe object,
wrong type, changed during capture, or captured-but-unverified -- are
**never** exceptions. They are typed
``redline_core.restore.capture_models.CaptureItemRecord`` outcomes, always
truthfully recorded in the sealed manifest. A capture package can, and
routinely will, seal successfully while individually reporting several such
outcomes -- inability to read damaged source bytes is exactly the condition
this subsystem exists to record, not a reason to fail the whole package.

Every exception defined here means the capture *package itself* -- the
evidence artifact -- could not be safely created or sealed. Every one of
them is an unconditional hard stop: **no proceed-anyway override exists
anywhere in this package**, and none is added by this mission.
"""
from __future__ import annotations


class CaptureError(Exception):
    """Base class for all Mission 1B-A2-2 degraded-source capture package
    failures."""


class CaptureConfigurationError(CaptureError):
    """``paths.backup_path`` (the shared configured root Mission 1A
    backups and degraded-source captures both use) is not configured.
    Mirrors ``BackupConfigurationError``'s "a missing destination is a
    configuration failure, not 'nothing to capture'" doctrine exactly."""


class CaptureDestinationUnsafeError(CaptureError):
    """The resolved capture root overlaps the live database or
    configuration directory, or the capture root (or an ancestor) is an
    unsafe filesystem object. Checked via the exact same structural,
    resolved-path containment ``redline_core.backup.paths.
    validate_backup_root_containment()`` already provides for Mission 1A
    backups -- a capture root safe for backups is safe for captures, since
    both are sibling subdirectories of the identical resolved root."""


class CapturePackageCollisionError(CaptureError):
    """The computed ``capture_id`` already exists at the destination. A
    degraded-source capture attempt, exactly like a Mission 1A backup,
    never overwrites, merges, or repairs an existing package -- every
    attempt uses its own fresh identity, and the final publish step fails
    closed on collision rather than replacing anything."""


class CaptureSystemWriteFailedError(CaptureError):
    """A filesystem-level failure (disk exhaustion, permission denial, or
    similar) prevented safely building the capture package's own staging
    structure -- distinct from a per-item source-read failure, which is a
    manifest outcome, never this."""


class CaptureSealFailedError(CaptureError):
    """The capture package's own manifest, manifest sidecar hash, or
    completion marker could not be durably written, or the staged package
    failed its own self-consistency check (every ``captured_relative_path``
    the manifest names must actually exist, with the recorded size) before
    being marked complete."""


class CapturePublicationError(CaptureError):
    """Atomic publication (staging directory -> ``degraded_source_captures/
    <capture_id>/``) failed for a reason other than a destination
    collision (that raises ``CapturePackageCollisionError`` instead).
    Staging is left in place for forensic inspection; nothing is deleted
    automatically, mirroring Mission 1A's own publication-failure
    doctrine."""
