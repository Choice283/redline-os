# Redline OS V2 Mission 1B-A2-3 Closure — Recovery Execution + Journal/Evidence Integration

## Governance

Agents advise. Paul decides. This document records the local implementation
checkpoint closure of Mission 1B-A2-3. It does **not** record publication —
see "Publication boundary" below.

## Mission hierarchy — read this before anything else below

```
Mission 1B-A2 — DEGRADED_SOURCE / MISSING_SOURCE Recovery
  ARCHITECTURE: ACCEPTED
  IMPLEMENTATION: IN PROGRESS

    1B-A2-1 — Source Classification + Read-Only Recovery Planning
      STATUS: PUBLISHED

    1B-A2-2 — Degraded-Source Capture
      STATUS: COMPLETE / CHECKPOINTED / PUBLISHED
      NOT PRODUCTION-CAPTURE-PROVEN

    1B-A2-3-Prep — Windows Filesystem Disposition Behavioral Proof
      STATUS: COMPLETE / CHECKPOINTED / PUBLISHED

    1B-A2-3-Prep2 — Shared Sidecar Safety Classification +
    Recovery-Planning Hardening
      STATUS: COMPLETE / CHECKPOINTED / PUBLISHED

    1B-A2-3 — Recovery Execution + Journal/Evidence Integration
      STATUS: IMPLEMENTED
      CHECKPOINTED LOCALLY
      NOT PUBLISHED
      NOT CI-VERIFIED FOR CHECKPOINT HEAD
      (this document)
```

**This document does not authorize publication.** It closes the local
implementation checkpoint only. Closure commit, publication push, and
exact-head CI verification each require their own separate, explicit
Founder authorization, per the standing mission-lifecycle discipline.

## Baseline

Starting published baseline (repository state before this mission's
implementation began, and the exact preflight this mission's authorization
was granted against):

```
48cc08a389ab6603f5e4f6b2d381274c0c6fcd51
```

Implementation checkpoint (this closure records):

```
3445063437b084ae235b21ee3cd0fbe2af5d69ce
```

Frozen `v1.0.0` remains unchanged at:

```
a41eb57012fbd80ae1be536d8e91ab74f459bc32
```

## Mission scope

Mission 1B-A2-3 adds the first live-mutation capability anywhere in the
Mission 1B-A2 family: `redline backup restore-recovery <backup_id>`,
DESTRUCTIVE, gated by an escalated `RecoveryAuthorization`. Every prior
Mission 1B-A2 step (A2-1 classification/planning, A2-2 capture,
A2-3-Prep/Prep2 behavioral proof and shared classification) remained
strictly read-only or evidence-only.

## Architecture summary — the implemented safety chain

```
RecoveryAuthorization
  -> fresh recovery-plan validation
  -> mandatory fresh degraded-source capture
  -> capture reverification (exact same capture_id)
  -> CHANGED_DURING_CAPTURE hard-stop check
  -> fresh source/sidecar reclassification
  -> PRE_MUTATION_STABILITY
  -> quiescence (proved probe, or not-applicable)
  -> mutation-bound disposition stability check (immediately before each rename)
  -> disposition (fixed order: database -> config -> -journal -> -wal -> -shm)
  -> FINAL_STABILITY
  -> existing sidecar pre-check (reused, unmodified)
  -> mutation-bound DB/config stability checks (immediately before each replacement step)
  -> staging/replacement (reused, unmodified)
  -> shared Restore verification (verify_restore(), STEP 0-6)
  -> terminal journal state
```

Recorded explicitly, as the mission's own governing safety doctrine:

- **`RECOVERY_BLOCKED` is absolutely non-overridable.** No field on
  `RecoveryAuthorization`, and no CLI flag anywhere in this repository, can
  bypass it — checked twice: once at initial recovery-plan validation
  (before any capture), and once at fresh post-capture source/sidecar
  reclassification.
