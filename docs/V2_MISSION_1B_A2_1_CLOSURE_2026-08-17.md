# Redline OS V2 Mission 1B-A2-1 Closure — Source Classification + Read-Only Recovery Planning

## Governance

Agents advise. Paul decides. This capability exists because Mission
1B-A1's own closure (`docs/V2_MISSION_1B_A1_CLOSURE_2026-08-17.md`)
recorded Mission 1B-A2 (whatever DEGRADED_SOURCE/MISSING_SOURCE recovery
Mission 1B-A1's own HEALTHY_SOURCE-only implementation motivated) as
separate, not-yet-authorized future work. Mission 1B-A2's architecture was
subsequently designed, corrected through two Control Room review passes,
and accepted. Mission 1B-A2-1 — the first of three implementation slices
that architecture decomposed into — was then separately authorized,
implemented, independently reviewed, corrected, and checkpointed. This
document closes **only** Mission 1B-A2-1.

## Mission hierarchy — read this before anything else below

```
Mission 1B-A2 — DEGRADED_SOURCE / MISSING_SOURCE Restore Recovery
  ARCHITECTURE: ACCEPTED
  IMPLEMENTATION: IN PROGRESS (one of three slices complete)

    1B-A2-1 — Source Classification + Read-Only Recovery Planning
      STATUS: COMPLETE / CHECKPOINTED (this document)

    1B-A2-2 — Degraded-Source Capture
      STATUS: NOT IMPLEMENTED / NOT AUTHORIZED

    1B-A2-3 — Recovery Execution + Journal/Evidence Integration
      STATUS: NOT IMPLEMENTED / NOT AUTHORIZED
```

**This document does not close Mission 1B-A2 as a whole.** No
degraded-source recovery *execution* capability exists anywhere in this
repository after this closure. Mission 1B-A2-2 and Mission 1B-A2-3 each
require their own, separate, future Founder authorization before any
implementation work on either may begin.

## Implementation checkpoint

SHA: `e298194e81d144358d27472d47a8bea9ce6f6706`

Subject: `feat: add degraded-source recovery planning`

Parent: `a4ce88ee55a31961229191990256f7e91db0e229`

This is the frozen Mission 1B-A2-1 *implementation* checkpoint — distinct
from Mission 1B-A2-1 *closure*, which this document and the accompanying
project-state update record separately, in their own commit, matching the
Mission 1A and Mission 1B-A1 closure precedent (the closure record is
never squashed into or backdated onto the implementation checkpoint).

Frozen `v1.0.0` remains unchanged at
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## Mission scope

Read-only source classification and recovery planning only. The full
authorized delivered scope:

- Independent DB/config source-condition classification: `HEALTHY` /
  `DEGRADED` / `MISSING`
- An orthogonal recovery-feasibility assessment: `NOT_APPLICABLE` /
  `RECOVERABLE` / `RECOVERY_BLOCKED`, with per-side blocking reasons
- Explicit target-backup selection, Mission 1A backup verification, and
  schema-compatibility checking, reusing Mission 1B-A1's own public
  primitives directly
- Read-only SQLite sidecar observation
- A quiescence *implication* that never asserts quiescence was proved
  against a database already known to be degraded
- Predictions of a future degraded-source capture and/or disposition
  requirement, without performing either
- Aggregate blocking issues and a `would_proceed` property meaning
  "architecturally eligible for a future recovery path," never "recovery
  was executed"
- CLI: `redline backup restore-recovery-plan <backup_id>`

Explicitly and deliberately **not** in scope, and not implemented anywhere
in this repository: degraded-source capture of any kind, destructive
recovery execution, sidecar disposition, wrong-type DB/config disposition,
staging, DB replacement, config replacement, a recovery journal, rollback,
resume, journal repair, or production Restore proof. `redline backup
restore-recovery` (destructive) **does not exist**. See "Explicit
non-capabilities" below.

## Delivered capability

An operator can, read-only, against a selected `backup_id`:

`redline backup restore-recovery-plan <backup_id>` — classify the live
database and required configuration independently
(`HEALTHY`/`DEGRADED`/`MISSING`), report whether a future, not-yet-
implemented Mission 1B-A2 recovery path would be architecturally eligible
for each side (`NOT_APPLICABLE`/`RECOVERABLE`/`RECOVERY_BLOCKED`), why not
if blocked, whether a future degraded-source capture or disposition would
be required, whether the selected Mission 1A backup remains valid and
schema-compatible, and what is knowable about live-database quiescence —
without creating, moving, renaming, or deleting anything.

Routed through the same `RestoreServices`/`build_restore_services()`
composition tier Mission 1B-A1's `restore-plan`/`restore` already use —
never opens a live `Database` connection, never constructs or connects a
Resolve adapter.

## Source-condition model

Per side (database, config), independently — exactly the source-side
prerequisites of Mission 1A's own, unmodified `create_backup()` contract,
neither broadened nor narrowed:

- **HEALTHY** — database: exists, safe regular file, opens as SQLite,
  passes `PRAGMA integrity_check`. Config: each of the six `REQUIRED_FILES`
  exists, is a safe regular file, and streams successfully via the same
  `fsutil.hash_stable_file()` primitive Mission 1A's own config-copy path
  uses. Config *content* validity (parseable YAML, a valid `RedlineConfig`
  schema) is deliberately never a requirement — proven directly by
  `test_classify_config_healthy_even_with_malformed_yaml_content`.
- **DEGRADED** — something exists at (or materially associated with) the
  expected path but fails a HEALTHY prerequisite.
- **MISSING** — the expected exact path does not exist. **Not an ordinal
  severity relative to DEGRADED** — no code anywhere compares these values
  for ordering (confirmed by repository-wide search during independent
  review).

**Infrastructure failure never reclassifies source health.** Classification
never calls `BackupManager.create_backup()` and infers source condition
from whichever exception it raises; it performs direct, independent,
read-only probes against the live source instead. Proven directly by
`test_classification_never_calls_create_backup` and
`test_backup_infrastructure_failure_does_not_alter_source_classification`.

## Recovery-feasibility model

A second, orthogonal per-side field. **`DEGRADED` never by itself implies
`RECOVERABLE`.** `RECOVERY_BLOCKED` cases: an unsafe filesystem object
(symlink, Windows junction, other reparse point) at the database path, the
config directory path, or any required config file — detected via the
existing `fsutil.is_unsafe_link()` primitive, **never followed, never
opened, never mutated** — and a structurally missing installation parent
directory, which requires Founder-level intervention rather than an
operator attestation. `RECOVERABLE` (predicted, not executed) cases: DB/
config missing with parent intact, DB a regular file but degraded, DB path
an ordinary directory, config directory with degraded required content,
config path an ordinary regular file.

## Safety model / architecture invariants preserved

1. Mission 1A remains authoritative for valid backups.
2. Mission 1B-A1 remains locked and unchanged — zero diff to
   `restore/manager.py`, `staging.py`, `journal.py`, `sidecar.py`,
   `quiescence.py`, `schema_fingerprint.py`, or any `backup/*.py` file.
3. Source condition and recovery feasibility are separate, independently
   reported facts.
4. Database and config classify completely independently.
5. `MISSING` is not an ordinal severity above `DEGRADED`.
6. `DEGRADED` does not imply `RECOVERABLE`.
7. Infrastructure failure does not reclassify source health.
8. Unsafe link/junction/reparse objects are never followed, opened, or
   traversed — detection uses `os.lstat()` + the existing
   `fsutil.is_unsafe_link()` only.
9. Unsafe DB/config link/reparse state is always `DEGRADED` +
   `RECOVERY_BLOCKED`.
10. Planning performs no live-source mutation of any kind.
11. Planning creates no backup.
12. Planning creates no degraded-source capture.
13. Planning creates no Restore/recovery journal.
14. Planning performs no staging, disposition, or replacement.
15. The selected recovery source is always an explicit, freshly
    re-verified Mission 1A backup — `validate_backup_id()`'s existing
    regex structurally excludes "latest" and any future degraded-source
    capture ID scheme.
16. A future recovery execution remains whole-package: the complete
    selected DB + exact-six-config backup, never a selective/partial
    restore.
17. A future degraded-source capture will be evidence, never a Mission 1A
    backup and never itself a Restore source.
18. The historical `RLC-E9901` queue-attempt harness's frozen source-
    identity pins remain untouched by this mission.

## Windows disposition gate — recorded, not closed

Before a future Mission 1B-A2-3 may rely on automatic disposition for a DB
path containing an ordinary directory, or a config path containing an
ordinary regular file, the required Windows rename/move-aside behavior
must be proven with isolated filesystem behavioral tests — no such test
exists in this repository today, and Mission 1B-A2-1 does not add one.
Every `disposition_description` this mission's classification produces
says so explicitly at runtime. **Unsafe link/junction/reparse disposition
is not, and is not intended to become, part of this gate** — that case is
`RECOVERY_BLOCKED` by accepted architecture and is not authorized by any
part of the Mission 1B-A2 design.

## Independent review history

1. **Original Mission 1B-A2-1 implementation.**
2. **Post-implementation review** (read-only, Control Room) found
   `ARCHITECTURE CONFORMS`, `READY FOR CHECKPOINT AUTHORIZATION`, zero
   BLOCKING findings, and two NON-BLOCKING automated-test-coverage
   gaps: (1) the config-side `RECOVERY_BLOCKED` branch of
   `build_recovery_plan()` had no test isolating it from the DB side; (2)
   "DB missing + orphaned sidecar present" had no dedicated test proving
   independent, non-mutating observation. Both were manually verified
   correct against the real implementation during that review before being
   recorded as coverage gaps, not defects.
3. **Final test-coverage correction** (tests-only, separately authorized)
   added exactly two regression tests closing both gaps —
   `test_recovery_plan_config_recovery_blocked_unsafe_link_isolates_config_side`
   and
   `test_recovery_plan_missing_db_with_sidecar_present_is_surfaced_independently`
   — reusing existing fixtures and the established ino/dev-scoped
   `is_unsafe_link` monkeypatch technique. Both passed on first run against
   the unmodified implementation: **no implementation defect was exposed**.
4. **Checkpoint commit review**, confirming exactly the reviewed 13-path
   diff, zero production-source drift since review, and returned:
   **READY FOR CHECKPOINT AUTHORIZATION**.

No BLOCKING finding was ever raised against Mission 1B-A2-1.

## Test evidence

- **New Mission 1B-A2-1 suite**: **49 passed** (21 classification + 17
  planning + 11 CLI — 15 original planning tests plus the 2 coverage-gap
  regressions), including dedicated proofs for config-side
  `RECOVERY_BLOCKED` → `would_proceed=False` (isolated from the DB side)
  and missing-DB-plus-orphaned-sidecar independent, byte-identical,
  non-mutating observation.
- **Locked-foundation regression** (Mission 1A / Mission 1B-A1 /
  composition): **184 passed** — reproduced identically across the
  implementation, post-implementation review, coverage-correction, and
  checkpoint-commit passes. Zero change at any point.
- **Combined post-checkpoint focused validation**: **233 passed**.
- **Broader implementation-tree suite** (established during the
  implementation pass, not re-run in full for every subsequent review
  since the working tree had not materially changed): **3122 passed / 32
  failed / 18 skipped** — the exact same 32 pre-existing failure families
  already documented in the Mission 1A and Mission 1B-A1 closure records
  (CLI end-to-end Windows-path/YAML fixture bug, fresh-venv installed-smoke
  variance, one native-process-helper timing test, and the historical
  RLC-E9901 harness pin consequence). **Zero new failure families.** These
  32 failures are not caused by, and are not attributable to, Mission
  1B-A2-1.
- `git diff --check`: clean at every stage of implementation, review,
  correction, and checkpoint.

## Historical RLC-E9901 harness

Mission 1B-A2-1 legitimately changed `src/cli/main.py` (registers the new
`restore-recovery-plan` action and dispatch branch) — one of the eight
SHA-256-pinned "mutation-bearing" source files
`scripts/rlc_e9901_queue_attempt_harness.py` hard-pins. That file's pin was
already stale against published master after Mission 1A's and Mission
1B-A1's own prior legitimate changes to it (recorded in both of their own
closure documents); Mission 1B-A2-1's additional, legitimate change to the
same file is the same already-documented, intentional, fail-closed
consequence, not a new one. `src/redline_core/runtime/composition.py` was
**not** touched by this mission and continues to show only the
pre-existing Mission 1A/1B-A1 mismatch. **This closure does not update the
historical harness pins.** Any future live Resolve queue-attempt requires
a separately reviewed current execution contract and separate, explicit
Founder authorization — not a pin update performed as a side effect of
unrelated work landing.

