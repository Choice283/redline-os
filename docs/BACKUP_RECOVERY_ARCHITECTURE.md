# Backup & Recovery Architecture — Mission 1A (Backup + Verification), Mission 1B-A1 (HEALTHY_SOURCE Restore), Mission 1B-A2-1 (Source Classification + Read-Only Recovery Planning), Mission 1B-A2-2 (Degraded-Source Capture), and Mission 1B-A2-3 (Recovery Execution + Journal/Evidence Integration)

**Status:** Mission 1A (System-of-Record Backup + Verification) implemented,
followed by an independent-review correction pass. Mission 1B-A1
(HEALTHY_SOURCE Restore) is also implemented, published, and closed --
`RestoreManager.restore_plan()`/`.restore()`, the `redline backup
restore-plan`/`redline backup restore` CLI commands, and a
`redline_core.restore` package all exist. Mission 1B-A1 is **HEALTHY_SOURCE
only**: it restores a target backup that itself independently re-verifies
immediately before restoring. Mission 1B-A2-1 (Source Classification +
Read-Only Recovery Planning) is implemented, published, and closed --
`redline backup restore-recovery-plan <backup_id>`, `build_recovery_plan()`,
and the `SourceCondition`/`RecoveryFeasibility` classification model all
exist, and are **strictly read-only**. Mission 1B-A2-2 (Degraded-Source
Capture) is implemented, published, and closed --
`build_degraded_source_capture()` and a new, structurally distinct
`degraded_source_captures/` package namespace (`dsc1-...` capture IDs) exist,
providing whole-system, best-effort **evidence preservation** for the case
where the live source cannot satisfy Mission 1A's fresh pre-restore backup
contract. **A degraded-source capture is never a Mission 1A backup, never a
Restore source, never a partial backup, and never a rollback or resumable
recovery transaction** -- it cannot appear in `backup list`, cannot pass
Mission 1A backup verification, and cannot be accepted by Restore, all by
construction (namespace/schema rejection), not merely by convention.
Mission 1B-A2-3 (Recovery Execution + Journal/Evidence Integration) is
implemented, published, and closed --
`redline backup restore-recovery <backup_id>` (DESTRUCTIVE, gated by an
escalated `RecoveryAuthorization`), `execute_recovery()`, disposition
(`recovery_disposition.py`), stability checking (`recovery_stability.py`),
and shared verification extraction (`verification.py`) all exist. Every
attempt builds its own brand-new degraded-source capture -- there is no
`--capture-id` anywhere, and a pre-existing capture is never an execution
input. **With Mission 1B-A2-3 published and exact-head CI-verified, the
parent Mission 1B-A2 (DEGRADED_SOURCE / MISSING_SOURCE Recovery) is
implementation-scope complete; see
`docs/V2_MISSION_1B_A2_CLOSURE_2026-08-19.md` for the parent-level closure
record.** See §13 below for the full Mission 1B-A1 architecture, §14 for the
full Mission 1B-A2-1 architecture, §15 for the full Mission 1B-A2-2
architecture, and §16 for the full Mission 1B-A2-3 architecture; §1-§11
below describe Mission 1A (Backup + Verification) exactly as originally
implemented and are unchanged by any later mission.

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

## 15. Mission 1B-A2-2: Degraded-Source Capture

**Governance:** Agents advise. Paul decides. Authorized for Mission
1B-A2-2 implementation only. This authorization does not include a
checkpoint commit, closure, push, tag, or any destructive recovery
execution -- Mission 1B-A2-3 (recovery execution + journal/evidence
integration) remains separate, not-yet-authorized future work, as does
Mission 1B-B. Mission 1A, Mission 1B-A1, and Mission 1B-A2-1 are treated
as locked published foundations; nothing in this section modifies any of
their behavior, and this mission touches zero previously-existing file --
every path introduced by Mission 1B-A2-2 is new.

### 15.1 Scope boundary: preservation/evidence only

A degraded-source capture is the application-level-immutable preservation
artifact built when the current live source cannot satisfy Mission 1A's
valid, fresh pre-restore backup contract -- "immutable" here means this
subsystem's own API provides no overwrite, append, resume, or repair
operation against a sealed capture (see §15.12), never that the
filesystem itself enforces immutability (no ACL/read-only-bit change or
equivalent OS-level protection is applied to a sealed capture directory
or its contents). It is evidence, never a Mission 1A backup,
never a Restore source, never a partial backup, and never a rollback or
resumable recovery transaction. Mission 1B-A2-2 introduces capture
capability only -- it performs no sidecar disposition, no wrong-type
live-object disposition, no Restore staging, no database or config
replacement, and no Restore/recovery execution journal integration. No CLI
command is registered for this capability; it is exposed as a plain,
programmatic function for a future, separately authorized Mission 1B-A2-3
to orchestrate as one step of an eventual, escalated-authorization-gated
recovery attempt (see §15.13).

### 15.2 Package layout and composition

```
src/redline_core/restore/
  capture_models.py       CaptureItemOutcome, StatFingerprint, CaptureItemRecord, CaptureResult
  capture_exceptions.py   typed capture-package failure taxonomy (§15.9)
  capture_paths.py        capture_id validation/build, capture-root resolution
  capture_io.py           best_effort_capture_file() -- the non-fail-closed read/copy primitive
  capture_package.py      per-slot classify-then-capture dispatch, staging, manifest, seal, publish
  capture_manager.py      build_degraded_source_capture() -- the one public orchestrator
```

