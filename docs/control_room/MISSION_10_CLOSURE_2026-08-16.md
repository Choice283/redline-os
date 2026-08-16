# Control Room V0 Mission 10 Closure

## Purpose

Mission 10 integrated the already-computed Mission 9 Closed-State
Currency result into the Project Detail screen's existing combined
`attention` signal. Under Mission 9, Closed-State Currency was
observation only -- displayed but never fed into `_derive_attention()`.
Mission 10 narrows that exclusion for exactly two of the four locked
states: `NOT_ANCESTOR` and `UNAVAILABLE` (anomalous/proof-failure
states) now contribute a factual reason to `attention.required`;
`CURRENT` and `AHEAD` (normal/expected states) still never do, by
themselves. Mission 10 changes only how the existing, already-proven
currency result is consumed -- it does not change how currency itself is
computed, and it does not touch any of the four locked state
definitions.

## Approved Architecture

Authorized via the Mission 10 architecture-delta review (read-only,
no implementation): `AUTHORIZE MISSION 10 ARCHITECTURE`, recommending
Closed-State Currency Attention Integration as the correct next Control
Room V0 capability, narrowly scoped to a composition change inside
`ProjectStatusService._derive_attention()` with no new source of truth,
no new Git operation, no new route, model, screen, or database. The
Founder subsequently locked the exact policy implemented here: `CURRENT`
and `AHEAD` never independently trigger attention (mirroring the
pre-existing `TrackingStatus.AHEAD` precedent); `NOT_ANCESTOR` and
`UNAVAILABLE` do.

## Published Checkpoint

SHA:
`337c5416de3d0491f99027ac8d953fe8a871183a`

Subject:
`feat: integrate Closed-State Currency with Control Room attention`

Parent:
`b66ba10544136862b6bb95774e16c01c139e1646`

This is the frozen Mission 10 *implementation* checkpoint -- distinct
from Mission 10 *closure/publication*, which this document and its
accompanying `PROJECT_STATE.yaml`/`CHANGELOG.md` updates record
separately, matching Missions 1-9 precedent (the closure record is
never squashed into or backdated onto the implementation checkpoint).

## Exact Implementation Scope

Checkpoint `337c5416de3d0491f99027ac8d953fe8a871183a` touches exactly
seven files:

- `src/control_room/project_status_service.py` -- the only production
  change. `ProjectStatusService._build_snapshot()` now computes
  `closed_state_currency` before calling `_derive_attention()` (a pure
  reorder of two pre-existing, already-present calls -- no new
  computation, no duplicate `_compute_closed_state_currency()` call) and
  passes the already-computed `ClosedStateCurrency` into it.
  `_derive_attention()` gained one new parameter and two new branches
  reading `closed_state_currency.status`.
- `tests/unit/control_room/test_project_status_service.py` -- 12 new
  deterministic, fixture-based tests of `_derive_attention()`'s full
  four-state policy and reason composition, plus a fixture correction
  (see "Fixture-Correction Evidence" below).
- `tests/unit/control_room/test_closed_state_currency.py` -- 2 net new
  real end-to-end tests (`test_current_state_does_not_trigger_founder_attention`,
  `test_unavailable_state_triggers_founder_attention`); the pre-existing
  `test_not_ancestor_state_does_not_trigger_founder_attention` was
  updated in place to `test_not_ancestor_state_triggers_founder_attention`,
  reflecting the Mission-10-authorized narrowing of the Mission-9-era
  exclusion for this one state, rather than being duplicated.
- `tests/unit/control_room/test_app.py`, `tests/unit/control_room/test_detail_view.py`
  -- fixture corrections only, no test-body/assertion changes (see
  "Fixture-Correction Evidence" below).
- `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`, `README.md` -- documentation
  updated to describe the new attention-integration behavior; no
  Git-behavior claim changed, since none was introduced.

No change anywhere to `git_reader.py`, `models.py`,
`mission_history_reader.py`, `app.py`, or `static/app.js` -- confirmed
empty diff on all five during both implementation and independent
review.

## Locked Four-State Attention Policy

`ProjectSnapshot.closed_state_currency.status`, exposed unchanged from
Mission 9:

- **CURRENT** -- does not independently trigger attention.
- **AHEAD** -- does not independently trigger attention. Deliberately
  mirrors the pre-existing `TrackingStatus.AHEAD` precedent: a local
  branch merely ahead of its upstream tracking branch does not
  independently trigger attention either, because a repository being
  ahead of its last recorded closed state is normal, expected
  post-closure development, not an anomaly.
- **NOT_ANCESTOR** -- triggers attention (`attention.required = True`)
  when no stronger or additional condition already does so. An
  anomalous state: the recorded closed state resolved successfully but
  is not reachable from current HEAD.
- **UNAVAILABLE** -- triggers attention when no stronger or additional
  condition already does so. A proof-failure state: the closed-state
  relationship could not be reliably established at all.

Mission 10 does not change the four Closed-State Currency states
themselves, their computation, or their displayed text -- only whether
two of the four now also contribute to the separate, pre-existing
`attention` boolean.

## Attention-Reason Composition Rules

- `_derive_attention()` never recomputes or re-derives Closed-State
  Currency; it consumes the already-computed `ClosedStateCurrency`
  passed in from `_build_snapshot()`.
- `NOT_ANCESTOR`/`UNAVAILABLE` reasons are drawn from
  `ClosedStateCurrency.detail`, which was already factual/descriptive
  under Mission 9 -- never a recommendation to commit, push, reset,
  repair, change branches, close a mission, or otherwise act. A
  hardcoded factual fallback string is used only when `detail` is
  `None`.
- Reasons compose via the pre-existing `"; ".join(reasons)` mechanism:
  a currency-derived reason never overwrites or is overwritten by any
  other simultaneously-true trigger's reason. Verified for
  dirty-tree+`UNAVAILABLE` and invalid-checkpoint+`NOT_ANCESTOR`
  combinations.
- `CURRENT`/`AHEAD` contribute nothing: verified that a pre-existing
  trigger's reason text (e.g. the dirty-working-tree message) is
  unchanged byte-for-byte when currency is `CURRENT` or `AHEAD`.

## Source-of-Truth Boundary

Unchanged from Mission 9, restated for Mission 10's consumption of it:
Git remains the sole source of the closed-state commit and its
ancestry/commit-count relationship to live HEAD, computed fresh on every
request, never cached, never written back into `PROJECT_STATE.yaml`.
Mission 10 adds no new source of truth -- it only changes which
already-computed field of the existing `ProjectSnapshot.closed_state_currency`
is also read by `_derive_attention()`.

## No-New-Git Guarantee

`_derive_attention()` contains no `GitReader` reference and no
subprocess call of any kind -- confirmed by direct source inspection,
not inferred from call counting. It operates purely on already-computed
values (`GitStatus`, `ProjectState`, `bool`, `ClosedStateCurrency`) with
no repository path or Git handle in scope. `ProjectStatusService`'s
`GitReader(...)` construction sites are unchanged in number and location
from Mission 9. A dedicated test
(`test_derive_attention_makes_no_git_subprocess_call`) monkeypatches
`subprocess.run` to raise if invoked and calls `_derive_attention()`
directly, proving no Git call occurs as a side effect of attention
derivation.

## No-Mutation Guarantee

`_derive_attention()` never assigns to any attribute of `git_status`,
`state`, or `closed_state_currency` -- confirmed by direct source
inspection. A dedicated test
(`test_derive_attention_does_not_mutate_closed_state_currency_value`)
deep-copies a `ClosedStateCurrency` before the call and asserts equality
after.

## API/Model/Frontend Boundaries

- **No new route.** API surface remains exactly `GET /`, `GET
  /api/projects`, `GET /api/projects/{project_id}`.
- **No model/schema change.** `models.py` has zero diff; `AttentionState`,
  `ClosedStateCurrency`, and `ClosedStateCurrencyStatus` are unchanged.
- **No frontend change.** `static/app.js` has zero diff -- the Detail
  screen already renders whatever `attention.reason` the API returns and
  needed no change to reflect the new trigger.
- **Backward-compatible response.** The `GET
  /api/projects`/`GET /api/projects/{project_id}` response shape is
  unchanged; only the runtime value of `attention` differs for the two
  newly-integrated currency states.

