# Changelog

## Unreleased - Phase 10 Mission 15: real Resolve `get_render_status`

- Implements `ResolveScriptAdapter.get_render_status(resolve_job_id) -> str`
  for real Resolve, preserving the existing public adapter contract. The lookup
  is scoped to the currently loaded Resolve project through
  `ProjectManager.GetCurrentProject()` and uses
  `Project.GetRenderJobStatus(resolve_job_id)` as the authoritative live-status
  API.
- Live API probing on Resolve Studio 21.0.3.7 confirmed that
  `GetRenderJobList()` returns render-job inventory and metadata but does not
  include live status. `GetRenderJobStatus(job_id)` returns a dictionary
  containing `JobStatus` and `CompletionPercentage` for known jobs and `None`
  for unknown jobs.
- Maps verified/approved Resolve statuses to Redline strings: `Ready` ->
  `queued`, `Rendering` -> `rendering`, `Complete` -> `complete`, `Failed` ->
  `failed`, and both `Cancelled`/`Canceled` -> `cancelled`. Unknown
  well-formed statuses return `unknown`, so `RenderManager` preserves the
  stored DB status instead of guessing.
- Rejects empty/non-string job IDs, missing current projects, malformed known
  job responses, and unavailable project managers with `RenderJobError` or
  `ResolveConnectionError` as appropriate. Unexpected Resolve API exceptions
  are wrapped in `RenderJobError` with the original exception preserved as
  `__cause__`.
- Adds focused fake-Resolve unit coverage in
  `tests/unit/test_resolve_script_adapter_render_status.py`. No manager,
  database, CLI, MCP, polling, progress persistence, project-searching, or
  cancellation behavior changed.
- Remaining Phase 10 real-Resolve gap: `cancel_render`.

### Verification

- Focused Mission 15 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_status.py -q` -> 28 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_status.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py -q` ->
  74 passed.
- Live adapter-level verification against disposable project
  `redline-os-test-duplicate` and Resolve job
  `6ac314da-9c99-41eb-bf79-621e5f6b7edc` returned `queued`.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 989
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 15 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 14: real Resolve `queue_render`

- Implements `ResolveScriptAdapter.queue_render(project_name, preset_name,
  output_path) -> str` for real Resolve. This is enqueue-only: it applies the
  named Resolve render preset, applies the output directory through
  `SetRenderSettings({"TargetDir": ...})`, adds exactly one render job with
  `AddRenderJob()`, and returns the Resolve render job ID. It does not start
  rendering, poll status, cancel jobs, add CLI commands, change MCP contracts,
  add manifest render sections, or alter `RenderManager` policy.
- Adds a documented adapter boundary in `docs/ARCHITECTURE.md` before the
  production-code change. `RenderJobError` remains the domain-specific render
  failure type. Unexpected Resolve API exceptions are wrapped as
  `RenderJobError` with the original exception preserved as `__cause__`.
- Handles Resolve's version-sensitive `AddRenderJob()` return shape without
  guessing: if `AddRenderJob()` returns a usable scalar ID (`str` or `int`),
  that ID is returned directly; otherwise the adapter compares
  `GetRenderJobList()` snapshots from before and after queueing and accepts
  exactly one newly appeared job ID. Missing, duplicate, or ambiguous
  candidates raise `RenderJobError`. If a job was queued but ID extraction or
  reconciliation fails, no automatic rollback or deletion is attempted; manual
  Resolve/SQLite reconciliation may be required.
- Failure boundaries covered explicitly: disconnected adapter, unknown project,
  empty preset name, preset-load rejection, output-setting rejection,
  `AddRenderJob()` rejection, missing job ID, ambiguous job ID, and unexpected
  Resolve API exceptions. Logging includes project/preset/job context without
  unnecessarily exposing full output filesystem paths.

### Verification

- Focused Mission 14 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_queue.py` -> 15 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py
  tests\unit\test_resolve_script_adapter_import_media.py
  tests\unit\test_resolve_script_adapter_timeline.py
  tests\unit\test_resolve_script_adapter_clip_placement.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_mcp_tools.py` -> 192 passed.
- Live verification passed on 2026-07-29 with DaVinci Resolve Studio
  21.0.3.7 and Python 3.11.9 against the disposable
  `redline-os-test-duplicate` project, built-in `YouTube - 720p` preset, and
  `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests` output
  directory. `AddRenderJob()` returned
  `6ac314da-9c99-41eb-bf79-621e5f6b7edc`, and the post-call
  `GetRenderJobList()` contained exactly one job with that same `JobId`.
  `get_render_status` and `cancel_render` remain unimplemented for real
  Resolve.

### Known unrelated regression limitation

- Full `tests\unit` was executed with Python 3.11.9 and completed with 961
  passed, 9 skipped, and 24 failed. The failures are pre-existing CLI
  end-to-end fixture portability defects: Windows paths are embedded in
  double-quoted YAML, causing PyYAML to interpret sequences such as `\U` as YAML
  escapes. Mission 14 does not change the affected CLI fixtures or YAML-
  generation logic. Repair is deferred to a separate focused maintenance
  mission.

## Unreleased - Phase 9 Mission 13: `redline episode assemble` CLI + atomic assembly claim

- Adds `redline episode assemble <manifest_path> [--force]` — the mutating
  counterpart to Mission 12's `validate-manifest`, and the first CLI action
  to reach `EpisodeManager.build_episode()`. A thin wrapper over the
  existing `load_manifest()` -> `validate_manifest()` ->
  `.to_build_definition()` -> `build_episode()` pipeline. Routed through
  `ApplicationServices`, the same composition tier as every other mutating
  `episode` action — no `cli/main.py` dispatch change needed, unlike
  Mission 12.
- Preceded by `docs/adr/ADR-0001-episode-assembly-retry-policy.md`, the
  project's first ADR: found that the existing rerun guard (an in-memory
  `_unsafe_rerun_episode_ids` set) provided zero protection through the CLI
  transport, since a fresh `EpisodeManager` is constructed on every CLI
  invocation. Replaced with an atomic, persisted assembly claim.