- **Every attempt creates a fresh capture.** `build_degraded_source_capture()`
  (Mission 1B-A2-2, unmodified) is called unconditionally on every attempt
  that passes initial validation.
- **No pre-existing capture is ever an execution input.** There is no
  `--capture-id`/`--confirm-capture-id` anywhere in `execute_recovery()`'s
  signature or the CLI parser — verified directly by signature introspection
  and by an argparse-rejection test.
- **`CHANGED_DURING_CAPTURE` hard-stops unconditionally.** Any capture item
  (database, the config-directory container when abnormal, any required
  config file, any sidecar) recording this outcome is a terminal hard stop
  before reclassification is ever attempted — it never reaches disposition
  and is never part of any evidence-preservation disposition trigger.
- **`UNREADABLE` handling is fingerprint/evidence-sufficiency aware.** A
  partial-read `sha256` is never treated as a full-file hash. An `UNREADABLE`
  item with a complete `StatFingerprint` is compared type/safety/size/
  mtime_ns/ino/dev only; one with no fingerprint evidence at all is
  insufficient evidence and always a `PRE_MUTATION_STABILITY` mismatch —
  never reaching disposition.
- **Unreadable-database evidence-preservation disposition.** A regular-file
  database this attempt's fresh capture recorded `UNREADABLE` (with
  sufficient fingerprint evidence to pass stability) is moved aside rather
  than silently overwritten by the ordinary database-replacement step —
  preserving the last surviving evidence of a file capture itself could not
  read a single byte of.
- **`SAFE_REGULAR` sidecar disposition.** A sidecar the fresh, post-capture
  reclassification finds `SAFE_REGULAR` is disposed (moved aside, restore-
  ID-scoped superseded name) before replacement.
- **`WRONG_TYPE`/`UNSAFE` sidecars block.** Either condition on any
  recognized sidecar suffix causes `SOURCE_RECLASSIFICATION_BLOCKED` —
  disposition is never attempted for either.
- **No retry / rollback / resume / overwrite fallback / delete fallback**
  exists anywhere in this mission's code. Every failure mode raises a typed
  exception and stops; already-completed mutations (a disposition that
  already succeeded) remain journaled and preserved on disk for manual
  inspection.

See `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §16 for the complete architecture
record, including the disposition trigger conditions, the mutation-bound
stability recheck contract, and the config-replacement rename-aside/vacancy
generalization.

## CLI

```
redline backup restore-recovery <backup_id> --confirm-backup-id <backup_id> \
    --attest-mcp-stopped --attest-control-room-stopped --attest-no-other-cli-operation \
    --attest-disposition-understood --attest-no-automatic-rollback \
    [--reason TEXT]
