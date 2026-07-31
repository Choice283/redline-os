# Build Command Specification

## 1. Purpose

Phase 13 defines the production build command as an operator-facing
composition boundary over existing Redline OS capabilities.

The command exists to give operators one deterministic workflow for the
common production step:

```text
redline build Episode_0001
```

It is not a replacement for `EpisodeManager`, the manifest layer,
`TimelineBuilder`, `RenderManager`, `ArchiveManager`, the Resolve adapter, or
SQLite. It coordinates approved stages and delegates policy to the managers and
domain layers that already own it.

## 2. Command Form

The canonical command is:

```text
redline build Episode_0001
```

The approved option surface is:

```text
redline build Episode_0001 --manifest path/to/episode.yaml
redline build Episode_0001 --force
```

`--manifest` is allowed so an operator can provide an explicit Episode
Manifest V1 file instead of relying on default manifest resolution.

`--force` is allowed only as a transport vocabulary mapping to the existing
`EpisodeManager.build_episode(..., allow_unsafe_retry=True)` contract. It does
not add CLI-owned retry policy.

No render, archive, polling, cleanup, overwrite, or recovery options belong to
the initial build command.

## 3. Build Target Contract

The canonical build target spelling is:

```text
Episode_0001
```

Target rules:

- The prefix is exactly `Episode_`.
- The numeric suffix is exactly four decimal digits.
- The suffix must represent an integer greater than zero.
- The command accepts exactly one build target.
- Target parsing is case-sensitive.
- Leading or trailing whitespace is not part of the target and should be
  rejected by normal argument parsing before normalization.

Accepted examples:

```text
Episode_0001
Episode_0025
Episode_1234
```

Rejected examples:

```text
episode_0001
EPISODE_0001
Episode_1
Episode_001
Episode_0000
Episode_-001
Episode_0001_extra
RLC-E001
```

Normalization:

- `Episode_0001` normalizes to `episode_number = 1`.
- `Episode_0025` normalizes to `episode_number = 25`.
- The Redline episode ID is derived from the active loaded
  `config.naming.episode_id_pattern`, using the normalized episode number.
- With the current default pattern, `Episode_0001` derives `RLC-E001`.

The target is not itself an episode ID, manifest ID, Resolve project name,
folder path, or filename after parsing. It is the operator-facing selector used
to derive the existing Redline episode number and episode ID.

Ambiguity handling:

- If the target cannot normalize to exactly one positive episode number, the
  build fails before loading configuration-dependent episode state or touching
  Resolve.
- If a resolved manifest declares an episode ID that does not match the ID
  derived from the target, the build fails before episode creation or assembly.

Mission 31 implements this parsing contract.

## 4. Manifest Contract

The manifest remains an Episode Manifest V1 file owned by the operator or
production workflow. It is durable YAML assembly intent, not a render contract
or archive contract.

Default manifest resolution:

- For `redline build Episode_0001`, the default manifest candidate is
  `Episode_0001.yaml` in the process current working directory.
- If that file does not exist, the alternate default candidate is
  `Episode_0001.yml` in the process current working directory.
- If both default candidates exist, `Episode_0001.yaml` wins
  deterministically.
- If neither default candidate exists, resolution fails as a missing manifest.

Explicit manifest path:

- `--manifest path/to/episode.yaml` may be provided.
- An explicit manifest path has precedence over default target-based
  resolution.
- When an explicit manifest path is provided, the target still remains the
  canonical build target, and the manifest's `episode.id` must match the
  episode ID derived from that target.

Manifest loading and validation:

- Build must reuse the existing `redline_core.manifest.load_manifest()` and
  `redline_core.manifest.validate_manifest()` behavior.
- Relative media paths continue to resolve relative to the manifest file's
  directory.
- Approved media roots remain the active loaded `config.paths.ingest_path` and
  `config.paths.assets_path`.
- Missing, unreadable, malformed, invalid, or path-unsafe manifests fail before
  episode creation or assembly.

