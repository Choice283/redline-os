"""SQLite Online Backup API wrapper (Mission 1A).

Determined from source, not assumed: ``redline_core.db.database.Database``
sets exactly one PRAGMA (``foreign_keys = ON``) and no ``journal_mode`` --
SQLite's own default is ``DELETE`` (rollback-journal), not WAL -- and most
mutating methods either commit immediately or wrap a short multi-statement
sequence in ``with self.conn:``. A raw filesystem copy of the live database
file can therefore capture a torn main-file/journal pair during one of
those short open-transaction windows. This module never performs a raw
copy: it opens the source through a **read-only** connection and uses
Python's stdlib ``sqlite3.Connection.backup()`` (SQLite's Online Backup
API), which reads through SQLite's own consistency machinery and produces
a destination file representing one consistent point in time regardless of
concurrent writer activity on the source.

Nothing here ever calls ``BEGIN``/``COMMIT``/any write statement against
the source connection, and nothing here ever touches DaVinci Resolve.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from redline_core.backup.exceptions import BackupDatabaseSnapshotError, BackupIntegrityCheckFailedError

_EXPECTED_INTEGRITY_OK = "ok"
_PROBED_TABLES = ("episodes", "render_jobs", "archives")


def _read_only_uri(db_path: Path) -> str:
    """Build a ``file:`` URI opening ``db_path`` strictly read-only.

    Uses ``Path.as_uri()`` (requires an absolute path; callers always pass
    an already-resolved path) rather than hand-built string concatenation,
    so Windows drive-letter paths are escaped correctly by the stdlib
    rather than by ad hoc logic.
    """
    return f"{db_path.as_uri()}?mode=ro"


def snapshot_database(source_db_path: Path, destination_db_path: Path) -> None:
    """Create a consistent point-in-time SQLite snapshot of
    ``source_db_path`` at ``destination_db_path`` via SQLite's Online
    Backup API, through an independent read-only source connection.

    Never mutates the source: the source connection is opened read-only
    (``mode=ro``) and only ever used as the argument to ``backup()``'s
    read side. ``destination_db_path``'s parent directory is created if
    needed; ``destination_db_path`` itself must not already exist as a
    non-empty file (the caller is responsible for staging into a fresh
    location -- this function does not check for or reject an existing
    destination itself, since staging-directory freshness is the caller's
    contract, not a SQLite-snapshot concern).
    """
    destination_db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        source_conn = sqlite3.connect(_read_only_uri(source_db_path), uri=True)
    except sqlite3.Error as exc:
        raise BackupDatabaseSnapshotError(
            f"could not open live database read-only for snapshot: {source_db_path}"
        ) from exc

    try:
        try:
            destination_conn = sqlite3.connect(str(destination_db_path))
        except sqlite3.Error as exc:
            raise BackupDatabaseSnapshotError(
                f"could not open backup snapshot destination: {destination_db_path}"
            ) from exc
        try:
            source_conn.backup(destination_conn)
        except sqlite3.Error as exc:
            raise BackupDatabaseSnapshotError(
                f"SQLite Online Backup API failed for {source_db_path} -> {destination_db_path}"
            ) from exc
        finally:
            destination_conn.close()
    finally:
        source_conn.close()


def run_integrity_check(db_path: Path) -> str:
    """Run ``PRAGMA integrity_check`` against ``db_path``, opened
    read-only. Returns the raw result string (``"ok"`` on success).
    Raises ``BackupIntegrityCheckFailedError`` if the database cannot even
    be opened/queried -- a distinct condition from a successful query
    that reports corruption, which the caller distinguishes by comparing
    the returned string, not by exception.
    """
    try:
        conn = sqlite3.connect(_read_only_uri(db_path), uri=True)
    except sqlite3.Error as exc:
        raise BackupIntegrityCheckFailedError(f"could not open backup copy for integrity check: {db_path}") from exc
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise BackupIntegrityCheckFailedError(f"PRAGMA integrity_check failed to run: {db_path}") from exc
    finally:
        conn.close()

    if len(rows) == 1 and rows[0][0] == _EXPECTED_INTEGRITY_OK:
        return _EXPECTED_INTEGRITY_OK
    return "; ".join(str(row[0]) for row in rows) if rows else "no result"


def require_integrity_ok(db_path: Path) -> str:
    """``run_integrity_check()``, raising ``BackupIntegrityCheckFailedError``
    unless the result is exactly ``"ok"``."""
    result = run_integrity_check(db_path)
    if result != _EXPECTED_INTEGRITY_OK:
        raise BackupIntegrityCheckFailedError(
            f"PRAGMA integrity_check did not return 'ok' for {db_path}: {result}"
        )
    return result


def probe_schema(db_path: Path) -> dict[str, list[str]]:
    """Ground-truth schema fingerprint of the three pipeline tables
    (`episodes`, `render_jobs`, `archives` -- `redline_core.db.schema.sql`'s
    own tables; the separate, unwired Asset Registry schema is out of
    Mission 1A's scope entirely, see docs/BACKUP_RECOVERY_ARCHITECTURE.md),
    read via ``PRAGMA table_info(...)`` against a read-only connection.

    `redline_core.db.schema.sql` has no `schema_version`/`user_version`
    marker of its own (determined from source, not assumed) -- this probe
    records the actual column shape instead of inventing a version number
    the application itself does not have.
    """
    try:
        conn = sqlite3.connect(_read_only_uri(db_path), uri=True)
    except sqlite3.Error as exc:
        raise BackupIntegrityCheckFailedError(f"could not open backup copy to probe schema: {db_path}") from exc
    try:
        probe: dict[str, list[str]] = {}
        for table in _PROBED_TABLES:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            probe[f"{table}_columns"] = sorted(row[1] for row in rows)
        return probe
    except sqlite3.Error as exc:
        raise BackupIntegrityCheckFailedError(f"could not probe schema for {db_path}") from exc
    finally:
        conn.close()