No file previously belonging to Mission 1A, Mission 1B-A1, or Mission
1B-A2-1 is modified. `capture_models.py`/`capture_exceptions.py` mirror
`redline_core.backup.models`/`.exceptions`' and `redline_core.restore.
recovery_models`' own frozen/slotted-dataclass and typed-exception
conventions exactly.

### 15.3 Namespace/identity: structurally impossible to confuse with a Mission 1A backup

| | Mission 1A backup | Degraded-source capture |
|---|---|---|
| ID schema | `b1-<timestamp>-<12 hex digest>` | `dsc1-<timestamp>-<12 random hex>` |
| Directory | `<backup_path>/system_backups/<backup_id>/` | `<backup_path>/degraded_source_captures/<capture_id>/` |
| Staging | `<backup_path>/.staging/` | `<backup_path>/.staging_capture/` |
| Listed by | `BackupManager.list_backups()` | nothing -- no capture-listing function exists |
| Verified by | `BackupManager.verify_backup()` | nothing -- `validate_backup_id()`'s `b1-` regex structurally rejects a `dsc1-...` ID before verification is ever attempted |
| Restore target | `RestoreManager.restore_plan()`/`.restore()` | rejected identically -- both call `validate_backup_id()` first |

A capture ID's `dsc1-` prefix means `redline_core.backup.paths.
validate_backup_id()` (locked, unmodified) rejects it with a plain
`ValueError` before any backup-domain code ever runs -- proven directly by
`test_capture_cannot_pass_mission_1a_backup_verification` and
`test_capture_cannot_be_restore_target`
(`tests/unit/test_capture_manager.py`). `BackupManager.list_backups()`
(locked, unmodified) only ever scans `system_backups/`, a directory a
capture never writes to -- proven by `test_capture_never_appears_in_
backup_list`. This is a structural guarantee, not a policy one: no code
change anywhere could accidentally cause one namespace to satisfy the
other's identity check.

### 15.4 Capture-root safety: reused, not reinvented

`capture_paths.resolve_capture_root()` reuses `redline_core.backup.paths.
validate_backup_root_containment()` (locked, unmodified) directly --
translating its `BackupPathContainmentError` into
`CaptureDestinationUnsafeError` at this subsystem's own boundary. A
capture root safe for Mission 1A backups (must not equal, contain, or be
contained by the live database or configuration directory) is safe for
captures too, since `degraded_source_captures/` is simply a sibling
subdirectory of the identical resolved `paths.backup_path` root
`system_backups/`/`restore_journal/`/`.staging/`/`.redline_restore_staging/`
already share. No new containment primitive was written for this mission.
`validate_backup_root_containment()`'s own containment check is lexical
(`Path.resolve(strict=False)`), which proves non-overlap but not
filesystem-object safety; the Mission 1B-A2-2 safety correction
(Correction 3) adds `capture_paths.require_safe_capture_directory()`
alongside it -- a small, locally-reimplemented lstat-based mirror of
`redline_core.backup.paths.require_safe_directory()`'s exact contract,
raising this subsystem's own `CaptureDestinationUnsafeError` instead of
Backup Manager's exception type -- and applies it, bracketing each
directory-creation call with a before-and-after check, to every
capture-destination filesystem object this mission writes into: the
configured capture root itself, `.staging_capture/`, one staging attempt
directory, and `degraded_source_captures/`. The final publish-time
collision check (`publish_staged_capture()`) was also changed from
`Path.exists()` to `os.lstat()` -- `exists()` follows symlinks and
reports `False` for a dangling/unsafe reparse object occupying the exact
final capture-ID path, silently missing exactly the collision case that
matters most; `lstat()` detects that object without ever following it.

### 15.5 Volume rule (corrected from the accepted architecture record)

The live source and the capture root **may** be on different volumes --
a capture is an evidence-copy operation, not Mission 1B-A1's atomic
destructive live-replacement, so Restore's same-volume-as-the-live-path
rule does not apply here. Capture staging (`<capture_root>/
.staging_capture/<uuid>/`) and the final sealed package
(`<capture_root>/degraded_source_captures/<capture_id>/`) are both nested
directly under the identical `capture_root`, so they are trivially always
same-volume by construction -- exactly mirroring Mission 1A's own
`build_staged_backup()`/`publish_staged_backup()` shape (stage → seal →
verify → atomically `os.rename()` publish), never Restore's staging.py
pattern of staging next to the *live* path's own parent.

### 15.6 Whole-system capture

Mission 1A backups remain all-or-nothing; a degraded-source capture
mirrors that shape rather than weakening it. One capture package
unconditionally accounts for the whole observed system on every attempt:
exactly one database slot, exactly six required config-file slots, every
currently-present SQLite sidecar, a safe non-recursive config-directory
inventory, and per-item capture outcomes for all of the above -- **even
when one side is independently classified `HEALTHY`** by Mission 1B-A2-1.
A healthy surviving component inside a degraded-run capture is still
capture evidence, never a separate "partial Mission 1A backup" -- proven
by `test_healthy_side_still_captured_as_evidence_not_skipped` and the
six-combination parametrized `test_whole_system_capture_accounts_for_
both_sides` (degraded DB + healthy config, healthy DB + degraded config,
missing DB + healthy config, healthy DB + missing config, both degraded,
both missing -- `tests/unit/test_capture_manager.py`).

### 15.7 Per-item outcome model

`CaptureItemOutcome` (`capture_models.py`): `CAPTURED_VERIFIED`,
`CAPTURED_UNVERIFIED`, `UNREADABLE`, `UNSAFE_OBJECT_RECORDED`, `MISSING`,
`WRONG_TYPE_RECORDED`, `CHANGED_DURING_CAPTURE`. `WRONG_TYPE_RECORDED` is
one addition beyond the architecture record's minimum named set,
introduced because "a plain directory sits where the database file is
expected" is semantically distinct from both "unreadable" (bytes were
attempted and failed) and "unsafe" (never opened at all) -- collapsing it
into either would lose exactly the distinction a future operator or
Mission 1B-A2-3 needs to decide what, if anything, could safely be moved
aside later. Never collapsed into package failure: a capture package can,
and routinely will, seal successfully while reporting several items in
any of these states other than `CAPTURED_VERIFIED` -- see §15.9.

### 15.8 DB and config capture behavior

**Database** (`capture_package.capture_database_slot()`): unconditionally
attempted every capture, regardless of the supplied classification.
Dispatch order, shared with each config file via
`capture_regular_file_item()`: missing (`os.lstat()` raises
`FileNotFoundError`) → cannot inspect (other `OSError`, `UNREADABLE`) →
unsafe filesystem object (`fsutil.is_unsafe_link()`, `UNSAFE_OBJECT_
RECORDED`, never followed, never opened, target never inspected) → wrong
type (not `S_ISREG`; a directory gets a shallow, non-recursive, one-level
listing only -- its contents are never treated as candidate database
bytes and are never copied anywhere) → best-effort byte capture
(`capture_io.best_effort_capture_file()`, §15.10).

**Config** (`capture_package.capture_config_slot()`): the config
*directory* itself is classified first (missing/unsafe/wrong-type/normal),
exactly mirroring the database dispatch; if it is missing, unsafe, or the
wrong type, all six required-file slots are honestly recorded as "not
individually inspected" (never enumerated, never guessed at) rather than
silently omitted, preserving the deterministic six-slot shape every
capture manifest has. If it is an ordinary, safe, enumerable directory,
each of the six required files goes through the identical shared
per-item dispatch, and a safe, single-level, non-recursive inventory of
every entry actually present (required or not) is recorded separately --
explaining any unexpected config entry by name, never by content. Config
file *content* (YAML parse, `RedlineConfig` schema) is never validated
anywhere in this module, exactly matching Mission 1B-A2-1's own
established discipline: capture is byte/evidence preservation, not
configuration semantic validation.

### 15.9 Capture package success vs. capture system failure

**Capture package success**: the sealed artifact itself was safely
created, with a completion marker (`CAPTURE_COMPLETE`) written last and a
manifest that truthfully records every item's real outcome -- proven by
`test_package_succeeds_even_when_every_item_is_unreadable_or_missing`
(every slot `MISSING`, package still seals). Immediately before sealing,
`_verify_staged_capture_self_consistency()` performs the package-level
integrity checks this module makes (strengthened by the Mission 1B-A2-2
safety correction, Correction 5, beyond the original existence/size-only
check): every `captured_relative_path` the manifest names must actually
exist on disk as a safe (lstat-checked, never a symlink/junction/reparse
point) regular file, matching both the manifest-recorded size and --
when one was recorded -- the manifest-recorded SHA-256 exactly; every
no-payload record (`MISSING`/`UNSAFE_OBJECT_RECORDED`/
`WRONG_TYPE_RECORDED`/a partial-read `UNREADABLE`) must have no stray
filesystem object sitting at the payload location it would have used;
and the manifest's own `.sha256` sidecar is independently re-verified
against the manifest bytes actually on disk. This remains a
self-consistency check of the staged *package*, never a re-proof of
source trustworthiness (each item's own outcome already carries that). A
mismatch anywhere in this is `CaptureSealFailedError`.

**Capture system failure**: the package itself could not be safely
created or sealed -- destination unconfigured
(`CaptureConfigurationError`), destination unsafe/overlapping
(`CaptureDestinationUnsafeError`), an existing `capture_id` collision
(`CapturePackageCollisionError`), a staging/write failure
(`CaptureSystemWriteFailedError`), or a seal/self-consistency failure
(`CaptureSealFailedError`). **Every one of these is an unconditional hard
stop. No proceed-anyway override exists anywhere in this package**, and
none was added by this mission -- proven directly by
`test_capture_system_failure_unconfigured_destination`,
`test_capture_system_failure_unsafe_destination_overlapping_config`, and
`test_capture_system_failure_leaves_no_usable_package`.

### 15.10 SQLite Online Backup question -- resolved conservatively

The accepted architecture left open whether an openable-but-degraded
SQLite database should first attempt the SQLite Online Backup API before
raw-byte preservation. Mission 1B-A2-2 resolves this conservatively:
**raw live-file byte preservation is the only capture mechanism
implemented.** No SQLite Online Backup API attempt, and no
supplementary SQLite-logical snapshot, exists anywhere in this mission.
Justification: attempting `sqlite3.Connection.backup()` against a
database already known to be degraded risks unpredictable behavior
against corrupt input (the exact category of risk Mission 1B-A2-1's own
`recovery_planning.py` module docstring already documents for a related
case -- calling into SQLite machinery against a file already suspected
corrupt), would not obviously preserve *more* useful evidence than the
raw bytes already do, and every requirement this mission was given
(never mutate the live source, never create live SQLite sidecars, never
make a normalized copy's success a precondition for package success,
never silently lose information about the original bytes) is fully and
more simply satisfied by raw preservation alone. `capture_io.
best_effort_capture_file()` reuses the identical stat-fingerprint
identity technique `fsutil.open_stable_source()` uses internally
(size/mtime_ns/inode/device, checked before and after streaming) --
downgraded from "raise" to "record `CHANGED_DURING_CAPTURE` and return" --
plus an independent post-write re-read/re-hash of the destination,
mirroring Mission 1A's own `_copy_and_verify_config_file()`/
`_copy_and_verify()` double-check pattern exactly.

### 15.11 SQLite sidecars: evidence only

`capture_package.capture_sidecars()` no longer reuses `redline_core.
restore.sidecar.find_present_sidecars()` (locked, unmodified) for
presence detection -- the Mission 1B-A2-2 safety correction (Correction 4)
replaced that `Path.exists()`-based presence check (correct for Mission
1B-A1's own fail-closed "must not proceed" purpose, but blind to a
dangling unsafe symlink/junction/reparse sidecar, since `exists()` follows
a link and reports `False` for a broken target) with a direct, per-suffix
`os.lstat()` probe against the same `SIDECAR_SUFFIXES` vocabulary. A
suffix is skipped only on genuine absence (`FileNotFoundError`, matching
`find_present_sidecars()`'s own correct behavior for that case); every
other observed suffix -- including a dangling unsafe one -- is handed to
the identical shared per-item capture dispatch used everywhere else in
this module. Sidecars are captured purely as evidence: never merged into
the database slot, never treated as proof of quiescence, and -- like
every item in this module -- never moved, renamed, or deleted. A missing
database with a present, orphaned sidecar is captured and reported
correctly and independently (`test_capture_sidecars_present_when_db_
missing`), and the same independence now holds for a missing database
alongside a *dangling unsafe* sidecar
(`test_capture_sidecars_dangling_unsafe_sidecar_recorded_even_when_db_
missing`). Disposition of a sidecar (move-aside before a future
replacement) remains explicitly out of scope; A2-3 owns that decision
under its own escalated-authorization ceremony.

### 15.12 Immutability

**Application-level only** (Mission 1B-A2-2 safety-correction
clarification, Correction 6): every guarantee below is enforced by this
subsystem's own API surface -- no operation exists anywhere in this
module to overwrite, append to, resume, or repair a sealed capture. None
of it is filesystem-ACL or read-only-bit enforced; a sealed capture
directory receives no OS-level write-protection of any kind, and nothing
outside this subsystem's own code paths is prevented from writing to it.

One capture attempt → one collision-refusing `capture_id`
(`capture_paths.build_capture_id()`, random-suffixed, mirroring
`redline_core.restore.journal.build_restore_id()`'s reasoning rather than
Mission 1A's content-digest-derived `backup_id` -- degraded evidence has
no single trustworthy content digest of its own before capture begins).
Staging lives in a namespace (`.staging_capture/<uuid4>/`) distinct from
the sealed, published package; publication is a single atomic
`os.rename()` that fails closed on collision
(`CapturePackageCollisionError`) rather than overwriting anything, exactly
mirroring Mission 1A's own `publish_staged_backup()`. No append-after-seal,
no resume, and no repair path exists anywhere in this module. Proven
directly by `test_cannot_overwrite_sealed_capture` and
`test_prior_sealed_capture_byte_identical_after_later_attempt` (a second,
independent capture attempt against changed live source content never
alters the first capture's already-sealed manifest or payload bytes).

### 15.13 CLI/API boundary

**No CLI command is registered for degraded-source capture.** The strong
default this mission resolves that open design question with:
programmatic capability first, because the only legitimate caller in the
accepted architecture is a future Mission 1B-A2-3 recovery attempt already
inside its own escalated-authorization ceremony -- exposing a standalone
capture CLI command now would let an operator trigger evidence-
preservation activity disconnected from that ceremony, for no
architectural benefit this mission's scope requires. `build_degraded_
source_capture()` (`capture_manager.py`) is the one public entry point;
a read-only capture-planning CLI, if ever wanted later, would need its own
separate justification and Founder authorization, not this one.

### 15.14 Manifest

`capture_manifest.json` (canonical JSON, `schema_tag: "dsc1"`) records:
`capture_id`, `created_at`, `reason`, `source` (live DB path, live config
path, Redline OS/Python version), `database` (the full `CaptureItemRecord`
plus the caller-supplied Mission 1B-A2-1 assessment dict, recorded
verbatim as reference context), `config` (`directory` -- `null` for an
ordinary safe directory, populated only for an abnormal container;
`files` -- always exactly six; `directory_inventory`; the supplied
assessment dict), `sidecars` (one entry per currently-present sidecar),
`total_bytes_captured`, and `capture_package_status`. Every
`CaptureItemRecord` serializes `item_key`, `source_path`, `outcome`,
`captured_relative_path`, `size_bytes`, `sha256`, `stat_fingerprint`
(`size`/`mtime_ns`/`ino`/`dev`), `unsafe_object`, and `detail` --
deterministic, structured, and directly assertable in tests (no embedded
free-text logs).

### 15.15 Relationship to Mission 1B-A2-1

`build_degraded_source_capture()` never calls `classify_database_source()`/
`classify_config_source()` itself -- it requires the caller-supplied
`SourceSideAssessment` values as required parameters, reused and recorded
verbatim, so there is exactly one real HEALTHY/DEGRADED/MISSING
classification implementation in this repository, never a second one
drifting alongside it (`test_capture_system_failure_*` and every
whole-system test in `tests/unit/test_capture_manager.py` pass
already-computed assessments from `recovery_classification.py` directly).
The fresh, independent per-item outcomes capture itself observes are a
distinct, complementary signal -- exactly what reveals drift between
planning-time classification and capture-time reality (e.g.
`CHANGED_DURING_CAPTURE`), without re-implementing the classifier to
detect it.

### 15.16 Windows disposition gate -- unchanged, still open

Mission 1B-A2-2 implements no disposition of any kind. The Windows
rename/move-aside behavior Mission 1B-A2-1's closure recorded as an open
future gate for a directory-type database path or a regular-file-type
config path remains exactly as open as before this mission -- Mission
1B-A2-2 only ever records shallow, non-recursive evidence for such an
object (`WRONG_TYPE_RECORDED`) and never attempts to move it. Unsafe
link/junction/reparse objects remain `RECOVERY_BLOCKED` per Mission
1B-A2-1's own model and are not, and are not intended to become, part of
this gate -- captured as metadata-only evidence here, never disposed of
by any future mission's disposition logic either.

### 15.17 Test evidence

- **`tests/unit/test_capture_io.py`**: 6 passed -- the best-effort
  primitive's full outcome decision tree (verified, missing, unreadable
  open failure, partial read preserved, changed during capture,
  destination re-verify mismatch).
- **`tests/unit/test_capture_package.py`**: 20 passed -- per-slot
  dispatch (database: healthy/degraded-readable/missing/directory/unsafe-
  link; config: six safe files/missing file/wrong-type file/unsafe-link
  file/unsafe-link directory/missing directory/unexpected inventory
  entry; sidecars: none/WAL+SHM+journal/orphaned/unreadable), plus
  manifest shape, publish, collision refusal, and seal self-consistency.
- **`tests/unit/test_capture_manager.py`**: 24 passed -- namespace/
  identity isolation (schema, backup-list exclusion, verification
  rejection, Restore-target rejection, directory separation), the full
  six-combination whole-system matrix, package-succeeds-despite-all-
  unreadable, capture system failure (unconfigured/unsafe destination,
  write failure with no usable package left behind), immutability
  (collision refusal, byte-identical prior capture), path safety
  (destination cannot alias the live database's own directory), and the
  read-only live-source proof (DB/config/sidecar bytes and directory
  inventory unchanged, no Restore staging/journal/sidecar created for the
  live database, an unsafe object never followed end-to-end).
- **Mission 1B-A2-1 / Mission 1B-A1 / Mission 1A / composition
  regression**: 49 + 184 = 233 passed, identical to the published Mission
  1B-A2-1 baseline, zero change -- Mission 1B-A2-2 touches zero
  previously-existing file.
- **Broader `tests/unit`/`tests/integration` suite**: 3174 passed / 32
  failed / 18 skipped -- the same 32 pre-existing failure families already
  documented in the Mission 1A, Mission 1B-A1, and Mission 1B-A2-1 closure
  records (CLI end-to-end Windows-path/YAML fixture bug, fresh-venv
  installed-smoke variance, one native-process-helper timing test, and the
  historical RLC-E9901 harness pin consequence -- unchanged from Mission
  1B-A2-1, since this mission touches neither `src/cli/main.py` nor
  `src/redline_core/runtime/composition.py`). The passed count differs
  from the prior 3122-plus-new-tests arithmetic by a small margin
  consistent with this suite's own already-documented installed-smoke/
  native-process-timing run-to-run member variance, not a new failure
  family -- the failed (32) and skipped (18) counts, and every failing
  test's identity, are unchanged.

### 15.18 Explicitly deferred

Not implemented by Mission 1B-A2-2, and not scheduled by this document:
sidecar disposition, wrong-type live-object disposition (directory
move-aside, file rename-aside), Restore staging, database replacement,
config replacement, a Restore/recovery execution journal, `backup
restore-recovery` (destructive), any CLI for capture, Mission 1B-A2-3,
Mission 1B-B, a live production degraded-source capture (every test in
this mission used only `tmp_path`-scoped, synthetic fixtures --
`REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` were never touched), any Control
Room mutation, and any Resolve interaction.

### 15.19 Post-implementation safety correction (uncommitted at authoring time)

A read-only post-implementation safety review of the §15.1-§15.18
implementation above found it **NOT READY FOR CHECKPOINT** on a confirmed
unsafe-source TOCTOU defect, plus three review findings Control Room
additionally treated as checkpoint-blocking. The accepted §15.1-§15.18
architecture and implementation direction were **not** redesigned by this
correction; every change below is a targeted fix to the five affected
functions, applied under the same governance model
(`docs/CHANGELOG.md`'s "Agents advise. Paul decides.").

1. **Source TOCTOU** (`capture_io.best_effort_capture_file()`): the
   opened-handle identity proof described in §15.10 is new -- before this
   correction, a pathname safety check (the caller's own, plus this
   function's own pre-open `os.lstat()`) was never re-proven against what
   `open()` actually resolved a moment later, so a symlink/junction/
   reparse point substituted in that window could have its bytes
   captured and, in the right timing, mislabeled `CAPTURED_VERIFIED`.
   Fixed honestly as "the substituted object's bytes are never READ," not
   "the substituted object is never OPENED" -- Windows offers no portable
   no-follow-at-open primitive (`os.O_NOFOLLOW` does not exist there) for
   this repository's supported primitives to use instead.
2. **Config container TOCTOU** (`capture_package.capture_config_slot()`):
   see §15.4's updated text -- an unsafe/reparse substitution of the
   config directory itself, occurring between the pre-enumeration safety
   check and `iterdir()` actually running, is now caught by a
   post-enumeration re-observation before either the inventory or any
   per-file capture built from that directory is trusted.
3. **Capture destination safety**: see §15.4's updated text --
   `capture_paths.require_safe_capture_directory()` is new, applied to
   the capture root, `.staging_capture/`, the staging attempt directory,
   and `degraded_source_captures/`; the final publish-time collision
   check moved from `Path.exists()` to `os.lstat()`.
4. **Sidecar discovery for capture**: see §15.11's updated text --
   `capture_sidecars()` no longer pre-filters through the locked,
   `Path.exists()`-based `find_present_sidecars()`, closing its blindness
   to a dangling unsafe sidecar.
5. **Seal-time self-verification**: see §15.9's updated text --
   `_verify_staged_capture_self_consistency()` now independently
   re-hashes captured payload against the manifest-recorded SHA-256,
   lstat-checks payload safety (not just existence), checks absence
   consistency for no-payload records, and independently re-verifies the
   manifest's own `.sha256` sidecar.
6. **Immutability terminology**: see §15.1's and §15.12's updated text --
   clarified as application-level only; no OS/ACL/read-only-bit
   enforcement was added or implied.

No disposition, Restore staging, database/config replacement, or
Restore/recovery execution journal integration was added by this
correction -- §15.18's deferred list is unchanged. Fifteen new regression
tests were added across the three existing A2-2 test files (none removed
or weakened); the focused A2-2 suite grew from 50 to 65 passed. No
previously-passing A2-2, Mission 1B-A2-1, Mission 1B-A1, or Mission 1A
test was altered in a way that weakens what it proves. This correction
remains uncommitted at authoring time, per the same commit/push boundary
as §15.1-§15.18.

## 16. Mission 1B-A2-3: Recovery Execution + Journal/Evidence Integration

**Governance:** Agents advise. Paul decides. Authorized for Mission
1B-A2-3 IMPLEMENTATION only, after Mission 1B-A2-3-Prep (Windows
Filesystem Disposition Behavioral Proof) and Mission 1B-A2-3-Prep2
(Shared Sidecar Safety Classification + Recovery-Planning Hardening)
closed the architecture blockers those two preparatory missions each
identified, and after a Control Room implementation-readiness review and
final architecture ratification (conducted outside this repository, after
the last durably published state) that Paul's explicit, current-thread
IMPLEMENTATION authorization exercises. This authorization does not
include CHECKPOINT COMMIT, CLOSURE DOCUMENTATION, CLOSURE COMMIT, or
PUBLICATION PUSH. Mission 1B-B remains separate, not-yet-authorized future
work.

### 16.1 Scope boundary: execution, not planning

Mission 1B-A2-3 is the first mission in the Mission 1B-A2 family that
performs live mutation of the degraded/missing source. Every prior
Mission 1B-A2 step (A2-1 classification/planning, A2-2 capture,
A2-3-Prep/Prep2 behavioral proof and shared classification) was strictly
read-only or evidence-only. This mission adds exactly one destructive
capability -- `redline backup restore-recovery <backup_id>` -- gated by an
escalated, itemized `RecoveryAuthorization` distinct from Mission 1B-A1's
own `QuiescenceAttestations`-only gate.

### 16.2 Package layout and composition

```
src/redline_core/restore/
  recovery_models.py          + RecoveryAuthorization (additive)
  recovery_stability.py       NEW -- reusable read-only target-level stability primitive
  recovery_disposition.py     NEW -- move-aside disposition of an existing live object
  verification.py             NEW -- extracted shared Restore verification (STEP 0-6)
  recovery_execution.py       NEW -- execute_recovery(): the one public orchestrator
  journal.py                  + recovery states, opt-in attempt_kind (additive)
  manager.py                  _verify_restore() -> thin wrapper around verification.py
  capture_manager.py          + verify_degraded_source_capture() (additive)
  exceptions.py                + Recovery* exception taxonomy (additive)
