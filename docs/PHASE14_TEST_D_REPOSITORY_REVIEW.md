# Phase 14 Test D — Construction r4 (Staged Publication Candidate) Repository Review

Review status: **NATIVE-VERIFIED; r1, r2-STAGED-DIFF, AND FINAL-r3-STAGED-DIFF FINDINGS CORRECTED; EXACT-BYTE HARDENED; r4 IS THE STAGED EIGHT-PATH PUBLICATION CANDIDATE; UNDERGOING FINAL STAGED-DIFF PUBLICATION REVIEW; LIVE EXECUTION PROHIBITED**

Construction revision: `phase14-test-d-video-payload-isolation-construction-r4` (the Git index now reflects this revision — see "Publication-state update" below for the completed index transition)

## Scope reviewed

Repository checkpoint reviewed:

- branch: `master`
- HEAD: `33b324220b3fbfe66def17b0e6587d55042e4c92`
- origin: `git@github.com:Choice283/redline-os.git`

Exact integrated construction artifacts (r2 baseline, r3 corrections reviewed below):

- `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`
- `docs/PHASE14_TEST_D_STATIC_REVIEW.md`
- `scripts/phase14_test_d_queue_attempt.py`
- `tests/unit/test_phase14_test_d_queue_attempt.py`

The repository copies matched the reviewed r2 construction hashes after local integration. Native Windows Python 3.11.9 compilation passed, the focused Test D suite passed with 35 tests, and the combined Phase 14 snapshot/Test D regression slice passed with 136 tests. HEAD remained unchanged and the Git index remained empty. No Resolve contact, Control timeline mutation, render-queue mutation, SQLite access, staging, commit, or push occurred.

An independent r2-staged-diff review subsequently found two further Important findings, corrected in construction r3 (below). The repository copies of the four r3 construction artifacts matched the reviewed r3 construction hashes exactly. Native Windows Python 3.11.9 compilation passed, the focused Test D suite passed with **41 tests**, and the combined Phase 14 focused regression slice passed with **142 tests**. Throughout the r3 correction review, HEAD remained `33b324220b3fbfe66def17b0e6587d55042e4c92` and the Git index retained the reviewed r2 publication-candidate state unchanged; only the working tree carried the r3 corrections. No Resolve contact, Control timeline mutation, render-queue mutation, or SQLite access occurred during that review. This document, `docs/CHANGELOG.md`, and `docs/ROADMAP.md` are updated to r3 and the eight-path r3 publication candidate was staged under separate, explicit founder authorization tied to that review.

A final independent review of the exact staged r3 bytes (the `git diff --cached` output for all eight paths) subsequently found one further Important finding, corrected in construction r4 (below). **Historical note:** construction r4 was first authorized and reviewed strictly as an unstaged working-tree correction layered over the seven authorized files; at that point the staged r3 eight-path candidate, including `.gitattributes`, was explicitly preserved in the Git index and not touched. The repository copies of the four modified r4 construction artifacts were independently hashed against the working tree at that stage. Native Windows Python 3.11.9 compilation passed, the focused Test D suite passed with **48 tests**, and the combined Phase 14 focused regression slice passed with **149 tests**. Throughout that construction-and-review step, HEAD remained `33b324220b3fbfe66def17b0e6587d55042e4c92`, the staged path set remained exactly the r3 eight paths, and the unstaged path set was exactly the four modified files (`docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, `docs/PHASE14_TEST_D_STATIC_REVIEW.md`, `scripts/phase14_test_d_queue_attempt.py`, `tests/unit/test_phase14_test_d_queue_attempt.py`) plus this document, `docs/CHANGELOG.md`, and `docs/ROADMAP.md`. No Resolve contact, Control timeline mutation, render-queue mutation, SQLite access, staging, unstaging, commit, or push occurred during that construction-and-review step.

## Publication-state update: r4 index integration completed

Paul Jones subsequently and separately authorized the Phase 14 Test D r4 publication-candidate index integration. Under that authorization, the seven reviewed r4 paths (`docs/CHANGELOG.md`, `docs/ROADMAP.md`, `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, `docs/PHASE14_TEST_D_STATIC_REVIEW.md`, `scripts/phase14_test_d_queue_attempt.py`, `tests/unit/test_phase14_test_d_queue_attempt.py`) were staged, and the existing staged `.gitattributes` blob was preserved unchanged and not restaged. The resulting Git index now contains the exact eight-path r4 publication candidate, and the working tree is clean relative to the index (zero unstaged drift).

