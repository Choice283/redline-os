"""SQLite sidecar gate (Mission 1B-A1).

A ``-journal``, ``-wal``, or ``-shm`` file next to a SQLite database means
another connection may still hold state against it (an in-progress
rollback journal, a WAL that has not been checkpointed, or shared-memory
index state) -- restoring over a database in that condition risks silently
discarding or corrupting that state. This module never deletes, renames, or
otherwise "recovers" a sidecar it finds; every check here is fail-closed
only: report presence, refuse to proceed.
"""
from __future__ import annotations

from pathlib import Path

from redline_core.restore.exceptions import RestoreSidecarPresentError

SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


def find_present_sidecars(db_path: Path) -> tuple[Path, ...]:
    """Return every sidecar path that currently exists next to ``db_path``.
    Read-only: performs no writes and never touches a sidecar it finds."""
    db_path = Path(db_path)
    return tuple(
        candidate
        for suffix in SIDECAR_SUFFIXES
        if (candidate := Path(str(db_path) + suffix)).exists()
    )


def require_no_sidecars(db_path: Path, *, when: str) -> None:
    """Raise ``RestoreSidecarPresentError`` if any sidecar exists next to
    ``db_path``. ``when`` names the checkpoint (e.g. "before database
    replacement", "after database replacement, before opening a SQLite
    connection to the restored database") for a precise, actionable error
    message. Never deletes, renames, or recovers anything it finds."""
    present = find_present_sidecars(db_path)
    if present:
        raise RestoreSidecarPresentError(
            f"SQLite sidecar file(s) present {when} for {db_path}: "
            f"{[str(p) for p in present]}. Sidecars are never deleted, renamed, or recovered "
            "automatically by Mission 1B-A1 -- refusing to proceed."
        )
