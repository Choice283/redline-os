# Phase 14 Test D — Construction r4 Static Review

Review status: **PASS FOR r4 CONSTRUCTION REVIEW; LIVE EXECUTION REMAINS PROHIBITED**

Construction revision: `phase14-test-d-video-payload-isolation-construction-r4`

## Scope

Construction r4 is limited to the single Important finding identified during the final r3 staged-diff publication review. It does not redesign the experiment, alter the target project/timeline, add retries, or authorize Resolve contact.

## r2 staged-diff Important finding 1 — corrected

In r2, `add_render_job_result.json` was written immediately after the sole `AddRenderJob()` call and before post-call queue/rendering/project observations. A failure of that write could therefore abort the function before best-effort observation of the queue state.

r3 keeps the pre-add checkpoint fail-closed, but treats **post-mutation** evidence persistence differently:

- `pre_add_evidence.json` must still be durably written before `AddRenderJob()`; failure prevents the queue call.
- after `AddRenderJob()` returns, failure to persist `add_render_job_result.json` is caught and recorded in `evidence_errors`; post-call read-only observations still run.
- a direct-result evidence-write failure forces the final result to `inconclusive`, even if the queue observation otherwise satisfies `accepted` or `rejected`.
- failure to persist `post_add_evidence.json` is also caught after observations, recorded, and forces `inconclusive`.
- no retry or cleanup is introduced.

Focused tests prove that a synthetic direct-result evidence-write failure still reaches the post-add queue read and preserves the observed queue state, and that a synthetic post-add evidence-write failure returns the already-collected observations with an `inconclusive` result.

## r2 staged-diff Important finding 2 — corrected

r2 allowed any timeline end frame after removal of the trailing video item, including the test value `99999`. That was broader than the contract's claim that only a derived end-frame change was permitted.

r3 allows exactly two justified values:

- `86424`: the reviewed retained audio item ends here, so Resolve may shrink the timeline to the last retained timeline item;
- `86544`: the reviewed pre-removal Control end, which Resolve may retain after item deletion.

Any other value, any non-integer value, or a boolean fails closed before render-context mutation or queue submission. Tests cover both allowed values, `99999`, a string value, and a boolean value.

## r3 staged-diff Important finding — corrected

The final r3 staged-diff publication review found that the r3 accepted-value end-frame gate checked each of the three pre-`AddRenderJob()` snapshots in isolation: a run could observe `86424` at one snapshot and `86544` at a later one without failing, because both values individually remained in the justified set. That let the end frame drift mid-run without being caught — a second, unauthorized experimental variable hiding behind two individually-valid values.

r4 adds temporal stability on top of the unchanged accepted-value set (`86424` or `86544`):

- the first Test D snapshot in a run (`initial`) binds whichever of the two values it observes as that run's expected end frame;
- the second pre-`AddRenderJob()` snapshot (`pre_render_context`) and the third (`final_guard`, immediately before the sole `AddRenderJob()` call) must each report that exact same value; a mismatch raises and fails closed before queue mutation, so `AddRenderJob()` is never called;
- the post-`AddRenderJob()` timeline observation is checked against the same bound value; a mismatch there is recorded as a post-call error (the existing observational, non-raising-outward mechanism) and forces the final result to `inconclusive` — the mutation has already happened and the harness only observes, it does not repair, retry, or restore.

Focused tests prove: a drift from `86424` to `86544` at the pre-render-context snapshot fails closed with zero `AddRenderJob()` calls; a drift surviving to the final pre-add guard also fails closed with zero calls; a drift appearing only in the post-call observation still allows exactly one `AddRenderJob()` call but forces `inconclusive`; and a run stable at `86424` throughout, or stable at `86544` throughout, remains valid and reaches `accepted`.

## Unchanged safety boundaries

- `EXECUTION_ENABLED = False`.
- original disposable Control project/timeline remains the target.
- Production remains prohibited.
- exactly one AST-visible `AddRenderJob()` call.
- exactly one AST-visible `LoadRenderPreset()` call.
- exactly one AST-visible `SetRenderSettings()` call.
- no retry path.
- no render start/stop or render-job deletion.
- no project loading, timeline switching, timeline/media mutation by the harness.
- no SQLite import/path.
- r1/r2/r3 protections remain: durable pre-add checkpoint, exact `mov` / `DNxHRHQX_10` render-context gate, and post-mutation evidence-write failures that continue best-effort observation while forcing `inconclusive`.
- the r4 temporal end-frame stability check is itself observational-only post-`AddRenderJob()`: it never restores the timeline, retries `AddRenderJob()`, deletes a render job, or switches projects/timelines.

## Construction verification

Executed in the construction environment:

- Python compilation: PASS
- focused mocked/static pytest suite: **48 passed**
- combined Phase 14 focused regression: **149 passed**
- AST-visible `AddRenderJob()` calls: 1
- AST-visible `LoadRenderPreset()` calls: 1
- AST-visible `SetRenderSettings()` calls: 1
- prohibited mutation intersection: empty
- SQLite import scan: empty
- exact-byte files: LF-only with final newline

Native Windows Python 3.11.9 verification remains a separate host gate.

## Live-readiness verdict

Construction r4 remains **hard-disabled and not live-authorized**. Construction/static/native verification does not authorize Control video removal, Resolve contact, `AddRenderJob()`, cleanup, staging changes, commit, or push.
