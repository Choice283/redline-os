# Phase 14 Test D — Execution-Enablement r1 Static Review

Review status: **PASS FOR r1 ENABLEMENT CONSTRUCTION REVIEW; LIVE EXECUTION REMAINS PROHIBITED**

Enablement revision: `phase14-test-d-video-payload-isolation-execution-enablement-r1`

## Base commit and immutable contract

This enablement revision is built directly on top of the published Phase 14 Test D r4 publication candidate:

- published r4 base commit: `9b26fa0886ae32bf30f30c2384861dfd0338f5a4`
- published r4 commit subject: `feat: add Phase 14 Test D r4 isolation controls`
- immutable execution contract: `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`
- immutable contract SHA-256: `e4b9cfdc1121f322a42633c6da4e15c54de4bb8f55a28812b9f516d421814b1d`

`docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, `docs/PHASE14_TEST_D_STATIC_REVIEW.md`, `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, and `.gitattributes` were not modified by this construction. The contract's own hash was independently re-verified against the working tree immediately before and after this construction and remains exactly the published value above.

## Scope

This revision is limited to making the already-published, already-reviewed r4 Test D experiment live-capable through its existing `--execute` path. It does not redesign the experiment, does not change the target project/timeline, and does not add retries. Only these files were modified: `scripts/phase14_test_d_queue_attempt.py`, `tests/unit/test_phase14_test_d_queue_attempt.py`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`. This document and `docs/PHASE14_TEST_D_LIVE_EXECUTION_RUNBOOK.md` were added.

## Exact enablement diff

Four changes to `scripts/phase14_test_d_queue_attempt.py`, all outside the frozen r4 experiment core:

1. **Revision identifier**: `CONSTRUCTION_REVISION` changed from `phase14-test-d-video-payload-isolation-construction-r4` to `phase14-test-d-video-payload-isolation-execution-enablement-r1`.
2. **Enablement flag**: `EXECUTION_ENABLED` changed from `False` to `True`. The `_require(EXECUTION_ENABLED is True, ...)` gate in `main()` is retained unchanged as a defensive self-check.
3. **Authorization binding**: the static `AUTHORIZATION_PHRASE` constant (compared with `==` against a fixed string) is replaced by `build_required_authorization(*, expected_repository_commit, expected_script_sha256, expected_contract_sha256)`, which renders an exact one-shot phrase that textually incorporates those three invocation-supplied values, the fixed `CONTROL_PROJECT` / `CONTROL_TIMELINE` identity, the fixed "exactly one manual removal" / "exactly one queue attempt" clauses, and the fixed `AUTHORIZATION_ONE_SHOT_SCOPE` prohibition clause (no retry, no Production access, no rendering, no cleanup, no second submission, no additional mutation). `main()` computes this required value from `args.expected_repository_commit` / `args.expected_script_sha256` / `args.expected_contract_sha256` and compares it with `==` against `args.authorization`.
4. **Documentation-only**: the module docstring and `connect_live_resolve()`'s docstring were updated to describe the enablement revision and the new authorization boundary; no behavior changed in either.

Nothing else in the file changed. No new imports, no new Resolve method references, no new argparse flags, no changes to `execute_test_d()`, `validate_test_d_snapshot()`, `_pre_add_snapshot()`, `classify_queue_outcome()`, `EvidencePackage`, `snapshot_timeline()`, `validate_render_context()`, or any other frozen-core function.

## Founder-authorization binding architecture

`build_required_authorization()` is a pure function of its three keyword arguments; it performs no I/O and reads no external state beyond the fixed `CONTROL_PROJECT` / `CONTROL_TIMELINE` / `AUTHORIZATION_ONE_SHOT_SCOPE` module constants. In `main()`, it is called using `args.expected_repository_commit`, `args.expected_script_sha256`, and `args.expected_contract_sha256` — the same three values already independently proven, earlier in the same `main()` call, to be well-formed (`FULL_SHA1_RE` / `FULL_SHA256_RE`) and to actually match the real repository HEAD (`repository_gate()`) and the real script/contract bytes on disk (`validate_bound_files()`). Because the required authorization text is derived from exactly those already-verified values, an authorization phrase that was correct for a different commit, a different harness revision, or a different contract revision renders a different required string and therefore fails the subsequent exact `==` comparison — before evidence-directory creation, before `DaVinciResolveScript` import, before `scriptapp("Resolve")`, and before any Resolve mutation.

The order of gates in `main()` under `--execute` is unchanged in shape from r4: host Python → bound-file hashes → repository state → (dry-review return here if `--execute` is absent) → `EXECUTION_ENABLED` → authorization → evidence-root creation → `connect_live_resolve()` → `execute_test_d()`. Only the authorization step's comparison target changed.

## Unchanged experiment core

Byte-for-byte unchanged from the published r4 commit: `execute_test_d()`, `validate_test_d_snapshot()`, `_pre_add_snapshot()`, `classify_queue_outcome()`, `EvidencePackage` (including its fsync/atomic-replace durability), the durable `pre_add_evidence.json` requirement before `AddRenderJob()`, post-mutation evidence-write-failure handling (continues best-effort observation, forces `inconclusive`), the temporal end-frame stability gate (`expected_end_frame` binding across `initial` / `pre_render_context` / `final_guard` / the post-call observation), the exact `mov` / `DNxHRHQX_10` render-context gate, and the Media Pool / timeline / project invariant checks. `git diff` against the published r4 commit confirms no line inside any of these functions changed.

## Test/static results

Executed on native Windows Python 3.11.9:

- compilation: PASS
- focused Test D suite: **55 passed** (48 existing, minus 2 whose sole purpose was asserting r4's hard-disable — `test_construction_revision_is_hard_disabled` and `test_execute_request_stops_before_resolve_connection` — replaced by 9 enablement-specific tests)
- combined Phase 14 focused regression: **156 passed**, 1327 deselected
- AST-visible `AddRenderJob()` calls: 1
- AST-visible `LoadRenderPreset()` calls: 1
- AST-visible `SetRenderSettings()` calls: 1
- prohibited-mutation AST intersection (`StartRendering`, `StopRendering`, `DeleteRenderJob`, `DeleteAllRenderJobs`, `LoadProject`, `SetCurrentTimeline`, `ImportMedia`, `AppendToTimeline`, `CreateEmptyTimeline`, `DeleteTimelines`, `DeleteClips`): empty
- `sqlite3` import scan: empty
- `DaVinciResolveScript` import confined to `connect_live_resolve()`: confirmed by AST-based test
- `git diff --check`: exit 0

New enablement-specific tests prove: the enablement revision reports `EXECUTION_ENABLED = True`; a non-`--execute` invocation never calls `connect_live_resolve()` or `execute_test_d()`; `--execute` with a missing, incorrect, wrong-commit-bound, wrong-harness-hash-bound, or wrong-contract-hash-bound authorization never calls `connect_live_resolve()`; and the exact correctly derived authorization, with repository/host/hash gates mocked valid, reaches the mocked `connect_live_resolve()` exactly once and calls `execute_test_d()` exactly once. No test contacts real DaVinci Resolve; all Resolve-shaped objects in the test suite are local fakes or mocks.

## Live execution remains unauthorized

This construction and its static/native verification do not authorize live Test D execution, Resolve contact, Control video-item removal, `AddRenderJob()`, render-queue mutation, `StartRendering()`, SQLite access, or Production access. `docs/PHASE14_TEST_D_LIVE_EXECUTION_RUNBOOK.md` describes only a proposed future sequence and is explicitly marked not authorized. Live execution requires a separately published commit, a fresh founder authorization computed by `build_required_authorization()` for that exact published commit and the exact enabled-harness/contract hashes, and the operator's own manual one-item Control video removal performed outside this harness — all under further separate, explicit authorization from Paul Jones. Phase 14 remains open and BLOCKED.