## Production-proof status

Mission 1B-A2-1 is **implemented, tested, and checkpointed**. It is a
strictly read-only planning/classification capability. It does **not**
establish, and this closure does not claim:

- Production degraded-source recovery proof
- Production Restore proof
- Mission 1B-A2 execution proof of any kind

Every test used only `tmp_path`-scoped, synthetic fixtures; no test in
this mission ever opened `REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR`, and no
production path was touched at any point during implementation, review,
correction, or checkpoint.

**Mission 1B-A1's own production-proof status is unchanged and is not
altered by this closure: it remains explicitly NOT PRODUCTION-RESTORE-
PROVEN.** Nothing in Mission 1B-A2-1 changes that record.

## Next mission boundary

The next implementation slice this architecture identifies is **Mission
1B-A2-2 — Degraded-Source Capture**. **This closure does not authorize
it.** Mission 1B-A2-2 (and, after it, Mission 1B-A2-3) each require their
own separate, explicit Founder authorization before any implementation
work begins, exactly as Mission 1B-A2-1 itself did.

## Closure

Redline OS V2 Mission 1B-A2-1 (Source Classification + Read-Only Recovery
Planning) is formally closed, locally. Implementation checkpoint
`e298194e81d144358d27472d47a8bea9ce6f6706` has been independently reviewed
(zero blocking findings) and checkpointed on `master`, one commit ahead of
`origin/master`. This closure has not yet been committed.

Mission 1B-A2 as a whole remains **in progress** — only its first of three
implementation slices is complete. No degraded-source recovery execution
capability exists anywhere in this repository. Mission 1B-A2-2, Mission
1B-A2-3, and Mission 1B-B all remain unauthorized and unimplemented. The
historical `RLC-E9901` queue-attempt harness's pinned source identity
remains untouched and continues to fail closed against Mission 1A's,
Mission 1B-A1's, and now Mission 1B-A2-1's source state, exactly as
designed.

Next work — including publication (push) of this checkpoint and closure,
Mission 1B-A2-2, Mission 1B-A2-3, Mission 1B-B, any live production Restore
or recovery drill, or any `RLC-E9901` pin update — requires a new, separate,
Founder-authorized step or mission.

Agents advise. Paul decides.
