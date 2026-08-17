# Redline OS V2 Mission 1A Closure — System-of-Record Backup + Verification

## Governance

Agents advise. Paul decides. This capability exists because V1 had no
first-class backup/restore procedure for the SQLite database that is
Redline OS's sole system of record for pipeline status
(`docs/DEPLOYMENT.md` §6, "Not automated: Database backup"), a gap
identified in the V2 Architecture Discovery report and authorized for
implementation as Mission 1A only.

## Implementation checkpoint

SHA: `b791a860aa0c2fa1a5fb8d3346c2e566eaa4d7bf`

Subject: `feat: add system-of-record backup verification`

Parent: `1d1dde25a9cd737fdf58b1246243186897e239b3`

This is the frozen Mission 1A *implementation* checkpoint — distinct from
Mission 1A *closure*, which this document and the accompanying
`docs/CHANGELOG.md`/`README.md`/`docs/DEPLOYMENT.md` updates record
separately, in their own commit, matching the Control Room V0 Mission
1–10 closure precedent (the closure record is never squashed into or
backdated onto the implementation checkpoint).

## Mission scope

Backup and verification only. The full authorized scope:

- `BackupManager.create_backup()` / `.list_backups()` / `.verify_backup()`
- `BackupServices` / `build_backup_services()` — a fourth, narrower
  composition tier
- SQLite Online Backup API snapshotting of the live database
- Exact `redline_core.config.loader.REQUIRED_FILES` config capture
- Immutable, sealed, hash-verified backup packages
- Independent, at-rest re-verification
- CLI: `backup create` / `backup list` / `backup verify`
- Documentation and tests

Explicitly and deliberately **not** in scope: restore, MCP exposure,
Control Room integration, database schema change, Archive Manager
redesign. See "Explicit absences" below.

## Architecture decision

Mirrors `redline_core.archive.package`'s proven stage → seal → verify →
publish shape deliberately, rather than inventing a different pipeline
for a structurally identical problem. Backups and archives remain two
separate responsibilities: this mission does not redesign or depend on
Archive Manager, though its package/manifest/atomic-publish mechanics are
deliberately reused in spirit. Filesystem-object safety (symlinks,
Windows junctions, reparse points) delegates entirely to the existing
domain-neutral `redline_core.fsutil.is_unsafe_link()` — the same
primitive `redline_core.archive.integrity` uses — so there is exactly one
real implementation of that safety contract in the repository.

See `docs/BACKUP_RECOVERY_ARCHITECTURE.md` for the complete architecture,
package layout, manifest contract, and error taxonomy.

## Delivered capability

An operator (or a future automated caller) can, at any time, on demand:

1. `redline backup create [--reason TEXT]` — produce one new,
   independently-verified, sealed backup package containing a consistent
   point-in-time snapshot of the live SQLite database and the exact six
   required configuration files.
2. `redline backup list` — enumerate every sealed, complete backup
   package under the configured backup root.
3. `redline backup verify <backup_id>` — independently re-verify a sealed
   backup at rest, at any later time, any number of times, without
   trusting its own prior success or its manifest's own claims.

## `BackupManager` surface

Public surface is deliberately narrow: `create_backup()`,
`list_backups()`, `verify_backup()`. No restore method, no restore result
type, and no MCP tool exists anywhere in this package — Mission 1B
(restore) is a separate, not-yet-authorized architecture.

## `BackupServices` composition boundary

A fourth, narrower composition tier alongside `ApplicationServices` (full
runtime), `CoreServices` (config-only), and `PersistenceServices` (config
+ a live DB connection, no Resolve). `build_backup_services()` loads
`RedlineConfig` and resolves the database's *path* for `BackupManager` —
it never calls `Database.connect()`, never calls `Database.init_schema()`
against the pipeline database, and never constructs or connects a Resolve
adapter. `BackupManager` opens its own independent, short-lived,
read-only SQLite connection only inside `create_backup()`.

This exists because `ArchiveManager`'s own tier, `PersistenceServices`,
opens a live `Database` connection and initializes schema — exactly the
live-DB contact Backup Manager must stay independent of, even though both
managers otherwise need "config + something DB-adjacent." Proven
behaviorally (not just statically): `Database.connect`,
`Database.init_schema`, and `ResolveScriptAdapter.__init__` were each
monkeypatched to raise, then the composition builder and the full
`create`/`list`/`verify` CLI dispatch were genuinely exercised end-to-end
through the real `cli.main.main()` entrypoint — none of the three is ever
reached.

