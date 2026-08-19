"""Recovery disposition: move an existing live object aside (Mission
1B-A2-3).

Implements exactly the contract Mission 1B-A2-3-Prep proved behaviorally
on Windows
(``docs/V2_MISSION_1B_A2_3_PREP_CLOSURE_2026-08-18.md``, "Proposed future
disposition contract"): fresh ``os.lstat()`` -> unsafe-object gate ->
re-derived type/classification (never trusts an earlier classification
result alone) -> same-volume gate -> destination non-existence gate (via
``os.lstat()``, never ``Path.exists()``) -> one collision-refusing
``os.rename()`` -> post-move verification. Never ``os.replace()`` (which
can silently succeed over an existing destination), never ``shutil.move``
(unused anywhere in this repository), no delete fallback, no overwrite
fallback, no retry, no rollback, no resume.

Disposition targets and their fixed, deterministic order:
``database`` -> ``config`` -> ``-journal`` -> ``-wal`` -> ``-shm``.
"""
from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path

from redline_core import fsutil
from redline_core.restore.exceptions import RecoveryDispositionFailedError
from redline_core.restore.staging import SUPERSEDED_CONFIG_INFIX, same_volume

DISPOSITION_ORDER: tuple[str, ...] = ("database", "config", "-journal", "-wal", "-shm")


@dataclass(frozen=True, slots=True)
class DispositionResult:
    target_kind: str
    source_path: Path
    superseded_path: Path


def superseded_disposition_path(source_path: Path, *, restore_id: str) -> Path:
    """The restore-ID-scoped destination one disposed live object is
    moved aside to -- the exact same naming convention
    ``staging.superseded_config_path()`` already uses (never a fixed
    name), generalized here to any disposition target (database file,
    config directory, or sidecar file). Raises
    ``RecoveryDispositionFailedError`` if that exact path already exists;
    the real collision authority remains the rename itself."""
    source_path = Path(source_path)
    destination = source_path.parent / f"{source_path.name}{SUPERSEDED_CONFIG_INFIX}{restore_id}"
    try:
        os.lstat(destination)
    except FileNotFoundError:
        return destination
    except OSError as exc:
        raise RecoveryDispositionFailedError(f"cannot inspect proposed disposition destination {destination}: {exc}") from exc
    raise RecoveryDispositionFailedError(f"restore-ID-scoped disposition destination already exists: {destination}")


def dispose_target(source_path: Path, *, target_kind: str, expected_regular: bool, restore_id: str) -> DispositionResult:
    """Move the live object currently at ``source_path`` aside to a
    fresh, restore-ID-scoped superseded path. Never deletes, never
    overwrites, never retries, never rolls back.

    ``expected_regular`` states what re-derived ``lstat()`` type this
    caller expects to find right now: ``True`` for the evidence-
    preservation case (an ordinary regular file, e.g. an unreadable
    database, being preserved rather than silently overwritten);
    ``False`` for the wrong-type case (a non-regular object, e.g. a
    directory sitting at the database path, or a regular file sitting at
    the config path). A mismatch against this attempt's own earlier
    classification is treated as fresher, more current ground truth, and
    fails closed rather than proceeding on a stale assumption.
    """
    source_path = Path(source_path)

    try:
        st = os.lstat(source_path)
    except FileNotFoundError as exc:
        raise RecoveryDispositionFailedError(
            f"disposition target {target_kind!r} at {source_path} does not exist; nothing to move aside."
        ) from exc
    except OSError as exc:
        raise RecoveryDispositionFailedError(f"cannot inspect disposition target {target_kind!r} at {source_path}: {exc}") from exc

    if fsutil.is_unsafe_link(st):
        raise RecoveryDispositionFailedError(
            f"disposition target {target_kind!r} at {source_path} is a symlink, junction, or reparse point; "
            "never moved, never followed -- RECOVERY_BLOCKED semantics apply, not disposition."
        )

    is_regular = stat_module.S_ISREG(st.st_mode)
    if is_regular != expected_regular:
        raise RecoveryDispositionFailedError(
            f"disposition target {target_kind!r} at {source_path} re-derived type (regular={is_regular}) no "
            f"longer matches the expected type (regular={expected_regular}) this disposition attempt was "
            "built for; refusing to act on a stale classification."
        )

    destination = superseded_disposition_path(source_path, restore_id=restore_id)

    if not same_volume(source_path, source_path.parent):
        raise RecoveryDispositionFailedError(
            f"disposition target {target_kind!r} at {source_path} is not on the same volume as its own "
            "parent directory; refusing to attempt a cross-volume rename."
        )

    try:
        os.lstat(destination)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RecoveryDispositionFailedError(f"cannot inspect disposition destination {destination} for {target_kind!r}: {exc}") from exc
    else:
        raise RecoveryDispositionFailedError(
            f"disposition destination for {target_kind!r} already exists: {destination}; refusing to overwrite."
        )

    try:
        os.rename(source_path, destination)
    except OSError as exc:
        raise RecoveryDispositionFailedError(
            f"disposition move-aside failed for {target_kind!r} ({source_path} -> {destination}): {exc}. The "
            "filesystem is left exactly as observed before this attempt -- no force, no delete, no overwrite "
            "fallback, no retry."
        ) from exc

    try:
        os.lstat(source_path)
    except FileNotFoundError:
        pass
    else:
        raise RecoveryDispositionFailedError(
            f"post-move verification failed for {target_kind!r}: {source_path} still exists after the "
            "disposition rename reported success."
        )
    try:
        os.lstat(destination)
    except OSError as exc:
        raise RecoveryDispositionFailedError(
            f"post-move verification failed for {target_kind!r}: disposed object does not exist at {destination}: {exc}"
        ) from exc

    return DispositionResult(target_kind=target_kind, source_path=source_path, superseded_path=destination)
