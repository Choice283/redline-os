# Redline OS V2 Mission 1B-A2-2 Closure — Degraded-Source Capture

## Governance

Agents advise. Paul decides. This capability exists because Mission
1B-A2-1's own closure (`docs/V2_MISSION_1B_A2_1_CLOSURE_2026-08-17.md`)
recorded Mission 1B-A2-2 (Degraded-Source Capture) as the second of three
implementation slices Mission 1B-A2's accepted architecture decomposed
into, and identified it as separate, not-yet-authorized future work.
Mission 1B-A2-2 was then separately authorized, implemented, found NOT
READY FOR CHECKPOINT by a post-implementation safety review (one BLOCKING
unsafe-source TOCTOU defect plus three additional checkpoint-blocking
findings), corrected under a targeted safety-correction authorization,
independently re-reviewed against a reconciled validation environment,
had two remaining NON-BLOCKING regression-coverage gaps closed under a
narrow test-only authorization, and was then checkpointed. This document
closes **only** Mission 1B-A2-2.

## Mission hierarchy — read this before anything else below

```
Mission 1B-A2 — DEGRADED_SOURCE / MISSING_SOURCE Recovery
  ARCHITECTURE: ACCEPTED
  IMPLEMENTATION: IN PROGRESS (two of three slices complete)

    1B-A2-1 — Source Classification + Read-Only Recovery Planning
      STATUS: PUBLISHED

    1B-A2-2 — Degraded-Source Capture
      STATUS: COMPLETE / CHECKPOINTED (this document)

    1B-A2-3 — Recovery Execution + Journal/Evidence Integration
      STATUS: NOT IMPLEMENTED / NOT AUTHORIZED
```

**This document does not close Mission 1B-A2 as a whole.** No
degraded-source recovery *execution* capability exists anywhere in this
repository after this closure. Mission 1B-A2-3 requires its own, separate,
future Founder authorization before any implementation work on it may
begin.

## Implementation checkpoint

SHA: `79eb4854e38f148ae636f0c99fc292dafa17d22d`

Subject: `feat: add degraded-source capture`

Parent: `df642dbe8afbd755c24140caa51e05996e933504`

This is the frozen Mission 1B-A2-2 *implementation* checkpoint — distinct
from Mission 1B-A2-2 *closure*, which this document and the accompanying
`docs/CHANGELOG.md` update record separately, in their own future commit,
matching the Mission 1A, Mission 1B-A1, and Mission 1B-A2-1 closure
precedent (the closure record is never squashed into or backdated onto
the implementation checkpoint).

Frozen `v1.0.0` remains unchanged at
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## Mission scope

Programmatic, evidence-preservation capture only. The full authorized
delivered scope:

- Whole-system degraded-source capture: `redline_core.restore.
  capture_manager.build_degraded_source_capture()`
- A structurally distinct `dsc1-...` capture-identity namespace and a
  separate `degraded_source_captures/` package root, both impossible to
  confuse with Mission 1A's `b1-...`/`system_backups/` by construction
- Database slot preservation
- Exact six-config-slot accounting, plus a safe, non-recursive config
  directory inventory
- SQLite sidecar evidence preservation (lstat-based observation, never the
  locked, `Path.exists()`-based presence primitive)
- A typed, seven-value per-item outcome model
- A sealed package manifest, manifest SHA-256 sidecar, and completion
  marker, published via stage → verify → atomic publish
- Collision refusal and application-level immutable sealed packages
- Package-level hard-failure semantics (typed `CaptureError` taxonomy, no
  proceed-anyway override)
- Best-effort per-item preservation (a damaged/unreadable/unsafe item
  never fails the whole package)
- Read-only live-source behavior (the live database, config, and sidecars
  are never mutated, moved, renamed, or deleted)
- Programmatic API only — **no CLI command exists for this capability**

Explicitly and deliberately **not** in scope, and not implemented anywhere
in this repository: sidecar disposition, DB/config wrong-type
disposition, live-object rename-aside, Restore staging, database
replacement, config replacement, a recovery execution journal, destructive
recovery execution, `backup restore-recovery` (destructive), rollback,
resume, repair, or production recovery proof. See "Explicit
non-capabilities" below.

## Delivered capability

Given a live `db_path`/`config_dir`, a resolved `paths.backup_path`
capture root, and the caller-supplied Mission 1B-A2-1
`SourceSideAssessment` for each side, `build_degraded_source_capture()`
builds, seals, and atomically publishes one whole-system degraded-source
capture package that truthfully records what could be preserved of the
current live database and configuration state — without creating a
Mission 1A backup, without staging anything for Restore, and without
disposing of, moving, renaming, or deleting anything it observes.

