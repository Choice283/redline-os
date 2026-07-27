# Redline OS — System Architecture (v0.1 Design)

**Status:** Design phase — no code written yet.
**Scope:** Production operating system that automates the Redline Content episode workflow. Redline OS *consumes* the Redline Universe creative standards (Asset IDs, Showrunner Bible, Broadcast Package V1.0, naming/folder conventions); it does not define or modify them.

---

## 1. System Architecture

Redline OS is an orchestration layer sitting between three things it does not own and one thing it does:

- **Redline Universe project** (external, source of truth for creative standards: Asset IDs, Bible, Broadcast Package, naming/folder conventions).
- **DaVinci Resolve Studio** (external, the actual editing/render engine, controlled via its Python scripting API).
- **The filesystem / media storage** (external, where footage, graphics, and deliverables live).
- **Redline OS itself** (owned): the automation, state tracking, and control logic that ties the other three together.

A hard architectural constraint drives everything below: **DaVinci Resolve's scripting API only works against a live, running Resolve Studio process** (GUI or `-nogui` headless) reachable on the same machine or local network, and only in the Studio (paid) edition — the free edition does not expose scripting at all. There is no cloud/serverless mode for Resolve. This means Redline OS is fundamentally a **local production-workstation service**, not a cloud service, even though it's built with production-grade discipline.

Given that, the architecture is split into three layers:

1. **MCP Server layer** — the interface an LLM (Claude) or other MCP client talks to. Thin. No business logic.
2. **Core Engine layer** (`redline_core`) — all real logic: episode lifecycle, config, database, orchestration. Transport-agnostic — could be driven by MCP, a CLI, or a future dashboard without duplication.
3. **Adapter layer** — isolates messy, version-fragile external integrations (Resolve scripting API, filesystem, future Frame.io/render-farm integrations) behind clean Python interfaces so the core engine never touches raw Resolve API quirks directly.

```
                     ┌─────────────────────────┐
                     │   MCP Client (Claude)    │
                     └────────────┬─────────────┘
                                  │ MCP (stdio/SSE)
                     ┌────────────▼─────────────┐
                     │   redline-mcp (server)    │   ← thin tool wrappers
                     └────────────┬─────────────┘
                                  │ function calls
                     ┌────────────▼─────────────┐
                     │       redline_core        │
                     │  Episode / Asset / Media   │
                     │  Timeline / Render / Archive│
                     │  Config / DB / Logging     │
                     └───┬─────────────┬─────────┘
                         │             │
              ┌──────────▼───┐   ┌─────▼──────────┐
              │ Resolve       │   │ Filesystem /    │
              │ Adapter       │   │ Config / SQLite │
              │ (scripting    │   │                 │
              │  API wrapper) │   │                 │
              └──────┬────────┘   └─────────────────┘
                     │ local scripting API
              ┌──────▼────────┐
              │ DaVinci Resolve│
              │ Studio (running)│
              └────────────────┘
```

---

## 2. Repository Structure

```
redline-os/
├── src/
│   ├── redline_core/
│   │   ├── episode/         # Episode lifecycle state machine
│   │   ├── asset/            # Asset Manager (consumes Asset IDs from Universe)
│   │   ├── media/            # Media Manager (ingest, bin organization)
│   │   ├── timeline/         # Timeline Builder
│   │   ├── render/           # Render Manager
│   │   ├── archive/          # Archive Manager
│   │   ├── resolve/          # DaVinci Resolve scripting API adapter
│   │   ├── config/           # Config loader + schema validation
│   │   ├── db/               # SQLite models + migrations
│   │   └── logging/          # Structured logging setup
│   └── mcp_server/
│       ├── server.py         # FastMCP/MCP SDK entrypoint
│       ├── tools/            # One module per tool group, thin wrappers only
│       └── resources.py      # Read-only MCP resources (episode/config state)
├── tests/
│   ├── unit/                 # Fast, mocked-Resolve tests (CI-safe)
│   └── integration/          # Requires a live Resolve Studio instance (marked, not run in CI)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── MCP_TOOLS.md
│   ├── CONFIG.md
│   └── CHANGELOG.md
├── config/
│   ├── naming.yaml           # References Universe naming conventions
│   ├── folder_structure.yaml
│   ├── render_presets.yaml
│   └── paths.yaml
├── scripts/
│   ├── setup_env.sh / .ps1   # Sets RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB / PYTHONPATH
│   └── bootstrap_db.py
├── pyproject.toml
├── .env.example
└── README.md
```

