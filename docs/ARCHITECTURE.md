# Redline OS — System Architecture (v0.1 Design)

**Status:** Production-ready platform through Phase 13.
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
│   │   ├── build/            # Build target parsing, manifest resolution, orchestration
│   │   ├── workflows/        # Cross-manager transport-neutral workflows
│   │   ├── resolve/          # DaVinci Resolve scripting API adapter
│   │   ├── config/           # Config loader + schema validation
│   │   ├── db/               # SQLite models + migrations
│   │   ├── logging/          # Structured logging setup
│   │   └── runtime/          # Transport-neutral composition root (composition.py)
│   ├── mcp_server/
│   │   ├── server.py         # FastMCP/MCP SDK entrypoint
│   │   ├── context.py        # Thin alias over redline_core.runtime.composition
│   │   ├── tools/            # One module per tool group, thin wrappers only
│   │   └── resources.py      # Read-only MCP resources (episode/config state)
│   └── cli/                  # Command-line transport (`redline` console script)
│       ├── main.py           # Thin entry point: parser assembly, logging, per-resource dispatch
│       ├── episode_commands.py  # All `episode` action logic (built from ApplicationServices)
│       ├── asset_commands.py    # All `asset` action logic (built from CoreServices, config-only)
│       ├── archive_commands.py  # All `archive` action logic (built from PersistenceServices, config+DB)
│       ├── build_commands.py    # `redline build`, thin transport over BuildOrchestrator
│       └── render_commands.py   # `redline render`, thin transport over RenderManager
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
| **CLI** | Exposes the above as terminal commands (`redline ...`) for a human operator. No business logic — same translation role as the MCP server, for a different caller. | All `redline_core` modules |

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
`media_ids`, `markers_applied`, ordered `timeline_item_ids`, and
`video_item_count` (see "Post-placement video-payload observation" below). For
the tested V1 media types, positional order is preserved:
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
7. Validate the returned ID counts/values.
8. Observe the resulting video TimelineItem count (read-only; see below) and
   return `EpisodeBuildResult`.

`EpisodeManager` does not call Resolve import, marker, timeline, or placement
adapter methods directly when a manager already owns that behavior. The shared
MCP application context constructs one Resolve adapter, one `MediaManager`, and
one `TimelineBuilder`, then passes those same instances into `EpisodeManager`.
`build_episode()` is not exposed as an MCP tool in V1.

