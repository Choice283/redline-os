# Redline OS

Production operating system that automates the episode workflow for Redline Content.

Redline OS **consumes** creative standards owned by the Redline Universe project
(Asset IDs, Showrunner Bible, Broadcast Package V1.0, naming/folder conventions).
It does not define or modify them — see `config/` for how those conventions are
plugged in.

See `docs/ARCHITECTURE.md` for the full system design and `docs/CONFIG.md` for
how to configure a new environment. For production workstation deployment, see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). For interrupted work, partial
Resolve state, and safe retry guidance, see
[`docs/RECOVERY.md`](docs/RECOVERY.md). For verified engineering milestones and
live verification history, see [`MILESTONES.md`](MILESTONES.md). For the Phase 2
Episode Manifest V1 design package, start with
[`docs/EPISODE_MANIFEST_ARCHITECTURE.md`](docs/EPISODE_MANIFEST_ARCHITECTURE.md).
For the Milestone 10 Persistent Asset Registry V1 architecture draft, start
with [`docs/ASSET_REGISTRY_ARCHITECTURE.md`](docs/ASSET_REGISTRY_ARCHITECTURE.md).
For the Phase 13 build command contract, see
[`docs/BUILD_COMMAND_SPEC.md`](docs/BUILD_COMMAND_SPEC.md).
For the current intentional project pause boundary, see
[`docs/REDLINE_OS_PAUSE_CHECKPOINT_2026-08-12.md`](docs/REDLINE_OS_PAUSE_CHECKPOINT_2026-08-12.md).
For the V1 release-candidate closure record — V1 status, CI exception
classification, and deferred V2 work — see
[`docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md`](docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md).

## Status: V1 complete; RLC-E9901 production render lifecycle verified (RLC-E9001 queue-acceptance experiment separately unresolved, not a V1 blocker)

Phase 14 (First Live Episode) has proven the live queue path fails closed
with consistent postflight state across three controlled live attempts
against a disposable Broadcast Master episode, but has not yet observed
Resolve accept that specific queue request: Resolve returned an empty
`AddRenderJob()` result and no new queue job ID was observed. Missions 39D and
39E are formally closed, but Phase 14 remains open and blocked. Earlier
development live-verified the real Resolve adapter's direct-ID queue-success
path using the `YouTube - 720p` preset; that earlier result did not validate
the later Mission 39B Broadcast Master production workflow. No further live
queue submission is authorized without a new root-cause investigation, a
separately reviewed attempt contract, and fresh explicit founder
authorization. Phase 14 Test D subsequently found that removing a Control
timeline's sole video TimelineItem, and nothing else, made a previously
queue-accepting timeline non-queueable; `RenderManager` now runs a
renderability preflight that fails closed with `RenderTimelineNotRenderableError`
before any SQLite claim or Resolve queue mutation when a preset requiring
video (`broadcast_master`) targets a timeline with zero video TimelineItems.
This is a repository-only safety capability and does not by itself resolve
production Broadcast Master queue acceptance. A follow-up repository-only
investigation found the underlying observability gap upstream of that
preflight: no assembly gate before it ever inspected actual video-track
content. `EpisodeManager.build_episode()` now records a read-only
post-placement `video_item_count` observation (reusing the same Resolve
inspection call) — a `0` count is a valid, non-rejecting V1 result and does
not mean assembly failed; `ASSEMBLED` means requested media passed the
existing import/placement contracts, not that the timeline is renderable by
every preset. See `docs/ROADMAP.md` for the full Phase 14 status.

A read-only RLC-E9901 Broadcast Master preflight tooling layer has passed
independent source review (Rev5) — see `docs/RLC_E9901_BROADCAST_MASTER_PREFLIGHT_CONTRACT.md`
for the complete contract. It does not queue or start a render. Live
execution has not yet been authorized or performed.

An RLC-E9901 Broadcast Master one-shot production queue-attempt harness has
passed independent source review (Rev7) — see
`docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md`, which is authoritative for its
full contract. Its sole mutation-bearing operation is exactly one real
production `render queue` CLI process launch. Live queue execution through
this specific harness script remains separately unauthorized and unperformed.

