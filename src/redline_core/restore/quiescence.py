"""Quiescence probe + operator attestations (Mission 1B-A1).

Two distinct, separately-checked things, never conflated:

1. ``probe_quiescence()`` -- the only *proved* precondition: opens a fresh,
   independent SQLite connection to the live database, attempts
   ``BEGIN IMMEDIATE`` with a zero timeout (so a held reserved/write lock
   fails immediately rather than blocking), then rolls back and closes the
   connection before returning. A successful probe proves no other
   connection currently holds a reserved or exclusive lock on the live
   database at that instant -- it proves nothing about what happens a
   moment later, and it is not a lock Restore itself holds afterward (the
   probe connection is fully closed before database replacement, per
   locked scope item 8).

2. ``require_attestations()`` -- three itemized, operator-supplied
   attestations (MCP stopped, Control Room stopped, no other Redline CLI
   operation in flight) that this module trusts but cannot itself verify.
   Mission 1B-A1 implements no new process-supervision framework to check
   these independently.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from redline_core.restore.exceptions import RestoreAttestationMissingError, RestoreQuiescenceFailedError
from redline_core.restore.models import QuiescenceAttestations


def probe_quiescence(db_path: Path) -> None:
    """Prove no other connection currently holds a write lock on
    ``db_path``. Raises ``RestoreQuiescenceFailedError`` if the database
    cannot be opened at all, or if ``BEGIN IMMEDIATE`` cannot acquire the
    lock immediately. The probe connection is always rolled back and
    closed before this function returns, success or failure.

    If ``db_path`` does not currently exist (the exact "database missing"
    scenario Restore exists to recover from), this is a no-op: there is
    nothing to be quiescent against, and -- critically -- ``sqlite3.connect()``
    would otherwise silently create a new empty database file as a side
    effect of merely probing, which would be a real mutation from what
    ``backup restore-plan`` promises is a read-only operation.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path), timeout=0)
    except sqlite3.Error as exc:
        raise RestoreQuiescenceFailedError(f"could not open {db_path} to probe quiescence: {exc}") from exc

    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise RestoreQuiescenceFailedError(
                f"could not acquire an immediate write lock on {db_path} -- another connection appears to "
                f"hold it (database not quiescent): {exc}"
            ) from exc
        else:
            conn.rollback()
    finally:
        conn.close()


def require_attestations(attestations: QuiescenceAttestations) -> None:
    """Raise ``RestoreAttestationMissingError`` naming every missing
    attestation if any of the three itemized attestations is not
    explicitly True."""
    missing = attestations.missing()
    if missing:
        raise RestoreAttestationMissingError(
            "the following required quiescence attestation(s) were not given: "
            f"{', '.join(missing)}. All three must be explicitly attested before a destructive restore may "
            "proceed."
        )