## Fixture-Correction Evidence

`tests/unit/control_room/test_app.py` and
`tests/unit/control_room/test_detail_view.py` each configured a fixture
`latest_checkpoint.document` value (`"docs/CHECKPOINT.md"`) that did not
correspond to any file actually committed in the fixture repository.
Under Mission 9, this was invisible: Closed-State Currency resolved to
`UNAVAILABLE` (the configured document could not be proven to be an
independently discovered, genuinely repository-relative mission history
entry) but currency was never fed into `attention`, so the fixtures'
`attention.required is False` assertions passed regardless. Under
Mission 10, `UNAVAILABLE` correctly triggers attention, which caused
`test_list_projects` and
`test_get_single_project_returns_full_snapshot_for_detail_rendering` to
fail -- correctly exposing that these fixtures never represented the
healthy/no-attention repository state the tests intended to model.

The correction adds a real closure document
(`docs/control_room/MISSION_1_CLOSURE_2026-01-01.md`) at the configured
path, committed in the same commit as `PROJECT_STATE.yaml`, so the same
real, unmocked production path (`MissionHistoryReader` discovery, Layer
1/Layer 2 closure-path validation, `GitReader.read_path_introduction_commit()`,
`GitReader.read_closed_state_currency()`) resolves to `CURRENT`, `0`
commits beyond -- a genuine, not bypassed, healthy baseline. No
assertion was weakened: `attention.required is False` remained the exact
expected value in both fixtures before and after the correction; only
the fixture's realism changed. The identical correction was applied to
`test_project_status_service.py`'s `_build_fixture` for the same reason.

Independent review reproduced both the old (`UNAVAILABLE`) and new
(`CURRENT`) behavior in an isolated scratch script outside the
repository, confirmed both were genuine consequences of the real,
unmocked production path (not mocked or hardcoded around), and
confirmed via mutation-testing (loading the pre-Mission-10
`_derive_attention()` from `git show HEAD:...` and re-running equivalent
scenarios against it) that the new tests are not vacuous -- they fail
against the old implementation. The review classified the fixture
changes as legitimate corrections, not masking changes, and not a
BLOCKER.

## Tests Added

**14 net new tests** (208 total, up from the published Mission 9
baseline of 194):

- `test_project_status_service.py`: +12 -- deterministic, fixture-based
  `_derive_attention()` coverage of all four currency states in
  isolation, reason-fallback behavior when `detail` is `None`, reason
  composition/preservation alongside pre-existing triggers, byte-exact
  preservation of pre-existing trigger reason text under `CURRENT`/`AHEAD`
  currency, the no-Git-call proof, and the no-mutation proof.
- `test_closed_state_currency.py`: +2 net -- `test_current_state_does_not_trigger_founder_attention`
  and `test_unavailable_state_triggers_founder_attention` (new); the
  pre-existing NOT_ANCESTOR attention test was updated in place to
  assert the new locked policy rather than duplicated.
- `test_app.py`, `test_detail_view.py`: 0 new tests -- fixture
  corrections only.

## Validation Results

- **Pre-Mission-10 baseline** (re-verified before implementation):
  `pytest tests/unit/control_room -q` -- **194 passed**.
- **Mission-10-affected files**: `pytest
  tests/unit/control_room/test_project_status_service.py
  tests/unit/control_room/test_closed_state_currency.py
  tests/unit/control_room/test_app.py
  tests/unit/control_room/test_detail_view.py -q` -- **88 passed**
  (independently re-run during review).
- **Focused Control Room suite** (final): `pytest
  tests/unit/control_room -q` -- **208 passed** (194 pre-existing + 14
  Mission 10), independently reproduced twice during implementation and
  review with an identical result.
- **Real Mission 10 attention/currency proof**, reproduced independently
  during review against this repository's own live state while the
  implementation was still uncommitted: `closed_state_currency.status =
  CURRENT`, `commits_since_closed_state = 0`, `attention.required =
  True` solely from the pre-existing dirty-working-tree trigger,
  `attention.reason` containing only the dirty-tree message -- `CURRENT`
  contributed zero text, confirmed live, not only in synthetic tests.
