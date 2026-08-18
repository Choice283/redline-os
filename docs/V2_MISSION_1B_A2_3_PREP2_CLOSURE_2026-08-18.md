# Redline OS V2 Mission 1B-A2-3-Prep2 Closure — Shared Sidecar Safety Classification + Recovery-Planning Hardening

## Governance

Agents advise. Paul decides. This preparatory mission exists because the
Mission 1B-A2-3 Control Room Decision Register / Final Architecture
Ratification concluded **NOT READY FOR A2-3 IMPLEMENTATION AUTHORIZATION**
and identified one remaining architecture blocker: no reusable,
authoritative primitive existed anywhere in this repository capable of
distinguishing a missing, safe-regular, wrong-type, or unsafe recognized
SQLite sidecar. Mission 1B-A2-1's own `sidecars_present` surface was
presence-only and `Path.exists()`-based; Mission 1B-A2-2 had already
independently proved that exact observation insufficient for its own
capture purposes (a dangling unsafe sidecar is invisible to
`Path.exists()`) and built its own embedded, capture-specific fix. This
document closes **only** Mission 1B-A2-3-Prep2.

## Mission hierarchy — read this before anything else below

```
Mission 1B-A2 — DEGRADED_SOURCE / MISSING_SOURCE Recovery
  ARCHITECTURE: ACCEPTED
  IMPLEMENTATION: IN PROGRESS

    1B-A2-1 — Source Classification + Read-Only Recovery Planning
      STATUS: PUBLISHED (sidecar classification hardened by this mission)

    1B-A2-2 — Degraded-Source Capture
      STATUS: COMPLETE / CHECKPOINTED
      NOT PRODUCTION-CAPTURE-PROVEN
      (sidecar observation now consumes the shared classifier; published
       capture semantics unchanged)

    1B-A2-3-Prep — Windows Filesystem Disposition Behavioral Proof
      STATUS: COMPLETE / CHECKPOINTED / PUBLISHED

    1B-A2-3-Prep2 — Shared Sidecar Safety Classification +
    Recovery-Planning Hardening
      STATUS: COMPLETE / CHECKPOINTED (this document)

    1B-A2-3 — Recovery Execution + Journal/Evidence Integration
      STATUS: NOT IMPLEMENTED / NOT AUTHORIZED
```

**This document does not close Mission 1B-A2 as a whole, and does not
authorize Mission 1B-A2-3.** No disposition, recovery execution, or
destructive CLI capability of any kind exists anywhere in this repository
after this closure.

## Implementation checkpoint

SHA: `0e3a77028490b97fafdb608c42ff14ea989779f2`

Subject: `feat: add shared sidecar safety classification`

Parent: `6d928d831cdc45c9bb5082a4faec9cf4ba174e6c`

This is the frozen Mission 1B-A2-3-Prep2 *implementation* checkpoint —
distinct from Mission 1B-A2-3-Prep2 *closure*, which this document and the
accompanying `docs/CHANGELOG.md` update record separately, in their own
future commit, matching the Mission 1A, Mission 1B-A1, Mission 1B-A2-1,
Mission 1B-A2-2, and Mission 1B-A2-3-Prep closure precedent.

Frozen `v1.0.0` remains unchanged at
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## Mission scope

One new module, three narrow additive/refactor edits, and one new test
file:

```
src/redline_core/restore/sidecar_classification.py    NEW
src/redline_core/restore/recovery_models.py            additive field
src/redline_core/restore/recovery_planning.py          additive integration
src/redline_core/restore/capture_package.py             refactor only
tests/unit/test_sidecar_classification.py               NEW (21 tests)
```

**No destructive recovery, disposition, authorization, execution, or
journal code was added anywhere in this repository.** `journal.py`,
`manager.py`, `staging.py`, `sidecar.py` (Mission 1B-A1's locked
presence-only sidecar gate), `quiescence.py`, `schema_fingerprint.py`,
every CLI routing file, all Mission 1A backup source, and the historical
`RLC-E9901` harness/pins were **not modified** — verified directly
(`git diff --stat`) against each, zero diff on every one.

## Shared sidecar classification