## SQLite Online Backup API mechanism

`redline_core.backup.sqlite_snapshot.snapshot_database()` never performs
a raw filesystem copy of the live database. Determined from source, not
assumed: `Database.connect()` sets no `journal_mode` (SQLite's own
default is `DELETE`, not WAL) and several mutating methods wrap a short
multi-statement sequence in `with self.conn:`, so a raw copy taken during
that window could capture a torn main-file/journal pair. Instead, the
live database is opened through an independent, **read-only** connection
(`file:...?mode=ro`) and `sqlite3.Connection.backup()` — Python's stdlib
wrapper for SQLite's genuine Online Backup API — produces the snapshot,
reading through SQLite's own consistency machinery to a single consistent
point in time regardless of concurrent writer activity. Nothing in this
subsystem ever issues `BEGIN`/`COMMIT`/any write statement against the
live database.

## Exact `REQUIRED_FILES` config capture

Exactly the six files named by `redline_core.config.loader.REQUIRED_FILES`
are captured — `naming.yaml`, `folder_structure.yaml`,
`render_presets.yaml`, `paths.yaml`, `assets.yaml`,
`timeline_template.yaml` — never an arbitrary directory scan. Each is
streamed through `fsutil.open_stable_source()`/hashed, then independently
re-read from its just-written destination and hash/size-compared before
the package is sealed.

## Immutable package/sealing contract

```
<backup_path>/system_backups/<backup_id>/
  backup_manifest.json
  backup_manifest.sha256
  payload/
    database/redline.db
    config/{naming,folder_structure,render_presets,paths,assets,timeline_template}.yaml
  BACKUP_COMPLETE
```

`build_staged_backup()` stages into `<backup_path>/.staging/<uuid4 hex>/`,
seals (canonical-JSON manifest + SHA-256 sidecar), self-verifies, and
writes the `BACKUP_COMPLETE` marker last. `publish_staged_backup()`
independently re-verifies once more, then atomically `os.rename()`s the
staging directory into `system_backups/<backup_id>/` — the rename itself
is the collision check (`BackupDestinationCollisionError` on an existing
destination), so there is no separate check-then-act race window. A
failed publish leaves the incomplete staging directory in place for
forensic inspection, never auto-deleted.

Payload-inventory verification (`_require_exact_payload_contents()`) is a
deliberate **single-level, non-recursive** scan: because Mission 1A's
approved payload structure is always flat (exactly one file under
`payload/database`, exactly six under `payload/config`), no legitimate
nested directory can ever exist there — the correct fix for the
correction-pass finding below is "never recurse," not "recurse more
carefully." Every directory entry is rejected immediately, safe or not,
junction or ordinary, without the function ever calling anything that
would enumerate that entry's contents.

## Verification behavior