```

Registered onto the *same* `backup` subparsers object
(`cli.recovery_execution_commands.register_parser()`), dispatched by
`cli.main` through the identical `RestoreServices` composition tier
`restore-plan`/`restore`/`restore-recovery-plan` already use. **No
`--capture-id`/`--confirm-capture-id` flag exists anywhere** — confirmed by
both a signature-introspection test and an argparse-rejection test.

## Journal

- **One `RestoreJournal` authority.** No parallel recovery journal exists
  anywhere in this repository.
- **Ordinary Restore's payload shape is preserved exactly.** The locked
  top-level shape (`restore_id`, `backup_id`, `sequence`, `state`,
  `timestamp`, `detail`) is unchanged for every pre-existing call site —
  proven by `test_ordinary_restore_journal_emits_no_attempt_kind_key`.
- **`attempt_kind` is opt-in and recovery-only.** `RestoreJournal.create()`
  gained one new, default-`None` constructor parameter; `None` (every
  ordinary Restore call, unmodified) emits no `attempt_kind` key at all. A
  recovery attempt passes `attempt_kind="recovery"`, included verbatim in
  every transition that journal instance records.
- **Exact enum delta, verified by direct diff against HEAD `48cc08a`:**
  **27 existing states → 50 current states, 23 additive A2-3 states, zero
  removed, zero renamed.**
- **Three of the 23 are explicitly accepted observability refinements**,
  not literal members of the compact ratified state-family list, each
  added only to durably record behavior the architecture requires
  unconditionally elsewhere in its own text:
  - `RECOVERY_PLAN_VALIDATED` / `RECOVERY_PLAN_BLOCKED` — record the fresh
    recovery-plan validation step's own outcome, mirroring the
    INTENT/BLOCKED pattern the architecture explicitly names for the
    structurally identical, later `SOURCE_RECLASSIFICATION_BLOCKED` check.
  - `CAPTURE_CHANGED_DURING_CAPTURE` — records the CHANGED_DURING_CAPTURE
    hard stop the architecture repeats as an unconditional, safety-critical
    terminal condition; without a distinct state, a human reading the
    journal after this hard stop would see only an unexplained gap.

  Control Room reviewed and explicitly accepted all three as necessary
  observability refinements within the ratified architecture, not
  unauthorized scope expansion.

The remaining 20 of the 23 map one-to-one onto the ratified state-family
list: recovery initiation (1), capture (3), capture reverification (3),
fresh reclassification (3), pre-mutation stability (3), quiescence-not-
applicable (1), disposition (3), final stability (3).

## Shared Restore verification authority

`RestoreManager._verify_restore()`'s exact STEP 0-6 body (Mission 1B-A1)
was extracted, behavior-preserving, into a new module-level function,
`verification.verify_restore()`. `RestoreManager._verify_restore()` is now
a thin wrapper around it — proven to be a real delegation, not merely
textually similar, by a test that makes the shared function raise and
confirms the failure propagates through `RestoreManager.restore()`.
Mission 1B-A2-3's `execute_recovery()` calls the identical function.
**Ordinary Restore and A2-3 recovery now share exactly one, behavior-
preserving verification implementation** — never a duplicated or
approximated copy. Mission 1B-A1's own observable behavior is unchanged,
proven by the locked historical regression gate re-running identically.

## Implementation inventory — exact 21 checkpoint paths

Checkpoint commit `3445063437b084ae235b21ee3cd0fbe2af5d69ce`, parent
`48cc08a389ab6603f5e4f6b2d381274c0c6fcd51`:

```
M  docs/BACKUP_RECOVERY_ARCHITECTURE.md
M  src/cli/backup_commands.py
M  src/cli/main.py
A  src/cli/recovery_execution_commands.py
M  src/redline_core/restore/capture_manager.py
M  src/redline_core/restore/exceptions.py
M  src/redline_core/restore/journal.py
M  src/redline_core/restore/manager.py
A  src/redline_core/restore/recovery_disposition.py
A  src/redline_core/restore/recovery_execution.py
M  src/redline_core/restore/recovery_models.py
A  src/redline_core/restore/recovery_stability.py
A  src/redline_core/restore/verification.py
A  tests/unit/test_cli_recovery_execution_commands.py
M  tests/unit/test_cli_recovery_planning_commands.py
A  tests/unit/test_recovery_disposition.py
A  tests/unit/test_recovery_execution.py
A  tests/unit/test_recovery_models.py
A  tests/unit/test_recovery_stability.py
M  tests/unit/test_restore_journal.py
A  tests/unit/test_verification.py
```

`src/cli/main.py` was accepted by Control Room as minimum necessary CLI
dispatch plumbing after exact diff review (two documentation/comment
additions, one import, one dispatch-branch extension — nothing else) and
explicit `-m workstation` verification (§ below) confirming the file's
already-documented RLC-E9901 pin drift (§14.11 precedent) was neither
newly introduced nor concealed by this change.

## Historical regression accounting

Historical locked recovery baseline at pristine HEAD `48cc08a`, verified
via `pytest --collect-only` against an independent, detached `git
worktree` checked out exactly at that commit:

```
333 nodes
```

Current comparison set (identical 20-file locked-baseline set, current
working state at checkpoint):

```
339 nodes
```

**339 is not "the 333 baseline" — it is 333 plus an explicitly accounted
delta:**

- 1 obsolete CLI test removed with explicit Control Room authorization
  (`test_cli_recovery_planning_commands.py::
  test_no_destructive_restore_recovery_action_registered` — its own
  assertion had become a false positive once `restore-recovery` became a
  real registered action; see "Process deviations" below).
- 7 replacement/additive nodes added (3 replacement tests in
  `test_cli_recovery_planning_commands.py` proving the new intended
  boundary — registered, cannot parse without `--confirm-backup-id`,
  cannot execute without full authorization, no unapproved alternate
  command — plus 4 additive `attempt_kind`/journal-backward-compatibility
  tests in `test_restore_journal.py`).
- Net **+6** (333 − 1 + 7 = 339).

No other historical node IDs were removed or renamed anywhere in the
20-file locked set (only these two files differ from HEAD at all — `git
diff --stat HEAD` confirms zero diff on the other 18). No historical
parametrized cases were removed (neither changed file contains
`@pytest.mark.parametrize`, at HEAD or now).

## Validation evidence

All runs below used the repository-required Python 3.11.9 interpreter
(`C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`).

- **CLI focused** (`test_cli_recovery_planning_commands.py` +
  `test_cli_recovery_execution_commands.py` + `test_cli_restore_commands.py`
  + `test_cli_backup_commands.py`): **52 passed, 0 failed**.
- **A2-3** (`test_recovery_stability.py`, `test_recovery_disposition.py`,
  `test_recovery_models.py`, `test_verification.py`,
  `test_recovery_execution.py`, `test_cli_recovery_execution_commands.py`):
  **78 passed, 0 failed**.
- **Portable** (`tests/unit` + `tests/integration`, `-m "not workstation"`,
  solo run, authoritative Python 3.11.9 interpreter): **3302 passed, 18
  skipped, 42 deselected, 0 failed**.
- **Workstation** (`tests/unit -m workstation`): **42 passed, 0 failed**
  (expected collection count matched exactly), including the parametrized
  pin-drift proof pair that positively confirms `src/cli/main.py`'s
  drift was detected, not hidden.
- **`git diff --check`**: clean at every stage (pre-stage, staged, and
  post-commit).

## Environmental/transient evidence

Two earlier, non-authoritative runs — one under concurrent execution
(two test suites racing to build a wheel into the same shared `build/`
directory), one under the wrong default interpreter session before the
repository-required Python 3.11.9 was selected explicitly — each produced
exactly one unrelated, environment-specific failure: a Windows file-
collision during a concurrently-built wheel (`WinError 183`), and a
transient PyPI connection reset during an installed-wheel-smoke test's own
`pip wheel` build. Neither failure touched anything in `redline_core.restore`,
`redline_core.backup`, or any A2-3 code path. The final, solo,
authoritative Python 3.11.9 run (recorded above) was clean. **These
transient artifacts are not represented as implementation regressions.**

## Process deviations

Recorded transparently, not hidden:

1. `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §16 was requested before
   production code, per the original mission authorization's stated
   preference. It was in fact written after implementation, once building
   the actual code clarified exact semantics the compact architecture
   description alone had not fully specified (see item 2 below for one
   concrete example). This chronology is not undone or hidden; §16
   accurately documents the architecture as ratified and as built.
