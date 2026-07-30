# Redline OS

Production operating system that automates the episode workflow for Redline Content.

Redline OS **consumes** creative standards owned by the Redline Universe project
(Asset IDs, Showrunner Bible, Broadcast Package V1.0, naming/folder conventions).
It does not define or modify them — see `config/` for how those conventions are
plugged in.

See `docs/ARCHITECTURE.md` for the full system design and `docs/CONFIG.md` for
how to configure a new environment. For interrupted work, partial Resolve state,
and safe retry guidance, see [`docs/RECOVERY.md`](docs/RECOVERY.md). For
verified engineering milestones and live verification history, see
[`MILESTONES.md`](MILESTONES.md). For the Phase 2 Episode Manifest V1 design
package, start with
[`docs/EPISODE_MANIFEST_ARCHITECTURE.md`](docs/EPISODE_MANIFEST_ARCHITECTURE.md).
For the Milestone 10 Persistent Asset Registry V1 architecture draft, start
with [`docs/ASSET_REGISTRY_ARCHITECTURE.md`](docs/ASSET_REGISTRY_ARCHITECTURE.md).

## Status: Phase 11 complete + Phase 12 production hardening in progress

What exists right now:

- `redline_core.config` — YAML config loading + pydantic validation (naming, folders, render presets, paths, assets, timeline template)
- `redline_core.db` — SQLite schema + thin `Database` wrapper (episodes, render jobs, archives)
- `redline_core.logging` — structured logging setup with idempotent console/file handler configuration and typed invalid-level failures
- `redline_core.resolve` — `ResolveAdapter` interface, a real adapter (`connect()`, `duplicate_project()`, `import_media()`, timeline creation, marker insertion, sequential clip placement, render queueing, render status, and render cancellation verified against a live, running DaVinci Resolve Studio instance), and a `MockResolveAdapter` used by all unit tests
- `redline_core.episode` — `EpisodeManager` (create/status/list, plus internal V1 Episode Assembly orchestration)
- `redline_core.asset` — `AssetManager` (verify required assets exist on disk)
- `redline_core.media` — `MediaManager` (scan ingest, import into Resolve media pool)
- `redline_core.timeline` — `TimelineBuilder` (build timeline, apply markers, delegate sequential clip placement)
- `redline_core.manifest` — Episode Manifest V1 loader/validator that reads strict YAML intent and translates validated plans into `EpisodeBuildDefinition` without SQLite or Resolve calls
- `redline_core.render` — `RenderManager` (queue/poll/cancel renders, async by design)
- `redline_core.archive` — `ArchiveManager` (move finished episodes to cold storage)
- `mcp_server` — MCP server exposing all of the above as 18 tools; see `docs/MCP_TOOLS.md`
- `cli` — command-line transport (`redline` console script); `episode` (`create`, `scan-ingest`, `status`, `list`, `organize-bins`, `build-timeline`, `place-clips`, `validate-manifest`, `assemble`), `asset` (`list`, `verify`), and `archive` (`list`, `episode`) resource groups so far. Shares the same composition root as `mcp_server` — see `redline_core.runtime.composition`.

Every manager in the original roadmap (`docs/ARCHITECTURE.md` §6) is built and
tested against `MockResolveAdapter` — the full "create episode → render → archive"
pipeline works end-to-end today. Resolve Studio is now installed, activated, and
`ResolveScriptAdapter.connect()`, `.duplicate_project()`, `.import_media()`,
`.build_timeline()`, `.add_markers()`, sequential `.place_clips()`,
`.queue_render()`, and `.get_render_status()` have been verified against the
real instance. Placement has been verified for still and audio-only media;
linked video/audio cardinality remains a live-test follow-up.
`EpisodeManager.build_episode()` now coordinates explicit media import, timeline
build/marker application, and sequential clip placement through the existing
managers; it is unit-tested and live-verified with deterministic WAV and PNG
media. Episode Manifest V1 has also been live-verified as a read-only manifest
front end that translates into the existing assembly boundary before Resolve is
touched. Controlled V1 assembly testing must run one operation at a time and
avoid reruns after status-update failures until Resolve and SQLite have been
inspected.
Phase 10 implements the real Resolve render lifecycle:
`queue_render()` is implemented as enqueue-only and does not start rendering.
Live verification on Resolve Studio 21.0.3.7 with Python 3.11.9 used the
disposable `redline-os-test-duplicate` project, built-in `YouTube - 720p`
preset, and `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests`
output directory. `AddRenderJob()` returned the actual UUID job ID
`6ac314da-9c99-41eb-bf79-621e5f6b7edc`, which matched the new `JobId` in
`GetRenderJobList()`. Resolve render settings are project-mutating operations,
and queue success followed by job-ID extraction failure has no automatic
rollback. `get_render_status()` is now implemented against the currently loaded
Resolve project: on Resolve Studio 21.0.3.7, `GetRenderJobList()` returns
render-job inventory and metadata but does not include live status.
`GetRenderJobStatus(job_id)` is therefore the authoritative status API. It
returns a dictionary containing `JobStatus` and `CompletionPercentage` for
known jobs and `None` for unknown jobs. `cancel_render()` is implemented for
queued and active renders: queued renders are cancelled by deleting the queued
Resolve job, while active renders are cancelled through project-scoped
`StopRendering()` only after Redline verifies the requested job is the sole
active render. A successfully stopped active job remains in Resolve's render
queue with status `Cancelled`. See
`docs/CHANGELOG.md` for what's verified vs. still mocked.