Rerun policy (Mission 13, ADR-0001 "Episode Assembly Retry Policy"):
`build_episode()` accepts a transport-neutral, keyword-only
`allow_unsafe_retry: bool = False` parameter. The CLI's `episode assemble
--force` maps directly onto it; no transport implements any part of the
eligibility decision itself — `EpisodeManager` is the sole policy
authority. Eligibility is enforced by an atomic, persisted **assembly
claim**, not the old in-memory guard described in earlier revisions of
this document (see below): two new nullable columns on `episodes`,
`assembly_claim_token` and `assembly_claimed_at`
(`Database.claim_episode_for_assembly()` / `.release_assembly_claim()`).
`_claim_episode_for_build()` is the first thing `build_episode()` calls,
strictly before any Resolve mutation begins, so the claim commits before
any other process can ever observe this episode as unclaimed once
assembly has started.

For an ordinary (non-forced) claim, `claim_episode_for_assembly()` is one
`UPDATE ... WHERE` statement whose rowcount is the sole authority on
whether the claim was acquired — eligibility-check and claim-acquisition
are the same atomic repository operation, never a separate read followed
by a write.

A forced claim (`allow_unsafe_retry=True`) cannot use that same single-
statement shape, because there is no fixed "expected" prior claim-token
value to hard-code into the WHERE clause — the whole point of forcing is
to take over *whatever* claim currently exists, dangling or not. An
earlier version of this design guarded the forced UPDATE only by `status
NOT IN (terminal...)`, with no dependency on the claim token at all; that
allowed two concurrent forced callers racing the same dangling claim to
both satisfy the guard and both acquire it, violating the single-claimant
invariant. The corrected design (`Database._claim_episode_for_assembly_cas()`)
does a diagnostic `SELECT` of the current `(status, assembly_claim_token)`
first, then issues a compare-and-swap `UPDATE` whose `WHERE` clause is
pinned to exactly that observed pair. The `SELECT` authorizes nothing —
it only supplies the two values the guarded `UPDATE` pins to; that `UPDATE`
remains the sole authority on acquisition, since SQLite evaluates its
`WHERE` clause against the row's real, current state at execution time,
not against the caller's possibly-stale read. Once either racer's `UPDATE`
commits, the other racer's `WHERE` clause (still pinned to the original,
now-superseded token) no longer matches, so its `UPDATE` affects zero rows
and it correctly loses the race — regardless of which racer's `SELECT`
happened to run first. A genuinely *sequential* second forced call (one
that freshly observes the first call's already-committed token and
correctly CASes against that current state) can still take over — that is
an operator issuing `--force` a second time with accurate, current
information, not a race, and is intentionally not what this guards
against.

The full status matrix: `CREATED`, `ASSETS_VERIFIED`, `MEDIA_ORGANIZED`,
and `TIMELINE_BUILT` are claimable normally (no claim already active).
`FAILED`, and an episode with an active/unresolved assembly claim from a
prior attempt, are blocked for an ordinary retry but claimable with
`allow_unsafe_retry=True`. `ASSEMBLED`, `RENDER_QUEUED`, `RENDERED`, and
`ARCHIVED` are **always** blocked — no override exists for those statuses
under any flag, ever. On successful assembly, `release_assembly_claim()`
atomically sets `assembled` and clears the claim, but only if the
caller's `claim_token` still matches the row's (token-owned release — a
stale or superseded attempt can never release a claim it doesn't own).
If no row matches (the token was superseded, or the episode vanished),
`release_assembly_claim()` raises `AssemblyClaimReleaseError` — this is a
hard failure by design, not a logged-and-ignored anomaly: silently
returning on a rowcount-0 release would let `build_episode()`'s success
path return an `EpisodeBuildResult` even though the episode was never
actually marked `assembled` and the claim was never actually cleared. No
media IDs, timeline IDs, TimelineItem IDs, or build history are persisted
in SQLite beyond the claim/status fields during this milestone.

Failure boundary: V1 does not attempt rollback. If media import fails, imported
MediaPoolItems may remain. If timeline build or marker insertion fails, imported
media, a newly created timeline, or earlier markers may remain. If clip
placement or returned-item validation fails, the destination timeline may remain
current and some or all clips may already be appended. `EpisodeBuildError`
reports the failed stage, episode ID, completed stages, project/timeline names
when known, and progress counts while preserving lower-level exceptions as
`__cause__`. For any of these mid-assembly failures, `_build_error()` releases
the claim with status `failed`, so an operator (or a forced retry) can act on
it. If Resolve assembly succeeds but persisting `assembled` fails — whether
`release_assembly_claim()` raises because the write itself failed, or because
it raised `AssemblyClaimReleaseError` on a genuine token mismatch — that
exception propagates out of `build_episode()`'s final block as an
`EpisodeBuildError` (stage `status_update`); the claim is deliberately left
set (or, in the token-mismatch case, left exactly as whatever superseded it):
this is the persisted, cross-process "uncertain outcome" signal ADR-0001
requires, and it blocks ordinary retries until an operator inspects both
Resolve and SQLite and, if appropriate, retries with `allow_unsafe_retry=True`.
No rollback exists for this case — `--force` never rolls back, verifies, or
repairs a prior partial Resolve mutation, it only lifts the retry block.

Cross-process and concurrent builds: the assembly claim is a genuine SQLite-
level guarantee, not an in-process guard. For an ordinary claim this is one
atomic `UPDATE ... WHERE` statement; for a forced claim it is the
compare-and-swap `UPDATE` described above. Either way, acquisition is
decided by SQLite evaluating a `WHERE` clause against the row's real,
current state at execution time, backed by SQLite's own file-level locking
— so it holds across separate CLI process invocations and would hold
across true concurrent processes contending for the same episode row. This
replaced an earlier V1 design (documented in prior revisions of this file)
that used an in-memory guard set on the `EpisodeManager` instance; that
guard provided no protection at all through the CLI transport, since a
fresh `EpisodeManager` is constructed on every CLI invocation. See
`docs/adr/ADR-0001-episode-assembly-retry-policy.md` for the full design
rationale, the exhaustive status matrix, and the required atomicity
invariants.

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

### Post-placement video-payload observation

A repository-only investigation into why a production-like episode could
reach `AddRenderJob()` with zero video TimelineItems (see the Phase 14
renderability preflight above, and `docs/CHANGELOG.md`) found that every
gate between `EpisodeBuildDefinition` and `EpisodeStatus.ASSEMBLED` is a
**counting and string-shape** gate — media/manifest schema, import-count
validation, and TimelineItem-ID-count validation all pass identically
whether placed content is video, audio, or both, because none of them
ever inspects actual track content. `RenderManager`'s renderability
preflight (`get_video_timeline_item_count()`) was, until this addition,
the first and only place in the entire pipeline with any explicit
knowledge of resulting video-track content, and it runs only much later,
at render-queue time.

`EpisodeManager.build_episode()` now closes that *observability* gap —
deliberately not a *policy* gap — with the smallest addition that reuses,
rather than duplicates, the existing inspection primitive: immediately
after TimelineItem-ID validation succeeds and before `EpisodeBuildResult`
is constructed or `ASSEMBLED` is persisted, it calls the same
`ResolveAdapter.get_video_timeline_item_count(project_name, timeline_name)`
`RenderManager` already uses, and records the result as
`EpisodeBuildResult.video_item_count`.

This is observational only. A count of `0` is a valid, non-rejecting
result under current V1 semantics — Episode Manifest V1 deliberately has
no media-role or track-placement contract (see
`docs/EPISODE_MANIFEST_ARCHITECTURE.md` §Non-Goals), so `EpisodeManager`
must not invent a hidden "every assembled episode must contain video"
requirement. **`ASSEMBLED` means the requested media successfully passed
the existing import and placement contracts and the resulting video
payload was observed — it does not mean the timeline is renderable by
every preset.** Renderability remains independently and exclusively
enforced by `RenderManager`'s preset-scoped `requires_video_payload`
preflight, unchanged by this addition, which is the only component
permitted to reject a queue request on this basis.

Failure semantics differ sharply from the zero-count case: if
`get_video_timeline_item_count()` itself *raises* — Resolve cannot
reliably report the count — assembly fails closed. This is reported as a
new `EpisodeBuildError` stage, `payload_observation`, following the exact
existing stage-failure pattern (`_build_error()` releases the assembly
claim as `failed`, so `ASSEMBLED` is never persisted and the claim's
"uncertain outcome" signal per ADR-0001 applies exactly as it does for
media-import, timeline-build, or clip-placement failures). Inspection
returning `0` and inspection *raising* are treated as categorically
different outcomes: the former is a fact worth recording; the latter is
an unknown that must not be silently treated as either "zero" or
"success."

**Exposing the observation externally.** For one revision, `video_item_count`
existed only inside the in-memory `EpisodeBuildResult` returned by
`build_episode()` — `BuildOrchestrator.BuildResult` dropped the field when
constructing its own transport result, the CLI never printed it, and it was
never persisted to SQLite. A separate root cause compounded this: the
`logger.info(...)` calls recording it used `EpisodeManager`'s module-level
`logging.getLogger(__name__)` (`"redline_core.episode.manager"`), a logger
namespace `configure_logging()` (`src/redline_core/logging/setup.py`) never
attaches handlers to — only the `"redline_os"` tree reaches the configured
console/rotating-file handlers, so the record was silently dropped rather
than merely hard to find. Both are now corrected: `BuildResult` carries
`video_item_count: int`, populated verbatim from `EpisodeBuildResult` in
`_build_result()` (no recomputation, no new Resolve call); `cli/build_commands.py`
prints `Video item count: <N>` in the `Build complete` summary; and
`build_episode()` resolves its `logger` via the existing `get_episode_logger()`
helper (the same one `create_episode()` and `resolve/adapter.py`'s own
queue-identity diagnostic logger already use), so its log records reach the
configured handlers under `"redline_os.episode"`.

**This does not change what `ASSEMBLED` means or when assembly fails.**
`video_item_count == 0` remains a valid, non-rejecting V1 result — the build
still reaches `ASSEMBLED` and exits `0`. "Production build success" (exit
`0`, final state `ASSEMBLED`) and "Phase 14 assembly-proof success"
(production build success **and** `video_item_count > 0`) are different
concepts: the former is unconditional production behavior; the latter is an
external, experiment-specific classification evaluated from `BuildResult`
after the fact, not a rule `EpisodeManager` or `RenderManager` enforces.

Evidence correction: an earlier repository-only investigation could not
determine, from committed repository evidence alone, whether the
production-like `RLC-E9001`/`RLC-E9001_MASTER` episode referenced
throughout Phase 14 (Missions 39A–39I, Test B/C/D) was ever built through
`EpisodeManager.build_episode()` at all. Separate historical live evidence
(the disposable Mission 39D SQLite registration for `RLC-E9001`/
`RLC-E9001_MASTER`) shows that episode's recorded status was `created`,
not `assembled` — meaning it is not evidence of an `EpisodeManager`-driven
assembly reaching `ASSEMBLED` with zero video payload. `RLC-E9001`'s
historical zero-video state must not be documented as proof that this
assembly pipeline itself lost video; it remains proof only that the
general observability gap this addition closes was real and unguarded
until now.

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

## 3.5 Real Resolve Render Queue Boundary

Mission 14 began canonical Phase 10 (Render Automation) by implementing only
the real Resolve queue mutation. Mission 39B tightens the production queue
boundary: `RenderManager` owns deterministic output planning, collision policy,
atomic active-output claims, and SQLite ordering;
`ResolveScriptAdapter.queue_render_job(...)` receives the already prepared
project, timeline, Resolve preset, target directory, and custom filename stem.

Render queueing is enqueue-only. It must not call `StartRendering()` unless the
existing adapter contract is explicitly changed in a later architecture
decision. The current async design remains: queueing returns a Resolve job ID
quickly, while `get_render_status()` remains the separate polling boundary.

Render output naming is deterministic and preset-configured through
`config/render_presets.yaml`: a queueable preset declares a filename template,
explicit extension, and `collision_policy: reject`. Redline rejects an exact
existing output file, inspectable Resolve queue jobs targeting the same output,
and concurrent active Redline jobs through an atomic SQLite output claim before
adding a new Resolve job. The canonical Broadcast Master standard is consumed
from the externally approved production convention `{project_name}.mov`; Redline
OS represents it as `broadcast_master` -> `Redline Broadcast Master`,
`output_subfolder: exports`, `filename_template: "{project_name}"`,
`file_extension: ".mov"`, and `collision_policy: reject`.

Presets that still lack an approved `filename_template` or `file_extension`
remain fail-closed before Resolve, SQLite render-job insertion, or output
filesystem mutation. This still applies to `youtube_1080p` until a separate
YouTube export filename standard is approved.

Manager flow:

1. Resolve the named render preset from configuration.
2. Construct one immutable `RenderOutputPlan` containing project, timeline,
   target directory, output stem, extension, and full expected output path.
3. Reject exact output-file collisions.
4. Inspect Resolve's queue and reject matching project/timeline/`TargetDir`/
   `CustomName` jobs where those fields are available.
5. Run the renderability preflight (below). A preset-specific requirement
   failure raises `RenderTimelineNotRenderableError` here, before any SQLite
   claim or Resolve queue mutation.
6. Atomically claim the output path in SQLite with status `claiming`; only the
   claim winner may proceed to Resolve queue mutation.
7. Submit the prepared request to Resolve.
8. If Resolve rejects the request, release the SQLite claim and surface the
   Resolve failure.
9. Finalize the SQLite claim as `queued` only after Resolve returns a usable
   job ID.
10. If SQLite finalization fails after Resolve accepts the job, attempt a
    best-effort `DeleteRenderJob(resolve_job_id)`. If deletion fails, surface a
    reconciliation-required error containing the Resolve job ID.

### Renderability preflight (post-Test-D)

Phase 14 Test D (see `docs/CHANGELOG.md` and `docs/ROADMAP.md` Phase 14) found
that the known-working disposable Control timeline stopped being queueable
once its sole video TimelineItem was removed, with audio, markers, Media Pool
inventory, project/timeline settings, and active render context otherwise
unchanged. `RenderManager` now turns that finding into a standing,
preset-scoped safety check rather than a one-off diagnostic.

`RenderPreset` (`config/render_presets.yaml`) carries an explicit
`requires_video_payload: bool` field, default `False`. Only `broadcast_master`
is currently `true`, based on the Test D evidence; this is a per-preset
capability declaration, not a universal Resolve rule, so `youtube_1080p` and
any future preset are unaffected unless separately approved.

When a preset requires video, `RenderManager._enforce_renderability()` calls
one new `ResolveAdapter` method, `get_video_timeline_item_count(project_name,
timeline_name)`, and raises `RenderTimelineNotRenderableError` — naming the
target project, timeline, preset, and failed requirement, and stating that
queue submission was not attempted — when the count is zero. `MockResolveAdapter`
implements the count deterministically (default `0`) with a test-only
`set_video_timeline_item_count()` helper; `ResolveScriptAdapter` implements it
with the same `Timeline.GetTrackCount("video")` /
`Timeline.GetItemListInTrack("video", index)` calls verified during Test D
evidence capture, and fails closed (`TimelineOperationError`) rather than
assuming renderability when Resolve inspection data is missing, invalid, or
raises. This preflight answers "should Redline OS attempt this render queue
operation?" and is a distinct concern from the Mission 39D/39D.2
post-`AddRenderJob()` reconciliation classification, which answers "what
happened after `AddRenderJob()` was called?" — that reconciliation behavior is
unchanged by this addition.

Implementation flow:

1. Fail fast with `ResolveConnectionError` if the adapter is not connected.
2. Validate project, timeline, preset, target directory, and custom name as
   non-empty strings before any Resolve mutation.
3. Load the target project through `ProjectManager.LoadProject(...)`; failure
   raises `ProjectNotFoundError`.
4. Verify and select the requested timeline.
5. Snapshot the render queue with `Project.GetRenderJobList()` before any new
   job is added.
6. Apply the named render preset through `Project.LoadRenderPreset(...)`;
   falsey results raise `RenderJobError`.
7. Apply output settings through `Project.SetRenderSettings({"TargetDir": ...,
   "CustomName": ...})`; falsey results raise `RenderJobError`.
8. Capture a best-effort, read-only pre-add render context for diagnostic use
   only: requested project, requested/current timeline names, preset name, the
   exact applied `TargetDir`/`CustomName`, normalized target-directory
   existence/type/read-access status, sanitized render-settings keys/value
   types when `Project.GetRenderSettings()` is available, and, if available,
   the current render format/codec via
   `Project.GetCurrentRenderFormatAndCodec()`. A failed or unavailable read
   never blocks `AddRenderJob()`.
9. Add exactly one render job with `Project.AddRenderJob()`.
10. Extract the Resolve job ID directly from `AddRenderJob()` when it returns a
    usable scalar ID. If it does not, snapshot `GetRenderJobList()` again and
    derive the one newly appeared job ID deterministically.
11. Reject missing, duplicate, or ambiguous job-ID candidates rather than
    guessing (see failure boundary below for exact classification).

Failure boundary: Resolve render settings are project-mutating operations.
If `LoadRenderPreset()` or `SetRenderSettings()` succeeds and a later step
fails, the project may retain those render settings. If `AddRenderJob()`
succeeds but Redline OS cannot extract or reconcile a usable job ID, the
manager releases the active SQLite claim and no queued SQLite row is
created, exactly as before. If Resolve returns a usable job ID and SQLite
finalization fails, `RenderManager` attempts to delete the newly accepted
Resolve job before surfacing the persistence failure.

Post-`AddRenderJob()` reconciliation failures are classified into two
distinct adapter exceptions, both subclasses of `RenderJobError`, rather
than a single undifferentiated `RenderJobError`:

- `RenderQueueIdentityUnresolvedError` — the general case. Raised when the
  after-phase `GetRenderJobList()` snapshot is unavailable, contains an
  unidentifiable item, yields multiple new candidate job IDs, or yields zero
  candidates without satisfying the exact empty-string/identical-ID-multiset
  predicate required for `RenderQueueAcceptanceNotObservedError`. This is
  Redline stating that Resolve's queue state is genuinely uncertain, not
  just unreachable or misconfigured.
- `RenderQueueAcceptanceNotObservedError` — a narrower, more confident
  claim reserved for exactly one evidence shape: `AddRenderJob()` returned
  an empty string, the after-phase snapshot itself succeeded, contained no
  unidentified item, and the before/after job-ID multisets are exactly
  equal (no new candidate at all). Only job IDs are compared, not other
  per-item queue metadata. Multiset *equality*, not merely zero new
  candidates, is what's checked here — if an existing job disappears
  between snapshots and this leaves zero new candidates, it stays on the
  more cautious `RenderQueueIdentityUnresolvedError` path rather than being
  read as confirmed non-acceptance, since a job vanishing is itself
  suspicious. This classification only runs when step 10 does not already
  return a single successful candidate; a disappearance that coincides
  with exactly one new candidate resolves as a direct success through that
  earlier, unrelated deterministic-derivation step and is never inspected
  here.

In both cases the manager releases the active SQLite claim and no queued
SQLite row is created; neither case starts rendering, retries, or mutates
Resolve further.

Live status (Mission 39D.3, executed against commit `2e36a41`): a fully
reviewed, freshly authorized, one-shot live queue attempt against the
production-like `RLC-E9001_MASTER` project exercised this exact reconciliation
path. A temporary active-output claim was acquired before the Resolve
call and released after the failure; postflight found zero render-job
rows and zero active output claims. `AddRenderJob()` returned an empty
string with `render_format='mov'`/`render_codec='DNxHRHQX_10'` genuinely
captured as active at the moment of the call — confirming the expected
format/codec were observed, though this does not identify the root cause
or rule out other Resolve-side conditions. The attempt was classified
`RenderQueueAcceptanceNotObservedError`. Across three controlled live
attempts, the live queue path has failed closed with consistent
postflight state each time — successively exposing the missing-ID
condition, validating the identity-unresolved diagnostics, and validating
this final acceptance-not-observed classification — but none has yet
observed Resolve accept the Broadcast Master request for the
production-like episode. Mission 39D is formally closed, but Phase 14 remains open and
blocked: Broadcast Master queue acceptance remains unproven because Resolve
returned an empty `AddRenderJob()` result and no new queue job ID was observed.
No further live queue submission is authorized without a new root-cause
investigation, a separately reviewed attempt contract, and fresh explicit
founder authorization. See Phase 14 in `docs/ROADMAP.md`.

`RenderJobError` remains the adapter's domain-specific render failure base
type, and the sole type for pre-acceptance failures (connection, validation,
project/timeline/preset/settings rejection, or an explicit `AddRenderJob()
== False`). Unexpected Resolve API exceptions are wrapped as `RenderJobError`
while preserving the original exception as `__cause__`.

Diagnostic logging for both post-`AddRenderJob()` reconciliation exceptions
is centralized in one best-effort helper, routed through the
`redline_os.resolve.adapter` logger (a child of the `redline_os` namespace
`configure_logging()` owns, so it reaches the configured console and
rotating-file handlers — see Logging below) rather than the adapter's
routine module-level logger. It records project name, preset name, the raw
`AddRenderJob()` return type/repr, before/after job-ID lists and counts,
after-list item types/keys, candidate job IDs, sanitized before/after queue
inventories, a diagnostic-only structural queue comparison, the underlying
reconciliation error's type/repr, a machine-searchable
`reconciliation_outcome` field (`acceptance_not_observed` or
`identity_unresolved`, never embedded only in prose), and the pre-add context
captured in implementation-flow step 8. Queue inventories record only
counts, item types, dictionary key names, usable job IDs, missing-ID counts,
and structural fingerprints; they do not log arbitrary queue object values.
The structural comparison is not an acceptance rule: the job-ID multiset
remains the sole authoritative queue-acceptance mechanism. Logging is
best-effort and can never mask either domain exception, including when the
logger itself fails.

`get_render_status()` and `cancel_render()` remain separate command boundaries.
Queueing must not poll status, cancel, archive, or start rendering.

Live Resolve verification on 2026-07-29 used DaVinci Resolve Studio 21.0.3.7
and Python 3.11.9 against the disposable `redline-os-test-duplicate` project,
the built-in `YouTube - 720p` preset, and
`C:\Users\pj198\Documents\redline-os\.artifacts\render-tests` as the output
directory. The queue was empty before the call. `Project.AddRenderJob()`
returned the string UUID `6ac314da-9c99-41eb-bf79-621e5f6b7edc`, and the
post-call `Project.GetRenderJobList()` contained exactly one job with the same
`JobId`. No render was started by Redline OS as part of this verification. The
queued Resolve job was left in the disposable project's render queue for manual
inspection rather than deleted by adapter code.

Phase 14 Test B (disposable project, custom preset) and Test C
(production-like project, built-in preset) complete the project x preset
isolation matrix begun by the 2026-07-29 control and the Mission 39D/39D.3
attempts documented above. Test B confirmed one matching render-queue job
accepted for the custom `Redline Broadcast Master` preset against the
disposable `redline-os-test-duplicate` project — confirmed by post-execution
queue-state recovery rather than the original harness's own
return-value/exit-code output, which was not preserved. Test C returned an
empty `AddRenderJob()` string and an unchanged queue for the built-in
`YouTube - 720p` preset against the production-like `RLC-E9001_MASTER`
project. Both presets were therefore accepted in the disposable control
context and rejected in the `RLC-E9001_MASTER`/`RLC-E9001_TIMELINE` context,
ruling out either preset being universally incapable of queue acceptance
while leaving the exact project- or timeline-level cause unidentified. See
the Phase 14 Test B/Test C entry in `docs/CHANGELOG.md` for full evidence and
`docs/ROADMAP.md` for current Phase 14 status.

A dual project/timeline read-only snapshot and offline comparison probe
(`scripts/phase14_resolve_context_snapshot.py`), its mocked unit test suite
(`tests/unit/test_phase14_resolve_context_snapshot.py`), and a companion
comparison contract (`docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md`) have
been constructed and independently reviewed to support inspecting the two
Test B/Test C contexts side by side. The probe's `snapshot` CLI path is
hard-disabled by `SNAPSHOT_EXECUTION_ENABLED = False`, checked before Resolve
connection is attempted; the source contains no direct `DaVinciResolveScript`
import and no call to any prohibited Resolve method, confirmed by an
independent AST safety scan showing the read-only accessor allowlist and the
prohibited method set are disjoint. Python compilation and the mocked test
suite (23 tests) both passed against the repository copies. No Resolve
contact, no SQLite access, and no live snapshot capture has occurred. This
construction hash is not a live-execution authorization; a future
live-capture mission requires a separately reviewed execution contract, a new
SHA-256, and explicit founder authorization tied to that exact source
revision and repository commit. Phase 14 remains open and blocked; the
production-like render rejection root cause described above is unresolved by
this construction.

## 3.6 Real Resolve Render Status Boundary

Mission 15 implements only
`ResolveScriptAdapter.get_render_status(resolve_job_id) -> str`, preserving the
existing adapter contract. Because the interface intentionally receives only a
Resolve render job ID, status lookup is scoped to the currently loaded Resolve
project through `ProjectManager.GetCurrentProject()`. The adapter must not
search every project, silently load another project, or modify the active
project.

On Resolve Studio 21.0.3.7, `GetRenderJobList()` returns render-job inventory
and metadata but does not include live status. `GetRenderJobStatus(job_id)` is
therefore the authoritative status API. It returns a dictionary containing
`JobStatus` and `CompletionPercentage` for known jobs and `None` for unknown
jobs. Mission 15 consumes only `JobStatus`; completion percentage remains a
future feature because the current adapter contract returns only a status
string.

Status mapping is centralized in the real adapter and intentionally limited to
verified or approved values: `Ready` maps to `queued`, `Rendering` to
`rendering`, `Complete` to `complete`, `Failed` to `failed`, and both
`Cancelled` and `Canceled` to `cancelled`. Matching is case-insensitive and
trims surrounding whitespace. Unknown but well-formed Resolve statuses return
`unknown`, preserving `RenderManager`'s existing behavior of ignoring
unrecognized adapter statuses rather than overwriting the database row.

Malformed known-job responses are hard failures: non-dictionary responses,
missing `JobStatus`, empty `JobStatus`, and non-string `JobStatus` raise
`RenderJobError`. Unexpected Resolve API exceptions are wrapped in
`RenderJobError` with the original exception preserved as `__cause__`.
`cancel_render()` remains unimplemented for real Resolve after Mission 15.

## 3.7 Real Resolve Render Cancellation Boundary

Mission 16 implements only
`ResolveScriptAdapter.cancel_render(resolve_job_id) -> None`, preserving the
existing adapter contract and leaving `RenderManager`, SQLite, CLI, and MCP
contracts unchanged. The lookup is scoped to the currently loaded Resolve
project, matching Mission 15's current-project boundary.

Queued renders are cancelled by deleting the queued Resolve job. On Resolve
Studio 21.0.3.7, `DeleteRenderJob(job_id)` returns `True` for a known queued
job, removes the job from `GetRenderJobList()`, and makes
`GetRenderJobStatus(job_id)` return `None`. For unknown jobs it returns
`False`; Redline treats unknown jobs as `RenderJobError` rather than silently
succeeding.

Active renders are cancelled through the project-scoped `StopRendering()` API
only after Redline verifies that the requested job is the active render. Because
`StopRendering()` does not accept a job ID and returns `None` on Resolve Studio
21.0.3.7, success is determined through postconditions, not its return value:
`IsRenderingInProgress()` must become `False`, and
`GetRenderJobStatus(job_id)["JobStatus"]` must become `Cancelled`. Redline
uses a short bounded adapter-local retry for those postconditions, not a polling
worker or configurable background loop.

A successfully stopped active job remains in Resolve's render queue with status
`Cancelled`; Redline does not delete it automatically. Queue cleanup is a
separate operation from cancellation and could create a partial-failure
inconsistency: if `StopRendering()` succeeds but a later delete fails,
`RenderManager` would not update SQLite even though the render actually
stopped. Preserving the cancelled queue entry keeps Resolve-side evidence and
allows `RenderManager` to mark the Redline row `cancelled` once the adapter
returns.

Terminal Resolve statuses (`Complete`, `Failed`, `Cancelled`, and `Canceled`)
are rejected with `RenderJobError`, even though live probing showed Resolve can
delete completed queue entries. Redline follows its existing mock policy here:
terminal jobs are not cancellable. Unsupported or malformed Resolve statuses
and malformed API responses are also `RenderJobError`.

## 3.8 Production Render Start Path (Rev4 correction; not yet live-verified)

Redline OS supported `render queue`/`render status`/`render list`/
`render cancel` but had no reviewed production pathway to actually start a
queued render — only an ad-hoc live script could call `StartRendering()`.
This section adds `ResolveAdapter.start_render(*, project_name,
timeline_name, resolve_job_id, output_path) -> None`/
`RenderManager.start_render(job_id) -> RenderJob`/`redline render start
<job_id>`, completing the render lifecycle with the same layered
architecture (CLI → RenderManager → ResolveAdapter → Resolve) every other
render command already uses. **As of this addition, `start_render()` has
been constructed and unit-tested against `MockResolveAdapter` only — it
has not been verified against a live, running Resolve Studio instance.**

Independent exact-source review: the first construction (Rev1) returned
**REVISION REQUIRED** (10 findings, 8 blocking); the Rev2 correction was
architecturally accepted but returned **not yet approved for publication
or live execution** (7 further findings, 4 blocking); the Rev3 correction
had its overall architecture and safety model **ACCEPTED**, with one
narrow BLOCKING integration mismatch found against live getter-only
evidence (see Rev4 below). This section describes the corrected (Rev4)
design; see `docs/RENDER_START_PATH_CONSTRUCTION.md` §6/§7/§8 for the full
finding-by-finding correction record.

**Rev4 correction — `OutputFilename` is the complete filename, not the
stem.** Rev3's queued-output-destination check derived
`Path(expected_output_path).stem` and compared it against the matched
queue entry's `OutputFilename`. Live getter-only evidence captured from a
real, running Resolve Studio 21.0.3.7 instance's `GetRenderJobList()`
(`RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json`, SHA-256
`f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975`) shows
Resolve reports `OutputFilename` as the complete filename, extension
included (observed: `"OutputFilename": "RLC-E9901_MASTER.mov"`, not
`"RLC-E9901_MASTER"`) — so Rev3's comparison would have failed closed
before `StartRendering()` against the real queue shape it was meant to
verify. `_require_exact_queued_output_destination()` now derives
`Path(expected_output_path).name` (the complete filename) instead, with
no extension stripped and none inferred from codec/format.

**Exact Resolve API signature (verified from the local Resolve Scripting
README, not guessed):**

```text
StartRendering(jobId1, jobId2, ...)                  --> Bool
StartRendering([jobIds...], isInteractiveMode=False) --> Bool  # job-ID-targeted
StartRendering(isInteractiveMode=False)              --> Bool  # starts every queued job
```

`ResolveScriptAdapter.start_render()` uses only the job-ID-targeted list
form, `StartRendering([resolve_job_id], isInteractiveMode=False)` — never
the zero-argument form, which would start every queued job regardless of
which one was requested.

**Project, timeline, and output-destination identity binding.** Unlike
`get_render_status()`/`cancel_render()`'s existing current-project-only
boundary (§3.6/§3.7), `start_render()` does not trust that whatever
project/timeline/destination happens to be current in Resolve is the one
the caller actually intends — Rev1's reasoning that reusing that same
boundary was acceptable "because status/cancel already do it" was rejected
by independent review specifically for a brand-new mutation pathway.
Before the `StartRendering()` mutation call, three getter-only checks run:
(1) `GetCurrentProject().GetName()` must equal exactly the render job's
persisted `project_name` — never calls `LoadProject()`, never switches
projects; (2) exactly one entry in `GetCurrentProject().GetRenderJobList()`
must *strictly* resolve to the requested `resolve_job_id`, and that
entry's own timeline identity must strictly resolve to exactly the render
job's persisted `timeline_name` — never calls `SetCurrentTimeline()`;
(3) that same matched entry's own `TargetDir`/`OutputFilename` must
strictly resolve to exactly the directory/**complete filename** (extension
included — Rev4 correction, see below) derived from the render
job's persisted `output_path` — never calls `SetRenderSettings()` or
`LoadRenderPreset()` to reconcile a mismatch (the already-queued job's
destination is immutable for this operation; a mismatch means stop, not
repair). `RenderManager` sources all four values (`project_name`,
`timeline_name`, `resolve_job_id`, `output_path`) from the persisted
`RenderJob` row and rejects a non-string, blank, or improperly-whitespaced
value before the start-specific adapter call (Rev3 Finding 6 — none of
this claims Resolve was never *connected to* at all; application
composition connects the adapter unconditionally before any CLI command
dispatches — see Rev3 Finding 5).

**Strict alias resolution (Rev3, Findings 1–3).** Checks (2) and (3) use a
new, start-pathway-owned `_strict_alias_value()` — deliberately separate
from the legacy, precedence-based helper other pathways
(`queue_render_job()`'s reconciliation, `cancel_render()`) still use
unchanged. It inspects *every* present recognized alias for a field
(Job-ID: `JobId`/`JobID`/`jobId`/`job_id`/`Id`/`ID`/`id`; timeline:
`TimelineName`/`Timeline`/`timeline_name`/`timelineName`; target
directory: `TargetDir`/`targetDir`/`target_dir`; output filename:
`OutputFilename`/`outputFilename`/`output_filename`), not merely the
first in precedence order: agreeing values are accepted, a
`bool`/`int`/`dict`/any other non-string or blank value is malformed and
fails closed, and multiple present-but-conflicting valid values fail
closed. A malformed job-ID entry anywhere in the render queue — not only
one that superficially overlaps the requested ID — fails the whole lookup
closed, since its true identity can't be ruled out.

**Precondition, in order:** connected; `project_name`/`timeline_name`/
`resolve_job_id`/`output_path` are each non-empty strings; current-project
identity match; queued-job/timeline identity match (strict); queued
output-destination match (strict); `GetRenderJobStatus(resolve_job_id)`
returns a dict (not `None` — job must exist); the job's own `JobStatus` is
exactly `Ready` (`Rendering`, every terminal status, and any unrecognized
status each fail closed with a distinct message, mirroring
`cancel_render()`'s exact status-branch structure); and, independently of
the target job's own status, `IsRenderingInProgress()` is **exactly**
`False` (Rev1 only rejected exact `True`, silently permitting
`None`/`0`/`1`/a string/a container/any other observed value through).

**One-call mutation guarantee.** `StartRendering()` is reachable from
exactly one call site in the entire adapter module (proved by a static AST
test, not merely by convention) — inside `_invoke_start_rendering_and_reconcile()`,
called only after every precondition above has passed — called at most
once per `start_render()` invocation, with no loop wrapping it in any
start-pathway function.

**Outcome reconciliation (Rev3 Finding 4).** The documented contract is
only `StartRendering(...) --> Bool` — no stronger documented guarantee
that an exact `False` proves no side effect or transient start occurred.
Once the call has actually been made, `True`, `False`, an exception, and
any non-boolean return value are all resolved **identically**: via the
same bounded, getter-only poll of `GetRenderJobStatus(resolve_job_id)`
(5 attempts, 0.1s apart, the budget already established for
`cancel_render()`'s own postcondition wait) for `JobStatus == "Rendering"`.
Confirmed within budget: treated as success regardless of which raw
signal preceded it — the mutation call did happen and may have taken
effect even behind an unusual or negative-looking return. Not confirmed
within budget: raises `RenderStartReconciliationRequiredError`, never a
plain `RenderJobError` — Rev1's claim that an adapter failure always
leaves a state where "a fresh `start_render()` call is safe" was rejected
by review for exactly this case (once `StartRendering()` had already been
invoked), and Rev2's treatment of exact `False` as an unambiguous,
no-reconciliation-needed rejection was itself rejected by Rev3 review for
the same underlying reason: no return value is trustworthy proof by
itself once the mutation call has happened. The reconciliation-required
exception's own semantics: the mutation was attempted, the final live
Resolve state is not proven, and it must not be retried until manual,
getter-only reconciliation establishes the truth. `StartRendering()`
itself is never called a second time under any outcome.

**RenderManager.start_render()** rejects a missing DB job
(`RenderJobNotFoundError`), a job with no persisted `resolve_job_id`
(`RenderJobMissingResolveIdError` — the job was never accepted by Resolve,
or acceptance was never confirmed), any job whose DB status is not exactly
`RenderJobStatus.QUEUED` (`RenderJobNotStartableError` — covers an
already-`RENDERING` job and every terminal status), a `QUEUED` job whose
persisted `project_name`/`timeline_name`/`resolve_job_id`/`output_path`
are not each a usable string (`RenderJobNotStartableError` — a non-string,
blank, or improperly-whitespaced value fails closed rather than being
silently repaired, Rev3 Finding 6), and a `QUEUED` job whose expected
output path already exists on disk (`RenderOutputCollisionError`, "Render
start mutation was not attempted" — corrected wording, Rev3 Finding 7 — a
start-time recheck of the same collision the queue path already enforces,
since the filesystem can change between queueing and starting) — each
before the start-specific `ResolveAdapter.start_render()` call (not
"before any Resolve contact" — see Rev3 Finding 5 above).

It then calls `ResolveAdapter.start_render()` exactly once, passing the
job's persisted identity including `output_path`. If that call raises
`RenderStartReconciliationRequiredError`, it propagates unchanged and no
database write happens — the row stays `QUEUED`, which here means "unknown
state," not "confirmed safe to retry." Once the call returns normally
(Resolve has independently confirmed `Rendering` via its own getter-only
postcondition), persistence uses a **guarded** `QUEUED -> RENDERING`
transition (`Database.transition_render_job_to_rendering()`: `UPDATE ...
WHERE status = 'QUEUED'`, checking the affected row count) rather than an
unconditional write. If that guarded transition itself raises, affects
zero or more than one row, or the row cannot be reloaded afterward,
`RenderManager` raises the distinct
`RenderStartPersistenceReconciliationRequiredError` (Rev2, Finding 7) —
Resolve may already be rendering the job while Redline's own database
record is stale — and never compensates by calling `StopRendering()`,
deleting the Resolve job, or calling `start_render()` again.

**CLI.** `redline render start <job_id>` is a thin wrapper — argument
parsing → `RenderManager.start_render()` → output formatting — reporting
the Redline job ID, Resolve job ID, status, and output path. Because the
adapter's own postcondition already confirms `Rendering` before
`RenderManager` returns, the CLI's "Render start confirmed" header and
printed `Status: rendering` are not a presumptive claim — both are already
independently established by the production path itself before the CLI
ever prints them. Two dedicated failure categories,
`render start reconciliation required` and `render start persistence
reconciliation required`, are mapped ahead of the generic `render start
failed` category so operators can distinguish an ordinary, safely-fixable
precondition failure from a state that requires manual reconciliation
before this job is touched again.

**Deliberately not built here: a live RLC-E9901 one-shot start harness.**
This construction adds only the reusable production capability. Neither
`RLC-E9901` nor its specific Resolve job ID appear in
`ResolveAdapter`/`RenderManager`/the CLI — those identifiers belong only in
a future, separately authorized one-shot harness/evidence contract, the
same separation already established between the reusable
`rlc_e9901_queue_attempt_harness.py`-style pattern and the underlying
production `render queue` path it wraps rather than reimplements. See
`docs/RENDER_START_PATH_CONSTRUCTION.md` for the full harness-justification
analysis; no such harness is implemented as part of this construction.

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

## 5.1 Application Composition Root and Multiple Transports

Redline OS has more than one way to be driven: the MCP server (for an LLM
client) and, as of the CLI slice, `redline` (for a human operator at a
terminal). Both are thin transports over the same `redline_core` business
logic — neither should own how Config, the SQLite `Database`, the Resolve
connection, and the six managers get constructed and wired together, since
that construction has to be identical (and singular — one Resolve
connection, not one per transport) regardless of which transport is
running.

That shared construction lives in `redline_core.runtime.composition`:
`ApplicationServices` (the dataclass holding config/db/resolve/every
manager) and `build_application_services()` (the function that builds one).
It is transport-neutral by design — it does not parse arguments, register
MCP tools, print output, or translate exceptions into transport-specific
responses. Those responsibilities stay with each transport's own entrypoint
(`mcp_server/server.py`, `cli/main.py`), including calling
`redline_core.logging.setup.configure_logging()` at startup — construction
and logging setup are both transport-invoked, not transport-owned.

`mcp_server/context.py` is now a thin, backward-compatible alias over this
(`AppContext = ApplicationServices`, `build_context()` delegates to
`build_application_services()`) so existing MCP-transport code and tests
didn't need to change.

Phase 13 adds a dedicated build orchestration boundary in
`redline_core.build.BuildOrchestrator`. It is transport-neutral and sits
between the CLI, future API transports, and the existing domain layers:

```text
CLI/API transport -> BuildOrchestrator -> manifest layer + EpisodeManager
```

`BuildOrchestrator` owns only the approved build-stage sequencing for
`redline build Episode_0001`: parse the target, resolve the manifest path,
load and validate the manifest, confirm target/manifest identity, resolve
episode existence through `EpisodeManager`, create the episode when absent,
and assemble through `EpisodeManager.build_episode(...)`. It does not parse
CLI arguments, print output, queue renders, archive episodes, mutate SQLite
directly, call raw Resolve APIs, duplicate manifest validation, or reproduce
manager-owned retry/status policy. The only orchestration-specific invariant
it enforces is that the validated manifest `episode.id` must match the
episode ID derived from the parsed build target before any episode mutation
can occur.

Phase 14 Mission 38A adds a read-only preflight boundary in
`redline_core.build.BuildPreflight` for the CLI's live-build path:

```text
CLI argument parsing -> CoreServices/config -> BuildPreflight
    -> ApplicationServices -> BuildOrchestrator.build_prepared(...)