2. `src/cli/main.py` was not on the mission's initial literal expected-
   modified-file list, but proved necessary as CLI dispatch plumbing for
   the explicitly authorized `redline backup restore-recovery` command.
   Control Room separately reviewed the exact, bounded diff and accepted
   it before checkpoint authorization.
3. The obsolete `test_no_destructive_restore_recovery_action_registered`
   test initially continued to pass after `restore-recovery` became a
   real registered action — but for the wrong reason (a `SystemExit` from
   argparse's required `--confirm-backup-id`, not from an unrecognized
   subcommand). This false-positive contract was identified and corrected
   before checkpoint acceptance (see "Historical regression accounting").
4. An early report of "18 new journal states" was a reporting miscount —
   all 23 names were in fact listed correctly at the time, just
   mis-totaled. An exact enum diff against HEAD proved 23 additive
   states, and Control Room reviewed and explicitly accepted all 23
   (including the three observability refinements named above) before
   checkpoint authorization.

## Protected scope

Verified zero diff, directly, against every one of the following, both
before and after the checkpoint commit:

```
src/redline_core/restore/staging.py
src/redline_core/restore/sidecar.py
src/redline_core/restore/quiescence.py
src/redline_core/restore/schema_fingerprint.py
src/redline_core/restore/capture_package.py
src/redline_core/restore/sidecar_classification.py
src/redline_core/restore/recovery_planning.py
src/cli/restore_commands.py
src/cli/recovery_planning_commands.py
```