This matches the required top-level shape (`/src /tests /docs /config /scripts /mcp_server`), with `mcp_server` and `redline_core` both living under `/src` for clean packaging.

---

## 3. Module Breakdown

| Module | Responsibility | Depends on |
|---|---|---|
| **Config System** | Loads and validates YAML config (naming, folders, render presets, paths). Single source of truth for anything environment- or convention-specific. | — |
| **DB Layer** | SQLite schema for episodes, render jobs, archive records. System of record for *pipeline state* — Resolve itself has no queryable "list all episodes" concept. | Config |
| **Logging** | Structured logging (rotating file + console), every log line correlated by episode ID and operation. | Config |
| **Resolve Adapter** | Wraps `DaVinciResolveScript` API: connection bootstrap, project create/duplicate, media pool import, timeline build calls, sequential clip placement, marker placement, render queue control. Absorbs all API quirks (1-based `nodeIndex`, headless inconsistencies, version differences) so nothing upstream touches raw Resolve objects. | Config, Logging |
| **Episode Manager** | Orchestrates the episode lifecycle: create → assets verified → media organized → timeline built → render queued → archived. Owns the state machine and DB records. | DB, Config, Asset/Media/Timeline/Render/Archive managers |
| **Asset Manager** | Verifies required approved graphics/assets exist for an episode, referencing Asset IDs (RLG-001, etc.) defined by the Universe project. Does not create or redefine assets. | Config, Filesystem |
| **Media Manager** | Scans ingest folders, matches raw media to an episode via naming convention, organizes Resolve media pool bins. | Resolve Adapter, Config |
| **Timeline Builder** | Builds/reuses timelines, delegates explicit clip placement requests, and applies markers per Broadcast Package spec (data-driven from config, not hardcoded). It does not duplicate projects or import media. | Resolve Adapter, Config |
| **Render Manager** | Builds render jobs from presets, queues them via Resolve's render queue, polls status asynchronously, routes output to the correct delivery path. | Resolve Adapter, DB, Config |
| **Archive Manager** | On completion, moves/packages finished project + media to archive storage, updates DB status, optionally exports a project archive. | DB, Filesystem, Config |
| **MCP Server** | Exposes the above as MCP tools/resources for an LLM client. No business logic — pure translation between MCP calls and `redline_core` function calls. | All `redline_core` modules |

---

## 3.1 Real Resolve Media Import Boundary

`ResolveScriptAdapter.import_media(project_name, media_paths, bin_name)` is the
first production media-pool operation behind the adapter interface. The public
contract remains a simple list of local file paths in, list of Resolve media item
IDs out.

Implementation flow:

1. Fail fast with `ResolveConnectionError` if the adapter is not connected.
2. Return `[]` immediately for an empty path list, without loading a Resolve project.
3. Validate every path locally with `pathlib.Path`; invalid or non-file paths
   raise `MediaImportError` before any Resolve import API is called.
4. Load the target project through Resolve's `ProjectManager`; failure raises
   `ProjectNotFoundError`.
5. Resolve the media pool root folder, find or create the requested top-level
   bin, and set it as the current media pool folder.
6. Import all validated absolute paths in one `MediaStorage.AddItemListToMediaPool(...)`
   call.
7. Treat falsey results, empty results, partial count mismatches, or imported
   items without `GetMediaId()` / `GetUniqueId()` values as `MediaImportError`.

Failure boundary: local validation failures are all reported together before
Resolve is touched, and partial Resolve imports are not reported as success.
The adapter does not implement recursive scanning, categorization, nested bins,
duplicate detection, or MCP error normalization; those remain separate choices
above this boundary.

Current limitation: if Resolve imports only part of a requested batch, the
adapter raises `MediaImportError`, but imported clips may remain in the
destination bin. Likewise, `SetCurrentFolder(...)` may leave the media pool
selection changed if a later operation fails. Automatic rollback is
intentionally deferred until Resolve cleanup behavior is validated against a
live project.

