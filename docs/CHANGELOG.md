# Changelog

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
