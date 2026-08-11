# Production Render Start Path — Construction Notes

Status: **Rev4 correction, construction-only.** No Resolve contact, no
`StartRendering()` call, no production queue attempt, and no live
execution occurred while building or correcting this feature.
`ResolveAdapter.start_render()` has been unit-tested against
`MockResolveAdapter` only; it has not been verified against a live,
running DaVinci Resolve Studio instance.
Files: `src/redline_core/resolve/adapter.py`,
`src/redline_core/resolve/mock.py`, `src/redline_core/render/manager.py`,
`src/redline_core/render/exceptions.py`,
`src/redline_core/resolve/exceptions.py`, `src/redline_core/db/database.py`,
`src/cli/render_commands.py`, and their test files.
Construction commit (parent checkpoint verified before work began):
`3c345ee259764e47b95d804a6be4a0683f62f4ee`

**Rev1 was independently reviewed from exact bundled bytes: REVISION
REQUIRED (10 findings, 8 blocking).** This document has been corrected
in place for Rev2; superseded Rev1 claims are struck through inline and
replaced, and a full finding-by-finding summary is in §6 below. Sections
§2/§3 below describe the *current* (Rev2) design; where a Rev1 claim was
rejected by review, it is marked and corrected rather than silently
removed.

This document does not authorize commit, push, or live Resolve execution.

## 1. Why this exists

Redline OS already supported `render queue` / `render status` / `render
list` / `render cancel`, but had no reviewed production pathway to
actually start a queued render — only an ad-hoc, unreviewed
`DaVinciResolveScript` script could call `StartRendering()` directly. This
construction adds the missing capability through the existing layered
architecture (CLI → `RenderManager` → `ResolveAdapter` → Resolve), matching
every other render command, rather than bypassing it.

## 2. Architecture investigation findings

Read before writing any code: `src/cli/render_commands.py`,
`src/redline_core/render/manager.py`, `src/redline_core/resolve/adapter.py`,
`src/redline_core/resolve/mock.py`, `src/redline_core/db/models.py`,
`src/redline_core/db/database.py`, `src/redline_core/runtime/composition.py`,
`tests/unit/test_resolve_script_adapter_render_cancel.py`,
`tests/unit/test_render_manager.py`, `tests/unit/test_cli_render.py`, and
`docs/ARCHITECTURE.md` §3.5–§3.7.

1. **`RenderJobStatus`** (`db/models.py`): `CLAIMING`, `QUEUED`,
   `RENDERING`, `COMPLETE`, `FAILED`, `CANCELLED`. `CLAIMING` is the
   pre-Resolve-acceptance state written by `claim_render_output()`, before
   `finalize_render_output_claim()` sets both `resolve_job_id` and
   `QUEUED` together — so a real `CLAIMING` row always has
   `resolve_job_id is None`.
2. **SQLite render-job lifecycle**: `queue_render()` writes `QUEUED` (with
   `resolve_job_id`) once Resolve accepts the job. `get_render_status()` is
   the *general* reconciliation bridge — it polls Resolve on every call and
   syncs whatever status Resolve reports. `cancel_render()` does **not**
   use that reconciliation path: it calls the adapter, and only after the
   adapter's own postcondition wait has already confirmed the mutation,
   writes `CANCELLED` to SQLite directly and immediately.
3. **Should starting eagerly change DB state, or wait for reconciliation?**
   Eagerly, mirroring `cancel_render()` exactly — not
   `get_render_status()`'s poll-driven pattern. The justification is the
   same in both cases: the adapter call itself doesn't return until its own
   getter-only postcondition wait has independently confirmed the new
   state (`Cancelled` for cancel, `Rendering` for start), so writing SQLite
   immediately afterward is recording an already-established fact, not
   optimistically assuming one.