src/cli/
  recovery_execution_commands.py   NEW -- `redline backup restore-recovery <backup_id>`
src/cli/backup_commands.py    registers recovery_execution_commands onto `backup`
src/cli/main.py               dispatches `restore-recovery` through RestoreServices
```

Dispatched through the identical `RestoreServices`/`build_restore_services()`
composition tier `restore-plan`/`restore`/`restore-recovery-plan` already
use -- no new composition tier was added. `staging.py`, `sidecar.py`,
`quiescence.py`, `schema_fingerprint.py`, `capture_package.py`,
`sidecar_classification.py`, `recovery_planning.py`, `restore_commands.py`,
and `recovery_planning_commands.py` were **not modified** -- every one of
their existing public functions is reused directly, unmodified.

### 16.3 RecoveryAuthorization

```python
@dataclass(frozen=True, slots=True)
class RecoveryAuthorization:
    confirm_backup_id: str
    quiescence: QuiescenceAttestations
    disposition_understood: bool
    no_automatic_rollback_understood: bool
```

`recovery_execution.require_recovery_authorization()` validates, in exact
order: (1) `backup_id` itself is well-formed (`validate_backup_id()`); (2)
`confirm_backup_id` exactly equals `backup_id`
(`RecoveryConfirmationError` otherwise); (3) the three existing
`QuiescenceAttestations` via the locked, unmodified `quiescence.
require_attestations()`; (4) the two recovery-specific attestations
(`RecoveryAttestationMissingError` naming whichever is missing). There is
no blanket `--yes` anywhere in this taxonomy, matching Mission 1B-A1's own
convention exactly. `RECOVERY_BLOCKED` (the fresh, post-capture
source/sidecar reclassification outcome, §16.7) is absolutely
non-overridable -- no field on `RecoveryAuthorization`, and no CLI flag
anywhere in this repository, can bypass it.

### 16.4 CLI surface

```
redline backup restore-recovery <backup_id> --confirm-backup-id <backup_id> \
    --attest-mcp-stopped --attest-control-room-stopped --attest-no-other-cli-operation \
    --attest-disposition-understood --attest-no-automatic-rollback \
    [--reason TEXT]