Episode creation is now also reachable directly from a terminal: `redline
episode create <episode_number>` (see `## Running the CLI` below), a second,
sibling transport alongside the MCP server, sharing the same composition root.

## Episode Manifest V1

Episode Manifest V1 is implemented as a read-only internal API:

```python
from redline_core.manifest import load_manifest, validate_manifest

manifest = load_manifest("episode.yaml")
plan = validate_manifest(manifest, manifest_path="episode.yaml", config=config)
definition = plan.to_build_definition()
```

The loader accepts one YAML document, rejects duplicate mapping keys, rejects
unknown fields, and prohibits unsafe Python object construction. Validation
resolves relative media paths from the manifest directory and requires every
resolved media file to remain under the active loaded `config.paths.ingest_path`
or `config.paths.assets_path`. Pure manifest loading and validation do not call
SQLite, `EpisodeManager`, or DaVinci Resolve. A `ValidatedEpisodePlan` is
deterministic intent at validation time, not a media snapshot or guaranteed
historical reproduction record. It stores immutable manifest-owned marker
values and creates fresh existing `MarkerDefinition` objects only when
translating to `EpisodeBuildDefinition`.

Controlled live verification on 2026-07-27 used a disposable `RLC-E909`
manifest with two expendable media files and two markers, then invoked the
existing `EpisodeManager.build_episode(...)` path against DaVinci Resolve Studio
21.0.3.7. Manifest media and marker order were preserved, the disposable
`RLC-E909_MASTER` project was removed afterward, and no production project or
production media was modified. No render, archive, manifest persistence,
snapshot, checksum, or Build History behavior is part of V1.

## Persistent Asset Registry V1 Architecture

Milestone 10 architecture is drafted in
[`docs/ASSET_REGISTRY_ARCHITECTURE.md`](docs/ASSET_REGISTRY_ARCHITECTURE.md),
[`docs/ASSET_REGISTRY_SCHEMA.md`](docs/ASSET_REGISTRY_SCHEMA.md),
[`docs/ASSET_REGISTRY_LIFECYCLE.md`](docs/ASSET_REGISTRY_LIFECYCLE.md), and
[`docs/ASSET_REGISTRY_VALIDATION.md`](docs/ASSET_REGISTRY_VALIDATION.md).

The design keeps the external Redline Production System authoritative for Asset
IDs and production standards. Redline OS may persist local operational state,
verification results, lifecycle state, path diagnostics, and provenance, but it
must not redefine creative metadata or treat a SQLite row as external approval.
No implementation code, tests, SQLite schema changes, migrations, MCP changes,
or Resolve interaction are part of this architecture draft.

## Requirements

- Python >= 3.10 for everything mock-based (config, DB, managers, MCP tools, test suite).
- **Python 3.11 specifically** for anything that touches the real `ResolveScriptAdapter`.
  DaVinci Resolve's native `fusionscript` scripting module is not built for the
  Python 3.13 ABI — loading it under 3.13 crashes the interpreter with an access
  violation (`0xC0000005`), not a normal Python exception. Python 3.11 is
  confirmed working against Resolve Studio 21.0.3. If you have multiple Pythons
  installed, invoke the 3.11 one explicitly, e.g.:
  `& "C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe" ...`
- DaVinci Resolve **Studio** (paid edition) installed and running, for anything that
  touches `ResolveScriptAdapter` for real — not required for the test suite or for
  trying the MCP server via `--mock-resolve`, both of which run entirely against
  `MockResolveAdapter`.

## First-run operator workflow

Use this path when running Redline OS as an installed package rather than from a
source checkout. The installed-wheel smokes verify this flow outside the
repository without `PYTHONPATH=src`.

