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
| 6 — Render Manager | Queue, monitor, presets, async job model. | Complete against `MockResolveAdapter`; real `queue_render`/`get_render_status`/`cancel_render` remain `NotImplementedError`, blocked on a Resolve Studio license situation |
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

- Real Resolve integration for `queue_render`/`get_render_status`/`cancel_render`
- Live-production validation beyond what's already verified in `MILESTONES.md`
- Operational recovery / restart procedures
- Packaging and installation hardening beyond the current `pip install -e .` flow
- Logging and diagnostics review
- Performance and failure-injection testing
- Deployment and upgrade documentation

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
| 9 — Episode Production Pipeline | CLI exposure of the existing manifest/build_episode() capability. | Mission 12 complete (`episode validate-manifest`, read-only); Mission 13 complete (`episode assemble`, mutating — unblocked by ADR-0001's atomic assembly claim design). Whether further work remains in this phase has not yet been reviewed. |
| 10 — Render Automation | Real Resolve integration for the render methods still stubbed in Phase 6. | Planned |
| 11 — MCP Expansion | Close the CLI/MCP capability gap (e.g. `place_clips`, episode assembly currently have no MCP tool exposure). | Planned |
| 12 — Production Release | Deployment, upgrade, and operational hardening beyond Phase 8A's scope. | Planned |

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