```

Registered onto the *same* `backup` subparsers object
(`cli.recovery_execution_commands.register_parser()`, called from
`cli.backup_commands.register_parser()`), dispatched by `cli.main` through
`RestoreServices`, exactly like `restore-plan`/`restore`/
`restore-recovery-plan`. **No `--capture-id`/`--confirm-capture-id` flag
exists anywhere** -- every attempt builds its own fresh, brand-new
degraded-source capture; a pre-existing capture is never an execution
input (`test_execute_recovery_signature_has_no_capture_id_parameter`,
`test_restore_recovery_has_no_capture_id_flag`).

### 16.5 Full execution ordering

```
explicit RecoveryAuthorization
  -> fresh recovery-plan validation                (build_recovery_plan(), initial)
  -> mandatory fresh degraded-source capture         (build_degraded_source_capture())
  -> capture reverification, exact same capture_id   (verify_degraded_source_capture())
  -> CHANGED_DURING_CAPTURE hard-stop check
  -> fresh source/sidecar reclassification           (build_recovery_plan(), post-capture)
  -> PRE_MUTATION_STABILITY
  -> quiescence (proved probe, or not-applicable)
  -> disposition (fixed order: database -> config -> -journal -> -wal -> -shm)
  -> FINAL_STABILITY
  -> existing sidecar pre-check                       (sidecar.require_no_sidecars(), unmodified)
  -> staging (staging.stage_database()/stage_config(), unmodified)
  -> database replacement (mutation-bound recheck + staging.replace_database())
  -> config replacement (mutation-bound recheck + staging.rename_config_aside()/install_staged_config())
  -> shared final verification                        (verification.verify_restore(), STEP 0-6)
  -> VERIFIED_SUCCESS