**The two paragraphs above describe the state before 2026-08-11 and remain
accurate for the RLC-E9001 disposable experiment and for these specific
review-only tooling scripts. They no longer describe RLC-E9901's own
production render lifecycle**, which was separately executed through the
existing production CLI (`render start`, not the harness scripts above) and
completed: queue acceptance was independently Resolve-side confirmed, exactly
one authorized `start_render()` invocation ran successfully, the render
reconciled to `complete`, and the rendered master (`RLC-E9901_MASTER.mov`,
132,364,925 bytes) was independently re-verified by SHA-256 outside this
repository. See `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md` §4 for the full
evidence record and `docs/ROADMAP.md`'s Phase 14 section for the exact
correction entry. RLC-E9001's own queue-acceptance failures are unaffected
by this and remain a separate, unresolved, non-V1-blocking thread.

What exists right now:

- `redline_core.config` — YAML config loading + pydantic validation (naming, folders, render presets, paths, assets, timeline template)
- `redline_core.db` — SQLite schema + thin `Database` wrapper (episodes, render jobs, archives)
- `redline_core.logging` — structured logging setup with idempotent console/file handler configuration and typed invalid-level failures
- `redline_core.resolve` — `ResolveAdapter` interface, a real adapter (`connect()`, `duplicate_project()`, `import_media()`, timeline creation, marker insertion, sequential clip placement, render queueing, render status, and render cancellation verified against a live, running DaVinci Resolve Studio instance; render start (`start_render()`) constructed, independently reviewed and corrected (Rev2, Rev3), unit-tested, and live-verified for the RLC-E9901 production render on 2026-08-11 — see `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md` §4), and a `MockResolveAdapter` used by all unit tests
- `redline_core.episode` — `EpisodeManager` (create/status/list, plus internal V1 Episode Assembly orchestration)
- `redline_core.asset` — `AssetManager` (verify required assets exist on disk)
- `redline_core.media` — `MediaManager` (scan ingest, import into Resolve media pool)
- `redline_core.timeline` — `TimelineBuilder` (build timeline, apply markers, delegate sequential clip placement)
- `redline_core.manifest` — Episode Manifest V1 loader/validator that reads strict YAML intent and translates validated plans into `EpisodeBuildDefinition` without SQLite or Resolve calls
- `redline_core.render` — `RenderManager` (queue/poll/cancel renders, async by design)
- `redline_core.archive` — `ArchiveManager` (move finished episodes to cold storage)
- `redline_core.build` — Phase 13 target parsing, deterministic manifest resolution, and transport-neutral `BuildOrchestrator`
- `redline_core.workflows` — transport-neutral `BuildRenderWorkflow` sequencing a successful build result into one render queue request
- `mcp_server` — MCP server exposing all of the above as 20 tools; see `docs/MCP_TOOLS.md`
- `cli` — command-line transport (`redline` console script); top-level `build`, `episode` (`create`, `scan-ingest`, `status`, `list`, `organize-bins`, `build-timeline`, `place-clips`, `validate-manifest`, `assemble`), `render` (`queue`, `status`, `list`, `cancel`), `asset` (`list`, `verify`), and `archive` (`list`, `create`, `verify`) resource groups so far. Shares the same composition root as `mcp_server` — see `redline_core.runtime.composition`.

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

Local workspace state stays outside version control. `.claude/` is local
workstation tool state, and `_episodes/` is the default generated episode
working root from `config/folder_structure.yaml`; both are ignored and must not
be staged as repository content.

### Git tooling in sandboxed or FUSE-mounted checkouts

If working from a FUSE-mounted or otherwise sandboxed checkout, a stale,
zero-byte `.git/index.lock` or `.git/HEAD.lock` can appear during `git
add`/`git commit` and cause `rm` to fail with "Operation not permitted."
Confirm no real git process is running, then move the lock file aside (for
example, rename it to `.git/index.lock.bak`) rather than deleting it, and
retry the same git command. "unable to unlink tmp_obj" warnings during commit
on such mounts are typically harmless if the commit still completes — check
the exit code and resulting commit hash, not the warning text.