```bash
python -m venv redline-venv
source redline-venv/bin/activate        # or redline-venv\Scripts\activate on Windows
pip install redline_os-*.whl             # or install the published package when available

export REDLINE_CONFIG_DIR=/path/to/config
export REDLINE_DB_PATH=/path/to/redline.db
export REDLINE_LOG_DIR=/path/to/logs
```

On Windows PowerShell, set the same variables with `$env:REDLINE_CONFIG_DIR`,
`$env:REDLINE_DB_PATH`, and `$env:REDLINE_LOG_DIR`.

`REDLINE_CONFIG_DIR` must point at the directory containing Redline OS's YAML
configuration files (`naming.yaml`, `paths.yaml`, `assets.yaml`,
`render_presets.yaml`, `folder_structure.yaml`, and
`timeline_template.yaml`). `REDLINE_DB_PATH` chooses the SQLite database file
used by commands and MCP tools that need persistence. `REDLINE_LOG_DIR` chooses
where `redline_os.log` is created.

The installed package includes the database schema resource. No
`scripts/bootstrap_db.py` run and no `PYTHONPATH=src` setting is required for an
installed operator. Commands and startup paths that need SQLite initialize the
schema through the installed `redline_core.db` package boundary.

Verify the installed CLI with a read-only command that needs only config:

```bash
redline asset list
```

Verify installed MCP startup with mock Resolve first:

```bash
redline-mcp --mock-resolve
```

`--mock-resolve` is appropriate for first startup, MCP client wiring, config
checks, logging checks, and workflows that should not touch DaVinci Resolve.
Use a real Resolve session only when running operations that require Resolve
state, such as episode creation, media import, timeline work, render queueing,
render status, or cancellation. Real Resolve usage also requires Python 3.11
and the Resolve scripting environment variables described in `docs/CONFIG.md`.

## Developer setup

Use this path when working from a source checkout.

```bash
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
cp .env.example .env             # edit paths for your machine
python scripts/bootstrap_db.py   # checkout helper that creates redline.db with the schema applied
```

The editable install and repository scripts are development conveniences. They
are not required for an installed operator workflow.

## Logging diagnostics