```

Every attempt is new: its own `restore_id`, its own journal, its own
fresh capture. `execute_recovery()` never inspects, resumes, or repairs a
prior attempt's journal or a prior attempt's capture.

### 16.6 Fresh capture and reverification

`build_degraded_source_capture()` (Mission 1B-A2-2, unmodified) is called
unconditionally on every attempt that passes initial recovery-plan
validation, fed the exact `SourceSideAssessment` values that same initial
validation just computed. `capture_manager.verify_degraded_source_capture()`
(new, additive) then reruns Mission 1B-A2-2's own private staged-capture
self-consistency primitive (`capture_package.
_verify_staged_capture_self_consistency()`) directly against the
just-published package, keyed to the exact `capture_id` this attempt just
built -- reused, not duplicated. Failure at either step is a typed
`RecoveryCaptureFailedError`, zero live-target mutation.

Immediately after reverification, every capture item (database, the
config-directory container when abnormal, every required config file,
every observed sidecar) is scanned for `CHANGED_DURING_CAPTURE`. Any
match is an unconditional terminal hard stop
(`RecoveryChangedDuringCaptureError`) -- it never reaches disposition and
is never included in any evidence-preservation disposition trigger.

### 16.7 Fresh source/sidecar reclassification

After the hard-stop check, `build_recovery_plan()` (Mission 1B-A2-1,
unmodified) is called a **second** time, against the current live state.
`would_proceed is False` here -- for any reason: an invalid/incompatible
target backup, database or config `RECOVERY_BLOCKED`, or a `WRONG_TYPE`/
`UNSAFE` sidecar -- is `SOURCE_RECLASSIFICATION_BLOCKED`, a terminal
`RecoveryBlockedError`, zero live-target mutation. This is deliberately
the same `would_proceed` check as the initial validation, re-run fresh:
a database/config pair that is completely `HEALTHY` by the time
reclassification runs, combined with a `WRONG_TYPE`/`UNSAFE` sidecar
alone, still blocks -- `RECOVERY_BLOCKED` is a property of the whole
plan, not just the two source sides.

### 16.8 Stability: one reusable primitive (`recovery_stability.py`)

`ExpectedTargetState`/`check_target_stability()` is the one primitive used
identically by `PRE_MUTATION_STABILITY`, every mutation-bound recheck
immediately before a disposition `os.rename()`, immediately before
`DB_REPLACE_INTENT`/`CONFIG_RENAME_ASIDE_INTENT`/`CONFIG_INSTALL_INTENT`,
and `FINAL_STABILITY`. Evidence strength, derived from the fresh capture's
own `CaptureItemRecord`/`StatFingerprint` (reused directly, no second
baseline representation invented):

- `CAPTURED_VERIFIED` / `CAPTURED_UNVERIFIED` (both always carry a
  trustworthy source-observed hash) -- compared by live hash+size.
- `UNREADABLE` -- **never** treated as a byte-hash source (a partial
  read's `sha256` is not a full-file hash). With a complete
  `StatFingerprint`: compared by type/safety/size/mtime_ns/ino/dev only.
  Without one: insufficient evidence, always a mismatch -- an `UNREADABLE`
  database with no fingerprint evidence fails at `PRE_MUTATION_STABILITY`
  and never reaches disposition.
- `UNSAFE_OBJECT_RECORDED` / `WRONG_TYPE_RECORDED` -- fingerprint-only.
  The expected "regular file vs. not" flag for the `WRONG_TYPE_RECORDED`
  case is supplied explicitly by the caller (never guessed from the
  outcome alone) -- a database's own wrong type always means "not a
  regular file" (typically a directory, the Prep-proven case), while a
  config *container*'s wrong type means "not a directory", which the
  Prep-proven case is a regular file; these are opposite expectations
  from the identical outcome enum value.
- `MISSING` -- the live target must still be missing. A sidecar suffix
  absent from the capture's own `sidecars` list (never recorded because
  it was genuinely `MISSING` at capture time) is likewise expected still
  missing.
- Config directory inventory: a fresh, shallow (non-recursive) listing
  must equal the captured inventory exactly, only when the capture
  recorded a normal, safe, enumerable container (its own
  `config_directory` record is `None`); an abnormal captured container is
  checked as one fingerprint-only target instead, never per-file.
- `CHANGED_DURING_CAPTURE` never reaches this module -- it is the earlier,
  unconditional terminal hard stop (§16.6).

`FINAL_STABILITY` reuses the identical sweep with one difference: a
disposed target's expected state becomes `expected_state_missing()`
instead of its capture baseline.

### 16.9 Disposition (`recovery_disposition.py`)

Implements exactly the contract Mission 1B-A2-3-Prep proved behaviorally
on Windows: fresh `os.lstat()` -> unsafe-object gate -> re-derived
type/classification (never trusts an earlier classification alone) ->
same-volume gate (`staging.same_volume()`, reused) -> destination
non-existence gate via `os.lstat()` (never `Path.exists()`) -> one
collision-refusing `os.rename()` -> post-move verification (source
absent, destination present). Never `os.replace()`, never `shutil.move`,
no delete fallback, no overwrite fallback, no retry, no rollback, no
resume. The restore-ID-scoped superseded destination name
(`<name>__superseded-<restore_id>`) reuses `staging.
SUPERSEDED_CONFIG_INFIX` textually, generalized to any disposition target
(database file, config directory, or sidecar file) rather than only a
config directory.

Fixed, deterministic disposition order: `database -> config -> -journal
-> -wal -> -shm`. Triggers:

- **Database**: `disposition_required` from fresh reclassification
  (`WRONG_TYPE`, e.g. a directory sitting at the database path;
  `expected_regular=False`), **or** this attempt's fresh capture recorded
  the database `UNREADABLE` with sufficient fingerprint evidence to pass
  `PRE_MUTATION_STABILITY` (evidence-preservation, `expected_regular=
  True`) -- an `UNREADABLE` database would otherwise be silently
  overwritten by the ordinary `os.replace()` database-replacement step
  without a single byte of it ever having been captured; disposition
  preserves it instead of destroying the last surviving evidence. These
  two triggers are mutually exclusive by construction (they come from
  disjoint `CaptureItemOutcome` values). An `UNREADABLE` database without
  sufficient fingerprint evidence never reaches this trigger at all -- it
  already failed at `PRE_MUTATION_STABILITY` (§16.8).
- **Config**: `disposition_required` from fresh reclassification
  (`WRONG_TYPE`, e.g. a regular file sitting at the config directory
  path; `expected_regular=True`, the Prep-proven case). `MISSING` config
  never triggers disposition (nothing to move aside).
- **Sidecars** (`-journal`, `-wal`, `-shm`, in that fixed order): a
  `SAFE_REGULAR` fresh reclassification triggers disposition
  (`expected_regular=True`). `WRONG_TYPE`/`UNSAFE` sidecars never reach
  this point -- they already caused `SOURCE_RECLASSIFICATION_BLOCKED`
  (§16.7). `MISSING` sidecars need no disposition.

Immediately before each disposition's `os.rename()`, the same
capture-baseline-aware `check_target_stability()` call used by
`PRE_MUTATION_STABILITY` is re-run against that exact target (a TOCTOU-
safety re-proof of an already-passed check, never a new evidentiary
requirement) -- a mismatch is `DISPOSITION_FAILED` with
`phase="pre_disposition_stability"`; a subsequent `dispose_target()`
failure (unsafe object, re-derived type mismatch, same-volume violation,
destination collision, or the rename itself failing, e.g. an open handle)
is `DISPOSITION_FAILED` with `phase="rename"`. Every `DISPOSITION_INTENT`/
`DISPOSITION_COMPLETE`/`DISPOSITION_FAILED` detail names `target_kind`
explicitly.

### 16.10 Config replacement: rename-aside is skipped when the path is already vacant

The ordinary two-step config replacement (`rename_config_aside()` then
`install_staged_config()`, Mission 1B-A1, unmodified) assumes a config
directory is present to rename aside. Recovery generalizes this: when the
config path is already vacant -- either because disposition already moved
a `WRONG_TYPE` config object aside, or because the fresh reclassification
found config genuinely `MISSING` to begin with (parent present, nothing
to rename) -- `CONFIG_RENAME_ASIDE_INTENT`/`rename_config_aside()` is
skipped entirely, going straight to `CONFIG_INSTALL_INTENT`. In every
case (disposed, originally missing, or freshly renamed aside by the
ordinary path), an "expected vacant" `check_target_stability()` call runs
immediately before `install_staged_config()`, unifying all three cases
into one mutation-bound recheck.

### 16.11 Mutation-bound replacement checks

Immediately after `DB_REPLACE_INTENT` and before `staging.
replace_database()`: the database target is revalidated against either
its fresh capture-derived expected state (not disposed) or "expected
missing because a previously verified disposition made it so" (disposed).
On mismatch: `DB_REPLACE_FAILED`, `phase="pre_replacement_stability"`,
`replace_database()` is never called. Likewise, when the ordinary
rename-aside path is taken: `CONFIG_RENAME_ASIDE_INTENT` -> immediate
config-container stability check -> `rename_config_aside()`; on mismatch,
`CONFIG_REPLACE_FAILED`, `phase="pre_rename_stability"`, no rename is
attempted. Immediately before `install_staged_config()`, in every case:
`CONFIG_REPLACE_FAILED`, `phase="pre_install_stability"` on mismatch.

### 16.12 Shared Restore verification authority (`verification.py`)

`RestoreManager._verify_restore()`'s exact STEP 0-6 body (Mission 1B-A1)
was extracted, behavior-preserving, into module-level `verification.
verify_restore(*, db_path, config_dir, backup_manager, manifest,
backup_id)`. `RestoreManager._verify_restore()` is now a thin wrapper
around it (`test_restore_manager_verify_restore_delegates_to_shared_
function` proves the delegation is real, not merely textually similar, by
making the shared function raise and confirming the failure propagates
through `RestoreManager.restore()`). Mission 1B-A2-3's `execute_recovery()`
calls the identical function -- there is exactly one verification
implementation in this repository, never a duplicated or approximated
copy. Mission 1B-A1's own observable behavior is unchanged, proven by the
locked 184-test regression gate re-running identically.

### 16.13 Journal: one journal, opt-in `attempt_kind`

No parallel recovery journal -- `RestoreJournal` gained one new,
opt-in constructor parameter, `attempt_kind: str | None = None`. `None`
(the default, used by every ordinary Mission 1B-A1 `restore()` call, and
by every pre-Mission-1B-A2-3 call site, unmodified) emits no
`attempt_kind` key in any recorded transition -- the locked ordinary
Restore top-level journal payload shape (`restore_id`, `backup_id`,
`sequence`, `state`, `timestamp`, `detail`) is unchanged, proven by
`test_ordinary_restore_journal_emits_no_attempt_kind_key`. A recovery
attempt passes `attempt_kind="recovery"`, included verbatim in every
transition that same journal instance records.

New `RestoreState` members, added purely additively (existing 27 states at
HEAD are unrenumbered, unmodified; verified by exact enum diff) --
**23 total**: `RECOVERY_INITIATED`, `RECOVERY_PLAN_VALIDATED`
/`RECOVERY_PLAN_BLOCKED`, `CAPTURE_INTENT`/`CAPTURE_COMPLETE`/
`CAPTURE_FAILED`, `CAPTURE_REVERIFICATION_INTENT`/`CAPTURE_REVERIFIED`/
`CAPTURE_REVERIFICATION_FAILED`, `CAPTURE_CHANGED_DURING_CAPTURE`,
`SOURCE_RECLASSIFICATION_INTENT`/`SOURCE_RECLASSIFIED`/
`SOURCE_RECLASSIFICATION_BLOCKED`, `PRE_MUTATION_STABILITY_INTENT`/
`_CONFIRMED`/`_MISMATCH`, `QUIESCENCE_NOT_APPLICABLE`,
`DISPOSITION_INTENT`/`DISPOSITION_COMPLETE`/`DISPOSITION_FAILED`,
`FINAL_STABILITY_INTENT`/`_CONFIRMED`/`_MISMATCH`. Every other transition
a recovery attempt records reuses an existing Mission 1B-A1 state
verbatim: `QUIESCENCE_CONFIRMED`/`QUIESCENCE_FAILED`,
`SIDECAR_CHECK_PASSED_PRE`/`SIDECAR_PRESENT_PRE`, `STAGING_*`,
`DB_REPLACE_*`, `CONFIG_*`, `VERIFICATION_*`.

20 of the 23 map one-to-one onto the ratified state-family list this
mission's authorization named explicitly (recovery initiation (1),
capture (3), capture reverification (3), fresh reclassification (3),
pre-mutation stability (3), quiescence-not-applicable (1), disposition
(3), final stability (3) -- 20 states, 8 families). Three are
implementation refinements, not named by that compact family list, added
because omitting them would leave a durable-record gap for behavior the
authorization elsewhere requires explicitly and unconditionally:
`RECOVERY_PLAN_VALIDATED`/`RECOVERY_PLAN_BLOCKED` durably record the
"fresh recovery-plan validation" step's own outcome -- the ordering
diagram requires this step to exist and to be able to block before any
capture is attempted, exactly mirroring the INTENT/BLOCKED pattern the
authorization *did* explicitly name for the structurally identical,
later `SOURCE_RECLASSIFICATION_BLOCKED` check; `CAPTURE_CHANGED_DURING_
CAPTURE` durably records the CHANGED_DURING_CAPTURE hard-stop the
authorization repeats three times as an unconditional, safety-critical
terminal condition ("must NEVER reach disposition") -- without a distinct
state, a human reading the journal after this hard stop would see only an
unexplained gap after `CAPTURE_REVERIFIED`. None of the three add new
mutation capability, a new bypass, or a new authorization surface; each
only journals recording of behavior already required elsewhere in this
section. Submitted for Control Room's explicit acceptance alongside this
closure, not unilaterally decided.

### 16.14 Failure doctrine

No automatic retry, rollback, resume, delete fallback, or overwrite
fallback exists anywhere in this mission's code. Every failure mode
raises a typed exception (`RecoveryConfirmationError`,
`RecoveryAttestationMissingError`, `RecoveryBlockedError`,
`RecoveryCaptureFailedError`, `RecoveryChangedDuringCaptureError`,
`RecoveryStabilityMismatchError`, `RecoveryDispositionFailedError`) and
stops; already-completed mutations (a disposition that already
succeeded) remain journaled and preserved on disk for manual inspection
-- proven by `test_execute_recovery_disposition_failure_leaves_partial_
state_preserved` and `test_execute_recovery_final_stability_catches_
reappearance_after_disposition`. Every attempt is new: a failed attempt
is never resumed, repaired, or retried automatically by this repository.

### 16.15 Explicitly deferred

Not implemented by Mission 1B-A2-3, and not scheduled by this document:
Mission 1B-B, a live production recovery drill (every test in this
mission uses only `tmp_path`-scoped, synthetic fixtures --
`REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` are never touched by any test),
MCP recovery tooling, any Control Room mutation, any Resolve interaction,
automatic rollback/retry/resume of any kind, and any new third-party
dependency introduced solely for recovery execution.
