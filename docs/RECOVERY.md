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

Blocked or dangerous action:

- **There is no restore capability in Mission 1A.** `redline backup restore`
  does not exist. A verified backup at this point is confirmed-good evidence
  and provenance, not yet a way back to a running system — restoring it is
  Mission 1B, separate, not-yet-authorized work (see
  `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §12).
- Do not attempt to reconstruct `redline.db` by hand-editing SQLite as a
  substitute for restore.

Expected result:

- The operator knows whether a verified, usable backup exists for this
  database/config pair, and has the exact `backup_id`, manifest SHA-256, and
  content-set digest needed to hand to a future, separately authorized
  restore mission — but this runbook does not, and Mission 1A does not,
  perform that restore.

See `docs/BACKUP_RECOVERY_ARCHITECTURE.md` for the complete Backup +
Verification architecture, and `docs/CONFIG.md` for `paths.backup_path`
configuration.