4. **Already-rendering requested job**: rejected before any Resolve
   mutation call, both at the DB level (`RenderManager` requires
   `status == QUEUED`) and, independently, at the adapter level (the
   target job's own `JobStatus` must be exactly `Ready`) — two layers, not
   one, since a caller could in principle invoke the adapter directly.
5. **Complete/Failed/Cancelled**: rejected with a message naming the exact
   terminal status, mirroring `cancel_render()`'s own terminal-status
   rejection exactly (same three statuses, same "cannot be started/cancelled
   from terminal status" phrasing pattern).
6. **Resolve job no longer exists**: `GetRenderJobStatus()` returning `None`
   is treated as "not found" and rejected before any mutation call — same
   as `cancel_render()`.
7. **DB job has no `resolve_job_id`**: rejected by `RenderManager` before
   the start-specific `ResolveAdapter.start_render()` call
   (`RenderJobMissingResolveIdError`) — the adapter's start method is
   never even reached (this does not claim Resolve was never connected to
   at all elsewhere in the running process — see Finding 5 in §6).
8. **Must the current Resolve project already match the job's project?**
   **(Rev2 correction — Rev1's answer here was rejected by independent
   review.)** Rev1 answered "not verified explicitly, by design, matching
   the existing `get_render_status()`/`cancel_render()` boundary" and
   argued this reproduced an already-accepted gap rather than introducing
   a new one. Independent review rejected that reasoning specifically for
   `start_render()`: unlike status-lookup or cancellation of a job that is
   already live in Resolve's own queue, *starting* a render is a brand-new
   mutation pathway, and a wrong-current-project mismatch here would start
   the wrong project's job outright, not merely report or cancel a
   possibly-wrong one. Rev2 therefore requires and implements an explicit,
   getter-only pre-mutation check: `GetCurrentProject().GetName()` must
   equal exactly the render job's own persisted `project_name` before the
   `StartRendering()` mutation call, and `RenderManager.start_render()` now sources
   and threads `project_name`/`timeline_name` from the persisted
   `RenderJob` row through to the adapter to make that check possible. See
   §6 Finding 1 below. Rev2 also independently binds the queued-job's own
   `TimelineName` (via `GetRenderJobList()`) against the persisted
   `timeline_name` — see §6 Finding 2.
9. **Can `StartRendering` target one specific queued job?** Yes — verified
   from the local Resolve Scripting README (`C:\ProgramData\Blackmagic
   Design\DaVinci Resolve\Support\Developer\Scripting\README.txt`), not
   guessed:
   ```text
   StartRendering(jobId1, jobId2, ...)                  --> Bool
   StartRendering([jobIds...], isInteractiveMode=False) --> Bool
   StartRendering(isInteractiveMode=False)              --> Bool  # starts every queued job
   ```
   The job-ID-targeted list form is used; the zero-argument
   "start everything queued" form is never called.
10. **Return/postcondition semantics**: `Bool`. Consistent with every other
    boolean-returning Resolve mutation in this codebase (`AddRenderJob`,
    `SetRenderSettings`, `LoadRenderPreset`, `DeleteRenderJob`), a `False`
    return is treated as an unambiguous, immediate rejection — no retry, no
    reconciliation attempt. A truthy return is *not* treated as sufficient
    proof by itself; `cancel_render()` already established the precedent
    (§3.7) that a Resolve state transition may not be immediately visible
    through a getter the instant the mutating call returns, so
    `start_render()` reuses that same bounded, getter-only postcondition
    pattern rather than trusting the return value alone.

## 3. Design decisions (Rev2)

- **`ResolveAdapter.start_render(*, project_name: str, timeline_name: str,
  resolve_job_id: str) -> None`.** ~~Rev1: deliberately matches
  `get_render_status()`/`cancel_render()`'s exact signature shape (job ID
  only, no project name)~~ **— rejected by Rev1 review (Finding 1).**
  `RenderManager.start_render()` now sources `project_name`/
  `timeline_name` from the persisted `RenderJob` row and passes them
  through explicitly, so the adapter can bind the mutation to the exact
  expected identity instead of trusting whatever project happens to be
  current.
- **Precondition order**: connected → `project_name`/`timeline_name`/
  `resolve_job_id` each non-empty strings → **current-project identity
  match** (`GetCurrentProject().GetName() == project_name`, getter-only,
  never `LoadProject()`) → **queued-job/timeline identity match** (exactly
  one `GetRenderJobList()` entry resolves to `resolve_job_id`, and that
  entry's own `TimelineName == timeline_name`, getter-only, never
  `SetCurrentTimeline()`) → job exists → job's own status is `Ready`
  (else: already-rendering / terminal / unsupported, each a distinct
  message) → `IsRenderingInProgress()` is **exactly `False`** (any other
  observed value — `True`, `None`, `0`, `1`, a string, a container, or any
  other object — fails closed; Rev1 only rejected exact `True`, silently
  permitting every other non-`False` value through). The rendering-state
  check is independent of the target job's own status: it exists
  specifically to satisfy "ensure no unrelated active render would be
  affected" even in the edge case where the target job is `Ready` but a
  *different* job is currently `Rendering`.
- **One-call mutation guarantee**: proved structurally, not just by
  intent — a dedicated static-safety test file parses `adapter.py`'s AST
  and confirms `StartRendering` is reachable from exactly one call site in
  the entire module (now inside `_invoke_start_rendering_and_reconcile()`,
  not `start_render()` itself), that no loop node in any start-pathway
  function contains it, and that none of `start_render()`,
  `_require_exact_current_project()`, `_require_exact_queued_job_identity()`,
  `_invoke_start_rendering_and_reconcile()`, or `_poll_for_rendering()`
  reaches `AddRenderJob`, `DeleteRenderJob`, `DeleteAllRenderJobs`,
  `StopRendering`, `SetRenderSettings`, `LoadRenderPreset`, `LoadProject`,
  or `SetCurrentTimeline` — scoped precisely to these new/changed methods
  (not a whole-file scan, since those names legitimately exist elsewhere
  in the same file for `queue_render_job()`/`cancel_render()`).
- **`StartRendering()` outcome matrix (Rev2 — see §6 Findings 4–6).**
  `StartRendering()` is called at most once. Its outcome is resolved as:
  exact `False` → Resolve's own unambiguous rejection, plain
  `RenderJobError`, no reconciliation; exact `True` → reconciled via the
  bounded getter-only postcondition poll below, success if confirmed,
  otherwise `RenderStartReconciliationRequiredError`; an exception, or any
  return value that is neither `True` nor `False` → ambiguous, reconciled
  the same getter-only way — confirmed `Rendering` is still treated as
  success (the mutation call *did* happen and may well have taken effect
  despite the unusual signal), not confirmed raises
  `RenderStartReconciliationRequiredError`. `StartRendering()` is never
  called a second time under any outcome.
- **Postcondition / reconciliation**: bounded getter-only poll of
  `GetRenderJobStatus()` for `JobStatus == "Rendering"`
  (`_poll_for_rendering()`), reusing `cancel_render()`'s exact
  attempt/delay budget (5 attempts, 0.1s apart) under its own named
  constants (`_RENDER_START_POSTCONDITION_ATTEMPTS`/`_DELAY_SECONDS`).
  ~~Rev1: a postcondition timeout after the mutation call raised a plain
  `RenderJobError`~~ **— rejected by Rev1 review (Finding 6): once
  `StartRendering()` has actually been invoked, "not yet confirmed" is not
  the same claim as "did not happen," and must never be presented as an
  ordinary, safely-retryable failure.** Rev2 raises the distinct
  `RenderStartReconciliationRequiredError` for every unconfirmed outcome
  after the mutation call, whose docstring states explicitly: `StartRendering`
  was attempted, the final live state is not proven, and it must not be
  retried until manual, getter-only reconciliation establishes the truth.
- **`RenderManager.start_render(job_id: int) -> RenderJob`**: DB-level
  rejects (missing job, missing `resolve_job_id`, non-`QUEUED` status,
  **Rev2: missing/blank persisted `project_name`/`timeline_name`, and a
  start-time output-path recheck — see §6 Findings 1/2/8**) all happen
  before the start-specific `ResolveAdapter.start_render()` call. ~~Rev2
  said "before any Resolve contact"~~ **— corrected by Rev3 review
  (Finding 5): that phrasing falsely implies Resolve has not been
  connected to at all. `redline_core.runtime.composition` connects the
  adapter unconditionally before any CLI command dispatches, so Resolve
  contact may already exist by the time these checks run — what they
  actually prove is that no start-specific mutation call has happened
  yet.** Once the adapter call returns normally
  (proving `Rendering` via its own postcondition), persistence uses a
  **guarded `QUEUED -> RENDERING` transition**
  (`Database.transition_render_job_to_rendering()`, `UPDATE ... WHERE
  status = 'QUEUED'`, checking the affected row count) rather than an
  unconditional write. ~~Rev1: "on adapter failure, no DB write happens...
  so a fresh `start_render()` call remains safe and well-defined"~~ **—
  that claim was correct only for ordinary pre-mutation rejections, and
  Rev1 stated it without that qualification (Finding 4/6).** Rev2: if the
  adapter raises `RenderStartReconciliationRequiredError`, it propagates
  unchanged and no DB write happens — but this is *not* "safe to retry
  immediately," it means live Resolve state is unproven and must be
  reconciled manually first. If the adapter call instead returns normally
  (Resolve confirmed `Rendering`) but the guarded DB transition itself
  fails, raises, affects zero/multiple rows, or the row cannot be reloaded
  afterward, `RenderManager` raises the distinct
  `RenderStartPersistenceReconciliationRequiredError` (Finding 7) and
  never compensates by calling `StopRendering()`, deleting the Resolve
  job, or invoking `ResolveAdapter.start_render()` again.
- **CLI**: `redline render start <job_id>` — argument parsing →
  `RenderManager.start_render()` → output formatting only, no Resolve
  business logic. Prints "Render start confirmed" (not merely
  "requested") because the underlying postcondition has already
  independently established `Rendering` before the CLI ever runs. Rev2
  adds two new failure categories, `render start reconciliation required`
  and `render start persistence reconciliation required`, mapped ahead of
  the generic `render start failed` category so operators can distinguish
  "safe to retry once the underlying cause is fixed" from "do not touch
  this job again without manual reconciliation."
- **No `RLC-E9901` or its Resolve job ID anywhere in this construction.**
  Confirmed by grep across every changed production file. Those values
  belong only in a future one-shot harness, not reusable core logic.

## 4. Live authorization harness consideration

The mission asked whether a narrow RLC-E9901 one-shot start harness,
analogous to `scripts/rlc_e9901_queue_attempt_harness.py`'s pattern, is
justified as part of this construction.

**Recommendation: not yet, and not as part of this construction.**

Reasoning:

- The existing queue-attempt harness pattern earned its complexity because
  the *queue* pathway had a long, evidenced history of live-attempt
  failures and reconciliation ambiguity (Missions 39D/39D.1/39D.2/39D.3 —
  `AddRenderJob()` repeatedly returning an empty string, requiring the
  identity-unresolved/acceptance-not-observed classification split
  documented in `docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md`). No equivalent
  live evidence exists yet for `StartRendering()` — this construction has
  never contacted Resolve, so there is no known failure mode of the real
  API to design a harness's evidence-classification model around.
- A harness built *before* the underlying capability has ever been
  exercised live would be speculative in exactly the way the existing
  harness's own extensive revision history (Rev1→Rev7) shows is
  expensive to get right after the fact — each of those revisions exists
  because independent review found a false-pass or evidence gap only
  discoverable once real behavior was being reasoned about concretely.
  Building a start-specific harness now would mean guessing at that
  same process's conclusions in advance.
- The reusable production path itself (this construction) is the correct
  and sufficient artifact to publish first. A future mission can build a
  one-shot RLC-E9901 start harness the same way the queue harness was
  built: wrapping this exact production `render start <job_id>` command
  as an opaque subprocess launch, verifying exact commit/source hashes,
  requiring a clean repository, requiring the historical queue-closure
  evidence (`3c0af847-bddd-43ee-8b79-a7b64cb915b4`,
  `exact_single_job_match`) as its own precondition, performing one fresh
  getter-only pre-start guard, launching production `render start` exactly
  once, and never retrying — but that construction should follow, not
  precede, independent review of *this* reusable path, and ideally follow
  at least one live-verified `start_render()` call under a separate,
  narrowly scoped live-verification authorization (mirroring how
  `queue_render_job()`/`get_render_status()`/`cancel_render()` were each
  live-verified before RLC-E9901-specific harnesses were built around
  them).

**If Control Room disagrees and wants the harness built now:** it would
need its own separate mission, its own execution interlock (unreachable
without explicit authorization, exactly like `rlc_e9901_queue_attempt_harness.py`'s
`run-queue-attempt` subcommand), and would still not be authorized to
execute during its own construction — the same discipline already applied
to this mission and to every Phase 14 probe construction.

## 5. What this construction does NOT do

- Does not contact Resolve.
- Does not call `StartRendering`, `AddRenderJob`, `DeleteRenderJob`,
  `DeleteAllRenderJobs`, `StopRendering`, `SetRenderSettings`, or
  `LoadRenderPreset` anywhere outside their existing, already-reviewed
  call sites.
- Does not reference `RLC-E9901` or `3c0af847-bddd-43ee-8b79-a7b64cb915b4`
  in any production file.
- Does not build a live authorization harness.
- Does not stage, commit, or push.

## 6. Rev2 corrections — finding-by-finding

Independent exact-source review of the Rev1 bundle returned **REVISION
REQUIRED**. Ten findings, eight blocking. All ten are corrected in Rev2;
this section is the map from finding to fix.

1. **BLOCKING — bind expected project identity.**
   `ResolveAdapter.start_render()` now takes `project_name`/
   `timeline_name`/`resolve_job_id` explicitly (keyword-only).
   `RenderManager.start_render()` sources `project_name`/`timeline_name`
   from the persisted `RenderJob` and rejects a missing/blank value before
   the start-specific adapter call. `_require_exact_current_project()` requires
   `GetCurrentProject().GetName() == project_name` exactly, getter-only,
   never `LoadProject()`. New adapter tests cover: correct project, wrong
   current project, missing/blank current project name, malformed
   (non-string) current project name, and a `GetName()` exception.
2. **Bind timeline/queued-job identity.** `_require_exact_queued_job_identity()`
   requires exactly one `GetRenderJobList()` entry resolving to
   `resolve_job_id`, with that entry's own `TimelineName` equal to the
   persisted `timeline_name`, getter-only, never `SetCurrentTimeline()`.
   Fails closed on: job absent, duplicate matching ID, missing
   `TimelineName`, wrong `TimelineName`, and an invalid/non-list
   `GetRenderJobList()` return.
3. **BLOCKING — exact-False `IsRenderingInProgress` guard.** Changed from
   "reject only if exactly `True`" to "proceed only if exactly `False`";
   every other observed value (`True`, `None`, `0`, `1`, a string, a
   container, or any other object) now fails closed. Parametrized test
   covers all of those explicitly.
4. **BLOCKING — model the mutation-attempt boundary explicitly.**
   `start_render()` now performs every pre-mutation guard (Category A)
   before calling `_invoke_start_rendering_and_reconcile()`, which is the
   only place `StartRendering()` is invoked (Category B). New
   `RenderStartReconciliationRequiredError` (adapter layer) and
   `RenderStartPersistenceReconciliationRequiredError` (manager layer)
   distinguish "nothing was attempted, retry is fine once the precondition
   is fixed" from "an attempt happened and the outcome is unproven, do not
   retry automatically."
5. **BLOCKING — strict `StartRendering` return semantics.** Documented and
   implemented outcome matrix: exact `False` → immediate rejection, no
   reconciliation; exact `True`, an exception, or any non-boolean value →
   reconciled via a getter-only poll; confirmed `Rendering` is success
   regardless of which of those three produced it; not confirmed always
   raises `RenderStartReconciliationRequiredError`. `StartRendering()`
   is never called a second time.
6. **BLOCKING — postcondition timeout cannot leave a "safe retry" claim.**
   A postcondition timeout after the mutation call now raises
   `RenderStartReconciliationRequiredError`, not a plain `RenderJobError`.
   Manager/CLI tests prove: the mutation was attempted, the DB is never
   written for this outcome (job stays `QUEUED`, which reflects "unknown,"
   not "confirmed safe"), the error explicitly says reconciliation is
   required, and no second `StartRendering()` call ever happens.
7. **BLOCKING — DB persistence failure after confirmed live start.**
   `Database.transition_render_job_to_rendering()` performs a guarded
   `UPDATE ... WHERE status = 'QUEUED'` and reports whether exactly one
   row was affected. `RenderManager.start_render()` raises
   `RenderStartPersistenceReconciliationRequiredError` for a transition
   exception, a zero/multiple-row result, or a reload failure afterward —
   and never compensates by calling `StopRendering()`, deleting the
   Resolve job, or invoking `start_render()` again. Tests cover all four
   scenarios plus the successful single-row transition.
8. **HIGH — start-time output collision.** `RenderManager.start_render()`
   now rechecks the persisted `job.output_path` before any Resolve
   contact: missing/blank raises `RenderJobNotStartableError`; an existing
   file at that path raises `RenderOutputCollisionError`. This is
   additional to the existing queue-time collision check — the filesystem
   can change between queueing and starting. A future RLC-E9901 harness
   will independently repeat this check immediately before launch.
9. **Historical queue-attempt hash pins.** `scripts/rlc_e9901_queue_attempt_harness.py`'s
   `_MUTATION_BEARING_SOURCE_SHA256` pins are a historical evidence
   binding for the (separately reviewed) `render queue` pathway. This
   correction touches four of those eight pinned files
   (`render_commands.py`, `render/manager.py`, `resolve/adapter.py`,
   `db/database.py`) for reasons unrelated to that pathway. The pins
   themselves are **unchanged** — verified by
   `test_mutation_bearing_source_pins_are_exactly_the_historically_reviewed_values`,
   a byte-for-byte snapshot equality test. The harness is now
   intentionally, provably unable to authorize a live queue attempt
   against current on-disk bytes:
   `test_verify_mutation_bearing_source_identity_fails_closed_against_current_master`
   replaces the old test that asserted the (now-false) opposite, and
   asserts the specific mismatched file and error code. A companion
   parametrized test proves the four *untouched* pinned files still match
   their pins exactly, isolating the intentional incompatibility to
   exactly the files this correction actually changed.
10. **Broad regression evidence.** See `docs/CHANGELOG.md` for the exact
    baseline vs. Rev2 failure-set comparison (by test name, not just
    counts) for this revision.

Two documentation claims Rev1 made that independent review rejected have
been removed and corrected in place above (marked with strikethrough where
the original wording is preserved for context): "current-project-only is
acceptable because status/cancel already do it" (§2 Finding 8), and "a
fresh `start_render()` call is safe" as an unqualified claim about every
adapter failure (§3, `RenderManager.start_render()`).

## 7. Rev3 corrections — finding-by-finding

Independent exact-source review of the Rev2 bundle accepted Rev2's
architecture but found it not yet approved for publication or live
execution: seven further findings, four blocking. All seven are corrected
here.

1. **BLOCKING — strict render-queue Job-ID alias resolution.** Rev2's
   queued-job identity check called the legacy, precedence-based
   `_render_job_id_from_job()` (still used unchanged by
   `queue_render_job()`'s reconciliation and `cancel_render()`), which
   silently resolves a queue entry with contradictory alias evidence
   (e.g. `JobId="EXPECTED"` alongside `job_id="OTHER"`) to whichever alias
   comes first in precedence order. The start pathway now uses a new,
   start-owned `_strict_alias_value()` instead: every present alias is
   inspected, agreeing values are accepted, a `bool`/`int`/`dict`/any
   other non-`str` or blank value is malformed and fails closed, and
   conflicting valid values fail closed. A malformed entry anywhere in the
   queue — not only one that superficially looks related to the requested
   ID — fails the whole lookup closed, since its true identity can't be
   ruled out. Adversarial tests: sole canonical ID, two agreeing aliases,
   `JobId`+`job_id` disagreement, `JobId` as `int`/`bool`/`dict`/`list`,
   duplicate queue entries, and an unrelated malformed entry elsewhere in
   the same queue.
2. **BLOCKING — strict timeline alias resolution.** The same
   `_strict_alias_value()` model now governs the matched entry's timeline
   identity too: agreeing aliases accepted, conflicting or malformed
   values fail closed, and the resolved value must equal exactly the
   persisted `timeline_name`. Still never calls `SetCurrentTimeline()`.
3. **BLOCKING — bind the actual queued output destination.**
   `ResolveAdapter.start_render()` gained a fourth required keyword-only
   argument, `output_path: str`. A new `_require_exact_queued_output_destination()`
   strictly resolves the matched queue entry's `TargetDir`/`OutputFilename`
   (same alias-conflict/malformation rules as Findings 1/2) and requires
   them to equal exactly the directory/~~stem~~ **complete filename — see
   §8 Rev4 Finding 1, this was corrected against live evidence: Resolve's
   real `OutputFilename` includes the extension** derived from
   `output_path`. Never calls `SetRenderSettings()` or `LoadRenderPreset()`
   to reconcile a mismatch — the already-queued job's destination is
   immutable for this operation; a mismatch means stop, not repair.
   `RenderManager.start_render()` now threads the job's persisted
   `output_path` through to the adapter call. `MockResolveAdapter.start_render()`
   gained the same parameter and enforces the same logical binding against
   its own stored `TargetDir`/`CustomName` queue metadata. Adversarial
   tests: exact destination, wrong `TargetDir`, wrong `OutputFilename`,
   missing either, and conflicting output aliases.
4. **BLOCKING — stop inferring safety from an exact `False` return.** Rev2
   treated `StartRendering(...) is False` as Resolve's unambiguous,
   no-side-effect rejection and raised immediately without reconciliation.
   The reviewed local SDK excerpt establishes only `StartRendering(...)
   --> Bool` — no stronger documented guarantee that `False` proves
   nothing happened. `_invoke_start_rendering_and_reconcile()` now treats
   `True`, `False`, an exception, and any non-boolean return identically:
   every one of them is resolved through the same bounded, getter-only
   `_poll_for_rendering()` check. Confirmed `Rendering` is success
   regardless of the raw signal; not confirmed always raises
   `RenderStartReconciliationRequiredError`, including for an exact
   `False`. `StartRendering()` is still never called a second time. Added
   the two required adversarial regressions: `False` return but
   `GetRenderJobStatus` proves `Rendering` → succeeds, DB may transition,
   exactly one `StartRendering()` call; and `False` return with
   `Rendering` never established → reconciliation-required, no second
   call.
5. **HIGH — corrected Resolve-contact-boundary wording.** Rev2 repeatedly
   said manager-level preconditions run "before any Resolve contact,"
   which is not true for the real production CLI:
   `redline_core.runtime.composition.build_application_services()`
   connects the Resolve adapter unconditionally before any CLI command
   dispatches, so Resolve contact may already have occurred by the time
   `RenderManager.start_render()`'s own checks run. Corrected throughout
   this document, `docs/ARCHITECTURE.md` §3.8, the `render/exceptions.py`
   docstrings, and `render/manager.py`'s own docstrings/comments to say
   "before the start-specific `ResolveAdapter.start_render()` call" (or
   equivalent) instead. Four test names in `tests/unit/test_render_manager.py`
   with a `..._before_resolve_contact` suffix were renamed to
   `..._before_adapter_start_call`. The safety guarantee these
   preconditions actually provide — zero `StartRendering()` calls, not
   zero Resolve connection — is unchanged; only the prose describing it
   was wrong.
6. **Persisted identity hardening.** `RenderManager.start_render()` now
   validates `resolve_job_id`/`project_name`/`timeline_name`/`output_path`
   through a new `_require_usable_persisted_string()` helper: a
   non-`str` value (a `bytes`/BLOB value is the realistic way this can
   happen through SQLite's own TEXT-affinity coercion rules — a literal
   `INTEGER`/`REAL` written into a TEXT-affinity column is converted to
   text by SQLite itself before storage, so a `bytes` value written via a
   `BLOB` literal is the only practical way to get a non-`str` Python
   value back) is rejected outright, and a blank or
   leading/trailing-whitespaced value is rejected rather than silently
   `.strip()`-ed and accepted. Tests cover both cases for all four fields.
7. **Wording corrections.** The start-time output collision message
   changed from "Resolve queue submission was not attempted" (accurate
   for the pre-existing *queue-time* collision check this start-time
   recheck mirrors, but wrong for a *start* operation) to "Render start
   mutation was not attempted." The review-bundle manifest's description
   of its own checksum model was also corrected — see the Rev3 bundle's
   own `MANIFEST.md` for the accurate wording (Rev2's manifest claimed
   `MANIFEST.md` was omitted from `SHA256SUMS.txt` "to avoid
   self-reference," but the actual Rev2 bundle *included* `MANIFEST.md`'s
   hash in `SHA256SUMS.txt` and omitted `SHA256SUMS.txt`'s own hash
   instead — the Rev3 manifest states this correctly).

Static safety was extended, not just preserved: the AST proof's start-path
function scope now includes `_strict_alias_value()` and
`_require_exact_queued_output_destination()`, and two new tests prove each
of those helpers touches nothing beyond pure dict/path logic plus the
already-getter-only helpers — neither one can be a hidden second mutation
path.

## 8. Rev4 correction — one narrow BLOCKING integration mismatch

Independent exact-source review of the Rev3 bundle **ACCEPTED** the
overall start-pathway architecture and safety model. One narrow BLOCKING
finding remained, evidence-backed rather than speculative.

**Finding 1 (BLOCKING) — Resolve's `OutputFilename` includes the
extension.** Rev3's `_require_exact_queued_output_destination()` derived
`Path(expected_output_path).stem` (the extensionless filename) and
compared it against the matched queue entry's `OutputFilename`. This is
inconsistent with already-preserved live getter-only evidence from the
real RLC-E9901 Resolve render queue:

```text
Evidence artifact: RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json
SHA-256: f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975
Captured against: DaVinci Resolve Studio 21.0.3.7 (live getter-only snapshot)

Expected persisted output:
C:\Users\pj198\RedlineOSLive\RLC-E9901\_episodes\RLC-E9901\exports\RLC-E9901_MASTER.mov

Observed Resolve GetRenderJobList() entry:
TargetDir      = C:\Users\pj198\RedlineOSLive\RLC-E9901\_episodes\RLC-E9901\exports
OutputFilename = RLC-E9901_MASTER.mov
VideoFormat    = QuickTime
VideoCodec     = Avid DNxHR HQX 10-bit
```

Rev3 would have derived the expected filename as `RLC-E9901_MASTER` (stem
only) and compared it against the real, observed `RLC-E9901_MASTER.mov` —
an exact-string mismatch that fails closed before `StartRendering()` is
ever reached, for every real queued job, not just RLC-E9901's. This
evidence artifact is historical and was not modified by this correction;
its SHA-256 was independently re-verified against the file on disk before
being cited here and in the corrected source/test comments.

**Correction.** `_require_exact_queued_output_destination()` now derives:

```python
expected_path = Path(expected_output_path)
expected_target_dir = expected_path.parent
expected_output_filename = expected_path.name  # complete filename, extension included
```

and requires the queue entry's strictly-resolved `OutputFilename` to equal
`expected_output_filename` exactly — never `.stem`. No extension is
stripped from the persisted path, and none is inferred from
codec/format/preset; the extension is simply read directly from
`output_path`, which already carries it. `TargetDir` binding is
unchanged. Still no `SetRenderSettings()`/`LoadRenderPreset()` call under
any outcome — a mismatch still means stop, not repair.

**Regression tests** (`tests/unit/test_resolve_script_adapter_render_start.py`):
`test_start_render_extension_bearing_output_filename_matches_and_starts`
(a queue entry shaped exactly like the real observed evidence —
`OutputFilename` with extension — against a matching `.mov` expected path
passes identity verification and calls `StartRendering()` exactly once)
and `test_start_render_extensionless_output_filename_fails_closed` (the
inverse: a stem-only `OutputFilename` — what Rev3 incorrectly expected —
fails closed with zero `StartRendering()` calls). The existing default
fixture (`EXPECTED_OUTPUT_FILENAME`, renamed from `EXPECTED_OUTPUT_STEM`)
was also updated to `Path(OUTPUT_PATH).name` so every other Finding-3 test
now exercises the corrected, evidence-matching shape rather than the
incorrect one. Values are generic (`RLC-E001`-style), not hard-coded to
RLC-E9901; the RLC-E9901 shape is used only in the two evidence-shaped
regression tests above and in the mission's own example.

**Mock fidelity.** `MockResolveAdapter.start_render()`'s internal
`CustomName`-vs-stem check is retained unchanged as an *internal
implementation detail* — `MockResolveAdapter.queue_render_job()` only ever
receives the extensionless `custom_name` (Redline's own
`SetRenderSettings({"CustomName": ...})` write-time convention, per
`RenderOutputPlan.output_stem`) from its caller, with no extension
available to reconstruct a complete filename from, and this correction
does not introduce speculative preset/format-driven extension-inference
logic to manufacture one. What changed is the mock's own docstring: it
no longer claims `CustomName` is "logically equivalent" to real Resolve's
`OutputFilename` representation. It now states explicitly that
`CustomName` models queue-*input* identity (what `RenderManager` wrote),
not the queue-*readback* shape Resolve reports back — and that the
real-adapter tests are the authoritative coverage for `OutputFilename`'s
actual (complete-filename) representation.

**Static safety.** Re-run unchanged (still exactly one `StartRendering`
call site; still zero start-path reachability into `AddRenderJob`/
`DeleteRenderJob`/`DeleteAllRenderJobs`/`StopRendering`/`SetRenderSettings`/
`LoadRenderPreset`/`LoadProject`/`SetCurrentTimeline`). One static-safety
test's allowed-attribute set was updated from `{..., "stem"}` to
`{..., "name"}` to match the corrected implementation — no new attribute
surface, no prohibited name added.

No other Rev3-accepted property was touched: identity binding shape,
strict alias handling for Job-ID/timeline, `IsRenderingInProgress()`
exact-`False`, the `StartRendering()` outcome matrix, reconciliation
errors, the guarded DB transition, the start-time filesystem collision
check, and the historical queue-harness pins are all unchanged from Rev3.
