"""Same-volume staging and live replacement (Mission 1B-A1).

The target backup package remains read-only throughout: everything staged
here is copied out of it into fresh, same-volume staging locations, with an
independently recomputed hash/size verified against the target backup's own
manifest before any live replacement is attempted. Staging never assumes
``paths.backup_path`` shares a volume with ``REDLINE_DB_PATH`` or
``REDLINE_CONFIG_DIR`` -- staging directories are nested directly inside
each live path's own parent directory, which is same-volume by
construction, and ``same_volume()`` re-proves it explicitly rather than
merely asserting it.

Database replacement is a single ``os.replace()`` -- one atomic swap.
Config replacement is a **two-step, non-atomic** directory-level rename:
live config directory -> restore-ID-scoped superseded path, then staged
config directory -> canonical live config path. The two steps are never
claimed to be atomic together; a crash between them leaves the live config
directory genuinely missing (config exists only at the superseded path and
the still-present staging path) -- Mission 1B-A1 implements no automatic
recovery from that window, by design (locked scope item 18).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from redline_core import fsutil
from redline_core.restore.exceptions import (
    RestoreConfigReplacementFailedError,
    RestoreDatabaseReplacementFailedError,
    RestorePathCollisionError,
    RestoreStagingFailedError,
)

STAGING_DIRNAME = ".redline_restore_staging"
SUPERSEDED_CONFIG_INFIX = "__superseded-"
_COPY_CHUNK_SIZE = 1024 * 1024  # 1 MiB; matches Mission 1A's backup copy chunk size.

_RESTORE_SAFE_FILE_EXCEPTIONS = fsutil.SafeFileExceptions(
    path_error=RestoreStagingFailedError,
    unsafe_object=RestoreStagingFailedError,
    source_changed=RestoreStagingFailedError,
)


def same_volume(a: Path, b: Path) -> bool:
    """True if the already-existing filesystem objects at ``a`` and ``b``
    report the same device (``st_dev``). Both must already exist."""
    return os.stat(a).st_dev == os.stat(b).st_dev


def _copy_and_verify(
    source_path: Path, destination_path: Path, *, expected_sha256: str, expected_size: int, description: str
) -> None:
    """Stream ``source_path`` (proving it did not change mid-read) into
    ``destination_path``, flush + fsync it, then independently re-read the
    destination and require its hash/size to match both the just-computed
    source-stream hash and the target backup manifest's recorded
    hash/size. Raises ``RestoreStagingFailedError`` on any mismatch --
    nothing staged this way is ever handed to live replacement unverified.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_digest = hashlib.sha256()
    with fsutil.open_stable_source(source_path, exceptions=_RESTORE_SAFE_FILE_EXCEPTIONS) as (fh, size_bytes):
        with destination_path.open("wb") as out:
            while True:
                chunk = fh.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                source_digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    stream_sha256 = source_digest.hexdigest()

    actual_sha256, actual_size = fsutil.hash_stable_file(destination_path, exceptions=_RESTORE_SAFE_FILE_EXCEPTIONS)
    if actual_sha256 != stream_sha256 or actual_size != size_bytes:
        raise RestoreStagingFailedError(
            f"copied {description} content does not match its verified source stream: "
            f"{source_path} -> {destination_path}"
        )
    if actual_sha256 != expected_sha256 or actual_size != expected_size:
        raise RestoreStagingFailedError(
            f"copied {description} does not match the target backup's manifest: expected "
            f"sha256={expected_sha256} size={expected_size}, got sha256={actual_sha256} size={actual_size} "
            f"({source_path} -> {destination_path})"
        )


def stage_database(*, target_db_path: Path, db_manifest_entry: dict, live_db_path: Path, restore_id: str) -> Path:
    """Copy the target backup's database payload into fresh, same-volume
    staging next to ``live_db_path``, verified against
    ``db_manifest_entry``. Never touches ``target_db_path`` itself, and
    never touches ``live_db_path``."""
    live_db_path = Path(live_db_path)
    staging_dir = live_db_path.parent / STAGING_DIRNAME / restore_id / "db"
    if staging_dir.exists():
        raise RestorePathCollisionError(f"restore database staging path already exists: {staging_dir}")
    staging_dir.mkdir(parents=True)

    staged_db_path = staging_dir / live_db_path.name
    _copy_and_verify(
        Path(target_db_path),
        staged_db_path,
        expected_sha256=db_manifest_entry["sha256"],
        expected_size=db_manifest_entry["size_bytes"],
        description="backup database payload",
    )
    if not same_volume(staged_db_path, live_db_path.parent):
        raise RestoreStagingFailedError(
            f"staged database {staged_db_path} is not on the same volume as {live_db_path.parent}; refusing "
            "to stage cross-volume."
        )
    return staged_db_path


