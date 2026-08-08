# Phase 14 Test D — Video-Payload Isolation Execution Contract

Status: **construction revision r4 — live execution prohibited**
Construction revision: `phase14-test-d-video-payload-isolation-construction-r4`

## 1. Authority and purpose

This contract defines a future one-shot controlled experiment. It does not itself authorize live execution.

Governing rule: **Agents advise. Paul decides.**

Test D asks one question only:

> If the exact known-working disposable Control project and timeline are preserved, but the timeline's single video item is removed while its audio payload, markers, track structure, Media Pool, and exposed project/timeline configuration remain otherwise unchanged, does DaVinci Resolve still accept one `Redline Broadcast Master` render-queue submission?

A Test D result may strengthen or weaken the missing-renderable-video hypothesis. It may not be described as proof of causation unless the exact accepted/rejected predicates in this contract are satisfied and the evidence is independently reviewed.

## 2. Why Test D uses the original disposable Control timeline

An earlier design proposed duplicating the Control timeline and deleting video from the duplicate. Static architecture review rejected that design because timeline duplication changes timeline identity as well as video payload. A rejection on the duplicate could therefore be caused by hidden duplicate-timeline state rather than video absence.

Test D instead uses the original disposable Control target:

- project: `redline-os-test-duplicate`
- timeline: `RLO-LIVE-ASM-92701_TIMELINE`

This is intentionally a disposable Control context. The pre-change state is already preserved in the independently reviewed Rev8 Control evidence. Production remains untouched.

The only intentional Resolve-content change before the queue experiment is removal of the one timeline video item. A derived end-frame change caused by that removal is permitted and recorded; it is not treated as a second independent mutation.

## 3. Evidence basis and immutable baseline

The reviewed Rev8 Control evidence established:

- Resolve Studio `21.0.3.7`
- project `redline-os-test-duplicate`
- timeline `RLO-LIVE-ASM-92701_TIMELINE`
- project/timeline canonical `GetSetting()` SHA-256: `71430f17446c1b4d2019f4ff4d73b6a9ab4154124255c31eecfd7cd3f21d355c`
- start frame `86400`
- pre-Test-D end frame `86544`
- one audio track with one enabled 24-frame WAV item
- one video track with one enabled 120-frame PNG still
- one empty subtitle track
- two exact timeline markers
- four exact project timelines
- ten exact Media Pool objects across three subfolders
- empty render queue
- inactive rendering

Historical Test B established that `Redline Broadcast Master` was accepted in this exact disposable Control project/timeline context. Test C and prior production-like attempts established rejection in the production-like context across tested presets.

## 4. Future operator preparation — separately authorized live setup

Construction revision r4 does not authorize this step.

After a later explicit live Test D authorization, the operator must:

1. Open project `redline-os-test-duplicate`.
2. Open timeline `RLO-LIVE-ASM-92701_TIMELINE`.
3. Remove exactly the single timeline video item `Redline OS Assembly Test Image.png` from that timeline using the Resolve UI.
4. Do **not** delete `Redline OS Assembly Test Image.png` from the Media Pool.
5. Do not change the audio item, markers, track counts, project settings, timeline settings, preset configuration, Media Pool organization, project timeline inventory, or any other project/timeline content.
6. Leave `RLO-LIVE-ASM-92701_TIMELINE` current.

No duplicate timeline is created. No Production project is opened or modified.

The harness deliberately does not automate timeline-item deletion because Test D does not need to introduce a new, unreviewed Resolve mutation API merely to prepare the experimental state.

## 5. Exact baseline invariants retained after video removal

Before the queue mutation, the harness must prove all of the following.

### Project/timeline identity

- current project: `redline-os-test-duplicate`
- current timeline: `RLO-LIVE-ASM-92701_TIMELINE`
- exact timeline inventory, in order:
  1. `Redline OS Timeline Test`
  2. `Redline OS Clip Placement Test`
  3. `Redline OS Clip Placement Test 2`
  4. `RLO-LIVE-ASM-92701_TIMELINE`

### Project/timeline settings

