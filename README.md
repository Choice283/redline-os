# Redline OS

Production operating system that automates the episode workflow for Redline Content.

Redline OS **consumes** creative standards owned by the Redline Universe project
(Asset IDs, Showrunner Bible, Broadcast Package V1.0, naming/folder conventions).
It does not define or modify them — see `config/` for how those conventions are
plugged in.

See `docs/ARCHITECTURE.md` for the full system design and `docs/CONFIG.md` for
how to configure a new environment. For verified engineering milestones and live
verification history, see [`MILESTONES.md`](MILESTONES.md). For the Phase 2
Episode Manifest V1 design package, start with
[`docs/EPISODE_MANIFEST_ARCHITECTURE.md`](docs/EPISODE_MANIFEST_ARCHITECTURE.md).
For the Milestone 10 Persistent Asset Registry V1 architecture draft, start
with [`docs/ASSET_REGISTRY_ARCHITECTURE.md`](docs/ASSET_REGISTRY_ARCHITECTURE.md).

## Status: Phase 7 complete (full pipeline, mock-tested) + Phase 1 real Resolve connection verified

What exists right now:

- `redline_core.config` — YAML config loading + pydantic validation (naming, folders, render presets, paths, assets, timeline template)
- `redline_core.db` — SQLite schema + thin `Database` wrapper (episodes, render jobs, archives)
- `redline_core.logging` — structured logging setup
- `redline_core.resolve` — `ResolveAdapter` interface, a real adapter (`connect()`, `duplicate_project()`, `import_media()`, timeline creation, marker insertion, and sequential clip placement verified against a live, running DaVinci Resolve Studio 21.0.3 instance; render calls still stubbed, see Phase 1 note below), and a `MockResolveAdapter` used by all unit tests
- `redline_core.episode` — `EpisodeManager` (create/status/list, plus internal V1 Episode Assembly orchestration)
- `redline_core.asset` — `AssetManager` (verify required assets exist on disk)
- `redline_core.media` — `MediaManager` (scan ingest, import into Resolve media pool)
- `redline_core.timeline` — `TimelineBuilder` (build timeline, apply markers, delegate sequential clip placement)
- `redline_core.manifest` — Episode Manifest V1 loader/validator that reads strict YAML intent and translates validated plans into `EpisodeBuildDefinition` without SQLite or Resolve calls
- `redline_core.render` — `RenderManager` (queue/poll/cancel renders, async by design)
- `redline_core.archive` — `ArchiveManager` (move finished episodes to cold storage)
- `mcp_server` — MCP server exposing all of the above as 15 tools; see `docs/MCP_TOOLS.md`
- `cli` — command-line transport (`redline` console script); currently one command, `redline episode create <episode_number>` (`--mock-resolve` supported). Shares the same composition root as `mcp_server` — see `redline_core.runtime.composition`.

Every manager in the original roadmap (`docs/ARCHITECTURE.md` §6) is built and
tested against `MockResolveAdapter` — the full "create episode → render → archive"
pipeline works end-to-end today. Resolve Studio is now installed, activated, and
`ResolveScriptAdapter.connect()`, `.duplicate_project()`, `.import_media()`,
`.build_timeline()`, `.add_markers()`, and sequential `.place_clips()` have been
verified against the real instance. Placement has been verified for still and
audio-only media; linked video/audio cardinality remains a live-test follow-up.
`EpisodeManager.build_episode()` now coordinates explicit media import, timeline
build/marker application, and sequential clip placement through the existing
managers; it is unit-tested and live-verified with deterministic WAV and PNG
media. Episode Manifest V1 has also been live-verified as a read-only manifest
front end that translates into the existing assembly boundary before Resolve is
touched. Controlled V1 assembly testing must run one operation at a time and
avoid reruns after status-update failures until Resolve and SQLite have been
inspected.
Still open:
implementing the remaining render methods
(`queue_render`, `get_render_status`, `cancel_render`) for real, one at a time,
verified against the live instance. See `docs/CHANGELOG.md` for what's verified
vs. still mocked.

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

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
cp .env.example .env             # edit paths for your machine
python scripts/bootstrap_db.py   # creates redline.db with the schema applied
```

## Running tests

```bash
pytest tests/unit
```

Tests under `tests/integration` require a live, running DaVinci Resolve Studio
instance and are excluded from the default `pytest` run and from CI (see
`pyproject.toml`'s `resolve` marker).

## Running the MCP server

```bash
pip install -e ".[mcp]"
python -m mcp_server.server --mock-resolve   # try it now, no Studio needed
python -m mcp_server.server                  # once you have Resolve Studio
```

See `docs/MCP_TOOLS.md` for the full tool reference.

## Running the CLI

```bash
pip install -e .
redline episode create 1 --mock-resolve         # try it now, no Studio needed
redline episode create 1                        # once you have Resolve Studio
redline episode scan-ingest 1 --mock-resolve    # list ingest-folder files matching episode 1 (read-only)
redline episode status 1 --mock-resolve         # show an episode's persisted state (read-only)
redline episode list --mock-resolve             # list every tracked episode (read-only)
```

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

CLI code is organized one module per resource group: `cli/main.py` is the
thin entry point (parser assembly, logging setup, dispatch), and
`cli/episode_commands.py` holds every `episode` action's logic. A future
resource group (e.g. `asset`) would get its own sibling module of the same
shape.

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