Some sandboxed environments cannot push or fetch over SSH (no `known_hosts`
entry for the remote host); this is an environment limitation, not a
repository problem — push from a machine with working SSH access instead.

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
redline --mock-resolve build Episode_0001                     # parse target, resolve manifest, create/reuse, assemble
redline build Episode_0001 --manifest manifests/episode.yaml   # use an explicit manifest path
redline build Episode_0001 --force                            # pass allow_unsafe_retry=True to assembly policy
redline --mock-resolve render queue RLC-E001 broadcast_master  # queue an existing assembled episode for render
redline --mock-resolve render status 7                         # sync and show a Redline render job by DB ID
redline --mock-resolve render list RLC-E001                    # list render jobs for one episode
redline --mock-resolve render cancel 7                         # cancel one queued or in-progress render job
redline --mock-resolve render start 7                          # start rendering an already-queued render job
redline asset list                               # list config/assets.yaml (read-only, no Resolve/DB needed)
redline asset verify RLG-001 RLG-003             # verify specific assets (omit for the required_for_episode default)
redline archive list                             # list every archived episode (read-only, no Resolve needed)
redline archive create RLC-E025                  # build, verify, and commit a Rev1 archive package (non-destructive)
redline archive create RLC-E025 --render-job-id 7 --manifest legacy.yaml  # explicit render selection / legacy fallback
redline archive verify RLC-E025                  # prove a committed Rev1 archive package is still intact (read-only)
redline archive recover RLC-E025 --archive-id RLC-E025-a1-72c51de17a42  # register a VERIFIED_UNREGISTERED package
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

`build <target> [--manifest path] [--force]` is the canonical production
composition command for an episode target such as `Episode_0001`. It is a
thin CLI wrapper over `BuildOrchestrator`: the CLI passes the target
string unchanged, passes `Path.cwd()` as the working directory, passes
`--manifest` through unchanged when supplied, and leaves target parsing,
manifest path selection, manifest loading, manifest validation, identity
checking, episode create/reuse policy, and assembly retry policy with the
existing build and episode layers.

Without `--manifest`, the build orchestrator resolves the manifest
deterministically from the current working directory as `Episode_0001.yaml`
first, then `Episode_0001.yml`. With `--manifest`, that explicit path is
used instead. `--force` maps only to `allow_unsafe_retry=True` on the
existing assembly policy; it does not overwrite, roll back, repair, ignore
manifest validation, recreate episodes, queue renders, or archive results.

A successful build exits `0` and reports the assembled episode identity and
counts:

```text
Build complete

Target: Episode_0001
Episode number: 1
Episode ID: RLC-E001
Manifest: C:\production\Episode_0001.yaml
Episode: created
Final state: assembled
Project: RLC-E001_MASTER
Timeline: RLC-E001_TIMELINE
Media count: 2
Markers applied: 3
Clips placed: 2
Warnings: none

Build completed through assembly.
Render queued: no
Archive performed: no
```

Known build failures exit `1` and print a deterministic failure message to
stderr without a normal traceback. Unexpected startup or internal failures
continue through the existing top-level CLI error handler and logging path.

`render queue <episode_id> <preset_name>` is a thin mutating wrapper over
`RenderManager.queue_render()`. The episode ID and preset name are passed
through unchanged; render eligibility, preset lookup, output path
selection, Resolve queueing, render-job persistence, and episode state
transitions remain with `RenderManager`. On success, the command reports
the Redline render-job ID, episode ID, preset, Resolve job ID, status, and
output path. It queues only: it does not wait for completion, build the
episode, or archive anything.

```text
Render queued

Job ID: 7
Episode ID: RLC-E001
Preset: broadcast_master
Resolve Job ID: resolve-job-7
Status: queued
Output path: C:\production\episodes\RLC-E001\exports

Build was not performed.
Archive was not performed.
```

`render status <job_id>` is a thin wrapper over
`RenderManager.get_render_status()`. `job_id` is the Redline render-job
database ID, not the Resolve job ID. The manager may sync the persisted
status from Resolve; the CLI does not poll, loop, infer progress, inspect
output files, or fabricate timestamps.

`render list <episode_id>` is a thin wrapper over
`RenderManager.list_render_jobs_for_episode()`. It lists the jobs returned
by the manager for that episode in the returned order. With no jobs, it
prints `No render jobs found.` and exits successfully.

`render cancel <job_id>` is a thin wrapper over
`RenderManager.cancel_render()`. The CLI passes only the Redline render-job
database ID and does not decide whether a job is cancellable. Cancellation
does not imply output cleanup, rollback, rebuilding, or archiving.

`render start <job_id>` is a thin wrapper over `RenderManager.start_render()`.
The CLI passes only the Redline render-job database ID; whether the job is
startable (queued, has a persisted Resolve job ID, not already rendering or
terminal) is decided by `RenderManager`/`ResolveAdapter`, not the CLI. On
success, the underlying adapter call has already independently confirmed
`Rendering` via a getter-only postcondition check before the CLI ever
prints anything, so `Status: rendering` in the output reflects an
established fact, not a request that may still be pending:

```text
Render start confirmed

Job ID: 7
Resolve Job ID: resolve-job-7
Status: rendering
Output: C:\production\episodes\RLC-E001\exports\RLC-E001.mov
```

**Construction history, at the time each pass occurred: `start_render()` had
not yet been verified against a live Resolve instance.** Its first
construction (Rev1) was independently reviewed and returned REVISION
REQUIRED; a Rev2 correction pass resolved every finding and was
architecturally accepted but not yet approved for publication or live
execution; a Rev3 correction pass resolved every remaining finding and had
its architecture and safety model ACCEPTED, with one narrow BLOCKING
mismatch found against live getter-only evidence; a Rev4 correction pass
resolved it, still fully offline (see `docs/ARCHITECTURE.md` §3.8 and
`docs/RENDER_START_PATH_CONSTRUCTION.md` §6/§7/§8). **This construction-time
status is superseded for actual production use**: on 2026-08-11,
`start_render()` was live-verified through exactly one authorized production
invocation for the RLC-E9901 render job, reconciled to `complete` and
independently re-verified by this documentation-correction mission —
see `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md` §4.

Known render failures exit `1` and print a concise message to stderr. The
top-level `redline build Episode_0001` command remains assembly-only:
render commands do not build episodes, and build commands do not queue
renders.

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
Rows report `archive_state` (`legacy`/`complete`) and `archive_id`
(`None` for a legacy row) alongside the original three fields, so a
pre-Rev1 record is distinguishable from a Rev1 one at a glance; `list`
is database enumeration only and never performs package verification.

`redline archive create <episode_id>` builds, verifies, and commits a
Rev1 archive package for a rendered episode — calling
`ArchiveManager.create_archive()` directly (Phase 15 Mission 15F's
canonical transport). `episode_id` is the same identifier shown by
`episode list`/`episode status` (e.g. `RLC-E025`), not the plain episode
number every `episode` command takes. It is **non-destructive**: the
episode's source workspace and `folder_path` are left exactly where they
were; nothing is moved. `--render-job-id <id>` is required only when the
episode has more than one completed render job (`ArchiveManager` never
guesses); `--manifest <path>` is a legacy fallback only, for an episode
built before canonical manifest provenance existed — omit it for
normally-built episodes. On success, the command reports the episode ID,
archive ID, archive path, render job ID, manifest SHA-256, and status.
Exit code is `0` on success, `1` on failure. A database-commit failure
*after* a successful, verified publication is reported distinctly (the
verified package on disk is not deleted, moved, or overwritten) rather
than as a generic "nothing happened" failure — see `archive recover`
below for how to register that package once the database issue is
resolved. Retrying `archive create` itself never overwrites or rebuilds
a package that already exists at the canonical destination for the
episode's current content; it reports the same distinct classification
pointing at `archive recover` instead. Same `PersistenceServices`
composition path as `archive list`.

`redline archive verify <episode_id>` proves a committed Rev1 archive
package is still intact — calling `ArchiveManager.verify_archive()`
directly. Read-only: never mutates the episode, the `archives` row, the
source workspace, or the archive package. Checks the filesystem package
itself (control files, manifest structure, payload completeness, hashes,
sizes) rather than trusting the database's `archive_state` column alone,
and cross-checks the committed record's `manifest_sha256`/`manifest_path`
against what was actually, independently verified on disk. A legacy
(pre-Rev1) archive record fails with a clear, distinct error rather than
being verified as if it were Rev1; an episode with no committed archive
record at all fails clearly rather than scanning the archive root
attempting recovery (`archive recover` handles that, and only when given
an explicit `--archive-id`). Exit code is `0` only when verification
succeeds.

`redline archive recover <episode_id> --archive-id <archive_id>` (Phase
15 Mission 15H) registers an already-published, independently-verified
final package that a prior `archive create` attempt left
**VERIFIED_UNREGISTERED** — calling `ArchiveManager.recover_archive()`
directly. `--archive-id` is required and explicit (the value reported
alongside `verified_unregistered`); there is no discovery/scan mode, no
`--force`, and no way to point it at an arbitrary filesystem path — the
canonical location is always derived from `episode_id` + `archive_id` +
the configured archive root. Recovery never repairs, rebuilds, or
re-seals a package: it independently re-verifies the sealed package with
the exact same verifier `archive verify` uses, reads only its
already-sealed restore metadata (`episode.json`/`render_job.json` —
never current source/evidence/config, which recovery does not require to
still exist or match), cross-checks that against current database state,
and — only if every precondition holds — performs the same guarded
database transaction `archive create` itself would have. It is safe to
run more than once: a second call against an already-registered package
reports `classification: "already_registered"`, never a duplicate row or
a misleading error. Any conflict between the sealed package and current
database state (a different existing archive row, a render job that no
longer matches, an episode that is not `rendered`) fails closed with no
mutation, exactly like `archive create`'s own eligibility checks.

