# Recovery and Restart Runbook

This runbook describes how to recover from interrupted Redline OS work using
the behavior that exists today. It does not add rollback, reconciliation,
cleanup, or repair behavior.

## 1. Purpose and safety rules

Redline OS persists pipeline state in SQLite and mutates external Resolve
projects through the Resolve adapter. Those systems can disagree after a
process exit, a CLI interruption, an exception, or a Resolve-side failure.

Safety rules:

- Inspect before retrying.
- Treat SQLite as the source of truth for Redline pipeline status.
- Treat Resolve as the source of truth for media-pool, timeline, marker, clip,
  and render-queue contents.
- Use `--force` only after inspecting both SQLite and Resolve.
- Do not treat `--force` as rollback, verification, cleanup, or repair.
- Do not mutate SQLite directly as a routine recovery procedure.
- Preserve logs, terminal output, manifest files, Resolve project names, and job
  IDs before taking corrective action.

## 2. What Redline OS persists

SQLite stores episode lifecycle state, paths, render-job rows, archive records,
and the persisted assembly-claim fields used to protect episode assembly:

- `episodes.status`
- `episodes.project_path`
- `episodes.folder_path`
- `episodes.assembly_claim_token`
- `episodes.assembly_claimed_at`
- `render_jobs.resolve_job_id`
- `render_jobs.status`
- `archives`

Use read-only Redline commands first:

```bash
redline episode status 1 --mock-resolve
redline episode list --mock-resolve
redline archive list
```

These commands report persisted Redline state. They do not prove that Resolve
media, timelines, markers, clips, or render jobs match that state.

## 3. What Resolve may retain externally

Resolve may retain mutations even when Redline OS reports a failure. Current
known retained state can include:

- imported Media Pool items
- a created or reused timeline
- added markers
- appended timeline clips
- a changed current media-pool folder or current timeline
- a queued render job
- a cancelled render job preserved in the render queue

Resolve project inspection is therefore a separate step from Redline status
inspection. Use the Resolve UI or a controlled live probe appropriate to the
operation. Do not infer Resolve state from SQLite alone.

## 4. First response after interruption

Observed condition: a CLI process, MCP server, Python process, or Resolve API
call was interrupted before the operator saw a final success result.

State to inspect:

- terminal output from the interrupted command
- `logs/redline_os.log` or the configured `REDLINE_LOG_DIR`
- `redline episode status <episode_number> --mock-resolve`
- `redline episode list --mock-resolve`
- Resolve project, timeline, media pool, and render queue if the operation could
  have touched Resolve

Safe next action:

- If the interrupted operation was read-only, rerun it after preserving the
  error output.
- If the interrupted operation could mutate Resolve or SQLite, inspect both
  systems before retrying.
- If an assembly claim remains, follow the assembly-claim recovery section.

Blocked or dangerous action:

- Do not rerun mutating commands repeatedly to see whether they eventually
  succeed.
- Do not delete or edit SQLite rows as the ordinary way to clear uncertainty.
- Do not assume mock Resolve behavior proves the real Resolve project is clean.

Expected result:

- The operator knows whether the next action is a normal retry, a blocked retry,
  or a forced retry after manual inspection.

## 5. Episode assembly recovery

Observed condition: `redline episode assemble <manifest_path>` fails, exits
early, or is interrupted.

State to inspect:

- persisted episode status
- assembly claim fields on the episode row, if visible through diagnostic
  inspection
- Resolve project named by the episode record
- imported media in the target bin
- timeline existence and marker contents
- appended timeline clips
- terminal output and Redline logs

Safe next action:

- If the episode status is still one of `Created`, `Assets Verified`,
  `Media Organized`, or `Timeline Built` and no unresolved assembly claim is
  present, a normal retry may be attempted.
- If the episode is `Failed`, inspect Resolve and SQLite before using
  `--force`.
- If an unresolved claim remains, treat the prior attempt as uncertain and
  follow the assembly-claim recovery section.