This is preservation/evidence infrastructure only, intended for a future,
separately authorized Mission 1B-A2-3 to orchestrate as one step of an
eventual, escalated-authorization-gated recovery attempt — deliberately
exposed as a plain function, not a CLI command, so an operator cannot
trigger evidence-preservation activity disconnected from that future
ceremony.

## Capture-vs-backup boundary

A degraded-source capture is **not**:

- a Mission 1A backup
- a partial Mission 1A backup
- a Restore target
- a rollback package
- a resumable transaction

Mission 1A remains the sole authority for valid Redline OS backups.
`dsc1-...` is structurally impossible to confuse with `b1-...`:
`redline_core.backup.paths.validate_backup_id()` (locked, unmodified)
rejects a `dsc1-...` ID outright, `BackupManager.list_backups()` (locked,
unmodified) only ever scans `system_backups/` and never
`degraded_source_captures/`, and `BackupManager.verify_backup()`/
`RestoreManager.restore_plan()`/`.restore()` (all locked, unmodified) all
reject a capture ID before any backup/restore-domain logic runs. Captures
therefore do not appear in `backup list`, cannot pass Mission 1A
verification, and cannot be accepted by Mission 1B-A1 Restore — proven
directly by `test_capture_never_appears_in_backup_list`,
`test_capture_cannot_pass_mission_1a_backup_verification`, and
`test_capture_cannot_be_restore_target`.

## Whole-system capture invariant

Every successful capture accounts for the observed live system as a
whole, on every attempt: exactly one database slot, exactly six required
config-file slots, every observed SQLite sidecar, a safe non-recursive
config-directory inventory, and a per-item preservation outcome for each
— **even when one side is independently classified `HEALTHY`** by Mission
1B-A2-1's own classifier. A healthy surviving component inside a
degraded-run capture remains capture evidence; it never becomes a
separate, partial Mission 1A backup — proven by
`test_healthy_side_still_captured_as_evidence_not_skipped` and the
six-combination parametrized `test_whole_system_capture_accounts_for_
both_sides`.

## Package success / failure semantics

**Capture package success**: a safe, sealed capture artifact exists and
truthfully records the outcome of every relevant source item. Individual
items may be `UNREADABLE`, `MISSING`, `UNSAFE_OBJECT_RECORDED`,
`WRONG_TYPE_RECORDED`, or `CHANGED_DURING_CAPTURE` — the package can, and
routinely does, still seal successfully. Per-item outcomes
(`CaptureItemOutcome`): `CAPTURED_VERIFIED`, `CAPTURED_UNVERIFIED`,
`UNREADABLE`, `UNSAFE_OBJECT_RECORDED`, `MISSING`, `WRONG_TYPE_RECORDED`,
`CHANGED_DURING_CAPTURE`.

**Capture system failure**: the evidence package itself cannot be safely
created, verified, sealed, or published — an unsafe destination
(`CaptureDestinationUnsafeError`), an unconfigured destination
(`CaptureConfigurationError`), a destination collision
(`CapturePackageCollisionError`), a staging/write failure
(`CaptureSystemWriteFailedError`), a seal/self-consistency failure, or a
publication failure (`CaptureSealFailedError`/`CapturePublicationError`).
**This is an unconditional hard stop. No proceed-anyway override exists
anywhere in this package.**

## Safety architecture — post-implementation correction record

The original implementation was reviewed (read-only, Control Room) and
found **NOT READY FOR CHECKPOINT** on a confirmed unsafe-source TOCTOU
defect, plus three additional findings Control Room treated as
checkpoint-blocking. The accepted architecture and implementation
direction were **not** redesigned; five targeted corrections were applied
under a separate, narrowly-scoped safety-correction authorization — see
`docs/BACKUP_RECOVERY_ARCHITECTURE.md` §15.19 for the full mapping from
each post-review finding to its fix. A subsequent, independent
post-correction review (conducted after reconciling a pre-existing,
machine-local Python import-environment defect unrelated to this mission
— see "Validation environment note" below) found `ARCHITECTURE CONFORMS`,
zero BLOCKING findings, and two NON-BLOCKING automated-test-coverage
gaps, both of which were then closed under a final, narrow, test-only
authorization. No implementation defect was exposed by either the
post-correction review or the final coverage correction.

### Source TOCTOU correction and actual guarantee

