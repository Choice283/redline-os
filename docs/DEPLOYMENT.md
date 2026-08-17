# Production Workstation Deployment

This guide describes how to deploy the Redline OS package onto a production
workstation using the installed workflow verified by Phase 12. It documents the
current manual deployment path only. It does not introduce an installer,
service, container, release pipeline, rollback mechanism, or upgrade policy.

## 1. Purpose

Use this runbook when preparing a workstation to run Redline OS as installed
software rather than from a source checkout.

Required:

- Use a built Redline OS wheel or another approved package artifact.
- Keep configuration, database, and logs in explicit workstation locations.
- Verify CLI startup before using mutating commands.
- Verify MCP startup with mock Resolve before connecting a client to real
  Resolve-backed workflows.

Optional:

- Configure Resolve scripting variables only on workstations that will run real
  Resolve-backed operations.

Verification:

- `redline asset list`
- `redline-mcp --mock-resolve`

Not automated:

- Package publishing
- Artifact signing
- Operating-system service installation
- Resolve installation or licensing
- Rollback or upgrade orchestration

## 2. Supported deployment model

Redline OS is a local production-workstation service. The real Resolve adapter
requires a live DaVinci Resolve Studio process reachable through Resolve's
Python scripting bridge. The supported deployment model is therefore:

Required:

- One workstation-local Python environment for Redline OS.
- One installed Redline OS package.
- One configured Redline OS config directory.
- One configured SQLite database path.
- One configured log directory.
- DaVinci Resolve Studio installed and running for workflows that touch Resolve.

Optional:

- MCP client integration through `redline-mcp`.
- Mock Resolve startup for first-run checks or non-Resolve client wiring.

Verification:

- Confirm the `redline` and `redline-mcp` console scripts exist after install.
- Confirm config, database, and log paths are explicit before first use.

Not automated:

- Multi-workstation coordination
- Remote Resolve control
- Docker or cloud execution
- Windows or Linux service management

## 3. Workstation prerequisites

Required:

- Python >= 3.10 for mock-based and non-Resolve workflows.
- Python 3.11 for workflows that use the real `ResolveScriptAdapter`.
- Filesystem access to the configured ingest, assets, archive, database, and log
  locations.
- A copy of the Redline OS YAML configuration directory.

Required for real Resolve workflows:

- DaVinci Resolve Studio, not the free edition.
- Resolve Studio running on the workstation.
- Resolve scripting environment variables set for the shell or process that
  launches `redline` or `redline-mcp`.

Optional:

- MCP client configured to launch `redline-mcp`.

Verification:

- Confirm `python --version` matches the workflow requirement.
- Confirm Resolve Studio launches before running real Resolve commands.
- Confirm the OS user can create files in the configured database and log
  directories.

Not automated:

- Python installation
- Resolve Studio installation
- Resolve license activation
- OS-level permission repair

## 4. Installing Redline OS

Install into an isolated Python environment.

Required:

```bash
python -m venv redline-venv
source redline-venv/bin/activate
pip install redline_os-*.whl
```

On Windows PowerShell:

```powershell
python -m venv redline-venv
.\redline-venv\Scripts\Activate.ps1
pip install .\redline_os-*.whl
```

Optional:

Install with the MCP extra when the workstation will run the MCP server:

```bash
pip install "redline_os-0.1.0-py3-none-any.whl[mcp]"
```

Use the actual wheel filename for the artifact being deployed. Mission 25
verifies that the wheel metadata declares the `mcp` optional dependency; this
guide does not define a package-publishing channel.

Verification:

```bash
redline --help
redline-mcp --help
```

Not automated:

- Artifact download
- Package publication
- Dependency mirroring
- Version promotion

## 5. Configuration locations

Required:

Set `REDLINE_CONFIG_DIR` to the directory containing:

- `naming.yaml`
- `folder_structure.yaml`
- `render_presets.yaml`
- `paths.yaml`
- `assets.yaml`
- `timeline_template.yaml`

Example:

```bash
export REDLINE_CONFIG_DIR=/path/to/config
```