Blocked or dangerous action:

- Do not use `--force` before inspecting Resolve project state.
- Do not assume a failed assembly rolled back imported media, markers, or clips.
- Do not retry terminal statuses: `Assembled`, `Render Queued`, `Rendered`, and
  `Archived` are blocked even with `--force`.

Expected result:

- A normal retry proceeds only for manager-approved pre-assembly states.
- A forced retry proceeds only for `Failed` or unresolved-claim states after
  operator review.
- Terminal or downstream statuses remain blocked.

## 6. Assembly-claim recovery

Observed condition: an episode has an active or unresolved assembly claim after
a prior assembly attempt.

State to inspect:

- `episodes.status`
- `episodes.assembly_claim_token`
- `episodes.assembly_claimed_at`
- Resolve project contents for that episode
- logs around the claim acquisition, failed stage, and process exit

Safe next action:

- Treat the episode as an uncertain outcome.
- Inspect Resolve and SQLite before deciding whether a forced retry is safe.
- Use `redline episode assemble <manifest_path> --force` only when the operator
  accepts the risk of duplicate media, markers, or clips.

Blocked or dangerous action:

- Do not clear the claim manually as routine recovery.
- Do not start a second normal assembly while a claim is active.
- Do not treat claim age alone as proof that Resolve state is clean.

Expected result:

- Ordinary retry is blocked.
- `--force` may take over a failed or unresolved claim through the manager-owned
  compare-and-swap claim policy.

## 7. Using `--force` safely

Observed condition: `episode assemble` reports a failed or unresolved-claim
episode and the operator is considering `--force`.

State to inspect:

- Redline episode status and paths
- Resolve project named by the episode row
- media pool target bin
- timeline existence
- marker count and placement
- timeline clip placement
- logs from the failed attempt

Safe next action:

```bash
redline episode assemble episode.yaml --force
```

Add `--mock-resolve` only when recovering a mock/test workflow. Use the real
Resolve-backed command only when the intended target is the real Resolve project
and the operator has inspected it.

Blocked or dangerous action:

- Do not use `--force` on `Assembled`, `Render Queued`, `Rendered`, or
  `Archived` episodes; Redline rejects those states.
- Do not use `--force` as cleanup.
- Do not expect `--force` to remove duplicated imports, markers, or clips.

Expected result:

- The CLI passes `--force` through to the manager-owned
  `allow_unsafe_retry=True` parameter.
- `EpisodeManager` remains the sole authority on whether the retry may proceed.

## 8. Render recovery by status

Render status is split between Redline SQLite rows and Resolve's render queue.
`RenderManager` owns Redline render-job policy; the real Resolve adapter owns the
Resolve API boundary.

### Unknown or missing Resolve job

Observed condition: Resolve no longer reports the job ID.

State to inspect:

- Redline `render_jobs` row
- Resolve render queue
- command logs

Safe next action:

- Treat the job as unresolved until operator inspection confirms whether it was
  deleted, completed elsewhere, or never queued successfully.

Blocked or dangerous action:

- Do not invent a terminal Redline status without evidence from Resolve or
  operator review.

Expected result:

- `get_render_status()` maps missing Resolve jobs to Redline's existing
  `unknown` status.

### Queued render

Observed condition: Resolve reports the job as ready/queued.

State to inspect:

- Resolve job ID
- Resolve queue entry
- Redline render-job row

Safe next action:

- `cancel_render()` may delete the queued Resolve job.

Blocked or dangerous action:

- Do not assume queue deletion updates unrelated queued jobs.

Expected result:

- Resolve removes the queued job.
- Redline marks the render row cancelled when `RenderManager.cancel_render()`
  completes.

### Active render

Observed condition: Resolve reports the requested job as rendering.

State to inspect:

- whether the requested job is the sole active render
- Resolve `IsRenderingInProgress()`
- Resolve render queue
- Redline render-job row