---

## 3.2 Real Resolve Timeline Operation Boundary

`ResolveScriptAdapter.build_timeline(project_name, timeline_name)` creates or
reuses an empty Resolve timeline by exact name. Timeline names must be non-empty;
if an exact existing timeline is found, it is reused and no duplicate timeline is
created. If Resolve creates a timeline under a different name, Redline OS treats
that as `TimelineOperationError` rather than accepting auto-renaming.

`ResolveScriptAdapter.add_markers(project_name, timeline_name, markers)` validates
all marker dictionaries before loading the project or modifying Resolve. Required
fields are `frame` and `color`; optional fields default to empty strings or a
duration of one frame. All validation failures are reported together via
`TimelineOperationError`.

Failure boundary: marker insertion is sequential. If Resolve accepts earlier
markers and rejects a later one, Redline OS raises `TimelineOperationError` with
the failed marker index, but already-added markers are not automatically rolled
back. If Resolve creates a timeline and later verification fails because
`GetName()` is empty or Resolve auto-renamed the timeline, that created timeline
may remain in the project. Automatic rollback is not implemented; timeline
deletion and marker cleanup are intentionally deferred until those behaviors are
validated against live Resolve.

Live Resolve verification confirmed empty timeline creation, exact-name return,
existing timeline reuse, and no duplicate timeline on a repeated call. Marker
placement was verified at frames 0 and 48, including `customData` round-trip
through `Timeline.GetMarkers()`. Resolve automatically creates default empty
video and audio tracks for a new empty timeline; Redline OS did not add clips,
transitions, or timeline items as part of this operation.

---

## 3.3 Real Resolve Sequential Clip Placement Boundary

`ResolveScriptAdapter.place_clips(project_name, timeline_name, clip_ids)` places
already-imported Media Pool clips on an existing timeline. The public contract is
intentionally narrow for Version 1: clip IDs in, TimelineItem IDs out. Media
Manager remains responsible for importing media and returning Resolve clip IDs;
Resolve Adapter resolves those IDs back to `MediaPoolItem` objects and performs
the placement; Timeline Builder only orchestrates timeline-level calls and does
not automatically place clips during `build_timeline_for_episode()`.

Implementation flow:

1. Fail fast with `ResolveConnectionError` if the adapter is not connected.
2. Return `[]` immediately for an empty clip ID list, without loading a Resolve
   project.
3. Validate all clip IDs and reject duplicate requested IDs before any Resolve
   project or media operation.
4. Load the project through `ProjectManager.LoadProject(...)`; failure raises
   `ProjectNotFoundError`.
5. Find the destination timeline by exact name, then set it current with
   `Project.SetCurrentTimeline(...)`. Resolve's `MediaPool.AppendToTimeline(...)`
   appends into the current timeline, so this state change is required.
6. Resolve the media pool root folder and recursively scan the full folder tree
   with `Folder.GetClipList()` and `Folder.GetSubFolderList()`.
7. Match requested clip IDs using the same identifier priority as media import:
   `MediaPoolItem.GetMediaId()` first, then `GetUniqueId()` fallback.
8. Reject missing or duplicate Media Pool matches before placement.
9. Call `MediaPool.AppendToTimeline([...])` once with an ordered list of
   `MediaPoolItem` objects. Placement order follows `clip_ids`, not Media Pool
   scan order.
10. Treat falsey, non-sequence, empty, partial-count, duplicate TimelineItem ID,
    or TimelineItem-ID extraction failures as `TimelineOperationError`.

Failure boundary: if Resolve appends some clips and then returns an invalid or
partial result, Redline OS reports the operation as failed, but the created
TimelineItems may remain in the Resolve timeline. `SetCurrentTimeline(...)` may
also leave the UI/current timeline changed if a later step fails. Automatic
rollback, clip deletion, explicit record-frame placement, track targeting,
source in/out frames, still-image duration controls, track creation, transitions,
and timeline settings are intentionally deferred until live Resolve behavior is
validated.