`capture_io.best_effort_capture_file()` proves the just-opened source
handle's own identity (`os.fstat()`) matches the pre-open pathname
observation (`os.lstat()`) **before a single byte is read from it**. On
mismatch, the handle is closed immediately and the outcome is recorded as
`CHANGED_DURING_CAPTURE` with zero captured bytes — a mismatch can never
become `CAPTURED_VERIFIED`.

**Stated honestly**: on supported Windows/Python behavior, a substituted
unsafe target may still be **OPENED** by the underlying OS before Redline
can inspect the opened handle — `os.O_NOFOLLOW` does not exist on
Windows, so no portable no-follow-at-open primitive is available to this
repository's supported primitives. What this correction actually proves
is that the substituted target's bytes are **never READ, hashed, or
written** once the identity mismatch is caught. This closure does not
claim, and the implementation does not provide, "unsafe targets can never
be opened" — only "never read when identity does not match." Proven by
`test_opened_handle_identity_mismatch_detected_before_any_read` and
`test_opened_handle_flagged_unsafe_detected_before_any_read`, both of
which assert zero `read()` calls occurred on the mismatched handle.

### Config-container safety

`capture_package.capture_config_slot()` performs a pre-enumeration
`lstat()`/safety check, a single-level, non-recursive `iterdir()`
enumeration, and then a **post-enumeration identity/safety recheck**
before ever trusting that enumeration or building any per-file path from
it. On any post-recheck mismatch (unsafe, wrong type, or changed
identity), the just-obtained inventory is discarded and all six required
config slots are truthfully recorded as not individually inspected,
sharing the container's `CHANGED_DURING_CAPTURE`-equivalent (or
unsafe/missing/wrong-type) outcome. Proven directly by
`test_capture_config_slot_post_enumeration_substitution_detected`, which
specifically forces the substitution to be observed only on the *second*
`lstat()` call (after `iterdir()` has already run), distinguishing this
branch from the separate, earlier pre-enumeration unsafe-link case.

A narrow residual race is honestly recorded, not claimed eliminated: the
window between the post-enumeration recheck succeeding and the six
subsequent per-file captures actually running is not independently
re-verified a third time immediately before each per-file open. This is a
known, platform-level limitation — Python's stdlib offers no atomic,
handle-based safe directory enumeration on Windows — mitigated, but not
eliminated, by each per-file capture's own independent source-identity
check (the same TOCTOU correction above, applied per file).

### Destination safety

Every capture-destination directory this subsystem creates or writes into
— the configured capture root, `.staging_capture/`, one staging attempt
directory, and `degraded_source_captures/` — is validated with
`capture_paths.require_safe_capture_directory()`: an `os.lstat()`-based
check, never `Path.exists()`/`Path.is_dir()`, rejecting symlink/junction/
reparse objects and wrong object types, bracketed immediately before and
immediately after each directory-creation call. The final capture-ID
collision check uses `os.lstat()`, not `Path.exists()`, so a dangling or
unsafe object occupying the exact final path is caught even though
`Path.exists()` would report it absent. Malformed or traversal capture
IDs remain structurally rejected by the unmodified `validate_capture_id()`
regex. No capture write can be redirected outside the approved
destination structure by a known unsafe child object. A narrow,
irreducible race between the final collision check and the atomic
`os.rename()` publish is mitigated by `os.rename()`'s own atomic
collision failure as the strongest feasible last-instant revalidation.

### Sidecar evidence behavior

`capture_package.capture_sidecars()` uses capture-specific, direct
`os.lstat()` observation for each recognized SQLite sidecar suffix,
**never** the locked, `Path.exists()`-based `find_present_sidecars()`
primitive (unmodified, still correct for Mission 1B-A1's own fail-closed
purpose). This lets capture evidence record safe, wrong-type, unsafe, and
**dangling unsafe** sidecars alike — including when the database itself
is missing, as two independent, non-interfering facts. Sidecars remain
evidence only: never treated as the database, never merged into the
database slot, never moved, renamed, or deleted, and never treated as
proof of quiescence.

### Seal-time verification

The completion marker (`CAPTURE_COMPLETE`) is written only after
`_verify_staged_capture_self_consistency()` returns without raising.
Before sealing, wherever applicable: payload objects are lstat-checked
safe and regular (never merely "exists"), payload size matches the
manifest, payload SHA-256 independently matches the manifest-recorded
hash, no-payload outcomes have no contradictory stray filesystem object
at the location they would have used, and the manifest's own `.sha256`
sidecar is independently re-verified against manifest bytes actually on
disk. A tampered or self-contradictory staged package fails sealing
unconditionally.

### Application-level immutability