Safe next action:

- `cancel_render()` may call project-scoped `StopRendering()` only after
  verifying the requested job is the active render.

Blocked or dangerous action:

- Do not call project-scoped stop behavior merely because any job is rendering.
- Do not delete the stopped job as part of Redline cancellation.

Expected result:

- Resolve stops rendering.
- The stopped job remains in Resolve with status `Cancelled`.
- Redline can mark its render row cancelled after the adapter returns.

### Terminal render

Observed condition: Resolve reports `Complete`, `Failed`, `Cancelled`, or
`Canceled`.

State to inspect:

- Resolve job status
- Redline render-job row
- output files, if completion is expected

Safe next action:

- Use read-only inspection first.

Blocked or dangerous action:

- Do not cancel terminal jobs through Redline; terminal statuses are rejected.
- Do not delete Resolve queue entries as a routine Redline recovery step.

Expected result:

- Redline refuses cancellation of terminal Resolve render states.

## 9. SQLite/Resolve drift

Observed condition: Redline status and Resolve project state do not appear to
match.

State to inspect:

- SQLite episode status and paths
- SQLite render-job rows
- Resolve project name
- Resolve media pool
- Resolve timelines, markers, and clips
- Resolve render queue
- Redline logs

Safe next action:

- Preserve evidence and decide which system is authoritative for the question:
  SQLite for Redline pipeline state, Resolve for actual project/media/timeline
  and render-queue contents.
- Use existing Redline commands only when their manager-owned policy allows the
  operation.

Blocked or dangerous action:

- Do not manually rewrite SQLite to make it match Resolve as a routine
  procedure.
- Do not manually clean Resolve and then assume Redline has observed that
  cleanup.
- Do not rely on `episode status` as a Resolve health check.

Expected result:

- The operator has enough evidence to choose a normal retry, a forced retry,
  manual external cleanup outside Redline, or escalation.

## 10. What Redline OS does not repair automatically

Redline OS does not automatically repair or roll back:

- partial media imports
- created timelines
- duplicate markers
- appended clips
- changed current Resolve folders or timelines
- queued render jobs that were not persisted after a job-ID extraction failure
- cancelled render entries preserved in Resolve
- moved archive folders after mid-archive failures
- SQLite rows after manual Resolve edits
- Resolve projects after manual SQLite edits

These are current V1 limitations, not operator mistakes.

## 11. Escalation and evidence to preserve

Before escalating or attempting a risky retry, preserve:

- exact command and arguments
- terminal output
- `redline_os.log`
- `REDLINE_CONFIG_DIR`, `REDLINE_DB_PATH`, and `REDLINE_LOG_DIR`
- manifest file used for assembly
- episode number and episode ID
- Resolve project name
- timeline name
- Resolve render job ID
- observed Resolve status
- whether `--mock-resolve` or real Resolve was used

Do not discard logs or manually clean Resolve before recording the state that
caused the recovery decision.

## 12. Database or configuration file loss (Mission 1A)

Observed condition: `redline.db` (at `REDLINE_DB_PATH`) or the active
configuration directory (at `REDLINE_CONFIG_DIR`) is missing, deleted, or
corrupted. Every scenario in this runbook above assumes the database file
exists and is queryable — this section covers the case where it does not.

State to inspect:

- whether `REDLINE_DB_PATH` still resolves to a file at all
- whether the file opens and passes `PRAGMA integrity_check`
- whether a Mission 1A backup exists: `redline backup list`

Safe next action:

- If a backup exists, independently re-verify it before relying on it:
  `redline backup verify <backup_id>`.
- Preserve whatever remains of the current database/config state before
  taking any further action — do not delete a partially corrupted file
  assuming a backup will cover it without first verifying that backup.
- As of Mission 1B-A1, a HEALTHY_SOURCE restore capability exists: run
  `redline backup restore-plan <backup_id>` first (read-only) to see
  whether every precondition would currently pass. This still requires
  explicit Founder authorization to actually execute — see below.
