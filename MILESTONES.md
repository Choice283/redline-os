# Redline OS Verified Milestones

Redline OS milestones are not considered complete merely because code exists.
For production-facing Resolve work, a completed verified milestone should normally
pass through architecture review, implementation, unit testing, senior review,
focused corrections, controlled live verification, documentation, and a Git
commit.

This document is an engineering history and verification record. It separates
implementation status from unit-test coverage, live Resolve verification,
documentation, and committed history.

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

Not all current capabilities are live Resolve verified. Render queue operations remain stubbed in the real Resolve adapter.

## Future Milestones

The following are Proposed or Planned unless promoted by later architecture,
implementation, tests, live verification, documentation, and commits:

- Episode Manifest: Planned.
- Expanded persistent Asset Registry behavior: Proposed.
- Persistent build history: Planned.
- Build recovery and explicit reset policy: Planned.
- Linked video/audio placement cardinality verification: Planned.
- Dedicated timeline-bin organization: Proposed.
- Real render queue implementation and export verification: Planned.
- MCP exposure for Episode Assembly: Planned.
- Operator dashboard: Proposed.
