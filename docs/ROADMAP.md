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

- Status: **Paused at verified checkpoint** (see Mission 39D.3 below)
- Objective: prove the production-ready build path against a live Resolve
  Studio workstation using one disposable episode.
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
  disposable `RLC-E9001_MASTER` project: `GetRenderPresetList()` found
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
  live queue revalidation against the disposable `RLC-E9001_MASTER`
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
  `RLC-E9001` episode. Phase 14 is **paused at this verified checkpoint**,
  not complete: the production-workflow objective — a successful live
  Broadcast Master queue acceptance — remains unproven. No further live
  queue attempt is authorized without a new root-cause investigation, a
  separately reviewed contract, and fresh explicit authorization.
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
  Resolve integration.

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