`redline_core.restore.sidecar_classification` is now the **one**
authoritative, read-only classifier for a recognized SQLite sidecar path
(`-journal`/`-wal`/`-shm`), replacing what were two independent, partial
`lstat` dispatches (Mission 1B-A2-2's own embedded capture-sidecar logic,
and the gap this left in Mission 1B-A2-1 planning) with a single shared
source of truth.

`SidecarCondition`: `MISSING`, `SAFE_REGULAR`, `WRONG_TYPE`, `UNSAFE`.

Classification:

- uses `os.lstat()` exclusively — never `Path.exists()`/`Path.is_file()`,
  both of which follow symlinks/junctions and are blind to a dangling
  reparse object;
- reuses the repository's one unsafe-object contract
  (`redline_core.fsutil.is_unsafe_link()`) unmodified;
- never follows an unsafe target, never opens or reads any target's
  contents, never moves, renames, or deletes anything;
- is strictly read-only and mutates nothing.

Shared consumers: Mission 1B-A2-1 recovery planning
(`recovery_planning.build_recovery_plan()`) and Mission 1B-A2-2
degraded-source capture (`capture_package.capture_sidecars()`). There is
now exactly one classification decision, not multiple independent copies.

## Ratified sidecar policy

```
SAFE_REGULAR     → recovery remains architecturally recoverable;
                    a future, not-yet-implemented Mission 1B-A2-3
                    disposition step would still be required to move it
                    aside before replacement.
WRONG_TYPE       → RECOVERY_BLOCKED
UNSAFE           → RECOVERY_BLOCKED
MISSING          → no disposition required
```

`RECOVERY_BLOCKED` cannot be overridden by any acknowledgement or CLI
flag — none exists anywhere in this repository for it, and none is added
by this mission.

## A2-1 recovery planning hardening

`RecoveryPlanResult` preserves its existing `sidecars_present` field
unchanged (still `Path.exists()`-based presence only, via the locked
`redline_core.restore.sidecar.find_present_sidecars()`, for backward
compatibility with existing callers) and adds one new field,
`sidecar_assessments: tuple[SidecarAssessment, ...]` — the authoritative,
`os.lstat()`-based classification of every recognized sidecar suffix,
always exactly `len(SIDECAR_SUFFIXES)` entries.

`build_recovery_plan()` now appends a `"sidecar recovery blocked: ..."`
entry to `blocking_issues` for every `WRONG_TYPE`/`UNSAFE` sidecar
assessment:

- a `SAFE_REGULAR` sidecar never blocks recovery by itself;
- a `WRONG_TYPE` sidecar blocks (`would_proceed` becomes `False`);
- an `UNSAFE` sidecar blocks (`would_proceed` becomes `False`);
- a `MISSING` sidecar never blocks;
- database existence and sidecar safety remain independent facts — a
  sidecar's classification is computed purely from its own path and never
  reads or depends on `db_path` itself.

Mission 1B-A2-1 remains strictly **read-only**. No disposition,
authorization, or execution capability was added. `src/cli/
recovery_planning_commands.py` required no edit: it builds its output by
naming specific fields explicitly (never `dataclasses.asdict()`), so the
new field is inert there while the new blocking-issue text automatically
surfaces through the CLI's existing `blocking_issues` printing.

## A2-2 capture semantic preservation

`capture_package.capture_sidecars()` now consumes
`sidecar_classification.classify_sidecars()` as its outer MISSING-vs-not
gate; every non-`MISSING` assessment is still handed to the existing,
**unmodified** `capture_regular_file_item()` dispatch exactly as before.
Published capture outcomes are unchanged:

```
SAFE_REGULAR → existing best-effort capture path (CAPTURED_VERIFIED where
                successfully captured, matching all prior behavior)
WRONG_TYPE    → WRONG_TYPE_RECORDED
UNSAFE        → UNSAFE_OBJECT_RECORDED
MISSING       → no sidecar capture record (unchanged)
```

`capture_regular_file_item()`, `capture_database_slot()`, and
`capture_config_slot()` were **not touched** — only `capture_sidecars()`'s
own inline pre-check was replaced. Capture remains evidence only,
programmatic-only (no CLI), never a Mission 1A backup, never a Restore
source, and non-destructive — unchanged by this mission.