- project `GetSetting()` canonical SHA-256: `71430f17446c1b4d2019f4ff4d73b6a9ab4154124255c31eecfd7cd3f21d355c`
- timeline `GetSetting()` canonical SHA-256: the same reviewed value
- timeline start frame: `86400`
- timeline end frame: exactly `86424` or `86544`

The only justified post-removal end-frame outcomes are `86424` (Resolve shrinks the timeline end to the retained audio-item end) or `86544` (Resolve retains the reviewed pre-removal timeline end). Any other value is unexplained timeline drift and invalidates Test D before queue submission.

**Temporal stability (construction r4):** whichever of the two justified values the *first* Test D snapshot in a run observes becomes that run's bound expected end frame. Every later snapshot in the same run — the pre-render-context repeat, the final pre-add guard, and the post-`AddRenderJob()` observation — must report that exact same value. A change from `86424` to `86544`, or the reverse, is itself a second, unauthorized experimental variable even though both values individually remain justified in isolation. A pre-`AddRenderJob()` mismatch fails closed before queue mutation; a post-`AddRenderJob()` mismatch is recorded and forces the result to `inconclusive` without any repair, retry, or restoration.

### Audio

- audio track count: 1
- audio item count: 1
- Media Pool name: `Redline OS Assembly Test Audio.wav`
- Media Pool unique ID: `b88773bf-c80f-4f23-b346-077f09419e23`
- start: `86400`
- end: `86424`
- duration: `24`
- enabled: `true`

### Video — intentional Test D variable

- video track count: 1
- **video item count: 0**

The reviewed pre-Test-D baseline contained exactly one enabled video item:

- Media Pool name: `Redline OS Assembly Test Image.png`
- Media Pool unique ID: `fdded4d6-0e2d-43f0-9007-2cae51bca76a`
- start: `86424`
- end: `86544`
- duration: `120`
- enabled: `true`

### Subtitle

- subtitle track count: 1
- subtitle item count: 0

### Markers

The markers must remain exactly:

1. frame 0, Blue, `Assembly Start`, note `Live V1 marker A`, duration 1
2. frame 48, Yellow, `Assembly Beat`, note `Live V1 marker B`, duration 1

### Media Pool

The complete name/unique-ID/folder inventory must still equal the reviewed Rev8 Control inventory. In particular, `Redline OS Assembly Test Image.png` must still exist in `Master/Redline OS Episode Assembly Test` with unique ID `fdded4d6-0e2d-43f0-9007-2cae51bca76a`.

Any baseline drift other than zero timeline video items and the resulting derived timeline end frame invalidates Test D before queue submission.

## 6. Repository and host gates

The future live revision must bind to exact reviewed bytes and a published repository commit supplied out of band in the founder authorization.

Required gates before any Resolve import/contact:

- canonical repository root: `C:\Users\pj198\Documents\redline-os`
- branch: `master`
- origin: `git@github.com:Choice283/redline-os.git`
- HEAD equals the separately reviewed full 40-character commit
- working tree clean
- Python exactly `3.11.9`
- Python executable exactly `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`
- harness SHA-256 equals the separately reviewed 64-lowercase-hex value
- this contract SHA-256 equals the separately reviewed 64-lowercase-hex value

Construction revision r4 has `EXECUTION_ENABLED = False`. Therefore `--execute` must fail before importing `DaVinciResolveScript` or contacting Resolve.

## 7. Live Resolve gates for the future enabled revision

After a future separately authorized live revision connects, it must prove:

- product exactly `DaVinci Resolve Studio`
- Resolve version exactly `21.0.3.7`
- all §5 invariants pass
- `GetRenderJobList()` is a valid empty list after normalization
- `IsRenderingInProgress()` is literally `False`
- `Redline Broadcast Master` exists exactly once in the preset inventory
- target directory `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests` exists and is a directory
- no output file matching `phase14-test-d-no-video.*` exists

