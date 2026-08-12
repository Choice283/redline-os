"""Thin SQLite wrapper for Redline OS.

This is deliberately NOT an ORM. It owns schema initialization and a small
set of narrow, well-named methods for the tables in schema.sql. Higher-level
managers (Episode Manager, Render Manager, etc. — Phase 2+) call into this;
they should never construct raw SQL of their own.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from importlib.resources import files
from pathlib import Path

from redline_core.db.models import ArchiveRecord, ArchiveState, Episode, EpisodeStatus, RenderJob, RenderJobStatus

logger = logging.getLogger(__name__)

_SCHEMA_PACKAGE = "redline_core.db"
_SCHEMA_RESOURCE = "schema.sql"

_TERMINAL_ASSEMBLY_STATUSES = ("assembled", "render_queued", "rendered", "archived")
_ACTIVE_RENDER_OUTPUT_STATUSES = (
    RenderJobStatus.CLAIMING.value,
    RenderJobStatus.QUEUED.value,
    RenderJobStatus.RENDERING.value,
)
_MANIFEST_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalize_manifest_sha256(value: object) -> str:
    """Validate and canonicalize a manifest_sha256 input for
    commit_verified_archive().

    This never computes a hash -- Mission 15B receives an already-computed
    digest from the caller (a future Archive Manager Rev1). It only
    enforces that the digest is structurally a SHA-256: exactly 64
    hexadecimal characters (32 bytes). Uppercase/mixed-case hex is
    accepted for caller ergonomics but always normalized to lowercase
    before being returned for storage, so two callers supplying the same
    digest in different casing produce the same stored value.
    """
    if not isinstance(value, str) or not _MANIFEST_SHA256_RE.fullmatch(value):
        raise ArchiveCommitError(
            "manifest_sha256 must be exactly 64 hexadecimal characters (a SHA-256 digest)."
        )
    return value.lower()


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


class ArchiveCommitError(RuntimeError):
    """Raised by commit_verified_archive() when a required precondition is
    not met (episode missing/not rendered, render job missing/not owned by
    the episode/not complete, an archive already exists for the episode) or
    when the guarded rendered -> archived episode transition does not
    affect exactly one row.

    Phase 15 Rev1 (Mission 15B): this is a database-layer-only failure.
    Every raise happens either before the transaction opens (a pre-check,
    for a precise message) or inside it, in which case Python's sqlite3
    context-manager rollback (see commit_verified_archive()'s docstring)
    guarantees no archive row survives -- the insert and the episode
    transition succeed together or not at all.
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
        self._migrate_add_archive_rev1_columns()
        self._migrate_add_archive_id_unique_index()
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

    def _migrate_add_archive_rev1_columns(self) -> None:
        """Add the Phase 15 Rev1 archive-identity columns to a pre-Rev1
        archives table that predates them. CREATE TABLE IF NOT EXISTS above
        is a no-op against an already-existing table, so this is the actual
        upgrade path for a database created before this migration existed.

        The DEFAULT values on archive_schema_version/archive_state
        deliberately backfill every pre-existing row as
        (archive_schema_version=0, archive_state='legacy') -- they are
        historical archive records, not verified Rev1 archives, and must
        never be silently reclassified as such. Only
        Database.commit_verified_archive() may write
        (archive_schema_version=1, archive_state='complete'). No try/except
        here by design -- see init_schema()'s docstring.
        """
        existing_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(archives)").fetchall()}
        if "archive_id" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN archive_id TEXT")
            logger.info("Migrated archives table: added archive_id column.")
        if "archive_schema_version" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN archive_schema_version INTEGER NOT NULL DEFAULT 0")
            logger.info("Migrated archives table: added archive_schema_version column (existing rows -> 0).")
        if "archive_state" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN archive_state TEXT NOT NULL DEFAULT 'legacy'")
            logger.info("Migrated archives table: added archive_state column (existing rows -> 'legacy').")
        if "manifest_path" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN manifest_path TEXT")
            logger.info("Migrated archives table: added manifest_path column.")
        if "manifest_sha256" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN manifest_sha256 TEXT")
            logger.info("Migrated archives table: added manifest_sha256 column.")
        if "render_job_id" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN render_job_id INTEGER REFERENCES render_jobs(id)")
            logger.info("Migrated archives table: added render_job_id column.")
        if "verified_at" not in existing_columns:
            self.conn.execute("ALTER TABLE archives ADD COLUMN verified_at TEXT")
            logger.info("Migrated archives table: added verified_at column.")

    def _migrate_add_archive_id_unique_index(self) -> None:
        """Enforce archive_id uniqueness among rows that have one.

        archive_id is the durable logical identity of a committed Rev1
        archive (used later for idempotency/recovery). Legacy rows
        legitimately have archive_id = NULL -- a partial unique index
        (WHERE archive_id IS NOT NULL) is required, not a plain UNIQUE
        column constraint, so any number of legacy NULL rows remain valid
        while two non-null archive_id values can never collide. Safe to
        apply to a table that already has rows: SQLite raises only if an
        existing pair of rows already violates the constraint, which
        cannot happen here since no Rev1 writer existed before this
        column did. Same idempotent CREATE UNIQUE INDEX IF NOT EXISTS
        pattern as idx_render_jobs_active_output_path above.
        """
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_archives_archive_id_unique "
            "ON archives(archive_id) "
            "WHERE archive_id IS NOT NULL"
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
        """Legacy, pre-Rev1 unguarded archive insert -- retained for
        compatibility/history, not for current archive creation.

        This does not represent Archive Manager Rev1 verified commit
        semantics: it performs no eligibility checks, computes no content
        identity, verifies no filesystem package, and is not transactional
        with any episode-status update. A row inserted through this method
        always gets the schema defaults (archive_schema_version=0,
        archive_state='legacy') -- the same classification as genuinely
        historical pre-Rev1 rows -- because it never touches those columns.

        No current production code path calls this method (Phase 15
        Mission 15F retired `ArchiveManager.archive_episode()`, the last
        remaining caller, along with it, and no replacement caller was
        introduced). It remains here only as the writer that produces a
        synthetic legacy row for tests exercising legacy-record handling
        (e.g. `ArchiveManager.verify_archive()`'s legacy-classification
        path) and as a record of the pre-Rev1 archive-insert shape.

        Archive Manager Rev1 archive creation (`ArchiveManager.create_archive()`)
        uses `commit_verified_archive()` instead, the only writer permitted
        to produce (archive_schema_version=1, archive_state='complete')
        rows, and the only one that runs the actual guarded, verified
        commit transaction. Do not route Rev1 archive creation through this
        method.
        """
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

    def commit_verified_archive(
        self,
        *,
        episode_id: str,
        render_job_id: int,
        archive_id: str,
        archive_path: str,
        manifest_path: str,
        manifest_sha256: str,
        verified_at: str,
    ) -> ArchiveRecord:
        """Atomically commit a Rev1 archive: insert the committed `archives`
        row and guard the `rendered -> archived` episode transition in one
        SQLite transaction.

        Phase 15 Rev1 (Mission 15B) database-layer primitive only. This
        method does not touch the filesystem and does not compute or
        independently verify a hash -- it receives manifest_sha256 as an
        already-computed digest from the caller (a future Archive Manager
        Rev1, Mission 15E) and only validates that it is *structurally* a
        SHA-256 (see _normalize_manifest_sha256(): exactly 64 hex
        characters, case-insensitive on input, always stored lowercase).
        It never writes episodes.folder_path -- Rev1's approved
        architecture keeps folder_path pointed at the original active
        workspace; only archive_path on the new archives row carries the
        archive location.

        Required, checked before the transaction begins (SELECTs here exist
        only to produce a precise error message -- they are not the
        mutation authority; see below):
          - episode exists and episode.status == 'rendered'
          - render_jobs.id == render_job_id
          - render_jobs.episode_id == episode_id
          - render_jobs.status == 'complete'
          - no archive row already exists for episode_id
          - manifest_sha256 is exactly 64 hexadecimal characters
          - archive_id does not already belong to another archive row
            (idx_archives_archive_id_unique, a partial UNIQUE index over
            non-null archive_id -- enforced by SQLite at INSERT time, not
            pre-checked here, the same division of labor as the existing
            episode_id UNIQUE constraint)

        Mutation authority (the actual transactional guard, per the same
        TOCTOU-closing principle already used by
        transition_render_job_to_rendering()/release_assembly_claim()):
        the INSERT itself is an `INSERT ... SELECT ... WHERE` re-testing
        every one of the five conditions above against the database's
        state at the moment the statement executes, not the caller's
        earlier read -- if zero rows match, zero rows are inserted, and
        this method raises. The subsequent episode UPDATE is guarded by
        `WHERE episode_id = ? AND status = 'rendered'` and must affect
        exactly one row, or this method raises. Either raise happens inside
        the `with self.conn:` block, so Python's sqlite3 context-manager
        rollback discards the entire transaction: an insert can never
        survive a failed episode transition, and vice versa.
        """
        episode = self.get_episode_by_episode_id(episode_id)
        if episode is None:
            raise ArchiveCommitError(f"No episode with episode_id={episode_id}.")
        if episode.status != EpisodeStatus.RENDERED:
            raise ArchiveCommitError(
                f"Episode {episode_id} has status {episode.status.value!r}; only a 'rendered' "
                "episode can be archive-committed."
            )
        existing = self.get_archive_by_episode_id(episode_id)
        if existing is not None:
            raise ArchiveCommitError(f"Episode {episode_id} already has a committed archive.")

        render_job = self.get_render_job_by_id(render_job_id)
        if render_job is None:
            raise ArchiveCommitError(f"No render job with id={render_job_id}.")
        if render_job.episode_id != episode_id:
            raise ArchiveCommitError(
                f"Render job {render_job_id} belongs to episode {render_job.episode_id!r}, "
                f"not {episode_id!r}."
            )
        if render_job.status != RenderJobStatus.COMPLETE:
            raise ArchiveCommitError(
                f"Render job {render_job_id} has status {render_job.status.value!r}; only a "
                "'complete' render job may be archived."
            )

        for field_name, value in (
            ("archive_id", archive_id),
            ("archive_path", archive_path),
            ("manifest_path", manifest_path),
            ("verified_at", verified_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ArchiveCommitError(f"{field_name} must be a non-empty string.")
        manifest_sha256 = _normalize_manifest_sha256(manifest_sha256)

        with self.conn:
            try:
                cur = self.conn.execute(
                    "INSERT INTO archives "
                    "(episode_id, archive_path, archive_id, archive_schema_version, archive_state, "
                    "manifest_path, manifest_sha256, render_job_id, verified_at) "
                    "SELECT episodes.episode_id, ?, ?, 1, ?, ?, ?, render_jobs.id, ? "
                    "FROM episodes "
                    "JOIN render_jobs ON render_jobs.id = ? AND render_jobs.episode_id = episodes.episode_id "
                    "WHERE episodes.episode_id = ? "
                    "AND episodes.status = ? "
                    "AND render_jobs.status = ? "
                    "AND NOT EXISTS (SELECT 1 FROM archives WHERE archives.episode_id = episodes.episode_id)",
                    (
                        archive_path,
                        archive_id,
                        ArchiveState.COMPLETE.value,
                        manifest_path,
                        manifest_sha256,
                        verified_at,
                        render_job_id,
                        episode_id,
                        EpisodeStatus.RENDERED.value,
                        RenderJobStatus.COMPLETE.value,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "archives.archive_id" not in str(exc):
                    raise
                raise ArchiveCommitError(
                    f"archive_id {archive_id!r} is already used by another committed archive."
                ) from exc
            if cur.rowcount != 1:
                raise ArchiveCommitError(
                    f"Archive commit precondition no longer holds for episode {episode_id} / "
                    f"render job {render_job_id} (episode rendered, render job complete and "
                    "owned by episode, no existing archive) -- commit rolled back."
                )
            updated = self.conn.execute(
                "UPDATE episodes SET status = ?, updated_at = datetime('now') "
                "WHERE episode_id = ? AND status = ?",
                (EpisodeStatus.ARCHIVED.value, episode_id, EpisodeStatus.RENDERED.value),
            )
            if updated.rowcount != 1:
                raise ArchiveCommitError(
                    f"Episode {episode_id} did not transition rendered -> archived "
                    f"(rowcount={updated.rowcount}); archive commit rolled back."
                )
            row = self.conn.execute("SELECT * FROM archives WHERE id = ?", (cur.lastrowid,)).fetchone()
            if row is None:
                raise ArchiveCommitError(f"Could not reload committed archive {cur.lastrowid}.")
            return ArchiveRecord.from_row(row)