## Dangling / wrong-type sidecar evidence

**Dangling unsafe sidecar** (the specific defect this mission exists to
close): a recognized sidecar path that is never actually created on disk
— `Path.exists()`-style presence observation would report it absent
throughout, exactly the blindness Mission 1B-A2-2 had already
independently proved and fixed for its own capture purposes — is still
seen by the shared `os.lstat()`-based classifier (via the repository's
established unsafe-object simulation convention), classified `UNSAFE`,
and results in `RECOVERY_BLOCKED` recovery planning. No source bytes are
ever read, and no mutation occurs. Proven by
`test_classify_sidecar_unsafe_dangling_never_created_on_disk` and
`test_recovery_plan_dangling_unsafe_sidecar_blocks_and_reads_no_bytes`
(`tests/unit/test_sidecar_classification.py`).

**Wrong-type sidecar**: an ordinary directory placed at a recognized
sidecar path (with a stray file inside, proving no recursive traversal)
classifies `WRONG_TYPE`, results in `RECOVERY_BLOCKED` recovery planning,
and is recorded `WRONG_TYPE_RECORDED` by Mission 1B-A2-2 capture. No
automatic disposition semantics of any kind are invented anywhere in this
mission. Proven by `test_classify_sidecar_wrong_type_directory`,
`test_recovery_plan_wrong_type_sidecar_blocks`, and
`test_capture_sidecars_wrong_type_directory_recorded`.

## DB-missing independence

A missing live database path never hides or absorbs a sidecar's own
condition. DB path `MISSING` combined with an unsafe/dangling sidecar
still independently classifies that sidecar `UNSAFE` and still blocks
recovery (`would_proceed` is `False`), while the database side
independently and correctly reports `MISSING`/`RECOVERABLE` — the two
facts never mask one another, exactly matching Mission 1B-A2-2's own
already-proven invariant for capture. Proven by
`test_classify_sidecar_independent_of_db_existence` and
`test_recovery_plan_db_missing_plus_unsafe_sidecar_still_blocks`.

## Cannot-inspect fail-closed semantics

An `os.lstat()` failure other than a genuine `FileNotFoundError` (e.g.
permission denied) means the sidecar object's real type cannot be safely
determined. This is conservatively folded into the `UNSAFE` bucket rather
than guessed at as `SAFE_REGULAR` or `WRONG_TYPE`, mirroring
`recovery_classification._cannot_inspect_assessment()`'s identical,
already-established fail-closed doctrine for the database and config
sides.

This is stated precisely as an **operational fail-closed execution
policy for recovery planning**, not a factual claim that every such
inspection failure literally proves a symlink/junction/reparse object
exists. The governing rule is: the sidecar object's condition cannot be
safely determined → do not guess → `RECOVERY_BLOCKED`. Proven by
`test_classify_sidecar_cannot_inspect_folds_into_unsafe`.

## Locked surfaces — untouched

Verified zero diff, directly, against each of the following:

```
src/redline_core/restore/journal.py
src/redline_core/restore/manager.py
src/redline_core/restore/staging.py
src/redline_core/restore/sidecar.py
src/redline_core/restore/quiescence.py
src/redline_core/restore/schema_fingerprint.py
src/cli/main.py
src/cli/backup_commands.py
src/cli/restore_commands.py
src/cli/recovery_planning_commands.py
src/redline_core/runtime/composition.py
scripts/rlc_e9901_queue_attempt_harness.py
all Mission 1A backup source (src/redline_core/backup/)
```

Mission 1B-A2-3 itself remains unimplemented: no
`recovery_execution.py`, `recovery_disposition.py`,
`recovery_authorization.py`, `recovery_stability.py`, or destructive
`restore-recovery` CLI command exists anywhere in this repository.

## Validation evidence

- **Mission 1B-A2-3-Prep2 focused suite**: **21 passed**
  (`tests/unit/test_sidecar_classification.py`).
- **Windows disposition proof**: **12 passed** — unchanged.
- **A2-2 regression**: **67 passed** — unchanged (published capture
  outcomes byte-for-byte identical to before this mission).
