"""Thin SQLite wrapper for Redline OS.

This is deliberately NOT an ORM. It owns schema initialization and a small
set of narrow, well-named methods for the tables in schema.sql. Higher-level
managers (Episode Manager, Render Manager, etc. — Phase 2+) call into this;
they should never construct raw SQL of their own.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from redline_core.db.models import ArchiveRecord, Episode, EpisodeStatus, RenderJob, RenderJobStatus

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Owns one SQLite connection and the schema applied to it."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> "Database":
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        logger.info("Connected to Redline OS database at %s", self.db_path)
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() or use it as a context manager.")
        return self._conn

    def init_schema(self) -> None:
        """Apply schema.sql. Safe to call repeatedly (uses CREATE TABLE IF NOT EXISTS)."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self.conn.commit()
        logger.info("Redline OS schema applied.")

    # -- Episode operations ------------------------------------------------

    def create_episode(self, episode_number: int, episode_id: str, project_name: str) -> Episode:
        cur = self.conn.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name) VALUES (?, ?, ?)",
            (episode_number, episode_id, project_name),
        )
        self.conn.commit()
        return self.get_episode_by_id(cur.lastrowid)

    def get_episode_by_id(self, row_id: int) -> Episode | None:
        row = self.conn.execute("SELECT * FROM episodes WHERE id = ?", (row_id,)).fetchone()
        return Episode.from_row(row) if row else None

    def get_episode_by_number(self, episode_number: int) -> Episode | None:
        row = self.conn.execute(
            "SELECT * FROM episodes WHERE episode_number = ?", (episode_number,)
        ).fetchone()
        return Episode.from_row(row) if row else None

    def get_episode_by_episode_id(self, episode_id: str) -> Episode | None:
        row = self.conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
        return Episode.from_row(row) if row else None

    def list_episodes(self) -> list[Episode]:
        rows = self.conn.execute("SELECT * FROM episodes ORDER BY episode_number").fetchall()
        return [Episode.from_row(row) for row in rows]

    def update_episode_status(self, episode_id: str, status: EpisodeStatus) -> None:
        self.conn.execute(
            "UPDATE episodes SET status = ?, updated_at = datetime('now') WHERE episode_id = ?",
            (status.value, episode_id),
        )
        self.conn.commit()

    def update_episode_paths(
        self,
        episode_id: str,
        project_path: str | None = None,
        folder_path: str | None = None,
    ) -> None:
        """Update project_path and/or folder_path once they're known.

        Only columns explicitly passed (non-None) are updated, so this can be
        called once after the folder is created and again after the Resolve
        project is duplicated, without clobbering the other field.
        """
        if project_path is None and folder_path is None:
            return
        fields, values = [], []
        if project_path is not None:
            fields.append("project_path = ?")
            values.append(project_path)
        if folder_path is not None:
            fields.append("folder_path = ?")
            values.append(folder_path)
        values.append(episode_id)
        self.conn.execute(
            f"UPDATE episodes SET {', '.join(fields)}, updated_at = datetime('now') WHERE episode_id = ?",
            values,
        )
        self.conn.commit()

    # -- Render job operations -----------------------------------------------

    def create_render_job(self, episode_id: str, preset_name: str) -> RenderJob:
        cur = self.conn.execute(
            "INSERT INTO render_jobs (episode_id, preset_name) VALUES (?, ?)",
            (episode_id, preset_name),
        )
        self.conn.commit()
        return self.get_render_job_by_id(cur.lastrowid)

    def get_render_job_by_id(self, job_id: int) -> RenderJob | None:
        row = self.conn.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return RenderJob.from_row(row) if row else None

    def list_render_jobs_for_episode(self, episode_id: str) -> list[RenderJob]:
        rows = self.conn.execute(
            "SELECT * FROM render_jobs WHERE episode_id = ? ORDER BY id", (episode_id,)
        ).fetchall()
        return [RenderJob.from_row(row) for row in rows]

    def update_render_job(
        self,
        job_id: int,
        resolve_job_id: str | None = None,
        status: RenderJobStatus | None = None,
        output_path: str | None = None,
    ) -> None:
        """Update whichever of resolve_job_id/status/output_path are passed (non-None)."""
        fields, values = [], []
        if resolve_job_id is not None:
            fields.append("resolve_job_id = ?")
            values.append(resolve_job_id)
        if status is not None:
            fields.append("status = ?")
            values.append(status.value)
        if output_path is not None:
            fields.append("output_path = ?")
            values.append(output_path)
        if not fields:
            return
        values.append(job_id)
        self.conn.execute(
            f"UPDATE render_jobs SET {', '.join(fields)}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
        self.conn.commit()

    # -- Archive operations ---------------------------------------------------

    def create_archive_record(self, episode_id: str, archive_path: str) -> ArchiveRecord:
        cur = self.conn.execute(
            "INSERT INTO archives (episode_id, archive_path) VALUES (?, ?)",
            (episode_id, archive_path),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM archives WHERE id = ?", (cur.lastrowid,)).fetchone()
        return ArchiveRecord.from_row(row)

    def get_archive_by_episode_id(self, episode_id: str) -> ArchiveRecord | None:
        row = self.conn.execute("SELECT * FROM archives WHERE episode_id = ?", (episode_id,)).fetchone()
        return ArchiveRecord.from_row(row) if row else None

    def list_archives(self) -> list[ArchiveRecord]:
        rows = self.conn.execute("SELECT * FROM archives ORDER BY archived_at").fetchall()
        return [ArchiveRecord.from_row(row) for row in rows]
