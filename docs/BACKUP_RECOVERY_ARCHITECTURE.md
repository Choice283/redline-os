# Backup & Recovery Architecture — Mission 1A (Backup + Verification), Mission 1B-A1 (HEALTHY_SOURCE Restore), and Mission 1B-A2-1 (Source Classification + Read-Only Recovery Planning)

**Status:** Mission 1A (System-of-Record Backup + Verification) implemented,
followed by an independent-review correction pass. Mission 1B-A1
(HEALTHY_SOURCE Restore) is also implemented, published, and closed --
`RestoreManager.restore_plan()`/`.restore()`, the `redline backup
restore-plan`/`redline backup restore` CLI commands, and a
`redline_core.restore` package all exist. Mission 1B-A1 is **HEALTHY_SOURCE
only**: it restores a target backup that itself independently re-verifies
immediately before restoring. Mission 1B-A2-1 (Source Classification +
Read-Only Recovery Planning) is now also implemented -- `redline backup
restore-recovery-plan <backup_id>`, `build_recovery_plan()`, and the new
`SourceCondition`/`RecoveryFeasibility` classification model all exist, and
are **strictly read-only**: no degraded-source capture, no disposition, no
staging, no replacement, and no recovery *execution* of any kind exists
anywhere in this repository. **DEGRADED_SOURCE and MISSING_SOURCE recovery
EXECUTION remains explicitly out of scope and not implemented** -- there is
no `backup restore-recovery` (destructive) command, no `backup
restore-degraded` command, no forensic/degraded-source-capture path, and no
MCP restore tool anywhere in this repository. Mission 1B-A2-2
(degraded-source capture) and Mission 1B-A2-3 (recovery execution) remain
separate, not-yet-authorized future work, as does Mission 1B-B. See §13
below for the full Mission 1B-A1 architecture and §14 below for the full
Mission 1B-A2-1 architecture; §1-§11 below describe Mission 1A (Backup +
Verification) exactly as originally implemented and are unchanged by either
Mission 1B-A1 or Mission 1B-A2-1.

No live production Restore has been performed or is authorized by this
document. Mission 1B-A1's own implementation record used only disposable,
`tmp_path`-scoped fixtures and synthetic production-shaped data -- see §13.9.

**Correction pass (post-independent-review, two rounds):** the first round
corrected four findings: (1) the concurrent-writer integration test was
rewritten to deterministically prove a committed write overlaps the real
`sqlite3.Connection.backup()` call, rather than inferring it from
`write_count > 0` at the end of the whole operation; (2) sealed-package
verification (`payload/config`, `payload/database`) became a recursive
inventory check instead of a non-recursive top-level scan; (3)
`list_backups()` began requiring a package directory's name to equal its
own manifest's `backup_id` before surfacing it; (4) backup commands moved
off `PersistenceServices` onto a new, narrower `BackupServices`/
`build_backup_services()` composition tier that never opens a `Database`
connection or calls `Database.init_schema()` against the live pipeline
database. A second independent review then found the round-1 fixes
substantively sound but incompletely proven, and a second round closed
those specific gaps: (A) added end-to-end tests through the real
`cli.main.main()` dispatch path (round 1's behavioral proofs stopped at
`build_backup_services()`/`backup_commands.run()`, never the actual CLI
entrypoint); (B) added a second concurrency test exercising the real,
unmodified production `snapshot_database()` wrapper directly (round 1's
deterministic test necessarily monkeypatches that wrapper to get a
synchronization hook, so it proves SQLite Online Backup API semantics, not
the shipped wrapper's own concurrent behavior — both proofs are now kept,
clearly distinguished, see §11); (C) replaced the `rglob()`-based payload
scan (which independent review showed traverses into a Windows junction's
target before rejecting the junction itself) with an explicit manual walk
that checks each entry before ever descending into it; (D) added a test
isolating the exact-inventory function's own unsafe-object rejection
branch; (E) added the requested copied-package (not merely renamed)
listing-identity test. See §3, §6, §8, and §11 below for the corrected
behavior in each area.

**Governance:** Agents advise. Paul decides. This capability exists because
V1 had no first-class backup/restore procedure for the SQLite database that
is Redline OS's sole system of record for pipeline status
(`docs/DEPLOYMENT.md` §6, "Not automated: Database backup"), a gap identified
in the V2 Architecture Discovery report and authorized for implementation as
Mission 1A only.

---

## 1. What this protects

Exactly two things, together as one backup unit:

- The live SQLite database at `REDLINE_DB_PATH` (`redline_core.db.schema.sql`'s
  three tables: `episodes`, `render_jobs`, `archives`).
- The active configuration directory at `REDLINE_CONFIG_DIR` — **exactly**
  the files named by `redline_core.config.loader.REQUIRED_FILES`
  (`naming.yaml`, `folder_structure.yaml`, `render_presets.yaml`,
  `paths.yaml`, `assets.yaml`, `timeline_template.yaml`). Arbitrary
  additional files present in the config directory are never automatically
  included — this is a deliberate, locked correction to Mission 1A's
  original discovery-phase proposal, not an oversight.

**Out of scope, unchanged by Mission 1A:** DaVinci Resolve project files,
media, rendered masters, and `ArchiveManager`'s own episode archive packages
(`paths.archive_path`). Episode archives and system-of-record backups remain
two separate responsibilities — this mission does not redesign or depend on
Archive Manager, though its package/manifest/atomic-publish shape is
deliberately mirrored (see §3).

## 2. Why a raw file copy is never used

Determined from source, not assumed: `redline_core.db.database.Database.
connect()` sets exactly one PRAGMA (`foreign_keys = ON`) and no
`journal_mode` — SQLite's own default is `DELETE` (rollback-journal), not
WAL — and several mutating methods (`commit_verified_archive()`,
`create_accepted_render_job()`, `finalize_render_output_claim()`,
`transition_render_job_to_rendering()`) wrap a short multi-statement sequence
in `with self.conn:`, meaning a real, if short, open-transaction window
exists. A raw filesystem copy taken during that window could capture a torn
main-file/journal pair.