Persistent mutations after failure may include the destination timeline remaining
current, some or all requested clips already appended, linked video/audio
TimelineItems already created, successful placement followed by returned-item
validation failure, or TimelineItem ID extraction failure after items were
placed. Redline OS does not attempt automatic rollback or deletion in Version 1.

Version 1 currently expects one returned TimelineItem per requested
MediaPoolItem. Live Resolve verification confirmed that invariant for a still
image MediaPoolItem and an audio-only WAV MediaPoolItem. Valid linked video/audio
behavior still requires a follow-up live test; the count check may need
adjustment if `AppendToTimeline(...)` returns separate linked video/audio
TimelineItems for one source clip.

Live Resolve verification confirmed sequential placement on a newly created
empty disposable timeline: `SetCurrentTimeline(...)` made the intended timeline
current, `AppendToTimeline([...])` returned one TimelineItem per requested
MediaPoolItem, returned TimelineItem IDs were real non-empty `GetUniqueId()`
values, and returned order matched the requested clip ID order. The actual
timeline contained one audio item for the WAV on an audio track and one video
item for the PNG still on a video track. The items were contiguous in timeline
time with no unexpected gap observed. Existing timelines in the disposable test
project were inspected before and after and did not receive new items.

---

## 3.4 V1 Episode Assembly Orchestration Boundary

`EpisodeManager.build_episode(definition)` is the internal Python API for
assembling an already-created episode. It deliberately preserves the distinction
between episode creation and episode assembly: `create_episode()` owns DB row
creation, working folder creation, and Resolve project duplication; assembly
looks up that existing DB record by `episode_id` and uses the stored
`project_name`.

Input is `EpisodeBuildDefinition`: `episode_id`, ordered `media_paths`, optional
`markers`, and `bin_name`. Output is `EpisodeBuildResult`: `episode_id`,
`project_name`, `timeline_id`, `timeline_name`, ordered `media_paths`, ordered
`media_ids`, `markers_applied`, and ordered `timeline_item_ids`. For the tested
V1 media types, positional order is preserved:
`media_paths[index] -> media_ids[index] -> timeline_item_ids[index]`.
`timeline_id` currently reflects the identifier returned by `TimelineBuilder`;
in current implementations this may effectively be the timeline name. It must
not be treated as a stable Resolve UUID unless Resolve later provides one and
Redline OS persists it.

Stage order is fixed:

1. Validate `EpisodeBuildDefinition`.
2. Retrieve and validate the existing episode.
3. Resolve the project name from the episode record.
4. Import explicit media paths through `MediaManager.import_media(...)`.
5. Build or reuse the configured timeline through
   `TimelineBuilder.build_timeline_for_episode(...)`, applying markers there.
6. Place imported clips through `TimelineBuilder.place_clips(...)`.
7. Validate the returned ID counts/values and return `EpisodeBuildResult`.

`EpisodeManager` does not call Resolve import, marker, timeline, or placement
adapter methods directly when a manager already owns that behavior. The shared
MCP application context constructs one Resolve adapter, one `MediaManager`, and
one `TimelineBuilder`, then passes those same instances into `EpisodeManager`.
`build_episode()` is not exposed as an MCP tool in V1.

Rerun policy: once an episode reaches `EpisodeStatus.ASSEMBLED`, another
`build_episode()` call is rejected before media import to avoid silently
duplicating markers or appended clips on an exact-name reused timeline. Episodes
marked `failed` are also rejected in V1 because the status does not record
whether Resolve was already mutated; an explicit recovery/reset policy is future
work. On successful assembly the status is set to `assembled`; expected stage
failures after episode lookup set the status to `failed` when that status update
succeeds. No media IDs, timeline IDs, TimelineItem IDs, or build history are
persisted in SQLite during this milestone.

Failure boundary: V1 does not attempt rollback. If media import fails, imported
MediaPoolItems may remain. If timeline build or marker insertion fails, imported
media, a newly created timeline, or earlier markers may remain. If clip
placement or returned-item validation fails, the destination timeline may remain
current and some or all clips may already be appended. `EpisodeBuildError`
reports the failed stage, episode ID, completed stages, project/timeline names
when known, and progress counts while preserving lower-level exceptions as
`__cause__`. If Resolve assembly succeeds but persisting `assembled` fails, the
Resolve project may already contain all imported media, markers, and clips while
SQLite still shows the prior status; immediate reruns may duplicate work and are
blocked in-process when detected. No rollback exists for this stale-status case.

