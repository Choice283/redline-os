"""Path-safety, containment, and identity primitives for Backup Manager
(Mission 1A).

Filesystem-object safety here delegates entirely to the domain-neutral
``redline_core.fsutil.is_unsafe_link()`` -- the same primitive
``redline_core.archive.integrity`` uses -- so there is exactly one real
implementation of "is this a symlink/junction/reparse point" in the
repository, not a second, slightly different one invented for backups.
"""
from __future__ import annotations

import os
import re
import stat as stat_module
from datetime import datetime, timezone
from pathlib import Path

from redline_core import fsutil
from redline_core.backup.exceptions import (
    BackupPathContainmentError,
    BackupSourceUnavailableError,
    BackupUnsafeFilesystemObjectError,
)

BACKUP_ID_SCHEMA_TAG = "b1"
_BACKUP_ID_RE = re.compile(r"^b1-\d{8}T\d{6}Z-[0-9a-f]{12}$")


def validate_backup_id(backup_id: object) -> str:
    """Validate ``backup_id`` is exactly the ``b1-<UTC timestamp>-<12 hex>``
    shape before it is ever interpolated into a filesystem path. Raises
    ``ValueError`` -- a plain, transport-agnostic input error, not a
    ``BackupError`` -- since this guards path construction itself, before
    any backup-domain operation begins."""
    if not isinstance(backup_id, str) or not _BACKUP_ID_RE.fullmatch(backup_id):
        raise ValueError(f"backup_id must match {_BACKUP_ID_RE.pattern!r}, got {backup_id!r}")
    return backup_id


def format_utc_compact(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def format_utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_backup_id(moment: datetime, content_set_digest: str) -> str:
    """``b1-<UTC timestamp>-<first 12 hex chars of content_set_digest>``.
    Timestamp-first (unlike Archive Rev1's episode_id-first archive_id):
    a system-of-record backup is a *series over time*, so identity must be
    time-ordered first and content-verified second."""
    backup_id = f"{BACKUP_ID_SCHEMA_TAG}-{format_utc_compact(moment)}-{content_set_digest[:12]}"
    return validate_backup_id(backup_id)


def _resolve(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _paths_overlap(a: Path, b: Path) -> bool:
    """True if a == b, a is inside b, or b is inside a. Structural
    containment via Path.is_relative_to() -- never string-prefix matching."""
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def validate_backup_root_containment(*, backup_root: Path, db_path: Path, config_dir: Path) -> Path:
    """Resolve and validate that ``backup_root`` cannot capture itself or a
    prior backup:

    - must not equal the live database path
    - must not equal, contain, or be contained by the active configuration
      directory
    - must not equal, contain, or be contained by the live database's own
      parent directory

    Returns the resolved ``backup_root``. Raises
    ``BackupPathContainmentError`` (naming the specific overlap) on any
    violation. All comparisons are structural (``Path.is_relative_to()``
    against fully resolved paths), never string-prefix matching.
    """
    resolved_root = _resolve(backup_root)
    resolved_db = _resolve(db_path)
    resolved_db_dir = resolved_db.parent
    resolved_config = _resolve(config_dir)

    if resolved_root == resolved_db:
        raise BackupPathContainmentError(
            f"backup_path ({resolved_root}) must not equal the live database path ({resolved_db})."
        )
    if _paths_overlap(resolved_root, resolved_config):
        raise BackupPathContainmentError(
            f"backup_path ({resolved_root}) overlaps the active configuration directory "
            f"({resolved_config}); a backup destination must never equal, contain, or be "
            "contained by REDLINE_CONFIG_DIR."
        )
    if _paths_overlap(resolved_root, resolved_db_dir):
        raise BackupPathContainmentError(
            f"backup_path ({resolved_root}) overlaps the live database's directory "
            f"({resolved_db_dir}); a backup destination must never equal, contain, or be "
            "contained by the directory holding REDLINE_DB_PATH."
        )
    return resolved_root


def require_safe_regular_file(path: Path, *, description: str) -> None:
    """Raise ``BackupSourceUnavailableError`` if ``path`` does not exist,
    or ``BackupUnsafeFilesystemObjectError`` if it exists but cannot be
    inspected, is a symlink/junction/reparse point, or is anything other
    than a plain regular file. The distinction matters: "missing" and
    "unsafe" are different, separately-testable failure modes."""
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise BackupSourceUnavailableError(f"{description} does not exist: {path}") from exc
    except OSError as exc:
        raise BackupUnsafeFilesystemObjectError(f"cannot inspect {description}: {path}") from exc
    if fsutil.is_unsafe_link(st):
        raise BackupUnsafeFilesystemObjectError(
            f"{description} is a symlink, junction, or reparse point and is rejected: {path}"
        )
    if not stat_module.S_ISREG(st.st_mode):
        raise BackupUnsafeFilesystemObjectError(f"{description} is not a regular file: {path}")


def require_safe_directory(path: Path, *, description: str, must_exist: bool) -> None:
    """Raise ``BackupUnsafeFilesystemObjectError`` if an existing ``path``
    is a symlink/junction/reparse point or not a directory. If
    ``must_exist`` is False and ``path`` does not exist yet (e.g.
    ``backup_root`` before its first use), a missing path is not an error
    -- the caller is responsible for creating it afterward."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if must_exist:
            raise BackupUnsafeFilesystemObjectError(f"{description} does not exist: {path}") from None
        return
    except OSError as exc:
        raise BackupUnsafeFilesystemObjectError(f"cannot inspect {description}: {path}") from exc
    if fsutil.is_unsafe_link(st):
        raise BackupUnsafeFilesystemObjectError(
            f"{description} is a symlink, junction, or reparse point and is rejected: {path}"
        )
    if not stat_module.S_ISDIR(st.st_mode):
        raise BackupUnsafeFilesystemObjectError(f"{description} is not a directory: {path}")
