# Redline OS V2 Mission 1B-A2-3-Prep Closure — Windows Filesystem Disposition Behavioral Proof

## Governance

Agents advise. Paul decides. This preparatory mission exists because the
read-only Mission 1B-A2-3 architecture/implementation-readiness review
concluded **NOT READY FOR A2-3 IMPLEMENTATION AUTHORIZATION** and
identified Windows filesystem move-aside behavior — for a database path
occupied by an ordinary directory, and a config path occupied by an
ordinary regular file — as the one true implementation-blocking proof
obligation still open. This document closes **only** Mission
1B-A2-3-Prep.

## Mission hierarchy — read this before anything else below

```
Mission 1B-A2 — DEGRADED_SOURCE / MISSING_SOURCE Recovery
  ARCHITECTURE: ACCEPTED
  IMPLEMENTATION: IN PROGRESS

    1B-A2-1 — Source Classification + Read-Only Recovery Planning
      STATUS: PUBLISHED

    1B-A2-2 — Degraded-Source Capture
      STATUS: COMPLETE / CHECKPOINTED
      NOT PRODUCTION-CAPTURE-PROVEN

    1B-A2-3-Prep — Windows Filesystem Disposition Behavioral Proof
      STATUS: COMPLETE / CHECKPOINTED (this document)

    1B-A2-3 — Recovery Execution + Journal/Evidence Integration
      STATUS: NOT IMPLEMENTED / NOT AUTHORIZED
```

**This document does not close Mission 1B-A2 as a whole, and does not
authorize Mission 1B-A2-3.** No disposition, recovery execution, or CLI
capability of any kind exists anywhere in this repository after this
closure.

## Implementation checkpoint

SHA: `f702f04d5d8938769f78432ddde28bc5ba35f42c`

Subject: `test: prove Windows recovery disposition behavior`

Parent: `5b12e95a3356276975cfa5fac48be98ef5a31b2e`

This is the frozen Mission 1B-A2-3-Prep *implementation* checkpoint —
distinct from Mission 1B-A2-3-Prep *closure*, which this document and the
accompanying `docs/CHANGELOG.md` update record separately, in their own
future commit, matching the Mission 1A, Mission 1B-A1, Mission 1B-A2-1,
and Mission 1B-A2-2 closure precedent.

Frozen `v1.0.0` remains unchanged at
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## Mission scope

Exactly one new, isolated test file:
`tests/unit/test_windows_disposition_behavior.py` (12 tests). **Zero
production source was touched** — no disposition, recovery execution, or
CLI code was added anywhere in this repository. Every test uses
`tmp_path`-scoped, synthetic fixtures only; `REDLINE_DB_PATH`/
`REDLINE_CONFIG_DIR` were never touched, and no live Resolve process was
contacted.

Explicitly and deliberately **not** in scope, and not implemented anywhere
in this repository by this mission: sidecar disposition, DB/config
wrong-type disposition, live-object rename-aside against a real live
path, Restore staging, database replacement, config replacement, a
recovery execution journal, an escalated recovery authorization model,
destructive recovery execution, `backup restore-recovery` (destructive),
and any A2-3 implementation of any kind.

## Windows environment proven

- Python: `3.13.5`
- OS: Windows 11, `Windows-11-10.0.26200-SP0`
- pytest: `9.1.1`

This is direct behavioral evidence for this specific, currently-supported
development environment. It does not establish, and this closure does not
claim, identical semantics on every Windows/Python/filesystem version or
configuration — it is evidence for the environment actually proven, and
for the architectural contract a future Mission 1B-A2-3 is expected to
adopt on that basis.

## DB-directory proof

When the future database target path is occupied by an ordinary
directory:

- `os.rename()` to a new, non-existing restore-ID-scoped superseded
  destination **succeeds**, removes the source path, preserves the
  destination as a directory, preserves every contained file's bytes
  exactly (including nested subdirectory content), and preserves observed
  NTFS identity metadata (`st_dev`/`st_ino` identical before and after).
  The original source path becomes immediately available for a regular
  database file to be created there.
- **Destination collision**: pre-creating the destination causes
  `os.rename()` to raise `FileExistsError` (`WinError 183`). Source
  remains unchanged; destination remains unchanged; no implicit overwrite
  or merge occurs.
