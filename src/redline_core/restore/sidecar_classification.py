"""Shared SQLite sidecar safety classification (Mission 1B-A2-3-Prep2).

The **one** authoritative, read-only classifier for a recognized SQLite
sidecar path (``-journal``/``-wal``/``-shm``, ``redline_core.restore.
sidecar.SIDECAR_SUFFIXES``), distinguishing four conditions:

  MISSING       -- the exact sidecar path does not exist.
  SAFE_REGULAR  -- exists, is not an unsafe filesystem object, and is an
                   ordinary regular file.
  WRONG_TYPE    -- exists, is not an unsafe filesystem object, but is not
                   an ordinary regular file (e.g. a directory).
  UNSAFE        -- exists (or its own link/reparse metadata does) and is a
                   symlink, Windows junction, or other reparse point --
                   detected via the same domain-neutral
                   ``redline_core.fsutil.is_unsafe_link()`` every other
                   unsafe-object check in this repository already uses.
                   An object whose own metadata cannot even be inspected
                   (an ``OSError`` other than ``FileNotFoundError`` --
                   e.g. permission denied) is conservatively folded into
                   this same UNSAFE bucket: its real type cannot be
                   safely determined, so -- mirroring
                   ``recovery_classification._cannot_inspect_assessment()``'s
                   identical "conservatively blocked rather than guessed
                   at" doctrine -- it is never treated as SAFE_REGULAR or
                   WRONG_TYPE by assumption.

Motivation: the locked Mission 1B-A1 ``redline_core.restore.sidecar.
find_present_sidecars()`` is deliberately ``Path.exists()``-based (correct
for its own fail-closed "must not proceed" purpose) and therefore blind to
a dangling unsafe sidecar -- ``exists()`` follows a symlink/junction/
reparse point and reports ``False`` for a broken target. Mission 1B-A2-2
already independently proved this exact defect and fixed it for capture
purposes (``capture_package.capture_sidecars()``'s Correction 4: a direct,
per-suffix ``os.lstat()`` probe). This module is that same lstat-based
observation, extracted once as a shared, reusable primitive -- read-only,
domain-neutral -- so Mission 1B-A2-1 recovery planning can finally see the
same truth Mission 1B-A2-2 capture already sees, instead of reimplementing
an independent third copy of this exact dispatch.

Strictly read-only: never follows an unsafe target, never opens anything,
never moves, renames, or deletes anything, never infers database health
from a sidecar's condition, and never mutates the filesystem in any way.
Uses ``os.lstat()`` exclusively -- never ``Path.exists()``/``Path.is_file()``,
both of which follow symlinks and are blind to a dangling reparse object.

This module does not decide *policy* (e.g. whether a given condition
blocks recovery) -- it only classifies. Mission 1B-A2-1's
``recovery_planning.build_recovery_plan()`` is the one place that
interprets ``SidecarCondition`` into a ``RECOVERY_BLOCKED``/blocking-issue
decision; Mission 1B-A2-2's ``capture_package.capture_sidecars()`` is the
other, interpreting it only as a MISSING-vs-not-missing gate ahead of its
own already-proven, unmodified per-item capture dispatch
(``capture_regular_file_item()``). Both consume this same classification
truth; neither reimplements it.
"""
from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from redline_core import fsutil
from redline_core.restore.sidecar import SIDECAR_SUFFIXES

_CANNOT_INSPECT_DETAIL_TEMPLATE = (
    "{path} could not be inspected ({error}); its type cannot be safely determined, so it is "
    "conservatively classified UNSAFE rather than guessed at."
)


class SidecarCondition(str, Enum):
    """The read-only, per-sidecar classification truth. Not an ordinal
    severity scale -- WRONG_TYPE is not "worse" than UNSAFE, they are
    simply different facts, mirroring
    ``redline_core.restore.recovery_models.SourceCondition``'s identical
    convention."""

    MISSING = "MISSING"
    """The exact sidecar path does not exist (``os.lstat()`` raises
    ``FileNotFoundError``)."""

    SAFE_REGULAR = "SAFE_REGULAR"
    """Exists, is not an unsafe filesystem object, and is an ordinary
    regular file -- the normal, expected shape of a live
    ``-journal``/``-wal``/``-shm`` sidecar."""

    WRONG_TYPE = "WRONG_TYPE"
    """Exists, is not an unsafe filesystem object, but is not an ordinary
    regular file (e.g. a directory occupies the sidecar path)."""

    UNSAFE = "UNSAFE"
    """A symlink, Windows junction, or other reparse point
    (``fsutil.is_unsafe_link()``) -- never followed, never opened, never
    inspected beyond its own link/reparse metadata. Also covers a path
    whose own metadata could not be inspected at all (permission denied or
    similar), conservatively folded in here rather than guessed at as
    SAFE_REGULAR or WRONG_TYPE."""


@dataclass(frozen=True, slots=True)
class SidecarAssessment:
    """One recognized sidecar suffix's read-only classification result.
    Never raised as an exception -- always returned, mirroring
    ``redline_core.restore.recovery_models.SourceSideAssessment``'s and
    ``redline_core.restore.capture_models.CaptureItemRecord``'s identical
    non-raising convention."""

    suffix: str
    path: str
    condition: SidecarCondition
    detail: str


def classify_sidecar(db_path: Path, suffix: str) -> SidecarAssessment:
    """Classify exactly one recognized sidecar suffix next to ``db_path``,
    strictly via ``os.lstat()``. Never follows, opens, or mutates the
    object; never touches ``db_path`` itself -- this function's result is
    completely independent of whether the database at ``db_path`` exists
    or is healthy (see this module's own docstring)."""
    db_path = Path(db_path)
    sidecar_path = Path(str(db_path) + suffix)

    try:
        st = os.lstat(sidecar_path)
    except FileNotFoundError:
        return SidecarAssessment(
            suffix=suffix,
            path=str(sidecar_path),
            condition=SidecarCondition.MISSING,
            detail=f"{sidecar_path} does not exist.",
        )
    except OSError as exc:
        return SidecarAssessment(
            suffix=suffix,
            path=str(sidecar_path),
            condition=SidecarCondition.UNSAFE,
            detail=_CANNOT_INSPECT_DETAIL_TEMPLATE.format(path=sidecar_path, error=exc),
        )

    if fsutil.is_unsafe_link(st):
        return SidecarAssessment(
            suffix=suffix,
            path=str(sidecar_path),
            condition=SidecarCondition.UNSAFE,
            detail=f"{sidecar_path} is a symlink, junction, or reparse point; never followed, never opened.",
        )

    if not stat_module.S_ISREG(st.st_mode):
        return SidecarAssessment(
            suffix=suffix,
            path=str(sidecar_path),
            condition=SidecarCondition.WRONG_TYPE,
            detail=f"{sidecar_path} exists but is not a regular file.",
        )

    return SidecarAssessment(
        suffix=suffix,
        path=str(sidecar_path),
        condition=SidecarCondition.SAFE_REGULAR,
        detail=f"{sidecar_path} is a safe regular file.",
    )


def classify_sidecars(db_path: Path) -> tuple[SidecarAssessment, ...]:
    """Classify every recognized sidecar suffix
    (``redline_core.restore.sidecar.SIDECAR_SUFFIXES``) next to ``db_path``,
    in suffix order. Always returns exactly ``len(SIDECAR_SUFFIXES)``
    assessments, one per suffix, regardless of how many are MISSING."""
    return tuple(classify_sidecar(db_path, suffix) for suffix in SIDECAR_SUFFIXES)