- As of Mission 1B-A2-1, if the database or config is not healthy, run
  `redline backup restore-recovery-plan <backup_id>` (read-only) to see
  exactly how each side is classified (`HEALTHY`/`DEGRADED`/`MISSING`) and
  whether a future recovery path would be architecturally eligible
  (`RECOVERABLE`/`RECOVERY_BLOCKED`) and why. **This reports and predicts
  only — it creates no backup, no capture, and mutates nothing.**
- As of Mission 1B-A2-3, if `restore-recovery-plan` reports the source
  would be architecturally eligible, **degraded/missing-source recovery
  *execution* now exists**: `redline backup restore-recovery <backup_id>`.
  This is a separate, DESTRUCTIVE capability from every command above it —
  see "Degraded/missing-source recovery execution" below for its exact
  safety contract before ever running it. **A live production recovery
  attempt remains Founder-authorized, case-by-case work, exactly like a
  live production Restore** — the capability existing in the codebase is
  not itself authorization to run it against
  `C:\Users\pj198\RedlineOSLive\Runtime\redline.db` or
  `...\production-config`.

Blocked or dangerous action:

- **A live production Restore remains Founder-authorized, case-by-case
  work.** Mission 1B-A1 implements the `redline backup restore` capability
  itself, but does not itself authorize running it against
  `C:\Users\pj198\RedlineOSLive\Runtime\redline.db` or
  `...\production-config` — that is a separate decision every time, per
  this repository's operating instructions (`CLAUDE.md` §1: "Agents advise.
  Paul decides.").
- `redline backup restore` is **HEALTHY_SOURCE only**: it requires the
  target backup to independently re-verify immediately before restoring.
  If the current database/config source is itself degraded or missing,
  `redline backup restore` cannot be used — see "Degraded/missing-source
  recovery execution" below for the command that can.
- Degraded-source *capture* (`redline_core.restore.capture_manager.
  build_degraded_source_capture()`, Mission 1B-A2-2) is evidence only —
  **never a Mission 1A backup, never a normal Restore source, and never
  listed, verified, or restored by any command.** It still has no
  standalone CLI command of its own: it is invoked automatically, as one
  mandatory step, by every `redline backup restore-recovery` attempt (see
  below) — an operator cannot trigger a capture in isolation, and a
  capture built by one recovery attempt is never reused as input by
  another.
- `redline backup restore` never accepts "latest" — an exact `backup_id`
  is always required — and requires repeating that exact `backup_id` via
  `--confirm-backup-id` plus three separate, itemized attestation flags
  (MCP stopped, Control Room stopped, no other Redline CLI operation in
  flight). Do not attempt it while any of those three is untrue.