`redline_core.backup.sqlite_snapshot.snapshot_database()` instead opens the
live database through an **independent, read-only** connection
(`file:...?mode=ro`) and calls Python stdlib `sqlite3.Connection.backup()`
(SQLite's Online Backup API), which reads through SQLite's own consistency
machinery and produces a destination file representing one consistent point
in time regardless of concurrent writer activity. Nothing in this subsystem
ever calls `BEGIN`/`COMMIT`/any write statement against the live database,
and nothing in it ever contacts DaVinci Resolve — both are proven, not just
asserted: `tests/unit/test_backup_manager.py::test_create_backup_never_
mutates_source_database_or_config` byte-for-byte compares source hashes
before/after, and `tests/integration/test_backup_concurrent_writer.py`
exercises a real, concurrently-committing writer connection while a backup
runs. `tests/unit/test_backup_manager.py::test_backup_subsystem_source_
never_imports_resolve` statically (via `ast`) proves no module under
`redline_core.backup` or `cli/backup_commands.py` imports anything
Resolve-related.

## 3. Package construction: stage → seal → verify → publish

Mirrors `redline_core.archive.package`'s proven shape deliberately, rather
than inventing a different pipeline for a structurally identical problem:

```
build_staged_backup()  (redline_core.backup.package)
  -> snapshot_database()            (Online Backup API, read-only source)
  -> PRAGMA integrity_check         (against the backup copy only)
  -> probe_schema()                 (ground-truth PRAGMA table_info() fingerprint)
  -> copy + verify each required config file (redline_core.fsutil safe-open/hash)
  -> compute content_set_digest
  -> build_backup_id()              (b1-<UTC timestamp>-<12 hex of content digest>)
  -> write backup_manifest.json + backup_manifest.sha256 (canonical JSON)
  -> verify_payload_against_manifest()  (re-enumerate/re-hash everything just written)
  -> write BACKUP_COMPLETE marker
       |
       v
publish_staged_backup()
  -> verify_payload_against_manifest() again, immediately pre-publish
  -> atomic os.rename() staging -> system_backups/<backup_id>/
     (fails closed via BackupDestinationCollisionError if the destination
      already exists -- the rename itself is the collision check; there is
      no separate check-then-act race window)
```

Filesystem-object safety (rejecting symlinks, Windows junctions, and reparse
points) delegates entirely to `redline_core.fsutil.is_unsafe_link()` — the
same domain-neutral primitive `redline_core.archive.integrity` uses — so
there is exactly one real implementation of that safety contract in the
repository, not a second, slightly different one invented for backups.

On any failure after staging begins, the incomplete staging directory is
left in place under `<backup_path>/.staging/` for forensic inspection —
never auto-deleted, matching Archive Rev1's publication-failure doctrine
(`ArchivePublicationError`'s own documented behavior). Proven by
`test_interrupted_staging_never_publishes_a_backup`.

## 4. Filesystem layout

```
<backup_path>/
  system_backups/
    <backup_id>/                          e.g. b1-20260816T193000Z-79c948abf73d/
      backup_manifest.json
      backup_manifest.sha256
      payload/
        database/
          redline.db                      (Online Backup API snapshot, not a raw copy)
        config/
          naming.yaml
          folder_structure.yaml
          render_presets.yaml
          paths.yaml
          assets.yaml
          timeline_template.yaml
      BACKUP_COMPLETE                      (empty marker, written last)
  .staging/
    <uuid4 hex>/                           (ephemeral; renamed away on success, left in place on failure)
```

## 5. Backup manifest contract

Canonical JSON (`sort_keys=True`, compact separators, ASCII-only), sealed
with a separate SHA-256 sidecar (`backup_manifest.sha256`) — exactly Archive
Rev1's manifest/sidecar precedent:

```json
{
  "schema_tag": "b1",
  "backup_id": "b1-20260816T193000Z-79c948abf73d",
  "created_at": "2026-08-16T19:30:00Z",
  "reason": "operator-supplied or null",
  "source": {
    "redline_db_path": "C:\\path\\to\\redline.db",
    "redline_config_dir": "C:\\path\\to\\config",
    "redline_os_version": "0.1.0",
    "repository_revision": null,
    "python_version": "3.11.9"
  },
  "database": {
    "relative_path": "payload/database/redline.db",
    "sha256": "<64 hex>",
    "size_bytes": 45056,
    "integrity_check": "ok",
    "schema_probe": {
      "episodes_columns": ["..."],
      "render_jobs_columns": ["..."],
      "archives_columns": ["..."]
    }
  },
  "config_files": [
    {"relative_path": "payload/config/naming.yaml", "sha256": "<64 hex>", "size_bytes": 123}
  ],
  "content_set_digest": "<64 hex>"
}
```

`repository_revision` is always `null`: determined from source, there is no
git-shelling repository-revision discovery mechanism anywhere in this
repository (the same finding `redline_core.archive.metadata_snapshot.
resolve_software_identity()` already documented for Archive Rev1's own
`software.json`). Not fabricated, not silently omitted.

`schema_probe` records the actual `PRAGMA table_info()` column shape of the
three pipeline tables at backup time, rather than inventing a version number
`redline_core.db.schema.sql` does not itself have (see §7).

## 6. Verification

`BackupManager.verify_backup(backup_id)` never trusts a prior success or the
manifest's own claims at face value: it re-derives the manifest sidecar
hash, re-hashes the database snapshot and every config file against the
manifest's recorded values, and re-runs `PRAGMA integrity_check` against the
backup copy. Every failure mode — corruption, tampering, a missing
completion marker, an incomplete package — raises
`BackupVerificationFailedError` (or a more specific subclass); a result is
only ever returned with `verified=True`, matching Archive Rev1's fail-closed
convention (`verify_archive()` never returns `verified=False` either).
Verification performs no writes and is safe to call any number of times
(`test_verify_backup_succeeds_and_is_idempotent`).

**Exact sealed-package inventory (correction pass, two rounds):**
independent review first found the original unexpected-file check under
`payload/config` used `Path.iterdir()` (immediate children only), so a
file planted inside a nested subdirectory escaped detection entirely, and
no equivalent check existed for `payload/database` at all. Round 1 fixed
this with a `Path.rglob("*")`-based recursive scan shared by both
directories. A second independent review then empirically demonstrated
that `rglob()` traverses *into* a Windows junction's target directory
before its own per-entry safety check ever runs against the junction entry
itself — Python's symlink-loop protection does not help, since
`Path.is_symlink()` reports `False` for junctions/reparse points.

`_require_exact_payload_contents()` (`redline_core/backup/package.py`) was
rewritten (round 2) as a deliberate **single-level, non-recursive** scan:
because Mission 1A's approved payload structure is always flat (exactly
one file under `payload/database`, exactly six under `payload/config`), no
legitimate nested directory can ever exist there at all — so the fix is
not "recurse more carefully," it is "never recurse." Every directory entry
found is rejected immediately, safe or not, junction or ordinary, without
the function ever calling anything that would enumerate that entry's
contents; `Path.iterdir()` (used only on the single top-level directory
itself, never on anything discovered inside it) has no recursive-descent
logic at all, unlike `rglob()`. The payload directory itself (not just its
contents) is checked the same way, via `require_safe_directory(...,
must_exist=False)`, before it is ever listed. Rejects an unmanifested
file, any nested directory, or any unsafe filesystem object
(symlink/junction/reparse point), fully closed and typed
(`BackupVerificationFailedError`/`BackupUnsafeFilesystemObjectError`).
Covered by nine tests in `tests/unit/test_backup_manager.py`: the original
six tampering scenarios, a no-false-positive check against a genuinely
untampered package, a test isolating the unsafe-object branch specifically
(not merely the earlier, separate per-manifested-file safety checks), and
a test proving a junction-standing-in entry's target directory is never
enumerated at all — tracked directly by recording every path
`Path.iterdir()` is ever called with.

`BackupManager.list_backups()` derives its listing entirely from sealed
packages on disk — **there is no "backups" table in `redline.db`**,
deliberately: tracking backups of the database inside the database being
protected is circular. A package missing its completion marker, whose
manifest sidecar hash doesn't match, or whose directory name no longer
equals its own manifest's `backup_id` (correction pass, see below) is
silently excluded from the listing, never reported as usable
(`test_list_backups_excludes_incomplete_package`,
`test_list_backups_excludes_package_with_tampered_manifest`,
`test_list_backups_excludes_package_with_renamed_directory`).

**`backup_id`/directory identity (correction pass):** independent review
found `list_backups()` could report `manifest["backup_id"]` paired with a
differently-named package directory — an inconsistency `verify_backup()`
(which reconstructs its lookup path purely from the requested `backup_id`)
could never actually resolve. `_try_read_record()` now requires
`manifest["backup_id"] == package_dir.name` before surfacing a record; this
is a structural identity check only, not a re-verification of package
content — `list_backups()` still does not re-hash the database or config
files, and `verify_backup()`'s own behavior is unchanged
(`test_verify_backup_unaffected_by_list_identity_check`).

## 7. Asset Registry / migration-framework finding (locked, not resolved by Mission 1A)

Source-level investigation for this mission found that the Asset Registry's
SQLite persistence layer — `src/redline_core/asset/sqlite_repository.py`,
`src/redline_core/asset/schema.sql` — is **real, complete, integration-tested
code** (`tests/integration/test_asset_sqlite_repository.py`, `test_asset_
database_initialization.py`), not merely an architecture draft as earlier
documentation implied. It is wired into nothing (`AssetManager`,
`composition.py`, no CLI command, no MCP tool import it) and has never been
pointed at a production database file — confirmed, the live `RedlineOSLive
\Runtime` directory contains exactly one database file, `redline.db`, and it
is not the asset registry schema.

That unwired code already tracks an explicit schema version
(`asset_registry_schema_metadata` table, hard-reject on mismatch) that
`redline_core/db/schema.sql` itself still does not have (§5's `schema_probe`
records column shape instead, precisely because no version number exists to
record). **Mission 1A does not implement a general SQLite migration
framework and does not resolve this two-philosophies-coexisting finding** —
per this mission's own locked direction, it is recorded here for whoever
later scopes Asset Registry activation, not solved now.

## 8. CLI surface

```
redline backup create [--reason TEXT]
redline backup list
redline backup verify <backup_id>
```

Routed through `BackupServices` (`redline_core.runtime.composition`) —
**not** `PersistenceServices`, the tier `archive` commands use. This is a
correction pass finding: independent review found that routing `backup`
through `build_persistence_services()` opened a live `Database` connection
and called `Database.init_schema()` against the pipeline database even for
read-only `backup list`/`backup verify`. `BackupServices`/
`build_backup_services()` is a fourth, narrower composition tier that loads
`RedlineConfig` and resolves the database *path* for `BackupManager` without
ever calling `Database.connect()`, `Database.init_schema()`, or constructing
a Resolve adapter — for `create`, `list`, and `verify` alike. Proven
behaviorally, not just statically, by
`test_build_backup_services_never_touches_database_class`,
`test_backup_create_list_verify_never_touch_database_class`, and
`test_build_backup_services_never_constructs_resolve_adapter`
(`tests/unit/test_cli_backup_commands.py`), which monkeypatch
`Database.connect`/`Database.init_schema`/`ResolveScriptAdapter.__init__` to
raise and then genuinely exercise the composition builder and full CLI
dispatch, proving none of the three is ever reached.

**Real `cli.main` dispatch proof (second correction pass):** the three
tests above stop at `build_backup_services()`/`backup_commands.run()` —
independent review found none of them, nor anything else in the
repository, actually invoked `cli.main.main()`'s real
`args.resource == "backup"` branch, so a regression reverting that one line
back to `build_persistence_services()` would have passed the entire suite
unchanged. `test_main_backup_list_end_to_end_never_touches_database_or_
resolve` and `test_main_backup_create_list_verify_end_to_end_never_touch_
database_or_resolve` (`tests/unit/test_cli_backup_commands.py`) close that
gap: real argparse parsing, real `REDLINE_CONFIG_DIR`/`REDLINE_DB_PATH`
environment resolution, real dispatch, with the same three monkeypatches
applied. Independently confirmed to catch the regression: temporarily
reverting `main.py`'s backup branch to `build_persistence_services()` made
both tests fail with the expected `Database.connect()` assertion, reverted
immediately after confirming (no net repository change).

As of Mission 1B-A1, `redline backup restore-plan <backup_id>` (read-only)
and `redline backup restore <backup_id>` (destructive) also exist --
registered onto this same `backup` subparsers object by
`cli.restore_commands.register_parser()`, but dispatched by `cli.main`
through `RestoreServices`/`build_restore_services()`, a narrower composition
tier than `BackupServices` (see §13.2). `redline backup restore-degraded
...` does **not** exist and is not planned by this mission; running it
produces argparse's own standard "invalid choice" error
(`test_no_restore_degraded_action_registered`), the same clean failure mode
as any other never-registered subcommand.

## 9. MCP and Control Room disposition

**No MCP tool exists for any backup operation.** `mcp_server/tools/` has no
`backup_tools.py`, and none of `create_backup()`/`list_backups()`/
`verify_backup()` is reachable via MCP. **Control Room has no backup
role in Mission 1A.** Both are deliberate scope boundaries, not oversights —
see the Mission 1A architecture discussion for the reasoning; neither is
revisited by this implementation.

## 10. Error taxonomy

```
BackupError (redline_core.backup.exceptions, base)
├── BackupConfigurationError            paths.backup_path not configured
├── BackupPathContainmentError          backup root overlaps db/config paths
├── BackupUnsafeFilesystemObjectError   symlink/junction/reparse point/wrong type
├── BackupSourceUnavailableError        live db or a required config file missing
├── BackupDatabaseSnapshotError         Online Backup API snapshot failed
├── BackupIntegrityCheckFailedError     PRAGMA integrity_check did not return "ok"
├── BackupCopyVerificationError         copied config file content mismatch
├── BackupDestinationCollisionError     backup_id already exists (never overwritten)
├── BackupPublicationError              atomic publish failed for another reason
├── BackupNotFoundError                 verify_backup() given an unknown backup_id
└── BackupVerificationFailedError       at-rest backup no longer matches its manifest
```

## 11. Testing

Unit (`tests/unit/test_backup_paths.py`, `test_backup_manager.py`,
`test_cli_backup_commands.py`, 72 tests as of the second correction pass,
up from 55 at Mission 1A's original implementation): path containment,
backup_id validation, unsafe-object rejection, create/list/verify happy
paths, every fail-closed precondition, collision-without-overwrite,
interrupted-staging never publishes, corruption detection (database,
config file, manifest/sidecar), missing-marker rejection, repeated
verification, zero-source-mutation proof, static zero-Resolve-import
proof, CLI serialization/exit-code behavior, exact single-level sealed-
package inventory (config and database payloads: nested unexpected file,
nested unexpected directory, unexpected top-level file, extra database
file, nested database file/directory, a no-false-positive check against an
untampered package, a test isolating the unsafe-object rejection branch
specifically, and a test proving a junction-standing-in entry's target is
never enumerated), `backup_id`/directory identity for listing (matching
package, renamed directory, and copied-to-a-different-name directory, each
distinctly), behavioral (not merely static) proof that backup composition
never touches `Database.connect()`, `Database.init_schema()`, or Resolve
construction — proven twice over: once for `build_backup_services()`/
`backup_commands.run()` directly, and once end-to-end through the real
`cli.main.main()` dispatch path (see §8).

Integration (`tests/integration/test_backup_concurrent_writer.py`, 2 tests
as of the second correction pass, up from 1): two real, independently-
committing SQLite writer threads (one per test) run concurrently with
`create_backup()` against the same live database file — never a mock, never
an assertion of documented SQLite behavior. In both, the produced backup
independently re-verifies clean, and the live source database is proven
still intact and still correctly writable afterward.

**Two distinct proofs — do not conflate them (second correction pass):**
independent review found the deterministic test necessarily monkeypatches
`redline_core.backup.package.snapshot_database` with a test-local function
to get a synchronization hook, and therefore does not directly exercise the
shipped, unmodified production wrapper under concurrency. Two tests now
cover the two distinct claims:

1. **`test_backup_created_while_writer_actively_commits_is_verified_
   consistent`** — deterministic proof that SQLite's Online Backup API
   (`sqlite3.Connection.backup()`) itself tolerates a real, concurrently
   committing writer. Independent review had reproduced a failure showing
   an earlier version's `write_count[0] > 0` assertion did not prove
   overlap with the actual API call — a writer commit could land entirely
   after `backup()` had already finished, during `create_backup()`'s later
   config-copy/verify/publish stages. The corrected test seeds one known,
   committed row before any concurrency activity (so no assertion depends
   on race timing), then monkeypatches `snapshot_database` with a
   test-local function that performs the identical real work — same
   read-only source connection, the genuine `sqlite3.Connection.backup()`
   call, never a mock — but with `pages=1` and a `progress` callback.
   Because `progress` is invoked synchronously from *within* the
   still-executing `backup()` call, blocking inside it until the writer
   thread's first commit succeeds deterministically proves that commit is
   bracketed between the real Online Backup API call's start and its
   return. **This proves SQLite Online Backup API concurrency semantics,
   not the production wrapper's behavior under concurrency** — see test 2.

2. **`test_backup_created_by_real_production_wrapper_while_writer_
   actively_commits`** — direct, unmocked exercise of the actual shipped
   `redline_core.backup.sqlite_snapshot.snapshot_database()` wrapper: zero
   monkeypatching of it anywhere in this test, with a real writer thread
   committing repeatedly and continuously throughout the whole
   `create_backup()` operation window. This test does **not** claim to
   deterministically prove a specific commit landed strictly between the
   production `backup()` call's entry and return — that narrower claim
   belongs to test 1 only, and is made there by instrumenting around the
   real API rather than the production wrapper (no test-only hooks were
   added to production code merely to make this proof prettier). What test
   2 proves: the real, unmodified wrapper, exercised exactly as production
   calls it, produces a valid, independently-verified snapshot under
   genuine sustained concurrent write activity, and the live source
   database remains intact and writable afterward.

See the test file's own module docstring for the full mechanism of each.
Both verified stable: 5/5 passes run together in isolation across five
fresh repetitions, plus green under the full Mission 1A test set, the full
`tests/unit` suite, and the full `tests/unit tests/integration` combined
suite.

**Known, pre-existing repository test-collection issue, not introduced by
Mission 1A:** `pyproject.toml`'s `testpaths = ["tests/unit"]` means
`tests/integration/` — including this mission's own concurrency test and the
pre-existing Asset Registry integration suite — is not collected by a bare
`pytest` invocation, and therefore not exercised by CI as currently
configured. Mission 1A does not change this policy (explicitly out of
scope); running `pytest tests/unit tests/integration` explicitly is required
to exercise the full regression, exactly as the Asset Registry's own
integration tests already required before this mission. See the Mission 1A
final report for the recommendation on this, left for separate Founder
decision.

## 12. What Mission 1B (restore) needed to design (historical) — now Mission 1B-A1

This section originally recorded, before any restore implementation
existed, exactly the design points restore would need: re-verify the target
backup immediately before restoring, never "restore the latest"; a
mandatory pre-restore safety snapshot using this same `BackupManager`;
same-volume staged `os.replace()`; post-restore integrity + application-
level smoke verification; and fail-closed behavior on schema
incompatibility. Mission 1B-A1 (§13 below) implements every one of these
for the HEALTHY_SOURCE case. Kept here as the historical record of what was
anticipated versus what was actually built; not re-derived or restated.

## 13. Mission 1B-A1: HEALTHY_SOURCE Restore

**Governance:** Agents advise. Paul decides. Authorized for Mission 1B-A1
implementation only, after Mission 1B architecture discovery and three
correction rounds plus a Final Architecture Lock. Mission 1B-A2
(DEGRADED_SOURCE/MISSING_SOURCE recovery) and Mission 1B-B remain separate,
not-yet-authorized future work -- nothing in this section implements or
schedules either.

### 13.1 Scope boundary: HEALTHY_SOURCE only

"HEALTHY_SOURCE" means: the target backup, given an explicit `backup_id`
(never "latest"), independently re-verifies via a fresh
`BackupManager.verify_backup()` call immediately before restoring. If that
fresh verification fails for any reason -- missing, corrupted, tampered,
incomplete -- restore raises `RestoreTargetUnavailableError` and stops
before any live mutation. Mission 1B-A1 does not attempt to recover from,
repair, or partially restore a degraded or missing source; there is no
`backup restore-degraded` command, no forensic-capture path, and no
"restore what's salvageable" behavior anywhere in this package.

### 13.2 Package layout and composition

```
src/redline_core/restore/
  exceptions.py          typed error taxonomy (§13.8)
  models.py               QuiescenceAttestations, RestorePlanResult, RestoreResult
  journal.py               RestoreState, RestoreJournal, discover_journal_chain()
  sidecar.py                SQLite sidecar gate (-journal/-wal/-shm)
  quiescence.py            BEGIN IMMEDIATE probe + itemized attestations
  schema_fingerprint.py    disposable-DB reference build + structural comparison
  staging.py                same-volume staging + live replacement primitives
  manager.py                RestoreManager: restore_plan() / restore()
src/cli/restore_commands.py
```

`RestoreManager` wraps a `BackupManager` instance (for target verification
and the mandatory pre-restore safety backup) and otherwise operates
directly on `REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` as plain filesystem
paths -- never a live `Database` connection, never a Resolve adapter.
`RestoreServices`/`build_restore_services()`
(`redline_core.runtime.composition`) is a fifth, narrower composition tier
alongside `ApplicationServices`/`CoreServices`/`PersistenceServices`/
`BackupServices`: it loads config and resolves the database path exactly
like `BackupServices` does, and additionally constructs the
`RestoreManager` on top of the same `BackupManager` instance. It never
calls `Database.connect()`, never calls `Database.init_schema()` against
the live/pipeline database, and never constructs or connects a Resolve
adapter -- proven behaviorally (`test_build_restore_services_never_touches_
database_class`, `test_build_restore_services_never_constructs_resolve_
adapter`, and end-to-end through real `cli.main.main()` dispatch).

### 13.3 CLI surface

```
redline backup restore-plan <backup_id>
redline backup restore <backup_id> --confirm-backup-id <backup_id> \
    --attest-mcp-stopped --attest-control-room-stopped --attest-no-other-cli-operation \
    [--reason TEXT]
```

Both are registered onto the *same* `backup` subparsers object
(`cli.restore_commands.register_parser()`, called from `cli.backup_commands
.register_parser()`), but `cli.main` dispatches `restore-plan`/`restore`
through `RestoreServices` while every other `backup` action still uses
`BackupServices` -- one resource, two composition tiers, chosen by action
name in `cli.main.main()`.

`backup_id` is always a required, explicit positional argument on both
commands. There is no `--latest` shortcut anywhere -- "restore the latest
backup" is not an operation this mission implements; the operator must name
an exact `backup_id` from `redline backup list`.

`backup restore` requires:
- `--confirm-backup-id`, which must exactly equal the positional
  `backup_id` (`RestoreConfirmationError` otherwise) -- a repeated-value
  confirmation, not a single blanket `--yes`.
- Three separate, itemized attestation flags (`--attest-mcp-stopped`,
  `--attest-control-room-stopped`, `--attest-no-other-cli-operation`), all
  of which default to `False` and must all be explicitly passed
  (`RestoreAttestationMissingError` naming whichever is missing otherwise).
  These are operator-supplied attestations, trusted but not independently
  verified -- Mission 1B-A1 implements no new process-supervision
  framework to check them itself.

`backup restore-plan` performs every read-only check `restore()` would run
immediately before acting (fresh target verification, schema
compatibility, a real-but-rolled-back quiescence probe, sidecar presence)
and reports which would block a restore, without creating a pre-restore
safety backup, staging anything, or writing any journal entry.

### 13.4 Full application-schema compatibility

`redline_core.restore.schema_fingerprint` builds a *reference* fingerprint
from a disposable, temporary database created by the real, current
`Database.init_schema()` (`redline_core.db.database`) -- the one and only
place in this package permitted to call it. The reference database is
created in a `tempfile.TemporaryDirectory()` and always removed before the
function returns, success or failure; it is never the live database and
never a restored/target database.

The *target* fingerprint is built by direct, read-only (`mode=ro`)
`PRAGMA`/`sqlite_master` inspection alone -- never through `Database`.
Comparison is exact and structural:

- table inventory (exact set of table names, excluding `sqlite_`-internal
  tables)
- column shape (`PRAGMA table_info`: cid, name, type, notnull, dflt_value,
  pk -- every field, in column order)
- index inventory (exact set of index names per table)
- index structure (`PRAGMA index_xinfo`: seqno, cid, name, desc, coll, key
  for every indexed column, plus uniqueness/origin/partial from `PRAGMA
  index_list`)
- for **explicit** indexes (`origin == 'c'`, created by a real `CREATE
  INDEX` statement -- which is also where a partial index's `WHERE`
  predicate lives, since SQLite exposes no PRAGMA for it): an additional
  whitespace-normalized `sqlite_master.sql` text comparison. This is what
  actually proves partial-index predicate identity -- there is no other
  way to observe a partial index's predicate.
- for **autoindexes** (`origin in ('u', 'pk')` -- SQLite-generated, with no
  `sqlite_master.sql` text of their own, e.g. `sqlite_autoindex_episodes_1`
  from `episode_number INTEGER NOT NULL UNIQUE`): structural (`PRAGMA
  index_xinfo` + uniqueness) comparison only, since there is nothing else
  to compare.
- any view or trigger present in either fingerprint fails closed
  (`RestoreUnsupportedSchemaObjectError`) before any table-level comparison
  is attempted -- Mission 1B-A1 does not implement view/trigger
  compatibility checking at all, and does not silently ignore or partially
  validate one if present.

`require_schema_compatible(target_db_path)` builds the reference fresh and
compares; `RestoreManager` calls it once against the target backup's
payload database (pre-mutation) and once again against the live database
post-replacement (§13.7, STEP 3) -- always read-only against the target,
always via a fresh disposable database for the reference, never via
`Database.init_schema()` against anything live or restored.

### 13.5 Mandatory pre-restore safety backup

`restore()`'s first mutating action -- after fresh target re-verification
and schema compatibility both pass -- is a normal, unmodified
`BackupManager.create_backup()` call against the *current* live database
and config, reason-tagged with the restore attempt's own `restore_id`. If
this fails for any reason, `RestorePreRestoreSnapshotFailedError` is raised
and restore stops before any further mutation -- Mission 1B-A1 does not
implement degraded/missing-source recovery, so a failed safety snapshot is
always a hard stop, never a proceed-anyway option.

### 13.6 Quiescence, sidecar gate, staging, and replacement

**Quiescence** (`redline_core.restore.quiescence`): `probe_quiescence()`
opens an independent connection to the live database and attempts `BEGIN
IMMEDIATE` with a zero timeout, then rolls back and closes before
returning. Success proves no other connection holds a reserved/write lock
at that instant; it is not a lock Restore itself holds afterward. If the
live database does not currently exist (the exact "database missing"
scenario Restore exists to recover from), the probe is a no-op --
`sqlite3.connect()` would otherwise silently create an empty file as a side
effect of merely probing, which would make `backup restore-plan` a
non-read-only operation. This proved probe is distinct from the three
operator-supplied attestations (§13.3); Mission 1B-A1 implements no new
process-supervision framework to check the attestations independently.

**SQLite sidecar gate** (`redline_core.restore.sidecar`): before database
replacement, and again after replacement but strictly before any SQLite
connection is opened to the replaced file, Restore checks for
`<REDLINE_DB_PATH>-journal`, `-wal`, and `-shm`. Any present sidecar fails
closed (`RestoreSidecarPresentError`); none is ever deleted, renamed, or
recovered automatically by this code.

**Staging** (`redline_core.restore.staging`): the target backup package
remains read-only throughout. Its database and config payload are copied
into fresh staging directories nested *inside* `REDLINE_DB_PATH`'s parent
directory and `REDLINE_CONFIG_DIR`'s parent directory respectively --
same-volume by construction, re-proven explicitly via `same_volume()`
(`os.stat().st_dev` comparison) rather than merely assumed. `paths.
backup_path` is never assumed to share a volume with either live path.
Each staged file's freshly-recomputed hash/size is independently verified
against the target backup's own manifest before any live replacement is
attempted.

**Database replacement**: a single `os.replace(staged_db_path,
live_db_path)` -- one atomic swap.

**Config replacement**: two-step, non-atomic directory-level rename: live
config directory -> `<REDLINE_CONFIG_DIR>__superseded-<restore_id>` (a
restore-ID-scoped destination, never one fixed `__superseded` name --
collision fails closed), then staged config directory -> canonical live
config path. **The two steps are never claimed to be atomic together.** If
the second rename fails, the live config directory is genuinely missing --
config exists only at the superseded path and the still-present staging
path. Mission 1B-A1 implements no automatic recovery from that window; the
error message itself names both surviving locations.

### 13.7 Restore transaction journal

`redline_core.restore.journal`: an immutable, restore-ID-scoped,
monotonically-numbered sequence of transition records under
`<backup_root>/restore_journal/<restore_id>/`. Each transition is written
once, as canonical JSON (`sort_keys=True`, compact separators, ASCII-only)
with a separate SHA-256 sidecar -- exactly Mission 1A's manifest/sidecar
precedent -- via a unique temp filename, flushed and `fsync`'d, then
published with a collision-refusing `os.rename()`. No transition pathname
is ever overwritten, edited, deleted, or reused; `restore()` always starts
a brand-new `restore_id` and journal -- it never inspects, resumes, or
repairs a prior attempt's journal.

Intent/completion states recorded around every live mutation (full list in
`RestoreState`): `RESTORE_INITIATED`, `TARGET_VERIFIED`/
`TARGET_VERIFICATION_FAILED`, `SCHEMA_COMPATIBLE`/`SCHEMA_INCOMPATIBLE`,
`PRE_RESTORE_SNAPSHOT_COMPLETE`/`PRE_RESTORE_SNAPSHOT_FAILED`,
`QUIESCENCE_CONFIRMED`/`QUIESCENCE_FAILED`,
`SIDECAR_CHECK_PASSED_PRE`/`SIDECAR_PRESENT_PRE`,
`STAGING_INTENT`/`STAGING_COMPLETE`/`STAGING_FAILED`,
`DB_REPLACE_INTENT`/`DB_REPLACED`/`DB_REPLACE_FAILED`,
`CONFIG_RENAME_ASIDE_INTENT`/`CONFIG_RENAMED_ASIDE`,
`CONFIG_INSTALL_INTENT`/`CONFIG_REPLACED`/`CONFIG_REPLACE_FAILED`,
`SIDECAR_CHECK_PASSED_POST`/`SIDECAR_PRESENT_POST`,
`VERIFICATION_INTENT`/`VERIFIED_SUCCESS`/`VERIFICATION_FAILED`.

`discover_journal_chain()` is a completely separate, **read-only**
function: it performs zero writes, does not resume or repair anything, and
stops at (and excludes) the first missing, corrupt, or hash-mismatched
sequence number -- a higher-numbered file existing beyond that point is
never treated as proof of a more-advanced state; only the gap-free prefix
starting at sequence 1 is trusted. It exists purely as a durable,
inspectable record for a human to read after an interruption, not as
input to any automatic continuation.

### 13.8 Post-restore verification (STEP 0 - STEP 7, in order)

Run as the final phase of `restore()`, after both live mutations
(database, then config) have completed:

0. SQLite sidecar absence next to the now-live database -- before *any*
   SQLite connection is opened to it.
1. Exact byte identity and size: the live database, and all six live
   config files, against the target backup's own manifest-recorded
   hashes/sizes (not merely "looks valid" -- a structurally valid,
   schema-compatible database or a well-formed-but-different YAML file
   that is not byte-identical to the target payload is rejected here).
2. `PRAGMA integrity_check == ok` against the live database.
3. Exact schema compatibility, re-checked against the now-live restored
   database (§13.4 again, never via `Database.init_schema()`).
4. Config loader parse (`redline_core.config.loader.load_config()`) plus
   per-file path-safety validation (`redline_core.backup.paths.
   require_safe_regular_file()`, reused directly -- not reimplemented).
5. Approved non-mutating application-level reads: a plain, read-only
   `sqlite3` connection running `SELECT COUNT(*)` against `episodes`,
   `render_jobs`, and `archives` -- never `Database.init_schema()` against
   the restored database.
6. Source target backup verify/preservation: `BackupManager.verify_backup
   (backup_id)` once more, proving the target backup itself is unaffected
   by having been restored.
7. `VERIFIED_SUCCESS` -- recorded only after every one of steps 0-6 has
   passed.

Any failure at any step raises `RestoreVerificationFailedError` (or a more
specific subclass for steps that reuse another typed exception's message)
and journals `VERIFICATION_FAILED`. **No rollback, no retry, and no success
marker is ever produced on a verification-failure path** -- the database
and config replacements that already happened are not undone.

### 13.9 Crash handling and production safety

After any live mutation and an unexpected interruption: the process stops.
Preserved, always: the journal, the target backup (read-only throughout),
the pre-restore safety backup, any staging remnants, and the superseded
config directory. Mission 1B-A1 implements **no** resume, continuation,
journal repair, automatic rollback, or automatic cleanup/recovery from any
of these states -- an operator must inspect the journal and the preserved
artifacts and decide the next step by hand.

No live production Restore has been performed by this mission. Every test
and every implementation-proof exercise used only `tmp_path`-scoped
fixtures and synthetic, production-shaped data (multiple episodes, render
jobs, and an archive row) -- `C:\Users\pj198\RedlineOSLive\Runtime\redline.
db` and `...\production-config` are never referenced by any code or test
in this package, and the trusted production backup
(`b1-20260817T030606Z-8abd0a149de5`) is never opened for write. Production
Restore remains explicitly Founder-authorized, separate future work, exactly
as Mission 1A's own original restore-not-implemented boundary was.

### 13.10 Error taxonomy (Mission 1B-A1)

```
RestoreError (redline_core.restore.exceptions, base)
├── RestoreConfirmationError              --confirm-backup-id does not match backup_id
├── RestoreAttestationMissingError        a required itemized attestation was not given
├── RestoreTargetUnavailableError         target backup missing or failed fresh re-verification
├── RestoreSchemaIncompatibleError        structural schema mismatch
├── RestoreUnsupportedSchemaObjectError   a view or trigger is present (unsupported)
├── RestorePreRestoreSnapshotFailedError  mandatory safety backup failed; aborted before mutation
├── RestoreQuiescenceFailedError          BEGIN IMMEDIATE probe could not acquire the lock
├── RestoreSidecarPresentError            -journal/-wal/-shm present at a gate checkpoint
├── RestoreStagingFailedError             staged copy failed or didn't match the manifest
├── RestorePathCollisionError             a restore-ID-scoped staging/superseded/journal path collided
├── RestoreJournalError                   a journal transition could not be durably recorded
├── RestoreDatabaseReplacementFailedError the single os.replace() failed
├── RestoreConfigReplacementFailedError   either step of the two-step config rename failed
└── RestoreVerificationFailedError        any post-restore verification step (0-6) failed
```

Every one of these is raised in place of a raw OS/SQLite exception at the
public `RestoreManager`/CLI boundary, matching Mission 1A's own convention.

### 13.11 Explicitly deferred

Not implemented by Mission 1B-A1, and not scheduled by this document:
DEGRADED_SOURCE recovery, MISSING_SOURCE recovery, forensic capture,
`backup restore-degraded`, Mission 1B-A2, Mission 1B-B, a live production
Restore drill, MCP Restore, any Control Room mutation, any Resolve
interaction, automatic rollback, automatic self-healing, scheduled Restore,
cloud Restore, remote orchestration, Asset Registry activation, a general
SQLite migration framework, a new process-supervision framework, and any
new third-party dependency introduced solely for Restore.

## 14. Mission 1B-A2-1: Source Classification + Read-Only Recovery Planning

**Governance:** Agents advise. Paul decides. Authorized for Mission
1B-A2-1 implementation only, after the Mission 1B-A2 architecture and two
correction passes were accepted. Mission 1B-A2-2 (degraded-source capture)
and Mission 1B-A2-3 (recovery execution: disposition, staging,
replacement) remain separate, not-yet-authorized future work -- nothing in
this section implements or schedules either. Mission 1A and Mission 1B-A1
are treated as locked published foundations; nothing in this section
modifies their behavior.

### 14.1 Scope boundary: classification and planning only

Mission 1B-A2-1 answers, strictly read-only, for one explicitly selected
`backup_id`: what condition is the live database in, what condition is the
live required configuration in (each independently `HEALTHY`/`DEGRADED`/
`MISSING`), whether a future Mission 1B-A2 recovery path would be
architecturally eligible to proceed for each side (`NOT_APPLICABLE`/
`RECOVERABLE`/`RECOVERY_BLOCKED`), why not if blocked, whether a future
degraded-source capture or disposition would be required, and whether the
explicitly selected Mission 1A backup remains valid and schema-compatible.
It creates no backup, no degraded-source capture, no restore/recovery
journal, no staging directory, no SQLite write connection, and performs no
rename/replace/delete/move-aside of anything. There is still no
degraded/missing-source recovery *execution* capability anywhere in this
repository after this mission.

### 14.2 Package layout and composition

```
src/redline_core/restore/
  recovery_models.py          SourceCondition, RecoveryFeasibility, SourceSideAssessment, RecoveryPlanResult
  recovery_classification.py  classify_database_source(), classify_config_source() -- read-only probes
  recovery_planning.py        build_recovery_plan() -- orchestrates target-side + source-side into one result
src/cli/
  recovery_planning_commands.py   `redline backup restore-recovery-plan <backup_id>`
```

Dispatched through the same `RestoreServices`/`build_restore_services()`
composition tier `restore-plan`/`restore` already use (never opens a live
`Database` connection, never constructs or connects a Resolve adapter) --
registered onto the *existing* `backup` subparsers by
`cli.backup_commands.register_parser()`, exactly like `restore_commands`
already is.

### 14.3 Source-condition model

Per side (database, config), independently, exactly the source-side
prerequisites of Mission 1A's own, unmodified `create_backup()` contract --
not broadened:

- **HEALTHY** -- database: exists, is a safe regular file
  (`redline_core.fsutil.is_unsafe_link()`), opens as SQLite, and passes
  `PRAGMA integrity_check` (mirrors `build_staged_backup()`'s own
  `require_integrity_ok()` call, which already fails closed on this
  condition today -- not new scope, a direct re-derivation against the live
  source). config: each of the six `REQUIRED_FILES` exists, is a safe
  regular file, and streams successfully via
  `redline_core.fsutil.hash_stable_file()` (the exact primitive Mission
  1A's own config-copy path already uses). **Config file content validity
  (parseable YAML, a valid `RedlineConfig` schema) is deliberately never
  checked** -- `create_backup()` itself never requires it either, only
  `require_safe_regular_file()`.
- **DEGRADED** -- something exists at (or materially associated with) the
  expected path, but fails a HEALTHY prerequisite: wrong object type, an
  unsafe filesystem object, unopenable/integrity-failing SQLite, an
  unreadable/unstable config file, or a required config file individually
  missing from an otherwise-real config directory.
- **MISSING** -- the expected exact path does not exist
  (`os.lstat()` raises `FileNotFoundError`). Not an ordinal severity level
  relative to DEGRADED -- DB and config classify completely independently,
  and no code anywhere compares these values for ordering.

**Source condition is never inferred from backup infrastructure failure.**
Classification never calls `BackupManager.create_backup()` and guesses from
its exception; it performs direct, independent, read-only probes against
the live source (`os.lstat()`, `fsutil.is_unsafe_link()`, a `mode=ro`
SQLite connection for `PRAGMA integrity_check`, `hash_stable_file()`).
`recovery_planning.build_recovery_plan()`'s target-backup-side checks
(`target_verified`/`schema_compatible`) are computed completely
independently of `database`/`config` classification, so a backup-root
misconfiguration or destination failure can never appear as a source-health
finding -- proven by
`test_backup_infrastructure_failure_does_not_alter_source_classification`
and `test_classification_never_calls_create_backup`
(`tests/unit/test_recovery_planning.py`).

### 14.4 Recovery-feasibility model

A second, orthogonal per-side field: `NOT_APPLICABLE` (HEALTHY; the
ordinary Mission 1A/1B-A1 path applies), `RECOVERABLE` (DEGRADED or
MISSING, and a safe path into existing or future disposition-augmented
replacement machinery is believed to exist), or `RECOVERY_BLOCKED`
(DEGRADED, and no repository-proven safe path exists). **DEGRADED never by
itself implies RECOVERABLE** -- `DEGRADED_SOURCE` + `RECOVERY_BLOCKED` is a
valid, expected, explicitly-reported combination.

`RECOVERY_BLOCKED` cases identified read-only:

- **Unsafe filesystem object** (symlink, Windows junction, other reparse
  point) at the database path, the config directory path, or any of the six
  required config files -- detected via `fsutil.is_unsafe_link()`, **never
  followed, never opened, never mutated**. No repository-proven safe
  non-following disposition exists for this case (see the accepted Mission
  1B-A2 architecture record: this repository's only existing uses of
  `is_unsafe_link()` are unconditional rejection, never manipulation).
- **Structurally missing installation parent** -- the database's or
  config's own parent directory is also absent. Reconstructing missing
  installation structure is disaster-bootstrap/provisioning work, out of
  Mission 1B-A2's scope; this requires Founder-level intervention, never an
  operator attestation.
- **Cannot inspect the path at all** (e.g. permission denied on `lstat()`)
  -- the object's type cannot be safely determined, so it is conservatively
  blocked rather than guessed at.

`RECOVERABLE` (predicted, not executed) cases: DB missing with parent
intact; DB a regular file but degraded (corrupt/unopenable/
integrity-failing); DB path is an ordinary directory (would require a
future move-aside disposition before replacement); config directory
missing with parent intact (a future rename-aside sub-step would be
skipped, since nothing exists to move); config directory exists with
degraded required content (existing whole-directory rename-aside already
handles this, predicted to need no new disposition); config path is an
ordinary regular file (would require a future rename-aside disposition,
though the existing mechanics are already type-agnostic).

### 14.5 Whole-package recovery principle, preserved

Mission 1A backups remain all-or-nothing -- there is no "DB-only" or
"config-only" Mission 1A backup, and Mission 1B-A2-1 introduces no such
concept. If either live side is DEGRADED or MISSING, a future Mission
1B-A2 recovery path would require one whole degraded-source capture package
covering the observed system state (evidence, never a backup, never a
Restore source). Mission 1B-A2-1 only reports this requirement
(`capture_required` per side); it creates no capture of any kind.

### 14.6 Windows disposition proof -- future execution gate

The Windows filesystem rename behavior a future Mission 1B-A2-3 execution
would rely on for wrong-type disposition (moving an ordinary directory
aside at the database path, or an ordinary regular file aside at the config
path) is **not yet repository-proven** -- no existing test in this
repository exercises renaming a live directory or file aside at a location
another component expects to occupy. Every `disposition_description` this
mission's classification produces says so explicitly. Before any future
execution may treat that disposition as safe, isolated filesystem
behavioral tests must prove the required non-following rename semantics on
Windows. Until then, `RecoveryPlanResult`'s prediction is an architectural
prediction only, not an execution guarantee. This is not permission to test
against production paths, and no such test exists in this mission.

### 14.7 Result model

`RecoveryPlanResult` (`redline_core.restore.recovery_models`): `backup_id`,
`target_verified`, `schema_compatible`, `database`/`config`
(`SourceSideAssessment`: `condition`, `feasibility`, `blocking_reason`,
`capture_required`, `disposition_required`, `disposition_description`,
`details`), `sidecars_present`, `quiescence_implication`, `blocking_issues`,
and the `would_proceed` property. `would_proceed` means **"architecturally
eligible for a future, not-yet-implemented Mission 1B-A2 recovery
execution"** -- never "recovery was executed" and never "recovery execution
currently exists." It is `False` only when the selected backup is invalid,
target verification/schema checks fail, or either side is
`RECOVERY_BLOCKED`; `DEGRADED` + `RECOVERABLE` alone does not make it
`False`, since that combination is exactly what "architecturally eligible
for a future path" means.

`quiescence_implication` deliberately never calls
`redline_core.restore.quiescence.probe_quiescence()` against a database
already classified `DEGRADED`: `quiescence.py`'s own
`except sqlite3.OperationalError` clause around `BEGIN IMMEDIATE` does not
catch `sqlite3.DatabaseError` -- the exception SQLite actually raises
against a corrupt or non-SQLite file on first real access, since
`sqlite3.connect()` itself is lazy and does not validate file format at
open time. Calling it against a known-degraded database risks an uncaught
exception propagating out of a command that is supposed to be purely
observational, proven by
`test_recovery_plan_degraded_db_does_not_probe_quiescence`
(`tests/unit/test_recovery_planning.py`). **Recorded here as an
out-of-scope observation for a possible future Mission 1B-A1 hardening
pass -- Mission 1B-A1 is locked and is not modified by this mission.** For
`HEALTHY`/`MISSING` databases, `probe_quiescence()` is called exactly as
safely as Mission 1B-A1's own `restore_plan()` already calls it.

### 14.8 CLI surface

```
redline backup restore-recovery-plan <backup_id>
```

Registered onto the existing `backup` resource's subparsers (mirroring
`restore-plan`/`restore`'s own registration), dispatched through
`RestoreServices`. Read-only only -- no `restore-recovery` (destructive)
action, and no `restore-degraded` action, exists anywhere in this
repository (`test_no_destructive_restore_recovery_action_registered`,
`tests/unit/test_cli_recovery_planning_commands.py`). Existing
`restore-plan`/`restore` registration and semantics are completely
unaffected (`test_existing_restore_plan_and_restore_actions_still_
registered`).

### 14.9 Explicitly deferred

Not implemented by Mission 1B-A2-1, and not scheduled by this document:
degraded-source capture of any kind, any disposition operation (sidecar
move-aside, wrong-type object move-aside), staging, DB/config replacement,
a restore/recovery transaction journal, `backup restore-recovery`
(destructive), Mission 1B-A2-2, Mission 1B-A2-3, Mission 1B-B, a live
production Restore or recovery drill, MCP recovery tooling, any Control
Room mutation, any Resolve interaction, and any new third-party dependency
introduced solely for recovery planning.

### 14.10 Test evidence

- **Recovery classification** (`tests/unit/test_recovery_classification.py`):
  21 passed -- healthy/degraded/missing database and config independently,
  wrong-type cases, unsafe-link cases (via the established
  `fsutil.is_unsafe_link` monkeypatch convention from
  `tests/unit/test_backup_paths.py`, not real symlink creation), read-only
  guarantees (no sidecars created, bytes/inventory unchanged).
- **Recovery planning** (`tests/unit/test_recovery_planning.py`): 15
  passed -- healthy/degraded/missing target and source combinations,
  infrastructure-failure separation, the `create_backup()`-never-called and
  `probe_quiescence()`-never-called-when-DEGRADED proofs, and a full
  never-mutates-anything proof.
- **CLI** (`tests/unit/test_cli_recovery_planning_commands.py`): 11
  passed -- registration, help text, success/blocked/invalid/missing
  result shapes, exit codes, and a full CLI-dispatch-path
  never-mutates-anything proof.
- **Mission 1B-A1 / Mission 1A / CLI-composition regression**: the
  existing focused Restore suite (97), Restore integration (3), and
  Mission 1A/CLI-composition suite (84) all re-run identically -- 184
  passed, zero change.
- **Broader `tests/unit`/`tests/integration` suite**: 3122 passed / 32
  failed / 18 skipped (baseline 3075/32/18 plus this mission's 47 new
  passing tests) -- the 32 failures are exactly the same pre-existing
  families already documented in the Mission 1A and Mission 1B-A1 closure
  records (CLI end-to-end Windows-path/YAML fixture bug, fresh-venv
  installed-smoke variance, one native-process-helper timing test, and the
  historical RLC-E9901 harness pin consequence -- see below). Zero new
  failure families.

### 14.11 Historical RLC-E9901 harness consequence

Mission 1B-A2-1 legitimately changes `src/cli/main.py` (registers the new
`restore-recovery-plan` action and dispatch branch) -- one of the eight
SHA-256-pinned "mutation-bearing" source files
`scripts/rlc_e9901_queue_attempt_harness.py` hard-pins. This file's pin was
already stale against published master after Mission 1A's and Mission
1B-A1's own legitimate changes to it; Mission 1B-A2-1's additional,
legitimate change to the same file is the same already-documented,
intentional, fail-closed consequence, not a new one. `src/redline_core/
runtime/composition.py` was **not** touched by this mission and continues
to show only the pre-existing Mission 1A/1B-A1 mismatch. This closure does
not update the historical pins.
