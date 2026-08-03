# Changelog

## Unreleased - Phase 14 Mission 39I.2a: Dry-Review Gate 1 Metadata Correction

- Corrects the Mission 39I harness repository gate so `.claude/` can remain
  an expected untracked path even when the harness subprocess can read a
  global Git ignore file that hides it from default `git status --porcelain`.
- Records raw default Git status, tracked-only status, untracked-path metadata,
  and `.claude/` Git metadata separately before parsing. `.claude/` remains
  verified through Git metadata only and must remain untracked.
- Adds focused regression coverage for the hidden-by-ignore case without
  inspecting `.claude/` contents.
- Does not run the harness with `--execute`, access Resolve, call
  `AddRenderJob()`, execute the queue command, change SQLite/configuration, or
  authorize a live Mission 39I attempt.

## Unreleased - Phase 14 Mission 39I.1: Controlled Queue Attempt Script Review Harness

- Adds a fail-closed Mission 39I live queue-attempt harness at
  `scripts/mission39i_live_queue_attempt.py` for review before any live use.
  The harness records a timestamped evidence package under the operating
  system temporary directory, encodes the seven preflight gates, requires an
  explicit `--expected-repository-commit` live pin supplied by the reviewed
  contract/authorization record, and fixes the future live command to the
  Python 3.11 module form:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m cli.main render queue RLC-E9001 broadcast_master`.
- The harness defaults to dry review and stops before Resolve access. Future
  live execution requires `--execute`, the reviewed script SHA-256, the exact
  reviewed repository commit, the exact founder authorization phrase, and a
  manual observation JSON file.
- Adds mocked unit coverage for the fixed command, dry-review stop boundary,
  script-hash guard, explicit repository-commit pin validation, sanitized
  queue inventory, acceptance-not-observed classification, and the rule that
  structural queue changes alone do not prove acceptance.
- Does not authorize or perform a live Resolve connection, `AddRenderJob()`,
  render start, render cancellation/deletion, configuration change, dependency
  change, SQLite mutation, or Windows YAML fixture repair.

## Unreleased - Phase 14 Mission 39H: Broadcast Master Queue Diagnostic Enrichment

- Improves post-`AddRenderJob()` diagnostics without changing render queue
  submission behavior, retry behavior, cleanup semantics, production
  configuration, or the authoritative job-ID multiset acceptance rule.
- Adds sanitized queue-inventory diagnostics for reconciliation failures:
  queue item counts, item types, dictionary key names, usable job IDs,
  missing-ID counts, non-dictionary item counts, and a diagnostic-only
  structural before/after comparison. Raw queue object values are not logged.
- Expands the pre-add diagnostic context with requested project, requested and
  current timeline names, preset name, normalized target-directory
  existence/type/read-access status, and sanitized render-settings keys/value
  types when Resolve exposes them.
- Maps MCP `queue_render` failures for `RenderQueueAcceptanceNotObservedError`
  and `RenderQueueIdentityUnresolvedError` to the same category strings used by
  the CLI while preserving the existing `success`/`error` response fields.
- Does not perform a live Resolve queue submission, start rendering, inspect a
  live render queue, change SQLite schema or data, alter environment variables,
  or authorize another Broadcast Master queue attempt.

## Unreleased - Phase 14 Mission 39F: Formal Mission 39D/39E Closure Record

- Formally closes Mission 39D. The queue-failure classification and diagnostic
  work is complete, the authorized one-shot Mission 39D.3 live revalidation
  completed, Resolve did not observably accept a new queue job, postflight
  cleanup was verified, and queue acceptance is not characterized as
  successful.
- Formally closes Mission 39E. The workstation configuration investigation and
  read-only validation are complete: Python 3.11.9 is operational for the
  current Resolve integration, Python 3.13 is incompatible with the current
  Resolve scripting import because it crashes with Windows access violation
  `0xC0000005`, and the read-only adapter connection observed
  `RLC-E9001_MASTER`, `RLC-E9001_TIMELINE`, zero render queue jobs, rendering
  inactive, and probe exit code `0`.
- Keeps Phase 14 open and BLOCKED. Broadcast Master queue acceptance remains
  unproven because Resolve returned an empty `AddRenderJob()` result and no
  new queue job ID was observed. No further live queue submission is
  authorized without a new root-cause investigation, a separately reviewed
  attempt contract, and fresh explicit founder authorization.
- Documentation-only closure record. No application code, tests,
  configuration, dependencies, scripts, SQLite, environment variables, Resolve
  state, or render queue state changed.

## Unreleased - Phase 14 Mission 39D.3: Live Queue Revalidation and Phase Checkpoint

- Performed one fully reviewed, freshly authorized, one-shot live queue
  revalidation against the disposable `RLC-E9001_MASTER` project, executed
  against published commit `2e36a41` under the Mission 39D.2 behavior. All
  seven ordered preflight gates passed (publication pin including local
  `origin/master` and live remote `refs/heads/master`, filesystem,
  environment, read-only SQLite, read-only Resolve, and a fresh Gate 7
  re-observation immediately before launch); the production
  `render queue RLC-E9001 broadcast_master` command was invoked exactly
  once.
- `AddRenderJob()` again returned an empty string. The pre-add diagnostic
  context captured genuinely live values this time — `render_format='mov'`,
  `render_codec='DNxHRHQX_10'` — confirming the expected Broadcast Master
  output format/codec were observed as active at the moment of the call.
  This rules out an absent or different format/codec observation; it does
  not identify the cause or rule out other Resolve-side conditions. The
  root cause remains unresolved. The result was classified
  `RenderQueueAcceptanceNotObservedError`. A temporary active-output claim
  was acquired before the Resolve call and released after the failure, per
  `RenderManager.queue_render()`'s existing claim/release sequence;
  postflight found zero render-job rows and zero active output claims, the
  episode remained `created`, no output file appeared, and the repository
  remained unchanged.
- Evidence directory:
  `%TEMP%\redline-mission39d3-live-revalidation-20260801T194713957967Z`.
  Reviewed script SHA-256:
  `39AE6DC8D891185F2A6CEB778A8D0FDC13E24F7126CABB59E133C2A6C429B0EC`.
- This is the third controlled live attempt against the disposable
  episode. Across all three, the live queue path failed closed and ended
  with consistent postflight state; the attempts successively exposed the
  missing-ID condition (pre-39D.1), validated the identity-unresolved
  diagnostics (post-39D.1.1), and validated the final
  acceptance-not-observed classification (this attempt). None has observed
  Resolve accept the request. No further live attempt is authorized
  without new root-cause investigation, a separately reviewed contract,
  and fresh explicit authorization.
- Phase 14 ("First Live Episode") is now recorded as **open and BLOCKED**
  rather than complete; the verified checkpoint evidence remains the Mission
  39D.3 result. See `docs/ROADMAP.md`. This was a documentation-only entry:
  no production code changed.

## Unreleased - Phase 14 Mission 39D.2: Empty AddRenderJob() Result Classification and Diagnostics

- Adds `RenderQueueAcceptanceNotObservedError(RenderJobError)` in
  `redline_core.resolve.exceptions`, a sibling of
  `RenderQueueIdentityUnresolvedError` reserved for one exact evidence
  shape: `AddRenderJob()` returned an empty string, the after-phase
  `GetRenderJobList()` snapshot itself succeeded, contained no unidentified
  item, and the before/after job-ID multisets are exactly equal (no new
  candidate). This is a positive claim -- no accepted render job was
  observed by job-ID comparison, not that the queue is unchanged in every
  respect -- rather than the weaker "identity is uncertain" claim
  `RenderQueueIdentityUnresolvedError` makes. Every other empty-string
  outcome (snapshot failure, unidentified item, multiple candidates) still
  raises `RenderQueueIdentityUnresolvedError` unchanged; multiset
  *equality* is required, not merely zero new candidates, so that an
  existing job disappearing with zero new candidates also stays on the
  more cautious path. This classification only runs when reconciliation
  does not already resolve to a single successful candidate; a
  disappearance that coincides with exactly one new candidate is
  unaffected and still succeeds directly, unchanged from before this
  slice.
- This is a direct response to a real, fully-authorized, evidence-preserved
  live Resolve queue attempt against the disposable `RLC-E9001_MASTER`
  project, which returned exactly this shape (`add_result_type=str,
  add_result_repr=''`, `before_job_ids=[]`, `after_job_ids=[]`,
  `candidate_job_ids=[]`) and was, until this slice, classified only as the
  more cautious identity-unresolved outcome.
- Adds `ResolveScriptAdapter._capture_pre_add_render_context()`, called once
  in `queue_render_job()` immediately after render settings are applied and
  before `AddRenderJob()`. Known request values (`timeline_name`,
  `target_dir`, `custom_name`) are the exact already-applied local values,
  never recomputed; the additional read-only `GetCurrentRenderFormatAndCodec()`
  inspection is fully defensive -- attribute discovery, invocation, and
  result parsing are wrapped in one try/except, since a bridged Resolve
  object's attribute lookup can itself raise a non-`AttributeError`
  exception that a bare `getattr(obj, name, default)` would not suppress --
  and never blocks `AddRenderJob()`. `render_mode` has no confirmed
  read-only getter on this adapter surface today and remains `"unavailable"`
  until one is verified against a live Resolve instance.
- Renames `_log_render_queue_identity_unresolved()` to
  `_log_render_queue_reconciliation_failure()` and adds a deterministic
  `reconciliation_outcome` field (`acceptance_not_observed` or
  `identity_unresolved`) plus the new pre-add context fields
  (`timeline_name`, `target_dir`, `custom_name`, `render_format`,
  `render_codec`, `render_mode`), appended after the existing diagnostic
  field bundle. Existing field names, order, and format are unchanged.
  Logging remains best-effort and cannot mask either domain exception.
- Adds a distinct CLI failure category, `"render queue acceptance not
  observed"`, in `cli.render_commands._run_render_queue`.
- `RenderManager` is unchanged -- its existing generic queue-exception
  boundary already releases the active SQLite claim and re-raises the
  original exception for any exception type, including this new one.
- Updates the render-queue failure-boundary section of
  `docs/ARCHITECTURE.md`, which had not been updated since before Mission
  39D.1 and still described every post-`AddRenderJob()` reconciliation
  failure as plain `RenderJobError`.
- Implemented and validated with mocks only -- no live Resolve connection,
  no `runtime\mission39d.sqlite` interaction, and no new queue attempt was
  made as part of this slice.

## Unreleased - Phase 14 Mission 39D.1.1: Route Queue-Identity Diagnostics to the Application Log

- The queue-identity diagnostic now emits through the configured `redline_os`
  application logger namespace and is proven to reach the rotating file
  handler in a temporary-directory test. Previously,
  `_log_render_queue_identity_unresolved()` logged via the adapter module's
  routine `logging.getLogger(__name__)` logger (`redline_core.resolve.adapter`),
  which is not a descendant of `redline_os` and therefore never reached
  `logs/redline_os.log` in a real run -- `configure_logging()`
  (`redline_core.logging.setup`) only installs handlers on `redline_os` and
  its descendants. A new dedicated `_render_queue_identity_logger =
  logging.getLogger("redline_os.resolve.adapter")` is used only at that one
  diagnostic call site; the adapter's routine logger is unchanged, and no
  other adapter log line was moved.
- Adds a direct file-routing proof to `tests/unit/test_logging_setup.py`
  (`test_application_child_logger_message_reaches_file`) confirming a child
  logger under `redline_os.*` reaches the configured rotating file handler.
- Adds an adapter-level integration test using a real `configure_logging()`
  call (rather than only `caplog`) to prove the queue-identity diagnostic
  bundle actually lands in `redline_os.log`. That test saves and restores
  the process-wide `redline_os` logger's handlers, level, and propagation
  around the real `configure_logging()` call so it cannot leak logging state
  into later tests in the same session, and closes only its own owned
  handlers so the temporary log file isn't held open on Windows.
- This is a logging-route correction only: queue behavior, exception
  classification, claim release, database finalization, episode status, and
  the CLI failure category are all unchanged. Implemented and validated
  with mocks and a real-but-isolated `configure_logging()` call only -- no
  live Resolve connection, no `runtime\mission39d.sqlite` interaction, and
  no new Mission 39D queue attempt.

## Unreleased - Phase 14 Mission 39D.1: Render Queue Identity-Unresolved Classification

- Adds `RenderQueueIdentityUnresolvedError(RenderJobError)` in
  `redline_core.resolve.exceptions`, raised only when `AddRenderJob()` has
  returned something other than explicit `False` and no direct job ID was
  obtained, and Redline subsequently cannot prove the identity of exactly one
  newly queued Resolve job — a snapshot fetch failure, an unidentifiable
  after-phase queue item, zero new candidates, multiple ambiguous candidates,
  or any other unexpected error while reconciling. Before-phase failures and
  standalone `list_render_jobs()` remain plain `RenderJobError`, unchanged.
- Adds `ResolveScriptAdapter._reconcile_after_add()`, replacing the inline
  after-phase reconciliation in `queue_render_job()`: a single
  `GetRenderJobList()` snapshot (`_get_render_jobs_snapshot`) is fetched once
  and reused for both ID extraction and diagnostic logging — no second
  Resolve observation. `_derive_new_render_job_id()`'s candidate logic is
  extracted into a pure `_compute_new_job_id_candidates()` helper but is
  otherwise behaviorally unchanged.