- Database and config replacement are **not atomic with each other** (see
  `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §13.6) — an interruption between
  them leaves the live config directory genuinely missing (recoverable by
  hand from the restore-ID-scoped superseded config path the error message
  names, but not automatically). There is no automatic rollback, retry, or
  resume of an interrupted restore anywhere in this mission — inspect the
  restore transaction journal under
  `<paths.backup_path>/restore_journal/<restore_id>/` and the preserved
  artifacts by hand.
- Do not attempt to reconstruct `redline.db` by hand-editing SQLite as a
  substitute for restore.

### Degraded/missing-source recovery execution (Mission 1B-A2-3)

Observed condition: `redline backup restore-recovery-plan <backup_id>`
reports the degraded or missing source would be architecturally eligible
(`RECOVERABLE`, not `RECOVERY_BLOCKED`), and the operator is considering
`redline backup restore-recovery <backup_id>`.

This is a **separate, DESTRUCTIVE capability** from `redline backup
restore` (HEALTHY_SOURCE only) — it exists specifically for the case
`restore` cannot handle: the current database and/or config is itself
`DEGRADED` or `MISSING`.

State to inspect before attempting it:

- the exact `restore-recovery-plan` output for this `backup_id`
- whether MCP, Control Room, and every other Redline CLI operation are
  genuinely stopped
- whether the operator genuinely understands and accepts the disposition
  and no-automatic-rollback doctrine below

Safe next action:

```bash
redline backup restore-recovery <backup_id> --confirm-backup-id <backup_id> \
    --attest-mcp-stopped --attest-control-room-stopped --attest-no-other-cli-operation \
    --attest-disposition-understood --attest-no-automatic-rollback
```

Every one of the five attestation flags is required explicitly — there is
no blanket `--yes`, and `--confirm-backup-id` must repeat the exact
`backup_id` being recovered. **Every attempt builds and reverifies its own
brand-new degraded-source capture before touching anything live** — there
is no `--capture-id`, and a capture from a prior attempt (successful or
not) is never reused as input to a later one.

Blocked or dangerous action:

- **`RECOVERY_BLOCKED` cannot be overridden.** No flag on this command
  bypasses it, at either of the two points it can occur (initial
  validation, before any capture; fresh reclassification, after capture).
  If `restore-recovery-plan` (or this command's own initial check) reports
  `RECOVERY_BLOCKED`, escalate — do not attempt manual reconstruction of
  an unsafe filesystem object or a structurally missing installation
  parent.
- **There is no automatic rollback, retry, or resume of an interrupted or
  failed recovery attempt**, exactly like `redline backup restore`. A
  disposition step that already completed (an existing live object moved
  aside to a restore-ID-scoped superseded path, never deleted) remains
  exactly where it was left — inspect the recovery journal under
  `<paths.backup_path>/restore_journal/<restore_id>/` (`attempt_kind:
  "recovery"`) and the preserved superseded/capture artifacts by hand
  before deciding the next step.
- A degraded-source capture built by a recovery attempt is preservation
  evidence, never a restore point of its own — do not attempt to point
  any command at a `degraded_source_captures/<capture_id>/` package
  directly; it is not a Mission 1A backup and is structurally rejected as
  one.
- A live production recovery attempt is Founder-authorized, case-by-case
  work, exactly like a live production Restore — see the "Safe next
  action" note above.

Expected result:

- If `RECOVERY_BLOCKED`, the attempt stops before any live-target
  mutation, with the exact blocking reason journaled.
- If not blocked, the degraded or missing source is replaced with the
  verified target backup's content — with any existing wrong-type object
  or unreadable database moved aside (never deleted) first — and the
  attempt reaches the same `VERIFIED_SUCCESS` proof `redline backup
  restore` reaches.
- On any failure at any step, the process stops; nothing already
  completed is undone automatically.

Expected result (general, both `restore` and `restore-recovery`):

- The operator knows whether a verified, usable backup exists for this
  database/config pair, has the exact `backup_id` needed, and (as of
  Mission 1B-A1) has a `redline backup restore-plan`/`redline backup
  restore` path available for Founder-authorized use — with the explicit
  understanding that a live production Restore is a separate authorization
  from the capability existing in the codebase. If the source itself is
  degraded or missing, the operator additionally knows (as of Mission
  1B-A2-1) exactly how each side is classified and whether a future
  recovery path would be architecturally eligible, and (as of Mission
  1B-A2-3) has a `redline backup restore-recovery` path available for
  Founder-authorized use when it is not `RECOVERY_BLOCKED`.

See `docs/BACKUP_RECOVERY_ARCHITECTURE.md` (§1-§11 for Backup +
Verification, §13 for Mission 1B-A1 Restore, §14 for Mission 1B-A2-1
Source Classification + Read-Only Recovery Planning, §15 for Mission
1B-A2-2 Degraded-Source Capture, §16 for Mission 1B-A2-3 Recovery
Execution + Journal/Evidence Integration) for the complete architecture,
and `docs/CONFIG.md` for `paths.backup_path` configuration.
