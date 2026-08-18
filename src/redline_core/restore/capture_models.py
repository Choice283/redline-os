"""Degraded-source capture result/enum models (Mission 1B-A2-2).

A degraded-source capture is evidence/preservation of the observed live
system state -- it is never a Mission 1A backup, never a Restore source,
never a partial backup, and never a rollback or resumable recovery
transaction. See ``redline_core.restore.capture_package`` for the
namespace/identity guarantees that keep this structurally impossible to
confuse with a Mission 1A backup.

Mirrors ``redline_core.backup.models``'s and
``redline_core.restore.recovery_models``'s frozen/slotted dataclass
convention. Per-item outcomes are always typed manifest data, never raised
exceptions -- see ``redline_core.restore.capture_exceptions`` for the
distinct, much narrower set of exceptions that represent the capture
*package itself* failing to be safely created or sealed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CaptureItemOutcome(str, Enum):
    """The truthful, per-item result of attempting to preserve one source
    item (the database, one required config file, or one observed SQLite
    sidecar). A capture *package* may still seal successfully (see
    ``CaptureResult``) even when individual items report anything other
    than ``CAPTURED_VERIFIED`` -- inability to read damaged source bytes is
    exactly the condition degraded-source capture exists to record, not a
    reason to fail the whole package."""

    CAPTURED_VERIFIED = "CAPTURED_VERIFIED"
    """Bytes were streamed from the source, written to the sealed package,
    independently re-read and re-hashed from the destination to confirm
    the write itself is intact, and the source's own stat fingerprint
    (size/mtime_ns/inode/device) was identical before and after streaming
    -- the strongest evidence this subsystem can produce."""

    CAPTURED_UNVERIFIED = "CAPTURED_UNVERIFIED"
    """Bytes were captured, but this evidence could not be independently
    confirmed trustworthy -- e.g. the destination copy could not be
    re-read, or it did not match the verified source stream."""

    UNREADABLE = "UNREADABLE"
    """The item exists (or existed) but no usable bytes could be captured
    -- the source could not be opened, or a read failed before any (or
    only some) bytes were obtained. Distinct from ``MISSING`` (the item
    never existed) and from ``UNSAFE_OBJECT_RECORDED`` (the item exists
    but is deliberately never opened at all)."""

    UNSAFE_OBJECT_RECORDED = "UNSAFE_OBJECT_RECORDED"
    """The item is a symlink, Windows junction, or other reparse point.
    Safe metadata only was recorded -- the object was never followed,
    never opened, and its target was never inspected."""

    MISSING = "MISSING"
    """The expected exact item path does not exist."""

    WRONG_TYPE_RECORDED = "WRONG_TYPE_RECORDED"
    """The item exists but is not the expected object type (e.g. a plain
    directory sits where the database file is expected, or a plain file
    sits where the config directory is expected). Safe, shallow,
    non-recursive metadata only was recorded -- its contents were never
    treated as candidate source bytes and were never recursively
    inspected."""

    CHANGED_DURING_CAPTURE = "CHANGED_DURING_CAPTURE"
    """The source item's stat fingerprint changed (or the item
    disappeared) between the start and the end of streaming it -- the
    captured bytes, if any, do not represent one consistent point in time
    and must never be treated as verified."""


@dataclass(frozen=True, slots=True)
class StatFingerprint:
    """The same four-field identity fingerprint
    (size/mtime_ns/inode/device) ``redline_core.fsutil``'s own
    ``open_stable_source()`` uses internally to detect a source changing
    mid-read, reused here as a first-class, manifest-serializable value
    rather than a private implementation detail."""

    size: int
    mtime_ns: int
    ino: int | None
    dev: int | None


@dataclass(frozen=True, slots=True)
class CaptureItemRecord:
    """One item's (database, one required config file, one observed
    sidecar, or the config directory container itself) truthful capture
    outcome. Never raised as an exception -- always returned as manifest
    data, mirroring ``redline_core.restore.recovery_models.
    SourceSideAssessment``'s own non-raising convention."""

    item_key: str
    source_path: str
    outcome: CaptureItemOutcome
    captured_relative_path: str | None
    size_bytes: int | None
    sha256: str | None
    stat_fingerprint: StatFingerprint | None
    unsafe_object: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """The result of one fully sealed, published degraded-source capture
    package. Only ever returned after the package's completion marker has
    been durably written -- every capture *system* failure mode (as
    opposed to a per-item outcome) raises a typed
    ``redline_core.restore.capture_exceptions.CaptureError`` subclass
    instead, with no proceed-anyway override anywhere in this package.

    ``capture_id`` always uses the ``dsc1-...`` schema
    (``redline_core.restore.capture_paths.CAPTURE_ID_SCHEMA_TAG``) --
    structurally distinct from Mission 1A's ``b1-...`` backup_id schema, so
    a capture can never be mistaken for, listed as, or accepted as a
    Mission 1A backup by construction, not merely by convention."""

    capture_id: str
    capture_path: Path
    manifest_path: Path
    manifest_sha256: str
    created_at: str
    reason: str | None
    database: CaptureItemRecord
    config_directory: CaptureItemRecord | None
    config_files: tuple[CaptureItemRecord, ...]
    config_directory_inventory: tuple[str, ...]
    sidecars: tuple[CaptureItemRecord, ...]
    total_bytes_captured: int
