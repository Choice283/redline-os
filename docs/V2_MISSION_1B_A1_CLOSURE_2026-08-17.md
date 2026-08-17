# Redline OS V2 Mission 1B-A1 Closure — HEALTHY_SOURCE Restore

## Governance

Agents advise. Paul decides. This capability exists because Mission 1A
delivered backup and independent verification but explicitly deferred
restore (`docs/V2_MISSION_1A_CLOSURE_2026-08-16.md`, "Mission 1B deferred
boundary"): a verified backup was confirmed-good evidence and provenance,
not yet a way back to a running system. Mission 1B-A1 was authorized to
close exactly that gap for the `HEALTHY_SOURCE` case only.

## Implementation checkpoint

SHA: `c1c7f3224c3d7e131b695f7be695b509417d8121`

Subject: `feat: add healthy-source system restore`

Parent: `9dbb3336daaca14e07563abfa98aef36e6cef9ed`

This is the frozen Mission 1B-A1 *implementation* checkpoint — distinct
from Mission 1B-A1 *closure*, which this document and the accompanying
`docs/CHANGELOG.md` update record separately, in their own commit,
matching the Mission 1A closure precedent (the closure record is never
squashed into or backdated onto the implementation checkpoint).

Frozen `v1.0.0` remains unchanged at
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## Mission scope

`HEALTHY_SOURCE` Restore only. The full authorized delivered scope:

- `redline backup restore-plan <backup_id>` — read-only preview
- `redline backup restore <backup_id>` — destructive, explicit-consent
  restore
- Explicit backup selection (never "latest")
- Repeated backup-ID destructive confirmation (`--confirm-backup-id`)
- Itemized quiescence attestations (`--attest-mcp-stopped`,
  `--attest-control-room-stopped`, `--attest-no-other-cli-operation`)
- Fresh target-backup re-verification immediately before restoring
- A mandatory Mission 1A pre-restore safety backup, unmodified
  `create_backup()`
- `HEALTHY_SOURCE` only

Explicitly and deliberately **not** in scope: `DEGRADED_SOURCE` recovery,
`MISSING_SOURCE` recovery, forensic capture, `backup restore-degraded`,
Mission 1B-A2, Mission 1B-B, a live production Restore drill, MCP Restore,
Control Room mutation, Resolve interaction, automatic
rollback/self-healing/resume/repair, scheduled or cloud Restore, remote
orchestration, Asset Registry activation, or a general SQLite migration
framework. See "Explicit deferred scope" below.

## Delivered capability

An operator can, on demand, against a Mission 1A sealed backup package:

1. `redline backup restore-plan <backup_id>` — read-only preview of
   whether every restore precondition would currently pass, without
   mutating anything.
2. `redline backup restore <backup_id> --confirm-backup-id <backup_id>
   --attest-mcp-stopped --attest-control-room-stopped
   --attest-no-other-cli-operation [--reason TEXT]` — perform a
   `HEALTHY_SOURCE` restore of the live database and config from the
   named backup, with a mandatory pre-restore safety backup, ordered
   post-restore verification, and no automatic rollback.

Routed through a new, fifth composition tier,
`RestoreServices`/`build_restore_services()`
(`redline_core.runtime.composition`), which — like `BackupServices` —
never opens a live `Database` connection, never calls
`Database.init_schema()` against the pipeline database, and never
constructs a Resolve adapter — proven behaviorally, including end-to-end
through real `cli.main.main()` dispatch.

## Schema compatibility

Full application-schema compatibility is checked by fingerprinting a
disposable database built fresh via the real, current
`Database.init_schema()` (the only place permitted to call it) and
comparing it structurally against the target backup's database, opened
strictly read-only:

- Exact table inventory
- Exact column fingerprint
- `PRAGMA index_xinfo` structural index semantics
- Whitespace-normalized explicit-index `CREATE INDEX` text comparison
  (also how a partial index's `WHERE` predicate identity is proven)
- Pure structural comparison for SQLite-generated autoindexes
- Fail-closed rejection if either side has a view or trigger

## SQLite safety

- `BEGIN IMMEDIATE` quiescence probe before any mutation
- The connection is closed before file replacement
- SQLite sidecar (`-journal`/`-wal`/`-shm`) gate checked both before
  database replacement and again after replacement but before any SQLite
  connection opens the restored file
- Sidecars are never deleted or recovered automatically

## Restore journal

- Restore-ID scoped
- Immutable, monotonically numbered transitions
- Canonical JSON
- SHA-256 sidecars
- `fsync`
- Collision-refusing `os.rename()` publication
- Gap-free valid-chain discovery (`discover_journal_chain()`), strictly
  read-only
- Intent/completion mutation states recorded around every live mutation
- No resume, no repair, no automatic rollback

## Filesystem replacement

- Target backup opened strictly read-only
- Staging independently verified same-volume (nested inside
  `REDLINE_DB_PATH`'s and `REDLINE_CONFIG_DIR`'s own parent directories,
  never assumed relative to `paths.backup_path`)
- Database replacement is a single `os.replace()`
- Config replacement is a restore-ID-scoped superseded path plus a
  two-step directory rename (live config → restore-ID-scoped superseded
  path, then staged config → canonical live path)
- Explicit: **DB + config Restore is NOT globally atomic.** A crash
  between the two config-rename steps leaves the live config directory
  genuinely missing, by design, with no automatic recovery — recoverable
  by hand from the restore-ID-scoped superseded config path the error
  message names.

## Post-restore verification

Exact ordering, any failure raises a typed `RestoreVerificationFailedError`
with no rollback, retry, or success marker:

0. SQLite sidecar absence
1. Exact DB/config byte identity + size against the manifest
2. `PRAGMA integrity_check`
3. Exact schema compatibility re-check
4. Config load + path safety
5. Non-mutating application-level reads
6. Target-backup preservation verification
7. `VERIFIED_SUCCESS`

## Failure model

- No automatic rollback
- No retry
- No resume
- No continuation
- No journal repair
- No automatic cleanup
- Partial state is preserved for Founder-directed recovery

## Test / review evidence

- **Focused Restore** (`test_restore_journal.py` + `test_restore_manager.py`
  + `test_restore_quiescence.py` + `test_restore_schema_fingerprint.py` +
  `test_restore_sidecar.py` + `test_restore_staging.py` +
  `test_cli_restore_commands.py`): **97 passed**.
- **Restore integration** (`tests/integration/test_restore_integration.py`):
  **3 passed**.
- **Mission 1A / affected CLI-composition regression**
  (`test_backup_manager.py` + `test_cli_backup_commands.py` +
  `test_backup_paths.py` + `test_composition.py`): **84 passed**.
- **Broader implementation-tree suite**: **3075 passed / 32 failed / 18
  skipped**.

Independent baseline comparison established:

- Zero new failure families introduced by Mission 1B-A1.
- All 32 implementation-tree failures are baseline-present (pre-existing,
  Restore-unrelated).
- Historical `RLC-E9901` harness pin failures already existed on published
  master before Mission 1B-A1 (see "Historical RLC-E9901 harness" below).
- Historical pins remain intentionally untouched.

All three focused/integration/regression figures above were re-confirmed
fresh, in isolation, immediately before the implementation checkpoint
commit (see the prior pre-commit hygiene and checkpoint-commit turns of
this mission): 97/97, 3/3, 84/84, identical counts.

## Independent review

Final verdict: **APPROVE V2 MISSION 1B-A1 IMPLEMENTATION COMMIT GATE.**

The independent reviewer independently derived the exact diff — 26 total
paths, 7 modified, 19 added, 0 deleted — matching the implementation
checkpoint's actual committed path set exactly, and independently
confirmed production safety (no live production Restore, no production
`redline.db`/config mutation, no Resolve contact).

## Accepted LOW finding — disposition

Restore schema compatibility currently compares table inventory, columns,
and full index semantics, but does not compare table-definition semantics
such as:

- `CHECK` constraints
- `FOREIGN KEY` clauses
- `WITHOUT ROWID`
- `STRICT`

The current Redline OS production schema contains none of those.

**Disposition: accepted as non-blocking. Not fixed in this closure or in
the frozen implementation checkpoint.** This is recorded as a
future-hardening item only — future schema evolution must revisit this
gap before adopting any of those four features, at which point schema
compatibility checking would need to compare table-definition semantics
as well as inventory/column/index structure. No implementation behavior
was changed during closure to address this finding.

## Historical RLC-E9901 harness

The historical `RLC-E9901` queue-attempt harness
(`scripts/rlc_e9901_queue_attempt_harness.py`) contains frozen
source-identity pins over eight "mutation-bearing" source files
(`docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md` §3), two of which —
`src/cli/main.py` and `src/redline_core/runtime/composition.py` — are
also files this mission legitimately changes.

Those tests were already fail-closed against published master **before**
Mission 1B-A1, because Mission 1A had already legitimately changed the
same two files to route `backup` commands through `BackupServices`
(recorded in `docs/V2_MISSION_1A_CLOSURE_2026-08-16.md`, "Historical
RLC-E9901 harness consequence"). Mission 1B-A1 also legitimately changes
those same two files, to route `restore-plan`/`restore` through the new
`RestoreServices` tier.

Independent baseline comparison proved Mission 1B-A1 introduced **zero new
failure families** — the harness's pinned-mismatch behavior against these
two files is a pre-existing, already-recorded, intentional fail-closed
consequence, not a new one.

**This closure does not update the historical harness pins.** Those pins
remain bound to the exact source state they originally authorized, per
`CLAUDE.md` §8's DaVinci Resolve safety boundary. Any future live Resolve
queue-attempt requires a separately reviewed current execution contract
and separate, explicit Founder authorization — not a pin update performed
as a side effect of unrelated work landing.

## Explicit deferred scope

Mission 1B-A1 does **not** provide:

- `DEGRADED_SOURCE` Restore
- `MISSING_SOURCE` Restore
- Forensic capture
- `backup restore-degraded`
- Mission 1B-A2
- Mission 1B-B
- Production Restore proof
- Live production Restore authorization
- MCP Restore
- Control Room mutation
- Resolve interaction
- Automatic rollback
- Automatic recovery
- Scheduled Restore
- Cloud/remote Restore
- Asset Registry activation
- A general SQLite migration framework

## Production-proof boundary

Mission 1B-A1 has been proven only through:

- Synthetic `tmp_path`-fixtured tests
- Disposable production-shaped copies
- Integration tests

It has **not** been used against:

- `C:\Users\pj198\RedlineOSLive\Runtime\redline.db`
- `C:\Users\pj198\RedlineOSLive\Runtime\production-config`

The trusted production backup (`b1-20260817T030606Z-8abd0a149de5`) was
never opened for write during implementation, review, or this closure. No
live Restore drill is authorized by this closure. Mission 1B-B remains a
future, separate Founder decision, as does any future live production
Restore drill against Mission 1B-A1's own capability.

## CHANGELOG / documentation disposition

`docs/CHANGELOG.md`'s existing Mission 1B-A1 entry was written before
independent review and commit; its heading and closing sentence stated
"pending review; not committed" and "no commit, tag, or push has been made
for this entry," which is no longer accurate. This closure applies the
minimum additive correction: the heading now reads "implementation
committed; independent review passed; closed locally, not yet published"
and the closing sentence now records the implementation checkpoint SHA and
that Mission 1B-A1 is closed locally pending a separate, future publication
(push) authorization. No other wording in that entry was changed, and no
implementation or test content was touched. `docs/ARCHITECTURE.md` and
`docs/RECOVERY.md` already carry Mission 1B-A1's Restore Manager row and
runbook update as part of the implementation checkpoint itself (see the
checkpoint diff) and required no further closure-time correction.

## Validation performed

- Full closure diff reviewed: only `docs/CHANGELOG.md` (minimal additive
  wording correction) and this new closure document are touched.
- Confirmed no `src/` production files changed.
- Confirmed no Restore test or behavior files changed.
- Confirmed the historical `RLC-E9901` harness file untouched.
- Confirmed no Mission 1B-A2 or Mission 1B-B content introduced.
- Because this closure is documentation-only, no full test-suite rerun was
  performed, consistent with the Mission 1A closure precedent's
  documentation-only correction pass.

## Production state

- **No production Restore has been performed.** Every `restore_plan()`/
  `restore()` invocation during implementation, review, and closure used
  `tmp_path`-fixtured, synthetic production-shaped data — never
  `REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` against the live production
  workstation.
- **No production DB or config mutation occurred.** The trusted production
  backup `b1-20260817T030606Z-8abd0a149de5` was never opened for write.
- **No Resolve contact occurred at any point** during implementation,
  review, or closure.

## Closure

Redline OS V2 Mission 1B-A1 (`HEALTHY_SOURCE` Restore) is formally closed,
locally. Implementation checkpoint `c1c7f3224c3d7e131b695f7be695b509417d8121`
has passed independent review (**APPROVE V2 MISSION 1B-A1 IMPLEMENTATION
COMMIT GATE**) and is committed on `master`, one commit ahead of
`origin/master`. This closure commit has not been pushed.

No production Restore has occurred. No Resolve contact has occurred.
Mission 1B-A2 (`DEGRADED_SOURCE`/`MISSING_SOURCE` recovery) and Mission
1B-B remain unauthorized and unimplemented. The historical `RLC-E9901`
queue-attempt harness's pinned source identity remains untouched and
continues to fail closed against both Mission 1A's and Mission 1B-A1's
source state, exactly as designed.

Next work — including publication (push) of this checkpoint and closure,
Mission 1B-A2, Mission 1B-B, any live production Restore drill, or any
`RLC-E9901` pin update — requires a new, separate, Founder-authorized step
or mission.

Agents advise. Paul decides.