The legacy `redline archive episode <episode_id>` command (a destructive-
sounding but, since Phase 15 Mission 15E, actually non-destructive thin
wrapper over `ArchiveManager.archive_episode()`) is retired as of Mission
15F — `ArchiveManager.archive_episode()` no longer exists, and the
parser no longer registers the `episode` action under `archive` at all.
The canonical archive vocabulary is `create`/`verify`/`list`/`recover`.

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

## Running Control Room (V0, read-only)

```bash
pip install -e ".[control_room]"
python -m control_room.app                  # http://127.0.0.1:8765
python -m control_room.app --port 9000
redline-control-room                          # same thing, once installed
```

Control Room V0 is a local-only, read-only Projects screen: it combines
live local Git state with the durable semantic state recorded in
`docs/control_room/PROJECT_STATE.yaml` for each project registered in
`config/control_room/projects.yaml`. V0 registers exactly one project,
Redline OS itself. It binds to `127.0.0.1` by default and has no
mutation routes — see `docs/CONTROL_ROOM_V0_ARCHITECTURE.md` for the full
design and non-goals.

Each project card on the Projects screen is a link to a read-only Project
Detail screen (client-side hash routing, e.g. `#/projects/redline-os`),
which renders the same `ProjectSnapshot` — name, summary, attention, live
Git state, current mission, latest checkpoint, and validation status —
plus a link back to the Projects screen. No new server route was added
for this: the detail screen calls the existing
`GET /api/projects/{project_id}` endpoint.

The Detail screen also shows a read-only Mission & Checkpoint History
section: every completed Control Room mission, parsed fresh on every
request from its closure document under `docs/control_room/` (never
stored in `PROJECT_STATE.yaml`, which remains current-state-only). Each
entry shows the mission number/title, completion status, published
checkpoint SHA (with live resolution against the repository), closure
document path, and closure date when available — missing or malformed
data is shown explicitly rather than invented. No history database or
event log exists; see `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`'s "Mission &
Checkpoint History" section for the parsing/discovery rules.

Each history entry can be expanded into three read-only drill-downs.
Mission Scope & Outcome Detail (`Projects → Project Detail → Mission &
Checkpoint History → Mission Scope & Outcome Detail`) shows that mission's
closure document `## Purpose`, `## Delivered Capability`, and `## Deferred
Work` sections verbatim — what the mission was for, what it delivered, and
what it deliberately deferred, exactly as recorded, with no derived score,
count, priority, or recommendation. Validation & Evidence Detail
(`... → Validation & Evidence Detail`) shows that mission's `## Validation`,
`## Independent Review`, and `## CI` sections verbatim, whichever are
present. Both are reads, not re-runs — no historical test or review is
ever re-executed, and a missing section renders an explicit "not
recorded" message rather than inventing or guessing content. See
`docs/CONTROL_ROOM_V0_ARCHITECTURE.md`'s "Mission Scope & Outcome Detail"
and "Validation & Evidence Detail" sections for why that text is shown
verbatim rather than parsed into structured fields, and for the
fence-aware section-boundary rules shared by both.

Checkpoint Change Set Detail (`... → Checkpoint Change Set Detail`) is
different in kind from the other two: it is machine truth, not closure
prose. It shows the repository-relative file paths live Git reports as
changed by that mission's published checkpoint commit, via a read-only
`git diff-tree` against the already-resolved checkpoint SHA — never
parsed from the closure document, never a user-supplied revision. File
paths only: no diff content, no line counts, no commit author/message,
no blame. A legitimately empty change set (a commit that changed no
tracked files) renders an explicit "changed no files" message rather than
an error; an undeterminable change set (unresolved checkpoint, Git
failure) renders an explicit "unavailable" message and never contaminates
closure-document `parse_error`. See
`docs/CONTROL_ROOM_V0_ARCHITECTURE.md`'s "Checkpoint Change Set Detail"
and "Git role" sections for the revision-input safety boundary.