Every capture guarantee below the manifest layer is enforced by this
subsystem's own API surface — unique, collision-refusing `capture_id`s,
no overwrite, no append-after-seal API, no resume, no repair, and no API
that mutates a sealed package. **This is application-level immutability
only.** No filesystem ACL or read-only-bit protection is applied to a
sealed capture directory or its contents, and none is claimed.

### Caller-supplied A2-1 assessments remain distinct

`build_degraded_source_capture()` never calls Mission 1B-A2-1's own
`classify_database_source()`/`classify_config_source()` — the caller
supplies its `SourceSideAssessment` values, recorded verbatim in the
manifest as `supplied_assessment`. Capture-time filesystem outcomes are
independently observed and stored separately, so a stale supplied
assessment remains distinguishable from what capture itself actually
observed at capture time (exactly what `CHANGED_DURING_CAPTURE` and the
other per-item outcomes exist to reveal).

## Windows disposition gate — recorded, not closed

Unchanged from Mission 1B-A2-1's closure record: before a future Mission
1B-A2-3 may rely on automatic disposition for a DB path containing an
ordinary directory, or a config path containing an ordinary regular file,
isolated Windows filesystem behavioral tests must prove the intended
rename/move-aside semantics — no such test exists in this repository
today, and Mission 1B-A2-2 does not add one. Mission 1B-A2-2 only
preserves such objects as `WRONG_TYPE_RECORDED` evidence; it does not
dispose of them. Unsafe link/junction/reparse objects remain
`RECOVERY_BLOCKED` per Mission 1B-A2-1's own model and are not, and are
not intended to become, part of this gate.

## Explicit non-capabilities / deferred to Mission 1B-A2-3

Not implemented by Mission 1B-A2-2, and not scheduled by this document:
sidecar disposition, DB wrong-type disposition, config wrong-type
disposition, live-object rename-aside, Restore staging, database
replacement, config replacement, a Restore/recovery execution journal,
destructive recovery execution, `backup restore-recovery` (destructive),
rollback, resume, repair, and production recovery proof. Mission
1B-A2-3 remains:

**NOT IMPLEMENTED. NOT AUTHORIZED.**

This closure does not authorize it, and no architecture or implementation
work on it has begun under any of the authorizations this closure
records.

## Independent review / correction history

1. **Original Mission 1B-A2-2 implementation** (six new
   `src/redline_core/restore/capture_*.py` files, zero previously-existing
   file modified).
2. **Post-implementation safety review** (read-only, Control Room) found
   `NOT READY FOR CHECKPOINT` on one BLOCKING finding (unsafe-source
   TOCTOU) plus three additional checkpoint-blocking findings
   (config-container TOCTOU, capture-destination safety, weak seal-time
   verification), and one clarification-only finding (immutability
   terminology).
3. **Targeted safety correction** (source/config-container/destination/
   sidecar/seal-time hardening, plus the immutability-terminology
   clarification) — fifteen new regression tests added across the three
   existing A2-2 test files; none removed or weakened; the focused A2-2
   suite grew from 50 to 65 passed.
4. **Post-correction review + validation-environment reconciliation**
   (read-only) independently re-traced all five corrections against the
   actual corrected code (not the correction report alone), reconciled a
   pre-existing, machine-local `cli` package-shadow import defect using
   only a process-local `PYTHONPATH` (no environment/package mutation),
   reproduced the exact accepted A2-1 (49) and locked-foundation (184)
   regression gates precisely, and found `ARCHITECTURE CONFORMS`, zero
   BLOCKING findings, and two NON-BLOCKING automated-test-coverage gaps —
   both independently verified correct against the real implementation
   via ad hoc, throwaway reproduction before being recorded as coverage
   gaps, not defects.
5. **Final regression-coverage correction** (test-only, separately
   authorized) closed both gaps: a dedicated regression for the
   config-container post-enumeration recheck branch specifically (not
   merely the earlier pre-enumeration unsafe-link branch), and a
   same-size, in-place-byte-flip SHA-256-mismatch regression isolated
   from the pre-existing size-mismatch case. Both passed on first run
   against the unmodified implementation: **no implementation defect was
   exposed**. Focused A2-2 suite grew from 65 to 67 passed.
6. **Checkpoint commit review**, confirming exactly the reviewed 12-path
   diff, zero production-source drift since review (SHA-256-verified
   byte-identical), and returned: **READY FOR CHECKPOINT AUTHORIZATION**.

No BLOCKING finding survived to checkpoint.

## Validation evidence

