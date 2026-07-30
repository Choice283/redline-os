# MCP Tools Reference

Redline OS's MCP server (`src/mcp_server`) exposes the Episode/Asset/Media/Timeline/Render/Archive managers (Phases 2-7) as 18 MCP tools - the full pipeline described in `docs/ARCHITECTURE.md` section 4, from "create an episode" through "archive it once it's rendered."

## Running the server

Installed operator path:

```bash
# Against a real, running DaVinci Resolve Studio instance:
redline-mcp

# Or, before you have Studio installed, against the in-memory mock
# (real for config/DB/folders, mocked for anything that would touch Resolve):
redline-mcp --mock-resolve
```

Development checkout path:

```bash
pip install -e ".[mcp]"
python -m mcp_server.server --mock-resolve
```

Transport is `stdio` (see `docs/ARCHITECTURE.md` section 5 for why) - point your MCP client (Claude Desktop, Claude Code, etc.) at this command directly.

## Design rules every tool follows

- **Thin.** Every tool is a one-line call into `redline_core` - zero business logic lives in `src/mcp_server`. The underlying logic functions (`_create_episode`, `_verify_assets_for_episode`, etc. in each `tools/*.py` module) have no dependency on the `mcp` package and are covered by `tests/unit/test_mcp_tools.py`.
- **Structured responses.** Tools return deterministic dictionaries. Tools catch the specific exceptions their manager can raise where that is the established domain pattern (`EpisodeAlreadyExistsError`, `EpisodeNotFoundError`, etc.); timeline-builder validation and Resolve boundary errors propagate from the neighboring timeline tools instead of being broadly wrapped.
- **One shared context.** All tools are bound to a single `AppContext` (one Config, one DB connection, one Resolve adapter) built once at server startup - see `src/mcp_server/context.py`. Resolve is single-instance and stateful, so there is deliberately no per-call connection.

## Tools

### Episode

| Tool | Args | Returns |
|---|---|---|
| `create_episode` | `episode_number: int` | New episode: DB record, working folder, duplicated Resolve project. |
| `get_episode_status` | `episode_number: int` | Current tracked status of an episode. |
| `list_episodes` | - | Every tracked episode, ordered by episode number. |
| `validate_manifest` | `manifest_path: str` | Loads and validates an Episode Manifest V1 file. Returns `valid`, `episode_id`, `bin_name`, resolved `media_paths`/`media_count`, and `markers`/`marker_count`. Validation failures return `success: false` with `error`. Side effects: none; no SQLite or Resolve access. Policy owner: `redline_core.manifest`. |
| `assemble_episode` | `episode_id: str, media_paths: list[str], markers: list[dict] \| None = None, bin_name: str = "footage", allow_unsafe_retry: bool = False` | Assembles an already-created episode from explicit ordered media paths. Returns `episode_id`, `project_name`, `timeline_name`, `media_paths`, `media_ids`, `markers_applied`, and `timeline_item_ids`. `EpisodeBuildError` failures return `success: false` with `error`; unexpected errors propagate. Side effects: the existing assembly path may import media, create/update a timeline, place clips, and update SQLite status. Policy owner: `EpisodeManager.build_episode`; assembly order, validation, retry behavior, persistence, and Resolve interactions remain owned by the core assembly path. |

### Asset

| Tool | Args | Returns |
|---|---|---|
| `list_available_assets` | - | Every asset registered in `config/assets.yaml`. |
| `verify_assets_for_episode` | `asset_ids: list[str] \| None` | Which required assets are present on disk vs. missing. Omit `asset_ids` to use the configured default set. |

### Media

| Tool | Args | Returns |
|---|---|---|
| `scan_ingest_for_episode` | `episode_id: str` | Ingest files matching this episode ID, without importing anything. |
| `organize_bins` | `project_name: str, episode_id: str, bin_name: str = "footage"` | Scans ingest and imports matches into the Resolve project's media pool. |

### Timeline

| Tool | Args | Returns |
|---|---|---|
| `build_timeline` | `project_name: str, episode_id: str` | Builds the timeline and applies the standard marker set from `config/timeline_template.yaml`. |
| `add_markers` | `project_name: str, timeline_name: str, markers: list[dict] \| None` | Applies markers to an existing timeline. Each marker dict needs `frame`/`color`/`name` (`note` optional). Omit `markers` to reapply the configured default set. |
| `place_clips` | `project_name: str, timeline_name: str, clip_ids: list[str]` | Places already-imported clips on an existing timeline. Returns `timeline_item_ids` in requested clip order and `placed_count`. Basic transport shape is validated before delegation; timeline-builder domain errors propagate like neighboring timeline tools. Side effects: appends clips to the Resolve timeline. Policy owner: `TimelineBuilder.place_clips` and the Resolve adapter boundary. |

### Render

Async by design (see `docs/ARCHITECTURE.md` sections 5 and 9) - `queue_render` returns immediately with a job ID; poll `get_render_status` separately rather than blocking on a multi-hour render.

| Tool | Args | Returns |
|---|---|---|
| `queue_render` | `episode_id: str, preset_name: str` | Queues a render job. Returns immediately with a `resolve_job_id`. |
| `get_render_status` | `job_id: int` | Current status, synced from Resolve's render queue. Bumps the episode to `rendered` on completion. |
| `cancel_render` | `job_id: int` | Cancels a queued or in-progress render job. |
| `list_render_jobs_for_episode` | `episode_id: str` | Every render job queued for an episode. |

### Archive

| Tool | Args | Returns |
|---|---|---|
| `archive_episode` | `episode_id: str` | Moves the episode's working folder to `paths.archive_path` and marks it `archived`. Does not gate on render status. |
| `list_archives` | - | Every archived episode. |

## Verified

`create_server(use_mock_resolve=True)` has been smoke-tested end-to-end: server construction, `list_tools()` (all 18 tools), and real `call_tool()` round-trips for `create_episode`, `list_episodes`, `verify_assets_for_episode`, and `queue_render` all work through the real `mcp` package (not just the underlying `_*` functions). Phase 10 live verification completed the real Resolve render adapter lifecycle (`queue_render`, `get_render_status`, and `cancel_render`); use mock Resolve for MCP startup checks and real Resolve only for workflows that intentionally touch Resolve state.