No historical RLC-E9901 pin (`scripts/rlc_e9901_queue_attempt_harness.py`'s
`_MUTATION_BEARING_SOURCE_SHA256`) was changed, updated, or weakened — the
file itself, and both of its own workstation-marked pin-verification test
files, show zero diff against HEAD. `v1.0.0` remains frozen at
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## Publication boundary

At closure-document drafting time:

```
HEAD:          3445063437b084ae235b21ee3cd0fbe2af5d69ce
origin/master: 48cc08a389ab6603f5e4f6b2d381274c0c6fcd51
ahead/behind:  1/0
```

**Mission 1B-A2-3 is not yet published.** Exact-head GitHub Actions CI has
not yet run against, let alone verified, the checkpoint/closure HEAD.
**CI-VERIFIED PUBLICATION may only be declared after a future publication
push and a terminal SUCCESS conclusion for the exact published HEAD** —
never inferred from local test results, a prior SHA's CI result, or this
closure document's own existence.

This implementation is **READY FOR CLOSURE COMMIT / PUBLICATION SEQUENCE** —
each of those remaining steps (closure commit, publication push, exact-head
CI verification) requires its own separate, explicit Founder authorization.

## Production-proof status

Mission 1B-A2-3 is **implemented, tested, and locally checkpointed**. It
establishes **no production recovery-execution proof of any kind** — every
test used only `tmp_path`-scoped, synthetic fixtures;
`REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` were never touched, and no live
Resolve process was ever contacted.

**Mission 1B-A1's production-proof status is unchanged: it remains
explicitly NOT PRODUCTION-RESTORE-PROVEN. Mission 1B-A2-2's
production-proof status is unchanged: it remains explicitly NOT
PRODUCTION-CAPTURE-PROVEN.** Nothing in this closure alters either record.
Mission 1B-A2-3 itself is, and remains, explicitly **NOT
PRODUCTION-RECOVERY-PROVEN**.

## Next mission boundary

The next steps this architecture identifies — closure commit, publication
push, exact-head GitHub Actions CI verification, Mission 1B-B, any live
production degraded-source capture or recovery attempt, or any RLC-E9901
pin update — each require their own separate, explicit Founder
authorization. **This closure document does not authorize any of them.**

## Closure

Redline OS V2 Mission 1B-A2-3 (Recovery Execution + Journal/Evidence
Integration) is **IMPLEMENTED**, **CHECKPOINTED LOCALLY** at
`3445063437b084ae235b21ee3cd0fbe2af5d69ce`, and **NOT PUBLISHED**. This
closure document itself has not yet been committed. Mission 1B-A2 as a
whole remains **in progress** — Mission 1B-B and any live production
recovery drill remain separate, not-yet-authorized future work. The
historical `RLC-E9901` queue-attempt harness's pinned source identity
remains untouched.

Agents advise. Paul decides.
