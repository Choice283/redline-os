"""Thin SQLite wrapper for Redline OS.

This is deliberately NOT an ORM. It owns schema initialization and a small
set of narrow, well-named methods for the tables in schema.sql. Higher-level
managers (Episode Manager, Render Manager, etc. — Phase 2+) call into this;
they should never construct raw SQL of their own.
"""
from __future__ import annotations

import logging
import sqlite3
from importlib.resources import files
from pathlib import Path

from redline_core.db.models import ArchiveRecord, Episode, EpisodeStatus, RenderJob, RenderJobStatus

logger = logging.getLogger(__name__)

_SCHEMA_PACKAGE = "redline_core.db"
_SCHEMA_RESOURCE = "schema.sql"

_TERMINAL_ASSEMBLY_STATUSES = ("assembled", "render_queued", "rendered", "archived")
_ACTIVE_RENDER_OUTPUT_STATUSES = (
    RenderJobStatus.CLAIMING.value,
    RenderJobStatus.QUEUED.value,
    RenderJobStatus.RENDERING.value,
)


def _read_schema_sql() -> str:
    schema_resource = files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_RESOURCE)
    return schema_resource.read_text(encoding="utf-8")


class AssemblyClaimReleaseError(RuntimeError):
    """Raised by release_assembly_claim() when no row matches the given
    episode_id + claim_token -- i.e. the caller's claim was superseded (a
    newer claim now owns the row) or the row otherwise changed unexpectedly.

    This is deliberately a hard failure, not a log-and-continue condition.
    On the success path, EpisodeManager.build_episode() must convert this
    into a real EpisodeBuildError (status_update stage) rather than return
    an EpisodeBuildResult while the episode was never actually marked
    ASSEMBLED and the claim was never actually cleared (ADR-0001).
    """


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
        """Apply schema.sql. Safe to call repeatedly (uses CREATE TABLE IF NOT EXISTS).

        Also runs any pending column migrations (see _migrate_add_assembly_claim_columns)
        against a database created before those columns existed. This method
        intentionally does not catch or suppress any exception from that step:
        if a migration cannot complete, this call raises, the composition
        builder that invoked it fails, and Redline OS refuses to start rather
        than continue against a partially migrated schema.
        """
        sql = _read_schema_sql()
        self.conn.executescript(sql)
        self._migrate_add_assembly_claim_columns()
        self._migrate_add_render_job_identity_columns()
        self._migrate_add_active_render_output_index()
        self.conn.commit()
        logger.info("Redline OS schema applied.")

    def _migrate_add_assembly_claim_columns(self) -> None:
        """Add assembly_claim_token/assembly_claimed_at to a pre-Mission-13
        episodes table that predates them. CREATE TABLE IF NOT EXISTS above
        is a no-op against an already-existing table, so this is the actual
        upgrade path for a database created before this migration existed.
        No try/except here by design -- see init_schema()'s docstring.
        """
        existing_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(episodes)").fetchall()}
        if "assembly_claim_token" not in existing_columns:
            self.conn.execute("ALTER TABLE episodes ADD COLUMN assembly_claim_token TEXT")
            logger.info("Migrated episodes table: added assembly_claim_token column.")
        if "assembly_claimed_at" not in existing_columns:
            self.conn.execute("ALTER TABLE episodes ADD COLUMN assembly_claimed_at TEXT")
            logger.info("Migrated episodes table: added assembly_claimed_at column.")

    def _migrate_add_render_job_identity_columns(self) -> None:
        existing_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(render_jobs)").fetchall()}
        if "project_name" not in existing_columns:
            self.conn.execute("ALTER TABLE render_jobs ADD COLUMN project_name TEXT")
            logger.info("Migrated render_jobs table: added project_name column.")
        if "timeline_name" not in existing_columns:
            self.conn.execute("ALTER TABLE render_jobs ADD COLUMN timeline_name TEXT")
            logger.info("Migrated render_jobs table: added timeline_name column.")

    def _migrate_add_active_render_output_index(self) -> None:
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_render_jobs_active_output_path "
            "ON render_jobs(output_path) "
            "WHERE output_path IS NOT NULL AND status IN ('claiming', 'queued', 'rendering')"
        )

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

    # -- Episode assembly claim (ADR-0001) -------------------------------------

    def claim_episode_for_assembly(
        self, episode_id: str, claim_token: str, *, allow_unsafe_retry: bool = False
    ) -> bool:
        """Atomically claim an episode for assembly. Returns True iff the
        claim was acquired by this call.

        allow_unsafe_retry=False: one UPDATE ... WHERE statement -- eligibility
        and claim acquisition are the same atomic repository operation
        (ADR-0001 invariant 6). Claimable only from CREATED, ASSETS_VERIFIED,
        MEDIA_ORGANIZED, or TIMELINE_BUILT, and only if no claim is already
        active or unresolved (assembly_claim_token IS NULL).

        allow_unsafe_retry=True: delegates to _claim_episode_for_assembly_cas()
        (see its docstring for why a plain "drop the token guard" UPDATE is
        unsafe under concurrent forced callers). The SELECT below is
        diagnostic only -- it does not authorize the mutation; the guarded
        UPDATE inside the CAS helper is the sole authority on whether the
        claim was acquired.
        """
        if not allow_unsafe_retry:
            cur = self.conn.execute(
                "UPDATE episodes SET assembly_claim_token = ?, assembly_claimed_at = datetime('now') "
                "WHERE episode_id = ? AND assembly_claim_token IS NULL "
                "AND status IN ('created', 'assets_verified', 'media_organized', 'timeline_built')",
                (claim_token, episode_id),
            )
            self.conn.commit()
            return cur.rowcount == 1

        row = self.conn.execute(
            "SELECT status, assembly_claim_token FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            return False
        return self._claim_episode_for_assembly_cas(
            episode_id,
            claim_token,
            observed_status=row["status"],
            observed_token=row["assembly_claim_token"],
        )

    def _claim_episode_for_assembly_cas(
        self,
        episode_id: str,
        claim_token: str,
        *,
        observed_status: str,
        observed_token: str | None,
    ) -> bool:
        """The authoritative forced-claim (allow_unsafe_retry=True) acquisition
        operation: a compare-and-swap UPDATE pinned to the exact (status,
        assembly_claim_token) pair the caller observed, not a bare "status is
        non-terminal" guard.

        Why this is required: a naive forced UPDATE guarded only by
        `status NOT IN (terminal...)` has no dependency on the claim token at
        all, so two forced callers racing the same dangling claim can both
        satisfy that guard and both acquire it -- violating ADR-0001's single-
        claimant invariant. Pinning the UPDATE's WHERE clause to the specific
        token (or `IS NULL`) the caller observed means that once either racer
        commits, the row's actual assembly_claim_token no longer matches what
        the other racer observed, so the second UPDATE's WHERE clause fails
        to match (rowcount 0) even though both callers started from the same
        observed state. SQLite evaluates each UPDATE's WHERE clause against
        the row's current, real state at the moment that statement executes
        -- the preceding SELECT is diagnostic input to this call, not a lock;
        this guarded UPDATE is what actually decides ownership.

        Note this intentionally still allows a *sequential* second forced
        call (one that freshly observes the first call's already-committed
        token and correctly CASes against it) to take over -- that is an
        operator issuing --force a second time with accurate, current
        information, not a race, and is not what this method defends
        against.

        Exposed as its own method (rather than inlined) so tests can supply
        two independently "observed" (status, token) pairs pinned to the
        same pre-race values and assert exactly one of two calls succeeds,
        deterministically, without depending on real thread/process
        scheduling to reproduce the race.
        """
        if observed_status in _TERMINAL_ASSEMBLY_STATUSES:
            return False
        if observed_token is None:
            cur = self.conn.execute(
                "UPDATE episodes SET assembly_claim_token = ?, assembly_claimed_at = datetime('now') "
                "WHERE episode_id = ? AND status = ? AND assembly_claim_token IS NULL",
                (claim_token, episode_id, observed_status),
            )
        else:
            cur = self.conn.execute(
                "UPDATE episodes SET assembly_claim_token = ?, assembly_claimed_at = datetime('now') "
                "WHERE episode_id = ? AND status = ? AND assembly_claim_token = ?",
                (claim_token, episode_id, observed_status, observed_token),
            )
        self.conn.commit()
        return cur.rowcount == 1

    def release_assembly_claim(self, episode_id: str, claim_token: str, status: EpisodeStatus) -> None:
        """Atomically set the final status and clear the assembly claim in
        one statement -- but only if claim_token still matches the row's
        current assembly_claim_token. This makes release token-owned: a
        caller can only release the specific claim it acquired, never one
        acquired by a different attempt (ADR-0001 refinement 1).

        Raises AssemblyClaimReleaseError if no row matches (rowcount == 0):
        the token no longer matches (superseded by a newer claim) or the
        episode no longer exists. This is a hard failure by design -- see
        the exception's own docstring for why silently logging and
        returning is not safe here.
        """
        cur = self.conn.execute(
            "UPDATE episodes SET status = ?, assembly_claim_token = NULL, assembly_claimed_at = NULL, "
            "updated_at = datetime('now') WHERE episode_id = ? AND assembly_claim_token = ?",
            (status.value, episode_id, claim_token),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            raise AssemblyClaimReleaseError(
                f"release_assembly_claim: no row matched episode_id={episode_id} with "
                f"claim_token={claim_token} -- the claim may have been superseded. Status "
                "was not updated by this call."
            )

    # -- Render job operations -----------------------------------------------

    def create_render_job(
        self,
        episode_id: str,
        preset_name: str,
        *,
        resolve_job_id: str | None = None,
        project_name: str | None = None,
        timeline_name: str | None = None,
        output_path: str | None = None,
        status: RenderJobStatus = RenderJobStatus.QUEUED,
    ) -> RenderJob:
        cur = self.conn.execute(
            "INSERT INTO render_jobs "
            "(episode_id, preset_name, resolve_job_id, project_name, timeline_name, status, output_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (episode_id, preset_name, resolve_job_id, project_name, timeline_name, status.value, output_path),
        )
        self.conn.commit()
        return self.get_render_job_by_id(cur.lastrowid)

    def create_accepted_render_job(
        self,
        *,
        episode_id: str,
        preset_name: str,
        resolve_job_id: str,
        project_name: str,
        timeline_name: str,
        output_path: str,
    ) -> RenderJob:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO render_jobs "
                "(episode_id, preset_name, resolve_job_id, project_name, timeline_name, status, output_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    episode_id,
                    preset_name,
                    resolve_job_id,
                    project_name,
                    timeline_name,
                    RenderJobStatus.QUEUED.value,
                    output_path,
                ),
            )
            self._mark_episode_render_queued(episode_id)
            row = self.conn.execute("SELECT * FROM render_jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
            if row is None:
                raise RuntimeError(f"Could not reload accepted render job {cur.lastrowid}.")
            return RenderJob.from_row(row)

    def claim_render_output(
        self,
        *,
        episode_id: str,
        preset_name: str,
        project_name: str,
        timeline_name: str,
        output_path: str,
    ) -> RenderJob | None:
        try:
            cur = self.conn.execute(
                "INSERT INTO render_jobs "
                "(episode_id, preset_name, project_name, timeline_name, status, output_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    episode_id,
                    preset_name,
                    project_name,
                    timeline_name,
                    RenderJobStatus.CLAIMING.value,
                    output_path,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            if "render_jobs.output_path" not in str(exc):
                raise
            return None

        return self.get_render_job_by_id(cur.lastrowid)

    def finalize_render_output_claim(self, claim_id: int, resolve_job_id: str) -> RenderJob:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE render_jobs SET resolve_job_id = ?, status = ?, updated_at = datetime('now') "
                "WHERE id = ? AND status = ?",
                (resolve_job_id, RenderJobStatus.QUEUED.value, claim_id, RenderJobStatus.CLAIMING.value),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"Could not finalize render output claim {claim_id}.")
            row = self.conn.execute("SELECT * FROM render_jobs WHERE id = ?", (claim_id,)).fetchone()
            if row is None:
                raise RuntimeError(f"Could not reload finalized render output claim {claim_id}.")
            self._mark_episode_render_queued(row["episode_id"])
            return RenderJob.from_row(row)

    def release_render_output_claim(self, claim_id: int) -> None:
        cur = self.conn.execute(
            "DELETE FROM render_jobs WHERE id = ? AND status = ?",
            (claim_id, RenderJobStatus.CLAIMING.value),
        )
        self.conn.commit()
        if cur.rowcount != 1:
            raise RuntimeError(f"Could not release render output claim {claim_id}.")

    def _mark_episode_render_queued(self, episode_id: str) -> None:
        updated = self.conn.execute(
            "UPDATE episodes SET status = ?, updated_at = datetime('now') WHERE episode_id = ?",
            (EpisodeStatus.RENDER_QUEUED.value, episode_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError(f"Could not mark episode {episode_id!r} render_queued.")

    def get_render_job_by_id(self, job_id: int) -> RenderJob | None:
        row = self.conn.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return RenderJob.from_row(row) if row else None

    def list_render_jobs_for_episode(self, episode_id: str) -> list[RenderJob]:
        rows = self.conn.execute(
            "SELECT * FROM render_jobs WHERE episode_id = ? ORDER BY id", (episode_id,)
        ).fetchall()
        return [RenderJob.from_row(row) for row in rows]

    def get_active_render_job_by_output_path(self, output_path: str) -> RenderJob | None:
        rows = self.conn.execute(
            "SELECT * FROM render_jobs WHERE output_path = ? AND status IN (?, ?, ?) ORDER BY id LIMIT 1",
            (output_path, *_ACTIVE_RENDER_OUTPUT_STATUSES),
        ).fetchall()
        return RenderJob.from_row(rows[0]) if rows else None

    def transition_render_job_to_rendering(self, job_id: int) -> bool:
        """Guarded `QUEUED -> RENDERING` transition for a single render job.

        Only called by `RenderManager.start_render()` after the Resolve
        adapter has already independently confirmed (via its own
        getter-only postcondition check) that the target job is `Rendering`
        live in Resolve. The `WHERE status = QUEUED` guard means this only
        ever affects a row still exactly `QUEUED` at the moment of the
        update — never a row that has already drifted to some other status
        between the caller's earlier read and this write.

        Returns True iff exactly one row was updated. A False return (zero
        or, in principle, more than one row affected) or a raised exception
        both mean the caller cannot trust that Redline's database now
        reflects the confirmed-live `Rendering` state — see
        `RenderStartPersistenceReconciliationRequiredError`.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE render_jobs SET status = ?, updated_at = datetime('now') WHERE id = ? AND status = ?",
                (RenderJobStatus.RENDERING.value, job_id, RenderJobStatus.QUEUED.value),
            )
        return cur.rowcount == 1

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