- Logs the full diagnostic bundle (`add_result` type/repr, before/after job
  IDs, after-list item count/types/keys, candidate IDs, and the underlying
  reconciliation error's type/repr) via one centralized, best-effort logging
  helper before raising. Logging is guaranteed never to mask the domain
  exception, including when `logger.error()` itself fails.
- Adds a distinct CLI failure category, `"render queue identity unresolved"`,
  in `cli.render_commands._run_render_queue`, so this condition is no longer
  indistinguishable from an ordinary Resolve connection or configuration
  failure.
- This slice is a response to an uncertain Mission 39D live queue outcome
  (`AddRenderJob()` returned no usable job ID) reviewed and reconciled
  read-only: the live workstation was left in a clean, consistent state
  (empty Resolve queue, zero SQLite render rows, episode status unchanged, no
  output file) — nothing required adoption or cleanup. This slice adds no
  polling, retries, sleeps, or new Resolve job-ID keys; those remain
  deferred pending evidence from a future controlled live attempt made with
  this logging in place. Implemented and validated with mocks only — no live
  Resolve connection or `runtime\mission39d.sqlite` interaction was made as
  part of this slice, and no new live queue attempt has been authorized.

## Unreleased - Phase 14 Mission 39C: Broadcast Master Preset Provisioning

- Activates the founder-approved Broadcast Master export filename standard in
  canonical config: `broadcast_master` now uses `filename_template:
  "{project_name}"`, `file_extension: ".mov"`, `output_subfolder: "exports"`,
  and `collision_policy: "reject"` while still mapping to the Resolve preset
  `Redline Broadcast Master`.
- Records live read-only Resolve verification for the disposable
  `RLC-E9001_MASTER` project: `GetRenderPresetList()` returned
  `Redline Broadcast Master`, `Preset found: True`, the queue remained empty,
  and no rendering was started.
- Leaves `youtube_1080p` incomplete and fail-closed until a separate approved
  YouTube export filename standard exists.
- Leaves Mission 39D not started; controlled live queue validation still
  requires review, commit, publication, and explicit authorization.

## Unreleased - Phase 14 Mission 39B: Deterministic Render Queueing

- Adds a deterministic render output contract to `render_presets.yaml`:
  queueable presets can provide `filename_template`, explicit
  `file_extension`, and `collision_policy: reject`.
- Keeps incomplete presets fail-closed before Resolve submission, SQLite
  render-job insertion, or output filesystem mutation. Mission 39C later
  activates the approved Broadcast Master `{project_name}.mov` standard while
  leaving unrelated presets incomplete unless separately approved.
- Adds immutable render output planning so one queue request calculates one
  canonical output directory, filename stem, extension, and full expected
  output path before Resolve or SQLite mutation.
- Changes render queue ordering so `RenderManager.queue_render(...)` rejects
  exact output-file collisions and matching inspectable Resolve queue jobs, then
  atomically claims the active output path in SQLite before Resolve queue
  mutation.
- Adds active-output uniqueness for `claiming`, `queued`, and `rendering`
  render jobs so concurrent queue requests cannot own the same output path.
- Changes Resolve queue submission to use an explicit prepared request:
  project, timeline, Resolve preset, `TargetDir`, and `CustomName`.
- Finalizes an active SQLite output claim only after Resolve accepts the job and
  returns a usable Resolve job ID. Resolve rejection releases the claim and
  creates no queued row.
- Adds best-effort compensation for database finalization failure after Resolve
  acceptance by deleting the newly accepted Resolve job; failed compensation
  surfaces a reconciliation-required error containing the Resolve job ID.
- Maps MCP render `ResolveError` failures for queue, status, and cancel into
  structured error responses, and includes `project_name` and `timeline_name`
  in MCP render-job responses.
- Keeps `render queue` enqueue-only: it does not call `StartRendering`, poll
  status, build, archive, overwrite, retry, or provision Resolve presets.
- Records that Mission 39B added the mechanism but did not yet activate a
  production filename standard.

### Verification

- Focused CLI render regression:
  `pytest tests/unit/test_cli_render.py -q` - 27 passed.
- Focused Mission 39B review-correction regression:
  `pytest tests/unit/test_config.py tests/unit/test_db.py
  tests/unit/test_render_manager.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_cli_render.py tests/unit/test_resolve_mock.py -q` - 134
  passed.
- Focused active-output claim correction regression:
  `pytest tests/unit/test_render_manager.py tests/unit/test_db.py -q` - 50
  passed.
- Focused MCP correction regression:
  `pytest tests/unit/test_mcp_tools.py -q` - 57 passed.
- MCP startup smoke and tool regression:
  `pytest tests/unit/test_mcp_tools.py
  tests/unit/test_installed_mcp_startup_smoke.py -q` - 58 passed.
- Render/config/composition regression:
  `pytest tests/unit/test_cli_render.py tests/unit/test_build_render_workflow.py
  tests/unit/test_render_manager.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_resolve_script_adapter_render_status.py
  tests/unit/test_resolve_script_adapter_render_cancel.py
  tests/unit/test_resolve_mock.py tests/unit/test_config.py
  tests/unit/test_composition.py tests/unit/test_db.py -q` - 199 passed.
- Mission 38A build preflight regression:
  `pytest tests/unit/test_cli_build.py -q` - 26 passed.
- Historical local Windows full unit suite:
  `pytest tests/unit -q` - 1236 passed, 9 skipped, and the same 24 accepted
  Windows YAML fixture failures.
- Published GitHub Actions CI for `origin/master` after the platform-neutral
  manifest-path assertion correction: 1268 passed, 1 skipped.
- Repository hygiene: `git diff --check`.

## Unreleased - Phase 14 Mission 38A: Build Preflight Before Mutable Composition

- Corrects the live-build preflight boundary discovered during the first
  Mission 38 disposable episode attempt: a missing `Episode_9001` manifest
  correctly failed, but full application composition had already initialized
  the default `redline.db`.
- Adds `redline_core.build.BuildPreflight` and immutable
  `PreparedBuildRequest` so `redline build` can parse the target, resolve the
  manifest path, load the manifest, and validate the manifest with
  configuration only.
- Adds `BuildOrchestrator.build_prepared(...)` so the CLI can hand off the
  already validated request after mutable application composition without
  loading or validating the manifest again.
- Updates CLI build dispatch so target, manifest resolution, manifest YAML,
  manifest schema, manifest media-path, and target/manifest identity failures
  occur before SQLite initialization, Resolve connection, or persistent logging
  artifact creation.
- Allows `build_application_services(...)` to reuse a preloaded
  `RedlineConfig`, preserving a single config object across preflight and full
  application composition.
- Does not change manifest policy, target syntax, episode manager policy,
  retry behavior, Resolve adapter behavior, render behavior, archive behavior,
  MCP behavior, database schema, or the accepted Windows YAML fixture failures.

### Verification

- Focused Mission 38A regression:
  `pytest tests/unit/test_cli_build.py tests/unit/test_build_orchestrator.py
  tests/unit/test_composition.py -q` - 50 passed.
- Related parser/manifest/build-render/render CLI regression:
  `pytest tests/unit/test_build_target.py tests/unit/test_manifest_resolution.py
  tests/unit/test_manifest_loader.py tests/unit/test_manifest_validator.py
  tests/unit/test_build_render_workflow.py tests/unit/test_cli_render.py -q` -
  135 passed, 2 skipped.
- Original live-run hygiene reproduction:
  `python -m cli.main build Episode_9001` - exit code 1 with missing-manifest
  failure; `Test-Path .\redline.db` and the isolated
  `REDLINE_LOG_DIR` check both returned `False`.
- Full accepted unit suite:
  `pytest tests/unit -q` - 1188 passed, 9 skipped, 24 accepted Windows YAML
  fixture failures.

## Unreleased - Phase 13 Mission 37: Documentation and Verification

- Closes Phase 13 through documentation alignment and verification evidence
  only.
- Updates README, architecture, roadmap, and build-command specification
  language so the documented command surfaces match implementation:
  `redline build TARGET [--manifest MANIFEST_PATH] [--force]` and
  `redline render {queue,status,list,cancel}`.
- Records that `redline build` remains assembly-only; render commands remain
  render-only; no combined CLI command exists in Phase 13.
- Records the implemented `BuildRenderWorkflow` boundary as transport-neutral
  sequencing from a successful `BuildResult` into one
  `RenderManager.queue_render(...)` call.
- Preserves the documented ownership boundaries: CLI parses transport inputs,
  `BuildOrchestrator` owns build-stage sequencing, existing manifest
  components own manifest policy, `EpisodeManager` owns episode/assembly
  policy, and `RenderManager` owns render policy.
- Does not change runtime code, CLI behavior, workflow sequencing,
  application composition, tests, retry policy, polling behavior, rollback,
  repair, archive behavior, SQLite access, Resolve access, or the accepted
  Windows YAML fixture failures.

### Verification

- Command help verified with Python 3.11 and `PYTHONPATH=src`:
  `python -m cli.main --help`; `python -m cli.main build --help`;
  `python -m cli.main render --help`; `python -m cli.main render queue --help`;
  `python -m cli.main render status --help`;
  `python -m cli.main render list --help`;
  `python -m cli.main render cancel --help`.
- Focused Phase 13 regression:
  `pytest tests/unit/test_build_orchestrator.py tests/unit/test_cli_build.py
  tests/unit/test_cli_render.py tests/unit/test_build_render_workflow.py
  tests/unit/test_composition.py -q` — 72 passed.
- Relevant render regression:
  `pytest tests/unit/test_render_manager.py tests/unit/test_resolve_mock.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_resolve_script_adapter_render_status.py
  tests/unit/test_resolve_script_adapter_render_cancel.py -q` — 103 passed.
- Full suite:
  `pytest tests/unit -q` — 1179 passed, 9 skipped, 24 accepted Windows YAML
  fixture failures.
- Repository hygiene: `git diff --check`, source-diff guard, documentation
  consistency searches, and `git status --short`.

## Unreleased - Phase 13 Mission 36: Build to Render Integration

- Adds `redline_core.workflows.BuildRenderWorkflow` as the transport-neutral
  build-to-render composition owner.
- Introduces immutable `BuildRenderResult`, containing the original successful
  `BuildResult` and the `RenderJob` returned by `RenderManager.queue_render(...)`.
- Wires `ApplicationServices` to expose one approved `BuildOrchestrator` and
  one `BuildRenderWorkflow` that reuses the same `EpisodeManager` and
  `RenderManager` instances already built by the composition root.
- Sequences `BuildOrchestrator.build(...)` exactly once before
  `RenderManager.queue_render(...)` exactly once. Render queueing occurs only
  after the build call returns successfully.
- Bridges only `BuildResult.target.episode_id` and the caller-supplied preset
  name into `RenderManager.queue_render(...)`; the workflow does not recompute
  targets, reload manifests, query persistence, inspect Resolve, derive project
  names, or evaluate render eligibility.
- Preserves existing build and render exceptions. Build failures prevent render
  invocation; render failures propagate after the successful build is preserved.
- Does not add a CLI command, alter standalone `redline build`, alter
  standalone `redline render`, archive, poll, retry, cancel automatically,
  roll back, repair, overwrite, access SQLite directly, call raw Resolve APIs,
  duplicate build policy, duplicate render policy, or repair unrelated Windows
  YAML fixtures.

### Verification

- Focused Mission 36 tests:
  `pytest tests/unit/test_build_render_workflow.py -q`.
- Mission 33-35 regression:
  `pytest tests/unit/test_build_orchestrator.py tests/unit/test_cli_build.py
  tests/unit/test_cli_render.py -q`.
- Relevant render regression:
  `pytest tests/unit/test_render_manager.py -q`.
- Composition regression:
  `pytest tests/unit/test_composition.py -q`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "sqlite3|DaVinciResolveScript|load_manifest|validate_manifest|archive|subprocess|Path\\.cwd|rollback|repair|overwrite|poll|retry"
  src/redline_core/workflows tests/unit/test_build_render_workflow.py`;
  `git diff -- src/cli/build_commands.py src/cli/render_commands.py`;
  `rg -n
  "ASSEMBLED|QUEUED|RENDERING|COMPLETED|FAILED|eligible|transition|retry|poll|cancel|rollback|repair|overwrite"
  src/redline_core/workflows`.

## Unreleased - Phase 13 Mission 35: CLI Render Surface

- Adds the top-level `redline render` CLI resource as a thin transport over
  the existing `RenderManager`.
- Exposes only render operations already supported by the manager:
  `render queue <episode_id> <preset_name>`, `render status <job_id>`,
  `render list <episode_id>`, and `render cancel <job_id>`.
- Routes render commands through the existing `ApplicationServices`
  composition path and uses `services.render_manager`; no composition change
  was required.
- Passes episode IDs, preset names, and Redline render-job database IDs through
  unchanged, with integer syntax validation for job IDs handled by argparse.
- Renders deterministic operator output for queue, status, list, and cancel
  results, including explicit build/archive exclusions for queue and cancel.
- Maps known render, episode, preset, and Resolve failures to exit code `1`
  with deterministic stderr messages while leaving unexpected failures to the
  existing top-level CLI guard and logger.
- Adds focused CLI tests for root registration, subcommand parsing, argument
  pass-through, single manager invocation, output formatting, zero-job listing,
  failure mapping, `--mock-resolve` composition pass-through, generic failure
  handling, and `redline build` render independence.
- Does not modify `redline build`, invoke `BuildOrchestrator`, parse or
  validate manifests, create episodes, assemble timelines, access SQLite
  directly, access raw Resolve APIs, duplicate render eligibility or state
  policy, add render-to-build coupling, archive, roll back, repair, overwrite,
  poll, retry, or repair unrelated Windows YAML fixtures.

### Verification

- Focused Mission 35 tests:
  `pytest tests/unit/test_cli_render.py -q`.
- Mission 34 regression:
  `pytest tests/unit/test_cli_build.py -q`.
- Mission 33 regression:
  `pytest tests/unit/test_build_orchestrator.py -q`.
- Relevant render regression:
  `pytest tests/unit/test_render_manager.py tests/unit/test_resolve_mock.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_resolve_script_adapter_render_status.py
  tests/unit/test_resolve_script_adapter_render_cancel.py -q`.
- Help verification:
  `python -m cli.main --help`; `python -m cli.main render --help`;
  `python -m cli.main render queue --help`;
  `python -m cli.main render status --help`;
  `python -m cli.main render list --help`;
  `python -m cli.main render cancel --help`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "BuildOrchestrator|parse_build_target|resolve_manifest_path|load_manifest|validate_manifest|create_episode|build_episode|sqlite3|DaVinciResolveScript|archive|rollback|repair|overwrite|subprocess"
  src/cli/render_commands.py tests/unit/test_cli_render.py`;
  `rg -n "QUEUED|RENDERING|COMPLETED|FAILED|CANCELLED|eligible|transition|retry|poll"
  src/cli/render_commands.py`.

## Unreleased - Phase 13 Mission 34: CLI redline build

- Adds the top-level `redline build TARGET` CLI command as a thin transport
  over the existing `BuildOrchestrator`.
- Supports the approved `TARGET` argument, optional `--manifest` path, and
  `--force` flag. The CLI passes the target unchanged, passes the current
  working directory explicitly, passes `--manifest` through unchanged, and maps
  `--force` only to `allow_unsafe_retry=True`.
- Uses the existing `build_application_services(...)` composition path and
  creates `BuildOrchestrator` from approved application services.
- Renders deterministic operator output for the assembly-only build result,
  including target identity, manifest path, episode create/reuse status, final
  state, project and timeline names, media/marker/clip counts, warnings, and
  explicit `Render queued: no` / `Archive performed: no` lines.
- Maps known build, manifest, episode, and Resolve failures to exit code `1`
  with a deterministic stderr message while leaving unexpected failures to the
  existing top-level CLI guard and logger.
- Adds focused CLI tests for parser registration, argument pass-through,
  single orchestrator invocation, result rendering, warning rendering, failure
  mapping, service composition, and `main(...)` dispatch.
- Does not duplicate target parsing, manifest selection, manifest loading,
  manifest validation, identity checks, episode lifecycle policy, retry policy,
  assembly logic, persistence, Resolve behavior, render behavior, archive
  behavior, rollback, repair, overwrite behavior, or unrelated Windows YAML
  fixture repairs.

### Verification

- Focused Mission 34 tests:
  `pytest tests/unit/test_cli_build.py -q`.
- Phase 13 regression:
  `pytest tests/unit/test_build_target.py tests/unit/test_manifest_resolution.py
  tests/unit/test_build_orchestrator.py -q`.
- CLI help verification:
  `redline --help`; `redline build --help`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "parse_build_target|resolve_manifest_path|load_manifest|validate_manifest|get_episode_status|create_episode|build_episode|sqlite3|DaVinciResolveScript|render|archive|rollback|repair|overwrite|subprocess"
  src/cli/build_commands.py src/cli/main.py tests/unit/test_cli_build.py`.

## Unreleased - Phase 13 Mission 33: Build Orchestrator

- Adds a transport-neutral `redline_core.build.BuildOrchestrator` that
  coordinates the approved build stages from target parsing through episode
  assembly without adding CLI behavior.
- Introduces immutable build reporting types: `BuildResult`, `BuildStage`,
  `BuildOrchestrationError`, and `ManifestIdentityMismatchError`.
- Reuses the existing Phase 13 target parser and manifest resolver, the
  existing Episode Manifest loader and validator, and the existing
  `EpisodeManager` lookup, creation, and `build_episode(...)` APIs.
- Enforces the composition-level invariant that the validated manifest
  `episode.id` must match the target-derived episode ID before any episode
  lookup, creation, assembly, SQLite mutation, or Resolve work can occur.
- Delegates create/reuse eligibility, assembly claims, failed-state retry
  handling, terminal-state rejection, persistence transitions, and Resolve
  interactions to `EpisodeManager`.
- Passes `allow_unsafe_retry` through only to the existing
  `EpisodeManager.build_episode(..., allow_unsafe_retry=...)` parameter.
- Adds focused orchestration tests for new and existing episodes, explicit
  manifest pass-through, identity mismatch, manifest load/validation failures,
  episode creation failure, manager policy failure propagation, assembly
  failure propagation, unsafe-retry pass-through, and result immutability.
- Documents the build orchestration boundary in `docs/ARCHITECTURE.md`.
- Does not add a CLI command, render behavior, archive behavior, direct
  database access, raw Resolve access, rollback, repair, overwrite behavior,
  automatic retry, new force semantics, or unrelated Windows YAML fixture
  repairs.

### Verification

- Focused Mission 33 tests:
  `pytest tests/unit/test_build_orchestrator.py -q`.
- Phase 13 regression:
  `pytest tests/unit/test_build_target.py tests/unit/test_manifest_resolution.py -q`.
- Relevant manager/manifest regression:
  `pytest tests/unit/test_manifest_loader.py tests/unit/test_manifest_validator.py
  tests/unit/test_manifest_integration.py tests/unit/test_episode_manager.py -q`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "sqlite3|DaVinciResolveScript|argparse|typer|click|render|archive|sys\\.exit|subprocess|rollback|repair|overwrite"
  src/redline_core/build tests/unit/test_build_orchestrator.py`;
  `rg -n "ASSEMBLED|FAILED|RENDER|ARCHIVE|allow_unsafe_retry|state"
  src/redline_core/build/orchestrator.py`.

## Unreleased - Phase 13 Mission 32: Manifest Resolution

- Adds a pure `redline_core.build` manifest resolver that consumes an existing
  `BuildTarget`, an optional explicit manifest path, and an injected working
  directory to select exactly one Episode Manifest path.
- Introduces an immutable `ManifestResolution` result containing the normalized
  manifest path and resolution source (`explicit`, `default_yaml`, or
  `default_yml`).
- Adds deterministic `ManifestResolutionError` failures for invalid resolver
  inputs, invalid explicit manifest extensions, missing explicit paths,
  non-file explicit paths, invalid working directories, and missing default
  candidates.
- Applies the approved Phase 13 precedence: explicit manifest paths win over
  defaults; otherwise `<target>.yaml` is checked before `<target>.yml`, and
  `.yaml` wins when both regular files exist.
- Adds focused filesystem-selection tests for explicit paths, default
  candidates, source reporting, path normalization, immutability, type checks,
  working-directory checks, and original-target filename derivation.
- Clarifies `docs/BUILD_COMMAND_SPEC.md` so the default `.yaml`/`.yml`
  behavior matches the approved Mission 32 precedence.
- Does not load YAML, parse manifest documents, validate schemas, compare
  manifest identity, create or reuse episodes, call managers, access SQLite,
  connect Resolve, add CLI behavior, render, archive, or repair unrelated
  Windows YAML fixtures.

### Verification

- Focused Mission 32 tests:
  `pytest tests/unit/test_manifest_resolution.py -q`.
- Mission 31 regression:
  `pytest tests/unit/test_build_target.py -q`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "yaml|sqlite|Resolve|EpisodeManager|ApplicationServices|CoreServices|argparse|typer|click|render|archive|open\\("
  src/redline_core/build tests/unit/test_manifest_resolution.py`.

## Unreleased - Phase 13 Mission 31: Build Target Parsing

- Adds a pure `redline_core.build` target parser for canonical Phase 13 build
  targets such as `Episode_0001`.
- Introduces an immutable `BuildTarget` result containing the original target,
  normalized episode number, and canonical episode ID derived from the supplied
  `NamingConfig`.
- Rejects non-canonical targets deterministically through `BuildTargetError`,
  including wrong case, missing or extra digits, extensions, path-like inputs,
  whitespace, non-digit suffixes, and `Episode_0000`.
- Adds focused parser tests covering valid targets, invalid syntax, number
  policy, immutability, supplied naming configuration, and non-mutation of the
  naming configuration.
- Anchors the root build-artifact ignore rule so the new `redline_core.build`
  source package is visible to Git.
- Does not add filesystem access, manifest resolution, YAML loading, CLI
  commands, manager calls, SQLite access, Resolve access, render behavior,
  archive behavior, orchestration, dependencies, or Windows YAML fixture
  repairs.

### Verification

- Focused Mission 31 tests:
  `pytest tests/unit/test_build_target.py -v`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "Path|open\\(|yaml|sqlite|Resolve|EpisodeManager|ApplicationServices|CoreServices|argparse|typer|click|os\\.environ|getenv|render|archive"
  src/redline_core/build tests/unit/test_build_target.py`.

## Unreleased - Phase 13 Mission 30: Canonical Build Command Specification

- Adds `docs/BUILD_COMMAND_SPEC.md` as the canonical Phase 13 contract for
  `redline build Episode_0001`.
- Defines the initial build command as a production composition boundary that
  parses an `Episode_0001` target, resolves and validates an Episode Manifest
  V1 file, creates or reuses the episode through existing manager policy, and
  stops after successful assembly.
- Records the canonical decisions for target syntax and normalization,
  manifest resolution, create/reuse semantics, build stages, ownership
  boundaries, dedicated build orchestration, render exclusion, archive
  exclusion, success/failure contracts, re-execution semantics, and minimum
  result requirements.
- Maps Missions 31-37 to the approved build contract and updates the roadmap:
  Phase 12 is complete, Phase 13 is in progress, and Mission 30 is complete.
- Does not change runtime code, tests, scripts, MCP tools, Resolve behavior,
  manager policy, database schema, deployment behavior, CI, or the accepted
  Windows YAML fixture failures.

### Verification

- Documentation/specification verification:
  `git diff --check`; `git diff --stat`; `git diff --
  docs/BUILD_COMMAND_SPEC.md docs/ROADMAP.md docs/CHANGELOG.md README.md
  docs/ARCHITECTURE.md`; `rg -n
  "redline build|Episode_0001|manifest|orchestrat|render|archive|idempoten|force|result|Phase 13|Mission 30"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 30 changes only architecture and
  specification documentation.

## Unreleased - Phase 12 Mission 29: Align CI Workflow With Canonical Release Branch

- Updates `.github/workflows/ci.yml` so the existing CI workflow runs for
  `push` and `pull_request` events targeting the canonical `master` branch.
- Preserves the existing workflow name, mocked unit-test job, Python version,
  editable development install, pytest command, and coverage arguments.
- Updates the roadmap while keeping Phase 12 in progress.
- Does not add release publishing, artifact uploads, package builds, deployment
  jobs, matrix testing, new operating systems, new Python versions, dependency
  changes, linting, formatting checks, security scanning, runtime code, tests,
  architecture updates, release tagging, or Windows YAML fixture repairs.

### Verification

- Workflow/configuration verification:
  `git diff --check`; `git diff --stat`; `git diff --
  .github/workflows/ci.yml docs/CHANGELOG.md docs/ROADMAP.md`;
  `Get-Content .github/workflows/ci.yml`; `rg -n
  "main|master|branches:" .github/workflows/ci.yml docs/ROADMAP.md
  docs/CHANGELOG.md`; `git status --short`.
- No unit tests were required because Mission 29 changes only CI branch
  configuration and mission documentation.

## Unreleased - Phase 12 Mission 28: Production Workstation Deployment Documentation

- Adds `docs/DEPLOYMENT.md` as the canonical production-workstation deployment
  runbook for the existing installed workflow verified by Missions 22-27.
- Documents supported workstation assumptions, Python and DaVinci Resolve Studio
  prerequisites, wheel installation, MCP optional-dependency installation,
  configuration/database/log locations, Resolve scripting variables, CLI and
  MCP verification, deployment evidence, and known deployment limitations.
- Links the deployment guide from `README.md` and updates the roadmap while
  keeping Phase 12 in progress.
- Does not add package publishing, installers, deployment automation, service
  wrappers, containers, release pipelines, rollback mechanisms, upgrade policy,
  troubleshooting procedures, CI changes, production code changes, tests, or
  Windows YAML fixture repairs.

### Verification

- Documentation-only verification:
  `git diff --check`; `git diff --stat`; `rg
  "deploy|deployment|workstation|wheel|REDLINE_CONFIG_DIR|REDLINE_DB_PATH|REDLINE_LOG_DIR|redline-mcp|Resolve"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 28 changes documentation only.

## Unreleased - Phase 12 Mission 27: Recovery and Restart Runbook Documentation

- Adds `docs/RECOVERY.md` as the canonical operator runbook for process
  interruption, failed episode assembly, persisted assembly claims, partial
  Resolve mutations, safe `--force` usage, render recovery states,
  SQLite/Resolve drift, and evidence preservation.
- Distinguishes persisted Redline state inspection from external Resolve state
  inspection, normal retry from forced retry, and operator review from manual
  SQLite mutation. Direct SQLite mutation is explicitly not documented as a
  routine recovery procedure.
- Links the runbook from `README.md` and corrects the MCP tools reference's
  stale real-Resolve verification wording without changing MCP behavior.
- Does not change production code, tests, retry policy, rollback behavior,
  reconciliation behavior, deployment guidance, upgrade policy, CI, or the
  known Windows YAML fixture failures.

### Verification

- Documentation-only verification:
  `git diff --check`; `git diff --stat`; `rg
  "rollback|retry|force|assembly claim|restart|recovery|Resolve|SQLite|render"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 27 changes documentation only.

## Unreleased - Phase 12 Mission 26: First-Run Installed Operator Workflow Documentation

- Documents the first-run installed operator workflow now verified by Missions
  22-25: install from a built wheel or package, select isolated config,
  database, and log paths, verify the installed CLI with `redline asset list`,
  and verify MCP startup with `redline-mcp --mock-resolve`.
- Separates installed operator usage from editable development setup. The docs
  keep `pip install -e`, `scripts/bootstrap_db.py`, and
  `python -m mcp_server.server` as source-checkout instructions only, and state
  that installed operators do not need `PYTHONPATH=src`.
- Clarifies when mock Resolve is appropriate for startup and client wiring, and
  when a real DaVinci Resolve Studio session plus Resolve scripting environment
  variables are required.
- Does not change production code, tests, CLI commands, MCP behavior, database
  schema, recovery policy, deployment policy, upgrade policy, CI, or the known
  Windows YAML fixture failures.

### Verification

- Documentation-only verification:
  `git diff --check`; `git diff --stat`; `rg
  "pip install -e|scripts/bootstrap_db.py|python -m mcp_server.server|PYTHONPATH"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 26 changes documentation only.

## Unreleased - Phase 12 Mission 25: Installed MCP Startup Smoke Verification

- Adds an installed MCP startup smoke test that builds the Redline OS wheel,
  installs it into an isolated temporary virtual environment, and verifies the
  installed MCP startup path from a working directory outside the repository
  checkout.
- Verifies Redline OS's wheel metadata declares the `mcp` optional dependency
  extra and uses a deterministic local MCP test wheel so the smoke does not
  silently depend on developer-environment packages or network access.
- Confirms installed startup without `PYTHONPATH=src`: the smoke imports
  `mcp_server.server`, finds the installed `redline-mcp` console script,
  initializes logging, loads an isolated config directory, initializes a
  temporary SQLite database, composes `ApplicationServices` with
  `MockResolveAdapter`, creates the FastMCP server, and observes all 18 expected
  tool registrations.
- Does not call `mcp.run()`, connect to live Resolve, change MCP tools, alter
  CLI behavior, modify database schema, redesign bootstrap, or repair the known
  Windows YAML fixture failures.

### Verification

- Focused Mission 25 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_mcp_startup_smoke.py -q` -> 1 passed.
- Targeted installed/MCP regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_mcp_startup_smoke.py
  tests\unit\test_mcp_tools.py tests\unit\test_installed_wheel_smoke.py -q`
  -> 55 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1073
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 25 adds no new full-suite failures.

## Unreleased - Phase 12 Mission 24: Installed Non-Help CLI Smoke Verification

- Adds an installed CLI smoke test that builds the Redline OS wheel, installs it
  into an isolated temporary virtual environment, and runs the installed
  `redline asset list` console entrypoint from a working directory outside the
  repository checkout.
- Verifies non-help operator startup without `PYTHONPATH=src`: the command loads
  an isolated config directory through `REDLINE_CONFIG_DIR`, initializes logging
  through `REDLINE_LOG_DIR`, composes `CoreServices`, delegates to
  `AssetManager.list_available_assets()`, returns expected asset-list output,
  and exits with code 0.
- Confirms the smoke path does not require `REDLINE_DB_PATH`, create a
  `redline.db` in the command working directory, connect to Resolve, add a new
  CLI command, touch MCP startup, or duplicate asset-list policy.

### Verification

- Focused Mission 24 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_cli_asset_list_smoke.py -q` -> 1 passed.
- Targeted installed-smoke regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_cli_asset_list_smoke.py
  tests\unit\test_installed_wheel_smoke.py
  tests\unit\test_installed_db_bootstrap_smoke.py -q` -> 3 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1072
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 24 adds no new full-suite failures.

## Unreleased - Phase 12 Mission 23: Installed Database Bootstrap Verification

- Adds an installed-package database bootstrap smoke test that builds the
  Redline OS wheel, installs it into an isolated temporary virtual environment,
  runs from a working directory outside the repository checkout, imports
  `Database` from the installed package, and initializes a temporary SQLite
  database through `Database.connect()` and `Database.init_schema()`.
- Verifies the canonical core tables (`episodes`, `render_jobs`, and
  `archives`) through SQLite metadata after initialization. The smoke path does
  not execute `scripts/bootstrap_db.py`, use `PYTHONPATH=src`, connect to
  Resolve, add a public bootstrap command, or duplicate schema SQL.
- Preserves database ownership in `redline_core.db`; scripts and transports
  remain operational entrypoints only.

### Verification

- Focused Mission 23 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_db_bootstrap_smoke.py -q` -> 1 passed.
- Targeted installed/bootstrap/resource regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_db_bootstrap_smoke.py
  tests\unit\test_installed_wheel_smoke.py
  tests\unit\test_db_schema_resource.py -q` -> 7 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1071
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 23 adds no new full-suite failures.

## Unreleased - Phase 12 Mission 22: Installed Wheel Smoke Verification

- Adds an installed-wheel smoke test that builds the Redline OS wheel, installs
  it into an isolated temporary virtual environment, and verifies behavior from
  a working directory outside the repository checkout.
- The smoke test confirms that the installed `redline_core` package imports,
  `redline_core.db/schema.sql` and `redline_core.asset/schema.sql` are readable
  through package resources, and the installed `redline` console entrypoint
  exists and runs `redline --help`.
- The test avoids Resolve-dependent commands, global environment mutation, new
  build dependencies, schema changes, bootstrap redesign, CLI/MCP redesign, and
  Windows YAML fixture repair. `redline --help` is used as the console smoke
  command because argparse exits before any config, database, logging, or
  Resolve startup side effects.

### Verification

- Focused Mission 22 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_wheel_smoke.py -q` -> 1 passed.
- Targeted packaging/database/composition regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_wheel_smoke.py
  tests\unit\test_db_schema_resource.py tests\unit\test_composition.py -q`
  -> 17 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1070
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 22 adds no new full-suite failures.
- The smoke test first attempts `python -m pip wheel ... --no-deps
  --no-build-isolation`; on this workstation that path reports
  `invalid command 'bdist_wheel'` because the active interpreter does not
  provide the wheel build command. It then falls back to pip's existing PEP 517
  isolated wheel build, still with `--no-deps`, and verifies the built wheel
  archive contains both packaged SQL resources before installing it into the
  temporary virtual environment.

## Unreleased - Phase 12 Mission 21: Package Core DB Schema Resource

- Moves `Database.init_schema()` from a source-tree-relative
  `Path(__file__).parent / "schema.sql"` lookup to the packaged
  `redline_core.db` resource boundary via `importlib.resources.files()`.
- Adds `redline_core.db/schema.sql` to setuptools package data so the core
  SQLite schema is available in editable installs, wheels, and packaged
  deployments.
- Preserves the existing schema SQL, initialization flow, automatic
  `assembly_claim_*` migration, commit behavior, and visible exception
  behavior. Missing or unreadable schema resources still raise from the
  resource/database boundary instead of being silently repaired or wrapped in a
  new policy type.
- Does not modify SQL schema contents, introduce schema versioning, add
  migrations, redesign database bootstrap, change CLI/MCP contracts, alter
  Resolve behavior, publish packages, or repair the known Windows YAML fixture
  failures.

### Verification

- Focused Mission 21 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_db_schema_resource.py -q` -> 5 passed.
- Targeted DB/composition/bootstrap regression was run with the PowerShell-
  expanded `tests\unit\test_db*.py`, `tests\unit\test_composition*.py`, and
  `tests\unit\test_bootstrap*.py` file list -> 37 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1069
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 21 adds no new full-suite failures.
- `python -m build` could not be used in this environment because the `build`
  module is not installed. A temporary no-dependency wheel was built with
  `python -m pip wheel . --no-deps`; inspecting the wheel confirmed both
  `redline_core/asset/schema.sql` and `redline_core/db/schema.sql` are
  included.

## Unreleased - Phase 12 Mission 20: Logging and Diagnostics Baseline

- Hardens `redline_core.logging.setup.configure_logging()` without changing the
  logging architecture or startup callers. CLI and MCP continue to pass only
  `REDLINE_LOG_DIR` and `REDLINE_LOG_LEVEL` values into the shared logging
  boundary.
- Repeated configuration now replaces only Redline-owned console/file handlers,
  identified by an internal ownership marker, so pytest, embedding
  applications, and third-party libraries can keep unrelated handlers attached
  to the `redline_os` logger.
- Invalid log levels now raise `LoggingConfigurationError` deterministically.
  Supported configured levels remain the documented `DEBUG`, `INFO`, `WARNING`,
  and `ERROR`, with case-insensitive input. Directory creation and file-handler
  failures remain visible and are not swallowed.
- Documents default level, console behavior, file logging path resolution,
  directory creation, invalid-level startup failures, and basic operator
  diagnostics in `README.md` and `docs/CONFIG.md`.
- Does not add JSON logging, retention policy, redaction, telemetry, tracing,
  packaging changes, deployment scripts, recovery workflows, Resolve changes,
  database changes, CLI/MCP feature expansion, or Windows YAML fixture repair.

### Verification

- Focused Mission 20 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_logging_setup.py -q` -> 14 passed.
- Targeted logging/CLI/MCP startup regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_logging_setup.py tests\unit\test_cli*.py
  tests\unit\test_mcp*.py -q` was attempted, but pytest received the wildcard
  literally in this PowerShell environment. Re-running with the PowerShell-
  expanded file list completed with 185 passed and 24 failed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1064
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 20 adds no new full-suite failures.

## Unreleased - Phase 11 Mission 19: MCP `assemble_episode`

- Adds the MCP `assemble_episode(...)` tool as a thin transport wrapper over
  the existing `EpisodeManager.build_episode()` assembly owner. The tool
  accepts the manager's explicit assembly inputs (`episode_id`, ordered
  `media_paths`, optional marker dicts, `bin_name`, and
  `allow_unsafe_retry`) and constructs the existing `EpisodeBuildDefinition`
  domain input before making exactly one high-level assembly call.
- Serializes the existing `EpisodeBuildResult` fields used by the CLI assembly
  path: `episode_id`, `project_name`, `timeline_name`, `media_paths`,
  `media_ids`, `markers_applied`, and `timeline_item_ids`.
- Does not load or validate manifests, verify assets, import media directly,
  build timelines directly, place clips directly, queue renders, write SQLite
  directly, call Resolve directly, or introduce retry behavior. Assembly order,
  validation, retry policy, persistence, and Resolve interactions remain owned
  by `EpisodeManager.build_episode()`.
- Known `EpisodeBuildError` failures return the neighboring episode-tool
  structured envelope: `{"success": False, "error": "..."}`. Unexpected
  non-assembly exceptions are not broadly wrapped.

### Verification

- Focused Mission 19 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -k "assemble_episode" -q` -> 11 passed, 42
  deselected.
- Full MCP tool tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -q` -> 53 passed.
- Targeted episode/MCP regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py tests\unit\test_episode_manager.py -q` -> 105
  passed. The originally requested `tests\unit\test_episode*.py` wildcard form
  was also attempted, but pytest received it literally in this PowerShell
  environment.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1050
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 19 adds no new full-suite failures.

## Unreleased - Phase 11 Mission 18: MCP `validate_manifest`

- Adds the MCP `validate_manifest(manifest_path)` tool as a thin transport
  wrapper over the existing `redline_core.manifest.load_manifest()` and
  `validate_manifest()` public API. The MCP layer passes the manifest path
  through unchanged and serializes the resulting `ValidatedEpisodePlan`.
- The success response is deterministic and includes `manifest_path`, `valid`,
  `episode_id`, `bin_name`, resolved `media_paths`/`media_count`, and
  `markers`/`marker_count`. Manifest loading, duplicate-key rejection, schema
  validation, path containment, and UNC-path handling remain owned by
  `redline_core.manifest`.
- Known manifest failures return the neighboring episode-tool structured
  envelope: `{"success": False, "error": "..."}`. Unexpected non-manifest
  exceptions are not broadly wrapped. The tool performs no episode creation,
  assembly, SQLite writes, manager calls, Resolve calls, or manifest repair.

### Verification

- Focused Mission 18 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -k "validate_manifest" -q` -> 12 passed, 30
  deselected.
- Full MCP tool tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -q` -> 42 passed.
- Targeted MCP/manifest regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py tests\unit\test_manifest_loader.py
  tests\unit\test_manifest_validator.py tests\unit\test_manifest_integration.py
  -q` -> 102 passed, 2 skipped. The originally requested
  `tests\unit\test_manifest*.py` wildcard form was also attempted, but pytest
  received it literally in this PowerShell environment.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1039
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 18 adds no new full-suite failures.

## Unreleased - Phase 11 Mission 17: MCP `place_clips`

- Adds the MCP `place_clips(project_name, timeline_name, clip_ids)` tool as a
  thin transport wrapper over the existing `TimelineBuilder.place_clips()`
  capability. The tool preserves the builder contract and serializes the
  returned TimelineItem IDs as `timeline_item_ids` with a deterministic
  `placed_count`.
- Basic MCP transport-shape validation rejects missing primitive inputs and
  malformed `clip_ids` before delegation. Empty clip lists are delegated to the
  builder so existing timeline placement policy remains centralized.
- The tool does not resolve clip IDs, import media, select timelines, write to
  SQLite, call the Resolve adapter directly, or duplicate clip-placement policy.
  Timeline-builder domain exceptions follow the neighboring timeline-tool
  behavior and are not broadly wrapped.

### Verification

- Focused Mission 17 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -k "place_clips" -q` -> 9 passed, 21
  deselected.
- Full MCP tool tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -q` -> 30 passed.
- Targeted timeline/MCP regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py
  tests\unit\test_resolve_script_adapter_clip_placement.py -q` -> 93 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1027
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 17 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 16: real Resolve `cancel_render`

- Implements `ResolveScriptAdapter.cancel_render(resolve_job_id) -> None` for
  real Resolve, preserving the existing public adapter contract. The lookup is
  scoped to the currently loaded Resolve project and leaves `RenderManager`,
  SQLite, CLI, and MCP contracts unchanged.
- Queued renders are cancelled through `Project.DeleteRenderJob(job_id)`.
  Resolve Studio 21.0.3.7 returns `True` for a known queued job, removes the
  job from the render queue, and makes `GetRenderJobStatus(job_id)` return
  `None`; unknown jobs return `False` and are reported as `RenderJobError`.
- Active renders are cancelled through project-scoped `Project.StopRendering()`
  only after Redline verifies that the requested job is the sole active render.
  `StopRendering()` returns `None` on Resolve Studio 21.0.3.7, so success is
  verified through postconditions: `IsRenderingInProgress()` becomes `False`
  and the requested job's `JobStatus` becomes `Cancelled`.
- A successfully stopped active job is intentionally left in Resolve's render
  queue with status `Cancelled`. Redline does not delete it automatically
  because queue cleanup is separate from cancellation and a post-stop delete
  failure could leave SQLite inconsistent with Resolve.
- Terminal statuses (`Complete`, `Failed`, `Cancelled`, and `Canceled`) are
  rejected with `RenderJobError`, matching the existing mock policy even though
  live probing showed Resolve permits deleting completed queue entries.
- Adds focused fake-Resolve unit coverage in
  `tests/unit/test_resolve_script_adapter_render_cancel.py`.

### Verification

- Focused Mission 16 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_cancel.py -q` -> 29 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_cancel.py
  tests\unit\test_resolve_script_adapter_render_status.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py -q` ->
  103 passed.
- Live adapter-level verification against disposable project
  `redline-os-test-duplicate` confirmed queued cancellation removes a `Ready`
  job and active cancellation transitions a `Rendering` job to `Cancelled`
  without deleting it automatically. The probe-created active queue entry was
  deleted afterward as manual cleanup.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1018
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 16 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 15: real Resolve `get_render_status`

- Implements `ResolveScriptAdapter.get_render_status(resolve_job_id) -> str`
  for real Resolve, preserving the existing public adapter contract. The lookup
  is scoped to the currently loaded Resolve project through
  `ProjectManager.GetCurrentProject()` and uses
  `Project.GetRenderJobStatus(resolve_job_id)` as the authoritative live-status
  API.
- Live API probing on Resolve Studio 21.0.3.7 confirmed that
  `GetRenderJobList()` returns render-job inventory and metadata but does not
  include live status. `GetRenderJobStatus(job_id)` returns a dictionary
  containing `JobStatus` and `CompletionPercentage` for known jobs and `None`
  for unknown jobs.
- Maps verified/approved Resolve statuses to Redline strings: `Ready` ->
  `queued`, `Rendering` -> `rendering`, `Complete` -> `complete`, `Failed` ->
  `failed`, and both `Cancelled`/`Canceled` -> `cancelled`. Unknown
  well-formed statuses return `unknown`, so `RenderManager` preserves the
  stored DB status instead of guessing.
- Rejects empty/non-string job IDs, missing current projects, malformed known
  job responses, and unavailable project managers with `RenderJobError` or
  `ResolveConnectionError` as appropriate. Unexpected Resolve API exceptions
  are wrapped in `RenderJobError` with the original exception preserved as
  `__cause__`.
- Adds focused fake-Resolve unit coverage in
  `tests/unit/test_resolve_script_adapter_render_status.py`. No manager,
  database, CLI, MCP, polling, progress persistence, project-searching, or
  cancellation behavior changed.
- At Mission 15 close, the remaining Phase 10 real-Resolve gap was
  `cancel_render`; Mission 16 resolves that gap.

### Verification

- Focused Mission 15 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_status.py -q` -> 28 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_status.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py -q` ->
  74 passed.
- Live adapter-level verification against disposable project
  `redline-os-test-duplicate` and Resolve job
  `6ac314da-9c99-41eb-bf79-621e5f6b7edc` returned `queued`.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 989
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 15 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 14: real Resolve `queue_render`

- Implements `ResolveScriptAdapter.queue_render(project_name, preset_name,
  output_path) -> str` for real Resolve. This is enqueue-only: it applies the
  named Resolve render preset, applies the output directory through
  `SetRenderSettings({"TargetDir": ...})`, adds exactly one render job with
  `AddRenderJob()`, and returns the Resolve render job ID. It does not start
  rendering, poll status, cancel jobs, add CLI commands, change MCP contracts,
  add manifest render sections, or alter `RenderManager` policy.
- Adds a documented adapter boundary in `docs/ARCHITECTURE.md` before the
  production-code change. `RenderJobError` remains the domain-specific render
  failure type. Unexpected Resolve API exceptions are wrapped as
  `RenderJobError` with the original exception preserved as `__cause__`.
- Handles Resolve's version-sensitive `AddRenderJob()` return shape without
  guessing: if `AddRenderJob()` returns a usable scalar ID (`str` or `int`),
  that ID is returned directly; otherwise the adapter compares
  `GetRenderJobList()` snapshots from before and after queueing and accepts
  exactly one newly appeared job ID. Missing, duplicate, or ambiguous
  candidates raise `RenderJobError`. If a job was queued but ID extraction or
  reconciliation fails, no automatic rollback or deletion is attempted; manual
  Resolve/SQLite reconciliation may be required.
- Failure boundaries covered explicitly: disconnected adapter, unknown project,
  empty preset name, preset-load rejection, output-setting rejection,
  `AddRenderJob()` rejection, missing job ID, ambiguous job ID, and unexpected
  Resolve API exceptions. Logging includes project/preset/job context without
  unnecessarily exposing full output filesystem paths.

### Verification

- Focused Mission 14 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_queue.py` -> 15 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py
  tests\unit\test_resolve_script_adapter_import_media.py
  tests\unit\test_resolve_script_adapter_timeline.py
  tests\unit\test_resolve_script_adapter_clip_placement.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_mcp_tools.py` -> 192 passed.
- Live verification passed on 2026-07-29 with DaVinci Resolve Studio
  21.0.3.7 and Python 3.11.9 against the disposable
  `redline-os-test-duplicate` project, built-in `YouTube - 720p` preset, and
  `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests` output
  directory. `AddRenderJob()` returned
  `6ac314da-9c99-41eb-bf79-621e5f6b7edc`, and the post-call
  `GetRenderJobList()` contained exactly one job with that same `JobId`.
  `get_render_status` and `cancel_render` remain unimplemented for real
  Resolve.

### Known unrelated regression limitation

- Full `tests\unit` was executed with Python 3.11.9 and completed with 961
  passed, 9 skipped, and 24 failed. The failures are pre-existing CLI
  end-to-end fixture portability defects: Windows paths are embedded in
  double-quoted YAML, causing PyYAML to interpret sequences such as `\U` as YAML
  escapes. Mission 14 does not change the affected CLI fixtures or YAML-
  generation logic. Repair is deferred to a separate focused maintenance
  mission.

## Unreleased - Phase 9 Mission 13: `redline episode assemble` CLI + atomic assembly claim

- Adds `redline episode assemble <manifest_path> [--force]` — the mutating
  counterpart to Mission 12's `validate-manifest`, and the first CLI action
  to reach `EpisodeManager.build_episode()`. A thin wrapper over the
  existing `load_manifest()` -> `validate_manifest()` ->
  `.to_build_definition()` -> `build_episode()` pipeline. Routed through
  `ApplicationServices`, the same composition tier as every other mutating
  `episode` action — no `cli/main.py` dispatch change needed, unlike
  Mission 12.
- Preceded by `docs/adr/ADR-0001-episode-assembly-retry-policy.md`, the
  project's first ADR: found that the existing rerun guard (an in-memory
  `_unsafe_rerun_episode_ids` set) provided zero protection through the CLI
  transport, since a fresh `EpisodeManager` is constructed on every CLI
  invocation. Replaced with an atomic, persisted assembly claim.