The Detail screen's live Git status block itself can also be expanded
into a read-only Current Working Tree Change Detail drill-down
(`Projects → Project Detail → Current Working Tree Change Detail`) —
distinct from Checkpoint Change Set Detail above, which is about one
*historical* commit; this is the repository's *current*, uncommitted
state. It shows the repository-relative paths currently staged,
unstaged, untracked, or mid-conflict, one record per path (so a file
that is both staged and further modified shows as one entry, not two),
from a single read-only `git status` call — the same read that already
determines the CLEAN/DIRTY pill, so the two can never disagree. A
renamed file shows its original path only when Git itself detected the
rename as staged; an unstaged filesystem move is reported by Git as a
plain delete plus a plain untracked add, and this feature does not try
to infer a rename Git didn't detect. Status codes and paths only: no
diff content, no line counts, no rename/copy score. A clean tree renders
an explicit "working tree is clean" message rather than an error; an
undeterminable result (a malformed or unrecognized status record) renders
an explicit "unavailable" message without discarding the rest of the Git
status block. See `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`'s "Current
Working Tree Change Detail" and "Git role" sections for the single-read
design and the two-tier failure behavior.

The Detail screen's state/checkpoint area also shows read-only
Closed-State Currency (`Projects → Project Detail → Closed-State
Currency`): whether the repository has moved beyond the latest formally
*closed* Control Room state — the commit that introduced the closure
document `PROJECT_STATE.yaml`'s `latest_checkpoint.document` field
records. "Closed state," never "Published State," and never "GitHub
verified" or "remote verified" — Control Room does not run `git fetch`,
so this is local Git history only. The recorded document path is
validated two ways before it is ever used as Git input (strict canonical
syntax, then an independently-discovered, provably repository-relative
match against what `MissionHistoryReader` already found) and the
resulting commit is compared against live HEAD via read-only
`git merge-base --is-ancestor` and `git rev-list --count`. Four states,
shown verbatim, no recommendation text: **CURRENT** (up to date, zero
commits beyond), **AHEAD** (N commits on HEAD beyond the recorded closed
state, local Git history only), **NOT_ANCESTOR** (the recorded closed
state is not an ancestor of current HEAD, so a linear count is not
computed), and **UNAVAILABLE** (with an explicit reason — a malformed or
unproven document path, an ambiguous or missing introduction commit, or
a Git failure). This is observation only: it is never fed into the
Detail screen's `attention` signal. See
`docs/CONTROL_ROOM_V0_ARCHITECTURE.md`'s "Closed-State Currency" section
for the full source-of-truth chain and the two-layer path-validation
design.

`redline-control-room` is installed by the base package, but FastAPI/
uvicorn (the `control_room` extra) are not — running it without that
extra installed fails with one clear message telling you to `pip install
-e ".[control_room]"`, not a raw import traceback.

**Control Room V0 requires an existing Redline OS repository checkout — it
is not a self-contained installed package.** Its whole purpose is reading
a real checkout's live Git state (branch, HEAD, dirty/clean, tracking),
which by definition cannot be bundled into a wheel (`.git/` is never
packaged). Registry/repository/state-file resolution is anchored to where
the installed `control_room` package's own source lives on disk, never to
the process's current working directory — for an editable dev install
that *is* the repo root, so running the command above from any directory
still finds this checkout. For a real, non-editable installed wheel, that
default resolves into `site-packages`, which correctly has no
`config/control_room/projects.yaml` — **you must set
`REDLINE_CONTROL_ROOM_ROOT` to the path of a Redline OS repository
checkout**, or `redline-control-room` fails fast at startup (before
binding a port) with a message telling you to do exactly that, rather
than starting a server that would only 503 on the first request. Either
way, launching from an unrelated directory can never silently
reinterpret that directory as the Redline OS project.
`REDLINE_CONTROL_ROOM_REGISTRY` overrides the registry file path itself,
resolved against `REDLINE_CONTROL_ROOM_ROOT` (or the package default)
when given as a relative path.

## Repository layout

```
src/redline_core/   # all business logic (transport-agnostic)
src/mcp_server/      # MCP tool layer (thin wrappers only)
src/control_room/    # Control Room V0: read-only local Projects screen (FastAPI + plain HTML/JS)
tests/unit/          # fast tests against MockResolveAdapter, run in CI
tests/integration/   # requires real Resolve, run manually
config/              # YAML config (naming, folders, render presets, paths, assets, timeline template)
docs/                # architecture, config, MCP tools, changelog
scripts/             # env setup, DB bootstrap
```
