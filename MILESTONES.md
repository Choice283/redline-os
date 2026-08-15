# Redline OS Verified Milestones

Redline OS milestones are not considered complete merely because code exists.
For production-facing Resolve work, a completed verified milestone should normally
pass through architecture review, implementation, unit testing, senior review,
focused corrections, controlled live verification, documentation, and a Git
commit.

This document is an engineering history and verification record. It separates
implementation status from unit-test coverage, live Resolve verification,
documentation, and committed history. For the V1 release-candidate closure
determination built from this history, see
[`docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md`](docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md).

## Status Legend

- Planned: proposed future work, not yet implemented.
- In Progress: active work exists but is not complete.
- Implemented: production code exists.
- Unit Tested: automated tests cover the implementation without requiring live Resolve.
- Live Verified: manually verified against a running DaVinci Resolve Studio instance.
- Committed: captured in Git history.
- Deferred: intentionally left for a later milestone.

## Verified Milestones

### Milestone: Resolve Connection

Status: Live Verified and Committed

Commit evidence:

```text
6b0c5e7 2026-07-26 chore: establish Redline OS foundation
```

Capabilities:

- Provides the `ResolveAdapter` public interface and `ResolveScriptAdapter.connect()`.
- Connects Redline OS to a running local DaVinci Resolve Studio process through the Resolve scripting API.
- Raises typed Resolve connection errors instead of exposing raw scripting failures upstream.

Verification:

- `docs/CHANGELOG.md` records live verification of `ResolveScriptAdapter.connect()` against DaVinci Resolve Studio 21.0.3.
- Later live milestones also depended on successful real adapter connection.
- No separate commit solely for connection live verification was identified in Git history.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- Requires DaVinci Resolve Studio, not the free edition.
- Real Resolve scripting requires Python 3.11 in the verified local environment.

### Milestone: Project Duplication

Status: Live Verified and Committed

Commit evidence:

```text
6b0c5e7 2026-07-26 chore: establish Redline OS foundation
```

Capabilities:

- Implements `ResolveScriptAdapter.duplicate_project(project_name, template_name)`.
- Loads a template project and creates a new Resolve project using Resolve project export/import behavior.
- Preserves the public adapter contract used by `EpisodeManager.create_episode()`.

Verification:

- Repository documentation records real `duplicate_project()` verification against a live Resolve instance.
- Unit tests cover duplicate-project behavior through `MockResolveAdapter`.
- No separate commit solely for project duplication live verification was identified in Git history.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- Uses temporary Resolve project archive files during duplication.
- Does not represent render/export behavior.

### Milestone: Media Import

Status: Live Verified and Committed

Commit:

```text
ca4e7eb 2026-07-26 feat: add verified Resolve media import
```

Capabilities:

- Implements `ResolveScriptAdapter.import_media(project_name, media_paths, bin_name)`.
- Validates local files before Resolve mutation.
- Loads the target project, reuses or creates a top-level media bin, imports all requested paths, and returns Resolve media item IDs.

Verification:

- Unit tests cover validation, bin reuse/creation, import failure handling, partial import detection, and ID fallback.
- Live verification imported one PNG into a disposable Resolve project.
- `GetMediaId()` returned a real non-empty ID that matched the item found during live Media Pool inspection.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- No automatic rollback for partial Resolve imports.
- Media Pool current-folder changes may remain after a later failure.
- Nested bins, duplicate detection, recursive scanning, categorization, and MCP error normalization were deferred.

### Milestone: Timeline Creation

Status: Live Verified and Committed

Commit:

```text
b1b18ea 2026-07-27 feat: add verified Resolve timeline operations
```

Capabilities:

- Implements `ResolveScriptAdapter.build_timeline(project_name, timeline_name)`.
- Reuses an existing timeline by exact name.
- Creates an empty timeline when no exact-name timeline exists.
- Rejects falsey handles, empty returned names, and Resolve auto-renaming.

Verification:

- Unit tests cover timeline lookup, invalid timeline counts, missing media pool, create failures, exact-name reuse, and error causes.
- Live verification confirmed empty timeline creation, exact-name return, and existing timeline reuse without duplicate creation.
- Resolve created its normal default empty video and audio tracks.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- A newly created timeline may remain if post-create verification fails.
- Automatic timeline rollback is not implemented.

### Milestone: Marker Insertion

Status: Live Verified and Committed

Commit:

```text
b1b18ea 2026-07-27 feat: add verified Resolve timeline operations
```

Capabilities:

- Implements `ResolveScriptAdapter.add_markers(project_name, timeline_name, markers)`.
- Validates marker fields before project loading.
- Adds markers to an exact-name timeline using Resolve `Timeline.AddMarker(...)`.
- Supports `custom_data` and legacy `customData` compatibility with an unambiguous conflict rule.

Verification:

- Unit tests cover marker validation, missing timeline handling, AddMarker failures, exception preservation, and partial-failure observability.
- Live verification added two markers at frames 0 and 48.
- `Timeline.GetMarkers()` returned both markers and their `customData`.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- Successfully inserted markers may remain after a later marker fails.
- Automatic marker rollback is not implemented.

### Milestone: Sequential Clip Placement

Status: Live Verified and Committed

Commit:

```text
9a54aa8 2026-07-27 feat: add verified Resolve clip placement
```

Capabilities:

- Implements `ResolveScriptAdapter.place_clips(project_name, timeline_name, clip_ids)`.
- Resolves imported Media Pool items by `GetMediaId()` with `GetUniqueId()` fallback.
- Sets the exact-name timeline current and appends requested clips in order with `MediaPool.AppendToTimeline([...])`.
- Returns one TimelineItem ID per requested MediaPoolItem for the verified media types.

Verification:

- Unit tests cover input validation, recursive Media Pool traversal, duplicate/missing clip handling, ordered placement, falsey and partial Resolve results, ID extraction, and mock behavior.
- Live verification placed one deterministic WAV and one deterministic PNG in requested order.
- Sequential placement was contiguous.
- Audio-only media was placed on an audio track.
- Still-image media was placed on a video track.
- Returned TimelineItem order matched requested MediaPoolItem order.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- Video clips with embedded or linked audio remain unverified.
- `AppendToTimeline(...)` returned-item cardinality for linked video/audio remains unverified.
- Explicit track targeting, explicit record-frame placement, and rollback are deferred.

### Milestone: Episode Assembly Orchestration

Status: Live Verified and Committed

Commit:

```text
8084242 2026-07-27 feat: add verified episode assembly orchestration
```

Capabilities:

- Implements V1 `EpisodeManager.build_episode(...)` orchestration for an existing episode.
- Preserves the architecture boundary:

```text
EpisodeManager
    -> MediaManager
    -> TimelineBuilder
    -> ResolveAdapter
```

- Coordinates ordered media import, timeline creation/reuse, marker application, sequential clip placement, result validation, and SQLite status transition.
- Rejects assembled reruns and unsafe failed reruns before repeating Resolve mutation in the same process.

Verified environment:

- DaVinci Resolve Studio 21.0.3.7
- Python 3.11.9
- Disposable project: `redline-os-test-duplicate`

Verified workflow:

```text
Existing episode
-> ordered media import
-> timeline creation
-> marker application
-> sequential clip placement
-> result validation
-> SQLite assembled status
-> assembled rerun rejection
```

Verified test media:

- Deterministic WAV
- Deterministic PNG

Verification:

- Unit-test result at commit time:

```text
253 passed
```