def stage_config(
    *, target_config_dir: Path, config_manifest_entries: list[dict], live_config_dir: Path, restore_id: str
) -> Path:
    """Copy every file named by ``config_manifest_entries`` from the target
    backup's config payload into fresh, same-volume staging next to
    ``live_config_dir``, each independently verified against its manifest
    entry. Never touches ``target_config_dir`` itself, and never touches
    ``live_config_dir``."""
    live_config_dir = Path(live_config_dir)
    staging_dir = live_config_dir.parent / STAGING_DIRNAME / restore_id / "config"
    if staging_dir.exists():
        raise RestorePathCollisionError(f"restore config staging path already exists: {staging_dir}")
    staging_dir.mkdir(parents=True)

    for entry in config_manifest_entries:
        filename = Path(entry["relative_path"]).name
        source_path = Path(target_config_dir) / filename
        destination_path = staging_dir / filename
        _copy_and_verify(
            source_path,
            destination_path,
            expected_sha256=entry["sha256"],
            expected_size=entry["size_bytes"],
            description=f"backup config payload {filename!r}",
        )

    if not same_volume(staging_dir, live_config_dir.parent):
        raise RestoreStagingFailedError(
            f"staged config directory {staging_dir} is not on the same volume as {live_config_dir.parent}; "
            "refusing to stage cross-volume."
        )
    return staging_dir


def superseded_config_path(live_config_dir: Path, restore_id: str) -> Path:
    """The restore-ID-scoped destination the current live config directory
    is renamed aside to -- never a fixed ``__superseded`` name. Raises
    ``RestorePathCollisionError`` if that exact path already exists."""
    live_config_dir = Path(live_config_dir)
    path = live_config_dir.parent / f"{live_config_dir.name}{SUPERSEDED_CONFIG_INFIX}{restore_id}"
    if path.exists():
        raise RestorePathCollisionError(f"restore-ID-scoped superseded config path already exists: {path}")
    return path


def replace_database(staged_db_path: Path, live_db_path: Path) -> None:
    """The single ``os.replace()`` that publishes the staged database over
    the live database path -- one atomic swap. Raises
    ``RestoreDatabaseReplacementFailedError`` on any OS failure."""
    try:
        os.replace(staged_db_path, live_db_path)
    except OSError as exc:
        raise RestoreDatabaseReplacementFailedError(
            f"could not replace live database at {live_db_path} with staged database {staged_db_path}: {exc}"
        ) from exc


def rename_config_aside(live_config_dir: Path, superseded_path: Path) -> None:
    """Step 1/2 of config replacement: rename the live config directory
    aside to its restore-ID-scoped superseded path."""
    try:
        os.rename(live_config_dir, superseded_path)
    except OSError as exc:
        raise RestoreConfigReplacementFailedError(
            f"could not rename live config directory {live_config_dir} aside to {superseded_path}: {exc}"
        ) from exc


def install_staged_config(staged_config_dir: Path, live_config_dir: Path, *, superseded_path: Path) -> None:
    """Step 2/2 of config replacement: rename the staged config directory
    into the canonical live config path. If this step fails, the live
    config directory is CURRENTLY MISSING -- config exists only at
    ``superseded_path`` and at ``staged_config_dir``. This is a
    crash-preserved intermediate state; Mission 1B-A1 implements no
    automatic recovery from it (locked scope item 18)."""
    try:
        os.rename(staged_config_dir, live_config_dir)
    except OSError as exc:
        raise RestoreConfigReplacementFailedError(
            f"live config directory was already renamed aside to {superseded_path}, but installing the "
            f"staged config directory at {live_config_dir} failed: {exc}. The live config directory is "
            f"CURRENTLY MISSING -- config now exists only at {superseded_path} and at the still-present "
            f"staging path {staged_config_dir}. No automatic recovery is implemented; preserve both paths "
            "and escalate to the Founder."
        ) from exc