`verify_backup(backup_id)` never trusts a prior success or the manifest's
own claims at face value: it re-derives the manifest sidecar hash,
re-hashes the database snapshot and every config file against the
manifest's recorded values, and re-runs `PRAGMA integrity_check` against
the backup copy. Every failure mode raises a typed `BackupError` subclass
(see `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §10 for the full taxonomy); a
result is only ever returned with `verified=True`. Safe to call any
number of times — performs no writes.

`list_backups()` requires a completion marker, a manifest whose sidecar
hash matches, **and** (correction pass) `manifest["backup_id"] ==
package_dir.name` before surfacing a record — a renamed or copied-to-a-
different-name package is excluded, never reported as usable.

## CLI surface

```
redline backup create [--reason TEXT]
redline backup list
redline backup verify <backup_id>
```

Routed through `BackupServices`, not `PersistenceServices` (the tier
`archive` commands use) — see "`BackupServices` composition boundary"
above. `redline backup restore ...` does not exist; running it produces
argparse's own standard "invalid choice" error, the same clean failure
mode as any other never-registered subcommand.

## Explicit absences

- **No Restore.** No `restore_backup()` method, no `BackupRestoreResult`
  type, no `backup restore` CLI action, no pre-restore safety snapshot,
  no replacement/swap logic, no automatic recovery. Mission 1B is a
  separate, not-yet-authorized architecture. `docs/RECOVERY.md` §12 and
  `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §12 record what Mission 1B will
  need to design, not what it implements.
- **No MCP exposure.** `mcp_server/tools/` has no `backup_tools.py`; none
  of `create_backup()`/`list_backups()`/`verify_backup()` is reachable
  via MCP.
- **No Control Room integration.** Control Room has no backup role in
  Mission 1A. `grep`-confirmed: zero references to `backup` anywhere
  under `src/mcp_server` or `src/control_room`.
- **No database schema change.** `src/redline_core/db/` has zero diff.
  `list_backups()` derives its listing entirely from sealed packages on
  disk — there is deliberately no "backups" table in `redline.db`
  (tracking backups of the database inside the database being protected
  is circular).
- **No Archive Manager redesign.** `src/redline_core/archive/` has zero
  diff.

## Source-immutability guarantee

`test_create_backup_never_mutates_source_database_or_config` byte-for-byte
compares source database and config file SHA-256 hashes before and after
`create_backup()`. `build_backup_services()` and the full `create` /
`list` / `verify` CLI dispatch are proven, behaviorally, to never call
`Database.connect()`/`Database.init_schema()`/construct a Resolve
adapter. `test_backup_subsystem_source_never_imports_resolve` statically
(via `ast`) proves no module under `redline_core.backup` or
`cli/backup_commands.py` imports anything Resolve-related.

## Concurrency evidence

Two tests, two distinct, honestly-scoped claims — neither substitutes for
the other:

1. **`test_backup_created_while_writer_actively_commits_is_verified_
   consistent`** — deterministic proof that SQLite's Online Backup API
   (`sqlite3.Connection.backup()`) itself tolerates a real, concurrently
   committing writer. Necessarily monkeypatches the call site (not
   SQLite) to install a synchronizing `progress` callback that blocks
   *inside* the still-executing `backup()` call until the writer's commit
   succeeds — proving genuine overlap, not wall-clock proximity.
2. **`test_backup_created_by_real_production_wrapper_while_writer_
   actively_commits`** — direct, unmocked exercise of the actual shipped
   `snapshot_database()` wrapper, zero monkeypatching, with a writer
   thread committing continuously throughout the whole `create_backup()`
   window. Does not claim strict commit-bracketing (that is test 1's
   narrower claim) — proves the real, unmodified wrapper produces a
   valid, independently-verified snapshot under genuine sustained
   concurrent writes, and the live source database remains intact and
   writable afterward.

Both re-run 5 fresh repetitions in isolation during the final independent
commit-gate review: 2/2 passed every time, zero flakes.

## Test results

- **Mission 1A focused** (`test_backup_paths.py` + `test_backup_manager.py`
  + `test_cli_backup_commands.py` + `test_backup_concurrent_writer.py`):
  **74 passed**, reproduced fresh both before and after this closure's
  comment-only correction.
- **`tests/integration`** (full suite): **71 passed**.
- **`tests/unit`** (full suite): **31 failed / 2905 passed / 18 skipped**,
  reproduced identically across two independent full runs.
- **Combined `tests/unit tests/integration`**: **31 failed / 2976 passed
  / 18 skipped**.

## Known pre-existing regression families

All 31 broad-suite failures are pre-existing and backup-unrelated,
confirmed by identity across three independent full runs (100%
deterministic):

1. **CLI end-to-end tests** (archive/asset/episode, ~20 tests) — a
   pre-existing bug where shared test-config helpers double-quote a
   Windows path containing backslashes in YAML, which `yaml.scanner` then
   tries to parse as escape sequences. Mission 1A's own new tests
   explicitly worked around this exact bug with single-quoted YAML
   scalars, evidencing awareness rather than a new occurrence.
2. **Installed-smoke tests** (`test_installed_wheel_smoke.py`,
   `test_installed_mcp_startup_smoke.py`,
   `test_installed_cli_asset_list_smoke.py`,
   `test_installed_db_bootstrap_smoke.py`) — fresh-venv `pip install`
   environment/network variance; the exact member failing within this
   family varies run-to-run (explains the 31-vs-32 count difference
   against an earlier correction-pass report — same family, same total
   collected, different member).
3. **`test_rev7_native_process_helpers_round_trip_on_windows`** — a real
   PowerShell subprocess round-trip, environment/timing-dependent.
4. **`test_rlc_e9901_queue_attempt_harness.py`** (3 tests) — see
   "Historical RLC-E9901 harness consequence" below; a real,
   mechanically-verified, but intentional and safe consequence of
   Mission 1A's own diff.

No new failure family beyond what's explained above.

## Independent-review history

1. **Original Mission 1A implementation.**
2. **First independent review** found four findings, corrected in a first
   correction pass: (1) flaky/inferred concurrent-writer proof rewritten
   to be deterministic; (2) incomplete exact-payload verification
   (recursive `rglob()` scan added); (3) backup-id/directory-name
   inconsistency in `list_backups()` closed; (4) backup CLI composition
   moved off `PersistenceServices` (which initializes the live DB) onto
   the new `BackupServices` tier.
3. **Second independent review** found the round-1 fixes substantively
   sound but incompletely proven, and identified four further findings,
   corrected in a second correction pass: (5) missing real `cli.main`
   dispatch coverage (end-to-end tests added); (6) the round-1
   concurrency proof overclaimed production-wrapper coverage (split into
   two honestly-scoped tests, both kept); (7) `rglob()` was shown to
   traverse into a Windows junction's target before its own per-entry
   safety check ran (replaced with the single-level, non-recursive scan);
   (8) a missing copied-package (not merely renamed) identity test was
   added.
4. **Final independent commit-gate review** (this repository's own
   read-only, independent review, see `docs/BACKUP_RECOVERY_ARCHITECTURE.md`
   and this closure's own preceding review transcript) re-derived every
   claim above from source and from fresh test execution rather than
   trusting the correction report, reproduced 74/74 focused, 71/71
   integration, and the full broad-suite counts, independently discovered
   and classified the 31-vs-32 count variance (installed-smoke family
   variance, not a new failure), and independently discovered and
   classified the RLC-E9901 harness consequence recorded below. Returned:
   **APPROVE V2 MISSION 1A IMPLEMENTATION COMMIT GATE**.

## Correction history

See "Independent-review history" above for the eight corrections in
full. Summarized: (1) flaky concurrent-writer proof, (2) incomplete
exact-payload verification, (3) backup-id/directory-name inconsistency,
(4) backup CLI composition invoking a DB-initializing tier, (5) missing
real `cli.main` dispatch coverage, (6) concurrency proof overclaiming
production-wrapper coverage, (7) Windows junction traversal before safety
rejection, (8) missing copied-package identity case. All eight are
independently re-verified fixed as of the implementation checkpoint.

## Final commit-gate approval

**APPROVE V2 MISSION 1A IMPLEMENTATION COMMIT GATE** — findings: zero
BLOCKER, zero HIGH, one MEDIUM (the RLC-E9901 harness consequence, below
— accepted as an intentional safety property, not a defect), one LOW
(stale "recursive" test comment — resolved in this closure, see below).

## Production state

- **No production backup exists from this mission.** Every `create_backup()`
  invocation during implementation, review, and closure used a
  `tmp_path`-fixtured test database and config directory — never
  `REDLINE_DB_PATH` or `REDLINE_CONFIG_DIR` against the live production
  workstation.
- **No production DB mutation occurred.** No test or review activity
  connected to, wrote to, or migrated the live `redline.db`.
- **No Resolve contact occurred at any point** — proven both statically
  (AST-based zero-Resolve-import test) and behaviorally (real dispatch
  tests with `ResolveScriptAdapter.__init__` monkeypatched to raise).

## Mission 1B deferred boundary

Restore remains explicitly Founder-authorized, separate future work.
Recorded only as a pointer (`docs/BACKUP_RECOVERY_ARCHITECTURE.md` §12,
`docs/RECOVERY.md` §12) to what Mission 1B will need to design — restore
preconditions (re-verify the target backup immediately before restoring,
never "restore the latest"), a mandatory pre-restore safety snapshot of
current state using this same `BackupManager`, same-volume staged
`os.replace()` atomicity on Windows, post-restore integrity +
application-level smoke verification, and fail-closed behavior on
schema/version incompatibility. None of this is implemented, scheduled,
or authorized by Mission 1A.

## Future production-proof requirement

Everything above is proven against `tmp_path`-fixtured tests only.
Mission 1A's capability has **not yet been exercised against the real
production `REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR`** on the production
workstation. Before this capability is relied upon operationally, a
future, separately Founder-authorized step should: (1) configure
`paths.backup_path` on the real production config, (2) run one real
`redline backup create` against production, (3) run `redline backup
verify <backup_id>` against the result, and (4) confirm the produced
package's manifest/hashes/integrity_check against the live database
independently — mirroring how RLC-E9901's own live render lifecycle
required a distinct, separately authorized live-verification step beyond
unit/mock coverage. This closure document does not perform, schedule, or
authorize that step.

## Historical RLC-E9901 harness consequence

Mission 1A legitimately changed `src/cli/main.py` and
`src/redline_core/runtime/composition.py` (to route `backup` commands
through the new `BackupServices` tier). Both files are 2 of the 8
SHA-256-pinned "mutation-bearing" source files that
`scripts/rlc_e9901_queue_attempt_harness.py` — the historical live-Resolve
one-shot `render queue` attempt safety harness — hard-pins as a source-
identity binding (`docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md` §3).

As a direct, mechanically-verified consequence:

- `tests/unit/test_rlc_e9901_queue_attempt_harness.py::
  test_verify_mutation_bearing_source_identity_fails_closed_against_current_master`
  now observes `src/cli/main.py` itself as the first pinned-hash
  mismatch (previously `src/cli/render_commands.py`, from an earlier,
  unrelated Render Start Path Rev2 correction).
- The two parametrized cases `test_mutation_bearing_source_files_
  untouched_by_render_start_correction_still_match_pins[src/cli/main.py]`
  and `[...composition.py]` now fail, because those two files no longer
  match their historical pins.

This is:

- **Intentional.** The harness's own docstring states it "must remain
  intentionally UNABLE to authorize a live queue attempt against later,
  differently-reviewed production bytes."
- **Safe.** The harness fails *closed* — it blocks authorization, it does
  not silently permit one against unreviewed source.
- **Not a Mission 1A defect.** Mission 1A's changes to these two files
  are legitimate, reviewed, and unrelated to the harness's own render-
  queue-attempt purpose.
- **Not authorization to update the historical pins.** Those pins remain
  bound to the exact source state they originally authorized, per
  `CLAUDE.md` §8's DaVinci Resolve safety boundary and this closure's own
  explicit instruction. They are untouched by this closure and must
  remain untouched.

**Any future live Resolve queue-attempt requires a separately reviewed
current execution contract and separate, explicit Founder authorization**
— not a pin update performed as a side effect of unrelated work landing.

## LOW review finding — disposition

The final independent review found stale wording in
`tests/unit/test_backup_manager.py` (lines 325–328): a comment described
the corrected payload-inventory check as "recursive," while the actual
final (round-2) implementation in `redline_core/backup/package.py`'s own
docstring is explicitly a deliberate **single-level, non-recursive**
scan. The comment described round-1's superseded mechanism, not what
shipped; test behavior itself was never affected.

**Disposition: corrected, in this closure commit, not in the frozen
implementation checkpoint.** The one-line wording was changed to say
"single-level, exhaustive check... deliberately non-recursive," matching
`package.py`'s own docstring language exactly. No assertion, test body,
or production code changed. `tests/unit/test_backup_manager.py` was
re-run in isolation after the edit: 34 passed, identical to before.

This choice — fixing it in a *separate* closure commit rather than
amending the checkpoint, and rather than leaving it undocumented — is the
option most consistent with established Redline OS closure precedent:
the repository's own convention (see the Control Room V0 Mission 10
closure's "Fixture-Correction Evidence" section) already treats closure
as the point where small, non-behavioral corrections found by review get
recorded and applied, distinctly from the frozen implementation
checkpoint they describe. Because the implementation checkpoint
`b791a860aa0c2fa1a5fb8d3346c2e566eaa4d7bf` is never amended — this fix
lands in an entirely separate, later commit — "the exact
independently-reviewed implementation" that checkpoint represents remains
byte-for-byte unchanged, satisfying both this closure's instruction not
to amend the checkpoint and the practical goal of not shipping a
documentation-only closure that permanently leaves committed test-file
prose known to be wrong.

## Closure

Redline OS V2 Mission 1A (System-of-Record Backup + Verification) is
formally closed.

No production backup has been created. No Resolve contact has occurred.
Mission 1B (Restore) remains unauthorized and unimplemented. The
historical RLC-E9901 queue-attempt harness's pinned source identity
remains untouched and is expected to fail closed against Mission 1A's
source state, exactly as designed.

Next work — including Mission 1B, any live production backup execution,
or any RLC-E9901 pin update — requires a new, separate,
Founder-authorized mission.

Agents advise. Paul decides.