The full project/timeline/Media Pool/queue/rendering state is captured twice before any render-context mutation and a third time immediately before `AddRenderJob()`. Construction r4 additionally binds the timeline end frame observed by the first of these captures as the run's expected value and requires the second and third captures to match it exactly, per the temporal-stability rule in §5.

After `LoadRenderPreset("Redline Broadcast Master")` and the exact reviewed `SetRenderSettings(...)` call, `GetCurrentRenderFormatAndCodec()` is a **required isolation gate**, not a best-effort diagnostic. It must be callable, return a dictionary, and report exactly:

- `format == "mov"`
- `codec == "DNxHRHQX_10"`

These identifiers correspond to the same Broadcast Master QuickTime / Avid DNxHR HQX 10-bit path recovered from Test B, and they were captured directly as `mov` / `DNxHRHQX_10` immediately before the Mission 39D.3 Broadcast Master `AddRenderJob()` call. If the accessor is unavailable, raises, returns a non-dictionary value, or either identifier differs, Test D stops before queue mutation. This gate prevents render-context drift from becoming a second plausible experimental discriminator.

## 8. Permitted live mutations in the future enabled revision

The operator's one manual timeline-item deletion described in §4 is part of the future separately authorized Test D setup.

After the harness begins, exactly these additional project render-context/queue mutations are allowed:

1. `LoadRenderPreset("Redline Broadcast Master")` exactly once
2. `SetRenderSettings({"TargetDir": "C:\\Users\\pj198\\Documents\\redline-os\\.artifacts\\render-tests", "CustomName": "phase14-test-d-no-video"})` exactly once
3. `AddRenderJob()` exactly once

No other Resolve mutation is authorized.

Specifically prohibited:

- `StartRendering`
- `StopRendering`
- render-job deletion
- render-queue cleanup before independent evidence review
- project loading/switching
- timeline switching
- timeline creation/duplication/deletion
- media import/deletion
- clip insertion/deletion by the harness
- Production project access
- SQLite access
- retry after any failure or ambiguous outcome

## 9. Outcome classification

The queue must be empty before the single `AddRenderJob()` call.

### `accepted`

Exactly one identifiable queue job exists afterward. If `AddRenderJob()` also returned a direct usable ID, it must match the observed queue job ID.

### `rejected`

The queue remains empty and `AddRenderJob()` returned either:

- the empty string `""`, or
- literal `False`.

### `inconclusive`

Every other state, including:

- unidentified queue item
- multiple queue items
- direct ID/queue-ID disagreement
- direct ID with no observed queue job
- queue read failure
- project/timeline/Media Pool drift
- a post-`AddRenderJob()` timeline end frame that no longer matches the value bound by the run's first Test D snapshot (construction r4)
- rendering becoming active
- evidence or repository post-check failure

No retry is permitted for any outcome. If a precondition fails after the future manual video-item removal, stop and preserve the state; restoration or another attempt requires separate authorization.

## 10. Evidence and preservation

Evidence must be written outside the repository to a unique directory. Every JSON evidence write uses a sibling temporary file, flush + file `fsync`, close, and atomic `os.replace()` before the write is considered complete; directory `fsync` is attempted where supported. A required evidence-write failure is fail-closed.

Before `AddRenderJob()` is called, r4 must successfully persist `pre_add_evidence.json`. That durable checkpoint records all state needed to prove the queue call was justified, including:

- immutable Rev8 Control baseline reference
- Resolve product/version
- project settings baseline hash
- project timeline inventory
- complete Media Pool name/unique-ID/folder inventory
- current Test D timeline snapshot
- the run-bound expected end frame established by the first Test D snapshot
- repeated pre-render-context and final pre-add guards, each confirmed to match the run-bound end frame
- preset and exact applied output settings
- exact gated render context (`mov` / `DNxHRHQX_10`)
- empty before-queue inventory
- explicit `queue_mutation_started: false` marker

If this checkpoint cannot be durably written, **`AddRenderJob()` must not be called**.