- `redline_core` changes (the first this Phase 9 initiative has required):
  - `schema.sql` / `database.py`: two new nullable `episodes` columns,
    `assembly_claim_token` and `assembly_claimed_at`, added via a new
    `Database._migrate_add_assembly_claim_columns()` migration (runs from
    `init_schema()`, no try/except — a failed migration fails application
    startup outright, per ADR-0001's explicit migration-failure policy).
    New `Database.claim_episode_for_assembly(episode_id, claim_token, *,
    allow_unsafe_retry=False) -> bool` and
    `Database.release_assembly_claim(episode_id, claim_token, status)`
    (token-owned: only releases a claim matching the caller's own token).
  - `episode/manager.py`: `build_episode()` gained a keyword-only
    `allow_unsafe_retry: bool = False` parameter (CLI's `--force` maps to
    it). `_get_existing_episode_for_build()` replaced with
    `_claim_episode_for_build()`, which claims the episode atomically
    before any Resolve mutation begins and threads the resulting
    `claim_token` through every `_build_error()` call site. The old
    in-memory `_unsafe_rerun_episode_ids` set is gone entirely.
  - `db/models.py`: `Episode` gained `assembly_claim_token` /
    `assembly_claimed_at` fields (and `from_row()` reads them), so the
    claim state the schema/database layer added is actually readable back
    through the model — caught and fixed during this mission's own test
    writing, not part of the original #46/#47 slices.
- **Two correctness issues found in review before this mission was
  committed, both fixed prior to commit:**
  1. The originally proposed forced-claim `UPDATE` guarded only by `status
     NOT IN (terminal...)`, with no dependency on the existing claim token
     at all — so two concurrent forced (`--force`) callers racing the same
     dangling claim could both satisfy that guard and both acquire it,
     violating ADR-0001's single-claimant invariant. Fixed by replacing it
     with `Database._claim_episode_for_assembly_cas()`: a diagnostic
     `SELECT` of the current `(status, assembly_claim_token)`, followed by
     a compare-and-swap `UPDATE` whose `WHERE` clause is pinned to exactly
     that observed pair (`IS NULL` when the observed token is `None`). The
     `SELECT` authorizes nothing; the guarded `UPDATE`'s rowcount remains
     the sole authority on acquisition. A genuinely sequential second
     forced call (one that freshly observes the first's already-committed
     token) can still legitimately take over — that's an operator issuing
     `--force` twice with accurate current information, not a race, and is
     not what this guards against.
  2. `release_assembly_claim()` originally logged an error and returned
     silently when no row matched the given token (rowcount 0) — on the
     success path, this could let `build_episode()` return an
     `EpisodeBuildResult` even though the episode was never actually
     marked `assembled` and the claim was never actually cleared. Fixed:
     `release_assembly_claim()` now raises a new
     `AssemblyClaimReleaseError` on a rowcount-0 release. Both existing
     call sites already had `except Exception` handling (the final
     success-path release, and `_build_error()`'s own failure-cleanup
     release), so this converts correctly into `EpisodeBuildError` (stage
     `status_update`) without needing new branching logic at either site.
- Full exhaustive status matrix enforced by `_claim_episode_for_build()`:
  `created`/`assets_verified`/`media_organized`/`timeline_built` claimable
  normally; `failed` and an active/unresolved claim from a prior attempt
  blocked without `--force`, claimable with it; `assembled`/
  `render_queued`/`rendered`/`archived` always blocked, no override under
  any flag, ever.
- `--force` is a pure transport-vocabulary translation, not a policy
  decision: the CLI passes it straight through as `allow_unsafe_retry` and
  never inspects episode status or claim state itself. The `--force`
  warning banner prints whenever the flag was passed, before checking the
  result, including on a failed (e.g. terminal-status-blocked) attempt.
- New tests: 15 DB-level tests (`test_db.py` — claim/release/token-owned-
  release/migration-idempotency/legacy-table-upgrade, plus 5 added for the
  CAS correctness fix: two racers on the same dangling claim resulting in
  exactly one success, a second racer failing against already-superseded
  state, `IS NULL` handling for a never-claimed episode, and terminal
  status rejected without attempting the update), 11 new `EpisodeManager`
  tests plus 3 rewritten ones (`test_episode_manager.py` — full status
  matrix, dangling-claim block/override, forced-retry-after-failure, plus
  2 added for the release-failure fix: a real (non-monkeypatched) token
  mismatch during the final release converts to `EpisodeBuildError`
  instead of a success result, and a positive proof that the claim is
  durably committed — visible via a second, independent DB connection —
  before `MediaManager.import_media()` runs), and 14 new CLI tests
  (`test_cli_episode_assemble.py` — success/failure payload shapes,
  `--force` warning banner, argument parsing, and an in-process `main()`
  end-to-end proof that `--force` actually unblocks a `FAILED` episode
  through the real CLI entry point). Full suite: 978 passed, 1 skipped (up
  from Mission 12's 938 passed, 1 skipped).
- **Phase 9 (Episode Production Pipeline) is now complete.** A post-
  implementation gap review found no remaining capability: `redline_core.manifest`'s
  entire public surface (`load_manifest()`, `validate_manifest()`) is called
  from the CLI (`validate-manifest` directly; `assemble` via
  `.to_build_definition()`), and `EpisodeManager.build_episode()` is now
  CLI-reachable via `assemble`. See `docs/ROADMAP.md`'s Phase 9 row.
- Manual smoke test: an in-process script sharing one `MockResolveAdapter`
  across sequential `main()` invocations (required, since the mock adapter
  is in-memory only and separate CLI processes don't share it) verified,
  against the real CLI entry point: a successful assemble; an ordinary
  retry blocked by the now-`assembled` terminal status; the same retry
  still blocked with `--force` (terminal statuses are never overridable);
  a `FAILED` episode blocked without `--force`; and the same episode
  successfully retried with `--force`. Repo working tree stayed clean
  throughout.

## Unreleased - Phase 9 Mission 12: `redline episode validate-manifest` CLI

- Adds `redline episode validate-manifest <manifest_path>` as an eighth
  `episode` action — the first Phase 9 mission, per the approved Phase 9
  Architecture Proposal and Mission 12 Implementation Contract. A thin,
  read-only wrapper over the existing, already-tested
  `redline_core.manifest.load_manifest()` and `.validate_manifest()`. No
  `redline_core` code changed: `EpisodeManager`, `TimelineBuilder`,
  `MediaManager`, `AssetManager`, `ArchiveManager`, the Resolve adapter,
  and the manifest loader/validator/models are all unmodified.
- Routed through `CoreServices`, not `ApplicationServices` — the first
  `episode` action to need only config, confirmed directly against
  `validate_manifest()`'s real signature (`RedlineConfig` only, no `db`,
  no `resolve`). `cli/main.py` now branches on `args.action` within the
  `episode` resource for this one case, dispatching to a new, separate
  `episode_commands.run_validate_manifest()` rather than adding an eighth
  branch to the existing `run()` (which stays typed `ApplicationServices`,
  unchanged, for the other seven actions). See `docs/ARCHITECTURE.md` for
  the full reasoning, including why a general per-action dispatch
  mechanism was deliberately not introduced for what's currently a single
  demonstrated case.
- Argument shape deviates from every other `episode` action on purpose:
  takes `manifest_path`, not `episode_number` — episode identity comes
  from inside the manifest file (`episode.id`), not from an operator-typed
  number, the same kind of contract-driven deviation `archive episode
  <episode_id>` already established.
- Result payload: `episode_id`, `bin_name`, `media_paths`, `media_count`,
  `markers` (each with `frame`/`color`/`name`/`note`), `marker_count` — all
  read directly off the existing `ValidatedEpisodePlan`, no new fields
  invented. Zero configured markers is a successful result
  (`marker_count: 0`), matching the manifest schema's own optional-markers
  default.
- Exception handling: catches exactly `ManifestLoadError`,
  `ManifestParseError`, `ManifestSchemaError`, `ManifestValidationError` —
  verified to transitively cover their subclasses `ManifestVersionError`
  and `ManifestPathError` via the actual class hierarchy in
  `redline_core/manifest/exceptions.py`, not a convenience catch of the
  shared `ManifestError` root. `str(exc)` passed through unchanged.
- No `--mock-resolve` needed or read by this command.
- New tests: `tests/unit/test_cli_episode_validate_manifest.py` (14 tests),
  including a gating `main()` end-to-end test that runs with neither
  `REDLINE_DB_PATH` set nor `--mock-resolve` passed — direct proof the new
  `CoreServices` routing actually took effect, mirroring the same proof
  `test_cli_asset_list.py` already established for `asset list`. Full
  suite: 938 passed, 1 skipped (up from Mission 11B's 924 passed, 1
  skipped).
- Manual smoke test: ran the installed `redline` console script directly
  against a real manifest file, with neither `REDLINE_DB_PATH` nor
  `--mock-resolve` set — a valid manifest (exit 0, full reported fields)
  and a missing-file manifest (exit 1, exact underlying error message).
  Repo working tree stayed clean throughout.
- Mission 13 (`episode assemble`) was blocked pending a separate
  architecture decision on rerun/recovery policy at the time this mission
  landed; resolved via ADR-0001 and implemented — see the Mission 13 entry
  above.

## Unreleased - Mission 11B: `redline episode place-clips` CLI

- Adds `redline episode place-clips <episode_number> [clip_id ...]` as a
  seventh `episode` action, as a thin wrapper over the existing,
  already-tested `TimelineBuilder.place_clips()`. This is the last
  `TimelineBuilder` public method to gain CLI exposure — `apply_markers()`
  remains internal-only (no natural episode-scoped argument shape; see
  Mission 11's architecture review).
- Unblocked directly by Mission 11A: `timeline_name` is resolved via
  `TimelineBuilder.timeline_name_for_episode()` — a pure call, no Resolve
  side effects — rather than by calling `build_timeline_for_episode()`
  again, which would have silently re-applied (duplicated) markers as an
  unrelated side effect.
- `clip_ids` are passed through completely unchanged: same order, no
  deduplication. Zero clip IDs is a successful no-op (`placed_count: 0`)
  — the adapter itself never touches the project or timeline when given
  an empty list, so this is the existing contract, not a CLI-invented
  distinction.
- Result payload echoes back both the requested `clip_ids` and the
  returned `timeline_item_ids`, since `place_clips()` preserves order
  position-for-position between them — real operator value, unlike
  `build-timeline`'s omitted `timeline_id`.
- Exception tuple matches Mission 10's: `EpisodeNotFoundError`,
  `ProjectNotFoundError`, `TimelineOperationError`, messages passed
  through unchanged; `ResolveConnectionError` remains owned by the
  top-level CLI boundary. No `mcp_server` changes.
- No new manager-level tests: `TimelineBuilder.place_clips()` and
  `timeline_name_for_episode()` both already have complete, independent
  coverage from Missions 10 and 11A. `tests/unit/test_cli_episode_place_clips.py`
  (17 tests) is CLI transport coverage only.
- No composition change: `ApplicationServices` already provided
  everything this command needs.
- Full suite: 924 passed, 1 skipped (up from Mission 11A's 911 passed, 1
  skipped).
- Smoke testing used two distinct categories, since mock Resolve state
  cannot survive across separate `redline` process invocations: an
  in-process smoke test (one shared `MockResolveAdapter` instance across
  `create` → `build-timeline` → `organize-bins` → `place-clips`, proving
  both the successful placement and the genuine "timeline not found"
  failure when `place-clips` runs before `build-timeline`), and an
  installed-script smoke test for the cases that don't need cross-process
  state (parser/`--help` behavior, zero-clip success, unknown-episode
  failure). A separately-invoked "project not found" case was also
  confirmed directly against the installed script, since a freshly
  started process's mock adapter has no projects at all.

## Unreleased - Mission 11A: pure timeline-naming helper (internal refactor, no CLI change)

- Adds `TimelineBuilder.timeline_name_for_episode(episode_id: str) -> str`,
  a pure method that formats `config.timeline.timeline_name_pattern` for a
  given `episode_id`. No Resolve, no SQLite, no logging, no mutation —
  reads one config field and returns a string.
- `TimelineBuilder.build_timeline_for_episode()` now calls this helper
  instead of inlining the `.format()` call. No observable behavior change:
  identical input produces the identical `timeline_name` it always did,
  proven by every existing `test_timeline_builder.py` assertion passing
  unmodified.
- `EpisodeManager.build_episode()`'s own pre-computation of `timeline_name`
  (used for early-stage error context before a real timeline exists) also
  now calls `self.timeline_builder.timeline_name_for_episode(...)` instead
  of independently reformatting the same pattern. This removes a
  pre-existing duplication — `EpisodeManager` was computing the identical
  value a second time, independently of `TimelineBuilder`, before this
  change — rather than merely preventing a new one. No observable
  behavior change here either: every existing `test_episode_manager.py`
  assertion (including the one checking `EpisodeBuildError.timeline_name`
  on a clip-placement failure) passes unmodified.
- This mission exists solely to resolve a real architectural blocker
  found while reviewing Mission 11's `place_clips` CLI candidate: neither
  `apply_markers()` nor `place_clips()` can be safely exposed by a
  transport without a way to obtain `timeline_name` that doesn't
  duplicate the naming pattern or re-trigger `build_timeline_for_episode()`'s
  marker-duplication side effect. A future `place-clips` CLI command can
  now call `services.timeline_builder.timeline_name_for_episode(episode_id)`
  directly. No CLI, MCP, Resolve, composition, or database change is part
  of this mission — `place-clips` itself remains deferred.
- Scope note: `tests/unit/test_episode_manager.py`'s hand-rolled
  `FakeTimelineBuilder` test double needed `timeline_name_for_episode()`
  added to it as well, to keep that file's existing tests passing against
  the refactored `EpisodeManager.build_episode()` call site — a necessary
  consequence of keeping the existing regression suite genuinely
  unmodified in behavior, not a scope expansion.
- New tests: two direct `timeline_name_for_episode()` tests in
  `tests/unit/test_timeline_builder.py`, proving the helper is
  pattern-driven (a second, different pattern/episode_id combination
  produces a different result) rather than hardcoded. Full suite: 911
  passed, 1 skipped (up from Mission 10's 909 passed, 1 skipped).

## Unreleased - Mission 10: `redline episode build-timeline` CLI

- Adds `redline episode build-timeline <episode_number>` as a sixth
  `episode` action, as a thin wrapper over the existing, already-tested
  `TimelineBuilder.build_timeline_for_episode()`. Continues the
  Resolve-driven CLI layer begun in Mission 9; `apply_markers()` and
  `place_clips()` (the other two `TimelineBuilder` public methods) remain
  internal-only primitives — used by `EpisodeManager.build_episode()`'s
  manifest flow — and are not exposed as independent CLI/MCP surfaces in
  this mission. Timeline IDs also remain internal: the CLI result and
  output report only `episode_id`, `project_name`, `timeline_name`, and
  `markers_applied`, never `timeline_id`.
- `episode_number` is resolved via the same `EpisodeManager.get_episode_status()`
  call every other `episode` action uses. No markers override is ever
  passed to the manager: `TimelineBuilder` owns timeline naming
  (`config.timeline.timeline_name_pattern`) and configured marker
  selection (`config.timeline.markers`) entirely on its own; the CLI does
  not re-derive the timeline name pattern itself anywhere.
- No new composition tier: `ApplicationServices` already provides
  everything this command needs (DB via `EpisodeManager` for episode
  resolution, Resolve via `TimelineBuilder` for the build/marker calls) —
  confirmed sufficient during architecture review, same tier every other
  `episode` action already uses.
- Zero configured markers is a successful result (`markers_applied: 0`),
  not an error, matching the manager's own behavior.
- Exception handling: catches exactly `EpisodeNotFoundError` (own
  episode-number resolution step), `ProjectNotFoundError`, and
  `TimelineOperationError` (both from `redline_core.resolve.exceptions`),
  messages passed through unchanged. `ResolveConnectionError` is excluded
  from this command-local tuple for the same reason established in
  Mission 9 — connection happens during `build_application_services()`,
  already owned by `main()`'s top-level boundary. `mcp_server/tools/timeline_tools.py`
  was not modified in this mission.
- **New required manager-level test**, closing a real, previously-uncovered
  gap found during architecture review: `TimelineBuilder.build_timeline_for_episode()`
  reuses an existing Resolve timeline by name (no duplicate timeline
  object is created on a second call — this was already true and already
  tested at the adapter layer), but it always reapplies the full
  configured marker set regardless, so calling it twice against the same
  episode duplicates markers on the timeline. `tests/unit/test_timeline_builder.py`
  now proves this directly (one timeline name after two calls, but `2N`
  stored markers where `N` is the configured count) — this is documented,
  existing behavior, not something this mission introduces or fixes.
- New tests: `tests/unit/test_cli_episode_build_timeline.py` (17 tests)
  plus the one new repeated-build test in `test_timeline_builder.py`.
  Full suite: 909 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script
  (`--mock-resolve`). Unknown-episode failure was run as a genuinely
  separate process invocation (exit 1). The successful-build case, and a
  second call against the same episode demonstrating the real
  marker-duplication behavior above (`markers_applied: 2` reported on
  both calls, not cumulative), were verified by sharing one
  `MockResolveAdapter` instance across `main()` calls — the same
  technique established in Mission 9 for cross-invocation Resolve state.
  Repo working tree stayed clean throughout.

## Unreleased - Mission 9: `redline episode organize-bins` CLI

- Adds `redline episode organize-bins <episode_number> [--bin-name footage]`
  as a fifth `episode` action, alongside `create`/`scan-ingest`/`status`/
  `list`, as a thin wrapper over the existing, already-tested
  `MediaManager.organize_bins()`. This begins the Resolve-driven CLI layer
  described in the Mission 9 architecture review; `MediaManager.import_media()`
  remains an internal-only primitive (used by `EpisodeManager.build_episode()`'s
  manifest flow) and is deliberately not exposed as its own CLI/MCP surface
  in this mission.
- `episode_number` is resolved to an `Episode` record via the existing
  `EpisodeManager.get_episode_status()` — the same call `scan-ingest`/
  `status` already use — giving `episode_id` and `project_name` for free
  (both already stored on the `Episode` record); no new lookup method or
  translation layer was added. `--bin-name` is passed through unchanged,
  defaulting to the manager's own literal default (`"footage"`) rather
  than inventing a new one.
- No new composition tier: `ApplicationServices` already provides
  everything this command's episode-number resolution and media import
  need (DB via `EpisodeManager`, Resolve via `MediaManager`) — confirmed
  sufficient during architecture review, same tier every other `episode`
  action already uses. `--mock-resolve` remains relevant, since this
  command genuinely calls `resolve.import_media()`.
- Zero matching ingest files is a successful result (`clip_count: 0`,
  `clip_ids: []`), not an error — matches `organize_bins()`'s own
  behavior (it returns `[]` without calling Resolve at all when nothing
  matches) and every prior mission's "empty state is still success"
  precedent. No episode-status update, no duplicate detection, no retry
  or rollback logic was added — `organize_bins()` doesn't perform any of
  those today, and this CLI action doesn't invent them.
- Exception handling: catches exactly `EpisodeNotFoundError` (from the
  CLI's own episode-number resolution step), `ProjectNotFoundError`, and
  `MediaImportError` (both from `redline_core.resolve.exceptions`,
  propagating through `MediaManager.import_media()` →
  `resolve.import_media()`), messages passed through unchanged.
  `ResolveConnectionError` is deliberately excluded from this command-local
  tuple — connection happens during `build_application_services()`, before
  this action's handler runs, and is already owned by `main()`'s existing
  top-level exception boundary. Unlike Missions 6-8, there was no
  already-defensive MCP tool to mirror here: `mcp_server/tools/media_tools.py`'s
  `organize_bins` tool has no exception handling of its own (see
  `docs/ARCHITECTURE.md`) — this CLI action's exception tuple was derived
  directly from what the manager/adapter can actually raise, not copied
  from the MCP transport. `mcp_server/tools/media_tools.py` itself was not
  modified in this mission.
- New tests: `tests/unit/test_cli_episode_organize_bins.py` (16 tests)
  plus one new custom-bin-name-forwarding test added to
  `tests/unit/test_media_manager.py` (a direct spy on the Resolve adapter
  call, proving forwarding without coupling to `MockResolveAdapter`'s
  internal clip-ID formatting or storage). Full suite: 895 passed, 1
  skipped.
- Manual smoke test: ran the installed `redline` console script
  (`--mock-resolve`) against an isolated temp config/DB. The zero-match
  and unknown-episode cases were run as genuinely separate process
  invocations (exit 0 and exit 1 respectively). The matched-media success
  case cannot be demonstrated across two separate real CLI invocations
  under `--mock-resolve` — confirmed directly: attempting it produced
  `ProjectNotFoundError`, since `MockResolveAdapter` has no persistence
  and `main()` builds a fresh instance every invocation, so a Resolve
  project created by one process doesn't exist for a separately-invoked
  one. That `ProjectNotFoundError` passthrough is itself a correct,
  real-world confirmation of this mission's failure handling. The
  matched-media success path was then verified directly against the
  installed package's own `cli.main.main()`, sharing one
  `MockResolveAdapter` instance across two calls (the same technique the
  automated end-to-end test uses) — episode created, clip imported,
  correct fields reported, exit 0. Repo working tree stayed clean
  throughout.

## Unreleased - Mission 8: `redline archive episode <episode_id>` CLI

- Adds the mutating `redline archive episode <episode_id>` action to the
  existing `archive` resource group (alongside Mission 7's `archive
  list`), as a thin wrapper over the existing, already-tested
  `ArchiveManager.archive_episode()`. `episode_id` is passed through
  completely unchanged — no type coercion, no `episode_number →
  episode_id` translation layer, resolving the argument-type finding
  recorded in Mission 7: the manager has always taken a raw string
  identifier (e.g. `"RLC-E025"`), never an episode number, and no call
  site anywhere in the repo has ever translated one into the other.
- Success output reports only the three fields on the manager's returned
  `ArchiveRecord` (`episode_id`, `archive_path`, `archived_at`) — reusing
  the existing `_archive_to_dict` from Mission 7 — with no additional
  Database or filesystem reads. Deliberately **no per-step progress
  checklist** (unlike `episode create`'s ✓ lines): this command reports
  the outcome, not `ArchiveManager`'s internal algorithm, so the CLI
  output stays correct even if the manager's internal steps change later
  (e.g. if its three DB writes are ever made transactional). See
  `docs/ARCHITECTURE.md` for where that internal-implementation detail
  now lives instead.
- Exception handling exactly mirrors the existing MCP tool
  (`mcp_server/tools/archive_tools.py._archive_episode`): catches
  `EpisodeNotFoundError` (from `redline_core.episode.exceptions`),
  `EpisodeAlreadyArchivedError`, and `ArchiveError` (both from
  `redline_core.archive.exceptions`) in one tuple, `str(exc)` passed
  through unchanged — no translation, no enrichment. Exit code `0` on
  success, `1` on any of the three exception types.
- Closes the one previously-uncovered `ArchiveManager` branch identified
  during Mission 8's architecture review: a pre-existing folder already
  sitting at the archive destination path with no matching archive
  record. Covered at two independent levels, per explicit instruction:
  `tests/unit/test_archive_manager.py` proves `ArchiveManager` itself
  raises `ArchiveError` for this condition (and that the source folder is
  left untouched, since `shutil.move()` never runs); the CLI's own test
  only proves the CLI passes that manager error through unchanged — it is
  not treated as that branch's only coverage.
- No composition change: `PersistenceServices` (Mission 7) already
  provided everything `archive_episode()` needs (`config.paths.archive_path`,
  `db`) — confirmed sufficient during architecture review, no new tier
  added.
- New tests: `tests/unit/test_cli_archive_episode.py` (11 tests) plus one
  new destination-collision test added to
  `tests/unit/test_archive_manager.py`. Full suite: 881 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script against
  an isolated temp config/DB (outside the repo tree), no `--mock-resolve`
  set. Confirmed both a successful archive (folder moved, DB fields
  updated, correct fields printed) and the destination-collision failure
  (folder left untouched, `ArchiveError` message printed unchanged, exit
  1). Repo working tree stayed clean throughout.

## Unreleased - Mission 7: `redline archive list` CLI + `PersistenceServices` composition path

- Adds the CLI's third resource group, `redline archive list` (no
  arguments), as a thin, read-only wrapper over the existing,
  already-tested `ArchiveManager.list_archives()`. Serialization reuses
  the exact three-field shape (`episode_id`/`archive_path`/`archived_at`)
  the existing MCP `list_archives` tool already uses. Order is whatever
  the DB returns (`SELECT * FROM archives ORDER BY archived_at`, no
  secondary sort key — a real latent nondeterminism on ties, not
  something this mission changes); the CLI does not re-sort. This
  mission adds only `archive list` — the mutating
  `redline archive episode <episode_id>` is deliberately deferred to a
  following mission, sequenced after this strictly smaller, read-only
  command per the same "smallest capability first" discipline every
  prior mission followed.
- New composition path:
  `redline_core.runtime.composition.PersistenceServices` /
  `build_persistence_services()` — configuration-backed services
  requiring SQLite persistence, but not Resolve. This is a third,
  distinct composition boundary alongside `ApplicationServices` (full
  runtime) and `CoreServices` (config-only), not a universal middle
  layer future commands default into; a manager only belongs here if it
  needs config and a DB connection but never touches Resolve, exactly
  `ArchiveManager`'s case. `ApplicationServices`/
  `build_application_services()` and `CoreServices`/
  `build_core_services()` are both **unchanged** — still the same full
  runtime and config-only paths as before. Small private construction
  helpers (`_resolve_config_dir`, `_resolve_db_path`, `_connect_database`)
  were extracted and are now shared by all three public builders, purely
  to avoid duplicating the same few lines a third time; none of the
  three public builders' own behavior changed as a result.
- **Argument-type finding from architecture review, resolved before
  implementation, not after.** This mission was expected to plausibly be
  `redline archive episode <episode_number>`, matching every other
  `episode`-adjacent CLI action so far. Fresh review of
  `ArchiveManager.archive_episode()` found it takes `episode_id: str`
  (e.g. `"RLC-E025"`), not an `episode_number: int` — confirmed against
  every existing call site (the MCP tool, all `test_archive_manager.py`
  tests). When Mission 8 implements the mutating `archive episode`
  command, its argument will be named and typed `<episode_id>` to match
  the real contract, not `<episode_number>` — this is a deliberate,
  reviewed decision, not an oversight, and does not affect this mission's
  read-only `archive list` (which takes no arguments at all).
- `list_archives()` has no failure modes of its own to report (no
  filtering, no arguments, nothing that can raise per the existing,
  already-tested manager) — `_run_archive_list()` always returns
  `success: True`, matching the existing MCP tool's shape exactly.
- New tests: `tests/unit/test_cli_archive_list.py` (10 tests) plus 4 new
  `build_persistence_services()` tests added to
  `tests/unit/test_composition.py`. Full suite: 870 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script against
  an isolated temp config/DB (outside the repo tree) with no
  `--mock-resolve` flag set — `archive list` printed "No archives found."
  on an empty DB and correctly displayed a seeded archived episode
  (`RLC-E025`) after one was created directly via `ArchiveManager`,
  confirming the command genuinely never depends on Resolve. Repo working
  tree stayed clean throughout (smoke test ran entirely under `/tmp`, not
  inside the repo).

## Unreleased - Mission 6: `redline asset verify` CLI

- Adds `redline asset verify [asset_id ...]`, a thin, read-only wrapper
  over the existing, already-tested `AssetManager.verify_assets_for_episode()`.
  Same `CoreServices` composition path as `asset list` — no DB, no Resolve.
- **Correction from the original Mission 6 framing.** This mission was
  initially sketched as `redline asset verify <episode_number>`, described
  as "the first cross-domain (episode + asset) CLI command." Fresh
  architecture review of `verify_assets_for_episode()`'s actual signature
  found it takes no episode identifier at all — just an optional
  `asset_ids: list[str] | None` override, defaulting to
  `config.assets.required_for_episode` (a single global list, not
  per-episode) when omitted. Every call site in the repo (the MCP tool,
  all existing unit tests) confirms this — none has ever passed an
  episode identifier. Building a CLI command that accepted
  `<episode_number>` and then didn't use it for anything would have been
  misleading UI, the same category of correction as Mission 2's original
  "ingest media" sketch and Mission 1's manifest/log lines. The command
  matches the real contract instead: no episode argument, not a
  cross-domain command.
- `found`/`missing` in the result dict reuse the existing MCP tool's exact
  shape (bare asset-ID strings, `all_present` bool) rather than inventing
  a richer one. A CLI-only `checked` list is built for display (`asset_id`,
  `status`, `path`) — but its `status` is assigned strictly from the
  manager's own `found`/`missing` result, never from a second
  `.is_file()` check in the CLI; the manager stays the sole authority on
  whether an asset is present. `path` is a display-only string built from
  `config.assets.get(asset_id).filename`, shown as `(not registered)`
  when no definition exists. Effective input order (explicit override, or
  `required_for_episode` when omitted) and duplicate asset IDs are both
  preserved as given, not re-sorted or deduplicated — matching the
  manager's own behavior exactly.
- Handles a real correctness trap at the argparse boundary: `nargs="*"`
  gives `[]` when no `asset_id` is passed, but the manager treats `[]`
  ("verify zero assets") and `None` ("use the configured default set")
  as different things. `asset_commands.run()` converts an empty parsed
  list to `None` before calling the handler, so `redline asset verify`
  with no arguments correctly triggers the default set rather than
  silently verifying nothing. Tested explicitly, both at the handler level
  and end-to-end through `main()`.
- Exit code is `0` for any completed verification, including one that
  finds missing assets — mirrors the existing MCP tool's `success: True`-
  always contract (missing assets is a reported result, not an operation
  failure). Exit `1` is reserved for genuine operational failures, handled
  by the existing top-level exception boundary in `main()` — no new logic
  needed for that.
- New tests: `tests/unit/test_cli_asset_verify.py` (14 tests). Full suite:
  858 passed, 1 skipped.

## Unreleased - Mission 5: `redline asset list` CLI + config-only composition path

- Adds the CLI's second resource group, `redline asset list` (no
  arguments), as a thin, read-only wrapper over the existing,
  already-tested `AssetManager.list_available_assets()`. Serialization
  reuses the exact three-field shape (`asset_id`/`description`/`filename`)
  the existing MCP `list_available_assets` tool already uses. Order is
  whatever the manager returns (config declaration order in
  `config/assets.yaml`) — not re-sorted; this ordering was never an
  explicitly asserted contract at the `redline_core` layer (the existing
  unit test checks membership via a set, not order), so this is presented
  as "current behavior," not a documented guarantee, and preserved as-is.
- New composition path: `redline_core.runtime.composition.CoreServices` /
  `build_core_services()` — configuration-backed services requiring
  neither SQLite nor Resolve (no adapter constructed or connected at all),
  scoped to exactly that dependency boundary rather than serving as a
  general "core" layer future commands default into; a manager only
  belongs here if it needs nothing but config, exactly
  `list_available_assets()`'s case. `ApplicationServices`/
  `build_application_services()` is **unchanged** —
  still the full runtime for the MCP server and every `episode` command.
  This was the first mission where a command actually demonstrated the
  need for the capability-specific construction deferred back in Mission
  1 — architecture review surfaced that `asset list` would otherwise fail
  without Resolve running despite touching nothing Resolve-related, which
  is exactly the situation that deferral was meant to avoid once a real
  case showed up.
  - Scoped narrowly per explicit instruction: no generic dependency-tier
    framework, no lazy DI container, no rework of Missions 1-4's
    `episode` commands (still on `ApplicationServices`, untouched).
  - `main.py` now selects the composition path per resource group before
    dispatch, rather than building one runtime unconditionally — routing
    logic, not new architecture.
  - Verified structurally, not just by inspection: a test monkeypatches
    `Database.connect`/`ResolveScriptAdapter.connect`/`.__init__` to raise
    if called, then calls `build_core_services()` and confirms no
    exception — proving the independence claim rather than assuming it
    from the implementation reading the same way twice.
  - Verified at the CLI-invocation level too: `redline asset list` runs
    successfully with `REDLINE_DB_PATH` unset and no `--mock-resolve`
    flag, and no `redline.db` file appears afterward — the real, visible
    payoff of the fix.
- New tests: `tests/unit/test_cli_asset_list.py` (9 tests), plus 3 new
  `build_core_services()` tests added to `tests/unit/test_composition.py`.
  Full suite: 844 passed, 1 skipped.

## Unreleased - Mission 4: `redline episode list` CLI + CLI module split

- Adds a fourth CLI action, `redline episode list` (no arguments), as a
  thin, read-only wrapper over the existing, already-tested
  `EpisodeManager.list_episodes()`. No filtering, pagination, or alternate
  ordering added — none exists on the underlying method (`SELECT * FROM
  episodes ORDER BY episode_number`, no `LIMIT`/`OFFSET`), so none was
  invented for the CLI either. Empty state ("No episodes found.") is a
  successful result (exit 0), matching the manager's own contract — zero
  episodes was never an error case anywhere in the stack.
- Splits `src/cli/` into a thin `main.py` (parser assembly, logging setup,
  building `ApplicationServices`, dispatch, exit-code translation) plus a
  new `episode_commands.py` holding every `episode` action's logic —
  `_run_*`/`_print_*` handler pairs, `_episode_to_dict`, subparser
  registration, and dispatch. This was one of the two trigger points
  agreed on in Mission 2 (`episode list` becoming a fourth action, or a
  new resource group appearing) for reconsidering the single-file
  structure; the other (a new resource group, e.g. `asset`) hasn't
  happened yet.
  - Mechanical move only: no generic command registry, base command
    classes, shared result dataclasses, printer framework, or DI
    container was introduced alongside the split.
  - Existing Mission 1-3 tests (`test_cli_episode_create.py`,
    `test_cli_episode_scan_ingest.py`, `test_cli_episode_status.py`) pass
    **unmodified** — `cli/main.py` re-exports the moved names
    (`_run_episode_create`, `_print_episode_create_result`, etc.) as thin
    aliases for backward compatibility, so no test file needed to change
    its imports.
- New tests: `tests/unit/test_cli_episode_list.py` (8 tests). Full suite:
  833 passed, 1 skipped.

## Unreleased - Mission 3: `redline episode status` CLI

- Adds a third CLI action, `redline episode status <episode_number>`, as a
  thin, read-only wrapper over the existing, already-tested
  `EpisodeManager.get_episode_status()`. No computed health checks,
  readiness inference, media counts, asset verification, or build
  validation — only what's already persisted on the `Episode` row.
- Extends the shared `_episode_to_dict()` helper (used by `episode create`
  since Mission 1) with three additional fields: `id`, `created_at`,
  `updated_at`. Purely additive — `episode create`'s own output doesn't
  reference the new keys, and a dedicated test
  (`test_episode_create_output_unaffected_by_new_fields`) proves its output
  is unchanged. `created_at`/`updated_at` are passed through as-is: they're
  already deterministic `TEXT` columns (SQLite's `datetime('now')`) by the
  time they reach the `Episode` dataclass, not Python `datetime` objects,
  so no new formatting/parsing logic was introduced to make them
  "JSON-safe" — that safety already existed.
- Architecture review for this mission also produced a full inventory of
  every `redline_core` capability not yet CLI-exposed (see
  `docs/ARCHITECTURE.md` §5.1 note). Render commands (`queue_render`,
  `get_render_status`, `cancel_render`) were explicitly ruled out for any
  near-term CLI mission — the real Resolve adapter methods behind them are
  still stubbed per this README's own "Still open" note, so a CLI surface
  over them today would front a non-functional real-Resolve path.
- `src/cli/main.py` stays a single file — reassess only when `episode list`
  becomes a fourth action or a new top-level resource group (e.g. `asset`)
  is introduced, per the explicitly agreed trigger points.
- New tests: `tests/unit/test_cli_episode_status.py` (9 tests). Full suite:
  825 passed, 1 skipped.

## Unreleased - Mission 2: `redline episode scan-ingest` CLI

- Adds a second CLI command, `redline episode scan-ingest <episode_number>`,
  as a thin, read-only wrapper over the existing, already-tested
  `MediaManager.scan_ingest_for_episode()`. Zero new business logic:
  matching is still purely by episode-ID substring in the filename,
  regardless of extension (a `.txt` file matches exactly as readily as a
  `.mov`), and a missing ingest folder is treated the same as "no
  matches" — the existing method's behavior, not a new distinction
  invented for this slice.
- Deliberately does **not** add media-type classification (video/audio/
  graphic), duplicate detection, file copying/moving/renaming, Asset
  Registry insertion, or Resolve media-pool import (that's the separate,
  existing `organize_bins()`, still not CLI-exposed). Confirmed during
  architecture review that none of this is on the approved roadmap or
  built anywhere yet — the Persistent Asset Registry / reconciliation
  engine (Milestone 10) explicitly excludes duplicate-content detection
  from its own scope and covers a different domain (externally-approved
  Universe assets, not raw incoming episode footage). Output ends with an
  explicit disclaimer ("No files were classified, deduplicated, copied,
  moved, imported, or registered.") so a scan is never mistaken for
  completed ingestion.
- `src/cli/main.py` stays a single file for now rather than splitting into
  per-resource command modules — two commands doesn't yet justify that
  structure; revisit when a third command makes the file unwieldy.
- New tests: `tests/unit/test_cli_episode_scan_ingest.py` (9 tests), same
  tmp-path-isolated-config discipline established in Mission 1. Full
  suite: 816 passed, 1 skipped.

## Unreleased - Mission 1: `redline episode create` CLI

- Redline OS is now reachable from a terminal, not just as MCP tool calls.
  Adds a second, sibling transport: `src/cli/` (mirrors `mcp_server/`'s thin
  shape) with one command, `redline episode create <episode_number>`
  (`--mock-resolve` supported, same as `mcp_server.server`'s flag), wired
  via a new `redline` console-script entry point.
- Extracts the shared composition root out of `mcp_server/context.py` into
  a transport-neutral `redline_core/runtime/composition.py`
  (`ApplicationServices` / `build_application_services()`), so both
  transports build Config + Database + Resolve connection + all six
  managers from one place instead of duplicating the wiring.
  `mcp_server/context.py` is now a thin alias (`AppContext =
  ApplicationServices`) delegating to it — no behavior change for the MCP
  server; `tests/unit/test_mcp_tools.py` passes unmodified as proof.
- Deliberately does **not** add `CompositionOptions`/capability-specific
  construction (e.g. skip-Resolve) in this slice — no command yet needs a
  partial runtime, so that flag would have no real caller or acceptance
  test. Add it when the first genuinely Resolve-optional command (e.g.
  `episode inspect`, `config validate`) is actually built.
- Deliberately does **not** add a new "episode manifest" output artifact or
  a dedicated per-episode log file, despite both appearing in the original
  Mission 1 sketch — the former would collide with the existing, differently
  -scoped Episode Manifest V1 (input intent for `build_episode`, not an
  output receipt); the latter is already covered by the existing shared
  `redline_os.log` (`get_episode_logger`). Checklist wording reflects this:
  "Resolve project initialized" rather than "duplicated," since duplication
  is an implementation detail, not what the user needs to know.
- Zero changes to `EpisodeManager`, `MediaManager`, `TimelineBuilder`,
  `RenderManager`, `ArchiveManager`, or `AssetManager` business logic — this
  slice only adds a second way to reach the existing, already-tested
  `EpisodeManager.create_episode()` path.
- New tests: `tests/unit/test_composition.py` (4 tests) and
  `tests/unit/test_cli_episode_create.py` (13 tests). Every test that
  actually calls `create_episode()` uses an in-memory or tmp-path-scoped
  config rather than the real `config/` directory, since the real
  `config/folder_structure.yaml` root_path is a relative `./_episodes` that
  a naive test would otherwise write into the actual repo working tree.
  Full suite: 807 passed, 1 skipped.

## Unreleased - Asset Registry Reconciliation Repository Integration Compatibility (Phase 3 Slice 11)

- No production code changed. This slice adds two integration test files
  only, per the approved "Phase 3 Slice 11 Implementation Contract --
  Integration Compatibility (Roadmap Row 13), Revision 3 (final)":
  `tests/integration/test_snapshot_loading_from_sqlite_repository.py` (6
  tests) and `tests/integration/test_reconciliation_repository_compatibility.py`
  (11 tests) -- 17 tests total, matching the approved contract's test
  matrix 1:1 by number.
- Proves that a `RegistrySnapshot` populated from records read out of a
  real, temporary SQLite database via the existing (Phase 1/2)
  `SQLiteAssetRepository` flows through the unmodified reconciliation
  chain (`validate_reconciliation_inputs` -> `build_indexes` ->
  `build_matching_state` -> `evaluate_record_observability` ->
  `classify_reconciliation` -> `plan_reconciliation` ->
  `serialize_public_plan`) exactly as a `RegistrySnapshot` built from
  in-memory `AssetRegistryRecord` literals already does in the Slice 1-10
  unit tests.
- `AssetRegistryRecord.record_id` is proven immaterial to any serialized
  plan field at current HEAD by direct source inspection (no code path
  between `validate_reconciliation_inputs` and `serialize_public_plan`
  reads it, and every production `RegistryRecordSubject` construction
  passes only `asset_id`) -- not assumed. This is exercised directly: a
  cross-domain equivalence test uses a deliberately different `record_id`
  on its in-memory comparison side, and a reversed-insertion-order test
  across two independently-seeded temporary databases first asserts the
  two databases assigned different `record_id` values for a shared
  `asset_id`, then asserts identical canonical serialized bytes anyway.
- "No writes" and "no schema change" are verified as data-level
  before/after comparisons of repository-visible record state
  (`count_records`, `list_records`) and a direct, read-only
  `sqlite_master` + schema-version snapshot (filtered by `tbl_name` so
  both named and SQLite auto-generated indexes are captured, not just
  objects literally named `asset_registry...`) -- not as a claim that any
  specific repository write method was never called, since the
  reconciliation pipeline never holds a reference to the repository
  object in the first place.
- Component ownership is preserved: the corrected path/root-scope test
  builds its snapshot from `list_records(...)` (a complete registry read)
  and lets `ObservationScope.roots`/`evaluate_record_observability`
  perform the actual scope evaluation, rather than letting
  `get_by_normalized_path(...)` pre-filter which records reconciliation
  ever sees. A separate, explicitly-labeled bridge assertion independently
  confirms `get_by_normalized_path(...)` results are themselves valid
  `RegistrySnapshot` inputs, without claiming that proves scope
  resolution.
- No package-root export change (`__init__.py` and
  `test_package_exports.py` unmodified); no change to
  `src/redline_core/asset/sqlite_repository.py` or any reconciliation
  production module.
- Full existing `tests/unit` suite remains passing unchanged (794 passed,
  1 skipped, 795 total, exit code 0), and the pre-existing repository
  integration tests remain passing unchanged (`test_asset_sqlite_repository.py`,
  `test_asset_database_initialization.py`, 52 tests). Note: this
  repository's `pyproject.toml` sets `testpaths = ["tests/unit"]`, so a
  bare `python -m pytest` does not collect `tests/integration/` at all --
  running `python -m pytest tests/unit tests/integration` explicitly is
  required to exercise this slice's tests (and the pre-existing repository
  integration tests) as part of a genuinely complete regression run: 863
  passed, 1 skipped, 864 total, exit code 0.

## Unreleased - Asset Registry Reconciliation Public Serialization (Phase 3 Slice 10)

- `redline_core.asset.reconciliation.serialization`: new module implementing
  public plan serialization, per the approved "Phase 3 Slice 10
  Implementation Contract -- serialization.py, Revision 3 (final)". Adds
  the public entry point
  `serialize_public_plan(plan, *, limit_policy=DEFAULT_LIMITS) -> dict[str, Any]`,
  which converts one already-built `ReconciliationPlan` (Slice 9 output)
  into a stable, deterministic, JSON-compatible public dictionary.
- Redaction is a **structural allowlist**, not a per-fact `PublicVisibility`
  evaluation: `serialize_public_plan` walks the known, fixed set of fields
  on `ReconciliationPlan`/`ReconciliationPlanItem`/`PlanSummary`/
  `PlanSubject` explicitly, field by field -- never
  `dataclasses.asdict()`, `vars()`, `__dict__`, or any other
  reflection-based dump, so a future domain-model field does not
  automatically appear in public output. `PublicVisibility` and the other
  Slice-1 evidence-model enums remain unused, exactly as they are unused
  by every module built so far; no visibility classification is invented
  or inferred by this slice.
- `RegistryRecordSubject.record_id` is never emitted, whether populated or
  `None` -- `asset_id` is the stable public business identifier;
  `record_id` is an optional internal row reference the approved contract
  deliberately excludes from the public DTO.
- Determinism and the size guard both use one exact canonical byte
  definition:
  `json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")`.
  If that byte length exceeds `limit_policy.max_serialized_public_plan_bytes`,
  `serialize_public_plan` raises the existing `ReconciliationLimitExceededError`
  (no new exception class) with
  `context={"limit_name": "max_serialized_public_plan_bytes", "limit_value": ...}`
  -- no truncation, no partial payload. The function still returns the
  plain public `dict`, never bytes or a JSON string.
- No `PublicPlanSerializer` class exists; `serialize_public_plan` is a bare
  function, matching every other Slice 5-9 module's convention.
- `serialize_public_plan` does not re-run `planner.py`'s domain validation
  or recompute plan state; it projects the already-valid structure it is
  given. One output-integrity check (not a domain revalidation) confirms
  every emitted `evidence_ref` in the DTO this function itself builds
  appears in that same DTO's own top-level `evidence` list.
- `redline_core.asset.reconciliation.__init__.py` is **not** modified.
  `serialize_public_plan` is importable only as
  `redline_core.asset.reconciliation.serialization.serialize_public_plan`,
  matching the established precedent that `build_indexes`,
  `build_matching_state`, `classify_reconciliation`, and
  `plan_reconciliation` are also not package-root exports. This keeps
  `tests/unit/asset/reconciliation/test_package_exports.py` (Slices 1-2,
  unmodified) passing exactly as already approved.
- 26 new test cases across 20 numbered tests (`test_serialization.py`,
  matching the approved contract's test matrix 1:1 by number); full
  existing suite of 558 prior tests remains passing, 584 total, plus 1
  pre-existing unrelated skip.

## Unreleased - Manifest Validator: Avoid Process-Wide os.name Monkeypatch (Task #38)

- `redline_core.manifest.validator`: replaced a direct `os.name` monkeypatch in
  test code with a module-local `_is_windows()` indirection, used internally
  by `_duplicate_key()`. This is a test-hygiene / cross-cutting infrastructure
  fix, unrelated to Phase 3 reconciliation.
- The prior test
  (`test_windows_duplicate_key_strategy_is_case_insensitive`) patched the
  shared, process-wide `os` module's `name` attribute directly
  (`monkeypatch.setattr(manifest_validator.os, "name", "nt")`). Even though
  `monkeypatch` reverts this after the test, the mutation was observed to
  interact badly with pytest's own internal `pathlib.Path()` usage later in
  the same full-suite run, producing an unrelated `WindowsPath`
  `INTERNALERROR` at teardown/report time under certain collection orders.
- Fix: `validator.py` now exposes a small private function
  `_is_windows() -> bool` (returns `os.name == "nt"`), and `_duplicate_key()`
  calls this indirection instead of reading `os.name` directly. The test now
  patches `_is_windows` itself
  (`monkeypatch.setattr(manifest_validator, "_is_windows", lambda: True)`),
  exercising the same Windows-specific casefold branch without mutating any
  shared interpreter state.
- No behavior change to `_duplicate_key()`'s duplicate-key normalization
  logic; the Windows casefold branch itself is unchanged, only how it is
  tested. `tests/unit/test_manifest_validator.py` updated accordingly (1 test
  changed).
- Unrelated to Phase 3 Asset Registry Reconciliation; committed as its own
  isolated commit (`dd5959a`) between Slice 9 (`planner.py`) and Slice 10
  (`serialization.py`), per this project's standing discipline of never
  bundling an infrastructure fix into feature work.

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 9)

- `redline_core.asset.reconciliation.planner`: new module implementing final
  plan assembly, per the approved "Phase 3 Slice 9 Implementation Contract --
  planner.py, Revision 4 (final)". Adds the public entry point
  `plan_reconciliation(inputs, classification_state, *, created_at)`, which
  assembles one immutable `ReconciliationPlan` directly from Slice 8's
  `ClassificationState` -- no `findings.py`/`actions.py` object system.
- Plan item order is exactly `ClassificationState.decisions` order,
  index-for-index; no classification "rank" is invented or stored.
  Deterministic `item_id`s (`item-000001`, `item-000002`, ...) are assigned
  over that same order.
- `ReconciliationPlanItem.findings` and `.actions` are always `()` for every
  item, for every classification, with no exceptions; `evidence_refs` carries
  `ClassificationDecision.evidence_facts` forward unchanged.
  `PlanSummary.severities` and `PlanSummary.action_kinds` are always empty
  mappings. No action-kind mapping, severity table, or other domain policy is
  introduced by this slice -- all deferred to a future `actions.py`/
  `findings.py` contract, per the approved contract's Decisions 2, 3, and 5.
- No `ReconciliationPlanner` class exists; `plan_reconciliation` is a bare
  function, matching every other Slice 5-8 module's convention (contract
  Decision 4).
- `_limit_policy_fingerprint` (private, local to `planner.py`) computes a
  stable SHA-256 fingerprint over `ReconciliationLimitPolicy`'s fields,
  sorted by name; `canonical.py` is not modified (contract Decision 6).
- `redline_core.asset.reconciliation.__init__.py` is **not** modified.
  `plan_reconciliation` is importable only as
  `redline_core.asset.reconciliation.planner.plan_reconciliation`, matching
  the established precedent that `build_indexes`, `build_matching_state`,
  and `classify_reconciliation` are also not package-root exports. This
  keeps `tests/unit/asset/reconciliation/test_package_exports.py` (Slices
  1-2, unmodified) passing exactly as already approved.
- 58 new tests (`test_planner.py`), including a hand-built
  `PrimaryClassification.INVALID_OBSERVATION` decision confirming
  `PlanSummary.invalid_observation_count` actually increments (not just that
  it stays zero for classifications Slice 8's real pipeline can currently
  emit); full existing suite of 500 prior tests remains passing, 558 total,
  plus 1 pre-existing unrelated skip.
- `_verify_plan_invariants` checks each item ID against its exact expected
  position (`item-{index:06d}`), not merely uniqueness -- catching any
  ordering defect, not just collisions.

## Unreleased - Phase 3 Documentation Reconciliation (Post-Slice 8)

- Corrected `docs/ASSET_RECONCILIATION_ARCHITECTURE.md` and
  `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md` to accurately describe
  the bounded string-code evidence convention `matching.py` (Slice 6/7) and
  `classification.py` (Slice 8) already established and documented in their
  own docstrings. No code or tests changed.
- The current implementation uses the bounded string evidence model. The
  original `PlanEvidence`/`ReconciliationFinding`/action-object design
  remains documented as an earlier architectural proposal and is not part
  of the current Phase 3 implementation path — not removed and not judged
  permanently unnecessary. `findings.py`, `actions.py`, and richer
  structured evidence are reclassified as future / re-evaluate after
  `planner.py` and `serialization.py` are implemented.
- `evidence.py`: no rich `PlanEvidence` extension is required for the
  current Phase 3 critical path.
- Roadmap numbering in `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md`,
  section 25 is unchanged (rows 9, 10, 11 keep their existing numbers and
  module assignments). Row 11's dependency is corrected to name Slice 8
  directly, with an explicit Sequencing Note rather than a renumbering. The
  note also defines roadmap row numbers and implementation slice numbers as
  independent terminology, so `planner.py`, if built next, is correctly both
  Phase 3 Slice 9 and roadmap row 11 — see the row itself.

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 8)

- `redline_core.asset.reconciliation.classification`: new module implementing
  the central ordered classification engine, per the approved "Slice 8
  Implementation Contract -- Revision 3" (architecture-only session; no code
  changed during contract drafting). Adds `ClassificationDecision`,
  `ClassificationState`, and the public entry point
  `classify_reconciliation(inputs, indexes, matching_state,
  observability_by_asset_id)`.
- Implements a strict 15-rank executable precedence table (first match wins):
  registry identity evidence conflict, registry identity collision,
  authoritative identity conflict, content conflict, duplicate path conflict,
  ambiguous match, unknown authoritative Asset ID, path changed, lifecycle
  conflict, availability changed, record not observed, new unregistered
  observation, unchanged, metadata drift, insufficient scope.
- Four `PrimaryClassification` enum members (`REGISTRY_SNAPSHOT_INVALID`,
  `INVALID_OBSERVATION`, `UNSUPPORTED_OBSERVATION`, `DIAGNOSTIC_ONLY`) are
  documented as intentionally non-executable in this slice and are never
  produced; `DIAGNOSTIC_ONLY` in particular is not a catch-all -- a subject
  that matches no rule raises `ReconciliationInvariantError`
  (`reason_code="classification_no_rule_matched"`) instead.
- `observability_by_asset_id` is an explicit input contract: the caller
  resolves scope (via `scope.evaluate_record_observability`) for every
  unmatched registry record before calling `classify_reconciliation`; a
  missing entry raises `ReconciliationInvariantError`
  (`reason_code="classification_missing_observability_decision"`) rather than
  defaulting silently.
- `SIZE_CONFLICT` is not added to `PrimaryClassification` in this slice
  (deferred to a future dedicated slice, Decision 5a). Pending that slice, a
  size difference with no comparable verified hash classifies as
  `METADATA_DRIFT` with `requires_review=True` and evidence fact
  `size_differs_no_comparable_hash` -- documented as interim, temporary
  policy, not permanent semantics.
- `registry_identity_evidence_conflict` required no new index: computed
  directly from `indexes.registry.record_evidence_by_asset_id`, already
  built by Slice 5.
- `classification.py` imports `indexes.py` directly; the implementation
  plan's advisory import list for this module is corrected to include it
  (Decision 7) -- `findings.py` and `actions.py` do not exist yet in this
  repository and are not part of this slice's dependencies.
- 32 new tests (`tests/unit/asset/reconciliation/test_classification.py`),
  matching the "Slice 8 Implementation Contract -- Revision 3" exhaustive
  test matrix 1:1 by number; all prior Slice 1-7 reconciliation tests and the
  full existing suite (468 tests) remain unchanged and passing (500 total).

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 7)

- `redline_core.asset.reconciliation.matching`: added strong-identity
  matching (`unique_strong_identity`), extending `build_matching_state`
  after trusted-Asset-ID and exact-path matching (Slice 6). Precedence:
  trusted Asset ID > exact normalized path > unique strong identity.
- Bridges the registry's five-component comparable-evidence key
  (`RegistryEvidenceLookupKey`) and the observation's three-component key
  (`ObservationIdentityKey`) privately inside `matching.py`, without
  modifying `indexes.py`; see `docs/ASSET_RECONCILIATION_ARCHITECTURE.md`
  "Implementation Note: Registry/Observation Identity-Key Bridge" for the
  disclosed semantic consequence of that reduction.
- Adds `registry_identity_collision`, `observation_identity_collision`, and
  `mixed_identity_collision` conflict facts for ambiguous strong-identity
  evidence, and preserves existing trusted-ID/exact-path associations when
  strong identity disagrees with them (`strong_identity_authoritative_conflict`
  / `strong_identity_content_conflict`) rather than overwriting them.
  `indexes.py`, `MatchingState`, and `ConsumedIds` are unchanged.
- 50 new tests (`tests/unit/asset/reconciliation/test_matching_strong_identity.py`);
  all prior Slice 1-6 reconciliation tests remain unchanged and passing.
- Note: Slices 1-6 of this same reconciliation engine (`enums.py`/`models.py`
  through `matching.py`'s trusted-ID/exact-path stage) were implemented and
  approved in prior work but were never given their own changelog entries;
  this is a pre-existing documentation gap, not something this entry
  retroactively fills beyond Slice 7 itself.

## Unreleased - Persistent Asset Registry Architecture

- Added the Milestone 10 Persistent Asset Registry V1 architecture design
  package: `docs/ASSET_REGISTRY_ARCHITECTURE.md`,
  `docs/ASSET_REGISTRY_SCHEMA.md`, `docs/ASSET_REGISTRY_LIFECYCLE.md`, and
  `docs/ASSET_REGISTRY_VALIDATION.md`.
- Documented authority boundaries: the external Redline Production System
  remains authoritative for Asset IDs and production standards,
  `config/assets.yaml` is the desired-state declaration and explicit
  reconciliation input, SQLite owns local Redline OS operational registry state,
  filesystem checks are
  point-in-time observations, and MCP remains a future thin presentation layer.
- Documented the recommended V1 registry shape: one active local registry record
  per external Asset ID, one resolved local path per active record, explicit
  config reconciliation with dry-run planning, transactional apply behavior, no
  startup mutation, and no normal public hard deletion.
- Documented V1 lifecycle, availability, verification, path-safety, error,
  logging, transaction, reconciliation, testing, platform, security, and future
  MCP compatibility models without changing implementation code, tests,
  configuration, SQLite schema, MCP tools, or Resolve integration.
- Focus-corrected the architecture after senior review: `config/assets.yaml` is
  now the desired-state declaration and explicit reconciliation input;
  `AssetManager` is the sole public V1 service; `AssetRepository` is the
  persistence boundary; direct public registration and reactivation are
  deferred; lifecycle, availability, and verification invariants are explicit;
  declared paths are root-relative to `config.paths.assets_path`; service-owned
  transaction scope is documented; ordinary missing/non-file verification
  outcomes are results rather than exceptions; and implementation remains
  pending final senior re-review.

## Unreleased - Episode Manifest Implementation

- Implemented `redline_core.manifest`, the Episode Manifest V1 internal API:
  `load_manifest(...)`, `validate_manifest(...)`, `EpisodeManifest`,
  `ValidatedEpisodePlan`, and typed manifest exceptions.
- Added safe YAML loading with one-document enforcement, UTF-8 reads, top-level
  mapping enforcement, safe construction, non-string mapping-key rejection, and
  duplicate mapping-key rejection at every nested level without mutating PyYAML
  global constructors.
- Added strict Pydantic V2 manifest schema models for `schema_version: 1`,
  `episode.id`, `assembly.bin_name`, object-shaped `assembly.media[].path`, and
  manifest marker fields limited to `frame`, `color`, `name`, and `note`.
- Added manifest domain and filesystem validation: manifest-relative path
  resolution, active `ingest_path` / `assets_path` approved-root containment,
  component-aware path checks, duplicate resolved media-path detection, missing
  file and directory rejection, and UNC/network handling through the same
  approved-root policy.
- Added immutable `ValidatedEpisodePlan` translation into the existing
  `EpisodeBuildDefinition` contract. The plan stores immutable manifest-owned
  marker values and creates fresh existing `MarkerDefinition` objects during
  translation without changing `EpisodeManager`, `MediaManager`,
  `TimelineBuilder`, SQLite, MCP tools, or Resolve adapter code.
- Documented and tested that YAML merge keys (`<<`) are intentionally
  unsupported in Episode Manifest V1.
- Added focused manifest unit and temporary-filesystem integration tests for the
  pure manifest layer, which still must not interact with Resolve.
- Live-verified Episode Manifest V1 on 2026-07-27 against DaVinci Resolve
  Studio 21.0.3.7 with Python 3.11.9: a controlled `RLC-E909` YAML manifest
  loaded, validated, translated into `EpisodeBuildDefinition`, and executed
  through `EpisodeManager.build_episode(...)` using a disposable
  `RLC-E909_MASTER` project duplicated from the approved
  `redline-os-test-duplicate` test project. The run imported two expendable
  media files, applied two manifest markers at frames 0 and 48, placed two
  timeline items, preserved manifest media and marker order, and updated only a
  temporary verification SQLite database.
- The live manifest verification removed the disposable Resolve project and
  temporary manifest/media/database artifacts afterward. The configured
  `RLC_MASTER_TEMPLATE` project was not present in the active Resolve project
  folder, so the documented disposable test project was used as the approved
  template source for this controlled run. No production project or production
  media was modified.
- During manifest live verification, Resolve represented the created
  `RLC-E909_TIMELINE` timeline as a Media Pool item in the target bin. This
  matches the known V1 Episode Assembly behavior and was not treated as an
  unexpected media import.

## Unreleased - Episode Manifest Architecture

- Added the Phase 2 Episode Manifest V1 architecture design package:
  `docs/EPISODE_MANIFEST_ARCHITECTURE.md`,
  `docs/EPISODE_MANIFEST_SCHEMA.md`,
  `docs/EPISODE_MANIFEST_LIFECYCLE.md`, and
  `docs/EPISODE_MANIFEST_VALIDATION.md`.
- Documented the approved YAML-only V1 manifest scope: an explicit existing
  episode ID, ordered media paths, optional bin name, and optional marker
  overrides that translate into `EpisodeBuildDefinition` without making
  `EpisodeManager` parse manifests.
- Documented V1 validation boundaries: manifest parsing and pure validation are
  read-only, make no SQLite mutations, and perform no Resolve interaction.
- Hardened the design package after senior review: approved roots are locked to
  the active loaded `ingest_path` and `assets_path`, duplicate YAML keys must be
  rejected, path containment must use resolved path-aware comparisons, and
  validated plans are documented as deterministic intent rather than guaranteed
  historical reproducibility.
- Explicitly deferred JSON support, schema migrations, manifest persistence,
  build history, rollback, MCP manifest tools, render/archive sections, asset
  roles, creative policy, and advanced timeline placement concepts.

## Unreleased - Episode Assembly

- Added V1 Episode Assembly orchestration through `EpisodeManager.build_episode()`, operating on an existing episode record and delegating media import to `MediaManager` plus timeline creation, marker insertion, and clip placement to `TimelineBuilder`.
- Added `EpisodeBuildDefinition` and `EpisodeBuildResult` for the internal Python assembly API; generated media IDs and TimelineItem IDs are returned in order but are not persisted to SQLite.
- Added stage-aware `EpisodeBuildError` with failed stage, episode ID, completed stages, project/timeline names when known, progress counts, and preserved lower-level causes.
- Added `MediaManager.import_media()` for explicit ordered media path imports while preserving existing ingest-scanning `organize_bins()` behavior.
- Added rerun protection: successfully assembled episodes are marked `assembled` and a second assembly attempt is rejected before media import; failed episodes are not automatically retried because Resolve may already have been mutated.
- Hardened assembly status failures: original stage failures remain primary if marking `failed` also fails, and an `assembled` status-update failure now raises a stage-aware `EpisodeBuildError` instead of returning success or leaking a raw DB exception.
- Documented V1 live-verification limits for Episode Assembly: stale-status rerun protection is in-process only, concurrent/cross-process builds are not protected, and `timeline_id` must not be treated as a stable Resolve UUID yet.
- Added unit coverage for assembly validation, manager call ordering, ordered ID propagation, stage failure boundaries, result validation, partial-state logging, status behavior, and shared application-context dependencies.
- Verified V1 Episode Assembly against Resolve Studio 21.0.3.7 and Python 3.11.9 using the disposable `redline-os-test-duplicate` project with one deterministic WAV and one deterministic PNG: media import, timeline creation, two markers, sequential placement, SQLite `assembled` status update, assembled rerun rejection, and validation failure without mutation all passed.
- Live verification observed that Resolve may represent a newly created timeline as a Media Pool item in the currently active target bin when the project is not using a dedicated Timelines bin. This is accepted Resolve behavior for V1, not an extra media import or assembly failure; Redline OS does not change the project-level "Use Timelines Bin" setting or relocate timelines.
- Remaining V1 limitations: linked video/audio cardinality is unverified, rollback is not implemented, cross-process concurrency protection is not implemented, and the stale-status restart limitation remains.

## Unreleased — Phase 1 (real Resolve connection)

- **Milestone: `ResolveScriptAdapter.connect()` verified against a real, running DaVinci Resolve Studio 21.0.3 instance** (licensed/activated Studio edition, not the free edition). This was the one thing blocked since Phase 0 — it is now unblocked.
- `ResolveScriptAdapter.import_media()` now has a first production implementation: connected-state guard, local path validation, project loading, top-level media pool bin reuse/creation, one-shot `MediaStorage.AddItemListToMediaPool(...)` import, strict partial-import detection, and media item ID extraction via `GetMediaId()` with `GetUniqueId()` fallback.
- Verified `ResolveScriptAdapter.import_media()` against a live DaVinci Resolve Studio project: created a top-level media pool bin, imported one PNG, received a real non-empty `GetMediaId()` value, and confirmed the returned ID matched the item found during live Media Pool inspection.
- Added `MediaImportError` under the Resolve exception hierarchy for import validation, bin setup, Resolve import, and ID extraction failures.
- Added focused unit coverage for the real adapter import path using fake Resolve API objects; no running Resolve instance is required for these tests.
- Current limitation: partial Resolve imports and media-pool current-folder changes are reported as failures but not automatically rolled back yet; cleanup behavior is deferred until it is validated against a live project.
- `ResolveScriptAdapter.build_timeline()` and `.add_markers()` now have first production implementations covered by fake Resolve API unit tests. Existing timelines are reused by exact name; Resolve auto-renaming is rejected; marker validation happens before any Resolve modification; partial marker insertion is reported but not automatically rolled back.
- Added `TimelineOperationError` under the Resolve exception hierarchy for timeline lookup, creation, marker validation, and marker insertion failures.
- Current limitation: created timelines may remain after post-create verification failure, and markers may remain after partial insertion failure; automatic rollback is deferred until deletion/cleanup behavior is validated against live Resolve.
- Verified `ResolveScriptAdapter.build_timeline()` and `.add_markers()` against a live DaVinci Resolve Studio project: created an empty timeline, returned the exact requested timeline name, reused the existing timeline on a repeated call without creating a duplicate, added two markers at frames 0 and 48, and confirmed marker `customData` round-tripped through `Timeline.GetMarkers()`. Resolve created its normal default empty video and audio tracks; no clips were added.
- `ResolveScriptAdapter.place_clips()` now has a first production implementation for Version 1 sequential timeline placement: validates requested clip IDs, rejects duplicate requests, resolves imported Media Pool items recursively by `GetMediaId()` with `GetUniqueId()` fallback, sets the exact-name timeline current, appends the resolved clips in requested order with `MediaPool.AppendToTimeline([...])`, and returns TimelineItem `GetUniqueId()` values.
- Added `MockResolveAdapter.place_clips()` and `TimelineBuilder.place_clips()` so the public adapter contract is available in unit tests and higher-level timeline orchestration without automatically changing episode assembly.
- Hardened V1 placement before live testing: `clip_ids` must be a real list, recursive Media Pool traversal is protected against repeated folder handles/cycles by object identity, placement-time ID fallback now matches import behavior, duplicate TimelineItem IDs are rejected, AppendToTimeline exceptions preserve their cause, and the mock now supports multiple exact-name timelines per project.
- Verified `ResolveScriptAdapter.place_clips()` against a live DaVinci Resolve Studio project using a newly created disposable timeline: one audio-only WAV and one PNG still were placed in requested order, `AppendToTimeline([...])` returned one TimelineItem per requested MediaPoolItem, returned TimelineItem IDs were real non-empty `GetUniqueId()` values, and the physical timeline contained one audio item and one video item on the expected track types.
- Current limitation: partial Resolve placement and current-timeline changes are reported but not automatically rolled back.
- Current follow-up: linked video/audio cardinality still needs live verification; if one source MediaPoolItem can produce multiple returned linked TimelineItems, the strict Version 1 count invariant may need adjustment.
- Root-caused and fixed a hard crash encountered along the way: launching the connection test under Python 3.13 caused an access violation (`0xC0000005`) when `DaVinciResolveScript` loads Resolve's native `fusionscript` module. Resolve's scripting DLL isn't built for the 3.13 ABI. Switching to Python 3.11 (already installed at `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`) fixed it immediately — this is not a bug in our code, it's an environment/Python-version requirement, now documented in `README.md`'s Requirements section.
- Verified `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` env vars (set via `scripts/setup_env.ps1`, dot-sourced) resolve correctly against the real install locations on this machine.
- **Still open, same file (`src/redline_core/resolve/adapter.py`):** `queue_render`, `get_render_status`, and `cancel_render` still raise `NotImplementedError`.

## Unreleased — Phase 6/7

- DB: `get_episode_by_episode_id()`, full `render_jobs` CRUD (`create_render_job`, `get_render_job_by_id`, `list_render_jobs_for_episode`, `update_render_job`), full `archives` CRUD (`create_archive_record`, `get_archive_by_episode_id`, `list_archives`). New `ArchiveRecord` model.
- `ResolveAdapter` interface gained `cancel_render()` — implemented in `MockResolveAdapter` (raises if the job doesn't exist or is already in a terminal state), blocked in `ResolveScriptAdapter` same as everything else pending Studio.
- `redline_core.render.manager.RenderManager`: `queue_render()` (async — returns a job ID immediately), `get_render_status()` (polls Resolve and syncs the DB row; bumps the episode to `rendered` on completion), `cancel_render()`, `list_render_jobs_for_episode()`.
- `redline_core.archive.manager.ArchiveManager`: `archive_episode()` (moves the working folder to `paths.archive_path`, records it, marks the episode `archived`; deliberately doesn't gate on render status — see `docs/ARCHITECTURE.md` §9 on keeping business rules minimal), `list_archives()`.
- 20 new tests (`test_render_manager.py`, `test_archive_manager.py`, `cancel_render` cases in `test_resolve_mock.py`) — 69 total.
- MCP: 6 new tools across `render_tools.py` / `archive_tools.py` (`queue_render`, `get_render_status`, `cancel_render`, `list_render_jobs_for_episode`, `archive_episode`, `list_archives`) — **15 tools total**, the complete pipeline from the original architecture doc.
- Re-verified against the real `mcp` package: all 15 tools list correctly, and a real `call_tool('queue_render', ...)` round-trip works after `create_episode`.
- **This closes out the roadmap in `docs/ARCHITECTURE.md` §6** — every manager (Episode/Asset/Media/Timeline/Render/Archive) is built and tested against the mock. The only remaining gap is real Resolve Studio integration beyond `connect()` (Phase 1), blocked on a Studio license.

## Unreleased — Phase 5

- `src/mcp_server`: real MCP server built on the official `mcp` package's `FastMCP`. `context.py` (`AppContext` / `build_context()`) constructs one Config, one DB connection, one Resolve adapter, and all four managers exactly once at startup.
- 9 tools across 4 modules (`tools/episode_tools.py`, `asset_tools.py`, `media_tools.py`, `timeline_tools.py`): `create_episode`, `get_episode_status`, `list_episodes`, `list_available_assets`, `verify_assets_for_episode`, `scan_ingest_for_episode`, `organize_bins`, `build_timeline`, `add_markers`. Full reference in `docs/MCP_TOOLS.md`.
- Every tool's actual logic lives in an underscore-prefixed function with **no dependency on the `mcp` package** — `register()` is the only place that touches FastMCP. This means `tests/unit/test_mcp_tools.py` (11 new tests, 45 total) runs without the optional `[mcp]` extra installed, same as the rest of CI.
- `server.py` entrypoint (`python -m mcp_server.server`) with a `--mock-resolve` flag, so the whole tool surface can be tried today, before Studio is installed. New `[project.scripts]` entry point: `redline-mcp`.
- **Verified for real, not just logic-tested:** installed the `mcp` package and confirmed the actual `FastMCP` server builds, lists all 9 tools with correct schemas, and executes real `call_tool()` round-trips (`create_episode`, `list_episodes`, `verify_assets_for_episode`) — the "Create Episode 025" scenario from `docs/ARCHITECTURE.md` §4 now genuinely works end-to-end against the mock.
- Render/Archive tools intentionally not included — those managers don't exist until Phase 6/7.

## Unreleased — Phase 4

- New config: `MarkerDefinition` / `TimelineTemplateConfig` (`config/timeline_template.yaml`) — timeline naming pattern + the standard marker set (frame/color/name/note) per the Broadcast Package V1.0 spec. Data-driven, not hardcoded.
- `redline_core.timeline.builder.TimelineBuilder`: `build_timeline_for_episode()` (builds the timeline + applies the default marker set, returns a `TimelineBuildResult`), `apply_markers()` (also usable standalone, with an optional marker-set override for special episodes).
- Scope note: Timeline Builder does not duplicate the project (Episode Manager's job) or import media (Media Manager's job) — it only calls `ResolveAdapter.build_timeline()` / `.add_markers()`.
- 4 new tests (`test_timeline_builder.py`) — 34 total, all against `MockResolveAdapter`.
- `ResolveScriptAdapter.build_timeline()` / `.add_markers()` comments updated to reflect they were blocked on a real Studio license, same as the other adapter methods.

## Unreleased — Phase 3

- New config: `AssetDefinition` / `AssetsConfig` (`config/assets.yaml`), `assets_path` added to `PathsConfig` (`config/paths.yaml`). Asset IDs remain sourced from the Universe project — this only records where the approved file lives on disk.
- `redline_core.asset.manager.AssetManager`: `list_available_assets()`, `verify_assets_for_episode()` (non-raising, returns found/missing), `ensure_assets_for_episode()` (raises `MissingAssetsError` if anything's missing).
- `redline_core.media.manager.MediaManager`: `scan_ingest_for_episode()` (filename-convention matching against `ingest_path`), `organize_bins()` (imports matches into the Resolve media pool via `ResolveAdapter.import_media()`).
- 11 new tests (`test_asset_manager.py`, `test_media_manager.py`), all against temp folders + `MockResolveAdapter` — 30 total, no Resolve/Studio required.
- `ResolveScriptAdapter.duplicate_project()` / `.import_media()` comments updated to reflect they're blocked on a real Studio license, not unbuilt logic — the business logic above is fully built and tested against the mock.

## Unreleased — Phase 2

- `redline_core.episode.manager.EpisodeManager`: `create_episode()`, `get_episode_status()`, `list_episodes()`. Orchestrates naming (from config) → DB row → working folder → duplicated Resolve project, in that order, so a partially-failed create still leaves a trackable DB row.
- `redline_core.db.database.Database.update_episode_paths()`: updates `project_path`/`folder_path` independently, added to support the above.
- `redline_core.episode.exceptions`: `EpisodeAlreadyExistsError`, `EpisodeNotFoundError`.
- Tests (`tests/unit/test_episode_manager.py`) covering create, duplicate-create conflict, status lookup (found/not found), and ordering — all against `MockResolveAdapter`, no Resolve/Studio required.
- **Blocked, not skipped:** real Resolve Studio integration (Phase 1 — `duplicate_project()` implemented for real, verified against a live instance) is paused because the workstation currently only has the free edition of Resolve 21. Everything above still works fully against the mock in the meantime.

## Unreleased — Phase 0

- Initial repo scaffold (`src/redline_core`, `src/mcp_server`, `tests/`, `docs/`, `config/`, `scripts/`).
- `redline_core.config`: pydantic schema (`NamingConfig`, `FolderStructureConfig`, `RenderPresetsConfig`, `PathsConfig`) + YAML loader with example config files.
- `redline_core.db`: SQLite schema (`episodes`, `render_jobs`, `archives`) + thin `Database` wrapper with basic episode CRUD.
- `redline_core.logging`: rotating-file + console logging setup, episode-correlated logger adapter.
- `redline_core.resolve`: `ResolveAdapter` interface, `ResolveScriptAdapter` (real, connection-only so far), `MockResolveAdapter` (fully implemented, used by all unit tests).
- Unit test suite (`tests/unit`) covering config, DB, and the mock Resolve adapter — runs in CI with no Resolve dependency.
- CI skeleton (`.github/workflows/ci.yml`) running `pytest tests/unit` on every push/PR.

**Not yet built:** Episode/Asset/Media/Timeline/Render/Archive managers, the MCP server, and any code path that talks to a *real* running Resolve instance beyond `connect()`. See `docs/ARCHITECTURE.md` §6 for the roadmap.
