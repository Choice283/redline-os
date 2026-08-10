# Redline OS Roadmap

## Roadmap interpretation

Roadmap phases classify system capabilities. They are not required to be
implemented in strict numerical order — a later-phase capability may be
delivered early when it's needed to establish a safe foundation for
earlier production capabilities. Missions and slices describe
implementation order. Roadmap phases describe capability ownership.
Release versions mark validated repository states.

**Governing rule:** Roadmap phases classify capabilities. Missions and
slices record implementation sequence. Release versions mark validated
repository states. These identifiers must not be treated as
interchangeable numbering systems.

## Naming model

Redline OS uses four planning levels:

1. **Roadmap Phase** — long-term product capability stage (this document,
   canonically rooted in `docs/ARCHITECTURE.md` §6).
2. **Initiative** — a coordinated body of work within or across phases
   (e.g. the CLI Automation Initiative, the Asset Registry Reconciliation
   Engine Initiative).
3. **Mission** — a reviewable engineering objective within an initiative
   (e.g. Mission 9 — `organize-bins`).
4. **Slice** — the smallest independently implemented increment, always
   qualified by its parent initiative (e.g. Reconciliation Slice 7 —
   never just "Phase 3" or "Slice 7" alone).

Use fully qualified names in issues, commits, documents, and reviews:
`Roadmap Phase 3`, `CLI Automation Initiative Mission 11B`,
`Reconciliation Slice 3`, `Release v0.3.0`. Avoid ambiguous forms like
"Phase 3 work" or "the third phase" unless the surrounding document has
already established which hierarchy is meant.

---

## A note on "Phase 3" — read this before using the term anywhere

Three genuinely different things have each been called "Phase 3" across
this repository's real history. None of the three labels is a mistake in
isolation; the collision only appears when they're compared side by side.

1. **`docs/ARCHITECTURE.md` §6's original, project-wide roadmap** defines
   Phase 3 as "Media + Asset Managers." This is the canonical meaning and
   the one this document uses below.
2. **The Asset Registry Reconciliation Engine** (`docs/ASSET_RECONCILIATION_ARCHITECTURE.md`,
   `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md`) defines its own,
   self-contained "Milestone 10 Phase 3," scoped strictly to that engine,
   with its own internal Slices 1–13 (Slices 1–11 are implementation
   gates, already complete; Slices 12–13 are optional documentation
   follow-ups). This is an Initiative living inside canonical Phase 3, not
   a competing roadmap phase.
3. **This session's CLI Automation work** (Missions 1–11B, released as
   `v0.3.0`, tagged "Phase 3 Foundation") was informally called "Phase 3"
   during its own implementation conversation. Functionally, that work
   maps to canonical **Phase 8 (Hardening)** — see Phase 8A below — not to
   canonical Phase 3 at all. The release name and Git tag are historical
   artifacts and are not renamed; this document is what resolves the
   ambiguity going forward.

Going forward: canonical Phase 3 means Media and Asset Management only.
Reconciliation work is always written as "Reconciliation Slice N," never
bare "Phase 3." CLI Automation is always written as "Phase 8A" or "the
CLI Automation Initiative," never bare "Phase 3."

---

## Roadmap Phases (canonical, rooted in `docs/ARCHITECTURE.md` §6)

| Phase | Capability | Status |
|---|---|---|
| 0 — Foundations | Repo scaffold, config schema, DB schema, logging, mock Resolve adapter. | Complete |
| 1 — Resolve Adapter Core | `connect()`, project create/duplicate, media pool operations. | Complete — verified against a live DaVinci Resolve Studio 21.0.3 instance |
| 2 — Episode Manager + Config + DB | Create/list/status-track episodes. | Complete |
| 3 — Media and Asset Management | Folder scanning, asset registry checks, ingest-to-episode matching. | Complete |
| 4 — Timeline Builder | Template-based timeline assembly, marker placement. | Complete |
| 5 — MCP Server v1 | Expose Phases 1–4 as tools; first end-to-end flow through Claude. | Complete |
| 6 — Render Manager | Queue, monitor, presets, async job model. | Complete against `MockResolveAdapter`; real `queue_render`, `get_render_status`, and `cancel_render` are implemented/live-verified |
| 7 — Archive Manager | Completes the episode lifecycle. | Complete |
| 8 — Hardening and Operator Interfaces | Full test coverage, error handling, doc polish, CLI fallback, packaging. | Partially complete — see Phase 8A below |

### Phase 8A — CLI and Architecture Hardening