```

This prevents invalid pre-execution requests from initializing mutable
application resources. Missing manifests, malformed YAML, manifest schema
failures, manifest media-path validation failures, and target/manifest identity
mismatches are resolved with loaded configuration only; they do not initialize
SQLite, connect Resolve, create persistent logging artifacts, create episodes,
or mutate Resolve. The prepared request carries the parsed target, selected
manifest path, loaded manifest, and validated plan into
`BuildOrchestrator.build_prepared(...)`, so the manifest layer remains the
single owner and the manifest is not loaded or validated twice.

Mission 36 adds a separate transport-neutral build-to-render composition
boundary in `redline_core.workflows.BuildRenderWorkflow`:

```text
combined transport -> BuildRenderWorkflow -> BuildOrchestrator -> RenderManager
```

`BuildRenderWorkflow` owns only sequencing. It calls
`BuildOrchestrator.build(...)` once with explicit inputs, and only after that
call returns successfully does it queue a render through
`RenderManager.queue_render(...)` once, using `BuildResult.target.episode_id`
and the caller-supplied render preset name. It does not parse targets, resolve
manifests, validate manifests, inspect build final state, decide render
eligibility, poll render status, retry either operation, cancel on failure,
archive, roll back, repair, mutate SQLite directly, or call raw Resolve APIs.
If build succeeds and render queueing fails, the successful build is preserved
and the render exception propagates; this is composition, not a distributed
transaction.

Standalone transports remain independent: `redline build` stays
assembly-only, `redline render` stays render-only, and any combined transport
must call the workflow rather than duplicating build or render policy.

The CLI now has resource groups for `build`, `episode`, `render`, `asset`, and
`archive`.
`episode list` becoming the fourth `episode` action was one of the two
agreed trigger points for splitting the CLI into per-resource modules
(mirroring `mcp_server/tools/`) — that split happened in Mission 4:
`cli/main.py` is a thin entry point only (parser assembly, logging setup,
per-resource dispatch, exit-code translation), and each resource group
gets its own sibling module (`episode_commands.py`, `asset_commands.py`,
`archive_commands.py`) holding that group's handler/printer pairs,
serialization, subparser registration, and dispatch. No generic command
registry, base command classes, shared result dataclasses, or DI
container exists across them — deliberately; each module is
self-contained.

Every `redline_core` capability not yet exposed via CLI was inventoried
before choosing `episode status` (Mission 3) and `asset list` (Mission 5).
Render (`queue_render`, `get_render_status`, `cancel_render`) was explicitly
excluded from that near-term CLI work at the time because the real-Resolve
adapter methods behind it were still stubbed. Phase 10 later implemented those
adapter methods one at a time; it did not add render CLI commands.

Mission 6 (`asset verify`) is a second example of the same "verify against
the actual contract before implementing" discipline. It was originally
planned as `asset verify <episode_number>`, the CLI's first cross-domain
command. Architecture review found `AssetManager.verify_assets_for_episode()`
has no episode parameter and no episode-aware call site anywhere in the
repo — it only accepts an optional asset-ID override, defaulting to a
single global `required_for_episode` list, not a per-episode one. The
command was corrected to `asset verify [asset_id ...]`, no episode
argument, still on `CoreServices` — not the cross-domain command it was
assumed to be.

**Capability-specific construction: no longer deliberately out of scope.**
Missions 1-4 built every command against the same full
`ApplicationServices` runtime, on the stated principle that a partial-
construction flag would be speculative abstraction with no real caller.
Mission 5's `asset list` is the first command to actually demonstrate that
need: `AssetManager.list_available_assets()` touches nothing but config,
so building the full runtime (SQLite connection, a live Resolve connect
attempt) for it isn't just wasted work — it would make the command fail on
a machine without Resolve running, despite the command having no Resolve
dependency at all. Rather than add a `require_resolve=False` flag to
`build_application_services()` (which would keep growing per future
dependency combination), a second, narrower composition function was
added for exactly this boundary: `CoreServices`/`build_core_services()` —
configuration-backed services requiring neither SQLite nor Resolve, not a
general "core" layer every future command defaults into. A manager only
belongs on `CoreServices` if it needs nothing but config, the same way
`AssetManager` does; no `db` or `resolve` attribute exists on `CoreServices` at
all. `build_application_services()` itself is completely unchanged, still
the full runtime for the MCP server and every `episode` command.
`main.py` now selects the right builder per resource group before
dispatch. This is not a general dependency-injection redesign — a further,
narrower builder (e.g. DB-only, no-Resolve) should wait for a command that
actually demonstrates that specific boundary, same discipline as
everything else in this file.

**Mission 7 demonstrated exactly that specific boundary.** `redline
archive list` (`ArchiveManager.list_archives()`) needs a connected
SQLite `Database` — unlike `asset list` — but never Resolve. Neither
existing builder fit: `CoreServices` has no `db` attribute at all, and
`ApplicationServices` would force a live Resolve connection attempt for a
command that doesn't touch Resolve. A third composition function,
`PersistenceServices`/`build_persistence_services()`, was added for
exactly this boundary — configuration-backed services requiring SQLite
persistence, but not Resolve. Like `CoreServices`, it is not a universal
middle layer future commands default into; a manager only belongs on
`PersistenceServices` if it needs config and a DB connection but never
touches Resolve, the same way `ArchiveManager` does; no `resolve`
attribute exists on `PersistenceServices` at all.
`build_application_services()` and `build_core_services()` are both
completely unchanged. The three public builders now share small private
construction helpers (`_resolve_config_dir`, `_resolve_db_path`,
`_connect_database`) purely to avoid duplicating the same few lines a
third time — this is sharing of construction plumbing, not a shared
dependency-tier framework, and none of the three builders' own public
behavior changed as a result.

Architecture review for Mission 7 also caught an argument-type
inconsistency before implementation, the same "verify against the actual
contract" discipline as Mission 6: `ArchiveManager.archive_episode()`
takes `episode_id: str` (e.g. `"RLC-E025"`), not `episode_number: int`
like every other `episode`-adjacent CLI action. Mission 7 itself doesn't
implement `archive episode` (deferred to a following mission), but the
finding is recorded here so that command is built as
`redline archive episode <episode_id>` against the real contract, not
`<episode_number>` against an assumed one.

**Mission 8 implemented that deferred command exactly as recorded:**
`redline archive episode <episode_id>` (no `episode_number` translation
layer, since none exists) over the existing, already-tested
`ArchiveManager.archive_episode()`, still on `PersistenceServices` — no
new composition tier needed, confirmed during architecture review.

**`ArchiveManager.archive_episode()`'s actual implementation (recorded
here, not in README, deliberately — see below):** mutation order is (1)
look up the episode by `episode_id`, (2) check for an existing archive
record, (3) check `folder_path` is set, (4) check the working folder
exists on disk, (5) `mkdir(parents=True, exist_ok=True)` the archive
root, (6) check the specific destination path doesn't already exist, (7)
`shutil.move()` the working folder, (8) `create_archive_record()`, (9)
`update_episode_status(ARCHIVED)`, (10) `update_episode_paths()` — steps
8-10 are three separate `INSERT`/`UPDATE` statements with three separate
commits, not one transaction, and step 7 (the filesystem move) happens
before any of them. There is currently no rollback: if a failure occurs
between steps 7 and 10, the working folder has already moved but the
database may not yet (or may only partially) reflect that. This is a
`ArchiveManager`-level characteristic — deliberate simplicity per the
manager's own docstring, not a CLI defect — and it is recorded here
rather than in `README.md`'s user-facing usage section on purpose: it
describes how the manager is implemented today, not the CLI's contract.
If `ArchiveManager` later adds a transaction or a rollback path, this
section is what changes; `redline archive episode`'s CLI behavior and its
README documentation are both unaffected, since the CLI has never
described or depended on the manager's internal steps — it only reports
the returned `ArchiveRecord`.

The one previously-uncovered `ArchiveManager` branch found during
Mission 8's review — a pre-existing folder already sitting at the
archive destination path — is now covered directly in
`tests/unit/test_archive_manager.py` (proving the manager itself raises
`ArchiveError` and leaves the source folder untouched), independently of
`tests/unit/test_cli_archive_episode.py` (which proves only that the CLI
passes that manager error through unchanged).

**Phase 15 Mission 15B added the Archive Manager Rev1 database
foundation, without changing any of the above.** Everything in this
section — `shutil.move()`, no render-status gate, `folder_path`
rewritten to the archive location, three separate unguarded commits — is
still exactly what `ArchiveManager.archive_episode()` does today; Mission
15B did not touch `redline_core/archive/manager.py` at all. What it added
is purely a new SQLite/model layer for a future, non-destructive Archive
Manager Rev1 (approved architecture: copy-only, preservation-first,
fail-closed, hash-verified, staged, atomically published,
Resolve-independent, restore-ready — see the Mission 15A architecture
reconciliation record) to consume later:

- `archives` evolved additively (same `_migrate_add_*_columns()` idiom as
  the episodes/render_jobs migrations above) with `archive_id`,
  `archive_schema_version`, `archive_state`, `manifest_path`,
  `manifest_sha256`, `render_job_id`, `verified_at`. Every pre-existing
  row is backfilled to `archive_schema_version=0`/`archive_state='legacy'`
  by the migration's own column defaults — never reclassified as a
  verified Rev1 archive.
- New `Database.commit_verified_archive()`: one SQLite transaction,
  guarded by an `INSERT ... SELECT ... WHERE` that re-tests episode/
  render-job/no-existing-archive eligibility against live database state
  (not an earlier read) plus a guarded `rendered -> archived` `UPDATE`,
  the same TOCTOU-closing principle as
  `transition_render_job_to_rendering()`/`release_assembly_claim()`. This
  is the only method permitted to write `archive_schema_version=1`/
  `archive_state='complete'`. It never touches `folder_path`.
- `create_archive_record()` (used above) is retained unchanged, now
  documented as the legacy/internal writer only — Archive Manager Rev1
  must not be routed through it.
- `docs/CHANGELOG.md`'s Mission 15B entry has the full test/scope record.
  No CLI, MCP, filesystem-copy, hashing, manifest, or `ArchiveManager`
  orchestration work happened in this mission — those remain later Phase
  15 missions (15C onward).

**Phase 15 Mission 15C added the source-side filesystem integrity
engine, `src/redline_core/archive/integrity.py`, still without changing
any of the destructive behavior described above.** `ArchiveManager`
itself, the CLI, MCP, and `Database.commit_verified_archive()` remain
completely untouched and unconsumed by this new module — it is a
read-only, transport-neutral set of primitives waiting for a future
Archive Manager Rev1 (Mission 15D+) to orchestrate them into an actual
copy-and-publish pipeline. No filesystem mutation of any kind occurs
anywhere in this module.

- **Safety boundary:** every filesystem object — the source root and
  every discovered entry — is classified via `os.lstat()` before being
  trusted. A symlink, a Windows junction, or any other reparse point is
  rejected outright regardless of destination (inside root, outside root,
  or as the root itself); junction detection uses
  `os.stat_result.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT`
  (stdlib-only, Python 3.5+, no elevated privileges) rather than
  `Path.is_junction()`, since that's 3.12+ only and this repo supports
  3.10+. Verified empirically against a real `New-Item -ItemType
  Junction` in this repository's own environment: `Path.is_symlink()`
  alone reports `False` for a genuine junction, confirming the stricter
  check is necessary, not defensive-programming caution.
- **Streaming SHA-256 with stability proof, strengthened to the opened
  file handle (narrow same-session correction):** `hash_stable_file()`
  reads in fixed 1 MiB chunks (never whole-file) and validates four
  checkpoints against the same stat-identity fingerprint (size,
  `mtime_ns`, inode/device where reported): a pre-open pathname `lstat()`
  (also the safety check), `os.fstat()` on the just-opened descriptor
  (required to match the pre-open observation — this narrows the gap
  where `open()` would silently follow a symlink that appeared at the
  path after the pathname check, since `open()` itself cannot refuse
  that), `os.fstat()` on the same descriptor again after streaming
  (required to match the just-opened observation), and a final pathname
  `lstat()` after closing (required to match the original pre-open
  observation). Any mismatch, or the file disappearing, raises
  `ArchiveUnsafeFilesystemObjectError` or `ArchiveSourceChangedError` and
  yields no hash. Still self-contained (performs its own full safety
  check on every call) and stdlib-only — this is a stronger observation
  contract, not filesystem locking or snapshot semantics; see the
  module's own docstring for the precise remaining limits.
- **Deterministic inventory:** every entry's identity is
  `(source root, normalized relative path)`, not an absolute path alone.
  Ordering is an explicit case-folded sort, not filesystem enumeration
  order. Relative-path identities are case-insensitively
  collision-checked unconditionally (not only on Windows), since a Rev1
  package targets a Windows production filesystem regardless of the OS
  that builds it. Directories are first-class inventory entries so an
  empty directory required by the production folder layout survives for a
  future restore.
- **Race/TOCTOU guarantee, stated precisely (see the module's own
  docstring for the full statement):** each returned file's hash was
  computed from content whose stat identity was unchanged immediately
  around the read, and a final structural re-enumeration pass fails
  closed if the file/directory set changed since the initial walk. This
  is not a filesystem lock and cannot catch every conceivable
  precisely-timed same-size/same-mtime substitution — Mission 15C does
  not attempt locking, per its governing instructions, and fails closed
  on everything it is able to observe.
- **Source-set digest:** a canonical JSON representation
  (`schema_version` + sorted directory paths + sorted
  `{path, size_bytes, sha256}` file objects), UTF-8-encoded with sorted
  keys and compact separators, then SHA-256'd — not a concatenation of
  raw file bytes, and not stored in SQLite (same pipeline-state/media-
  content boundary Mission 15B already established). This is an internal
  integrity primitive, not the future Archive Manifest Rev1 document.
- `docs/CHANGELOG.md`'s Mission 15C entry has the full test/scope record,
  including the reuse review against `asset/path_policy.py` (used only as
  a pattern reference — its single-declared-path, broken-symlink-only
  semantics don't match Rev1's reject-all-symlinks, recursive-tree
  requirement) and the honest platform-limitation note on symlink tests
  (skipped only where this session's environment concretely lacks the
  privilege to create one; real Windows junction rejection was exercised
  for real, not skipped).

**Phase 15 Mission 15D added the package-construction layer,
`src/redline_core/archive/package.py`, that turns a verified Mission 15C
`SourceInventory` into a sealed, hash-verified, atomically-published
package directory — the first Phase 15 mission authorized to perform
filesystem copies. Still narrowly scoped: `ArchiveManager`, the CLI, MCP,
and `Database.commit_verified_archive()` remain completely untouched and
unconsumed; every test builds and copies synthetic `tmp_path` fixtures
only, never RLC-E9901, the live `redline.db`, or Resolve.**

- **Two-phase API, deliberately not a single call.** `build_staged_package()`
  copies, verifies, and seals a complete package at a staging location
  under `<archive-root>/.staging/<archive-id>.<attempt-id>.partial/`
  without publishing it; `publish_package()` independently re-verifies that
  sealed package and then atomically renames it to
  `<archive-root>/episodes/<episode-id>/<archive-id>/`.
  `build_archive_package()` is a thin convenience wrapper calling both in
  sequence. Exposing the intermediate `StagedPackage` is what let this
  mission's own tests deliberately tamper with a sealed package between
  sealing and publication (manifest tampering, destination corruption, a
  missing/unexpected artifact, an atomic-publication collision race) —
  scenarios a single opaque call could not exercise deterministically.
- **Destination collision fails closed twice.** The final destination is
  checked before any copying begins (before any I/O against the source
  happens at all) and rechecked immediately before the rename in
  `publish_package()`, closing the race window between the two calls.
  Publication uses `os.rename()`, not `os.replace()` — on this
  repository's target Windows filesystem `os.rename()` raises rather than
  silently replacing an existing destination directory, which is the
  never-overwrite guarantee this mission requires; the explicit recheck
  does not rely on that behavior alone.
- **Every copied file is verified three ways, all reusing Mission 15C's
  own primitives — no second hashing routine.** After a chunked
  `shutil.copyfileobj()` copy (never a whole-file read), the source is
  re-hashed with `integrity.hash_stable_file()` and required to still
  match the inventory's recorded hash/size (source changed since the
  inventory was built → `ArchiveSourceChangedError`); the destination is
  then hashed with the same primitive and required to match too (mismatch
  → `ArchiveCopyVerificationError`). Reusing `hash_stable_file()` for the
  destination also gets destination object-safety for free — an
  unexpected symlink/junction or a file that disappears mid-check fails
  closed with the same `ArchiveUnsafeFilesystemObjectError`/
  `ArchiveSourceChangedError` Mission 15C already defines.
- **Completeness is independently verified twice, not assumed from
  per-copy success.** After every file is copied, `payload/` (the
  recreated source topology, kept in its own subdirectory precisely so it
  never collides with the manifest/marker files written alongside it) is
  re-enumerated with a full `integrity.build_source_inventory()` walk —
  not a weaker duplicate traversal — and compared against the original
  inventory for missing files, unexpected files, missing directories,
  unexpected directories, hash mismatches, and size mismatches. The exact
  same check runs again, unconditionally, as the first step of
  `publish_package()`'s pre-publication re-verification.
- **Archive Manifest Rev1**, sealed only after every check above passes:
  canonical JSON (`sort_keys=True`, compact separators, UTF-8) containing
  `schema_version`, `archive_id`, `episode_id`, `created_at_utc`
  (clock-injected — `Clock = Callable[[], datetime]` — for deterministic
  tests, not monkeypatched global state), `source.source_root`/
  `source.source_set_digest`, an `artifacts` list
  (`source_relative_path`/`archive_relative_path`/`size_bytes`/`sha256`
  per file), a `directories` list of archive-relative paths, a `summary`,
  and a `verification` block. Artifact/directory order is preserved
  exactly from the already-deterministically-sorted `SourceInventory` —
  nothing here re-sorts or depends on dict/set iteration order. Database
  episode/render-job snapshots, production evidence, and software/
  repository identity are deliberately not populated — Mission 15D does
  not possess them; that is Mission 15G/orchestration scope.
- **Sealing order**: `archive_manifest.json` written, then its SHA-256 is
  computed by reading the just-written file back with
  `hash_stable_file()` (not re-hashing the in-memory bytes) into
  `archive_manifest.sha256`, and only then is the empty `PACKAGE_COMPLETE`
  marker written. A failure at any point before that ordering completes —
  proven directly by a dedicated test that corrupts a copy mid-loop and
  asserts the leftover staging directory contains neither the manifest nor
  the marker — never produces a sealed package.
- **New exceptions** in `src/redline_core/archive/exceptions.py`:
  `ArchivePackageError` (base), `ArchiveDestinationCollisionError`,
  `ArchiveCopyVerificationError`, `ArchivePackageVerificationError`,
  `ArchivePublicationError`. Mission 15C's `ArchiveSourceChangedError`,
  `ArchiveUnsafeFilesystemObjectError`, and `ArchivePathError` are reused
  as-is wherever they already describe the failure accurately, per this
  mission's explicit instruction not to multiply exception types.
- **Narrow source-integrity correction (same Mission 15D, pre-publication):** two gaps in the source guarantee above were closed before publication approval. First, the copy read itself now goes through the same four-checkpoint safe-open contract as hashing — `integrity.open_stable_source()` (extracted from `hash_stable_file()`, which now consumes it too) yields an already-identity-proven file handle, so the descriptor a copy actually streams bytes from is proven to correspond to the pre-open pathname identity and stays stable while streaming, closing a gap where the copy's own `open()` had no way to refuse a pathname swapped after the original inventory. This is in addition to, not a replacement for, the pre-existing separate post-copy source re-hash and destination hash. Second, per-file re-hashing alone cannot detect a file or directory *added* to the source tree since the inventory was built (there is nothing in the original inventory to re-verify an added entry against) — a final whole-tree reconciliation, `package._reconcile_complete_source_set()`, now runs once after payload completeness verifies and strictly before any manifest/sidecar/`PACKAGE_COMPLETE` is written: it rebuilds a fresh `SourceInventory` from the original inventory's own root and requires its `source_set_digest` to still equal the digest of the inventory the package was built from (the existing deterministic digest, not a second tree-comparison format), transitively catching addition, removal, rename, and empty-directory add/remove alike. A digest mismatch fails closed; the fresh inventory is discarded, never adopted.
- `docs/CHANGELOG.md`'s Mission 15D entry has the full test/scope record.

**Mission 9 begins the Resolve-driven CLI layer: `redline episode
organize-bins <episode_number> [--bin-name footage]`**, a thin wrapper
over the existing, already-tested `MediaManager.organize_bins()`. It
stays under the `episode` resource, on `ApplicationServices` — the same
tier every other `episode` action already uses — rather than introducing
a `media` top-level CLI resource; `organize_bins()` needs exactly what
`ApplicationServices` already provides (DB via `EpisodeManager` to
resolve `episode_number` into `episode_id`/`project_name`, Resolve via
`MediaManager` to perform the import), so no composition change was
needed, the same "verify the actual dependency before introducing a
tier" discipline as every prior mission. `MediaManager.import_media()` —
the lower-level primitive `organize_bins()` itself calls, also used
internally by `EpisodeManager.build_episode()`'s manifest flow — remains
un-exposed as its own CLI or MCP surface; architecture review found no
existing MCP tool, no manager-level unit test, and no natural
episode-scoped argument shape for it, so it stays an internal primitive
until a real need for direct exposure is demonstrated.

**Implementation characteristics recorded here, not in `README.md`:**
`organize_bins()` performs no database write of any kind — despite
`EpisodeStatus.MEDIA_ORGANIZED` existing as an enum value, calling this
command has zero effect on what `episode status` subsequently reports.
Neither the manager nor the Resolve adapter perform duplicate-media
detection: running `organize-bins` twice against unchanged ingest files
imports the same files again, producing new Resolve clip IDs each time,
with no dedup guard at any layer. Both are `MediaManager`/`ResolveAdapter`-
level characteristics, not CLI defects, and the CLI does not attempt to
compensate for either — the same "manager is sole authority, no CLI-side
invention" principle as Missions 6-8.

**Failure-handling divergence from precedent, noted for future
missions:** unlike `episode`/`asset`/`archive`'s MCP tools, which each
catch their own operation's exception set (mirrored by their CLI
siblings), `mcp_server/tools/media_tools.py`'s `organize_bins` tool has
**no exception handling at all** — a `ProjectNotFoundError`,
`MediaImportError`, or `ResolveConnectionError` propagates raw through
that MCP tool today. Mission 9 did not modify `media_tools.py`; the CLI's
own exception tuple (`EpisodeNotFoundError`, `ProjectNotFoundError`,
`MediaImportError`) was derived directly from what
`MediaManager`/`ResolveAdapter` can actually raise, not copied from the
MCP transport, since there was nothing defensive there to copy.

**Mission 10 continues the Resolve-driven CLI layer: `redline episode
build-timeline <episode_number>`**, a thin wrapper over the existing,
already-tested `TimelineBuilder.build_timeline_for_episode()`. Also
stays under `episode`, on `ApplicationServices` — no composition change,
same reasoning as Mission 9: `TimelineBuilder` needs only config +
Resolve, and the CLI's `episode_number` resolution needs `EpisodeManager`
(DB + Resolve), both already provided. `TimelineBuilder.apply_markers()`
and `.place_clips()` — the other two public methods, also used internally
by `EpisodeManager.build_episode()`'s manifest flow — remain un-exposed:
architecture review found `apply_markers()` takes a raw `timeline_name`
string rather than an episode identifier (the CLI would either have to
duplicate the naming-pattern formatting that today lives only inside
`build_timeline_for_episode`, or accept a raw timeline name, breaking the
established "episode_number in, everything else derived" CLI
convention), and `place_clips()` has no MCP exposure, no natural
CLI-typeable input, and depends on clip IDs this mission has no way to
obtain independently — the same shape that disqualified
`MediaManager.import_media()` in Mission 9. `TimelineBuilder` owns
timeline naming entirely; no transport re-derives
`config.timeline.timeline_name_pattern` itself.

**Timeline naming ownership.** `config.timeline.timeline_name_pattern`
formatting happens in exactly one place: `TimelineBuilder.timeline_name_for_episode()`
(added in Mission 11A — see below). No transport (CLI or MCP) reproduces
this formatting independently — every timeline-name value a transport
reports comes from a manager's own returned object (`TimelineBuildResult`
via `build-timeline`), never from re-formatting the pattern itself.

**Implementation characteristics recorded here, not in `README.md`:**
`resolve.build_timeline()` reuses an existing Resolve timeline by name
rather than creating a duplicate — verified at the adapter layer
(`test_resolve_script_adapter_timeline.py`) and reproduced by
`MockResolveAdapter`. However, `build_timeline_for_episode()` always
calls `apply_markers()` afterward regardless of whether the timeline was
newly created or reused, and neither `apply_markers()` nor
`resolve.add_markers()` performs any deduplication. **Calling
`build-timeline` twice against the same episode therefore reuses the
same timeline object but duplicates its markers** — each call reports
`markers_applied == N` (the configured count), not a running total, but
the timeline itself ends up with `2N` marker entries after two calls.
This is documented, tested `TimelineBuilder`/`ResolveAdapter` behavior
(see `tests/unit/test_timeline_builder.py`'s repeated-build test), not a
CLI defect — the CLI does not add deduplication, retries, or rollback to
compensate for it. Nothing about a built timeline (name or ID) is
persisted in SQLite; `episode status` cannot report whether or what
timeline exists — the only way to observe it again is via Resolve
itself, or by calling `build-timeline` again (reproducing the
marker-duplication above). `mcp_server/tools/timeline_tools.py`'s
`build_timeline`/`add_markers` tools have the same "no exception
handling at all" characteristic already noted for `media_tools.py` — not
modified in this mission.

**Mission 11A: pure timeline-naming helper, an internal refactor with no
CLI-visible change.** Reviewing `place_clips()` as a Mission 11 CLI
candidate surfaced a real blocker: both remaining `TimelineBuilder`
public methods (`apply_markers`, `place_clips`) require a `timeline_name`
that is never persisted anywhere and, before this mission, had no
standalone way to obtain — re-deriving `config.timeline.timeline_name_pattern`
in a transport would have violated the ownership principle above, and
calling `build_timeline_for_episode()` again purely to read the name back
would silently re-trigger the marker-duplication behavior documented
above. `TimelineBuilder.timeline_name_for_episode(episode_id: str) -> str`
resolves this: a pure method (no Resolve, no SQLite, no logging, no
mutation) that both `build_timeline_for_episode()` and
`EpisodeManager.build_episode()`'s own pre-computation now call, instead
of each independently reformatting the pattern — the latter having done
so, independently of `TimelineBuilder`, since before this mission
existed. No observable behavior changed anywhere: every existing
`test_timeline_builder.py` and `test_episode_manager.py` assertion passes
unmodified. This mission touched no CLI, MCP, Resolve, composition, or
database code; a future `place-clips` command can now call
`services.timeline_builder.timeline_name_for_episode(episode_id)`
directly to obtain a real timeline name with no side effects, but
`place-clips` itself remains unimplemented and deferred.

**Mission 11B: `redline episode place-clips <episode_number> [clip_id ...]`**,
the last `TimelineBuilder` public method to gain CLI exposure. Also stays
under `episode`, on `ApplicationServices` — no composition change.
`timeline_name` is resolved via `timeline_name_for_episode()` exactly as
Mission 11A intended, never by re-calling `build_timeline_for_episode()`.
`TimelineBuilder.apply_markers()` remains the one `TimelineBuilder`
public method still without CLI exposure: it takes a raw `timeline_name`
rather than an episode identifier, and unlike `place_clips` there is no
operator-meaningful reason to call it standalone outside of building a
timeline (re-applying the same configured markers a second time only
duplicates them) — see Mission 11's architecture review for the full
comparison.

**Implementation characteristic recorded here, not in `README.md`:**
`place_clips()` is append-only at every layer (`TimelineBuilder`, the
Resolve adapter, and `MockResolveAdapter` alike) — there is no
deduplication or "already placed" check anywhere. Calling
`place-clips` twice with the same clip IDs places the same clips onto
the timeline a second time, exactly like `organize-bins`'s duplicate
import behavior and `build-timeline`'s duplicate marker behavior. The
CLI does not add deduplication, retries, or rollback to compensate.

**Mission 12 (Phase 9): `redline episode validate-manifest <manifest_path>`**,
a thin, read-only wrapper over the existing, already-tested
`redline_core.manifest.load_manifest()` and `.validate_manifest()`. This is
the first `episode` action that needs only `CoreServices` — confirmed
directly against `validate_manifest()`'s real signature, which takes only
a `RedlineConfig`, never a `Database` or a `ResolveAdapter` — rather than
the `ApplicationServices` every other `episode` action uses. This is a
second demonstrated use of the existing config-only tier (`asset
list`/`asset verify` was the first), not a new one.

Two deliberate deviations from established `episode`-action convention,
both contract-driven rather than incidental:

1. **Argument shape.** Every other `episode` action takes `episode_number`
   as its primary CLI argument. `validate-manifest` instead takes a
   `manifest_path`, because the episode identity here comes from inside
   the manifest file (`episode.id`, a string like `"RLC-E025"`) rather
   than from a number the operator types — the same kind of contract-driven
   deviation `archive episode <episode_id>` already established for a
   different reason.
2. **Dispatch shape.** `cli/main.py`'s per-resource composition selection
   has, until now, been decided once per resource group. This mission
   needed to branch on `args.action` within the `episode` resource
   specifically, since `validate-manifest` alone needs `CoreServices`
   while the other seven `episode` actions need `ApplicationServices`.
   Rather than adding an eighth branch to `episode_commands.run()` (which
   is, and remains, typed `ApplicationServices` — accurate for every
   action it actually handles), a separate `run_validate_manifest(args,
   services: CoreServices)` function was added, and `main.py` picks
   between the two based on `args.action` before either builder is
   constructed. This keeps both functions' type signatures honest rather
   than introducing a `Union[ApplicationServices, CoreServices]` parameter
   that would be correct for only one of eight branches.

   A related design question was explicitly considered and deliberately
   deferred, not overlooked: should the CLI introduce a general
   per-action, composition-tier-aware dispatch mechanism now, anticipating
   a future family of `CoreServices`-backed `episode` commands? Checked
   against the actual roadmap rather than speculated: Phase 10 (Render
   Automation) and the only other currently-scoped Phase 9 candidate
   (Mission 13, `episode assemble`) both need `ApplicationServices` for
   `EpisodeManager`/`TimelineBuilder`/Resolve; Phase 11 (MCP Expansion) is
   scoped as closing the MCP surface's gap against *already-existing* CLI
   capability, not adding new CLI actions. The one plausible future
   `CoreServices`-tier sibling — a manifest "preview" or "dry-run" command
   — is already exactly what `validate-manifest` does. No second
   `CoreServices`-tier `episode` action is currently evidenced anywhere in
   the roadmap, so a general dispatch-tier abstraction was deliberately
   not built now; a single targeted branch was judged sufficient for a
   demonstrated one-off, the same "add a tier/mechanism only when a real
   command demonstrates the need" discipline `CoreServices` and
   `PersistenceServices` were each held to. If a second `CoreServices`-tier
   `episode` action is ever genuinely proposed, revisit this decision then,
   with that command's real shape in hand, rather than now with only one
   data point.

`load_manifest()` and `validate_manifest()` are both called with the
identical, unmodified `manifest_path` string the operator passed — the CLI
performs no path normalization, existence check, or `Path` conversion of
its own, since `validate_manifest()` already resolves the manifest's own
parent directory from that exact value to validate relative media paths.
No `redline_core` code changed in this mission: `EpisodeManager`,
`TimelineBuilder`, `MediaManager`, `AssetManager`, `ArchiveManager`, the
Resolve adapter, and the manifest loader/validator/models are all
unmodified.

**Mission 13 (Phase 9): `redline episode assemble <manifest_path>
[--force]`**, the mutating counterpart to Mission 12's `validate-manifest`
and the first CLI action to reach `EpisodeManager.build_episode()`. Unlike
Mission 12, this one required real `redline_core` changes, not just a new
CLI wrapper — because the existing retry guard (an in-memory
`_unsafe_rerun_episode_ids` set on `EpisodeManager`) could never protect
anything through the CLI transport: a fresh `EpisodeManager` is
constructed on every CLI invocation, so the guard was always empty at the
start of any process. Preceded by `docs/adr/ADR-0001-episode-assembly-retry-policy.md`,
the project's first ADR, which resolved this and defined the full retry
policy before implementation began. See §3.4 above for the resulting
design (the atomic assembly claim, the exhaustive status matrix, and the
token-owned release). Summarized here at the CLI/composition level:

1. **Same `ApplicationServices` composition path as every other mutating
   `episode` action** — no composition change, unlike Mission 12.
   `assemble` needs `EpisodeManager`/`TimelineBuilder`/`MediaManager`/
   Resolve, exactly like `organize-bins`/`build-timeline`/`place-clips`,
   so `cli/main.py` needed no new dispatch branch (unlike Mission 12's
   `validate-manifest`, which needed `CoreServices`). This resolves, with
   a real second data point, the open question Mission 12's architecture
   review deferred: `assemble` confirms there is no current family of
   `CoreServices`-tier `episode` actions beyond `validate-manifest`.
2. **`--force` is a pure transport-vocabulary translation, not a policy
   decision.** `_run_episode_assemble()` passes `force` straight through
   as `allow_unsafe_retry` to `build_episode()` — it never inspects
   episode status, never decides eligibility, and never re-implements any
   part of the matrix in §3.4. This was a deliberate, explicit engineering
   discipline for this mission: resist letting the CLI, `Database`, and
   `EpisodeManager` each "help" enforce eligibility. `EpisodeManager`
   remains the sole authority; `Database` provides only atomic
   primitives (`claim_episode_for_assembly()`/`release_assembly_claim()`);
   the CLI stays a thin transport.
3. **The `--force` warning is unconditional on the flag, not on the
   outcome.** `_print_episode_assemble_result()` prints the warning
   whenever `force=True` was passed, before checking success — including
   on a failed attempt (e.g. `--force` against a terminal `assembled`
   status, which is still rejected). Determining whether force was
   *actually needed* would require the CLI to inspect eligibility itself,
   which point 2 above forbids.
4. **Manifest handling is byte-for-byte the same as Mission 12's** —
   `load_manifest()` -> `validate_manifest()` -> `.to_build_definition()`,
   with the resulting `EpisodeBuildDefinition` passed to
   `build_episode()` unchanged. No manifest-layer code changed in this
   mission.
5. **Two correctness issues were found and fixed in review before this
   mission was committed**, both in the persistence layer described in
   §3.4, neither visible from the CLI/composition summary above: the
   original forced-claim `UPDATE` guarded only by `status NOT IN
   (terminal...)`, with no dependency on the claim token at all, so two
   concurrent forced callers could both satisfy that guard and both
   acquire the same dangling claim — corrected to the compare-and-swap
   design in §3.4 (`_claim_episode_for_assembly_cas()`). And
   `release_assembly_claim()` originally logged and returned silently on a
   token mismatch instead of raising, which would have let
   `build_episode()`'s success path return an `EpisodeBuildResult` even
   though the episode was never actually marked `assembled` — corrected to
   raise `AssemblyClaimReleaseError`, which both `build_episode()` call
   sites already convert into `EpisodeBuildError` via their existing
   exception handling. Both fixes were verified with dedicated tests
   (`tests/unit/test_db.py`'s forced-claim CAS race tests, and
   `test_episode_manager.py`'s `test_build_episode_final_release_token_mismatch_prevents_success_result`)
   before this mission's changes were committed.

`Episode` (in `redline_core.db.models`) gained `assembly_claim_token` and
`assembly_claimed_at` fields (and `from_row()` reads them) so the claim
state added to `schema.sql` is actually readable back through the
existing model — the persistence and manager layers depend on the claim
existing on the DB row itself, via `Database.claim_episode_for_assembly()`
and `.get_episode_by_episode_id()`, not on the `Episode` dataclass
exposing it; the dataclass fields exist for operator/diagnostic
inspection (e.g. a future `episode status` enhancement), not because any
current logic path reads them.

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