The stale-status guard is in-memory only. If Resolve assembly completes, the
SQLite `assembled` status update fails, the current process blocks the episode
from rerun, and then Redline OS restarts, that guard is cleared. SQLite may
still show a non-assembled status, and calling `build_episode()` again may
duplicate imports, markers, or clips. This is acceptable only for controlled
manual V1 verification. Operators must not restart and rerun an episode after a
`status_update` failure without inspecting both Resolve and SQLite. This must be
solved before broader MCP or automated assembly use.

Cross-process and concurrent builds are not protected in V1. There is no
database transaction lock, compare-and-set `assembling` state, or cross-process
lock. Two simultaneous `build_episode()` calls may both pass the status guard
and mutate the same Resolve project. Controlled V1 testing must run only one
Episode Assembly operation at a time; concurrency protection is required before
automated or multi-process use.

Live V1 verification against Resolve Studio 21.0.3.7 confirmed the complete
orchestration path using the disposable `redline-os-test-duplicate` project, one
deterministic WAV, one deterministic PNG, two markers, sequential placement,
SQLite `assembled` status update, assembled-rerun rejection, and validation
failure without Resolve mutation. DaVinci Resolve represents timelines as Media
Pool items; when a project is not configured to use a dedicated Timelines bin, a
newly created timeline may appear in the currently active Media Pool bin. During
the V1 Episode Assembly live verification, the created timeline appeared in the
same target bin as the imported WAV and PNG. This is accepted Resolve behavior
for V1 and is not treated as an extra media import or an assembly failure.
Redline OS does not currently change the project-level "Use Timelines Bin"
setting or relocate created timelines. Dedicated timeline-bin organization may
be considered as a separate project-organization feature later.

Episode Assembly inherits the current placement limitation: WAV audio-only and
PNG still-image placement have been live-verified as one returned TimelineItem
per requested MediaPoolItem, but embedded or linked video/audio cardinality,
explicit track targeting, explicit record-frame placement, and rollback remain
future work. Marker frames are not validated against final placed clip duration
in V1.

Episode Manifest V1 is implemented in `src/redline_core/manifest/` and is
documented separately in
`docs/EPISODE_MANIFEST_ARCHITECTURE.md`,
`docs/EPISODE_MANIFEST_SCHEMA.md`,
`docs/EPISODE_MANIFEST_LIFECYCLE.md`, and
`docs/EPISODE_MANIFEST_VALIDATION.md`. The implementation keeps manifest
loading, schema validation, versioning, and path parsing outside
`EpisodeManager`; the manifest layer translates validated YAML intent into the
existing `EpisodeBuildDefinition` execution contract. Pure manifest loading and
validation do not call SQLite, `EpisodeManager`, or DaVinci Resolve.
Controlled live verification on 2026-07-27 confirmed that a validated manifest
can be translated and passed into the existing `EpisodeManager.build_episode(...)`
boundary for a disposable Resolve project without adding YAML awareness to
`EpisodeManager`.

Persistent Asset Registry V1 architecture is documented separately in
`docs/ASSET_REGISTRY_ARCHITECTURE.md`,
`docs/ASSET_REGISTRY_SCHEMA.md`,
`docs/ASSET_REGISTRY_LIFECYCLE.md`, and
`docs/ASSET_REGISTRY_VALIDATION.md`. The design keeps external production
standards authoritative for Asset IDs and approved metadata, treats
`config/assets.yaml` as the desired-state declaration and explicit
reconciliation input, and reserves SQLite registry rows for local operational
state such as path state,
availability, lifecycle, verification facts, timestamps, diagnostics, and
provenance. No implementation, schema migration, MCP exposure, or Resolve
behavior is part of the architecture draft.

---

## 4. Data Flow

Example: **"Create Episode 025"**