- **Route/mutation scan**: API surface remains exactly `GET /`, `GET
  /api/projects`, `GET /api/projects/{project_id}`; `src/control_room`
  contains no Mission 10 write path, filesystem-write route, shell
  execution, network Git operation, mutating Git verb invocation,
  database write, POST/PUT/PATCH/DELETE route, mission editing,
  checkpoint creation, automation, Resolve, Hermes, Context Engine, or
  agent-integration capability.

## Independent Review

**Final recommendation: APPROVE MISSION 10 IMPLEMENTATION COMMIT GATE.**

Findings: BLOCKER: none. HIGH: none. MEDIUM: none. LOW: none.

The review independently re-derived (not merely trusted) the
implementation report: re-read the full diff, independently reproduced
the fixture-correction claim in an isolated scratch script outside the
repository (see "Fixture-Correction Evidence" above), independently
re-ran the targeted and full focused suites (88 passed / 208 passed,
matching exactly), independently confirmed the no-Git-call and
no-mutation invariants by direct source inspection rather than trusting
the tests' framing, performed a mutation-testing check against the
pre-Mission-10 implementation to confirm the new tests are regression-
sensitive, and independently queried the live repository's own
Closed-State Currency and attention values. No repository mutation
occurred during review; all scratch reproduction happened outside the
repository.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No V1 tag was created, moved, or deleted during
Mission 10.

## Deferred Work

Explicitly out of scope for Mission 10, unchanged by this closure:

- Widening `CURRENT`/`AHEAD` to trigger attention, or narrowing
  `NOT_ANCESTOR`/`UNAVAILABLE` back out -- would require separate,
  explicit Founder authorization, exactly like any other change to
  `_derive_attention()`'s trigger set.
- Any recommendation, "checkpoint now," "needs review," "publish these,"
  or other suggested-action wording anywhere in Closed-State Currency or
  attention -- Mission 10 introduces no recommendation engine.
  `attention.required` remains a boolean signal with a factual reason,
  never an instruction.
- Changing how the four Closed-State Currency states themselves are
  computed, displayed, or defined -- that remains exactly Mission 9's
  territory, untouched.
- `git fetch`, remote/GitHub-verified currency, or any network Git
  operation.
- Additional projects, project auto-discovery, additional Control Room
  screens, a history/evidence/change-set database, automatic historical
  test/evidence reruns, diff content or commit-metadata display, or
  derived scoring/classification of historical outcomes.
- Mission creation, mission editing, checkpoint creation, validation or
  test reruns, CI execution or repair.
- Context Engine, agent routing, Hermes integration, automation of any
  kind.
- Resolve, render, episode, asset, archive, or production controls.
- Mission 11 definition -- no scope, objective, or timeline for a next
  mission is implied or proposed by this document.

## Mission 10 Completion Criteria

All of the following are satisfied as of this closure:

- Approved architecture (Closed-State Currency Attention Integration,
  authorized via the Mission 10 architecture-delta review).
- Implementation checkpoint frozen at
  `337c5416de3d0491f99027ac8d953fe8a871183a`, exact scope as listed
  under "Exact Implementation Scope" above.
- Independent review completed with zero correction rounds required,
  ending **APPROVE MISSION 10 IMPLEMENTATION COMMIT GATE** with zero
  BLOCKER/HIGH/MEDIUM/LOW findings.
- Focused Control Room suite: 208 passed (194 pre-existing + 14 Mission
  10). Real-repository Closed-State Currency and attention behavior
  independently confirmed consistent.
- Zero new Git operation, zero new route, zero new model, zero new
  frontend screen, zero new database, zero recommendation engine, zero
  mutation capability. `v1.0.0` unchanged.

## Next-Mission Boundary

This document authorizes nothing beyond Mission 10 as delivered at
checkpoint `337c5416de3d0491f99027ac8d953fe8a871183a`. No Mission 11
scope, objective, or timeline is implied or proposed. Any further
Control Room capability -- including widening or narrowing which
Closed-State Currency states affect `attention.required`, or anything
listed under "Deferred Work" above -- requires a separate, explicitly
Founder-authorized mission per `CLAUDE.md`.

## Closure

Control Room V0 Mission 10 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