Mission 32 implements this manifest-resolution contract.

## 5. Build Stage Model

The initial build command owns this ordered stage model:

1. CLI argument parsing.
2. Configuration loading.
3. Read-only build preflight:
   target parsing, manifest resolution, manifest loading, and manifest
   validation.
4. Mutable application composition.
5. Target-to-manifest episode identity check.
6. Episode resolution.
7. Episode creation or reuse.
8. Assembly through the existing Episode Manifest V1 to
   `EpisodeManager.build_episode(...)` path.
9. Build result summary.

The initial build command stops after successful assembly. Rendering and
archival are not part of the initial build stage boundary.

The build result reports completed stages. The command must not skip earlier
validation to discover later failures.

Phase 14 Mission 38A clarifies the preflight boundary after the first live
episode attempt found that a missing manifest could create the default SQLite
database before failing. `redline build` now performs target parsing, manifest
path selection, manifest loading, manifest validation, and target/manifest
episode identity confirmation with configuration only. Full mutable application
composition, including SQLite initialization, Resolve connection, and
persistent logging artifact creation, occurs only after that preflight succeeds.
The validated preflight request is then passed into
`BuildOrchestrator.build_prepared(...)` so the manifest is not loaded or
validated a second time.

## 6. Episode Creation and Reuse Contract

No existing episode:

- Build creates the episode through `EpisodeManager.create_episode()`.
- If creation fails, build stops and reports the owning failure.
- If creation partially persists state before failing, build does not roll back
  or repair that state.

Existing episode:

- Build may reuse an existing episode row only by delegating assembly
  eligibility to `EpisodeManager.build_episode(...)`.
- Build must not make its own status eligibility matrix.
- Existing episode status, unresolved assembly claims, failed status, and
  terminal statuses are interpreted by `EpisodeManager`.

Prior assembly state:

- A successfully assembled episode is a conflict for build re-execution.
- A downstream episode state such as render queued, rendered, or archived is a
  conflict for build re-execution.
- Build must not convert these conflicts into no-ops unless a later approved
  manager-level policy changes that behavior.

Assembly claim:

- An active or unresolved assembly claim remains an uncertain outcome signal.
- Build must not clear the claim.
- Build must not mutate SQLite directly.

Force:

- Without `--force`, build passes `allow_unsafe_retry=False`.
- With `--force`, build passes `allow_unsafe_retry=True`.
- `--force` does not affect target parsing, manifest resolution, manifest
  validation, episode creation, render behavior, archive behavior, or direct
  SQLite state.
- `--force` does not roll back, verify, repair, or clean Resolve mutations.
- Terminal statuses remain blocked by `EpisodeManager` even with `--force`.

Partial state:

- Build does not reconcile SQLite and Resolve.
- Build does not inspect Resolve beyond calls made by the managers it invokes.
- Operators must use `docs/RECOVERY.md` for interrupted or uncertain outcomes.

## 7. Ownership Boundaries

CLI:

- Accepts arguments.
- Performs config-only build preflight before mutable composition.
- Invokes approved build composition with the prepared request.
- Prints or serializes the result.
- Maps known failures to exit behavior.
- Does not own business policy.

Build orchestration boundary:

- Coordinates the approved build stages.
- Keeps the stage order deterministic.
- Delegates manifest behavior to the manifest layer.
- Delegates episode lifecycle and assembly policy to `EpisodeManager`.
- Delegates no render or archive behavior in the initial build contract.

EpisodeManager:

- Owns episode creation.
- Owns episode lookup.
- Owns assembly eligibility.
- Owns assembly claim acquisition and release.
- Owns assembly status transitions and stage-aware `EpisodeBuildError`.

Manifest loader and validator:

- Own durable YAML syntax, schema validation, path safety, and translation into
  `EpisodeBuildDefinition`.
- Do not touch SQLite or Resolve.

Timeline and assembly components:

- `MediaManager` owns media import delegation.
- `TimelineBuilder` owns timeline naming, timeline build, marker application,
  and clip placement delegation.