- **A2-2 suite**: **67 passed** — includes dedicated regressions for
  opened-handle identity mismatch (zero reads), opened-handle flagged
  unsafe (zero reads), config-container post-enumeration substitution,
  unsafe/wrong-type/dangling capture-destination objects, dangling unsafe
  SQLite sidecars (including with a missing database), payload size
  mismatch, same-size SHA-256 payload tamper, manifest-bytes tamper,
  manifest-SHA sidecar mismatch, contradictory stray payload for a
  no-payload outcome, and legitimate no-payload records still sealing.
- **A2-1 regression**: **49 passed** — unchanged.
- **Locked Mission 1A / Mission 1B-A1 regression**: **184 passed** —
  unchanged (Focused Restore 97 + Restore integration 3 +
  Mission 1A/CLI-composition 84).
- **Architecture review**: `CONFORMS`.
- **Blocking findings**: `NONE`.
- `git diff --check`: clean at every stage of implementation, correction,
  review, coverage correction, and checkpoint.

### Validation environment note

The development machine contains a pre-existing, machine-local, unrelated
third-party Python 3.13 user-site package literally named `cli` that can
shadow the repository's own `src/cli` for a bare `python -m pytest`
invocation, depending on `sys.path` ordering. This is an
import-resolution/environment characteristic of this machine — **it is
not a Mission 1B-A2-2 product defect**, and no part of the implementation
or its tests caused or depends on it. Every accepted focused validation
result recorded in this document and its history was reproduced without
any machine, package, or environment mutation, using only a per-subprocess
`PYTHONPATH=C:\Users\pj198\Documents\redline-os\src` prefix — verified
each time by confirming `cli.__file__` resolved into
`C:\Users\pj198\Documents\redline-os\src\cli\__init__.py`, never the
stray package. No `pip install`/`uninstall`, `.pth` edit, or persistent
environment variable was ever used.

## Historical RLC-E9901 harness

Mission 1B-A2-2 adds no CLI surface and registers no new command — zero
diff to `src/cli/main.py`, `src/cli/backup_commands.py`,
`src/redline_core/runtime/composition.py`, or
`scripts/rlc_e9901_queue_attempt_harness.py` (all verified byte-identical
to `origin/master` immediately before staging the checkpoint commit).
**This closure does not update the historical harness pins.** Their
pre-existing staleness (recorded in the Mission 1A, Mission 1B-A1, and
Mission 1B-A2-1 closure records) is unchanged by this mission.

## Production-proof status

Mission 1B-A2-2 is **implemented, tested, and checkpointed**. It is
**not**:

**PRODUCTION-CAPTURE-PROVEN.**

No real production degraded-source capture has been separately authorized
or executed. Every test in this mission's implementation, correction,
review, and coverage-correction history used only `tmp_path`-scoped,
synthetic fixtures; `REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` were never
touched, and no live Resolve process was ever contacted. This mission
establishes no production recovery-execution proof of any kind.

**Mission 1B-A1's own production-proof status is unchanged and is not
altered by this closure: it remains explicitly NOT
PRODUCTION-RESTORE-PROVEN.** Nothing in Mission 1B-A2-2 changes that
record.

## Next mission boundary

The next implementation slice this architecture identifies is **Mission
1B-A2-3 — Recovery Execution + Journal/Evidence Integration**. **This
closure does not authorize it.** Mission 1B-A2-3 requires its own,
separate, explicit Founder authorization before any implementation work
begins, exactly as Mission 1B-A2-1 and Mission 1B-A2-2 themselves each
did.

## Closure

Redline OS V2 Mission 1B-A2-2 (Degraded-Source Capture) is formally
closed, locally. Implementation checkpoint
`79eb4854e38f148ae636f0c99fc292dafa17d22d` has been independently
reviewed, safety-corrected, re-reviewed, had its final regression-coverage
gaps closed, and checkpointed on `master`, one commit ahead of
`origin/master`. This closure has not yet been committed.

Mission 1B-A2 as a whole remains **in progress** — two of its three
implementation slices are complete. No degraded-source recovery
*execution* capability exists anywhere in this repository. Mission
1B-A2-3 and Mission 1B-B remain unauthorized and unimplemented. The
historical `RLC-E9901` queue-attempt harness's pinned source identity
remains untouched.

Next work — including publication (push) of this checkpoint and closure,
Mission 1B-A2-3, Mission 1B-B, any live production degraded-source
capture, any live production Restore or recovery drill, or any
`RLC-E9901` pin update — requires a new, separate, Founder-authorized step
or mission.

Agents advise. Paul decides.
