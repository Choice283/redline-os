# Configuration Guide

Redline OS reads two kinds of configuration:

1. **`.env`** — machine-specific paths and the DaVinci Resolve scripting bridge variables. Copy `.env.example` to `.env` and edit it. Never commit `.env`.
2. **`/config/*.yaml`** — pipeline conventions (naming, folder structure, render presets, global paths). These are validated on load by `redline_core.config.loader.load_config()` against the pydantic models in `redline_core.config.schema`.

## `.env` variables

| Variable | Purpose |
|---|---|
| `RESOLVE_SCRIPT_API` | Path to Resolve's scripting API folder. Required by `ResolveScriptAdapter`. |
| `RESOLVE_SCRIPT_LIB` | Path to Resolve's `fusionscript` library. Required by `ResolveScriptAdapter`. |
| `REDLINE_DB_PATH` | Path to the SQLite database file. |
| `REDLINE_CONFIG_DIR` | Path to the `/config` directory (defaults to `./config`). |
| `REDLINE_LOG_DIR` | Directory for rotating log files. |
| `REDLINE_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |

Platform defaults for `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` are pre-filled in `scripts/setup_env.sh` (macOS/Linux) and `scripts/setup_env.ps1` (Windows) — source/dot-source the one matching your workstation, or set the same values in `.env`.

## First-run installed operator configuration

For an installed package, choose explicit machine-local paths before first
startup:

```bash
export REDLINE_CONFIG_DIR=/path/to/config
export REDLINE_DB_PATH=/path/to/redline.db
export REDLINE_LOG_DIR=/path/to/logs
```

On Windows PowerShell:

```powershell
$env:REDLINE_CONFIG_DIR = "C:\path\to\config"
$env:REDLINE_DB_PATH = "C:\path\to\redline.db"
$env:REDLINE_LOG_DIR = "C:\path\to\logs"
```

`REDLINE_CONFIG_DIR` must contain the YAML files listed below. `REDLINE_DB_PATH`
selects the SQLite database used by persistence-backed commands and MCP tools.
`REDLINE_LOG_DIR` is created at startup if it does not already exist.

The installed package carries the canonical SQLite schema as a package
resource. Installed operators do not need `PYTHONPATH=src` and do not need to
run `scripts/bootstrap_db.py`; that script is a source-checkout helper. The
installed database bootstrap path is the `redline_core.db.Database` package
boundary used by the application services.

After setting the paths, verify startup without Resolve:

```bash
redline asset list
redline-mcp --mock-resolve
```

Use mock Resolve for first-run checks, MCP client wiring, config verification,
and logging verification. Set `RESOLVE_SCRIPT_API` and `RESOLVE_SCRIPT_LIB`
only when running a real Resolve-backed workflow. Those variables must match
the installed DaVinci Resolve Studio scripting locations and require a Python
version compatible with Resolve's native scripting module; Python 3.11 is the
verified interpreter for Resolve Studio 21.0.3.

On the verified Windows workstation, real Resolve workflows require the
interactive Windows identity that runs Resolve validation to own the User-scope
Resolve scripting variables. Mission 39E verified that identity as
`CHOICES\pj198`, with user profile `C:\Users\pj198`; values written for a
different account, such as `Choices\CodexSandboxOffline`, are not inherited by
that interactive session. User-scope configuration does not require elevation.
After writing User-scope values, open a genuinely new native Windows
PowerShell session before checking Process-scope inheritance.

Verified Windows values for that workstation:

```powershell
RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
PYTHONPATH Resolve Modules entry = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
```

Mission 39E also verified that Python 3.11.9 can import
`DaVinciResolveScript` and that `ResolveScriptAdapter` can connect through
Python 3.11. Python 3.13 can run ordinary Python code on the workstation, but
it crashes while importing `DaVinciResolveScript` with Windows access
violation `0xC0000005`; do not use Python 3.13 for the current Resolve
integration.

## Logging and diagnostics

CLI and MCP startup both call `redline_core.logging.setup.configure_logging()`.
The transport entrypoints read only these existing environment variables:

| Variable | Default | Behavior |
|---|---|---|
| `REDLINE_LOG_DIR` | `./logs` | Parent directory for `redline_os.log`. Created at startup if it does not exist. Relative paths resolve from the process working directory. |
| `REDLINE_LOG_LEVEL` | `INFO` | Minimum Redline OS log level. Supported values are `DEBUG`, `INFO`, `WARNING`, and `ERROR`; values are case-insensitive. |

Logging installs one console handler and one rotating file handler owned by
Redline OS. Repeated startup/configuration replaces Redline-owned handlers
without removing unrelated handlers installed by a test runner, embedding
application, or third-party library. Invalid log levels raise
`LoggingConfigurationError` during startup; directory creation or file-handler
failures also propagate instead of being swallowed.

Operator checks:

- To verify the active level, check `REDLINE_LOG_LEVEL`; if it is unset, startup
  uses `INFO`.
- To verify where logs are written, check `REDLINE_LOG_DIR`; if it is unset,
  logs are written under `./logs/redline_os.log` relative to the process working
  directory.
- To verify the process can create the log directory, create the configured
  directory manually with the same OS user that runs `redline` or
  `redline-mcp`.
- If startup fails before a log file appears, check stderr/terminal output for
  configuration, permission, or path errors from logging initialization.

## `/config/*.yaml` files

| File | Model | Purpose |
|---|---|---|
| `naming.yaml` | `NamingConfig` | Episode ID / project name patterns — **sourced from the Redline Universe project**, not invented here. |
| `folder_structure.yaml` | `FolderStructureConfig` | Per-episode working folder layout. |
| `render_presets.yaml` | `RenderPresetsConfig` | Named render presets; `resolve_preset_name` must match a preset that actually exists inside Resolve's Deliver page. A queueable preset also declares deterministic output naming: `output_subfolder`, `filename_template`, explicit `file_extension`, `collision_policy`, and `requires_video_payload`. |
| `paths.yaml` | `PathsConfig` | Global ingest/archive/assets paths, the master project template name, and the optional episode-scoped evidence root (`evidence_path` — see below). |
| `assets.yaml` | `AssetsConfig` | Registry of approved assets (Asset IDs + filenames) and which ones every episode requires by default. Asset IDs themselves are **sourced from the Universe project** — add an entry here only once one's been approved there. |
| `timeline_template.yaml` | `TimelineTemplateConfig` | Timeline naming pattern + the standard marker set (frame, color, name, note) applied to every episode timeline, per the Broadcast Package V1.0 spec. |

The checked-in `folder_structure.yaml` uses `./_episodes` as the default local
episode working root. That directory is runtime workspace state, not repository
source, and is ignored alongside workstation-local tool state such as
`.claude/`.

**Rule of thumb:** if the Redline Universe project changes a naming or folder convention, update the YAML here — never hardcode the old or new convention inside `redline_core`.

## Episode-scoped evidence root (`paths.evidence_path`, Phase 15 Mission 15G.1)

`paths.yaml` may optionally set `evidence_path`: the parent directory containing
per-episode production-evidence directories, `<evidence_path>/<episode_id>/`. It
is `null`/absent by default at the **configuration-schema** level — the
checked-in `config/paths.yaml` does not set it, no machine-specific live path is
ever hard-coded into repository source, and a `paths.yaml` document written
before Mission 15G.1 still loads without any change.

**Configuration parsing being backward-compatible does not mean archive creation
succeeds without it.** `PathsConfig.evidence_path` staying optional is a schema-
loading concern only; `ArchiveManager.create_archive()`'s eligibility gate is a
separate, deliberately fail-closed archive-completeness requirement (a narrow
correction to Mission 15G.1's original, more permissive session — Control Room
rejected "no configured authority" as equivalent to "authoritative zero
evidence"). The two are independent: a config document without `evidence_path`
loads fine; calling `create_archive()` against that same config raises.

The directory boundary is the *only* ownership authority: a file is evidence for
`episode_id` if and only if it lives under `<evidence_path>/<episode_id>/`
(nested subdirectories preserved). A filename containing an episode ID elsewhere
under the evidence root is never treated as that episode's evidence.

`ArchiveManager.create_archive()`'s evidence-authority state machine, in full:

| `evidence_path` | `<evidence_path>` on disk | `<evidence_path>/<episode_id>/` | Result |
|---|---|---|---|
| unset (`None`) | — | — | **Fails closed** — `ArchiveEvidenceConfigurationError`, before any package/DB work. No configured authority is never treated as an authoritative zero-evidence result. |
| set | missing | — | **Fails closed** — `ArchivePathError`. |
| set | exists, unsafe (symlink/junction/reparse point/not a directory) | — | **Fails closed** — `ArchiveUnsafeFilesystemObjectError`/`ArchivePathError`. |
| set | exists, valid directory | absent | **Succeeds** — the one and only valid zero-evidence route: zero evidence supplements, archive proceeds normally. |
| set | exists, valid directory | exists, valid | Evidence resolved and archived (see the resolver contract below). |

Every failure row above raises before `ArchivePackagePlan` construction, package
staging, publication, or database commit — no source mutation, no archive
directory created, the episode remains `'rendered'`.

Evidence never changes `content_set_digest`/`archive_id` — it is sealed,
supplemental package content (`payload/external/evidence/...`), not preservation
identity. See `docs/ARCHITECTURE.md`'s Mission 15G.1 subsection for the full
resolver contract.

## Render preset output contract

- `filename_template` is a filename stem template only. It cannot be empty,
  absolute, contain path separators, traverse with `..`, or use placeholders
  other than `episode_id`, `preset_name`, `project_name`, or `timeline_name`.
- `file_extension` must include the leading dot, for example `.mov`.
- `collision_policy` currently supports only `reject`.
- A preset may exist without `filename_template` and `file_extension` so
  canonical config can represent a known Resolve preset whose approved export
  filename standard is still absent. Queueing that preset fails before
  Resolve, SQLite render-job insertion, or output filesystem mutation.
- Redline calculates the complete expected output path before queueing Resolve:
  episode folder -> preset `output_subfolder` -> `filename_template` +
  `file_extension`.
- Queueing rejects an exact existing output file and active Redline/Resolve
  queue jobs that target the same output. It never overwrites automatically.
- `requires_video_payload` (default `false`) declares that the preset needs at
  least one video TimelineItem on the target timeline. When `true`, queueing
  runs a renderability preflight that fails closed with
  `RenderTimelineNotRenderableError` — before any SQLite output claim or
  Resolve queue mutation — if the target timeline has zero video
  TimelineItems. This is a per-preset capability declaration, not a universal
  Resolve rule; see the Phase 14 Test D entry in `docs/CHANGELOG.md` for the
  evidence behind it.

The approved Broadcast Master export filename standard is `{project_name}.mov`.
The canonical `broadcast_master` preset maps to the externally provisioned
Resolve preset `Redline Broadcast Master`, writes beneath `exports`, uses
`filename_template: "{project_name}"`, `file_extension: ".mov"`,
`collision_policy: "reject"`, and `requires_video_payload: true`.

The `youtube_1080p` preset remains incomplete because no separate approved
YouTube export filename standard has been supplied. It continues to fail closed
before Resolve, SQLite render-job insertion, or output filesystem mutation.

## Validation errors

`load_config()` raises `ConfigError` (from `redline_core.config.loader`) if:

- a required YAML file is missing from the config directory, or
- a file's contents fail pydantic validation (wrong types, missing required fields, empty naming patterns).

The error message includes the underlying validation detail — check it before assuming the codebase is broken; it's usually a config typo.
