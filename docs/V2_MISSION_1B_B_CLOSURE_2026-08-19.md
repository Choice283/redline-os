# Redline OS V2 Mission 1B-B Closure — Backup / Restore / Recovery MCP Read Surface

## Governance

Agents advise. Paul decides. This document records the local implementation
checkpoint closure of Mission 1B-B, following a dedicated architecture-
discovery and ratification pass, an accepted implementation authorization,
and an accepted checkpoint commit. It does **not** record a closure commit
or publication — see "Publication boundary" below.

## Mission identity and objective

**Mission 1B-B — Backup / Restore / Recovery MCP Read Surface.**

Objective: expose the safe, non-mutating inspection and planning
capabilities of Redline OS Backup, Restore, and Recovery through MCP while
preserving all existing human authorization, quiescence, destructive-
mutation, and composition boundaries.

Mission 1B-B's own boundary/scope was previously undefined in this
repository (see the Mission 1B-B Definition/Boundary Review that preceded
architecture discovery); this closure records the exact ratified scope as
implemented.

## Lifecycle status at drafting time

```
IMPLEMENTED
CHECKPOINTED LOCALLY
NOT PUBLISHED
NOT CI-VERIFIED FOR CHECKPOINT HEAD
READY FOR CLOSURE COMMIT / PUBLICATION SEQUENCE
```

## Exact MCP surface: exactly four tools

| Tool | Core authority |
|---|---|
| `backup_list` | `BackupManager.list_backups()` |
| `backup_verify` | `BackupManager.verify_backup()` |
| `restore_plan` | `RestoreManager.restore_plan()` |
| `restore_recovery_plan` | `build_recovery_plan(backup_manager=..., db_path=..., config_dir=..., backup_id=...)` |

No other Backup/Restore/Recovery MCP tool exists. The MCP layer is a thin
transport adapter only: `src/mcp_server/tools/backup_tools.py` and
`src/mcp_server/tools/restore_tools.py` contain no business logic beyond
result-to-dict serialization and exception-to-structured-response mapping.
There is no CLI subprocess routing anywhere in either module — every
domain decision is made by the same core functions the CLI already calls,
unmodified.

## Composition architecture

- `ApplicationServices`/`AppContext` remains **unchanged** — no
  `backup_manager`/`restore_manager` field was added to it.
- `RestoreServices` (already existing, already used by `src/cli/main.py`)
  is reused as a second, independent MCP context, `RestoreContext`.
- `mcp_server/context.py`'s new `build_restore_context()` is a thin
  delegation to the already-existing `build_restore_services()`.
- `RestoreServices` is built exactly once, at MCP server startup, alongside
  `ApplicationServices` — not lazily, not per-call.
- The six pre-existing MCP tool modules continue receiving `ctx`
  (`AppContext`) exactly as before; only `backup_tools`/`restore_tools`
  receive `restore_ctx` (`RestoreContext`).
- `src/redline_core/runtime/composition.py` was **not modified** — zero
  diff, confirmed by `git diff --stat`.

**Resource-lifecycle reason this is safe:** `BackupManager.__init__` and
`RestoreManager.__init__` hold only plain config/path values, never a live
connection or handle. `BackupManager.list_backups()` never touches
`REDLINE_DB_PATH` at all (pure filesystem read). `BackupManager.
verify_backup()`'s only SQLite contact is a short-lived, read-only
connection to the **backup package's own** database copy, closed in a
`finally` block before returning — never the live database.
`RestoreManager.restore_plan()` and `build_recovery_plan()` do touch the
live database, via `probe_quiescence()` — but that function opens a
transient connection, attempts `BEGIN IMMEDIATE`, and always rolls back and
closes before returning; it is by design safe to run concurrently with
other live connections, since detecting another connection's write lock is
the entire point of the probe. No file handle, SQLite handle, Resolve
handle, or lock is held by any of these objects across or between calls.
Building `RestoreContext` once, alongside `AppContext`, therefore carries
no more resource risk than `AppContext` already does on its own.

## Safety boundary: the permanent `mcp_stopped` invariant

Mission 1B-B does **not** expose: `backup_create`, `RestoreManager.
restore()`, `execute_recovery()`, degraded-source capture creation as an
MCP mutation, disposition, database/config replacement,
`RecoveryAuthorization`, `QuiescenceAttestations`, any fabricated operator
attestation, automatic rollback, automatic retry, automatic resume,
self-healing, Control Room mutation, Resolve interaction, or
scheduled/cloud/remote Restore.

**This is a permanent architecture invariant, not a temporary scope
choice, and not something a future mission could simply lift by adding
tool wrappers.** `QuiescenceAttestations` — required by both ordinary
Mission 1B-A1 `RestoreManager.restore()` and Mission 1B-A2-3
`RecoveryAuthorization` — requires an itemized `mcp_stopped` attestation.
An MCP tool call occurs, by construction, while the MCP server process
that received it is running and actively dispatching that call. There is
no code path by which a call arriving *through* the MCP server can make
"the MCP server is stopped" a true statement at the moment of the call. No
tool in `backup_tools.py`/`restore_tools.py` may ever accept or fabricate
a parameter intended to produce `mcp_stopped=True` on an MCP-originated
call. Building an MCP tool that calls `RestoreManager.restore()` or
`execute_recovery()` would require either silently lying on the caller's
behalf, or redesigning the attestation model itself — both are out of
bounds. Mutating Restore/Recovery exposure over MCP is therefore
**intentionally absent, not merely deferred by convenience**, and this
finding is expected to remain true regardless of future mission scope
unless the underlying attestation architecture itself is deliberately
redesigned by a separate, explicit Founder decision.

