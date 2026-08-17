# Redline OS V2 Mission 1A — First Production Backup Execution Evidence

## Governance

Agents advise. Paul decides. This document records the first real
production execution of Mission 1A's published `BackupManager` capability
against Redline OS's live production runtime. It is evidence of an
*operational event*, not a mission implementation record — it does not
reopen, amend, or restate the frozen implementation checkpoint or the
closure document below.

## Referenced records

- Mission 1A implementation checkpoint: `b791a860aa0c2fa1a5fb8d3346c2e566eaa4d7bf`
  (`feat: add system-of-record backup verification`)
- Mission 1A closure commit: `275870a6ac0940c32d8c8a3ebf078dfe0a404d01`
  (`docs: close Redline OS V2 Mission 1A`)
- Closure record: `docs/V2_MISSION_1A_CLOSURE_2026-08-16.md`, whose
  "Future production-proof requirement" section anticipated exactly this
  event and did not itself perform, schedule, or authorize it.

## Production-proof date/time

Backup created: `2026-08-17T03:06:06.890350Z` (`2026-08-16 22:06:06 CDT`).
Executed against repository state `HEAD = origin/master =
275870a6ac0940c32d8c8a3ebf078dfe0a404d01` (unchanged before, during, and
after this execution).

## Execution identity

- Python executable: `C:\Python313\python.exe`
- Working directory: `C:\Users\pj198\Documents\redline-os`
- `PYTHONPATH=src` — required because an unrelated global `cli` package
  in `site-packages` (`C:\Users\pj198\AppData\Roaming\Python\Python313\site-packages\cli\__init__.py`)
  shadows the repository's own `src/cli` package; confirmed from source
  that `python -m cli.main` fails with `No module named cli.main` without
  it.
- `REDLINE_DB_PATH=C:\Users\pj198\RedlineOSLive\Runtime\redline.db`
- `REDLINE_CONFIG_DIR=C:\Users\pj198\RedlineOSLive\Runtime\production-config`
- `REDLINE_LOG_DIR=C:\Users\pj198\RedlineOSLive\Runtime\logs` — set
  explicitly because the CLI's default (`./logs`, relative to CWD) would
  otherwise have written inside the Git repository; this path is the
  pre-existing production log directory (contains `redline_os.log` dated
  2026-08-09, predating this execution), not an invented location.
- None of the above four environment variables were persisted at User or
  Machine scope — execution-scoped only, confirmed absent from persistent
  environment both before and after.

## Backup creation

Exact command:

```
& "C:\Python313\python.exe" -m cli.main backup create --reason "first production system-of-record backup after V2 Mission 1A"
```

Exit code: `0`. stderr: empty. stdout:

```
Backup ID:        b1-20260817T030606Z-8abd0a149de5
Backup path:      C:\Users\pj198\RedlineOSLive\Backups\system_backups\b1-20260817T030606Z-8abd0a149de5
Manifest SHA-256: 650e900128e0427912f4951e8c6d3134acb91c13d3673dbe7fb3ee7807c69836
Database SHA-256: 1894fe97235bcb4eafc2a45b8f1645d90c7d15f0517099a8fcf95dd3e0b453e9
Database size:    45056 bytes
Config files:     6
Total size:       48610 bytes
Content digest:   8abd0a149de51cee4421219238fa931b8e7d69c360871d7da9dded2dbddfc620
Created at:       2026-08-17T03:06:06.890350Z
```

- Backup ID: `b1-20260817T030606Z-8abd0a149de5`
- Backup path: `C:\Users\pj198\RedlineOSLive\Backups\system_backups\b1-20260817T030606Z-8abd0a149de5`
- Manifest SHA-256: `650e900128e0427912f4951e8c6d3134acb91c13d3673dbe7fb3ee7807c69836`
  — independently recomputed against `backup_manifest.json` on disk and
  confirmed to match `backup_manifest.sha256` exactly.

## Backed-up database vs. live database

| | size | SHA-256 |
|---|---|---|
| Backup copy | 45056 bytes | `1894fe97235bcb4eafc2a45b8f1645d90c7d15f0517099a8fcf95dd3e0b453e9` |
| Live source | 45056 bytes | `eb4969bcd21428cc469a3b25b5f4e33d7854ac43a8a9c93cfc71c35246836a55` |

**The differing hashes are expected and not a defect.** `snapshot_database()`
never performs a raw filesystem copy; it opens the live database through
an independent read-only connection and uses `sqlite3.Connection.backup()`
— Python's wrapper for SQLite's genuine Online Backup API — which produces
a fresh, logically consistent file whose on-disk page layout is not
required to be byte-identical to the source, only logically equivalent.
Both databases independently pass `PRAGMA integrity_check = ok`
(re-verified directly against each file in this session, not merely
trusted from CLI output).

## Backed-up production state (independently queried from the backup copy)

- Tables present: `archives`, `episodes`, `render_jobs`, `sqlite_sequence`
  — identical to the live source.
