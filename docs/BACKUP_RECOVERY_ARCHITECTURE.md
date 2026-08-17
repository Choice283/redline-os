# Backup & Recovery Architecture — Mission 1A (Backup + Verification)

**Status:** Mission 1A (System-of-Record Backup + Verification) implemented,
followed by an independent-review correction pass. **Restore is NOT
implemented.** There is no `restore_backup()` method, no `backup restore`
CLI command, no restore result type, and no MCP backup tool anywhere in this
repository. Restore is Mission 1B: a separate, not-yet-authorized
architecture requiring its own review. Nothing in this document describes
shipped restore behavior — every restore-shaped statement below is
explicitly marked as future/unimplemented.

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

`redline backup restore ...` does not exist; running it produces argparse's
own standard "invalid choice" error
(`test_register_parser_has_no_restore_action`), the same clean failure mode
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

## 12. What Mission 1B (restore) will need to design — not implemented here

Recorded only as a pointer to the earlier Mission 1A architecture-discovery
document, `docs/REDLINE_OS_V2_ARCHITECTURE_DISCOVERY_2026-08-16.md`-style
material referenced during authorization: restore preconditions
(re-verify the target backup immediately before restoring, never "restore
the latest"), a mandatory pre-restore safety snapshot of current state
(restore's own first internal step, using this same `BackupManager`),
same-volume staged `os.replace()` atomicity on Windows, post-restore
integrity + application-level smoke verification, and fail-closed behavior
on schema/version incompatibility. None of this is implemented, scheduled,
or authorized by Mission 1A. Restore remains explicitly Founder-authorized,
separate future work.