1. MCP client calls tool `create_episode(episode_number=25)`.
2. `mcp_server` validates input, calls `redline_core.episode.create_episode(25)`.
3. **Episode Manager** reads `naming.yaml` to compute the episode ID/folder name per the existing convention, checks the DB for conflicts, inserts a DB row (`status = created`).
4. **Asset Manager** verifies required approved graphics exist against the Asset ID registry.
5. **Media Manager** creates the on-disk folder structure (from `folder_structure.yaml`, itself sourced from the Broadcast Package spec — referenced, not redefined).
6. **Resolve Adapter** connects to the running Resolve instance and duplicates the master project template, returning a `Project` handle.
7. **Media Manager** imports matched media into the Resolve media pool; **Timeline Builder** builds/reuses the timeline, can delegate sequential placement for already-imported clip IDs when explicitly called, and applies markers.
8. DB updated to `status = timeline_built`; log entry written; MCP tool returns a structured result (episode ID, project path, status, any warnings) to the client.
9. Later, `queue_render(episode_id=25)` → **Render Manager** builds the job from a preset, calls Resolve's render queue, returns a job ID immediately (render itself may take hours).
10. `get_render_status(job_id)` polls Resolve's render queue state.
11. On completion, **Archive Manager** moves the finished package to archive storage and updates the DB to `status = archived`.

Each arrow above crosses exactly one module boundary — no module reaches two layers down (e.g., Timeline Builder never touches the DB directly; it reports back to Episode Manager, which owns DB writes).

---

## 5. MCP Design

**Server:** `redline-mcp`, built on the official MCP Python SDK or FastMCP.
**Transport:** `stdio` by default (Redline OS runs on the edit workstation alongside Resolve). SSE/HTTP is a future option only if Redline OS ever needs to be driven from a separate machine on the local network — not needed for v0.1, and expanding Resolve's own scripting access beyond local/console has real security implications per Blackmagic's own documentation, so this should stay local-only unless a deliberate, hardened decision is made later.

**Tool groups** (each tool is a thin wrapper calling exactly one `redline_core` function):

- **Episode:** `create_episode`, `get_episode_status`, `list_episodes`, `advance_episode_stage`
- **Asset:** `list_available_assets`, `verify_assets_for_episode`
- **Media:** `import_media`, `organize_bins`
- **Timeline:** `build_timeline`, `add_markers`
- **Render:** `queue_render`, `get_render_status`, `cancel_render`
- **Archive:** `archive_episode`, `list_archives`

**Resources** (read-only, for the LLM to inspect state without invoking mutating tools): `redline://episodes/{id}`, `redline://config/naming`, `redline://config/render_presets`.

**Design rules:**

- Tools validate preconditions and return structured errors rather than throwing — e.g., `queue_render` refuses cleanly if `build_timeline` hasn't run yet.
- Long-running operations (render) are **async by design**: `queue_render` returns a job ID immediately; status is polled separately. A synchronous multi-hour tool call would block the MCP session.
- Destructive tools (`archive_episode`, anything deleting media) require an explicit `confirm=True` parameter.
- The server holds a **single persistent connection** to Resolve and serializes calls against it — Resolve is inherently a single-instance, stateful application, so concurrent uncoordinated script calls are a real risk to guard against, not a theoretical one.

---

## 6. Development Roadmap

| Phase | Goal |
|---|---|
| **0 — Foundations** | Repo scaffold, config schema, DB schema, logging, CI skeleton, mock Resolve adapter for testing. |
| **1 — Resolve Adapter core** | `connect()`, project create/duplicate, basic media pool operations. Verified manually against a real Resolve Studio instance (highest-risk piece — done first, deliberately). |
| **2 — Episode Manager + Config + DB** | Create/list/status-track episodes; no deep Resolve interaction yet. |
| **3 — Media + Asset Managers** | Folder scanning, asset registry checks, ingest-to-episode matching. |
| **4 — Timeline Builder** | Template-based timeline assembly, marker placement. |
| **5 — MCP Server v1** | Expose Phases 1–4 as tools. First end-to-end "create episode" flow through Claude, minus rendering. |
| **6 — Render Manager** | Queue, monitor, presets, async job model. |
| **7 — Archive Manager** | Completes the lifecycle. |
| **8 — Hardening** | Full test coverage, error handling, doc polish, CLI fallback, packaging. |