- **Open handle**: a held-open handle on a file *contained inside* the
  directory causes the whole-directory move-aside to fail with
  `PermissionError` (`WinError 5`, "Access is denied"). The filesystem is
  left exactly as it was before the attempt.

## Config-file proof

When the future config target path is occupied by an ordinary regular
file:

- `os.rename()` to a new, non-existing restore-ID-scoped superseded
  destination **succeeds**, removes the source path, preserves the
  destination as a regular file, preserves its bytes exactly, and
  preserves observed NTFS identity metadata (`st_dev`/`st_ino`/`st_size`/
  `st_mtime_ns` identical before and after). The original source path
  becomes immediately available for a config directory to be created
  there.
- **Destination collision**: pre-creating the destination causes
  `os.rename()` to raise `FileExistsError` (`WinError 183`) — the same
  exception type observed for the directory-source case. Source and
  destination both remain byte-identical to before the attempt.
- **Open handle**: an open **read** handle on the source file causes
  `os.rename()` to fail with `PermissionError` (`WinError 32`, "The
  process cannot access the file because it is being used by another
  process"). An open **read+write** handle produces the identical
  `PermissionError`/`WinError 32`. No partial mutation occurs in either
  case.

## Collision semantics — safety-critical result

Windows `os.rename()` **never silently overwrote either object type** in
this environment: both the directory-source and regular-file-source
collision cases raised the identical exception type, `FileExistsError`
(`WinError 183`). This is the positive proof result the "move aside,
never delete, never overwrite" contract depends on — no BLOCKING finding
here.

## Open-handle failure semantics

`PermissionError` caused by an open handle (on the object itself, or on a
file merely contained inside a directory being moved) is recorded as an
**expected Windows disposition failure mode, not an implementation
defect**. A future Mission 1B-A2-3 disposition step must, on this
failure: fail closed; journal the disposition failure truthfully; leave
the filesystem exactly as observed (no force, no delete, no overwrite
fallback); not continue to replacement; not retry blindly; not resume the
same attempt automatically.

## Same-volume boundary

Two ordinary `tmp_path` subdirectories reported `same_volume() == True`
(trivially, one filesystem tree). **No real cross-volume rename was
manufactured** — no safe second temporary volume exists in this isolated
test environment, and none was fabricated against arbitrary machine
paths. Proven instead: the *gate pattern* a future disposition must
apply — refuse to attempt any `os.rename()` when `same_volume()` (patched
to report a mismatch) returns `False`, checked before the rename, not
after. This closure does not claim actual cross-volume rename behavior
was exercised; a future Mission 1B-A2-3 must call the existing
`same_volume()` primitive and fail closed on `False` before ever
attempting a rename, exactly as Mission 1B-A1's own `stage_database()`/
`stage_config()` already do.

## Unsafe-object boundary

Unsafe symlink/junction/reparse objects remain outside the automatic
move-aside contract entirely. The behavioral tests prove the intended
gate pattern — `os.lstat()` the source, then `fsutil.is_unsafe_link()`,
refusing before any `os.rename()` attempt — using the repository's
existing unsafe-object simulation convention (monkeypatching
`fsutil.is_unsafe_link()`, matching `tests/unit/test_backup_paths.py`),
not real symlink/junction creation, which can require elevated privileges
on Windows. A future Mission 1B-A2-3 must refuse unsafe objects before
any rename attempt, consistent with Mission 1B-A2-1's own
`RECOVERY_BLOCKED` treatment of unsafe DB/config objects.

## Proposed future disposition contract — evidence-derived, NOT implemented

For both proof cases alike, the evidence in this mission supports the
following contract for a future Mission 1B-A2-3
`recovery_disposition.py` (not built by this mission):

1. Fresh `os.lstat()` of the source object.
2. Unsafe-object gate: refuse (`RECOVERY_BLOCKED`) if
   `fsutil.is_unsafe_link()` is true — never move an unsafe object under
   any circumstance.
3. Confirm the object is actually the expected wrong type, re-derived
   from the same `lstat()`, never assumed from an earlier classification
   result alone.
4. Same-volume gate: fail closed before any rename if `same_volume()` is
   `False`.
5. Destination non-existence gate using `lstat()`-style observation
   (never `Path.exists()`, which is blind to a dangling/unsafe object
   already occupying the destination).
6. Record a `DISPOSITION_INTENT` journal transition.
7. One collision-refusing `os.rename()` call — never `os.replace()`
   (which can silently succeed over an existing destination on this
   platform, the opposite of the required guarantee) and never
   `shutil.move` (unused anywhere in this repository).
8. Post-move verification: re-`lstat()` the now-absent source (must raise
   `FileNotFoundError`) and the destination (must exist, correct type,
   byte-identical content).
9. Record `DISPOSITION_COMPLETE` on success, `DISPOSITION_FAILED` on any
   failure.
10. No automatic retry. No delete fallback. No overwrite fallback. No
    rollback. No resume.

## Explicit non-capabilities

Not implemented by this mission, and not scheduled by this document:
sidecar disposition, DB wrong-type disposition, config wrong-type
disposition, live-object rename-aside against any real live path, Restore
staging, database replacement, config replacement, a recovery execution
journal, an escalated recovery authorization model, destructive recovery
execution, `backup restore-recovery` (destructive), rollback, resume,
repair, and production recovery proof of any kind. Mission 1B-A2-3
remains:

**NOT IMPLEMENTED. NOT AUTHORIZED.**

## Validation evidence

- **Windows behavioral proof**: **12 passed**
  (`tests/unit/test_windows_disposition_behavior.py`).
- **A2-2 regression**: **67 passed** — unchanged.
- **A2-1 regression**: **49 passed** — unchanged.
- **Locked Mission 1A / Mission 1B-A1 regression**: **184 passed** —
  unchanged (Focused Restore 97 + Restore integration 3 + Mission
  1A/CLI-composition 84).
- `git diff --check`: clean at every stage (pre-stage, staged, and
  post-commit).
- All four gates were reproduced identically both immediately before and
  immediately after the checkpoint commit.

## A2-3 readiness boundary / remaining decisions

This mission closes **only** the Windows move-aside behavioral proof
obligation identified by the Mission 1B-A2-3 architecture/readiness
review. **It does not itself make Mission 1B-A2-3 ready for
implementation.** The following Control Room decisions remain open and
are **not** resolved by this closure:

- the escalated recovery authorization model (exact field set, CLI
  representation)
- wrong-type sidecar disposition policy (block vs. move-aside)
- unsafe sidecar disposition policy
- journal extension shape, versioning, and ID namespace
- capture reverification-before-mutation requirement
- reusable Restore verification (`_verify_restore()`) extraction
- CLI authorization representation for a future `restore-recovery`
  command

## Production-proof status

Mission 1B-A2-3-Prep is **implemented, tested, and checkpointed**. It
establishes **no production recovery-execution proof of any kind** — every
test used only `tmp_path`-scoped, synthetic fixtures;
`REDLINE_DB_PATH`/`REDLINE_CONFIG_DIR` were never touched, and no live
Resolve process was ever contacted.

**Mission 1B-A1's production-proof status is unchanged: it remains
explicitly NOT PRODUCTION-RESTORE-PROVEN. Mission 1B-A2-2's
production-proof status is unchanged: it remains explicitly NOT
PRODUCTION-CAPTURE-PROVEN.** Nothing in this closure alters either
record.

## Next mission boundary

The next implementation slice this architecture identifies is **Mission
1B-A2-3 — Recovery Execution + Journal/Evidence Integration**. **This
closure does not authorize it.** Mission 1B-A2-3 requires its own,
separate, explicit Founder authorization — plus resolution of the
remaining Control Room decisions listed above — before any implementation
work begins.

## Closure

Redline OS V2 Mission 1B-A2-3-Prep (Windows Filesystem Disposition
Behavioral Proof) is formally closed, locally. Implementation checkpoint
`f702f04d5d8938769f78432ddde28bc5ba35f42c` has been reviewed and
checkpointed on `master`, one commit ahead of `origin/master`. This
closure has not yet been committed.

Mission 1B-A2 as a whole remains **in progress**. No degraded-source
recovery *execution* capability exists anywhere in this repository.
Mission 1B-A2-3 and Mission 1B-B remain unauthorized and unimplemented.
The historical `RLC-E9901` queue-attempt harness's pinned source identity
remains untouched.

Next work — including publication (push) of this checkpoint and closure,
Mission 1B-A2-3, Mission 1B-B, any live production degraded-source
capture, any live production Restore or recovery drill, or any
`RLC-E9901` pin update — requires a new, separate, Founder-authorized step
or mission.

Agents advise. Paul decides.