- `redline_core` changes (the first this Phase 9 initiative has required):
  - `schema.sql` / `database.py`: two new nullable `episodes` columns,
    `assembly_claim_token` and `assembly_claimed_at`, added via a new
    `Database._migrate_add_assembly_claim_columns()` migration (runs from
    `init_schema()`, no try/except — a failed migration fails application
    startup outright, per ADR-0001's explicit migration-failure policy).
    New `Database.claim_episode_for_assembly(episode_id, claim_token, *,
    allow_unsafe_retry=False) -> bool` and
    `Database.release_assembly_claim(episode_id, claim_token, status)`
    (token-owned: only releases a claim matching the caller's own token).
  - `episode/manager.py`: `build_episode()` gained a keyword-only
    `allow_unsafe_retry: bool = False` parameter (CLI's `--force` maps to
    it). `_get_existing_episode_for_build()` replaced with
    `_claim_episode_for_build()`, which claims the episode atomically
    before any Resolve mutation begins and threads the resulting
    `claim_token` through every `_build_error()` call site. The old
    in-memory `_unsafe_rerun_episode_ids` set is gone entirely.
  - `db/models.py`: `Episode` gained `assembly_claim_token` /
    `assembly_claimed_at` fields (and `from_row()` reads them), so the
    claim state the schema/database layer added is actually readable back
    through the model — caught and fixed during this mission's own test
    writing, not part of the original #46/#47 slices.
- **Two correctness issues found in review before this mission was
  committed, both fixed prior to commit:**
  1. The originally proposed forced-claim `UPDATE` guarded only by `status
     NOT IN (terminal...)`, with no dependency on the existing claim token
     at all — so two concurrent forced (`--force`) callers racing the same
     dangling claim could both satisfy that guard and both acquire it,
     violating ADR-0001's single-claimant invariant. Fixed by replacing it
     with `Database._claim_episode_for_assembly_cas()`: a diagnostic
     `SELECT` of the current `(status, assembly_claim_token)`, followed by
     a compare-and-swap `UPDATE` whose `WHERE` clause is pinned to exactly
     that observed pair (`IS NULL` when the observed token is `None`). The
     `SELECT` authorizes nothing; the guarded `UPDATE`'s rowcount remains
     the sole authority on acquisition. A genuinely sequential second
     forced call (one that freshly observes the first's already-committed
     token) can still legitimately take over — that's an operator issuing
     `--force` twice with accurate current information, not a race, and is
     not what this guards against.
  2. `release_assembly_claim()` originally logged an error and returned
     silently when no row matched the given token (rowcount 0) — on the
     success path, this could let `build_episode()` return an
     `EpisodeBuildResult` even though the episode was never actually
     marked `assembled` and the claim was never actually cleared. Fixed:
     `release_assembly_claim()` now raises a new
     `AssemblyClaimReleaseError` on a rowcount-0 release. Both existing
     call sites already had `except Exception` handling (the final
     success-path release, and `_build_error()`'s own failure-cleanup
     release), so this converts correctly into `EpisodeBuildError` (stage
     `status_update`) without needing new branching logic at either site.
- Full exhaustive status matrix enforced by `_claim_episode_for_build()`:
  `created`/`assets_verified`/`media_organized`/`timeline_built` claimable
  normally; `failed` and an active/unresolved claim from a prior attempt
  blocked without `--force`, claimable with it; `assembled`/
  `render_queued`/`rendered`/`archived` always blocked, no override under
  any flag, ever.
- `--force` is a pure transport-vocabulary translation, not a policy
  decision: the CLI passes it straight through as `allow_unsafe_retry` and
  never inspects episode status or claim state itself. The `--force`
  warning banner prints whenever the flag was passed, before checking the
  result, including on a failed (e.g. terminal-status-blocked) attempt.
- New tests: 15 DB-level tests (`test_db.py` — claim/release/token-owned-
  release/migration-idempotency/legacy-table-upgrade, plus 5 added for the
  CAS correctness fix: two racers on the same dangling claim resulting in
  exactly one success, a second racer failing against already-superseded
  state, `IS NULL` handling for a never-claimed episode, and terminal
  status rejected without attempting the update), 11 new `EpisodeManager`
  tests plus 3 rewritten ones (`test_episode_manager.py` — full status
  matrix, dangling-claim block/override, forced-retry-after-failure, plus
  2 added for the release-failure fix: a real (non-monkeypatched) token
  mismatch during the final release converts to `EpisodeBuildError`
  instead of a success result, and a positive proof that the claim is
  durably committed — visible via a second, independent DB connection —
  before `MediaManager.import_media()` runs), and 14 new CLI tests
  (`test_cli_episode_assemble.py` — success/failure payload shapes,
  `--force` warning banner, argument parsing, and an in-process `main()`
  end-to-end proof that `--force` actually unblocks a `FAILED` episode
  through the real CLI entry point). Full suite: 978 passed, 1 skipped (up
  from Mission 12's 938 passed, 1 skipped).
- **Phase 9 (Episode Production Pipeline) is now complete.** A post-
  implementation gap review found no remaining capability: `redline_core.manifest`'s
  entire public surface (`load_manifest()`, `validate_manifest()`) is called
  from the CLI (`validate-manifest` directly; `assemble` via
  `.to_build_definition()`), and `EpisodeManager.build_episode()` is now
  CLI-reachable via `assemble`. See `docs/ROADMAP.md`'s Phase 9 row.
- Manual smoke test: an in-process script sharing one `MockResolveAdapter`
  across sequential `main()` invocations (required, since the mock adapter
  is in-memory only and separate CLI processes don't share it) verified,
  against the real CLI entry point: a successful assemble; an ordinary
  retry blocked by the now-`assembled` terminal status; the same retry
  still blocked with `--force` (terminal statuses are never overridable);
  a `FAILED` episode blocked without `--force`; and the same episode
  successfully retried with `--force`. Repo working tree stayed clean
  throughout.

## Unreleased - Phase 9 Mission 12: `redline episode validate-manifest` CLI

- Adds `redline episode validate-manifest <manifest_path>` as an eighth
  `episode` action — the first Phase 9 mission, per the approved Phase 9
  Architecture Proposal and Mission 12 Implementation Contract. A thin,
  read-only wrapper over the existing, already-tested
  `redline_core.manifest.load_manifest()` and `.validate_manifest()`. No
  `redline_core` code changed: `EpisodeManager`, `TimelineBuilder`,
  `MediaManager`, `AssetManager`, `ArchiveManager`, the Resolve adapter,
  and the manifest loader/validator/models are all unmodified.
- Routed through `CoreServices`, not `ApplicationServices` — the first
  `episode` action to need only config, confirmed directly against
  `validate_manifest()`'s real signature (`RedlineConfig` only, no `db`,
  no `resolve`). `cli/main.py` now branches on `args.action` within the
  `episode` resource for this one case, dispatching to a new, separate
  `episode_commands.run_validate_manifest()` rather than adding an eighth
  branch to the existing `run()` (which stays typed `ApplicationServices`,
  unchanged, for the other seven actions). See `docs/ARCHITECTURE.md` for
  the full reasoning, including why a general per-action dispatch
  mechanism was deliberately not introduced for what's currently a single
  demonstrated case.
- Argument shape deviates from every other `episode` action on purpose:
  takes `manifest_path`, not `episode_number` — episode identity comes
  from inside the manifest file (`episode.id`), not from an operator-typed
  number, the same kind of contract-driven deviation `archive episode
  <episode_id>` already established.
- Result payload: `episode_id`, `bin_name`, `media_paths`, `media_count`,
  `markers` (each with `frame`/`color`/`name`/`note`), `marker_count` — all
  read directly off the existing `ValidatedEpisodePlan`, no new fields
  invented. Zero configured markers is a successful result
  (`marker_count: 0`), matching the manifest schema's own optional-markers
  default.
- Exception handling: catches exactly `ManifestLoadError`,
  `ManifestParseError`, `ManifestSchemaError`, `ManifestValidationError` —
  verified to transitively cover their subclasses `ManifestVersionError`
  and `ManifestPathError` via the actual class hierarchy in
  `redline_core/manifest/exceptions.py`, not a convenience catch of the
  shared `ManifestError` root. `str(exc)` passed through unchanged.
- No `--mock-resolve` needed or read by this command.
- New tests: `tests/unit/test_cli_episode_validate_manifest.py` (14 tests),
  including a gating `main()` end-to-end test that runs with neither
  `REDLINE_DB_PATH` set nor `--mock-resolve` passed — direct proof the new
  `CoreServices` routing actually took effect, mirroring the same proof
  `test_cli_asset_list.py` already established for `asset list`. Full
  suite: 938 passed, 1 skipped (up from Mission 11B's 924 passed, 1
  skipped).
- Manual smoke test: ran the installed `redline` console script directly
  against a real manifest file, with neither `REDLINE_DB_PATH` nor
  `--mock-resolve` set — a valid manifest (exit 0, full reported fields)
  and a missing-file manifest (exit 1, exact underlying error message).
  Repo working tree stayed clean throughout.
- Mission 13 (`episode assemble`) was blocked pending a separate
  architecture decision on rerun/recovery policy at the time this mission
  landed; resolved via ADR-0001 and implemented — see the Mission 13 entry
  above.

## Unreleased - Mission 11B: `redline episode place-clips` CLI

- Adds `redline episode place-clips <episode_number> [clip_id ...]` as a
  seventh `episode` action, as a thin wrapper over the existing,
  already-tested `TimelineBuilder.place_clips()`. This is the last
  `TimelineBuilder` public method to gain CLI exposure — `apply_markers()`
  remains internal-only (no natural episode-scoped argument shape; see
  Mission 11's architecture review).
- Unblocked directly by Mission 11A: `timeline_name` is resolved via
  `TimelineBuilder.timeline_name_for_episode()` — a pure call, no Resolve
  side effects — rather than by calling `build_timeline_for_episode()`
  again, which would have silently re-applied (duplicated) markers as an
  unrelated side effect.
- `clip_ids` are passed through completely unchanged: same order, no
  deduplication. Zero clip IDs is a successful no-op (`placed_count: 0`)
  — the adapter itself never touches the project or timeline when given
  an empty list, so this is the existing contract, not a CLI-invented
  distinction.
- Result payload echoes back both the requested `clip_ids` and the
  returned `timeline_item_ids`, since `place_clips()` preserves order
  position-for-position between them — real operator value, unlike
  `build-timeline`'s omitted `timeline_id`.
- Exception tuple matches Mission 10's: `EpisodeNotFoundError`,
  `ProjectNotFoundError`, `TimelineOperationError`, messages passed
  through unchanged; `ResolveConnectionError` remains owned by the
  top-level CLI boundary. No `mcp_server` changes.
- No new manager-level tests: `TimelineBuilder.place_clips()` and
  `timeline_name_for_episode()` both already have complete, independent
  coverage from Missions 10 and 11A. `tests/unit/test_cli_episode_place_clips.py`
  (17 tests) is CLI transport coverage only.
- No composition change: `ApplicationServices` already provided
  everything this command needs.
- Full suite: 924 passed, 1 skipped (up from Mission 11A's 911 passed, 1
  skipped).
- Smoke testing used two distinct categories, since mock Resolve state
  cannot survive across separate `redline` process invocations: an
  in-process smoke test (one shared `MockResolveAdapter` instance across
  `create` → `build-timeline` → `organize-bins` → `place-clips`, proving
  both the successful placement and the genuine "timeline not found"
  failure when `place-clips` runs before `build-timeline`), and an
  installed-script smoke test for the cases that don't need cross-process
  state (parser/`--help` behavior, zero-clip success, unknown-episode
  failure). A separately-invoked "project not found" case was also
  confirmed directly against the installed script, since a freshly
  started process's mock adapter has no projects at all.

## Unreleased - Mission 11A: pure timeline-naming helper (internal refactor, no CLI change)

- Adds `TimelineBuilder.timeline_name_for_episode(episode_id: str) -> str`,
  a pure method that formats `config.timeline.timeline_name_pattern` for a
  given `episode_id`. No Resolve, no SQLite, no logging, no mutation —
  reads one config field and returns a string.
- `TimelineBuilder.build_timeline_for_episode()` now calls this helper
  instead of inlining the `.format()` call. No observable behavior change:
  identical input produces the identical `timeline_name` it always did,
  proven by every existing `test_timeline_builder.py` assertion passing
  unmodified.
- `EpisodeManager.build_episode()`'s own pre-computation of `timeline_name`
  (used for early-stage error context before a real timeline exists) also
  now calls `self.timeline_builder.timeline_name_for_episode(...)` instead
  of independently reformatting the same pattern. This removes a
  pre-existing duplication — `EpisodeManager` was computing the identical
  value a second time, independently of `TimelineBuilder`, before this
  change — rather than merely preventing a new one. No observable
  behavior change here either: every existing `test_episode_manager.py`
  assertion (including the one checking `EpisodeBuildError.timeline_name`
  on a clip-placement failure) passes unmodified.
- This mission exists solely to resolve a real architectural blocker
  found while reviewing Mission 11's `place_clips` CLI candidate: neither
  `apply_markers()` nor `place_clips()` can be safely exposed by a
  transport without a way to obtain `timeline_name` that doesn't
  duplicate the naming pattern or re-trigger `build_timeline_for_episode()`'s
  marker-duplication side effect. A future `place-clips` CLI command can
  now call `services.timeline_builder.timeline_name_for_episode(episode_id)`
  directly. No CLI, MCP, Resolve, composition, or database change is part
  of this mission — `place-clips` itself remains deferred.
- Scope note: `tests/unit/test_episode_manager.py`'s hand-rolled
  `FakeTimelineBuilder` test double needed `timeline_name_for_episode()`
  added to it as well, to keep that file's existing tests passing against
  the refactored `EpisodeManager.build_episode()` call site — a necessary
  consequence of keeping the existing regression suite genuinely
  unmodified in behavior, not a scope expansion.
- New tests: two direct `timeline_name_for_episode()` tests in
  `tests/unit/test_timeline_builder.py`, proving the helper is
  pattern-driven (a second, different pattern/episode_id combination
  produces a different result) rather than hardcoded. Full suite: 911
  passed, 1 skipped (up from Mission 10's 909 passed, 1 skipped).

## Unreleased - Mission 10: `redline episode build-timeline` CLI

- Adds `redline episode build-timeline <episode_number>` as a sixth
  `episode` action, as a thin wrapper over the existing, already-tested
  `TimelineBuilder.build_timeline_for_episode()`. Continues the
  Resolve-driven CLI layer begun in Mission 9; `apply_markers()` and
  `place_clips()` (the other two `TimelineBuilder` public methods) remain
  internal-only primitives — used by `EpisodeManager.build_episode()`'s
  manifest flow — and are not exposed as independent CLI/MCP surfaces in
  this mission. Timeline IDs also remain internal: the CLI result and
  output report only `episode_id`, `project_name`, `timeline_name`, and
  `markers_applied`, never `timeline_id`.
- `episode_number` is resolved via the same `EpisodeManager.get_episode_status()`
  call every other `episode` action uses. No markers override is ever
  passed to the manager: `TimelineBuilder` owns timeline naming
  (`config.timeline.timeline_name_pattern`) and configured marker
  selection (`config.timeline.markers`) entirely on its own; the CLI does
  not re-derive the timeline name pattern itself anywhere.
- No new composition tier: `ApplicationServices` already provides
  everything this command needs (DB via `EpisodeManager` for episode
  resolution, Resolve via `TimelineBuilder` for the build/marker calls) —
  confirmed sufficient during architecture review, same tier every other
  `episode` action already uses.
- Zero configured markers is a successful result (`markers_applied: 0`),
  not an error, matching the manager's own behavior.
- Exception handling: catches exactly `EpisodeNotFoundError` (own
  episode-number resolution step), `ProjectNotFoundError`, and
  `TimelineOperationError` (both from `redline_core.resolve.exceptions`),
  messages passed through unchanged. `ResolveConnectionError` is excluded
  from this command-local tuple for the same reason established in
  Mission 9 — connection happens during `build_application_services()`,
  already owned by `main()`'s top-level boundary. `mcp_server/tools/timeline_tools.py`
  was not modified in this mission.
- **New required manager-level test**, closing a real, previously-uncovered
  gap found during architecture review: `TimelineBuilder.build_timeline_for_episode()`
  reuses an existing Resolve timeline by name (no duplicate timeline
  object is created on a second call — this was already true and already
  tested at the adapter layer), but it always reapplies the full
  configured marker set regardless, so calling it twice against the same
  episode duplicates markers on the timeline. `tests/unit/test_timeline_builder.py`
  now proves this directly (one timeline name after two calls, but `2N`
  stored markers where `N` is the configured count) — this is documented,
  existing behavior, not something this mission introduces or fixes.
- New tests: `tests/unit/test_cli_episode_build_timeline.py` (17 tests)
  plus the one new repeated-build test in `test_timeline_builder.py`.
  Full suite: 909 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script
  (`--mock-resolve`). Unknown-episode failure was run as a genuinely
  separate process invocation (exit 1). The successful-build case, and a
  second call against the same episode demonstrating the real
  marker-duplication behavior above (`markers_applied: 2` reported on
  both calls, not cumulative), were verified by sharing one
  `MockResolveAdapter` instance across `main()` calls — the same
  technique established in Mission 9 for cross-invocation Resolve state.
  Repo working tree stayed clean throughout.

## Unreleased - Mission 9: `redline episode organize-bins` CLI

- Adds `redline episode organize-bins <episode_number> [--bin-name footage]`
  as a fifth `episode` action, alongside `create`/`scan-ingest`/`status`/
  `list`, as a thin wrapper over the existing, already-tested
  `MediaManager.organize_bins()`. This begins the Resolve-driven CLI layer
  described in the Mission 9 architecture review; `MediaManager.import_media()`
  remains an internal-only primitive (used by `EpisodeManager.build_episode()`'s
  manifest flow) and is deliberately not exposed as its own CLI/MCP surface
  in this mission.
- `episode_number` is resolved to an `Episode` record via the existing
  `EpisodeManager.get_episode_status()` — the same call `scan-ingest`/
  `status` already use — giving `episode_id` and `project_name` for free
  (both already stored on the `Episode` record); no new lookup method or
  translation layer was added. `--bin-name` is passed through unchanged,
  defaulting to the manager's own literal default (`"footage"`) rather
  than inventing a new one.
- No new composition tier: `ApplicationServices` already provides
  everything this command's episode-number resolution and media import
  need (DB via `EpisodeManager`, Resolve via `MediaManager`) — confirmed
  sufficient during architecture review, same tier every other `episode`
  action already uses. `--mock-resolve` remains relevant, since this
  command genuinely calls `resolve.import_media()`.
- Zero matching ingest files is a successful result (`clip_count: 0`,
  `clip_ids: []`), not an error — matches `organize_bins()`'s own
  behavior (it returns `[]` without calling Resolve at all when nothing
  matches) and every prior mission's "empty state is still success"
  precedent. No episode-status update, no duplicate detection, no retry
  or rollback logic was added — `organize_bins()` doesn't perform any of
  those today, and this CLI action doesn't invent them.
- Exception handling: catches exactly `EpisodeNotFoundError` (from the
  CLI's own episode-number resolution step), `ProjectNotFoundError`, and
  `MediaImportError` (both from `redline_core.resolve.exceptions`,
  propagating through `MediaManager.import_media()` →
  `resolve.import_media()`), messages passed through unchanged.
  `ResolveConnectionError` is deliberately excluded from this command-local
  tuple — connection happens during `build_application_services()`, before
  this action's handler runs, and is already owned by `main()`'s existing
  top-level exception boundary. Unlike Missions 6-8, there was no
  already-defensive MCP tool to mirror here: `mcp_server/tools/media_tools.py`'s
  `organize_bins` tool has no exception handling of its own (see
  `docs/ARCHITECTURE.md`) — this CLI action's exception tuple was derived
  directly from what the manager/adapter can actually raise, not copied
  from the MCP transport. `mcp_server/tools/media_tools.py` itself was not
  modified in this mission.
- New tests: `tests/unit/test_cli_episode_organize_bins.py` (16 tests)
  plus one new custom-bin-name-forwarding test added to
  `tests/unit/test_media_manager.py` (a direct spy on the Resolve adapter
  call, proving forwarding without coupling to `MockResolveAdapter`'s
  internal clip-ID formatting or storage). Full suite: 895 passed, 1
  skipped.
- Manual smoke test: ran the installed `redline` console script
  (`--mock-resolve`) against an isolated temp config/DB. The zero-match
  and unknown-episode cases were run as genuinely separate process
  invocations (exit 0 and exit 1 respectively). The matched-media success
  case cannot be demonstrated across two separate real CLI invocations
  under `--mock-resolve` — confirmed directly: attempting it produced
  `ProjectNotFoundError`, since `MockResolveAdapter` has no persistence
  and `main()` builds a fresh instance every invocation, so a Resolve
  project created by one process doesn't exist for a separately-invoked
  one. That `ProjectNotFoundError` passthrough is itself a correct,
  real-world confirmation of this mission's failure handling. The
  matched-media success path was then verified directly against the
  installed package's own `cli.main.main()`, sharing one
  `MockResolveAdapter` instance across two calls (the same technique the
  automated end-to-end test uses) — episode created, clip imported,
  correct fields reported, exit 0. Repo working tree stayed clean
  throughout.

## Unreleased - Mission 8: `redline archive episode <episode_id>` CLI

- Adds the mutating `redline archive episode <episode_id>` action to the
  existing `archive` resource group (alongside Mission 7's `archive
  list`), as a thin wrapper over the existing, already-tested
  `ArchiveManager.archive_episode()`. `episode_id` is passed through
  completely unchanged — no type coercion, no `episode_number →
  episode_id` translation layer, resolving the argument-type finding
  recorded in Mission 7: the manager has always taken a raw string
  identifier (e.g. `"RLC-E025"`), never an episode number, and no call
  site anywhere in the repo has ever translated one into the other.
- Success output reports only the three fields on the manager's returned
  `ArchiveRecord` (`episode_id`, `archive_path`, `archived_at`) — reusing
  the existing `_archive_to_dict` from Mission 7 — with no additional
  Database or filesystem reads. Deliberately **no per-step progress
  checklist** (unlike `episode create`'s ✓ lines): this command reports
  the outcome, not `ArchiveManager`'s internal algorithm, so the CLI
  output stays correct even if the manager's internal steps change later
  (e.g. if its three DB writes are ever made transactional). See
  `docs/ARCHITECTURE.md` for where that internal-implementation detail
  now lives instead.
- Exception handling exactly mirrors the existing MCP tool
  (`mcp_server/tools/archive_tools.py._archive_episode`): catches
  `EpisodeNotFoundError` (from `redline_core.episode.exceptions`),
  `EpisodeAlreadyArchivedError`, and `ArchiveError` (both from
  `redline_core.archive.exceptions`) in one tuple, `str(exc)` passed
  through unchanged — no translation, no enrichment. Exit code `0` on
  success, `1` on any of the three exception types.
- Closes the one previously-uncovered `ArchiveManager` branch identified
  during Mission 8's architecture review: a pre-existing folder already
  sitting at the archive destination path with no matching archive
  record. Covered at two independent levels, per explicit instruction:
  `tests/unit/test_archive_manager.py` proves `ArchiveManager` itself
  raises `ArchiveError` for this condition (and that the source folder is
  left untouched, since `shutil.move()` never runs); the CLI's own test
  only proves the CLI passes that manager error through unchanged — it is
  not treated as that branch's only coverage.
- No composition change: `PersistenceServices` (Mission 7) already
  provided everything `archive_episode()` needs (`config.paths.archive_path`,
  `db`) — confirmed sufficient during architecture review, no new tier
  added.
- New tests: `tests/unit/test_cli_archive_episode.py` (11 tests) plus one
  new destination-collision test added to
  `tests/unit/test_archive_manager.py`. Full suite: 881 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script against
  an isolated temp config/DB (outside the repo tree), no `--mock-resolve`
  set. Confirmed both a successful archive (folder moved, DB fields
  updated, correct fields printed) and the destination-collision failure
  (folder left untouched, `ArchiveError` message printed unchanged, exit
  1). Repo working tree stayed clean throughout.

## Unreleased - Mission 7: `redline archive list` CLI + `PersistenceServices` composition path

- Adds the CLI's third resource group, `redline archive list` (no
  arguments), as a thin, read-only wrapper over the existing,
  already-tested `ArchiveManager.list_archives()`. Serialization reuses
  the exact three-field shape (`episode_id`/`archive_path`/`archived_at`)
  the existing MCP `list_archives` tool already uses. Order is whatever
  the DB returns (`SELECT * FROM archives ORDER BY archived_at`, no
  secondary sort key — a real latent nondeterminism on ties, not
  something this mission changes); the CLI does not re-sort. This
  mission adds only `archive list` — the mutating
  `redline archive episode <episode_id>` is deliberately deferred to a
  following mission, sequenced after this strictly smaller, read-only
  command per the same "smallest capability first" discipline every
  prior mission followed.
- New composition path:
  `redline_core.runtime.composition.PersistenceServices` /
  `build_persistence_services()` — configuration-backed services
  requiring SQLite persistence, but not Resolve. This is a third,
  distinct composition boundary alongside `ApplicationServices` (full
  runtime) and `CoreServices` (config-only), not a universal middle
  layer future commands default into; a manager only belongs here if it
  needs config and a DB connection but never touches Resolve, exactly
  `ArchiveManager`'s case. `ApplicationServices`/
  `build_application_services()` and `CoreServices`/
  `build_core_services()` are both **unchanged** — still the same full
  runtime and config-only paths as before. Small private construction
  helpers (`_resolve_config_dir`, `_resolve_db_path`, `_connect_database`)
  were extracted and are now shared by all three public builders, purely
  to avoid duplicating the same few lines a third time; none of the
  three public builders' own behavior changed as a result.
- **Argument-type finding from architecture review, resolved before
  implementation, not after.** This mission was expected to plausibly be
  `redline archive episode <episode_number>`, matching every other
  `episode`-adjacent CLI action so far. Fresh review of
  `ArchiveManager.archive_episode()` found it takes `episode_id: str`
  (e.g. `"RLC-E025"`), not an `episode_number: int` — confirmed against
  every existing call site (the MCP tool, all `test_archive_manager.py`
  tests). When Mission 8 implements the mutating `archive episode`
  command, its argument will be named and typed `<episode_id>` to match
  the real contract, not `<episode_number>` — this is a deliberate,
  reviewed decision, not an oversight, and does not affect this mission's
  read-only `archive list` (which takes no arguments at all).
- `list_archives()` has no failure modes of its own to report (no
  filtering, no arguments, nothing that can raise per the existing,
  already-tested manager) — `_run_archive_list()` always returns
  `success: True`, matching the existing MCP tool's shape exactly.
- New tests: `tests/unit/test_cli_archive_list.py` (10 tests) plus 4 new
  `build_persistence_services()` tests added to
  `tests/unit/test_composition.py`. Full suite: 870 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script against
  an isolated temp config/DB (outside the repo tree) with no
  `--mock-resolve` flag set — `archive list` printed "No archives found."
  on an empty DB and correctly displayed a seeded archived episode
  (`RLC-E025`) after one was created directly via `ArchiveManager`,
  confirming the command genuinely never depends on Resolve. Repo working
  tree stayed clean throughout (smoke test ran entirely under `/tmp`, not
  inside the repo).

## Unreleased - Mission 6: `redline asset verify` CLI

- Adds `redline asset verify [asset_id ...]`, a thin, read-only wrapper
  over the existing, already-tested `AssetManager.verify_assets_for_episode()`.
  Same `CoreServices` composition path as `asset list` — no DB, no Resolve.
- **Correction from the original Mission 6 framing.** This mission was
  initially sketched as `redline asset verify <episode_number>`, described
  as "the first cross-domain (episode + asset) CLI command." Fresh
  architecture review of `verify_assets_for_episode()`'s actual signature
  found it takes no episode identifier at all — just an optional
  `asset_ids: list[str] | None` override, defaulting to
  `config.assets.required_for_episode` (a single global list, not
  per-episode) when omitted. Every call site in the repo (the MCP tool,
  all existing unit tests) confirms this — none has ever passed an
  episode identifier. Building a CLI command that accepted
  `<episode_number>` and then didn't use it for anything would have been
  misleading UI, the same category of correction as Mission 2's original
  "ingest media" sketch and Mission 1's manifest/log lines. The command
  matches the real contract instead: no episode argument, not a
  cross-domain command.
- `found`/`missing` in the result dict reuse the existing MCP tool's exact
  shape (bare asset-ID strings, `all_present` bool) rather than inventing
  a richer one. A CLI-only `checked` list is built for display (`asset_id`,
  `status`, `path`) — but its `status` is assigned strictly from the
  manager's own `found`/`missing` result, never from a second
  `.is_file()` check in the CLI; the manager stays the sole authority on
  whether an asset is present. `path` is a display-only string built from
  `config.assets.get(asset_id).filename`, shown as `(not registered)`
  when no definition exists. Effective input order (explicit override, or
  `required_for_episode` when omitted) and duplicate asset IDs are both
  preserved as given, not re-sorted or deduplicated — matching the
  manager's own behavior exactly.
- Handles a real correctness trap at the argparse boundary: `nargs="*"`
  gives `[]` when no `asset_id` is passed, but the manager treats `[]`
  ("verify zero assets") and `None` ("use the configured default set")
  as different things. `asset_commands.run()` converts an empty parsed
  list to `None` before calling the handler, so `redline asset verify`
  with no arguments correctly triggers the default set rather than
  silently verifying nothing. Tested explicitly, both at the handler level
  and end-to-end through `main()`.
- Exit code is `0` for any completed verification, including one that
  finds missing assets — mirrors the existing MCP tool's `success: True`-
  always contract (missing assets is a reported result, not an operation
  failure). Exit `1` is reserved for genuine operational failures, handled
  by the existing top-level exception boundary in `main()` — no new logic
  needed for that.
- New tests: `tests/unit/test_cli_asset_verify.py` (14 tests). Full suite:
  858 passed, 1 skipped.

## Unreleased - Mission 5: `redline asset list` CLI + config-only composition path

- Adds the CLI's second resource group, `redline asset list` (no
  arguments), as a thin, read-only wrapper over the existing,
  already-tested `AssetManager.list_available_assets()`. Serialization
  reuses the exact three-field shape (`asset_id`/`description`/`filename`)
  the existing MCP `list_available_assets` tool already uses. Order is
  whatever the manager returns (config declaration order in
  `config/assets.yaml`) — not re-sorted; this ordering was never an
  explicitly asserted contract at the `redline_core` layer (the existing
  unit test checks membership via a set, not order), so this is presented
  as "current behavior," not a documented guarantee, and preserved as-is.
- New composition path: `redline_core.runtime.composition.CoreServices` /
  `build_core_services()` — configuration-backed services requiring
  neither SQLite nor Resolve (no adapter constructed or connected at all),
  scoped to exactly that dependency boundary rather than serving as a
  general "core" layer future commands default into; a manager only
  belongs here if it needs nothing but config, exactly
  `list_available_assets()`'s case. `ApplicationServices`/
  `build_application_services()` is **unchanged** —
  still the full runtime for the MCP server and every `episode` command.
  This was the first mission where a command actually demonstrated the
  need for the capability-specific construction deferred back in Mission
  1 — architecture review surfaced that `asset list` would otherwise fail
  without Resolve running despite touching nothing Resolve-related, which
  is exactly the situation that deferral was meant to avoid once a real
  case showed up.
  - Scoped narrowly per explicit instruction: no generic dependency-tier
    framework, no lazy DI container, no rework of Missions 1-4's
    `episode` commands (still on `ApplicationServices`, untouched).
  - `main.py` now selects the composition path per resource group before
    dispatch, rather than building one runtime unconditionally — routing
    logic, not new architecture.
  - Verified structurally, not just by inspection: a test monkeypatches
    `Database.connect`/`ResolveScriptAdapter.connect`/`.__init__` to raise
    if called, then calls `build_core_services()` and confirms no
    exception — proving the independence claim rather than assuming it
    from the implementation reading the same way twice.
  - Verified at the CLI-invocation level too: `redline asset list` runs
    successfully with `REDLINE_DB_PATH` unset and no `--mock-resolve`
    flag, and no `redline.db` file appears afterward — the real, visible
    payoff of the fix.
- New tests: `tests/unit/test_cli_asset_list.py` (9 tests), plus 3 new
  `build_core_services()` tests added to `tests/unit/test_composition.py`.
  Full suite: 844 passed, 1 skipped.

## Unreleased - Mission 4: `redline episode list` CLI + CLI module split

- Adds a fourth CLI action, `redline episode list` (no arguments), as a
  thin, read-only wrapper over the existing, already-tested
  `EpisodeManager.list_episodes()`. No filtering, pagination, or alternate
  ordering added — none exists on the underlying method (`SELECT * FROM
  episodes ORDER BY episode_number`, no `LIMIT`/`OFFSET`), so none was
  invented for the CLI either. Empty state ("No episodes found.") is a
  successful result (exit 0), matching the manager's own contract — zero
  episodes was never an error case anywhere in the stack.
- Splits `src/cli/` into a thin `main.py` (parser assembly, logging setup,
  building `ApplicationServices`, dispatch, exit-code translation) plus a
  new `episode_commands.py` holding every `episode` action's logic —
  `_run_*`/`_print_*` handler pairs, `_episode_to_dict`, subparser
  registration, and dispatch. This was one of the two trigger points
  agreed on in Mission 2 (`episode list` becoming a fourth action, or a
  new resource group appearing) for reconsidering the single-file
  structure; the other (a new resource group, e.g. `asset`) hasn't
  happened yet.
  - Mechanical move only: no generic command registry, base command
    classes, shared result dataclasses, printer framework, or DI
    container was introduced alongside the split.
  - Existing Mission 1-3 tests (`test_cli_episode_create.py`,
    `test_cli_episode_scan_ingest.py`, `test_cli_episode_status.py`) pass
    **unmodified** — `cli/main.py` re-exports the moved names
    (`_run_episode_create`, `_print_episode_create_result`, etc.) as thin
    aliases for backward compatibility, so no test file needed to change
    its imports.
- New tests: `tests/unit/test_cli_episode_list.py` (8 tests). Full suite:
  833 passed, 1 skipped.

## Unreleased - Mission 3: `redline episode status` CLI

- Adds a third CLI action, `redline episode status <episode_number>`, as a
  thin, read-only wrapper over the existing, already-tested
  `EpisodeManager.get_episode_status()`. No computed health checks,
  readiness inference, media counts, asset verification, or build
  validation — only what's already persisted on the `Episode` row.
- Extends the shared `_episode_to_dict()` helper (used by `episode create`
  since Mission 1) with three additional fields: `id`, `created_at`,
  `updated_at`. Purely additive — `episode create`'s own output doesn't
  reference the new keys, and a dedicated test
  (`test_episode_create_output_unaffected_by_new_fields`) proves its output
  is unchanged. `created_at`/`updated_at` are passed through as-is: they're
  already deterministic `TEXT` columns (SQLite's `datetime('now')`) by the
  time they reach the `Episode` dataclass, not Python `datetime` objects,
  so no new formatting/parsing logic was introduced to make them
  "JSON-safe" — that safety already existed.
- Architecture review for this mission also produced a full inventory of
  every `redline_core` capability not yet CLI-exposed (see
  `docs/ARCHITECTURE.md` §5.1 note). Render commands (`queue_render`,
  `get_render_status`, `cancel_render`) were explicitly ruled out for any
  near-term CLI mission — the real Resolve adapter methods behind them are
  still stubbed per this README's own "Still open" note, so a CLI surface
  over them today would front a non-functional real-Resolve path.
- `src/cli/main.py` stays a single file — reassess only when `episode list`
  becomes a fourth action or a new top-level resource group (e.g. `asset`)
  is introduced, per the explicitly agreed trigger points.
- New tests: `tests/unit/test_cli_episode_status.py` (9 tests). Full suite:
  825 passed, 1 skipped.

## Unreleased - Mission 2: `redline episode scan-ingest` CLI

- Adds a second CLI command, `redline episode scan-ingest <episode_number>`,
  as a thin, read-only wrapper over the existing, already-tested
  `MediaManager.scan_ingest_for_episode()`. Zero new business logic:
  matching is still purely by episode-ID substring in the filename,
  regardless of extension (a `.txt` file matches exactly as readily as a
  `.mov`), and a missing ingest folder is treated the same as "no
  matches" — the existing method's behavior, not a new distinction
  invented for this slice.
- Deliberately does **not** add media-type classification (video/audio/
  graphic), duplicate detection, file copying/moving/renaming, Asset
  Registry insertion, or Resolve media-pool import (that's the separate,
  existing `organize_bins()`, still not CLI-exposed). Confirmed during
  architecture review that none of this is on the approved roadmap or
  built anywhere yet — the Persistent Asset Registry / reconciliation
  engine (Milestone 10) explicitly excludes duplicate-content detection
  from its own scope and covers a different domain (externally-approved
  Universe assets, not raw incoming episode footage). Output ends with an
  explicit disclaimer ("No files were classified, deduplicated, copied,
  moved, imported, or registered.") so a scan is never mistaken for
  completed ingestion.
- `src/cli/main.py` stays a single file for now rather than splitting into
  per-resource command modules — two commands doesn't yet justify that
  structure; revisit when a third command makes the file unwieldy.
- New tests: `tests/unit/test_cli_episode_scan_ingest.py` (9 tests), same
  tmp-path-isolated-config discipline established in Mission 1. Full
  suite: 816 passed, 1 skipped.

## Unreleased - Mission 1: `redline episode create` CLI

- Redline OS is now reachable from a terminal, not just as MCP tool calls.
  Adds a second, sibling transport: `src/cli/` (mirrors `mcp_server/`'s thin
  shape) with one command, `redline episode create <episode_number>`
  (`--mock-resolve` supported, same as `mcp_server.server`'s flag), wired
  via a new `redline` console-script entry point.
- Extracts the shared composition root out of `mcp_server/context.py` into
  a transport-neutral `redline_core/runtime/composition.py`
  (`ApplicationServices` / `build_application_services()`), so both
  transports build Config + Database + Resolve connection + all six
  managers from one place instead of duplicating the wiring.
  `mcp_server/context.py` is now a thin alias (`AppContext =
  ApplicationServices`) delegating to it — no behavior change for the MCP
  server; `tests/unit/test_mcp_tools.py` passes unmodified as proof.
- Deliberately does **not** add `CompositionOptions`/capability-specific
  construction (e.g. skip-Resolve) in this slice — no command yet needs a
  partial runtime, so that flag would have no real caller or acceptance
  test. Add it when the first genuinely Resolve-optional command (e.g.
  `episode inspect`, `config validate`) is actually built.
- Deliberately does **not** add a new "episode manifest" output artifact or
  a dedicated per-episode log file, despite both appearing in the original
  Mission 1 sketch — the former would collide with the existing, differently
  -scoped Episode Manifest V1 (input intent for `build_episode`, not an
  output receipt); the latter is already covered by the existing shared
  `redline_os.log` (`get_episode_logger`). Checklist wording reflects this:
  "Resolve project initialized" rather than "duplicated," since duplication
  is an implementation detail, not what the user needs to know.
- Zero changes to `EpisodeManager`, `MediaManager`, `TimelineBuilder`,
  `RenderManager`, `ArchiveManager`, or `AssetManager` business logic — this
  slice only adds a second way to reach the existing, already-tested
  `EpisodeManager.create_episode()` path.
- New tests: `tests/unit/test_composition.py` (4 tests) and
  `tests/unit/test_cli_episode_create.py` (13 tests). Every test that
  actually calls `create_episode()` uses an in-memory or tmp-path-scoped
  config rather than the real `config/` directory, since the real
  `config/folder_structure.yaml` root_path is a relative `./_episodes` that
  a naive test would otherwise write into the actual repo working tree.
  Full suite: 807 passed, 1 skipped.

## Unreleased - Asset Registry Reconciliation Repository Integration Compatibility (Phase 3 Slice 11)

- No production code changed. This slice adds two integration test files
  only, per the approved "Phase 3 Slice 11 Implementation Contract --
  Integration Compatibility (Roadmap Row 13), Revision 3 (final)":
  `tests/integration/test_snapshot_loading_from_sqlite_repository.py` (6
  tests) and `tests/integration/test_reconciliation_repository_compatibility.py`
  (11 tests) -- 17 tests total, matching the approved contract's test
  matrix 1:1 by number.
- Proves that a `RegistrySnapshot` populated from records read out of a
  real, temporary SQLite database via the existing (Phase 1/2)
  `SQLiteAssetRepository` flows through the unmodified reconciliation
  chain (`validate_reconciliation_inputs` -> `build_indexes` ->
  `build_matching_state` -> `evaluate_record_observability` ->
  `classify_reconciliation` -> `plan_reconciliation` ->
  `serialize_public_plan`) exactly as a `RegistrySnapshot` built from
  in-memory `AssetRegistryRecord` literals already does in the Slice 1-10
  unit tests.
- `AssetRegistryRecord.record_id` is proven immaterial to any serialized
  plan field at current HEAD by direct source inspection (no code path
  between `validate_reconciliation_inputs` and `serialize_public_plan`
  reads it, and every production `RegistryRecordSubject` construction
  passes only `asset_id`) -- not assumed. This is exercised directly: a
  cross-domain equivalence test uses a deliberately different `record_id`
  on its in-memory comparison side, and a reversed-insertion-order test
  across two independently-seeded temporary databases first asserts the
  two databases assigned different `record_id` values for a shared
  `asset_id`, then asserts identical canonical serialized bytes anyway.
- "No writes" and "no schema change" are verified as data-level
  before/after comparisons of repository-visible record state
  (`count_records`, `list_records`) and a direct, read-only
  `sqlite_master` + schema-version snapshot (filtered by `tbl_name` so
  both named and SQLite auto-generated indexes are captured, not just
  objects literally named `asset_registry...`) -- not as a claim that any
  specific repository write method was never called, since the
  reconciliation pipeline never holds a reference to the repository
  object in the first place.
- Component ownership is preserved: the corrected path/root-scope test
  builds its snapshot from `list_records(...)` (a complete registry read)
  and lets `ObservationScope.roots`/`evaluate_record_observability`
  perform the actual scope evaluation, rather than letting
  `get_by_normalized_path(...)` pre-filter which records reconciliation
  ever sees. A separate, explicitly-labeled bridge assertion independently
  confirms `get_by_normalized_path(...)` results are themselves valid
  `RegistrySnapshot` inputs, without claiming that proves scope
  resolution.
- No package-root export change (`__init__.py` and
  `test_package_exports.py` unmodified); no change to
  `src/redline_core/asset/sqlite_repository.py` or any reconciliation
  production module.
- Full existing `tests/unit` suite remains passing unchanged (794 passed,
  1 skipped, 795 total, exit code 0), and the pre-existing repository
  integration tests remain passing unchanged (`test_asset_sqlite_repository.py`,
  `test_asset_database_initialization.py`, 52 tests). Note: this
  repository's `pyproject.toml` sets `testpaths = ["tests/unit"]`, so a
  bare `python -m pytest` does not collect `tests/integration/` at all --
  running `python -m pytest tests/unit tests/integration` explicitly is
  required to exercise this slice's tests (and the pre-existing repository
  integration tests) as part of a genuinely complete regression run: 863
  passed, 1 skipped, 864 total, exit code 0.

## Unreleased - Asset Registry Reconciliation Public Serialization (Phase 3 Slice 10)

- `redline_core.asset.reconciliation.serialization`: new module implementing
  public plan serialization, per the approved "Phase 3 Slice 10
  Implementation Contract -- serialization.py, Revision 3 (final)". Adds
  the public entry point
  `serialize_public_plan(plan, *, limit_policy=DEFAULT_LIMITS) -> dict[str, Any]`,
  which converts one already-built `ReconciliationPlan` (Slice 9 output)
  into a stable, deterministic, JSON-compatible public dictionary.
- Redaction is a **structural allowlist**, not a per-fact `PublicVisibility`
  evaluation: `serialize_public_plan` walks the known, fixed set of fields
  on `ReconciliationPlan`/`ReconciliationPlanItem`/`PlanSummary`/
  `PlanSubject` explicitly, field by field -- never
  `dataclasses.asdict()`, `vars()`, `__dict__`, or any other
  reflection-based dump, so a future domain-model field does not
  automatically appear in public output. `PublicVisibility` and the other
  Slice-1 evidence-model enums remain unused, exactly as they are unused
  by every module built so far; no visibility classification is invented
  or inferred by this slice.
- `RegistryRecordSubject.record_id` is never emitted, whether populated or
  `None` -- `asset_id` is the stable public business identifier;
  `record_id` is an optional internal row reference the approved contract
  deliberately excludes from the public DTO.
- Determinism and the size guard both use one exact canonical byte
  definition:
  `json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")`.
  If that byte length exceeds `limit_policy.max_serialized_public_plan_bytes`,
  `serialize_public_plan` raises the existing `ReconciliationLimitExceededError`
  (no new exception class) with
  `context={"limit_name": "max_serialized_public_plan_bytes", "limit_value": ...}`
  -- no truncation, no partial payload. The function still returns the
  plain public `dict`, never bytes or a JSON string.
- No `PublicPlanSerializer` class exists; `serialize_public_plan` is a bare
  function, matching every other Slice 5-9 module's convention.
- `serialize_public_plan` does not re-run `planner.py`'s domain validation
  or recompute plan state; it projects the already-valid structure it is
  given. One output-integrity check (not a domain revalidation) confirms
  every emitted `evidence_ref` in the DTO this function itself builds
  appears in that same DTO's own top-level `evidence` list.
- `redline_core.asset.reconciliation.__init__.py` is **not** modified.
  `serialize_public_plan` is importable only as
  `redline_core.asset.reconciliation.serialization.serialize_public_plan`,
  matching the established precedent that `build_indexes`,
  `build_matching_state`, `classify_reconciliation`, and
  `plan_reconciliation` are also not package-root exports. This keeps
  `tests/unit/asset/reconciliation/test_package_exports.py` (Slices 1-2,
  unmodified) passing exactly as already approved.
- 26 new test cases across 20 numbered tests (`test_serialization.py`,
  matching the approved contract's test matrix 1:1 by number); full
  existing suite of 558 prior tests remains passing, 584 total, plus 1
  pre-existing unrelated skip.

## Unreleased - Manifest Validator: Avoid Process-Wide os.name Monkeypatch (Task #38)

- `redline_core.manifest.validator`: replaced a direct `os.name` monkeypatch in
  test code with a module-local `_is_windows()` indirection, used internally
  by `_duplicate_key()`. This is a test-hygiene / cross-cutting infrastructure
  fix, unrelated to Phase 3 reconciliation.
- The prior test
  (`test_windows_duplicate_key_strategy_is_case_insensitive`) patched the
  shared, process-wide `os` module's `name` attribute directly
  (`monkeypatch.setattr(manifest_validator.os, "name", "nt")`). Even though
  `monkeypatch` reverts this after the test, the mutation was observed to
  interact badly with pytest's own internal `pathlib.Path()` usage later in
  the same full-suite run, producing an unrelated `WindowsPath`
  `INTERNALERROR` at teardown/report time under certain collection orders.
- Fix: `validator.py` now exposes a small private function
  `_is_windows() -> bool` (returns `os.name == "nt"`), and `_duplicate_key()`
  calls this indirection instead of reading `os.name` directly. The test now
  patches `_is_windows` itself
  (`monkeypatch.setattr(manifest_validator, "_is_windows", lambda: True)`),
  exercising the same Windows-specific casefold branch without mutating any
  shared interpreter state.
- No behavior change to `_duplicate_key()`'s duplicate-key normalization
  logic; the Windows casefold branch itself is unchanged, only how it is
  tested. `tests/unit/test_manifest_validator.py` updated accordingly (1 test
  changed).
- Unrelated to Phase 3 Asset Registry Reconciliation; committed as its own
  isolated commit (`dd5959a`) between Slice 9 (`planner.py`) and Slice 10
  (`serialization.py`), per this project's standing discipline of never
  bundling an infrastructure fix into feature work.

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 9)

- `redline_core.asset.reconciliation.planner`: new module implementing final
  plan assembly, per the approved "Phase 3 Slice 9 Implementation Contract --
  planner.py, Revision 4 (final)". Adds the public entry point
  `plan_reconciliation(inputs, classification_state, *, created_at)`, which
  assembles one immutable `ReconciliationPlan` directly from Slice 8's
  `ClassificationState` -- no `findings.py`/`actions.py` object system.
- Plan item order is exactly `ClassificationState.decisions` order,
  index-for-index; no classification "rank" is invented or stored.
  Deterministic `item_id`s (`item-000001`, `item-000002`, ...) are assigned
  over that same order.
- `ReconciliationPlanItem.findings` and `.actions` are always `()` for every
  item, for every classification, with no exceptions; `evidence_refs` carries
  `ClassificationDecision.evidence_facts` forward unchanged.
  `PlanSummary.severities` and `PlanSummary.action_kinds` are always empty
  mappings. No action-kind mapping, severity table, or other domain policy is
  introduced by this slice -- all deferred to a future `actions.py`/
  `findings.py` contract, per the approved contract's Decisions 2, 3, and 5.
- No `ReconciliationPlanner` class exists; `plan_reconciliation` is a bare
  function, matching every other Slice 5-8 module's convention (contract
  Decision 4).
- `_limit_policy_fingerprint` (private, local to `planner.py`) computes a
  stable SHA-256 fingerprint over `ReconciliationLimitPolicy`'s fields,
  sorted by name; `canonical.py` is not modified (contract Decision 6).
- `redline_core.asset.reconciliation.__init__.py` is **not** modified.
  `plan_reconciliation` is importable only as
  `redline_core.asset.reconciliation.planner.plan_reconciliation`, matching
  the established precedent that `build_indexes`, `build_matching_state`,
  and `classify_reconciliation` are also not package-root exports. This
  keeps `tests/unit/asset/reconciliation/test_package_exports.py` (Slices
  1-2, unmodified) passing exactly as already approved.
- 58 new tests (`test_planner.py`), including a hand-built
  `PrimaryClassification.INVALID_OBSERVATION` decision confirming
  `PlanSummary.invalid_observation_count` actually increments (not just that
  it stays zero for classifications Slice 8's real pipeline can currently
  emit); full existing suite of 500 prior tests remains passing, 558 total,
  plus 1 pre-existing unrelated skip.
- `_verify_plan_invariants` checks each item ID against its exact expected
  position (`item-{index:06d}`), not merely uniqueness -- catching any
  ordering defect, not just collisions.

## Unreleased - Phase 3 Documentation Reconciliation (Post-Slice 8)

- Corrected `docs/ASSET_RECONCILIATION_ARCHITECTURE.md` and
  `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md` to accurately describe
  the bounded string-code evidence convention `matching.py` (Slice 6/7) and
  `classification.py` (Slice 8) already established and documented in their
  own docstrings. No code or tests changed.
- The current implementation uses the bounded string evidence model. The
  original `PlanEvidence`/`ReconciliationFinding`/action-object design
  remains documented as an earlier architectural proposal and is not part
  of the current Phase 3 implementation path — not removed and not judged
  permanently unnecessary. `findings.py`, `actions.py`, and richer
  structured evidence are reclassified as future / re-evaluate after
  `planner.py` and `serialization.py` are implemented.
- `evidence.py`: no rich `PlanEvidence` extension is required for the
  current Phase 3 critical path.
- Roadmap numbering in `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md`,
  section 25 is unchanged (rows 9, 10, 11 keep their existing numbers and
  module assignments). Row 11's dependency is corrected to name Slice 8
  directly, with an explicit Sequencing Note rather than a renumbering. The
  note also defines roadmap row numbers and implementation slice numbers as
  independent terminology, so `planner.py`, if built next, is correctly both
  Phase 3 Slice 9 and roadmap row 11 — see the row itself.

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 8)

- `redline_core.asset.reconciliation.classification`: new module implementing
  the central ordered classification engine, per the approved "Slice 8
  Implementation Contract -- Revision 3" (architecture-only session; no code
  changed during contract drafting). Adds `ClassificationDecision`,
  `ClassificationState`, and the public entry point
  `classify_reconciliation(inputs, indexes, matching_state,
  observability_by_asset_id)`.
- Implements a strict 15-rank executable precedence table (first match wins):
  registry identity evidence conflict, registry identity collision,
  authoritative identity conflict, content conflict, duplicate path conflict,
  ambiguous match, unknown authoritative Asset ID, path changed, lifecycle
  conflict, availability changed, record not observed, new unregistered
  observation, unchanged, metadata drift, insufficient scope.
- Four `PrimaryClassification` enum members (`REGISTRY_SNAPSHOT_INVALID`,
  `INVALID_OBSERVATION`, `UNSUPPORTED_OBSERVATION`, `DIAGNOSTIC_ONLY`) are
  documented as intentionally non-executable in this slice and are never
  produced; `DIAGNOSTIC_ONLY` in particular is not a catch-all -- a subject
  that matches no rule raises `ReconciliationInvariantError`
  (`reason_code="classification_no_rule_matched"`) instead.
- `observability_by_asset_id` is an explicit input contract: the caller
  resolves scope (via `scope.evaluate_record_observability`) for every
  unmatched registry record before calling `classify_reconciliation`; a
  missing entry raises `ReconciliationInvariantError`
  (`reason_code="classification_missing_observability_decision"`) rather than
  defaulting silently.
- `SIZE_CONFLICT` is not added to `PrimaryClassification` in this slice
  (deferred to a future dedicated slice, Decision 5a). Pending that slice, a
  size difference with no comparable verified hash classifies as
  `METADATA_DRIFT` with `requires_review=True` and evidence fact
  `size_differs_no_comparable_hash` -- documented as interim, temporary
  policy, not permanent semantics.
- `registry_identity_evidence_conflict` required no new index: computed
  directly from `indexes.registry.record_evidence_by_asset_id`, already
  built by Slice 5.
- `classification.py` imports `indexes.py` directly; the implementation
  plan's advisory import list for this module is corrected to include it
  (Decision 7) -- `findings.py` and `actions.py` do not exist yet in this
  repository and are not part of this slice's dependencies.
- 32 new tests (`tests/unit/asset/reconciliation/test_classification.py`),
  matching the "Slice 8 Implementation Contract -- Revision 3" exhaustive
  test matrix 1:1 by number; all prior Slice 1-7 reconciliation tests and the
  full existing suite (468 tests) remain unchanged and passing (500 total).

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 7)

- `redline_core.asset.reconciliation.matching`: added strong-identity
  matching (`unique_strong_identity`), extending `build_matching_state`
  after trusted-Asset-ID and exact-path matching (Slice 6). Precedence:
  trusted Asset ID > exact normalized path > unique strong identity.
- Bridges the registry's five-component comparable-evidence key
  (`RegistryEvidenceLookupKey`) and the observation's three-component key
  (`ObservationIdentityKey`) privately inside `matching.py`, without
  modifying `indexes.py`; see `docs/ASSET_RECONCILIATION_ARCHITECTURE.md`
  "Implementation Note: Registry/Observation Identity-Key Bridge" for the
  disclosed semantic consequence of that reduction.
- Adds `registry_identity_collision`, `observation_identity_collision`, and
  `mixed_identity_collision` conflict facts for ambiguous strong-identity
  evidence, and preserves existing trusted-ID/exact-path associations when
  strong identity disagrees with them (`strong_identity_authoritative_conflict`
  / `strong_identity_content_conflict`) rather than overwriting them.
  `indexes.py`, `MatchingState`, and `ConsumedIds` are unchanged.
- 50 new tests (`tests/unit/asset/reconciliation/test_matching_strong_identity.py`);
  all prior Slice 1-6 reconciliation tests remain unchanged and passing.
- Note: Slices 1-6 of this same reconciliation engine (`enums.py`/`models.py`
  through `matching.py`'s trusted-ID/exact-path stage) were implemented and
  approved in prior work but were never given their own changelog entries;
  this is a pre-existing documentation gap, not something this entry
  retroactively fills beyond Slice 7 itself.

## Unreleased - Persistent Asset Registry Architecture

- Added the Milestone 10 Persistent Asset Registry V1 architecture design
  package: `docs/ASSET_REGISTRY_ARCHITECTURE.md`,
  `docs/ASSET_REGISTRY_SCHEMA.md`, `docs/ASSET_REGISTRY_LIFECYCLE.md`, and
  `docs/ASSET_REGISTRY_VALIDATION.md`.
- Documented authority boundaries: the external Redline Production System
  remains authoritative for Asset IDs and production standards,
  `config/assets.yaml` is the desired-state declaration and explicit
  reconciliation input, SQLite owns local Redline OS operational registry state,
  filesystem checks are
  point-in-time observations, and MCP remains a future thin presentation layer.
- Documented the recommended V1 registry shape: one active local registry record
  per external Asset ID, one resolved local path per active record, explicit
  config reconciliation with dry-run planning, transactional apply behavior, no
  startup mutation, and no normal public hard deletion.
- Documented V1 lifecycle, availability, verification, path-safety, error,
  logging, transaction, reconciliation, testing, platform, security, and future
  MCP compatibility models without changing implementation code, tests,
  configuration, SQLite schema, MCP tools, or Resolve integration.
- Focus-corrected the architecture after senior review: `config/assets.yaml` is
  now the desired-state declaration and explicit reconciliation input;
  `AssetManager` is the sole public V1 service; `AssetRepository` is the
  persistence boundary; direct public registration and reactivation are
  deferred; lifecycle, availability, and verification invariants are explicit;
  declared paths are root-relative to `config.paths.assets_path`; service-owned
  transaction scope is documented; ordinary missing/non-file verification
  outcomes are results rather than exceptions; and implementation remains
  pending final senior re-review.

## Unreleased - Episode Manifest Implementation

- Implemented `redline_core.manifest`, the Episode Manifest V1 internal API:
  `load_manifest(...)`, `validate_manifest(...)`, `EpisodeManifest`,
  `ValidatedEpisodePlan`, and typed manifest exceptions.
- Added safe YAML loading with one-document enforcement, UTF-8 reads, top-level
  mapping enforcement, safe construction, non-string mapping-key rejection, and
  duplicate mapping-key rejection at every nested level without mutating PyYAML
  global constructors.
- Added strict Pydantic V2 manifest schema models for `schema_version: 1`,
  `episode.id`, `assembly.bin_name`, object-shaped `assembly.media[].path`, and
  manifest marker fields limited to `frame`, `color`, `name`, and `note`.
- Added manifest domain and filesystem validation: manifest-relative path
  resolution, active `ingest_path` / `assets_path` approved-root containment,
  component-aware path checks, duplicate resolved media-path detection, missing
  file and directory rejection, and UNC/network handling through the same
  approved-root policy.
- Added immutable `ValidatedEpisodePlan` translation into the existing
  `EpisodeBuildDefinition` contract. The plan stores immutable manifest-owned
  marker values and creates fresh existing `MarkerDefinition` objects during
  translation without changing `EpisodeManager`, `MediaManager`,
  `TimelineBuilder`, SQLite, MCP tools, or Resolve adapter code.
- Documented and tested that YAML merge keys (`<<`) are intentionally
  unsupported in Episode Manifest V1.
- Added focused manifest unit and temporary-filesystem integration tests for the
  pure manifest layer, which still must not interact with Resolve.
- Live-verified Episode Manifest V1 on 2026-07-27 against DaVinci Resolve
  Studio 21.0.3.7 with Python 3.11.9: a controlled `RLC-E909` YAML manifest
  loaded, validated, translated into `EpisodeBuildDefinition`, and executed
  through `EpisodeManager.build_episode(...)` using a disposable
  `RLC-E909_MASTER` project duplicated from the approved
  `redline-os-test-duplicate` test project. The run imported two expendable
  media files, applied two manifest markers at frames 0 and 48, placed two
  timeline items, preserved manifest media and marker order, and updated only a
  temporary verification SQLite database.
- The live manifest verification removed the disposable Resolve project and
  temporary manifest/media/database artifacts afterward. The configured
  `RLC_MASTER_TEMPLATE` project was not present in the active Resolve project
  folder, so the documented disposable test project was used as the approved
  template source for this controlled run. No production project or production
  media was modified.
- During manifest live verification, Resolve represented the created
  `RLC-E909_TIMELINE` timeline as a Media Pool item in the target bin. This
  matches the known V1 Episode Assembly behavior and was not treated as an
  unexpected media import.

## Unreleased - Episode Manifest Architecture

- Added the Phase 2 Episode Manifest V1 architecture design package:
  `docs/EPISODE_MANIFEST_ARCHITECTURE.md`,
  `docs/EPISODE_MANIFEST_SCHEMA.md`,
  `docs/EPISODE_MANIFEST_LIFECYCLE.md`, and
  `docs/EPISODE_MANIFEST_VALIDATION.md`.
- Documented the approved YAML-only V1 manifest scope: an explicit existing
  episode ID, ordered media paths, optional bin name, and optional marker
  overrides that translate into `EpisodeBuildDefinition` without making
  `EpisodeManager` parse manifests.
- Documented V1 validation boundaries: manifest parsing and pure validation are
  read-only, make no SQLite mutations, and perform no Resolve interaction.
- Hardened the design package after senior review: approved roots are locked to
  the active loaded `ingest_path` and `assets_path`, duplicate YAML keys must be
  rejected, path containment must use resolved path-aware comparisons, and
  validated plans are documented as deterministic intent rather than guaranteed
  historical reproducibility.
- Explicitly deferred JSON support, schema migrations, manifest persistence,
  build history, rollback, MCP manifest tools, render/archive sections, asset
  roles, creative policy, and advanced timeline placement concepts.

## Unreleased - Episode Assembly

- Added V1 Episode Assembly orchestration through `EpisodeManager.build_episode()`, operating on an existing episode record and delegating media import to `MediaManager` plus timeline creation, marker insertion, and clip placement to `TimelineBuilder`.
- Added `EpisodeBuildDefinition` and `EpisodeBuildResult` for the internal Python assembly API; generated media IDs and TimelineItem IDs are returned in order but are not persisted to SQLite.
- Added stage-aware `EpisodeBuildError` with failed stage, episode ID, completed stages, project/timeline names when known, progress counts, and preserved lower-level causes.
- Added `MediaManager.import_media()` for explicit ordered media path imports while preserving existing ingest-scanning `organize_bins()` behavior.
- Added rerun protection: successfully assembled episodes are marked `assembled` and a second assembly attempt is rejected before media import; failed episodes are not automatically retried because Resolve may already have been mutated.
- Hardened assembly status failures: original stage failures remain primary if marking `failed` also fails, and an `assembled` status-update failure now raises a stage-aware `EpisodeBuildError` instead of returning success or leaking a raw DB exception.
- Documented V1 live-verification limits for Episode Assembly: stale-status rerun protection is in-process only, concurrent/cross-process builds are not protected, and `timeline_id` must not be treated as a stable Resolve UUID yet.
- Added unit coverage for assembly validation, manager call ordering, ordered ID propagation, stage failure boundaries, result validation, partial-state logging, status behavior, and shared application-context dependencies.
- Verified V1 Episode Assembly against Resolve Studio 21.0.3.7 and Python 3.11.9 using the disposable `redline-os-test-duplicate` project with one deterministic WAV and one deterministic PNG: media import, timeline creation, two markers, sequential placement, SQLite `assembled` status update, assembled rerun rejection, and validation failure without mutation all passed.
- Live verification observed that Resolve may represent a newly created timeline as a Media Pool item in the currently active target bin when the project is not using a dedicated Timelines bin. This is accepted Resolve behavior for V1, not an extra media import or assembly failure; Redline OS does not change the project-level "Use Timelines Bin" setting or relocate timelines.
- Remaining V1 limitations: linked video/audio cardinality is unverified, rollback is not implemented, cross-process concurrency protection is not implemented, and the stale-status restart limitation remains.

## Unreleased — Phase 1 (real Resolve connection)

- **Milestone: `ResolveScriptAdapter.connect()` verified against a real, running DaVinci Resolve Studio 21.0.3 instance** (licensed/activated Studio edition, not the free edition). This was the one thing blocked since Phase 0 — it is now unblocked.
- `ResolveScriptAdapter.import_media()` now has a first production implementation: connected-state guard, local path validation, project loading, top-level media pool bin reuse/creation, one-shot `MediaStorage.AddItemListToMediaPool(...)` import, strict partial-import detection, and media item ID extraction via `GetMediaId()` with `GetUniqueId()` fallback.
- Verified `ResolveScriptAdapter.import_media()` against a live DaVinci Resolve Studio project: created a top-level media pool bin, imported one PNG, received a real non-empty `GetMediaId()` value, and confirmed the returned ID matched the item found during live Media Pool inspection.
- Added `MediaImportError` under the Resolve exception hierarchy for import validation, bin setup, Resolve import, and ID extraction failures.
- Added focused unit coverage for the real adapter import path using fake Resolve API objects; no running Resolve instance is required for these tests.
- Current limitation: partial Resolve imports and media-pool current-folder changes are reported as failures but not automatically rolled back yet; cleanup behavior is deferred until it is validated against a live project.
- `ResolveScriptAdapter.build_timeline()` and `.add_markers()` now have first production implementations covered by fake Resolve API unit tests. Existing timelines are reused by exact name; Resolve auto-renaming is rejected; marker validation happens before any Resolve modification; partial marker insertion is reported but not automatically rolled back.
- Added `TimelineOperationError` under the Resolve exception hierarchy for timeline lookup, creation, marker validation, and marker insertion failures.
- Current limitation: created timelines may remain after post-create verification failure, and markers may remain after partial insertion failure; automatic rollback is deferred until deletion/cleanup behavior is validated against live Resolve.
- Verified `ResolveScriptAdapter.build_timeline()` and `.add_markers()` against a live DaVinci Resolve Studio project: created an empty timeline, returned the exact requested timeline name, reused the existing timeline on a repeated call without creating a duplicate, added two markers at frames 0 and 48, and confirmed marker `customData` round-tripped through `Timeline.GetMarkers()`. Resolve created its normal default empty video and audio tracks; no clips were added.
- `ResolveScriptAdapter.place_clips()` now has a first production implementation for Version 1 sequential timeline placement: validates requested clip IDs, rejects duplicate requests, resolves imported Media Pool items recursively by `GetMediaId()` with `GetUniqueId()` fallback, sets the exact-name timeline current, appends the resolved clips in requested order with `MediaPool.AppendToTimeline([...])`, and returns TimelineItem `GetUniqueId()` values.
- Added `MockResolveAdapter.place_clips()` and `TimelineBuilder.place_clips()` so the public adapter contract is available in unit tests and higher-level timeline orchestration without automatically changing episode assembly.
- Hardened V1 placement before live testing: `clip_ids` must be a real list, recursive Media Pool traversal is protected against repeated folder handles/cycles by object identity, placement-time ID fallback now matches import behavior, duplicate TimelineItem IDs are rejected, AppendToTimeline exceptions preserve their cause, and the mock now supports multiple exact-name timelines per project.
- Verified `ResolveScriptAdapter.place_clips()` against a live DaVinci Resolve Studio project using a newly created disposable timeline: one audio-only WAV and one PNG still were placed in requested order, `AppendToTimeline([...])` returned one TimelineItem per requested MediaPoolItem, returned TimelineItem IDs were real non-empty `GetUniqueId()` values, and the physical timeline contained one audio item and one video item on the expected track types.
- Current limitation: partial Resolve placement and current-timeline changes are reported but not automatically rolled back.
- Current follow-up: linked video/audio cardinality still needs live verification; if one source MediaPoolItem can produce multiple returned linked TimelineItems, the strict Version 1 count invariant may need adjustment.
- Root-caused and fixed a hard crash encountered along the way: launching the connection test under Python 3.13 caused an access violation (`0xC0000005`) when `DaVinciResolveScript` loads Resolve's native `fusionscript` module. Resolve's scripting DLL isn't built for the 3.13 ABI. Switching to Python 3.11 (already installed at `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`) fixed it immediately — this is not a bug in our code, it's an environment/Python-version requirement, now documented in `README.md`'s Requirements section.
- Verified `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` env vars (set via `scripts/setup_env.ps1`, dot-sourced) resolve correctly against the real install locations on this machine.
- **Still open, same file (`src/redline_core/resolve/adapter.py`):** `queue_render`, `get_render_status`, and `cancel_render` still raise `NotImplementedError`.

## Unreleased — Phase 6/7

- DB: `get_episode_by_episode_id()`, full `render_jobs` CRUD (`create_render_job`, `get_render_job_by_id`, `list_render_jobs_for_episode`, `update_render_job`), full `archives` CRUD (`create_archive_record`, `get_archive_by_episode_id`, `list_archives`). New `ArchiveRecord` model.
- `ResolveAdapter` interface gained `cancel_render()` — implemented in `MockResolveAdapter` (raises if the job doesn't exist or is already in a terminal state), blocked in `ResolveScriptAdapter` same as everything else pending Studio.
- `redline_core.render.manager.RenderManager`: `queue_render()` (async — returns a job ID immediately), `get_render_status()` (polls Resolve and syncs the DB row; bumps the episode to `rendered` on completion), `cancel_render()`, `list_render_jobs_for_episode()`.
- `redline_core.archive.manager.ArchiveManager`: `archive_episode()` (moves the working folder to `paths.archive_path`, records it, marks the episode `archived`; deliberately doesn't gate on render status — see `docs/ARCHITECTURE.md` §9 on keeping business rules minimal), `list_archives()`.
- 20 new tests (`test_render_manager.py`, `test_archive_manager.py`, `cancel_render` cases in `test_resolve_mock.py`) — 69 total.
- MCP: 6 new tools across `render_tools.py` / `archive_tools.py` (`queue_render`, `get_render_status`, `cancel_render`, `list_render_jobs_for_episode`, `archive_episode`, `list_archives`) — **15 tools total**, the complete pipeline from the original architecture doc.
- Re-verified against the real `mcp` package: all 15 tools list correctly, and a real `call_tool('queue_render', ...)` round-trip works after `create_episode`.
- **This closes out the roadmap in `docs/ARCHITECTURE.md` §6** — every manager (Episode/Asset/Media/Timeline/Render/Archive) is built and tested against the mock. The only remaining gap is real Resolve Studio integration beyond `connect()` (Phase 1), blocked on a Studio license.

## Unreleased — Phase 5

- `src/mcp_server`: real MCP server built on the official `mcp` package's `FastMCP`. `context.py` (`AppContext` / `build_context()`) constructs one Config, one DB connection, one Resolve adapter, and all four managers exactly once at startup.
- 9 tools across 4 modules (`tools/episode_tools.py`, `asset_tools.py`, `media_tools.py`, `timeline_tools.py`): `create_episode`, `get_episode_status`, `list_episodes`, `list_available_assets`, `verify_assets_for_episode`, `scan_ingest_for_episode`, `organize_bins`, `build_timeline`, `add_markers`. Full reference in `docs/MCP_TOOLS.md`.
- Every tool's actual logic lives in an underscore-prefixed function with **no dependency on the `mcp` package** — `register()` is the only place that touches FastMCP. This means `tests/unit/test_mcp_tools.py` (11 new tests, 45 total) runs without the optional `[mcp]` extra installed, same as the rest of CI.
- `server.py` entrypoint (`python -m mcp_server.server`) with a `--mock-resolve` flag, so the whole tool surface can be tried today, before Studio is installed. New `[project.scripts]` entry point: `redline-mcp`.
- **Verified for real, not just logic-tested:** installed the `mcp` package and confirmed the actual `FastMCP` server builds, lists all 9 tools with correct schemas, and executes real `call_tool()` round-trips (`create_episode`, `list_episodes`, `verify_assets_for_episode`) — the "Create Episode 025" scenario from `docs/ARCHITECTURE.md` §4 now genuinely works end-to-end against the mock.
- Render/Archive tools intentionally not included — those managers don't exist until Phase 6/7.

## Unreleased — Phase 4

- New config: `MarkerDefinition` / `TimelineTemplateConfig` (`config/timeline_template.yaml`) — timeline naming pattern + the standard marker set (frame/color/name/note) per the Broadcast Package V1.0 spec. Data-driven, not hardcoded.
- `redline_core.timeline.builder.TimelineBuilder`: `build_timeline_for_episode()` (builds the timeline + applies the default marker set, returns a `TimelineBuildResult`), `apply_markers()` (also usable standalone, with an optional marker-set override for special episodes).
- Scope note: Timeline Builder does not duplicate the project (Episode Manager's job) or import media (Media Manager's job) — it only calls `ResolveAdapter.build_timeline()` / `.add_markers()`.
- 4 new tests (`test_timeline_builder.py`) — 34 total, all against `MockResolveAdapter`.
- `ResolveScriptAdapter.build_timeline()` / `.add_markers()` comments updated to reflect they were blocked on a real Studio license, same as the other adapter methods.

## Unreleased — Phase 3

- New config: `AssetDefinition` / `AssetsConfig` (`config/assets.yaml`), `assets_path` added to `PathsConfig` (`config/paths.yaml`). Asset IDs remain sourced from the Universe project — this only records where the approved file lives on disk.
- `redline_core.asset.manager.AssetManager`: `list_available_assets()`, `verify_assets_for_episode()` (non-raising, returns found/missing), `ensure_assets_for_episode()` (raises `MissingAssetsError` if anything's missing).
- `redline_core.media.manager.MediaManager`: `scan_ingest_for_episode()` (filename-convention matching against `ingest_path`), `organize_bins()` (imports matches into the Resolve media pool via `ResolveAdapter.import_media()`).
- 11 new tests (`test_asset_manager.py`, `test_media_manager.py`), all against temp folders + `MockResolveAdapter` — 30 total, no Resolve/Studio required.
- `ResolveScriptAdapter.duplicate_project()` / `.import_media()` comments updated to reflect they're blocked on a real Studio license, not unbuilt logic — the business logic above is fully built and tested against the mock.

## Unreleased — Phase 2

- `redline_core.episode.manager.EpisodeManager`: `create_episode()`, `get_episode_status()`, `list_episodes()`. Orchestrates naming (from config) → DB row → working folder → duplicated Resolve project, in that order, so a partially-failed create still leaves a trackable DB row.
- `redline_core.db.database.Database.update_episode_paths()`: updates `project_path`/`folder_path` independently, added to support the above.
- `redline_core.episode.exceptions`: `EpisodeAlreadyExistsError`, `EpisodeNotFoundError`.
- Tests (`tests/unit/test_episode_manager.py`) covering create, duplicate-create conflict, status lookup (found/not found), and ordering — all against `MockResolveAdapter`, no Resolve/Studio required.
- **Blocked, not skipped:** real Resolve Studio integration (Phase 1 — `duplicate_project()` implemented for real, verified against a live instance) is paused because the workstation currently only has the free edition of Resolve 21. Everything above still works fully against the mock in the meantime.

## Unreleased — Phase 0

- Initial repo scaffold (`src/redline_core`, `src/mcp_server`, `tests/`, `docs/`, `config/`, `scripts/`).
- `redline_core.config`: pydantic schema (`NamingConfig`, `FolderStructureConfig`, `RenderPresetsConfig`, `PathsConfig`) + YAML loader with example config files.
- `redline_core.db`: SQLite schema (`episodes`, `render_jobs`, `archives`) + thin `Database` wrapper with basic episode CRUD.
- `redline_core.logging`: rotating-file + console logging setup, episode-correlated logger adapter.
- `redline_core.resolve`: `ResolveAdapter` interface, `ResolveScriptAdapter` (real, connection-only so far), `MockResolveAdapter` (fully implemented, used by all unit tests).
- Unit test suite (`tests/unit`) covering config, DB, and the mock Resolve adapter — runs in CI with no Resolve dependency.
- CI skeleton (`.github/workflows/ci.yml`) running `pytest tests/unit` on every push/PR.

**Not yet built:** Episode/Asset/Media/Timeline/Render/Archive managers, the MCP server, and any code path that talks to a *real* running Resolve instance beyond `connect()`. See `docs/ARCHITECTURE.md` §6 for the roadmap.