- **A2-1 regression**: **49 passed** — unchanged.
- **Locked Mission 1A / Mission 1B-A1 regression**: **184 passed** —
  unchanged (Focused Restore 97 + Restore integration 3 + Mission
  1A/CLI-composition 84).
- **Combined**: **333 passed**, 0 failed.
- `git diff --check`: clean at every stage (pre-stage, staged, and
  post-commit).
- All gates were reproduced identically before staging, on the staged
  diff, and again after the checkpoint commit.
- Blocking findings: **NONE**.

## A2-3 readiness boundary / remaining decisions

This mission closes the **sole** architecture blocker the Mission 1B-A2-3
Control Room Decision Register / Final Architecture Ratification
identified: the absence of one reusable, authoritative sidecar
safety-classification primitive. **This closure does not itself make
Mission 1B-A2-3 ready for implementation.** Before implementation
authorization, Control Room intends one final, read-only,
implementation-readiness review.

Two narrow, previously-identified edits to locked Mission 1B-A1 files
remain expected future work, requiring their own separate,
explicit Founder mutation authorization — these are controlled
*permission* decisions, not unresolved architecture questions:

- **`journal.py`**: future recovery-specific journal schema/attempt-kind
  metadata should be optional/opt-in, so that existing healthy Mission
  1B-A1 `RestoreJournal` calls preserve their existing payload shape
  unless Control Room separately and explicitly authorizes otherwise.
- **`manager.py`**: a future extraction of `RestoreManager.
  _verify_restore()`'s reusable verification steps into public,
  module-level primitives must preserve Mission 1B-A1's **observable
  behavior** exactly, proven by the locked 184-test regression gate —
  not merely "byte-identical source," which is not the correct
  requirement for a refactor.

Neither edit was made or scheduled by this mission. `journal.py` and
`manager.py` remain byte-identical to the published baseline.

## Production-proof status

Mission 1B-A2-3-Prep2 is **implemented, tested, and checkpointed**. It
establishes **no production recovery-execution proof of any kind** —
every test used only `tmp_path`-scoped, synthetic fixtures;
`REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` were never touched, and no live
Resolve process was ever contacted.

**Mission 1B-A1's production-proof status is unchanged: it remains
explicitly NOT PRODUCTION-RESTORE-PROVEN. Mission 1B-A2-2's
production-proof status is unchanged: it remains explicitly NOT
PRODUCTION-CAPTURE-PROVEN.** Nothing in this closure alters either
record.

## Next mission boundary

The next step this architecture identifies is Control Room's own final,
read-only Mission 1B-A2-3 implementation-readiness review, followed —
only if that review and separate Founder authorization both grant it —
by **Mission 1B-A2-3 — Recovery Execution + Journal/Evidence
Integration**. **This closure does not authorize any of that.** Mission
1B-A2-3 requires its own, separate, explicit Founder authorization —
including explicit authorization for the two narrow `journal.py`/
`manager.py` edits named above — before any implementation work begins.

## Closure

Redline OS V2 Mission 1B-A2-3-Prep2 (Shared Sidecar Safety Classification
+ Recovery-Planning Hardening) is formally closed, locally. Implementation
checkpoint `0e3a77028490b97fafdb608c42ff14ea989779f2` has been reviewed
and accepted; this closure document and the accompanying
`docs/CHANGELOG.md` update record its closure. This closure has not yet
been committed.

Mission 1B-A2 as a whole remains **in progress**. No degraded-source
recovery *execution* capability exists anywhere in this repository.
Mission 1B-A2-3 and Mission 1B-B remain unauthorized and unimplemented.
The historical `RLC-E9901` queue-attempt harness's pinned source identity
remains untouched.

Next work — including the closure commit itself, publication (push) of
this checkpoint and closure, Control Room's own final A2-3
implementation-readiness review, Mission 1B-A2-3, Mission 1B-B, any live
production degraded-source capture, any live production Restore or
recovery drill, or any `RLC-E9901` pin update — requires a new, separate,
Founder-authorized step or mission.

Agents advise. Paul decides.
