"""Path-safety, containment, and identity primitives for degraded-source
capture (Mission 1B-A2-2).

Reuses Mission 1A's own backup-root containment check
(``redline_core.backup.paths.validate_backup_root_containment()``)
unmodified: a degraded-source capture shares the exact same configured
``paths.backup_path`` root Mission 1A backups already use, and that root's
existing containment guarantee -- must not equal, contain, or be contained
by the live database or configuration directory -- protects a capture
identically, with zero new containment logic invented for this mission.

The capture namespace (``degraded_source_captures/<capture_id>/`` under
that same root, ``dsc1-...`` capture IDs) is structurally distinct from
Mission 1A's own (``system_backups/<backup_id>/``, ``b1-...`` backup IDs),
so the two can never collide or be mistaken for one another by
construction, not merely by convention: ``BackupManager.list_backups()``
only ever scans ``system_backups/``, and ``validate_backup_id()``'s regex
structurally rejects a ``dsc1-...`` capture ID as a Restore/backup target.
"""
from __future__ import annotations

import os
import re
import stat as stat_module
import uuid
from datetime import datetime, timezone
from pathlib import Path

from redline_core import fsutil
from redline_core.backup.exceptions import BackupPathContainmentError
from redline_core.backup.paths import validate_backup_root_containment
from redline_core.restore.capture_exceptions import CaptureConfigurationError, CaptureDestinationUnsafeError

CAPTURE_ID_SCHEMA_TAG = "dsc1"
_CAPTURE_ID_RE = re.compile(r"^dsc1-\d{8}T\d{6}Z-[0-9a-f]{12}$")


def validate_capture_id(capture_id: object) -> str:
    """Validate ``capture_id`` is exactly the ``dsc1-<UTC timestamp>-<12
    hex>`` shape before it is ever interpolated into a filesystem path.
    Raises ``ValueError`` -- a plain, transport-agnostic input error, not a
    ``CaptureError`` -- mirroring ``redline_core.backup.paths.
    validate_backup_id()``'s exact convention. This regex's ``dsc1-``
    prefix (versus Mission 1A's ``b1-``) is what structurally guarantees a
    capture ID can never collide with, or be mistaken for, a Mission 1A
    backup_id."""
    if not isinstance(capture_id, str) or not _CAPTURE_ID_RE.fullmatch(capture_id):
        raise ValueError(f"capture_id must match {_CAPTURE_ID_RE.pattern!r}, got {capture_id!r}")
    return capture_id


def _format_utc_compact(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def format_utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_capture_id(moment: datetime) -> str:
    """``dsc1-<UTC timestamp>-<12 random hex>``. Random, not
    content-derived -- mirrors ``redline_core.restore.journal.
    build_restore_id()``'s reasoning, not Mission 1A's content-digest-
    derived ``backup_id``: a capture attempt has no single, trustworthy
    content digest of its own before it begins (degraded, possibly-
    unreadable evidence is exactly what may exist), so randomness is
    sufficient to keep concurrent capture attempts at the same wall-clock
    second from colliding. The destination directory's own collision-
    refusing creation remains the true authority, not this ID's
    uniqueness alone."""
    capture_id = f"{CAPTURE_ID_SCHEMA_TAG}-{_format_utc_compact(moment)}-{uuid.uuid4().hex[:12]}"
    return validate_capture_id(capture_id)


def resolve_capture_root(*, backup_path: str | Path | None, db_path: Path, config_dir: Path) -> Path:
    """Resolve and validate the degraded-source capture root -- the exact
    same configured ``paths.backup_path`` Mission 1A backups use. Fails
    closed with a typed ``CaptureError`` before any capture staging begins;
    never a raw exception leaking across this subsystem's boundary."""
    if not backup_path:
        raise CaptureConfigurationError(
            "paths.backup_path is not configured; degraded-source capture requires the same "
            "configured destination Mission 1A backups use, both to hold the sealed capture "
            "package and to remain structurally distinct from the live database/config it is "
            "capturing."
        )
    try:
        return validate_backup_root_containment(backup_root=Path(backup_path), db_path=db_path, config_dir=config_dir)
    except BackupPathContainmentError as exc:
        raise CaptureDestinationUnsafeError(str(exc)) from exc


def require_safe_capture_directory(path: Path, *, description: str, must_exist: bool) -> None:
    """Mission 1B-A2-2 safety correction (Correction 3): lstat-based
    safety check for a directory this subsystem is about to create or
    write into as an evidence-destination container (the configured
    capture root itself, ``degraded_source_captures/``,
    ``.staging_capture/``, or one staging attempt directory). Raises
    ``CaptureDestinationUnsafeError`` if an existing ``path`` is a
    symlink/junction/reparse point or not a directory, mirroring
    ``redline_core.backup.paths.require_safe_directory()``'s exact
    contract -- reimplemented locally (rather than imported) so every
    capture-destination-safety failure raises this subsystem's own
    ``CaptureError`` taxonomy, not Backup Manager's, exactly as
    ``resolve_capture_root()`` above already translates
    ``BackupPathContainmentError`` into ``CaptureDestinationUnsafeError``
    at this module's boundary.

    ``Path.exists()``/``Path.is_dir()`` are deliberately never used here:
    both follow symlinks and silently accept a directory reached only
    through one, which is exactly the substitution this check exists to
    reject. A caller is expected to call this both immediately before
    creating/using ``path`` and again immediately after, bracketing the
    unavoidable gap between validation and the filesystem operation that
    follows it -- this function proves only what is true at the instant
    it is called, not for the remainder of the caller's operation.
    """
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if must_exist:
            raise CaptureDestinationUnsafeError(f"{description} does not exist: {path}") from None
        return
    except OSError as exc:
        raise CaptureDestinationUnsafeError(f"cannot inspect {description}: {path}") from exc
    if fsutil.is_unsafe_link(st):
        raise CaptureDestinationUnsafeError(
            f"{description} is a symlink, junction, or reparse point and is rejected: {path}"
        )
    if not stat_module.S_ISDIR(st.st_mode):
        raise CaptureDestinationUnsafeError(f"{description} is not a directory: {path}")