If `AddRenderJob()` returns normally, r4 immediately attempts to persist its exact return type/safe representation and mutation timestamps to `add_render_job_result.json`. A failure of that **post-mutation** write is recorded in memory but must not suppress the read-only post-call observations: the harness still attempts queue, rendering, identity, timeline, Media Pool, timeline-inventory, and project-settings observations. Any such evidence-persistence failure forces the result to `inconclusive`; no retry is authorized. The post-call timeline observation includes the same run-bound end-frame check described in §5; a mismatch there is recorded the same observational way and likewise forces `inconclusive`, without repairing, retrying, or restoring anything.

After those read-only observations and outcome classification, r4 attempts to persist `post_add_evidence.json`. Failure of that post-call evidence write is likewise recorded in the returned result, forces `inconclusive`, and does not erase the observations already collected. The required pre-add checkpoint remains the durable evidence floor.

The final evidence set therefore includes, at minimum:

- `execution_binding.json`
- `pre_add_evidence.json`
- `add_render_job_result.json` when `AddRenderJob()` returns normally
- `post_add_evidence.json` when post-call evidence collection reaches classification
- final result / repository-postflight records when later layers complete
- `run_failure.json` for caught failure paths

If `AddRenderJob()` itself raises or the process fails after the call begins, the already-persisted `pre_add_evidence.json` remains the durable proof of the exact pre-mutation state. No retry is authorized.

If a job is accepted, it must remain queued and must **not** be rendered or deleted until independent evidence review is complete and Paul separately authorizes cleanup/restoration.

The modified disposable Control timeline also remains as-found after the one-shot result until independent review is complete. No automatic restoration is authorized.

## 10.1 r3 correction boundary

Construction r3 changes only the two Important staged-diff findings discovered after r2:

1. post-`AddRenderJob()` evidence-write failure may not suppress best-effort read-only post-call observation; such persistence failures are recorded and force `inconclusive`; and
2. Test D timeline end frame must be exactly `86424` or `86544`, rejecting any unexplained end-frame drift before queue mutation.

The r1 corrections retained in r3 remain unchanged: durable pre-add evidence and the mandatory exact `mov` / `DNxHRHQX_10` render-context gate. All other Test D experiment invariants and prohibitions remain unchanged.

## 10.2 r4 correction boundary

Construction r4 changes only the single Important finding identified during the final r3 staged-diff publication review:

1. the r3 accepted-value end-frame gate (`86424` or `86544`) checked each snapshot in isolation, so a run could observe `86424` at one snapshot and `86544` at another without failing, because both values individually remained justified. Construction r4 adds temporal stability: the first Test D snapshot in a run binds whichever of the two values it observes as that run's expected end frame, every later pre-`AddRenderJob()` snapshot must match it exactly (failing closed before queue mutation on a mismatch), and any post-`AddRenderJob()` mismatch is recorded and forces the result to `inconclusive` without repair, retry, or restoration.

The r1/r2/r3 corrections retained in r4 remain unchanged: durable pre-add evidence, the mandatory exact `mov` / `DNxHRHQX_10` render-context gate, and post-mutation evidence-write failures continuing best-effort observation while forcing `inconclusive`. All other Test D experiment invariants and prohibitions remain unchanged.

## 11. Interpretation

If Test D is `rejected`, the missing-video-payload hypothesis is strongly strengthened because the same previously accepted project/timeline identity rejected after the one intentional content change: removal of its sole video item.

If Test D is `accepted`, the simple hypothesis that zero video timeline items alone explains the Production rejection is substantially weakened/falsified under this experiment.

If Test D is `inconclusive`, no causal inference is allowed.

## 12. Construction/review gate

Before live execution can be considered:

1. Review this contract and `scripts/phase14_test_d_queue_attempt.py` independently.
2. Run the focused mocked/static tests.
3. Run `git diff --check` after repository integration.
4. Record exact SHA-256 values for the final contract and harness bytes.
5. Publish the reviewed repository state only under separate repository-change/publication authorization.
6. Re-verify local and remote commit identity.
7. Obtain a new explicit founder authorization tied to the final commit, contract hash, harness hash, manual one-item setup mutation, and exact one-shot queue scope.

Construction authorization is not live execution authorization.