- Live verification passed media import, timeline creation, two markers, sequential placement, SQLite `assembled` status update, assembled rerun rejection, and validation failure without mutation.
- Live verification observed that DaVinci Resolve represents timelines as Media Pool items. When no dedicated Timelines bin is configured, a newly created timeline may appear in the currently active Media Pool bin. This is accepted V1 Resolve behavior, not an extra media import or assembly failure.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`

Limitations:

- No rollback.
- No cross-process concurrency protection.
- Stale-status protection is in-process only and does not survive restart.
- Linked video/audio cardinality remains unverified.
- `EpisodeBuildResult.timeline_id` may currently be equivalent to the timeline name; it must not be treated as a stable Resolve UUID.
- Redline OS does not change the project-level "Use Timelines Bin" setting or relocate created timelines.

### Milestone: Episode Manifest V1

Status: Implemented, Unit Tested, and Live Verified

Commit evidence:

```text
Captured by the Milestone 09 commit.
```

Capabilities:

- Implements the `redline_core.manifest` package.
- Loads strict YAML Episode Manifest V1 files through `load_manifest(...)`.
- Rejects duplicate YAML mapping keys before schema validation.
- Validates schema version `1`, required fields, unknown fields, marker shape,
  media path safety, active approved roots, and duplicate resolved media paths.
- Produces immutable `ValidatedEpisodePlan` objects.
- Stores immutable manifest-owned marker values in validated plans and creates
  fresh existing `MarkerDefinition` objects during translation into the existing
  `EpisodeBuildDefinition` contract.
- Performs pure loading and validation without SQLite, `EpisodeManager`, or
  DaVinci Resolve interaction.

Verification:

- Focused unit and temporary-filesystem integration tests cover the manifest
  loader, schema behavior, path validation, and translation.
- Controlled live verification passed on 2026-07-27 using Python 3.11.9 and
  DaVinci Resolve Studio 21.0.3.7. A disposable manifest for `RLC-E909`
  loaded, validated, translated into the existing `EpisodeBuildDefinition`,
  and executed through `EpisodeManager.build_episode(...)`.
- Live verification used the approved disposable `redline-os-test-duplicate`
  project as the template source because the configured `RLC_MASTER_TEMPLATE`
  project was not present in the active Resolve project folder.
- The run imported two expendable media files, applied two manifest markers,
  placed two timeline items, and marked the controlled episode assembled in a
  temporary verification SQLite database. Manifest media and marker order were
  preserved through translation and execution.
- Resolve represented the created `RLC-E909_TIMELINE` timeline as a Media Pool
  item in the target bin, matching the known V1 Episode Assembly behavior.
- The disposable `RLC-E909_MASTER` Resolve project and temporary manifest,
  media, and database artifacts were removed after verification. No production
  project or production media was modified.

Documentation:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md`
- `docs/EPISODE_MANIFEST_ARCHITECTURE.md`
- `docs/EPISODE_MANIFEST_SCHEMA.md`
- `docs/EPISODE_MANIFEST_LIFECYCLE.md`
- `docs/EPISODE_MANIFEST_VALIDATION.md`

Limitations:

- No manifest persistence, snapshots, checksums, or Build History.
- No MCP tools.
- No render/archive sections.
- No episode creation.
- No schema migration framework.
- Validation is deterministic intent at a point in time, not guaranteed
  historical reproducibility.
- UNC/network approved-root behavior was not live-tested.
- No render, archive, persistence, snapshot, checksum, or Build History behavior
  was introduced or verified.

### Milestone: Persistent Asset Registry V1 Architecture

Status: Architecture Drafted and Focus-Corrected, Pending Final Senior Re-Review

Commit evidence:

```text
Pending future commit.
```

Scope:

- Designs the first persistent Asset Registry architecture for Redline OS.
- Keeps the external Redline Production System authoritative for Asset IDs,
  approved metadata vocabulary, naming conventions, folder conventions, and
  creative or production standards.
- Classifies `config/assets.yaml` as the desired-state declaration and explicit
  reconciliation input, not as a competing persistent operational authority.
- Defines SQLite registry ownership as local Redline OS operational state:
  path state, lifecycle state, availability state, verification state,
  timestamps, diagnostics, and provenance.
- Separates external Asset ID, internal database row identity, filesystem path,
  file identity, and content identity.
- Recommends explicit config reconciliation with dry-run planning and
  transactional apply behavior. Startup must not silently mutate the registry.
- Defines V1 lifecycle, availability, verification, path-safety, error,
  logging, transaction, reconciliation, and future MCP compatibility models.
- Focus-corrected after senior architecture review to make config authority,
  component ownership, registration, state invariants, declared-path handling,
  transaction ownership, verification results, founder-decision status,
  identity rules, schema precision, and production/test separation
  implementation-ready.