## Path disclosure

MCP serialization exposes only path/filesystem fields already present on
the authoritative core result models (`BackupRecord`,
`BackupVerificationResult`, `RestorePlanResult`, `RecoveryPlanResult`,
`SourceSideAssessment`, `SidecarAssessment`) — the same convention every
other MCP tool in this server already follows (episode `folder_path`,
archive `archive_path`, etc. are likewise returned verbatim). No new path
field was added. No Mission-1B-B-specific redaction framework was
introduced.

## Tool-count evidence: 20 → 24

**Pre-existing discrepancy found and resolved:** `README.md` already
stated 20 MCP tools (correct). `docs/MCP_TOOLS.md`'s intro line incorrectly
stated 19, while that same document's own "Verified" section already said
20 — an internal self-contradiction predating this mission. Source
enumeration (every `@mcp.tool()`-decorated function across the six
pre-existing modules) and a live installed-wheel registration proof both
independently confirmed **20** as the actual, correct pre-Mission-1B-B
baseline. `docs/MCP_TOOLS.md`'s intro was corrected to state this, as
source-derived truth, not repeated as 19.

**Post-implementation: 24 tools total.** Exact delta: `backup_list`,
`backup_verify`, `restore_plan`, `restore_recovery_plan`. No existing tool
was removed, renamed, or behavior-changed.

## Installed-wheel evidence — precise characterization

`tests/unit/test_installed_mcp_startup_smoke.py` builds and installs a
real Redline OS wheel into an isolated venv, installs a repository-
established lightweight `mcp` stub wheel (because the external
third-party `mcp` package was unavailable in the implementation
environment), and executes the real `create_server(use_mock_resolve=True)`
registration path in a subprocess against that installed package.

**This is accepted proof of Redline OS's own registration/composition
behavior — it is not, and must not be described as, independent
validation of the external third-party `mcp` package itself.** The stub
only reproduces `FastMCP`'s `tool()`-decoration/registration shape; it
does not exercise the real package's transport, protocol, or runtime
behavior.

## Deferred ownership

Mission 1B-B intentionally does **not** resolve, and this closure does
**not** assign to any new or existing mission:

- MCP backup creation
- MCP Restore execution
- MCP Recovery execution
- a future human-authorization mechanism for non-CLI destructive
  operations
- Control Room mutation
- live production proof (of Backup, Restore, Recovery, or this MCP
  surface)
- scheduled/cloud/remote Restore
- automatic healing/retry/rollback/resume

No repository evidence currently assigns any of these to a named future
mission; this closure does not manufacture one.

## Documentation updates made by this closure

- **Created:** `docs/V2_MISSION_1B_B_CLOSURE_2026-08-19.md` (this
  document).
- **Updated:** `docs/CHANGELOG.md` — new top entry recording this
  checkpoint closure.