- `ResolveAdapter` owns raw Resolve API interactions and Resolve-specific
  failure boundaries.

RenderManager:

- Owns render queue, status, cancellation, and render-job SQLite updates.
- Is not invoked by the initial build command.

ArchiveManager:

- Owns moving working folders to archive storage and archive records.
- Is not invoked by the initial build command.

Database:

- Owns persisted pipeline state primitives.
- Is not modified directly by CLI or build transport code.

## 8. Build Orchestration Boundary

Phase 13 introduces a dedicated build-level orchestration boundary.

It is needed because `redline build Episode_0001` spans target parsing,
configuration, manifest resolution, optional episode creation, manifest
validation, and assembly. Putting that sequence directly into the CLI would
turn the CLI into an orchestration and policy-adjacent layer, which conflicts
with the repository's established transport discipline.

The build orchestration boundary:

- receives the raw build target string, an explicit working directory, an
  optional manifest path, and the unsafe-retry pass-through value;
- coordinates the approved build stages;
- calls `load_manifest()` and `validate_manifest()` through the manifest layer;
- compares the derived episode ID to the manifest episode ID;
- looks up whether the episode exists;
- calls `EpisodeManager.create_episode()` when no episode exists;
- calls `EpisodeManager.build_episode()` with the approved force mapping;
- produces a structured build result.

When a transport already completed read-only preflight, it may call
`BuildOrchestrator.build_prepared(...)` with the prepared request. That entry
point resumes with an identity-invariant check and mutable episode
orchestration; it must not re-run target parsing, manifest resolution, manifest
loading, or manifest validation.

It must not:

- implement target parsing rules that belong to Mission 31;
- implement manifest path-resolution rules that belong to Mission 32;
- duplicate manifest validation;
- duplicate `EpisodeManager` retry or status policy;
- call subordinate managers individually for assembly;
- call `RenderManager` in the initial build contract;
- call `ArchiveManager` in the initial build contract;
- call raw Resolve APIs;
- mutate SQLite directly.

Dependency direction:

```text
CLI -> build orchestration boundary -> existing redline_core managers/layers
```

The boundary returns a build result. It does not print.

Mission 33 implements this approved boundary.

## 9. Render Boundary Decision

Initial decision: `redline build Episode_0001` stops after successful assembly.
It does not queue a render.

Reasons:

- Rendering is already async by design: queue, status, and cancellation are
  separate operations.
- `RenderManager.queue_render()` returns immediately and does not imply render
  completion.
- Render queueing mutates Resolve render settings and the render queue.
- Render recovery has separate status and cancellation concerns.
- Including render in the initial build command would force a preset-selection
  contract before the build command's core assembly contract is proven.
- Excluding render keeps Mission 34 small and testable.

Implemented companion boundaries:

- Mission 35 exposes CLI render commands as thin transports over
  `RenderManager`.
- Mission 36 adds `BuildRenderWorkflow` as a transport-neutral composition
  boundary that queues one render only after `BuildOrchestrator.build(...)`
  returns successfully.
- Mission 36 does not change the core meaning of `redline build`: the build
  command still normalizes target, resolves manifest, creates or reuses the
  episode, and assembles through `EpisodeManager`.
- No combined CLI command exists in Phase 13.

Success of the initial build command does not imply render queued, rendering,
render complete, or render output present.

## 10. Archive Boundary Decision

Initial decision: `redline build Episode_0001` does not archive.

Reasons:

- Archive moves the working folder to cold storage and marks the episode
  archived.
- `ArchiveManager.archive_episode()` currently does not gate on render status.
- Silent archive as a side effect would be surprising and destructive.
- Existing recovery and deployment documentation keep archive operations
  explicit.

Archival remains an explicit operator action through the existing archive
manager and transports. A future phase may define a release/package command,
but that is not part of the Phase 13 build contract.

## 11. Success Contract

A successful initial build means:

- the target parsed successfully;
- the manifest resolved, loaded, and validated successfully;
- the manifest episode ID matched the target-derived episode ID;
- the episode existed or was created successfully;
- `EpisodeManager.build_episode(...)` completed successfully;
- SQLite was updated according to the existing assembly path;
- the build result reports the build as assembled.

Success must include enough information for an operator to identify the result:

- target;
- episode number;
- episode ID;
- manifest path;
- completed stages;
- final state;
- Resolve project name;
- timeline name;
- imported media count;
- marker count;
- placed clip count.

Success exit behavior for the CLI command is exit code `0`.

Success does not imply:

- render queued;
- render started;
- render completed;
- archive created;
- rollback or cleanup performed.

## 12. Failure Contract

Failures remain deterministic and attributable to the owning layer.

Expected categories:

- Invalid target: owned by the target parser; fails before manifest loading,
  DB access, Resolve mutation, or persistent logging artifact creation.
- Missing or ambiguous manifest: owned by manifest resolution; fails before
  manifest loading, DB access, Resolve mutation, or persistent logging artifact
  creation.
- Manifest load, parse, schema, validation, or path failure: owned by the
  manifest layer; fails before DB access, Resolve connection, episode creation,
  persistent logging artifact creation, or assembly.
- Target/manifest mismatch: owned by the build orchestration boundary; fails
  before DB access, Resolve connection, episode creation, persistent logging
  artifact creation, or assembly.
- Configuration failure: owned by config loading.
- Episode creation failure: owned by `EpisodeManager.create_episode()` and its
  dependencies.
- Existing-state conflict: owned by `EpisodeManager.build_episode()`.
- Assembly claim conflict: owned by `EpisodeManager.build_episode()` and
  `Database.claim_episode_for_assembly()`.
- Resolve connection or Resolve API failure during create or assembly: owned by
  the Resolve adapter boundary and surfaced through the manager stage that
  invoked it.
- Assembly failure: owned by `EpisodeManager.build_episode()` and reported with
  its stage-aware failure behavior.

Render failures are not part of the initial build failure contract because the
initial build command does not queue, poll, or cancel renders.

CLI failure behavior maps known build failures to exit code `1` and does not
leak raw tracebacks across the transport boundary.

## 13. Idempotency and Re-Execution

Running:

```text
redline build Episode_0001
```

more than once is not defined as an automatic no-op.

Completed build:

- A repeated invocation after successful assembly reaches existing manager
  policy and is expected to fail as an already assembled episode.

Partially completed build:

- A repeated invocation after interruption or failure is governed by persisted
  episode status and assembly claim state.
- Build does not inspect or repair Resolve state before retrying.
- Operators must inspect state according to `docs/RECOVERY.md`.

Existing episode:

- If the episode exists and is in a manager-approved pre-assembly state, build
  may proceed to assembly.
- If the episode exists in failed or unresolved-claim state, normal build is
  blocked unless manager policy allows the requested `--force` path.

Force:

- `--force` maps only to `allow_unsafe_retry=True`.
- `--force` does not make completed, render queued, rendered, or archived
  episodes retryable.

No-op expectations:

- The initial build command should not silently treat an already assembled
  episode as success.
- The initial build command should not silently skip assembly because Resolve
  appears to contain a timeline.

Conflict expectations:

- Conflicts are reported as failures attributable to the owning layer.

## 14. Result Model Requirements

The build result exposes only the minimum useful information:

- `target`
- `episode_number`
- `episode_id`
- `manifest_path`
- `completed_stages`
- `final_state`
- `project_name`
- `timeline_name`, when assembly succeeds
- `media_count`
- `markers_applied`
- `clips_placed`
- `warnings`

Render job identity is excluded from the initial result because render is
excluded from the initial build contract.

The result model remains transport-neutral. CLI formatting and any future MCP
serialization must be derived from the same result, not separate business logic.

## 15. CLI Boundary

Mission 34 places only this behavior in the CLI:

- accept the build target argument;
- accept approved options;
- invoke the approved composition boundary;
- print or serialize the build result;
- map known failures to exit code behavior.

The CLI must not:

- load business policy;
- duplicate manifest validation;
- create ad hoc retry loops;
- poll renders;
- archive automatically;
- mutate SQLite directly;
- call raw Resolve APIs;
- call subordinate managers individually for assembly.

## 16. Explicit Non-Goals

Mission 30 and the initial build contract do not include:

- no parser implementation;
- no manifest resolver implementation;
- no build orchestrator implementation;
- no CLI command implementation;
- no new Resolve behavior;
- no manager redesign;
- no render polling loop;
- no background worker;
- no automatic archive;
- no rollback;
- no reconciliation;
- no deployment changes;
- no MCP changes;
- no UI;
- no cloud services;
- no telemetry;
- no installer.

## 17. Mission Mapping

Mission 31 - Build Target Parsing:

- May implement the `Episode_0001` parsing and normalization contract.
- Must not load manifests, touch SQLite, connect Resolve, or assemble episodes.

Mission 32 - Manifest Resolution:

- May implement target-to-manifest and explicit `--manifest` resolution.
- Must reuse existing manifest loader/validator after resolution.
- Must not create episodes or assemble.

Mission 33 - Build Orchestrator:

- May implement the approved build orchestration boundary and result model.
- Must delegate policy to the manifest layer and `EpisodeManager`.
- Must not include render or archive behavior.

Mission 34 - CLI `redline build`:

- May expose the build boundary through the CLI.
- Must keep the CLI thin.
- Must not duplicate orchestration or manager policy in CLI code.

Mission 35 - CLI Render Surface:

- Exposes `RenderManager` queue, status, cancel, and list operations through
  CLI.
- Does not change build command behavior by itself.

Mission 36 - Build to Render Integration:

- Adds `BuildRenderWorkflow` as a transport-neutral workflow that sequences a
  successful build into one render queue request.
- Preserves standalone `redline build` and `redline render` behavior.
- Preserves async render boundaries and avoids polling loops.

Mission 37 - Documentation and Verification:

- Documents and verifies the Phase 13 workflow.
- Records what is proven and what remains explicit operator action.

## 18. Acceptance Examples

Valid target:

```text
redline build Episode_0001
```

Expected meaning: target parses to episode number `1`; active config derives
the Redline episode ID, currently `RLC-E001`.

Invalid target:

```text
redline build episode_0001
```

Expected result: invalid target failure before manifest loading, SQLite access,
or Resolve mutation.

Missing manifest:

```text
redline build Episode_0001
```

Expected result when neither `Episode_0001.yaml` nor `Episode_0001.yml` exists
in the process current working directory: missing manifest failure before
episode creation or Resolve mutation.

Explicit manifest:

```text
redline build Episode_0001 --manifest manifests/episode.yaml
```

Expected result: explicit path is loaded instead of default candidates, and
the manifest `episode.id` must match the target-derived episode ID.

New episode:

```text
redline build Episode_0001
```

Expected result when the manifest is valid and no episode exists:
`EpisodeManager.create_episode()` creates the episode, then
`EpisodeManager.build_episode()` assembles it.

Existing episode:

```text
redline build Episode_0001
```

Expected result when the episode already exists in a manager-approved
pre-assembly state: build reuses the existing episode and delegates assembly
eligibility to `EpisodeManager`.

Assembly conflict:

```text
redline build Episode_0001
```

Expected result when the episode is already assembled or downstream: build
fails through existing manager policy. It does not report success as a no-op.

Successful assembly:

```text
redline build Episode_0001
```

Expected result: build completes through assembly and reports assembled state,
project identity, timeline identity, and media/marker/clip counts. No render is
queued and no archive is created.

Repeated invocation:

```text
redline build Episode_0001
redline build Episode_0001
```

Expected result: the second command reaches existing-state conflict unless a
future manager policy explicitly changes completed-build idempotency.