`redline` and `redline-mcp` configure logging at startup through
`redline_core.logging.setup.configure_logging()`. By default, Redline OS logs at
`INFO` to the console and to `./logs/redline_os.log`, creating the log directory
if needed. Set `REDLINE_LOG_DIR` to choose a different log directory and
`REDLINE_LOG_LEVEL` to one of `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

Invalid log levels, log-directory creation failures, and log-file creation
failures stop startup visibly instead of falling back silently. If a log file is
not created, check the terminal error first, then confirm the configured
`REDLINE_LOG_DIR` can be created by the same OS user running the command.

## Running tests

```bash
pytest tests/unit
```

Tests under `tests/integration` require a live, running DaVinci Resolve Studio
instance and are excluded from the default `pytest` run and from CI (see
`pyproject.toml`'s `resolve` marker).

## Running the MCP server

```bash
redline-mcp --mock-resolve   # installed operator path, no Studio needed
redline-mcp                  # installed operator path, once you have Resolve Studio
```

See `docs/MCP_TOOLS.md` for the full tool reference.

## Running the CLI

```bash
redline episode create 1 --mock-resolve         # try it now, no Studio needed
redline episode create 1                        # once you have Resolve Studio
redline episode scan-ingest 1 --mock-resolve    # list ingest-folder files matching episode 1 (read-only)
redline episode status 1 --mock-resolve         # show an episode's persisted state (read-only)
redline episode list --mock-resolve             # list every tracked episode (read-only)
redline episode organize-bins 1 --mock-resolve  # scan ingest + import matches into a Resolve media pool bin
redline episode build-timeline 1 --mock-resolve # build the episode's timeline and apply configured markers
redline episode place-clips 1 clip-1 clip-2 --mock-resolve # place already-imported clips onto the timeline
redline episode validate-manifest episode.yaml   # validate an Episode Manifest V1 file (read-only, no Resolve/DB needed)
redline episode assemble episode.yaml --mock-resolve            # assemble an already-created episode from a manifest
redline episode assemble episode.yaml --mock-resolve --force    # retry a failed/unresolved-claim episode -- inspect first
redline asset list                               # list config/assets.yaml (read-only, no Resolve/DB needed)
redline asset verify RLG-001 RLG-003             # verify specific assets (omit for the required_for_episode default)
redline archive list                             # list every archived episode (read-only, no Resolve needed)
redline archive episode RLC-E025                 # move that episode's working folder to archive storage
```

From a development checkout, install editable with `pip install -e .` before
using the `redline` console script.

`episode_number` is the plain integer `EpisodeManager.create_episode()`
already expects — the real episode ID (e.g. `RLC-E001`) is derived from
`config/naming.yaml`. `episode scan-ingest` is a thin, read-only wrapper over
the existing `MediaManager.scan_ingest_for_episode()` — it matches files by
episode-ID substring in the filename regardless of extension, and performs
no classification, deduplication, copying, moving, importing, or
registration. `episode status` is a thin, read-only wrapper over the
existing `EpisodeManager.get_episode_status()` — it displays only what's
already persisted (DB ID, status, folder/project paths, timestamps), with no
computed health checks, readiness inference, media counts, or asset
verification. `episode list` is a thin, read-only wrapper over the existing
`EpisodeManager.list_episodes()` — every tracked episode, ordered by
episode number, with no filtering, pagination, or alternate sort order
(none of that exists in the underlying method either).

`episode organize-bins <episode_number> [--bin-name footage]` is a thin
wrapper over the existing `MediaManager.organize_bins()` — it scans the
ingest folder for files matching the episode (same matching as
`scan-ingest`) and, if any match, imports them into the named bin in the
episode's Resolve project media pool. `--bin-name` defaults to
`footage`, matching the manager's own default; passed through unchanged
when overridden. Finding zero matching files is a successful result
(`Clips added: 0`), not an error — no files to import is not a failure
condition. On success, the command reports the episode, its Resolve
project, the bin name, the number of clips added, and their Resolve clip
IDs. Exit code is `0` on success (including zero matches), `1` on an
unknown episode or a Resolve-side import failure. Same `ApplicationServices`
composition path as `episode create`/`scan-ingest`/`status`/`list` — needs
Resolve, so `--mock-resolve` remains relevant here too.

`episode build-timeline <episode_number>` is a thin wrapper over the
existing `TimelineBuilder.build_timeline_for_episode()` — it builds the
episode's timeline and applies the configured marker set from
`config/timeline_template.yaml`. No arguments beyond the episode number:
the timeline name and marker set are both derived entirely from config,
the same way every other value the CLI doesn't ask for is. Zero
configured markers is a successful result (`Markers applied: 0`), not an
error. On success, the command reports the episode, its Resolve project,
the timeline name, and the number of markers applied. Exit code is `0`
on success, `1` on an unknown episode or a Resolve-side failure. Same
`ApplicationServices` composition path as every other `episode` action.

`episode place-clips <episode_number> [clip_id ...]` is a thin wrapper
over the existing `TimelineBuilder.place_clips()` — it places the given
Resolve media pool clip IDs (e.g. the ones printed by a prior
`organize-bins` run) onto the episode's timeline, in the order given.
The timeline must already exist (run `build-timeline` first). Omitting
every `clip_id` is a successful result (`Clips placed: 0`), not an
error. On success, the command reports the episode, its Resolve project
and timeline, how many clips were placed, and each clip ID paired with
the timeline item Resolve created for it. Exit code is `0` on success
(including zero clips), `1` on an unknown episode, a project or timeline
that doesn't exist, or another Resolve-side failure. Same
`ApplicationServices` composition path as every other `episode` action.
README documents operator usage and output only. Append-only and
duplicate-placement semantics remain architecture documentation, not
command help text.

`episode validate-manifest <manifest_path>` is a thin, read-only wrapper
over the existing `redline_core.manifest.load_manifest()` and
`.validate_manifest()` — it loads and validates an Episode Manifest V1
YAML file and reports the episode ID, bin name, resolved media file
paths/count, and markers/count it found, without ever connecting to
Resolve or opening a database connection. Unlike every other `episode`
action, it does not take `episode_number`: the episode identity comes
from inside the manifest file itself (`episode.id`). On success, the
command reports what a subsequent assembly of this manifest would use;
on failure, it reports the exact underlying manifest error unchanged.
Exit code is `0` for a manifest that validates successfully, `1` for any
load, parse, schema, or path-validation failure. No `--mock-resolve` flag
is needed or read by this command, since it never touches Resolve.

`episode assemble <manifest_path> [--force]` is a thin, mutating wrapper
over the existing `load_manifest()` -> `validate_manifest()` ->
`.to_build_definition()` -> `EpisodeManager.build_episode()` pipeline — it
loads and validates an Episode Manifest V1 file, then assembles the
already-created episode it describes (media import, timeline build,
marker application, sequential clip placement), the same way
`validate-manifest` previews it but without touching Resolve or SQLite.
`--force` maps directly onto `build_episode()`'s transport-neutral
`allow_unsafe_retry` parameter; this command performs no eligibility
check or retry-policy decision of its own (see `docs/adr/ADR-0001-episode-assembly-retry-policy.md`
— `EpisodeManager` is the sole authority on whether a retry is allowed,
via an atomic, persisted assembly claim rather than any transport-side
guess). Ordinary retries are blocked once an episode is `Failed` or has
an active/unresolved assembly claim; `--force` overrides that block, but
never for a terminal status (`Assembled`, `Render Queued`, `Rendered`,
`Archived`) — those are never retryable, with or without `--force`.
Passing `--force` always prints a warning before the result, on both
success and failure, since determining whether force was actually needed
would itself require the CLI to inspect eligibility, which this design
forbids: **`--force` does not roll back, verify, or repair any prior
partial Resolve mutation.** Inspect the Resolve project and the SQLite
`episodes` row for the episode before retrying. Exit code is `0` on
successful assembly, `1` on any manifest error or a blocked/failed
attempt. Same `ApplicationServices` composition path as every other
mutating `episode` action.

`asset list` is the CLI's second resource group and a thin, read-only
wrapper over the existing `AssetManager.list_available_assets()` — every
asset registered in `config/assets.yaml`, in file declaration order. Unlike
every `episode` command, it needs **only** config: no SQLite connection, no
Resolve connection at all, so it works even without `--mock-resolve` and
without Resolve Studio installed or running.

`asset verify` is a thin, read-only wrapper over the existing
`AssetManager.verify_assets_for_episode()`. Despite its name, that method
has no episode parameter — it only accepts an optional list of asset IDs,
defaulting to `config/assets.yaml`'s `required_for_episode` set when
omitted. `redline asset verify` was originally sketched as taking an
`<episode_number>` argument; architecture review found no episode-aware
call site anywhere in the codebase, so the command matches the real
contract instead: `redline asset verify [asset_id ...]`, no episode
argument. Exit code is `0` for any completed verification, including one
that finds missing assets — a CLI "check" and an operation failure are
different things here, matching the existing MCP tool's `success: True`-
always contract. Same `CoreServices` composition path as `asset list`.

`archive list` is the CLI's third resource group and a thin, read-only
wrapper over the existing `ArchiveManager.list_archives()` — every
archived episode, in whatever order the DB returns (`ORDER BY
archived_at`, no secondary sort key). It needs config **and** a connected
SQLite DB, but never Resolve, so it works without `--mock-resolve` and
without Resolve Studio installed or running, the same as `asset list`.

`redline archive episode <episode_id>` moves that episode's working folder
to archive storage (`config/paths.yaml`'s `archive_path`), records the
archive, and marks the episode `Archived`. `episode_id` is the same
identifier shown by `episode list`/`episode status` (e.g. `RLC-E025`), not
the plain episode number every `episode` command takes — a thin wrapper
over the existing `ArchiveManager.archive_episode()`, which itself only
ever accepted that identifier. On success, the command reports the three
fields on the returned archive record (episode ID, archive path, archived-
at timestamp). Exit code is `0` on success, `1` on failure — an unknown
episode, an already-archived episode, a missing working folder, or an
existing archive-destination conflict are each reported with the
underlying error message unchanged. Same `PersistenceServices`
composition path as `archive list`.

CLI code is organized one module per resource group: `cli/main.py` is the
thin entry point (parser assembly, logging setup, dispatch), and
`cli/episode_commands.py`/`cli/asset_commands.py`/`cli/archive_commands.py`
hold each resource group's action logic. Most `episode` commands are built from
`redline_core.runtime.composition.ApplicationServices` (full DB + Resolve
runtime); the one exception is `episode validate-manifest`, built from
`CoreServices` since it never touches SQLite or Resolve. `asset` commands are built from `CoreServices` — configuration-
backed services requiring neither SQLite nor Resolve; `archive` commands
are built from `PersistenceServices` — configuration-backed services
requiring SQLite persistence, but not Resolve. Neither `CoreServices` nor
`PersistenceServices` is a general layer every future command will use —
`main.py` picks the right one per resource group rather than building all
three unconditionally.

## Repository layout

```
src/redline_core/   # all business logic (transport-agnostic)
src/mcp_server/      # MCP tool layer (thin wrappers only)
tests/unit/          # fast tests against MockResolveAdapter, run in CI
tests/integration/   # requires real Resolve, run manually
config/              # YAML config (naming, folders, render presets, paths, assets, timeline template)
docs/                # architecture, config, MCP tools, changelog
scripts/             # env setup, DB bootstrap
```