- **Already updated at the accepted implementation checkpoint (not
  touched further by this closure, because no statement in them is false):**
  `README.md`, `docs/MCP_TOOLS.md`, `docs/ARCHITECTURE.md` §5/§5.1,
  `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §17.

### Out-of-scope observation (found, not corrected)

`docs/ARCHITECTURE.md:128` (the "Restore Manager (Mission 1B-A1)" row in
the §4 manager table) reads, in part: *"DEGRADED_SOURCE/MISSING_SOURCE
recovery (Mission 1B-A2) and Mission 1B-B are not implemented."* This
sentence describes what the `RestoreManager` **class itself** implements —
`execute_recovery()` (Mission 1B-A2) is a free function, not a
`RestoreManager` method, so the Mission 1B-A2 half of that clause may
still be narrowly accurate read that way; the Mission 1B-B half is now
stale, since this closure's read-only MCP planning surface does exist and
does call `RestoreManager.restore_plan()` directly. This line predates
Mission 1B-B, was not part of the accepted implementation checkpoint, and
touching it risks either an incomplete fix (leaving the ambiguous 1B-A2
half unaddressed) or reinterpreting a sentence about `RestoreManager`'s own
class-level scope that this mission has no authorization to redraft. Left
unchanged, deliberately, and reported here for Control Room to resolve
separately rather than silently corrected.

## Implementation checkpoint inventory

Checkpoint commit: `30e12b8c46f6209033712efe6317f8c97499545f` (`feat: add
Mission 1B-B MCP read surface`), parent
`ee9ab2e85838da1ebbe251f7fc8c1507305b4c25`.

Exactly 10 paths changed — 7 modified, 3 new:

```
M  README.md
M  docs/ARCHITECTURE.md
M  docs/BACKUP_RECOVERY_ARCHITECTURE.md
M  docs/MCP_TOOLS.md
M  src/mcp_server/context.py
M  src/mcp_server/server.py
A  src/mcp_server/tools/backup_tools.py
A  src/mcp_server/tools/restore_tools.py
M  tests/unit/test_installed_mcp_startup_smoke.py
A  tests/unit/test_mcp_backup_restore_tools.py
```

No `src/redline_core/*` (Backup/Restore/Recovery core) or
`src/redline_core/runtime/composition.py` production file changed.

## Validation evidence

Focused MCP + Backup/Restore/Recovery set (Python 3.11.9): **391 passed, 0
failed.**

Broad portable (`tests/unit`+`tests/integration`, `-m "not workstation"`,
Python 3.11.9): **3323 passed, 18 skipped, 42 deselected, 0 failed.**
Exact additive accounting: prior accepted baseline **3302 passed** +
Mission 1B-B's **21 new tests** = **3323 passed** — zero other change.

Workstation tier: **not required, not run** — no historically pinned/
mutation-bearing source file (`src/cli/main.py`) was touched; confirmed
zero diff.

`git diff --check`: clean at every stage (only benign CRLF/LF autocrlf
notices, no actual whitespace errors).

Protected files (`src/redline_core/backup/*`, `src/redline_core/
restore/*`, `src/redline_core/runtime/composition.py`, `src/cli/main.py`,
and every Mission 1B-A2-established protected recovery file — `staging.py`,
`sidecar.py`, `quiescence.py`, `schema_fingerprint.py`,
`capture_package.py`, `sidecar_classification.py`, `recovery_planning.py`,
`restore_commands.py`, `recovery_planning_commands.py`): **zero diff.**

`v1.0.0` remains frozen at `a41eb57012fbd80ae1be536d8e91ab74f459bc32`. No
historical `RLC-E9901` pin was touched.

## Environmental evidence

One installed-wheel smoke attempt encountered a transient network/build-
isolation dependency-fetch failure (fetching `setuptools` for an isolated
build environment) before any code change was made. A retry, with no code
changes, passed cleanly, including the full 24-tool registration
assertion. This is recorded as environmental evidence of this sandbox's
network conditions, not an implementation regression — neither hidden nor
overstated.

## Production-proof boundary

Mission 1B-B is **NOT live-production-MCP-proven**. No live MCP client
exercise against a real, running production instance has occurred or is
claimed by this document. This is consistent with Mission 1A's, Mission
1B-A1's, and Mission 1B-A2's own unchanged production-proof status.
Production proof of this MCP surface (or of Backup/Restore/Recovery more
broadly) remains separate, not-yet-authorized future work, per established
repository precedent (production proof is never a precondition for
formally closing the implementation that makes that future proof
possible).

## Publication boundary

At drafting time:

```
HEAD:            30e12b8c46f6209033712efe6317f8c97499545f
origin/master:   ee9ab2e85838da1ebbe251f7fc8c1507305b4c25
ahead/behind:    1/0
```

Mission 1B-B is **not yet published**. No exact-head GitHub Actions CI run
yet verifies this checkpoint/closure HEAD. After a future closure commit is
created and published, that exact new HEAD must receive a terminal
**SUCCESS** GitHub Actions run before **CI-VERIFIED PUBLICATION** may be
declared for it — the 1B-A2-3 child's own already-recorded CI success does
not, and cannot, satisfy verification for a different, later HEAD.
Symmetrically, once that future verification succeeds, no further commit
should be created solely to record its run ID back into the repository
(the verification-loop-prevention rule already established for this
repository's mission lifecycle).

## Next authorization boundary

The next steps this document identifies — CLOSURE COMMIT of this document
and the accompanying `docs/CHANGELOG.md` update, PUBLICATION PUSH,
exact-head GitHub Actions CI verification of that new HEAD, any live
production MCP exercise, and any resolution of the deferred-ownership items
above — each require their own separate, explicit Founder authorization.
**This document does not authorize any of them.**

## Closure

Redline OS V2 Mission 1B-B (Backup / Restore / Recovery MCP Read Surface)
is, at the local-checkpoint level: **IMPLEMENTED**, **CHECKPOINTED
LOCALLY** at `30e12b8c46f6209033712efe6317f8c97499545f`, **NOT PUBLISHED**,
and **NOT CI-VERIFIED** for this checkpoint HEAD. It is **READY FOR
CLOSURE COMMIT / PUBLICATION SEQUENCE**. This document itself has not yet
been committed.

Mission 1B-B is **NOT live-production-MCP-proven**, consistent with
established repository precedent, and this is not a closure blocker. The
permanent `mcp_stopped` invariant (§ "Safety boundary" above) means
mutating Restore/Recovery exposure over MCP remains structurally absent,
not merely deferred. One out-of-scope documentation observation
(`docs/ARCHITECTURE.md:128`) was found and is reported, not silently
corrected. Deferred ownership items are recorded as unowned, not assigned
to a new mission this closure does not have evidence for.