Independently re-verified after that integration: HEAD remained `33b324220b3fbfe66def17b0e6587d55042e4c92`; the four hash-bound staged artifacts — execution contract, static review, harness, and focused tests — matched their reviewed r4 SHA-256 values exactly when hashed directly from the Git index (`git cat-file -p`), not merely the working tree; `git check-attr` reported `text: set` / `eol: lf` for all four; native Windows Python 3.11.9 compilation passed; the focused Test D suite reproduced **48 passed**; the combined Phase 14 focused regression reproduced **149 passed, 1327 deselected**; and `git diff --cached --check` exited 0.

A subsequent final staged-diff publication review of the complete `git diff --cached` for all eight paths found no code or safety-boundary defect, but identified exactly the documentation-status issue this section itself corrects: prior wording in this document, `docs/ROADMAP.md`, and `docs/CHANGELOG.md` still described construction r4 as unstaged after the index integration had already completed. This document, together with the corresponding sections of `docs/ROADMAP.md` and `docs/CHANGELOG.md`, was updated under a separate, explicit founder authorization limited to that reconciliation; no harness, test, execution-contract, static-review, or `.gitattributes` byte was touched by that correction.

Commit, push, and live Test D execution remain unauthorized. `EXECUTION_ENABLED` remains `False`.

## r1 Important finding 1 — corrected in r2

Construction r1 computed the final pre-add state before the one-shot `AddRenderJob()` call but did not durably persist that state until the queue-attempt function returned.

Construction r2 now requires `pre_add_evidence.json` to be successfully persisted before `AddRenderJob()` can be called. The evidence writer uses a unique sibling temporary path, UTF-8/LF JSON, flush, file `fsync`, close, and atomic `os.replace()`; directory `fsync` is attempted where supported. Failure to persist the pre-add checkpoint stops before queue mutation.

If `AddRenderJob()` returns normally, its direct result is independently persisted to `add_render_job_result.json`. Post-call queue/rendering/identity/timeline/Media Pool observations and classification are independently persisted to `post_add_evidence.json`. Focused tests prove that the pre-add checkpoint exists before the sole queue call, that checkpoint-write failure leaves the queue-call count at zero, and that a synthetic `AddRenderJob()` exception leaves the pre-add checkpoint preserved.

Verdict: **CORRECTED**.

## r1 Important finding 2 — corrected in r2

Construction r1 recorded the active render format/codec but did not require them to match the reviewed Broadcast Master context.

Construction r2 makes `GetCurrentRenderFormatAndCodec()` a mandatory isolation gate after the reviewed preset/settings mutations and immediately before the final queue-attempt gate. The accessor must be callable, return a dictionary, and report exactly:

- `format == "mov"`
- `codec == "DNxHRHQX_10"`

Unavailable, exceptional, non-dictionary, or mismatched render context fails closed before `AddRenderJob()`. Focused tests cover the expected values, wrong format, wrong codec, unavailable accessor, non-dictionary return, accessor exception, and an execution-path mismatch proving zero queue calls.

Verdict: **CORRECTED**.

## r2 staged-diff Important finding 1 — corrected in r3

Independent review of the r2 staged diff found that `add_render_job_result.json` was written immediately after the sole `AddRenderJob()` call and before the post-call queue/rendering/identity/timeline/Media Pool observations. A failure of that single write could therefore abort `execute_test_d()` before any best-effort observation of the resulting queue state — losing exactly the evidence needed to understand what the one-shot mutation did.

Construction r3 keeps the pre-add checkpoint fail-closed (unchanged from r2: a pre-add persistence failure still stops execution before `AddRenderJob()` is called), but changes how a **post-mutation** evidence-write failure is handled:

- a failure to persist `add_render_job_result.json` after `AddRenderJob()` returns is caught, recorded in an in-memory `evidence_errors` list, and does not prevent the read-only post-call observations (queue, rendering state, project/timeline identity, timeline snapshot, Media Pool inventory) from running;
- any recorded evidence-write failure forces the final `outcome.classification` to `inconclusive`, even if the queue observation would otherwise satisfy `accepted` or `rejected`;
- a failure to persist `post_add_evidence.json` after those observations complete is caught and recorded the same way, and likewise forces `inconclusive` without discarding the observations already collected;
- no retry or cleanup is introduced at any point.

Verified directly against `scripts/phase14_test_d_queue_attempt.py` (the `try`/`except` blocks around both evidence writes in `execute_test_d`, lines ~1009–1150) and exercised by two new focused tests, `test_add_result_evidence_write_failure_still_observes_queue` and `test_post_add_evidence_write_failure_returns_observed_inconclusive_result`, both of which assert the post-call observations are still collected and the classification is forced to `inconclusive`.

Verdict: **CORRECTED**.

## r2 staged-diff Important finding 2 — corrected in r3

Independent review of the r2 staged diff found that `validate_test_d_snapshot()` recorded the post-removal timeline end frame but did not constrain it, and a unit test explicitly exercised an arbitrary value (`99999`) as passing. This was broader than the contract's own claim that Test D changes exactly one variable (video-item presence).

Construction r3 restricts the post-removal end frame to exactly two justified values, `EXPECTED_TEST_D_END_FRAMES = frozenset({86424, 86544})`: `86424` if Resolve shrinks the timeline end to the retained audio item's end, or `86544` if Resolve retains the reviewed pre-removal Control end. Any other value, any non-integer, or a boolean now fails closed via `_require` inside `validate_test_d_snapshot()` before render-context mutation or queue submission. This gate runs inside `_pre_add_snapshot()`, which construction r3 calls three times before the sole `AddRenderJob()` call (`execute_test_d` lines ~939, ~944, ~973) — confirmed by direct source trace, so the gate is enforced before queue mutation, not merely documented.

Verdict: **CORRECTED**.

## Independent r1-to-r2 safety review

The r2 correction diff preserves the Test D experiment boundary:

- original disposable Control project/timeline remains the experimental target;
- Production remains prohibited;
- `EXECUTION_ENABLED = False` remains in construction r2;
- exactly one AST-visible `AddRenderJob()` call exists;
- exactly one AST-visible `LoadRenderPreset()` call exists;
- exactly one AST-visible `SetRenderSettings()` call exists;
- no retry path is introduced;
- no render start/stop or render-job deletion is introduced;
- no project loading or timeline switching is introduced;
- no harness media import, clip insertion/deletion, timeline creation/deletion, or SQLite path is introduced;
- accepted jobs remain queued for later independently authorized cleanup;
- the one manual Control video-item deletion remains a future separately authorized setup action and is not performed by the harness.

No Critical or Important harness-correctness finding remains from the r1-to-r2 correction review.

## Independent r2-to-r3 safety review

Re-verified all of the invariants above directly against the r3 harness source and its AST-based static tests, plus the two new r3-specific properties:

- `EXECUTION_ENABLED = False` remains in construction r3;
- exactly one AST-visible `AddRenderJob()` call, one `LoadRenderPreset()` call, and one `SetRenderSettings()` call exist (confirmed both by grep and by the harness's own `ast`-based static tests);
- no `StartRendering`, `StopRendering`, render-job deletion, project load, timeline switch, timeline/media mutation, or `sqlite3` import exists anywhere in the harness;
- no retry path is introduced by either r3 correction;
- the durable pre-add checkpoint and the mandatory exact `mov` / `DNxHRHQX_10` render-context gate from r1/r2 are unchanged and still enforced before `AddRenderJob()`;
- the new post-mutation evidence-failure handling never suppresses read-only post-call observation and always forces `inconclusive`;
- the new end-frame gate (`86424` or `86544` only) is enforced before queue mutation, not only documented.

No Critical or Important harness-correctness finding remains from the r2-staged-diff-to-r3 correction review. `git diff --check` against the four r3 working-tree files reported no whitespace or line-ending errors.

## Final r3 staged-diff publication review Important finding — corrected in r4

The final independent review of the staged r3 eight-path candidate (performed against the exact `git diff --cached` bytes, separately from this document) found one further Important finding: `validate_test_d_snapshot()`'s accepted-value gate (`86424` or `86544`) checked each of the three pre-`AddRenderJob()` snapshots independently. A run could therefore observe `86424` at the first snapshot and `86544` at a later one without failing, because both values individually remained in the justified set — an unauthorized second experimental variable hiding behind two individually-valid values.

Construction r4, built as an unstaged working-tree layer over the preserved r3 index, corrects this without touching the accepted-value set itself:

- the first Test D snapshot in a run (`initial`) binds whichever of `86424`/`86544` it observes as that run's expected end frame;
- `_pre_add_snapshot()` now accepts an `expected_end_frame` parameter, threaded into `validate_test_d_snapshot()`; the second (`pre_render_context`) and third (`final_guard`) pre-`AddRenderJob()` snapshots pass the bound value and must match it exactly, raising and failing closed before queue mutation on a mismatch;
- the post-`AddRenderJob()` timeline observation is checked against the same bound value using the identical run-bound-value parameter; a mismatch there is caught by the existing observational `post_errors` mechanism (it never raises out of `execute_test_d()`) and forces the final result to `inconclusive`, without repairing, retrying, or restoring anything.

Verified directly against the r4 working-tree source (`_pre_add_snapshot` and `execute_test_d` in `scripts/phase14_test_d_queue_attempt.py`) and exercised by five new focused `execute_test_d()`-level tests plus two granular `validate_test_d_snapshot()` tests: drift at the pre-render-context snapshot fails closed with zero `AddRenderJob()` calls; drift surviving to the final pre-add guard also fails closed with zero calls; drift appearing only in the post-call observation still allows exactly one `AddRenderJob()` call but forces `inconclusive`; and runs stable at `86424` or stable at `86544` throughout each remain valid and reach `accepted`.

Verdict: **CORRECTED**.

## Independent r3-to-r4 safety review

Re-verified all previously confirmed invariants directly against the r4 harness source and its AST-based static tests:

- `EXECUTION_ENABLED = False` remains in construction r4;
- exactly one AST-visible `AddRenderJob()` call, one `LoadRenderPreset()` call, and one `SetRenderSettings()` call exist;
- no `StartRendering`, `StopRendering`, render-job deletion, project load, timeline switch, timeline/media mutation, or `sqlite3` import exists anywhere in the harness;
- no retry, repair, or restoration path is introduced by the r4 correction;
- the durable pre-add checkpoint, the mandatory exact `mov` / `DNxHRHQX_10` render-context gate, and the r3 post-mutation evidence-failure handling are all unchanged and still enforced;
- the new temporal end-frame stability check is itself observational-only post-`AddRenderJob()` — it raises internally only inside the existing try/except that was already used for post-call validation, so it can never escape and trigger a mutation.

No Critical or Important harness-correctness finding remains from the final-r3-staged-diff-to-r4 correction review. `git diff --check` against the four modified r4 working-tree files reported no whitespace or line-ending errors. Native Windows Python 3.11.9 verification reproduced compilation PASS, the focused Test D suite passed with **48 tests** (41 existing + 7 new), and the combined Phase 14 focused regression slice passed with **149 tests** (142 existing + 7 new).

**Historical note:** at the time of this safety review, construction r4 had been performed entirely as an unstaged working-tree layer over the seven authorized files, and the existing staged r3 eight-path publication candidate, including `.gitattributes`, had been left untouched in the Git index throughout the review; no staging, unstaging, commit, or push had yet occurred. Paul Jones subsequently authorized the r4 index integration described in "Publication-state update" above, under which those same seven files were staged over the preserved r3 candidate. Commit and push remained — and remain — unauthorized.

## Exact-byte publication hardening

The native r1-to-r2 diff review emitted Git warnings that LF working-tree content could later be converted to CRLF. Because Test D review/publication binds exact SHA-256 values to the construction artifacts, line-ending conversion would create avoidable byte drift.

This repository-review mission therefore adds `text eol=lf` rules in `.gitattributes` for the four r2 construction artifacts listed above. The hardening is publication policy only: it does not alter the reviewed r2 artifact bytes.

The repository review requires all four artifacts to retain their exact SHA-256 values and LF-only working-tree bytes after the attribute change, and requires `git check-attr` to report `text: set` and `eol: lf` for each path. `.gitattributes` itself is carried forward unchanged from the existing staged r2 blob by this r3 canonical-documentation update.

Exact r2 construction hashes (historical; superseded by the r3 bytes below):

- execution contract: `7fd8dc545761231c5b9bcfb9db083ada61caf6f11b7c0b40a4c55904f6cef5f8`
- static review: `f45a706c0bfe17c916b065ee484a69a51902f29babe1f03cf90c54a88a9731c8`
- harness: `11bc77403910d67dff342eb20af73cd75ac39d47f9baedf2023c0fa015d68d7a`
- focused tests: `fa23102e3177b64e8ab8a5892b3aa913e9e3d282405a67c9915009b15152d4f4`

Exact r3 construction hashes (historical; superseded by the r4 bytes below; these remain the exact bytes of the preserved staged r3 index):

- execution contract: `d68f7fbb613629b6c6d3d52f145ed7486e1068219874e05cf34b84c8a000c8db`
- static review: `18300fa053a1cb422e3786c593f5fa8b5df59e4a780702d8603827d60d881a71`
- harness: `9b0c43585399af0b42752ed52dc3616fd58ab4c83359f1db7fa63d28c8b22238`
- focused tests: `117b7c401e1cc445de3af5baf6ad47309defd20a7295b108382535edb126de2d`

Exact r4 construction hashes (current staged bytes; independently re-verified directly from the Git index after the r4 index-integration authorization, in addition to the working-tree hashes computed immediately after the r4 correction):

- execution contract: `e4b9cfdc1121f322a42633c6da4e15c54de4bb8f55a28812b9f516d421814b1d`
- static review: `1b05e10ce6efb11672338b2265a667599fc9937b14d39cfe3a77712a08bac4a5`
- harness: `a70d0df5a7fe91a1315e19cb56f16cda50ba1044af4e4dbc515017f0f8ca123d`
- focused tests: `9c40d6821932d4c6201604521a150924204b17b047a96c1f80a5fb444ddc1b64`

## Verdict

Construction r4 is the **STAGED EIGHT-PATH PUBLICATION CANDIDATE**, following its separately authorized index integration, and is undergoing/following final staged-diff publication review at the repository-review level. This verdict means the two r1 Important findings (corrected in r2), the two r2-staged-diff Important findings (corrected in r3), and the one final-r3-staged-diff Important finding (corrected in r4) are all corrected; native verification reproduced 48 focused Test D passes and 149 combined Phase 14 focused passes against the staged content; the exact-byte publication-hardening gap remains addressed for the unchanged four-file `.gitattributes` pin; and the final staged-diff publication review that examined the complete eight-path `git diff --cached` found no code or safety-boundary defect, only the documentation-status issue this revision of the document corrects.

It does **not** authorize commit, push, Resolve contact, Control timeline mutation, `AddRenderJob()`, SQLite access, or live Test D execution. `EXECUTION_ENABLED` remains `False`. Staging itself is complete and separately authorized; commit and push are each their own future authorization and have not been granted.

Required next gates:

1. obtain one final staged-diff publication review confirming this documentation reconciliation is itself accurate and complete;
2. commit only under separate, explicit founder authorization;
3. push only under further separate explicit founder authorization;
4. verify the pushed commit and exact published artifact bytes;
5. construct and independently review a minimal execution-enablement revision tied to that published checkpoint;
6. obtain fresh explicit founder authorization for the one manual Control video-item deletion plus exactly one Test D queue attempt.

Until those gates pass, **do not remove the Control video item and do not run Test D live**.
