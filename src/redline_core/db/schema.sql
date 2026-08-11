-- Redline OS SQLite schema.
-- This is the system of record for PIPELINE STATE (what episodes exist, what
-- stage they're in, what render jobs are queued). It is NOT the system of
-- record for media/timeline content — DaVinci Resolve project files are.
-- Keep that distinction in mind before adding columns here.

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_number INTEGER NOT NULL UNIQUE,
    episode_id TEXT NOT NULL UNIQUE,          -- e.g. "RLC-E025", computed from naming.yaml
    project_name TEXT NOT NULL,               -- e.g. "RLC-E025_MASTER"
    project_path TEXT,                        -- filled in once the Resolve project is duplicated
    folder_path TEXT,                         -- filled in once the working folder is created
    status TEXT NOT NULL DEFAULT 'created',   -- see EpisodeStatus enum in models.py
    assembly_claim_token TEXT,                -- NULL = no active/unresolved assembly attempt (ADR-0001)
    assembly_claimed_at TEXT,                 -- operator diagnostics only; not read by any logic
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS render_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
    preset_name TEXT NOT NULL,
    resolve_job_id TEXT,                      -- ID returned by Resolve's render queue, once queued
    project_name TEXT,
    timeline_name TEXT,
    status TEXT NOT NULL DEFAULT 'queued',    -- claiming | queued | rendering | complete | failed | cancelled
    output_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL UNIQUE REFERENCES episodes(episode_id),
    archive_path TEXT NOT NULL,
    archive_id TEXT,                          -- Rev1 stable archive identity; NULL for pre-Rev1 rows
    archive_schema_version INTEGER NOT NULL DEFAULT 0,  -- 0 = legacy (pre-Rev1); 1 = Rev1 committed archive
    archive_state TEXT NOT NULL DEFAULT 'legacy',       -- 'legacy' | 'complete' -- see db/models.py ArchiveState
    manifest_path TEXT,                       -- Rev1 Archive Manifest location; NULL for pre-Rev1 rows
    manifest_sha256 TEXT,                     -- Rev1 Archive Manifest seal; NULL for pre-Rev1 rows
    render_job_id INTEGER REFERENCES render_jobs(id),  -- render job this archive was built from; NULL for pre-Rev1 rows
    verified_at TEXT,                         -- when the Rev1 package was verified; NULL for pre-Rev1 rows
    archived_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_render_jobs_episode_id ON render_jobs(episode_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_render_jobs_active_output_path
ON render_jobs(output_path)
WHERE output_path IS NOT NULL AND status IN ('claiming', 'queued', 'rendering');
-- idx_archives_archive_id_unique is intentionally NOT declared here: archive_id
-- is itself only added by Database._migrate_add_archive_rev1_columns() for a
-- pre-Rev1 database, which runs *after* this script's executescript() call --
-- declaring the index here would break init_schema() against a legacy archives
-- table that doesn't have the column yet. Database._migrate_add_archive_id_unique_index()
-- creates it instead, safely, for both fresh and legacy databases alike.