- Status: **Complete**
- Release: `v0.3.0`
- Release name: **Phase 3 Foundation** (historical name; see "A note on
  'Phase 3'" above — this work is canonically Phase 8, not Phase 3)
- Initiative: CLI Automation Initiative (Missions 1–11B)

Completed capabilities:

- Stable command-line entry point (`redline` console script)
- Episode lifecycle commands (`create`, `status`, `list`, `scan-ingest`,
  `organize-bins`, `build-timeline`, `place-clips`)
- Asset inspection and verification commands (`list`, `verify`)
- Archive commands (`list`, `episode`)
- Thin transport boundaries — CLI and MCP both delegate to `redline_core`
  with no business logic of their own
- Three composition tiers (`ApplicationServices`, `CoreServices`,
  `PersistenceServices`), each earned by a demonstrated dependency boundary
- Centralized timeline-name ownership (`TimelineBuilder.timeline_name_for_episode()`)
- Documented mutation and idempotency semantics (timeline creation is
  idempotent; marker application and clip placement are append-only; no
  automatic rollback; no hidden retries)
- Full regression baseline: 924 passed, 1 skipped
- Release documentation and an annotated Git tag (`v0.3.0`)

Remaining Phase 8 work (not part of `v0.3.0`):

- Live-production validation beyond what's already verified in `MILESTONES.md`
- Operational recovery / restart procedures (addressed by Mission 27)
- Packaging and installation hardening beyond the v0.3.0 editable-install flow
  (partially addressed by Phase 12 installed-runtime smokes and operator docs)
- Logging and diagnostics review
- Performance and failure-injection testing
- Deployment documentation (addressed by Mission 28) and upgrade documentation

### Reconciliation Engine Initiative (inside canonical Phase 3)

- Status: **Complete** (Slices 1–11; Slices 12–13 are optional
  documentation-only follow-ups, not implementation gates)
- Tag: `phase3-slice8`
- Scope: read-only Asset Registry reconciliation planning — matching,
  classification, scope evaluation, evidence handling, public
  serialization. No filesystem scanning, no repository mutation, no
  Resolve interaction; actions are inert in this phase.
- See `docs/ASSET_RECONCILIATION_ARCHITECTURE.md` and
  `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md` for the engine's own
  architecture and slice-by-slice detail. Slice numbers there are local to
  this initiative and are never roadmap-phase numbers.

---

## Forward-looking phases (not yet started)

Numbered from 9 onward specifically so they don't collide with the
original roadmap's own Phase 4–7 meanings, all of which already describe
completed work above.

| Phase | Capability | Status |
|---|---|---|
| 9 — Episode Production Pipeline | CLI exposure of the existing manifest/build_episode() capability. | **Complete** — Mission 12 (`episode validate-manifest`, read-only) and Mission 13 (`episode assemble`, mutating, ADR-0001 atomic assembly claim) both landed. Post-Mission-13 gap review (grepped `redline_core.manifest`'s full public surface — `load_manifest()`/`validate_manifest()` only — and confirmed `EpisodeManager.build_episode()` is now CLI-reachable via `assemble`) found no remaining manifest- or build_episode()-related capability without a CLI entry point. |
| 10 — Render Automation | Real Resolve integration for the render methods still stubbed in Phase 6. | Complete — Mission 14 (real `ResolveScriptAdapter.queue_render()`, enqueue-only), Mission 15 (real `ResolveScriptAdapter.get_render_status()`), and Mission 16 (real `ResolveScriptAdapter.cancel_render()`) are complete and live-verified. |
| 11 — MCP Expansion | Close the CLI/MCP capability gap (e.g. `place_clips`, episode assembly currently have no MCP tool exposure). | **Complete** — Mission 17 (`place_clips` MCP tool), Mission 18 (`validate_manifest` MCP tool), and Mission 19 (`assemble_episode` MCP tool) are complete. No approved Phase 11 MCP transport gaps remain. |
| 12 — Production Release | Deployment, upgrade, and operational hardening beyond Phase 8A's scope. | Complete — Mission 20 (Logging and Diagnostics Baseline), Mission 21 (Package Core DB Schema Resource), Mission 22 (Installed Wheel Smoke Verification), Mission 23 (Installed Database Bootstrap Verification), Mission 24 (Installed Non-Help CLI Smoke Verification), Mission 25 (Installed MCP Startup Smoke Verification), Mission 26 (First-Run Installed Operator Workflow Documentation), Mission 27 (Recovery and Restart Runbook Documentation), Mission 28 (Production Workstation Deployment Documentation), and Mission 29 (Align CI Workflow With Canonical Release Branch) are complete. |
| 13 — Production Build Command Composition | Compose existing production-ready capabilities into the canonical `redline build Episode_0001` operator workflow without moving policy into transports. | Complete — Mission 30 (Canonical Build Command Specification), Mission 31 (Build Target Parsing), Mission 32 (Manifest Resolution), Mission 33 (Build Orchestrator), Mission 34 (CLI `redline build`), Mission 35 (CLI Render Surface), Mission 36 (Build to Render Integration), and Mission 37 (Documentation and Verification) are complete. |

---

## Phase 14 - First Live Episode

- Status: **Open and BLOCKED**. Missions 39D and 39E are formally closed, but
  Phase 14 is not complete.
- Objective: prove the production-ready build path against a live Resolve
  Studio workstation using one production-like episode.
- Mission 38 (Live Resolve Episode Build) reached and passed the real Resolve
  connection boundary, then stopped correctly on missing manifest preflight.
- Mission 38A (Build Preflight Before Mutable Composition) corrects the
  discovered repository-hygiene gap: failed build preflight must not initialize
  the default SQLite database, connect Resolve, or create persistent logging
  artifacts before manifest resolution, loading, and validation succeed.
- Mission 38 completed the first live Resolve episode build from a validated
  disposable manifest: real project duplication, media import, timeline
  creation, clip placement, and SQLite episode persistence completed without
  render queueing or archive execution.
- Mission 39A completed live render queue preflight investigation and found two
  blockers: the configured `Redline Broadcast Master` Resolve preset is not
  installed, and render queueing needed deterministic output naming, collision
  policy, and Resolve-before-SQLite persistence ordering.
- Mission 39B is implemented, reviewed, committed, pushed to `origin/master`,
  and CI-green:
  preset-configured output naming, immutable output planning, exact output and
  active-job collision rejection, atomic SQLite active-output claims before
  Resolve queue mutation, Resolve failure compensation, reconciliation-required
  errors when compensation fails, and MCP render response/error consistency are
  in the published repository state. Current GitHub Actions CI for the published
  head reports 1268 passed and 1 skipped.
- Mission 39C provisioned the `Redline Broadcast Master` Resolve preset
  manually and verified it through the read-only Resolve scripting API in the
  production-like `RLC-E9001_MASTER` project: `GetRenderPresetList()` found
  `Redline Broadcast Master`, no render job was queued, and rendering was not
  started. The approved Broadcast Master export filename standard
  `{project_name}.mov` is activated in canonical config for `broadcast_master`;
  `youtube_1080p` remains incomplete and fail-closed until separately approved.
- Mission 39D.1 classified post-`AddRenderJob()` reconciliation uncertainty
  into `RenderQueueIdentityUnresolvedError`, distinguishing unresolved
  Resolve queue identity from an ordinary pre-acceptance failure. This was
  a direct response to an earlier live attempt where `AddRenderJob()`
  returned no usable job ID.
- Mission 39D.1.1 corrected diagnostic logging to route through the
  configured `redline_os` application logger, so the identity diagnostic
  actually reaches `<REDLINE_LOG_DIR>/redline_os.log` instead of a logger
  tree `configure_logging()` never attaches handlers to.
- Mission 39D.2 added `RenderQueueAcceptanceNotObservedError`, a narrower
  classification distinguishing unresolved queue identity from the more
  specific condition in which no accepted job was observed under the
  exact unchanged-ID-multiset predicate. Reserved for the exact evidence a
  second live attempt produced: `AddRenderJob()` returned an empty string
  and the before/after Resolve queue snapshot showed the same job-ID
  multiset by job-ID comparison. It also added pre-add diagnostic context
  (timeline, exact applied target directory/custom name, render
  format/codec/mode) and a machine-searchable `reconciliation_outcome` log
  field.
- Mission 39D.3 performed one fully reviewed, freshly authorized, one-shot
  live queue revalidation against the production-like `RLC-E9001_MASTER`
  project, executed against published commit `2e36a41` under the Mission
  39D.2 behavior. All seven ordered preflight gates passed, including
  local `origin/master` and live remote `refs/heads/master` publication
  pins. `AddRenderJob()` again returned an empty string, this time with
  `render_format='mov'` and `render_codec='DNxHRHQX_10'` genuinely
  captured as active at the moment of the call — confirming the expected
  format/codec were observed, though this does not rule out other
  Resolve-side conditions and the root cause remains unresolved. The
  result was classified `RenderQueueAcceptanceNotObservedError`. A
  temporary active-output claim was acquired before the Resolve call and
  released after the failure; postflight found zero render-job rows and
  zero active output claims, the episode remained `created`, no render
  started, and the repository was left exactly as found. Evidence
  directory: `%TEMP%\redline-mission39d3-live-revalidation-20260801T194713957967Z`;
  reviewed script SHA-256:
  `39AE6DC8D891185F2A6CEB778A8D0FDC13E24F7126CABB59E133C2A6C429B0EC`.
- Across three controlled live attempts, the live queue path failed closed
  and ended with consistent postflight state every time. The attempts
  successively exposed the missing-ID condition (pre-39D.1), validated the
  identity-unresolved diagnostics (post-39D.1.1), and validated the final
  acceptance-not-observed classification (Mission 39D.3). None observed
  Resolve accept the Broadcast Master queue request for the disposable
  `RLC-E9001` episode. Phase 14 is **open and BLOCKED**,
  not complete: the production-workflow objective — a successful live
  Broadcast Master queue acceptance — remains unproven. No further live
  queue attempt is authorized without a new root-cause investigation, a
  separately reviewed contract, and fresh explicit authorization. Mission 39D
  is **FORMALLY CLOSED**: the queue-failure classification and diagnostic work
  is complete, the authorized one-shot Mission 39D.3 live revalidation
  completed, Resolve did not observably accept a new queue job, and postflight
  cleanup was verified. Closing Mission 39D does not characterize queue
  acceptance as successful.
- Mission 39E established the current Windows Resolve scripting workstation
  configuration facts without authorizing another render submission. The
  correct interactive Windows identity is `CHOICES\pj198`, with user profile
  `C:\Users\pj198`; User-scope Resolve scripting values must belong to that
  identity, not `Choices\CodexSandboxOffline`, and elevation is not required
  for User-scope configuration. The verified values are:
  `RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting`,
  `RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll`,
  and a `PYTHONPATH` Resolve Modules entry of
  `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules`.
  A genuinely new native Windows PowerShell session is required after
  configuration to verify Process-scope inheritance.
- Mission 39E verified Python 3.11.9 importing `DaVinciResolveScript` and
  `ResolveScriptAdapter` connecting successfully through Python 3.11. The
  read-only observation found current project `RLC-E9001_MASTER`, current
  timeline `RLC-E9001_TIMELINE`, render queue count `0`, rendering active
  `False`, and probe exit code `0`. Python 3.13 successfully ran ordinary
  Python code but crashed while importing `DaVinciResolveScript` with Windows
  access violation `0xC0000005`; Python 3.13 must not be used for the current
  Resolve integration. Mission 39E is **FORMALLY CLOSED**. Mission 39E did
  not prove Broadcast Master queue acceptance.
- Phase 14 remains **open and BLOCKED**. The exact remaining blocker is:
  Broadcast Master queue acceptance remains unproven because Resolve returned
  an empty `AddRenderJob()` result and no new queue job ID was observed. No
  further live queue submission is authorized. A future attempt requires a new
  root-cause investigation, a separately reviewed attempt contract, and fresh
  explicit founder authorization.
- Mission 39H improves the next failure's diagnostic evidence without
  changing Phase 14's status or authorizing another live attempt. It preserves
  the job-ID multiset as the sole authoritative queue-acceptance mechanism and
  adds sanitized pre-add context, target-directory diagnostics, render-settings
  key/type capture, queue inventories, and diagnostic-only structural
  comparison for post-`AddRenderJob()` reconciliation failures. Phase 14
  remains **open and BLOCKED** on the same Broadcast Master queue-acceptance
  blocker above.
- Mission 39I.1 creates a reviewable, fail-closed live-attempt script and
  evidence harness only. It does not authorize execution. The reviewed future
  command is
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m cli.main render queue RLC-E9001 broadcast_master`.
  A live Mission 39I attempt still requires separate founder authorization
  tied to the final script SHA-256 and an explicit reviewed repository commit
  supplied at execution time, with no retry, render start, cancellation,
  deletion, configuration change, or additional submission authorized.
- Mission 39I.2o completed independent source-level review at r9 for the
  read-only Resolve content-identification probe. The probe remains
  execution-prohibited; source-review closure does not authorize importing
  the probe, connecting to Resolve, or inspecting the live project. Any
  future execution must be a separately numbered and explicitly authorized
  mission. This documentation closure does not by itself change Phase 14's
  BLOCKED status or the Broadcast Master queue-acceptance blocker above.
- Phase 14 Test B and Test C complete the project x preset isolation matrix:
  Test B (disposable `redline-os-test-duplicate` project, custom `Redline
  Broadcast Master` preset) confirmed one accepted render-queue job via
  post-execution queue-state recovery; Test C (production-like
  `RLC-E9001_MASTER` project, built-in `YouTube - 720p` preset) returned an
  empty `AddRenderJob()` result and an unchanged queue, classified
  `queue_job_rejected`. Both presets were accepted in the disposable control
  context and rejected in the `RLC-E9001_MASTER`/`RLC-E9001_TIMELINE`
  context, ruling out either preset being universally incapable of queue
  acceptance. Phase 14 remains **open and BLOCKED**: Test B and Test C are
  each complete as evidence-gathering activities, but the exact project- or
  timeline-level root cause remains unidentified, and the broader production
  queue-acceptance problem is not resolved. No further live Resolve mutation
  is authorized. The next allowed planning activity is repository-only
  review and read-only comparison design; this entry does not design or
  authorize a Test D. See the Phase 14 Test B/Test C entry in
  `docs/CHANGELOG.md` for full evidence.
- A dual project/timeline read-only snapshot and offline comparison probe,
  its mocked unit test suite, and a companion comparison contract have been
  constructed at `scripts/phase14_resolve_context_snapshot.py`,
  `tests/unit/test_phase14_resolve_context_snapshot.py`, and
  `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md`, independently reviewed,
  and added to the repository in this commit. The probe's live `snapshot`
  path remains hard-disabled by `SNAPSHOT_EXECUTION_ENABLED = False`; no
  direct `DaVinciResolveScript` import exists, no prohibited Resolve method
  is called, and no Resolve contact, SQLite access, or live project/timeline
  snapshot has occurred. Python compilation, an independent AST safety
  scan, and the focused mocked test suite (23 passed) all passed against
  the repository copies. The construction hash is not a live-execution
  authorization hash; a future live-capture mission requires a separately
  reviewed execution contract, a new SHA-256, and explicit founder
  authorization tied to that exact revision and commit. Phase 14 remains
  **open and BLOCKED**: this construction does not resolve the
  production-like render rejection root cause and does not authorize any
  live comparison capture.

- The authorized Rev8 dual live snapshots and subsequent offline comparison completed successfully. The exposed project settings and target-timeline settings matched between Control and Production, while the Control target contained one enabled video item and the production-like target contained zero video items. That makes missing video payload the leading exposed discriminator, but the comparison contract does not treat correlation as causation and Phase 14 remains blocked.
- Phase 14 Test D construction r2 keeps the original disposable-Control video-payload isolation experiment and corrects both Important r1 review findings: pre-add evidence is now durably checkpointed before the sole queue mutation, and the active Broadcast Master render context must exactly match `mov` / `DNxHRHQX_10` before `AddRenderJob()`. Exact-byte local integration passed native Windows Python 3.11.9 verification (35 focused Test D tests; 136 combined Phase 14 focused tests). Independent r1-to-r2 review found the harness corrections sound but identified a publication-readiness EOL risk, so `.gitattributes` now pins the four r2 construction artifacts to `text eol=lf` without changing their reviewed bytes. Construction r2 is ready for publication review only; it remains hard-disabled, Phase 14 remains open and BLOCKED, and no Control video-item removal or live Test D queue attempt is authorized by this roadmap entry.
- Independent review of the r2 staged diff found two further Important findings, both corrected in construction r3 without redesigning the experiment: a post-`AddRenderJob()` evidence-write failure can no longer abort the harness before best-effort read-only post-call observation (any such failure is recorded and forces the result to `inconclusive` instead), and the post-removal Control timeline end frame is now restricted to exactly `86424` or `86544`, failing closed on any other value. Native Windows Python 3.11.9 verification reproduced compilation PASS, **41** focused Test D tests, and **142** combined Phase 14 focused tests; the exact r3 hashes were independently re-verified against the working tree. Construction r3, together with this roadmap update, `docs/CHANGELOG.md`, and `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, forms the r3 canonical publication candidate now staged under explicit founder authorization. It remains hard-disabled (`EXECUTION_ENABLED = False`), Phase 14 remains open and BLOCKED, and no Control video-item removal, `AddRenderJob()`, commit, or push is authorized by this roadmap entry.
- The final independent review of the staged r3 candidate found one further Important finding. At construction time, this was corrected in construction r4 as an unstaged correction layered over the preserved r3 index: the r3 end-frame gate accepted `86424` or `86544` at each snapshot independently, so the value could drift between the two mid-run without being caught. r4 binds whichever value the first Test D snapshot observes as that run's expected end frame, requires every later pre-`AddRenderJob()` snapshot to match it exactly (failing closed on drift, before queue mutation), and treats a post-`AddRenderJob()` drift as observation-only evidence that forces `inconclusive` without repair, retry, or restoration. Native Windows Python 3.11.9 verification reproduced compilation PASS, **48** focused Test D tests, and **149** combined Phase 14 focused tests; the exact r4 hashes were independently computed against the working tree. At that construction step, r4 remained hard-disabled (`EXECUTION_ENABLED = False`) and unstaged — the r3 eight-path index was still the only staged candidate — and no Control video-item removal, `AddRenderJob()`, staging, commit, or push was authorized by that entry.
- Paul Jones subsequently and separately authorized the Phase 14 Test D r4 publication-candidate index integration. The reviewed r4 candidate has completed that index integration: the seven reviewed r4 paths were staged, the existing staged `.gitattributes` blob was preserved unchanged, and the Git index now contains the exact eight-path r4 publication candidate with zero unstaged drift. The four hash-bound staged artifacts were re-verified directly from the Git index against their reviewed r4 SHA-256 values; native Windows Python 3.11.9 compilation, the focused Test D suite (**48 passed**), and the combined Phase 14 focused regression (**149 passed, 1327 deselected**) were all reproduced against the staged content, and `git diff --cached --check` exited 0. Construction r4 remains hard-disabled (`EXECUTION_ENABLED = False`), Phase 14 remains open and BLOCKED, and this roadmap entry authorizes only the completed index integration — not commit, push, Control video-item removal, `AddRenderJob()`, or live Test D execution, each of which requires its own separate explicit founder authorization.
- The published r4 publication candidate was committed (`9b26fa0886ae32bf30f30c2384861dfd0338f5a4`, `feat: add Phase 14 Test D r4 isolation controls`) and pushed to `origin/master` under separate, explicit founder authorizations for each step. A further separate authorization then constructed the smallest reviewable execution-enablement revision, `phase14-test-d-video-payload-isolation-execution-enablement-r1`, on top of that immutable, published r4 core: `EXECUTION_ENABLED` becomes `True` only in this new revision, and the static founder-authorization phrase gate is replaced by a value textually bound to the invocation's expected repository commit, expected harness SHA-256, and expected execution-contract SHA-256, failing closed before any Resolve contact on a missing, malformed, or non-exact match. The r4 experiment core (`execute_test_d()`, the temporal end-frame gate, the durable evidence checkpoints, the exact render-context gate, the Media Pool/timeline/project invariants) is unchanged, and the published r4 execution contract, static review, repository review, and `.gitattributes` were not modified. Native Windows Python 3.11.9 verification reproduced compilation PASS, **55** focused Test D tests, and **156** combined Phase 14 focused tests. This construction remains unstaged, is not itself authorized for staging, commit, or push, and does not authorize live execution, Resolve contact, Control video-item removal, or `AddRenderJob()`. Phase 14 remains open and BLOCKED.
- Phase 14 Test D executed once, live, under the enablement-r1 harness bound to repository commit `aedae2ece9009153573b1ac5d0e0657a90513209`. The operator removed exactly the one video TimelineItem (`Redline OS Assembly Test Image.png`) from the disposable Control timeline `RLO-LIVE-ASM-92701_TIMELINE`, retaining the PNG in the Media Pool and the audio TimelineItem untouched. `AddRenderJob()` returned an empty string; the render queue held 0 jobs before and after; the harness classified the result `rejected` (exit code 16). Pre-add evidence proved every other reviewed timeline/project fact — audio, markers, settings SHA-256, Media Pool inventory, timeline start/end, and active `mov`/`DNxHRHQX_10` render context — unchanged from the known-queueable baseline. The approved conclusion: removing the sole video TimelineItem, and nothing else, made the previously queue-accepting Control timeline non-queueable, strongly supporting a required-video-payload precondition for the tested `broadcast_master` path specifically, not a universal Resolve rule. See the full evidence record in `docs/CHANGELOG.md`. This single authorized execution is consumed; no retry, Control restoration, or cleanup was authorized or performed. Phase 14 remains **open and BLOCKED**: this closes the Test D root-cause question but does not by itself resolve production Broadcast Master queue acceptance.
- A renderability preflight is now implemented in `RenderManager.queue_render()`, turning the Test D finding into a standing, transport-independent safety capability rather than a one-off diagnostic: for any preset configured `requires_video_payload: true` (currently only `broadcast_master`), Redline OS now inspects the target timeline's video TimelineItem count via a new `ResolveAdapter.get_video_timeline_item_count()` and fails closed with `RenderTimelineNotRenderableError` before any SQLite output claim or Resolve queue mutation when that count is zero. Nine new focused tests plus eleven new `ResolveScriptAdapter` inspection tests, alongside the existing `RenderManager` suite (updated to place a mock video item so its pre-existing queue-path tests remain representative), pass: 62 in the focused slice, 1291 in the full `tests/unit` regression (5 failures and 15 `cli`-import-shadowing collection errors, all independently traced — via direct traceback analysis on the unstashed working tree, not a stash comparison — to this local machine's Python 3.13 environment and unrelated to this change; see `docs/CHANGELOG.md` for the exact root causes). This does not authorize live Resolve contact or change Phase 14's BLOCKED status; it prevents Redline OS from re-attempting a request already proven non-renderable, and does not resolve the still-open production Broadcast Master queue-acceptance root cause. See `docs/CHANGELOG.md` for full detail and `docs/ARCHITECTURE.md` §3.5 for the updated manager flow.
- A repository-only root-cause investigation found that every existing episode-assembly gate is a counting/string-shape gate — none inspects resulting track content — so `RenderManager`'s renderability preflight was the first and only pipeline component with explicit knowledge of actual video-track content, and only at render-queue time, well after `ASSEMBLED` was already persisted. The investigation could not determine from repository evidence alone whether the production-like `RLC-E9001` episode was ever built through `EpisodeManager.build_episode()`; separate historical live evidence (the disposable Mission 39D SQLite registration) shows `RLC-E9001`'s recorded status was `created`, not `assembled`, so its zero-video state is not proof this assembly pipeline lost video — only that the observability gap itself was real.
- `EpisodeManager.build_episode()` now closes that observability gap with a read-only, post-placement video-payload observation, added immediately after TimelineItem-ID validation and before `EpisodeBuildResult`/`ASSEMBLED` persistence, reusing (not duplicating) `RenderManager`'s existing `ResolveAdapter.get_video_timeline_item_count()`. `EpisodeBuildResult` gains `video_item_count: int`. This is observational only: a `0` count is a valid, non-rejecting V1 result — Episode Manifest V1 has no media-role/track-placement contract, so `EpisodeManager` does not invent a hidden video requirement; `RenderManager`'s preset-scoped `requires_video_payload` preflight remains the sole, unchanged enforcement boundary. Inspection *failure* (not a zero count) fails closed as a new `EpisodeBuildError` stage, `payload_observation`, releasing the assembly claim as `failed` exactly like existing stage failures. Five new tests plus two updated pre-existing test assertions pass: 57 in the focused `EpisodeManager` suite, 226 across the broader related regression (episode, build orchestrator, MCP, render manager, resolve mock/adapter, config, composition — all unchanged), 1296 in the full `tests/unit` regression (exactly +5 over the prior 1291 baseline; the same 5 failures and 15 `cli`-shadowing collection errors previously traced to this local machine's environment, reproduced without any stash-based comparison). No manifest schema, `RenderPreset` schema, renderability policy, CLI, MCP, Resolve queue-reconciliation, or Resolve placement-semantics change is part of this entry. Phase 14 remains open and BLOCKED; this is an observability addition only and does not authorize live Resolve contact. See `docs/CHANGELOG.md` for full detail and `docs/ARCHITECTURE.md` §3.4 for the updated assembly flow.
- RLC-E9901 one-shot live-build authorization preparation found that `video_item_count`, despite being computed since the entry above, was not externally observable after a build: `BuildOrchestrator.BuildResult` dropped the field, the CLI never printed it, it was never persisted to SQLite, and its `logger.info(...)` call used a logger namespace (`"redline_core.episode.manager"`) that `configure_logging()` never attaches handlers to, so the record was silently dropped rather than merely hard to find. This is now corrected: `BuildResult` carries `video_item_count: int` populated verbatim from `EpisodeBuildResult` (no recomputation, no new Resolve call); the CLI prints `Video item count: <N>` in the `Build complete` summary; and `build_episode()` now logs via the existing `get_episode_logger()` helper (the same one `create_episode()` already uses) so its records reach the configured `"redline_os.episode"` handlers. **This changes no build/assembly/render decision**: `video_item_count == 0` remains a valid, non-rejecting result and the build still reaches `ASSEMBLED` and exits `0` regardless of the count — "production build success" and "Phase 14 assembly-proof success" (production success **and** `video_item_count > 0`) remain distinct, externally-evaluated concepts, not a rule `EpisodeManager` enforces. Seven new/updated focused tests pass: 195 across the focused related regression (episode manager, build orchestrator, CLI build, CLI render, build-render workflow, MCP tools); 1578 in the full `tests/unit` regression (exactly +5 over the prior 1573 baseline; the same 24 known Windows-temp-path/YAML failures, no new or different failure). `git diff --check` exited 0. No Resolve mutation surface, render-queue behavior, `EpisodeStatus` semantics, retry behavior, or database schema changed. Phase 14 remains open and BLOCKED; this closes an evidence-capture gap only and does not authorize the RLC-E9901 live build, Resolve contact, staging, commit, or push. See `docs/CHANGELOG.md` for full detail and `docs/ARCHITECTURE.md` §3.4 for the updated observability section.
- **RLC-E9901's own live assembly proof is formally closed and passed** (`PHASE 14 LIVE ASSEMBLY PROOF CLOSED — PASSED`: exit code `0`, final episode state `ASSEMBLED`, `video_item_count: 1`, exactly one live production build invocation, zero render jobs queued, zero renders started). This closure record is stated here explicitly because it had not previously been recorded in this roadmap as its own standing fact, only narrated through the incremental technical entries above. **Closing RLC-E9901's assembly proof does not by itself change, resolve, or narrow Phase 14's separate, still-open Broadcast Master queue-acceptance blocker** (§ above: `AddRenderJob()` returning an empty string against the historical `RLC-E9001_MASTER` project across three controlled live attempts) — assembly proof and queue-acceptance proof remain two distinct objectives under this one Phase 14 label, and only the former is closed. Phase 14 as a whole remains **open and BLOCKED** on the latter.
- A new RLC-E9901-specific, single-context read-only Broadcast Master preflight tooling layer (`scripts/rlc_e9901_snapshot_preflight_contract.py`, `scripts/rlc_e9901_module_provenance_check.py`, `scripts/rlc_e9901_preflight_assertion.py`, fully documented in the new `docs/RLC_E9901_BROADCAST_MASTER_PREFLIGHT_CONTRACT.md`) has completed five construction/independent-review passes (Rev1–Rev5) and **Rev5 has passed independent source review** at the exact hashes recorded in that contract document's header. It wraps the published rev8 collector (`scripts/phase14_resolve_context_snapshot.py`) unmodified rather than editing it. **This tooling has not been executed live as of this entry** — `run_authorized_rlc_e9901_preflight()`/`run-live-preflight` was never invoked during any construction or review pass — and passing source review does not by itself authorize that execution, does not authorize a live Broadcast Master queue attempt, and does not change Phase 14's BLOCKED status. See `docs/CHANGELOG.md` for the full construction/review history and `docs/RLC_E9901_BROADCAST_MASTER_PREFLIGHT_CONTRACT.md` for the complete contract, including the still-required future authorization steps before any live use.
- A new RLC-E9901-specific one-shot production `render queue` attempt harness (`scripts/rlc_e9901_queue_attempt_harness.py`, fully documented in the new `docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md`) has completed the Rev1→Rev7 construction and independent-review cycle and **Rev7 has passed independent source review** at the exact hashes recorded in that contract document's header. It never reimplements or bypasses `RenderManager`/`ResolveAdapter`; its one mutation-bearing operation is exactly one real production CLI process launch, reached only through its own `run-queue-attempt` CLI subcommand. **This harness has never been executed live**: `run_authorized_queue_attempt()`/`run-queue-attempt` was never invoked during any construction or review pass, and `AddRenderJob()` has not been attempted through this harness at any point. Passing source review is not execution authorization. RLC-E9901's own live episode-assembly proof (§ above: `PHASE 14 LIVE ASSEMBLY PROOF CLOSED — PASSED`) remains closed and unaffected by this entry — Rev7 source-review approval does not reopen or alter it. The separate Broadcast Master production render-queue acceptance sub-objective remains open/blocked and still requires a fresh, explicit founder authorization before any live queue attempt through this harness. This entry does not make any broader Phase 14 reclassification. See `docs/CHANGELOG.md` for the full construction/review history and `docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md` for the complete contract, including the still-required future authorization steps before any live use.
- The RLC-E9901 queue-attempt harness's `PRODUCTION_QUEUE_PATH_ACCEPTED` classification proves the production queue path, not independent Resolve-side queue state — its only Resolve contact is one fresh getter-only preflight subprocess run before the mutation, never after. A follow-on Rev8 getter-only context snapshot attempt correctly stopped with `render_queue_not_empty`, because that collector's own safety model requires an empty queue by design and must not be weakened to fit a post-queue observation. A new, generically parameterized (not RLC-E9901-specific) Phase 14 render queue read-only snapshot probe (`scripts/phase14_render_queue_snapshot.py`, its mocked unit test suite at `tests/unit/test_phase14_render_queue_snapshot.py` (53 tests, all passing), and a companion contract at `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md`) has been constructed as the deliberate complement: it explicitly permits a non-empty render queue, reuses Rev8's genuinely pure, Resolve-contact-free helpers by ordinary import without modifying Rev8's published source or SHA-256, and defines its own narrower six-method getter-only allowlist and its own execution interlock (`EXECUTION_REVISION_ID = phase14.2-render-queue-snapshot-construction-rev1`) rather than reusing Rev8's broader allowlist or revision identifier. **No live snapshot has been captured under this revision** — `run_snapshot_command()`/the `snapshot` CLI subcommand was exercised only against injected fake Resolve handles during construction. This construction does not by itself prove RLC-E9901 independent render-queue closure and does not change Phase 14's BLOCKED status; the exact future authorized workflow to obtain that proof is documented in `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §9.1. See `docs/CHANGELOG.md` for full construction detail.
- Independent exact-source review of the Rev1 render queue snapshot probe accepted its architecture and six-method getter-only boundary but found six findings — five BLOCKING/HIGH correctness gaps (exact queue-closure semantics producing a false-pass; shallow snapshot validation that could not detect a forged/inconsistent document; silent first-alias-wins resolution of conflicting job-ID aliases; inherited non-finite-float/non-strict-JSON evidence writing; no context/rendering verification after the final queue read) and one documentation-accuracy issue (`connect_resolve_read_only` imprecisely described as "pure"). All six are corrected in Rev2 (`EXECUTION_REVISION_ID = phase14.2-render-queue-snapshot-construction-rev2`, replacing Rev1's now-rejected `...-rev1`), documented in full in `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §0 and §6, with the getter-only allowlist unchanged (still exactly `GetProjectManager`/`GetCurrentProject`/`GetName`/`GetCurrentTimeline`/`IsRenderingInProgress`/`GetRenderJobList`, no new Resolve method name introduced) and the Rev8 collector still untouched and byte-identical. **Rev2 has not itself been independently reviewed or approved.** The focused test suite grew from 53 to 119 tests, passing under both this workstation's default Python 3.13.5 and the project's documented Python 3.11.9 interpreter; under 3.11 the combined Phase 14/RLC-E9901 regression is a clean 695/695 with zero failures, confirming the previously documented `cli`-package-shadowing and native-process-helper interpreter-identity issues are both artifacts of the 3.13 environment, not genuine regressions. **No live snapshot has been captured under Rev2 either** — this remains a correction to construction-only, offline-tested source. This does not change Phase 14's BLOCKED status or claim RLC-E9901 independent render-queue closure. See `docs/CHANGELOG.md` for full correction detail.
- Independent exact-source review confirmed Rev2 correctly resolved all six Rev1 findings — Rev2's architecture and corrections are accepted — but Rev2 itself did not pass review: two further BLOCKING evidence-integrity gaps were independently reproduced (an entry's stored job ID could contradict its own preserved Resolve field evidence and still validate; the evidence envelope tolerated unknown top-level keys and an unvalidated `captured_at`, including missing/null/NaN/malformed values). Both are corrected in Rev3 (`EXECUTION_REVISION_ID = phase14.2-render-queue-snapshot-construction-rev3`, replacing Rev2's now-rejected `...-rev2` alongside the already-rejected `...-rev1`), documented in full in `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §0/§0.1 and §6.6/§6.7. All previously accepted Rev2 corrections are preserved and re-verified unregressed, and the getter-only allowlist remains unchanged (still exactly `GetProjectManager`/`GetCurrentProject`/`GetName`/`GetCurrentTimeline`/`IsRenderingInProgress`/`GetRenderJobList`, confirmed by static AST inspection); the Rev8 collector remains untouched and byte-identical. **Rev3 has not itself been independently reviewed or approved.** The focused test suite grew from 119 to 166 tests, passing under the project's documented Python 3.11.9 interpreter; the combined Phase 14/RLC-E9901 regression under 3.11 is a clean 742/742 with zero failures and no artificial exclusions. **No live snapshot has been captured under Rev3 either** — this remains a correction to construction-only, offline-tested source. This does not change Phase 14's BLOCKED status or claim RLC-E9901 independent render-queue closure. See `docs/CHANGELOG.md` for full correction detail.
---

## Release History

| Release | Name | Canonical phase | Status |
|---|---|---|---|
| v0.3.0 | Phase 3 Foundation (historical name) | Phase 8A — CLI and Architecture Hardening | Complete |

`v0.3.0` is the early Phase 8A baseline release that completed CLI and
architecture hardening while the broader roadmap's Phase 3 (Media and
Asset Management, including the Reconciliation Engine) had already closed
out separately.

---

## Where to look, not what to assume

- `docs/ARCHITECTURE.md` — original system design, canonical roadmap (§6), risks (§8).
- `docs/ASSET_RECONCILIATION_ARCHITECTURE.md` / `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md` — the Reconciliation Engine's own architecture and slice-by-slice plan.
- `docs/CHANGELOG.md` — the closest thing to real release notes; entries exist per mission/slice.
- `docs/releases/` — versioned release baseline notes (`v0.3.0.md` and future releases).
- `MILESTONES.md` — named-milestone history and live-verification records against real Resolve Studio.
- `README.md` — current "what exists right now" status and still-open items.

This document is a navigation aid, not a live snapshot — re-verify current
repository state (git log, git status, file reads) before relying on any
status above as still current fact.