PowerShell:

```powershell
$env:REDLINE_CONFIG_DIR = "C:\path\to\config"
```

Optional:

- Keep a copy of the deployed config directory with the deployment evidence.

Verification:

```bash
redline asset list
```

Not automated:

- Config generation
- Creative-standard approval
- Config migration

## 6. Database and logging locations

Required:

Set explicit database and log locations:

```bash
export REDLINE_DB_PATH=/path/to/redline.db
export REDLINE_LOG_DIR=/path/to/logs
```

PowerShell:

```powershell
$env:REDLINE_DB_PATH = "C:\path\to\redline.db"
$env:REDLINE_LOG_DIR = "C:\path\to\logs"
```

The installed package includes the core SQLite schema resource. Installed
operators do not need `PYTHONPATH=src` and do not need
`scripts/bootstrap_db.py`.

Optional:

- Create the parent directories before first startup to verify permissions.

Verification:

- Run a command that needs only config first: `redline asset list`.
- Run a persistence-backed command only after database path selection is clear:
  `redline episode list --mock-resolve`.
- Confirm `redline_os.log` appears under `REDLINE_LOG_DIR` after startup.

Not automated:

- Database backup scheduling/triggering (manual, on-demand backup +
  independent verification exists as of V2 Mission 1A: `redline backup
  create` / `list` / `verify` -- see `docs/BACKUP_RECOVERY_ARCHITECTURE.md`;
  restore is not implemented, deferred to a separate, not-yet-authorized
  Mission 1B)
- Database migration planning beyond current startup schema initialization
- Log shipping or retention policy

## 7. Resolve prerequisites

Required for real Resolve workflows:

- DaVinci Resolve Studio installed and running.
- Python 3.11 for the process that imports Resolve's scripting module.
- `RESOLVE_SCRIPT_API` pointing at Resolve's scripting API directory.
- `RESOLVE_SCRIPT_LIB` pointing at Resolve's `fusionscript` library.
- `PYTHONPATH` containing the Resolve scripting `Modules` directory.

Example PowerShell values on Windows:

```powershell
RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
PYTHONPATH Resolve Modules entry = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
```

For persistent Windows workstation configuration, write those values at User
scope for the same interactive Windows identity that runs Resolve validation.
Mission 39E verified that identity as `CHOICES\pj198`, with user profile
`C:\Users\pj198`. Do not configure them under a different account, such as
`Choices\CodexSandboxOffline`, and do not rely on elevation; User-scope values
do not require an elevated shell. After setting User-scope values, start a
genuinely new native Windows PowerShell session to verify process inheritance.

Use Python 3.11 for every real Resolve adapter process. Mission 39E verified
Python 3.11.9 importing `DaVinciResolveScript` and connecting
`ResolveScriptAdapter`; Python 3.13 ran ordinary Python code but crashed while
importing `DaVinciResolveScript` with Windows access violation `0xC0000005`, so
Python 3.13 must not be used for the current Resolve integration.

Optional:

- Use the repository setup scripts as a reference when deploying from a source
  checkout. They are not required by installed operators.

Verification:

- Run non-Resolve checks with `--mock-resolve` first.
- Transition to real Resolve only for operations that intentionally touch
  Resolve state, such as episode creation, media import, timeline work, render
  queueing, render status, or cancellation.

Not automated:

- Resolve installation
- Resolve license activation
- Resolve project cleanup
- Headless Resolve reliability validation

## 8. Verifying CLI deployment

Required:

Run the installed CLI outside the repository checkout:

```bash
redline asset list
```

Optional:

Run a read-only persistence-backed command after `REDLINE_DB_PATH` is set:

```bash
redline episode list --mock-resolve
```

Verification:

- `redline asset list` exits with code 0.
- Asset output comes from the configured `assets.yaml`.
- Logs are written to the configured log directory.

Not automated:

- Full production episode creation
- Resolve project mutation
- Archive validation

## 9. Verifying MCP deployment

Required:

Run the installed MCP entrypoint with mock Resolve:

