# Phase 14 Test D — Live Execution Runbook

Status: **PROPOSED / NOT AUTHORIZED. This document does not authorize live execution.**

Enablement revision this runbook targets: `phase14-test-d-video-payload-isolation-execution-enablement-r1`

Governing rule: **Agents advise. Paul decides.**

## Purpose

This runbook describes, for future reference only, the sequence a later, separately authorized live Test D attempt would follow using the execution-enablement r1 harness. It is a proposal, not an instruction set to be carried out now or by any agent acting on this document alone. No step in this runbook may be performed under this document's authority. Each step requires its own separate, explicit authorization from Paul Jones at the time it is performed, tied to the exact commit and hashes current at that time.

## Proposed future sequence

1. **Published enabled revision verification** — independently re-verify that the exact enablement-r1 bytes (harness, and this and companion documents) have been published to a specific commit, and re-verify the four hash-bound artifacts (execution contract, harness, and their companions) directly from that published commit.
2. **Non-contact preflight** — invoke the harness without `--execute` against that exact published commit and hashes, and confirm the resulting JSON reports `execution_enabled: true`, `resolve_contact: false`, `queue_mutation: false`, and a clean repository/host/hash gate. This step never imports `DaVinciResolveScript` and never contacts Resolve.
3. **Fresh founder authorization bound to the final commit/hashes** — Paul Jones computes or is given the exact `build_required_authorization()` value for that specific published commit's SHA-1, that specific harness's SHA-256, and that specific execution contract's SHA-256, and separately, explicitly authorizes exactly one Test D queue attempt using that exact text.
4. **Manually open the exact Control project/timeline** — the operator opens project `redline-os-test-duplicate` and timeline `RLO-LIVE-ASM-92701_TIMELINE` in the Resolve UI. No other project or timeline is opened.
5. **Manually remove exactly one reviewed video timeline item** — the operator removes exactly the single timeline video item `Redline OS Assembly Test Image.png` from that timeline using the Resolve UI only, per §4 of `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`. The item is not deleted from the Media Pool. No other project/timeline content is changed.
6. **Invoke the enabled harness exactly once** — run the harness with `--execute` and the exact authorization from step 3, bound to the exact commit/hashes from step 1. The harness performs its own fail-closed pre-add verification, one `LoadRenderPreset()`, one `SetRenderSettings()`, and the sole `AddRenderJob()` call, exactly as specified in the immutable execution contract.
7. **No retry** — if the harness reports `rejected` or `inconclusive`, or fails any gate, the run is over. No second invocation, no retry, no repair is authorized under this runbook or any prior authorization.
8. **Preserve queue/timeline/evidence as found** — an accepted render job remains queued and is not rendered or deleted. The modified Control timeline remains exactly as the harness left it. All evidence files remain in place outside the repository.
9. **Stop for independent review** — the run's evidence and outcome are handed to independent review before any further action (cleanup, restoration, a written interpretation of the result, or any subsequent mission) is authorized.

## What this runbook does not authorize

This document does not itself authorize: opening the Control project/timeline, removing the Control video item, invoking the harness with `--execute`, any `DaVinciResolveScript` import, any Resolve contact, `AddRenderJob()`, render-queue mutation, `StartRendering()`, SQLite access, Production access, cleanup, or restoration. Publishing or reviewing this runbook is construction/documentation only.

Phase 14 remains open and BLOCKED. Live Test D remains prohibited until each step above receives its own separate, explicit founder authorization at the time it is performed.