---

## 7. Version 0.1 Milestones

v0.1 is a **thin, real, end-to-end skeleton** — not a feature-complete system:

- Repo scaffold per Section 2, `pyproject.toml`, CI stub.
- Config system loading `naming.yaml` / `paths.yaml` with schema validation.
- SQLite schema + migration for the `episodes` table.
- Resolve Adapter: `connect()`, `duplicate_project()`, `import_media()`, timeline creation, and marker insertion proven against a real running Resolve Studio instance.
- Episode Manager: `create_episode()` creates a DB row + folder structure + duplicated Resolve project (no timeline or media yet).
- MCP server exposing exactly three tools: `create_episode`, `get_episode_status`, `list_episodes`.
- Logging wired end to end.
- Unit tests for core logic (mocked Resolve) + one manual integration test script for the real Resolve connection.
- Docs: `README.md`, this architecture document, `CONFIG.md`.

If "say 'Create Episode 025' and get a real duplicated Resolve project + DB record" works, v0.1 is done.

---

## 8. Risks and Limitations

- **No cloud/serverless execution.** Resolve scripting requires a live Resolve Studio process on a reachable machine. Redline OS must run on or near the edit workstation.
- **Studio license required.** The scripting API is unavailable in the free edition — every target machine must run Resolve Studio.
- **Headless reliability is inconsistent across Resolve versions.** External script behavior under `-nogui` has varied release to release; pin and test against the specific version in use.
- **Single-instance concurrency.** Resolve doesn't support concurrent scripted sessions cleanly; Redline OS must serialize its own calls (a simple lock in the adapter) to avoid races.
- **Long renders block the render engine.** Tool design must be async from day one, or a real render will hang an MCP call for hours.
- **API version drift.** Resolve's scripting surface has changed before (e.g., `nodeIndex` becoming 1-based in v16.2). Pin a tested version and log API diffs in the changelog on upgrade.
- **Security.** Default scripting permission is Console/local-machine only; enabling network scripting access has explicit security implications per Blackmagic's own docs — stay local-only unless a hardened auth layer is deliberately added.
- **No CI coverage for Resolve-dependent code.** Integration tests need a real workstation with Resolve running; CI can only validate `redline_core` logic against the mock adapter.
- **Convention drift risk.** Naming/folder/Asset-ID conventions must live in config, sourced from the Universe project — hardcoding them inside Redline OS risks the two projects silently diverging.
- **State desync risk.** If someone edits a project manually in the Resolve UI outside Redline OS, the DB and real Resolve state can drift apart. A reconciliation/status-check tool should exist early, not be an afterthought.

---

## 9. Recommendations

1. Build the **Resolve Adapter and its mock test double first** — it's the single highest-risk, most version-fragile piece, and everything else can be developed and tested against the mock before a real Resolve license is even in the loop.
2. Use **`stdio` transport** for the MCP server initially; don't build HTTP/SSE until there's an actual need to control Redline OS from a machine other than the workstation running Resolve.
3. **Pin the exact Resolve Studio version** in config/docs and treat any Resolve upgrade as a deliberate, tested migration — not an automatic assumption that scripts still behave the same.
4. Keep the **MCP tool layer thin** — zero business logic in tool handlers, everything in `redline_core` — so the same core can later power a CLI or dashboard without duplicating logic.
5. Design **render jobs as async (job ID + polling) from v0.1**, even though early renders may be simple, to avoid a painful refactor once real multi-hour renders show up.
6. Treat **SQLite as the source of truth for pipeline state** and **Resolve project files as the source of truth for media/timeline content** — keep these two conceptually separate so it's always clear which system to trust for which question.
7. Start **manual integration testing against a real Resolve Studio license in Phase 1**, rather than trusting documentation alone — community docs for the scripting API vary in accuracy and version coverage.

---

*This document is Redline OS's architectural foundation per the "documentation is part of the implementation" principle. No code has been written against this design yet — next step is Phase 0 (repo scaffold, config schema, DB schema) pending your go-ahead.*