Documentation:

- `docs/ASSET_REGISTRY_ARCHITECTURE.md`
- `docs/ASSET_REGISTRY_SCHEMA.md`
- `docs/ASSET_REGISTRY_LIFECYCLE.md`
- `docs/ASSET_REGISTRY_VALIDATION.md`

Limitations:

- Architecture and documentation only.
- No implementation code.
- No tests.
- No SQLite schema changes or migrations.
- No configuration changes.
- No MCP changes.
- No Resolve interaction.
- Asset-ID authority and local-operational V1 scope are resolved by repository
  contracts. Later expansion decisions remain open for broader production
  metadata, formal Asset-ID format validation, and approved asset categories.

### Milestone: RLC-E9901 Production Render Lifecycle (Queue Confirmation Through Completion)

Status: Live Verified via External Evidence (2026-08-11), Not Yet Committed to Repository

Commit evidence:

```text
Not applicable — this milestone is evidenced outside the repository (see below), not by a repository commit. The repository checkpoint at the time of authorization was 0a0614bbb90af64b51766a434c920291ce2f027b ("feat: add render job status to Phase 14 queue snapshot probe").
```

Capabilities:

- Independent Resolve-side confirmation that RLC-E9901's already-queued render job (Resolve Job ID `3c0af847-bddd-43ee-8b79-a7b64cb915b4`) existed in Resolve's render queue, via the Rev5 render-queue snapshot/comparison probe (`classification: exact_single_job_match`, `job_status: Ready`).
- One authorized, successful production invocation of `RenderManager.start_render()` → `ResolveAdapter.start_render()` → `Project.StartRendering(...)`, exit code `0`, no retry.
- Getter-only reconciliation (`render status`) to `render_jobs.status = complete` and `episodes.status = rendered`.
- A verified rendered master on disk.

Verification (independently re-performed, read-only, by this documentation-correction mission — not merely restated from the evidence bundle):

- All four evidence files confirmed to exist at `C:\Users\pj198\RedlineOSLive\...`; SHA-256 independently recomputed and matched exactly against the values recorded in each file/handoff.
- Rendered master `RLC-E9901_MASTER.mov`: confirmed to exist, `132,364,925` bytes, SHA-256 `17e0099b591acd30790bbf3520955ba51f645b3f303ec8ff980219242230b6e9`.
- Live `redline.db` at `C:\Users\pj198\RedlineOSLive\Runtime\redline.db` queried directly, read-only: `render_jobs` row `id=1`, `episode_id=RLC-E9901`, `resolve_job_id=3c0af847-bddd-43ee-8b79-a7b64cb915b4`, `status=complete`; `episodes` row `RLC-E9901`, `status=rendered`; `archives` table has 0 rows for this episode — matching the evidence bundle's self-reported state exactly, field for field.

Documentation:

- `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md` §4 (full evidence table)
- `docs/ROADMAP.md` Phase 14 (dated correction entry)
- `README.md`

Limitations:

- **Not yet committed to this repository.** The live event occurred after commit `0a0614b` but before the nine subsequent commits through `1bca657`; none of those commits, nor any repository documentation prior to this correction, recorded it. This milestone entry is the first repository record of it.
- **Provenance gap, not concealed**: the exact original artifact showing how/when RLC-E9901's `AddRenderJob()` queue acceptance was first produced has not been independently re-traced by this correction — only the later queue-confirmation-through-completion chain (Rev5 snapshot onward) was independently re-verified.
- **Does not affect the separate `RLC-E9001` disposable experiment**, whose three documented `AddRenderJob()` failures (Missions 39D.1–39D.3) remain unresolved and are a distinct thread from RLC-E9901.
- Archive Manager has not been run against this episode (`archives` table: 0 rows for RLC-E9901) — archiving remains a separate, not-yet-performed step.

## Current System Capabilities

Based on current repository evidence, Redline OS can execute this verified V1 assembly path:

```text
Episode lifecycle
    -> Resolve project duplication
    -> media import
    -> timeline creation
    -> marker application
    -> sequential clip placement
    -> assembly result validation
    -> SQLite status transition
```

