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

## `/config/*.yaml` files

| File | Model | Purpose |
|---|---|---|
| `naming.yaml` | `NamingConfig` | Episode ID / project name patterns — **sourced from the Redline Universe project**, not invented here. |
| `folder_structure.yaml` | `FolderStructureConfig` | Per-episode working folder layout. |
| `render_presets.yaml` | `RenderPresetsConfig` | Named render presets; `resolve_preset_name` must match a preset that actually exists inside Resolve's Deliver page. |
| `paths.yaml` | `PathsConfig` | Global ingest/archive/assets paths and the master project template name. |
| `assets.yaml` | `AssetsConfig` | Registry of approved assets (Asset IDs + filenames) and which ones every episode requires by default. Asset IDs themselves are **sourced from the Universe project** — add an entry here only once one's been approved there. |
| `timeline_template.yaml` | `TimelineTemplateConfig` | Timeline naming pattern + the standard marker set (frame, color, name, note) applied to every episode timeline, per the Broadcast Package V1.0 spec. |

**Rule of thumb:** if the Redline Universe project changes a naming or folder convention, update the YAML here — never hardcode the old or new convention inside `redline_core`.

## Validation errors

`load_config()` raises `ConfigError` (from `redline_core.config.loader`) if:

- a required YAML file is missing from the config directory, or
- a file's contents fail pydantic validation (wrong types, missing required fields, empty naming patterns).

The error message includes the underlying validation detail — check it before assuming the codebase is broken; it's usually a config typo.