```bash
redline-mcp --mock-resolve
```

Optional:

- Point an MCP client at `redline-mcp --mock-resolve` for client wiring checks.
- Start `redline-mcp` without `--mock-resolve` only when the workstation is
  ready to use real Resolve-backed tools.

Verification:

- The command starts from the installed console script.
- Startup uses the configured config, database, and log locations.
- Mock Resolve startup does not require Resolve Studio.

Not automated:

- MCP client configuration
- Long-running process supervision
- Service restart policy

## 10. Deployment checklist

Required:

- [ ] Select deployment workstation.
- [ ] Install supported Python.
- [ ] Use Python 3.11 for real Resolve workflows; do not use Python 3.13 for
      the current Resolve integration.
- [ ] Install DaVinci Resolve Studio if real Resolve workflows are required.
- [ ] Create isolated Python environment.
- [ ] Install the Redline OS wheel.
- [ ] Install with MCP support if the workstation will run `redline-mcp`.
- [ ] Set `REDLINE_CONFIG_DIR`.
- [ ] Set `REDLINE_DB_PATH`.
- [ ] Set `REDLINE_LOG_DIR`.
- [ ] Set Resolve scripting variables at User scope for the interactive Windows
      identity if real Resolve workflows are required.
- [ ] Open a genuinely new native PowerShell session after User-scope Resolve
      scripting configuration.
- [ ] Run `redline asset list`.
- [ ] Run `redline-mcp --mock-resolve` if MCP is required.

Optional:

- [ ] Preserve a copy of the wheel artifact.
- [ ] Preserve a copy of deployed config files.
- [ ] Record Python and Resolve versions.

Verification:

- CLI verification passes.
- MCP verification passes when MCP is in scope.
- Logs are created in the expected directory.

Not automated:

- Deployment approval
- Release promotion
- Rollback
- Upgrade

## 11. Evidence to retain

Required:

- Redline OS wheel filename and checksum, if available.
- Git commit or release identifier used to build the artifact.
- Python version.
- Resolve Studio version, when real Resolve is in scope.
- `REDLINE_CONFIG_DIR`, `REDLINE_DB_PATH`, and `REDLINE_LOG_DIR`.
- CLI verification output.
- MCP verification output, when MCP is deployed.
- Relevant `redline_os.log` startup lines.

Optional:

- Copy of deployed YAML config.
- MCP client command configuration.

Verification:

- Evidence is enough to reproduce which artifact, config, and workstation paths
  were used.

Not automated:

- Artifact signing
- Evidence upload
- Release-note generation

## 12. Known limitations

Required awareness:

- Redline OS is not a cloud/serverless service.
- Real Resolve workflows require Resolve Studio.
- Python 3.11 is the verified interpreter for Resolve Studio 21.0.3.
- Python 3.13 must not be used for the current Resolve integration because
  importing `DaVinciResolveScript` has been observed to crash with Windows
  access violation `0xC0000005`.
- Windows User-scope Resolve scripting variables must belong to the
  interactive identity that runs Resolve validation; writing them under another
  account will not configure that session.
- Mock Resolve verifies Redline startup and transport wiring, not real Resolve
  project state.
- No automatic rollback exists for partial Resolve mutations.
- Deployment does not define upgrade or rollback policy.
- CI cannot validate real Resolve-dependent code.

Optional:

- Use `docs/RECOVERY.md` for interrupted work and drift handling.

Verification:

- Operators know which parts of deployment are manual and which checks are
  verified by existing Phase 12 smokes.

Not automated:

- Troubleshooting
- Performance validation
- Failure injection

## 13. Related documentation

- `README.md` - high-level status, first-run operator workflow, CLI/MCP usage.
- `docs/CONFIG.md` - environment variables and configuration files.
- `docs/RECOVERY.md` - recovery and restart runbook.
- `docs/MCP_TOOLS.md` - MCP server usage and tool reference.
- `docs/ROADMAP.md` - phase and mission status.
- `docs/CHANGELOG.md` - mission history and verification notes.