- `episodes`: `episode_id='RLC-E9901'`, `status='archived'`.
- `render_jobs`: exactly one row for `RLC-E9901`, `status='complete'`.
- `archives`: exactly one row, `archive_id='RLC-E9901-a1-b67c50e31ff6'`,
  `archive_state='complete'`.

## Backed-up config vs. production-config source

All six `redline_core.config.loader.REQUIRED_FILES` are byte-identical
between `payload/config/` inside the sealed package and
`C:\Users\pj198\RedlineOSLive\Runtime\production-config`:

| file | size | SHA-256 |
|---|---|---|
| naming.yaml | 365 | `1880db5e1dd53450d6e7fa65db54b023f61733290789421eade202640cf82cc5` |
| folder_structure.yaml | 253 | `9718b6096fd097b60dea9e8723620474739d86da2d16fc2db0f92566aec1ed47` |
| render_presets.yaml | 994 | `f9434b087e504bdfb6858e7fe83cd1e6bc6ccf4caaab56eb4295690502a40524` |
| paths.yaml | 389 | `bf86072a8f446d9cafc26ca99de3717ad1c1aee00b3f79dcfe2d667d0347ba95` |
| assets.yaml | 964 | `dbb6195b78c653dcf7f03887c3505d6ddd4bc3e309b8a4a2c3c38ffc65ecada7` |
| timeline_template.yaml | 589 | `9ea23322f95769dc4068c53510a949a9f809cfe5b45201a09d9dc5b488d185f5` |

## Live source immutability (proven, not assumed)

Re-checked directly after create + verify + list:

- Live `redline.db`: size 45056 bytes, SHA-256
  `eb4969bcd21428cc469a3b25b5f4e33d7854ac43a8a9c93cfc71c35246836a55`, mtime
  `2026-08-16 15:31:42.845735000` — identical to the pre-execution
  baseline, proving no write occurred against the live database.
- All six `production-config` files: hashes identical to the pre-execution
  baseline (table above).
- All six historical `RLC-E9901-archive-config` files: hashes identical to
  their previously recorded values — this directory, preserved evidence of
  the original RLC-E9901 archive execution, remains untouched.
- The RLC-E9901 archive package
  (`Archives\episodes\RLC-E9901\RLC-E9901-a1-b67c50e31ff6\`):
  `archive_manifest.json` SHA-256 unchanged
  (`eb593f2ae96131694e3b8fe3e154166089df850ec2426b57a8bde59b21a65c3c`),
  `PACKAGE_COMPLETE` marker still present, package untouched.

## Discoverability and sealing

`redline backup list` (exit 0) shows exactly one backup — `backup_id` and
path match the `create` output exactly; no unexpected second production
backup exists. Sealed-package inventory
(`C:\Users\pj198\RedlineOSLive\Backups\system_backups\b1-20260817T030606Z-8abd0a149de5\`)
contains exactly: `BACKUP_COMPLETE`, `backup_manifest.json`,
`backup_manifest.sha256`, `payload\database\redline.db`,
`payload\config\{naming,folder_structure,render_presets,paths,assets,timeline_template}.yaml`
— no undeclared object.

## Staging state

`Backups\.staging\` exists and is empty (parent directory left in place by
design, per Mission 1A's forensic-preservation doctrine — not deleted).
`Backups\system_backups\` contains exactly the one sealed package.

## Repository state

`HEAD = origin/master = 275870a6ac0940c32d8c8a3ebf078dfe0a404d01` before,
during, and after this execution; 0/0 ahead/behind; working tree and index
clean; stash empty; `v1.0.0` unchanged
(`a41eb57012fbd80ae1be536d8e91ab74f459bc32`). No repository source file was
touched by this execution — the repository's own `logs/redline_os.log`
(untracked) is unmodified, its modification time predating this
execution, confirming the explicit `REDLINE_LOG_DIR` override worked.

## Failure/recovery condition

None. `backup create`, `backup verify`, and `backup list` each succeeded
on the first attempt with exit code 0. No retry, repair, or cleanup was
required or performed.

## Explicit absences

No Resolve contact occurred at any point. No Mission 1B (Restore) work was
performed, implied, or is authorized by this evidence record — no
`restore_backup()` method, no `backup restore` CLI action, and no
pre-restore safety snapshot exist anywhere in the repository as of
`275870a6ac0940c32d8c8a3ebf078dfe0a404d01`. No production database was
mutated. No production or historical configuration file was mutated. No
second production backup was created.

## Closure

This is the first production execution of Mission 1A's system-of-record
backup capability. It is independently verified, sealed, and internally
consistent with the RLC-E9901 production state established prior to
Mission 1A's implementation. It does not authorize, schedule, or imply
Mission 1B (Restore), any further production backup, or any change to the
historical RLC-E9901 archive evidence — all of which remain separate,
future, Founder-authorized decisions.

Agents advise. Paul decides.
