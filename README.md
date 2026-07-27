# Redline OS

Production operating system that automates the episode workflow for Redline Content.

Redline OS **consumes** creative standards owned by the Redline Universe project
(Asset IDs, Showrunner Bible, Broadcast Package V1.0, naming/folder conventions).
It does not define or modify them — see `config/` for how those conventions are
plugged in.

See `docs/ARCHITECTURE.md` for the full system design and `docs/CONFIG.md` for
how to configure a new environment.

## Status: Phase 7 complete (full pipeline, mock-tested) + Phase 1 real Resolve connection verified

What exists right now:

- `redline_core.config` — YAML config loading + pydantic validation (naming, folders, render presets, paths, assets, timeline template)
- `redline_core.db` — SQLite schema + thin `Database` wrapper (episodes, render jobs, archives)
- `redline_core.logging` — structured logging setup
- `redline_core.resolve` — `ResolveAdapter` interface, a real adapter (`connect()` and `duplicate_project()` verified against a live, running DaVinci Resolve Studio 21.0.3 instance; `import_media()` implemented and unit-tested against fake Resolve API objects; timeline/render calls still stubbed, see Phase 1 note below), and a `MockResolveAdapter` used by all unit tests
- `redline_core.episode` — `EpisodeManager` (create/status/list)
- `redline_core.asset` — `AssetManager` (verify required assets exist on disk)
- `redline_core.media` — `MediaManager` (scan ingest, import into Resolve media pool)
- `redline_core.timeline` — `TimelineBuilder` (build timeline, apply markers)
- `redline_core.render` — `RenderManager` (queue/poll/cancel renders, async by design)
- `redline_core.archive` — `ArchiveManager` (move finished episodes to cold storage)
- `mcp_server` — MCP server exposing all of the above as 15 tools; see `docs/MCP_TOOLS.md`

Every manager in the original roadmap (`docs/ARCHITECTURE.md` §6) is built and
tested against `MockResolveAdapter` — the full "create episode → render → archive"
pipeline works end-to-end today. Resolve Studio is now installed, activated, and
`ResolveScriptAdapter.connect()`, `.duplicate_project()`, and `.import_media()`
have been verified against the real instance. Still open: implementing the
remaining `ResolveScriptAdapter` methods (`build_timeline`, `add_markers`,
`queue_render`, `get_render_status`, `cancel_render`) for real, one at a time,
verified against the live instance. See `docs/CHANGELOG.md` for what's verified
vs. still mocked.

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