Additional current capabilities:

- Configuration loading and validation for naming, paths, folders, render presets, assets, and timeline templates.
- SQLite persistence for episodes, render jobs, and archives.
- Asset verification against configured local paths.
- Ingest scanning and media organization through the media manager.
- MCP tools for episode, asset, media, timeline, render, and archive manager operations.
- Render and archive manager logic tested against the mock Resolve adapter.
- Episode Manifest V1 loading, validation, and translation into
  `EpisodeBuildDefinition`, without SQLite or Resolve interaction during pure
  validation.
- Persistent Asset Registry V1 architecture documentation, pending review and
  approval before implementation.
- Render-queue post-`AddRenderJob()` reconciliation: `RenderQueueIdentityUnresolvedError`
  and `RenderQueueAcceptanceNotObservedError` distinguish unresolved
  Resolve queue identity from the narrower condition in which no accepted
  job was observed under the exact unchanged-ID-multiset predicate, both
  with full diagnostic logging routed through the configured `redline_os`
  application logger to `<REDLINE_LOG_DIR>/redline_os.log` (Missions
  39D.1-39D.2). The broader live queue path has been exercised three
  times; the attempts successively exposed the missing-ID condition,
  validated the identity-unresolved diagnostics, and validated the final
  acceptance-not-observed classification. See Phase 14 in
  `docs/ROADMAP.md`. Missions 39D and 39E are formally closed; the
  `RLC-E9001` disposable experiment described in this bullet remains open
  and blocked because Broadcast Master queue acceptance was never observed
  for it. This is a separate thread from `RLC-E9901`, whose own production
  render lifecycle was independently evidenced complete on 2026-08-11 — see
  the "RLC-E9901 Production Render Lifecycle" milestone above.
- Workstation Resolve configuration validation (Mission 39E): the interactive
  Windows identity for current Resolve validation is `CHOICES\pj198`, Python
  3.11.9 is operational for the current Resolve integration, Python 3.13 is
  incompatible with the current Resolve scripting import because it crashes
  with Windows access violation `0xC0000005`, and the read-only adapter probe
  connected to `RLC-E9001_MASTER` / `RLC-E9001_TIMELINE` with zero render queue
  jobs and rendering inactive. Mission 39E did not prove Broadcast Master queue
  acceptance.

Not all current capabilities are live Resolve verified. Render queueing
itself is fully implemented (not stubbed). Earlier development live-verified
the real Resolve adapter's direct-ID queue-success path using the
`YouTube - 720p` preset; that earlier result did not validate the later
Mission 39B Broadcast Master production workflow (output claims,
deterministic naming, and the Broadcast Master preset). Three controlled
live attempts against the disposable Broadcast Master episode (`RLC-E9001`)
have proven the live queue path fails closed with consistent postflight
state each time but have not yet observed Resolve accept that specific
request — see Phase 14 in `docs/ROADMAP.md`.

## Future Milestones

The following are Proposed or Planned unless promoted by later architecture,
implementation, tests, live verification, documentation, and commits:

- Expanded persistent Asset Registry behavior: Architecture drafted, pending senior review.
- Persistent build history: Planned.
- Build recovery and explicit reset policy: Planned.
- Linked video/audio placement cardinality verification: Planned.
- Dedicated timeline-bin organization: Proposed.
- Broadcast Master render queue acceptance and export verification for the
  `RLC-E9001` disposable Phase 14 experiment: Blocked pending root-cause
  investigation (the real adapter's direct-ID queue-success path was
  live-verified under a different preset; the Mission 39B Broadcast Master
  workflow remains unproven for this specific disposable episode). A future
  live queue attempt requires a separately reviewed attempt contract and
  fresh explicit founder authorization. **`RLC-E9901`'s own Broadcast Master
  render queue acceptance and export are no longer part of this Future
  Milestones entry** — see the "RLC-E9901 Production Render Lifecycle"
  Verified Milestone above.
- MCP exposure for Episode Assembly: Planned.
- Operator dashboard: Proposed.
