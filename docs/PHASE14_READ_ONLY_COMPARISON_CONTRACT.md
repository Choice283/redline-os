# Phase 14 Read-Only Project/Timeline Comparison Contract

Status: **Construction and static review only** (this document describes the
published Phase 14 commit `7e37d5f01249cc2b97714b0266a8c3caca1fabc3`; see
`docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md` for the unstaged Phase 14.1
live-execution-capable revision layered on top of it)
Mission: **Phase 14 — Dual Project/Timeline Read-Only Snapshot Probe Construction and Static Review**
Founder authorization: Paul Jones, August 4, 2026
Canonical repository checkpoint: `d9ebe5947ba8e5fa77e765f8db3482fee03d7132`
Canonical commit subject: `docs: record Phase 14 isolation evidence`

## 1. Purpose

Phase 14 has established the following project-by-preset isolation matrix:

| Project context | YouTube - 720p | Redline Broadcast Master |
|---|---:|---:|
| `redline-os-test-duplicate` / `RLO-LIVE-ASM-92701_TIMELINE` | Accepted | Accepted |
| `RLC-E9001_MASTER` / `RLC-E9001_TIMELINE` | Rejected | Rejected |

The matrix rules out either tested preset being universally incapable of queue
acceptance. It does not identify a project- or timeline-level cause.

This contract defines the smallest fail-closed system for collecting two
read-only Resolve context snapshots and comparing them offline. It does not
claim corruption, repairability, render eligibility, or causation.

## 2. Current authorization boundary

The authorized construction mission permits only:

- architecture documentation;
- source drafting;
- mocked unit tests;
- static safety review;
- hash generation.

The construction mission prohibits:

- importing or executing `DaVinciResolveScript` against a live environment;
- calling `scriptapp("Resolve")`;
- contacting DaVinci Resolve;
- inspecting live projects, timelines, media pools, render settings, or queues;
- loading or switching projects;
- switching timelines;
- loading presets;
- setting render settings;
- adding, deleting, starting, stopping, or cancelling render jobs;
- accessing or modifying SQLite;
- committing or publishing repository changes.

**Historical note — describes the published Phase 14 commit `7e37d5f`
only, not the current unstaged source.** That commit's source enforced this
boundary with:

```python
SNAPSHOT_EXECUTION_ENABLED = False
```

and its `snapshot` CLI stopped before the connection function while that
constant was false. **This constant does not exist in the unstaged Phase
14.1 revision** (rev1 through the current rev6) — it was replaced outright,
not merely bypassed. See §2.1 and §2.2 immediately below for what actually
governs the current source, and `docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md`
for the full revision history.

### 2.1 Phase 14.1 update (unstaged, not yet authorized for live use)

An unstaged Phase 14.1 revision replaces the flat boolean disable above with
an explicit execution interlock, documented in full in
`docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md` and
`docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md`. Summary:

- `SNAPSHOT_EXECUTION_ENABLED` no longer exists. In its place, the `snapshot`
  CLI requires `--execution-authorization <revision-id>`, checked by
  `enforce_execution_interlock()` before output-path validation, before
  `DaVinciResolveScript` import, before connection, and before any snapshot
  collection.
- The supplied value must exactly equal the immutable `EXECUTION_REVISION_ID`
  constant for this exact source text. Missing, malformed, or mismatched
  values stop with exit code `2` and structured error codes
  `live_execution_authorization_missing`, `live_execution_authorization_invalid`,
  or `live_execution_revision_mismatch`, none of which echo the supplied value.
- This is a deliberate execution interlock, not authentication and not a
  security secret. It exists so an operator cannot reach Resolve by accident;
  it does not resist a determined adversary and must never be described or
  treated as one.
- `compare` and `--print-sha256` are unaffected and never require this
  interlock.
- Remaining fail-closed by default is structural, not a matter of a flag
  being left in the right position: with no `--execution-authorization`
  supplied, or a value that isn't exactly this revision's identifier,
  Resolve is never contacted.
- Enabling live capture with this revision still requires everything this
  document already specifies in §12: a separately reviewed execution
  contract and explicit founder authorization bound to the exact commit,
  source SHA-256, `EXECUTION_REVISION_ID`, contexts, and evidence paths. A
  matching source and identifier are a precondition for that authorization,
  not a substitute for it.

### 2.2 Phase 14.1 rev3 update (historical — superseded by rev4, then rev5, then rev6; not the current source)

`EXECUTION_REVISION_ID` is now `phase14.1-live-interlock-construction-rev3`.
An independent review of rev2 found real defects, all corrected in rev3:

- **The runbook no longer embeds a repository commit inside itself.**
  rev2's `$expectedRepoCommit = "REPLACE_WITH_COMMIT_SHA..."` placeholder
  created an unresolvable cycle: the runbook is part of the commit whose SHA
  it would need to contain, so editing it to insert that SHA changes the
  commit, which changes the SHA, indefinitely. rev3 instead requires an
  external, founder-authorized **authorization manifest** (§14), generated
  only after the commit exists, never embedded in it.
- **The runbook now verifies its own executing bytes** against the
  manifest's `runbook_sha256` (via `$PSCommandPath`) before trusting
  anything else it does — a safety controller that never checks its own
  integrity cannot be trusted to check anything else's.
- **All exact-match comparisons that matter for authorization are now
  case-sensitive** (`-ceq`/`-cne`/`-cnotmatch` in the runbook,
  byte-for-byte string comparison with no normalization in the Python
  interlock), because PowerShell's default `-eq`/`-ne` are case-insensitive
  for strings — `confirm-control-snapshot` must not satisfy a check written
  as `CONFIRM-CONTROL-SNAPSHOT`.
- **`EXECUTION_REVISION_ID_PATTERN` now enforces both endpoints.** rev1/rev2
  required only the *first* character to be alphanumeric; a value ending in
  `.`, `_`, or `-` still passed. rev3's pattern requires both the first and
  last character to be alphanumeric, 2–80 characters total.
- **The Python interpreter is resolved once and reused everywhere**,
  including for version verification (`sys.version_info`, not a second
  `py -3.11 --version` launcher call) and for the execution itself.
- **Resolve's version is matched exactly**, not with a substring-tolerant
  regex — a "contains 21.0.3.7" check would also accept an unexpected
  longer version string.
- **The evidence-directory probe copy is rehashed at every boundary** —
  after copy, after confirmation (alongside the repository copy),
  immediately before process launch, and immediately after process exit —
  against the manifest's `probe_sha256`, to support the claim that the
  evidence package contains exactly the bytes that were executed.
- **`connect_resolve_read_only()` no longer lets import or connection
  exceptions escape as raw tracebacks.** `resolve_module_import_failed` and
  `resolve_scriptapp_call_failed` are new structured codes (§7); the
  pre-existing `resolve_connection_failed` is unchanged (a falsy handle with
  no exception).
- **`execution_validation.json` is now written after every individual
  check**, success or failure, not only once all checks pass — a failed
  capture's evidence directory now records exactly which checks passed,
  which one failed, and which never ran, instead of an empty or missing
  validation file.
- **A process that fails to start is itself a recorded, structured
  outcome** (`processStarted: false` in `execution_record.json`), not an
  uncaught exception.
- **Evidence hashing is now complete**: the copied probe, the copied
  runbook, the copied contract, and the copied authorization manifest are
  each hashed after copying and required to match their verified source —
  previously only the probe copy was rehashed this way.

### 2.3 Phase 14.1 rev4 update (historical — staged for review, then rejected; not the current source)

**Rev4 was constructed and staged for a staged-diff review. The staged
candidate was rejected for commit consideration. No commit or publication
occurred. Rev4 was superseded by rev5 corrections (§2.4).** The rejection
findings and their rev5 resolutions are listed in §2.4; the description
below is preserved as an accurate historical record of what rev4 itself
introduced relative to rev3.

`EXECUTION_REVISION_ID` is now `phase14.1-live-interlock-construction-rev4`.
A third independent review conditionally accepted the rev3 Python probe and
writer but found the manifest parser and runbook still incomplete. Fixed:

- **A real non-contact preflight mode.** `-PreflightOnly` performs every
  check up to, but never including, the typed confirmation and the
  Resolve-contacting process launch: manifest validation, self-hash
  binding, repository/remote/commit/artifact hashes, the exact Python
  interpreter, Resolve's version and required environment configuration,
  and a full preflight evidence copy-and-package. No `Read-Host` call and
  no snapshot launch exist anywhere on that code path. It exits `0` only
  when every preflight check passed, and explicitly reports `Resolve
  contact: false`, `Snapshot execution: false`, `Preflight complete: true`.
  A normal (non-preflight) invocation still requires the exact
  case-sensitive typed confirmation, unchanged.
- **Duplicate-key-safe, exact-schema manifest validation moved into the
  probe itself.** `validate_authorization_manifest_bytes()` (new) uses
  `json.loads(..., object_pairs_hook=...)` to reject any duplicate object
  key at any depth — Windows PowerShell 5.1's `ConvertFrom-Json` silently
  resolves duplicate keys to the last value with no warning, so it is never
  used to parse the manifest itself, only the validator's own
  guaranteed-duplicate-free output. The same function requires the root to
  be one JSON object with exactly the twelve required top-level fields (no
  more, no fewer), `schema_version` to be the literal integer `1` (a JSON
  boolean is explicitly rejected even though Python's `bool` is an `int`
  subclass), every string-typed field to actually be a JSON string, and
  `contexts` to contain exactly `Control`/`Production`, each with exactly
  `project`/`timeline`. A new `validate-manifest` CLI subcommand exposes
  this over stdin so the proposed runbook invokes the identical,
  independently unit-tested implementation rather than a second,
  unverified copy of the same logic.
- **Single-byte-read binding.** The runbook reads the manifest as raw bytes
  exactly once; those same bytes are hashed, strict-UTF-8-decoded, piped to
  the validator's stdin, and later written verbatim into the evidence
  copy — never a second read of the source path, never a re-serialization
  standing in for the original bytes.
- **Exception-safe validation.** Every recorded check now runs inside a
  shared helper that catches an exception raised while *evaluating* the
  check itself — not just a false result — records it, and persists
  `execution_validation.json` before propagating. A top-level guard active
  from the moment the evidence directory exists writes
  `runbook_failure.json` for any otherwise-unclassified terminating
  exception before the script exits nonzero.
- **Working-directory independence.** Every local Git command is rooted
  with `git -C $repo`; the repository root is itself re-verified via
  `git -C $repo rev-parse --show-toplevel` against the canonical path.
- **Reparse-point guarding.** A reusable ordinary-file check (exists, is a
  file, is not a directory, does not carry `FileAttributes.ReparsePoint`)
  is applied to the manifest, the runbook's own executing path, the
  canonical repository runbook copy, the repository probe/test/contract
  files, the resolved Python executable, `Resolve.exe`, and every copied
  evidence artifact; the freshly created evidence directory is checked the
  same way.
- **Documentation corrections**: this contract's §14 subsections (formerly
  mis-numbered §15.1–§15.3 under a section already renamed to §14) and
  `docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md`'s rev2/rev3 history entries
  (both previously labeled "this revision" after being superseded) are
  both fixed as part of this same revision.

### 2.4 Phase 14.1 rev5 update (historical — staged for review, then rejected; superseded by rev6; not the current source)

**Rev5 was constructed and staged for a second, independent staged-diff
review. The staged candidate was rejected for commit consideration. No
commit or publication occurred. Rev5 was superseded by rev6 corrections
(§2.5).** The rejection findings and their rev6 resolutions are listed in
§2.5; the description below is preserved as an accurate historical record
of what rev5 itself introduced relative to rev4.

`EXECUTION_REVISION_ID` is now `phase14.1-live-interlock-construction-rev5`.
Rev4 was constructed and staged for a staged-diff review; the staged
candidate was rejected for commit consideration (no commit or publication
occurred) after that review found three Important and two Minor findings,
all fixed in rev5:

- **Repository-root validation ordering.** `Assert-RepoCheckpoint` used to
  pass `git -C $repo rev-parse --show-toplevel`'s output straight into
  `Resolve-Path` before checking `$LASTEXITCODE`; a failed Git call meant
  `Resolve-Path` threw its own confusing exception on empty/garbage input
  before the intended "STOP: unable to resolve repository root" message
  could ever run. Every Git-output-consuming step in that function now
  captures the exit code first, checks it before touching the output at
  all, and raises a stable, static message that does not depend on what
  Git printed.
- **Six real, individually reachable probe-hash checkpoints**, replacing
  a mix of one early general check and a pair of bare, duplicate
  post-confirmation checks: `repository_probe_hash_pre_copy`,
  `evidence_probe_hash_post_copy`, `repository_probe_hash_pre_confirmation`,
  `evidence_probe_hash_pre_confirmation`, `repository_probe_hash_pre_launch`,
  `evidence_probe_hash_pre_launch`. Every one of them runs through
  `Invoke-ValidationCheck` — no bare post-confirmation hash `if (...) {
  throw ... }` remains. `-PreflightOnly` attempts the pre-copy, post-copy,
  and pre-confirmation checkpoints and leaves the two pre-launch
  checkpoints `not_run`, because that branch returns before either could be
  reached. The pre-confirmation and pre-launch pairs are genuinely distinct
  checkpoints, separated by the typed confirmation itself — not, as in
  rev4, the same check run twice back to back with no intervening state
  change.
- **Original exception identity is preserved.** `Invoke-ValidationCheck`'s
  catch block records the failure code and the real exception's
  `GetType().FullName`, persists `execution_validation.json`, and then
  re-raises with a bare `throw` rather than `throw "STOP: ..."`. A bare
  `throw` inside a `catch` re-raises the exact exception object currently
  being handled, so `runbook_failure.json` (written by the outer handler)
  now reports the same real exception type instead of a wrapping
  `RuntimeException` manufactured from a string.
- **Documentation precision.** No document claims a check happens
  "immediately before" a given step unless the code is actually placed
  immediately before it; the six-checkpoint description above states
  exactly what sits between each checkpoint and the step it guards.

### 2.5 Phase 14.1 rev6 update (current; unstaged; not yet authorized for live use)

`EXECUTION_REVISION_ID` is now `phase14.1-live-interlock-construction-rev6`.
Rev5 was constructed and staged for a second, independent staged-diff
review; the staged candidate was rejected for commit consideration (no
commit or publication occurred) after that review found one Important and
one Minor finding, both documentation-only, both fixed in rev6:

- **Stale test count corrected.** §10 below said "46 tests total ... as of
  Phase 14.1 rev2" with no historical marking, even though this document
  had by then been revised through rev5 and the actual count had grown to
  70 three revisions earlier (46 = 21 unchanged + 2 updated + 13 rev1-new +
  10 rev2-new; the missing 8 rev3-new and 16 rev4-new tests brought the
  total to 70 — see `docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md` §6 for the
  full, current inventory). §10 now states 70 as the current, verified
  count and retains 46 only as clearly labeled Rev2-era historical
  information.
- **Checkpoint-comment precision corrected.** Two of the six probe-hash
  checkpoint comments (checkpoints 1 and 2, in both
  `scripts/phase14_live_snapshot_runbook.ps1` and
  `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §9) claimed "no other operation
  sits between" a check and its guarded step, when a non-mutating
  path-construction line (checkpoint 1) or an `Assert-OrdinaryFile` guard
  call (checkpoint 2) actually sat between them. Neither intervening
  operation can modify or replace the hashed file, so this was a
  documentation-precision gap, not a correctness gap — but it is exactly
  the class of overclaim rev5's own "Documentation precision" item existed
  to prevent, and rev5's staged-diff review found it had not fully closed
  that gap. Both comments now state precisely what they can guarantee: no
  operation *capable of modifying or replacing the hashed probe* sits
  between the check and its guarded step. The non-mutating operations
  themselves were left in place, unrearranged.

## 3. Deliverable layout

The construction review bundle contains:

```text
scripts/phase14_resolve_context_snapshot.py
tests/unit/test_phase14_resolve_context_snapshot.py
docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md
docs/PHASE14_STATIC_REVIEW_REPORT.md
construction_manifest.json
```

This list describes the external construction-review bundle assembled during
review, not a manifest of files required to exist in the canonical
repository. Not every bundle artifact was required to be committed here:
`docs/PHASE14_STATIC_REVIEW_REPORT.md` and `construction_manifest.json` were
review-time artifacts of that external bundle and are not present in this
repository; their absence does not indicate the published Phase 14 commit
(`7e37d5f01249cc2b97714b0266a8c3caca1fabc3`) was incomplete. The canonical
repository contains the integrated probe, its tests, and this contract. Any
future execution-enablement review artifact (see
`docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md`) has an explicitly documented
storage and publication policy stated in that document rather than being
assumed.

No production adapter interface is changed. The probe is intentionally isolated
from `src/redline_core` because it is an evidence-gathering mission artifact,
not an approved production capability.

## 4. Architecture

### 4.1 Two-stage evidence flow

```text
Operator-prepositioned Resolve context
                |
                v
Single-context snapshot collector
                |
       +--------+--------+
       |                 |
       v                 v
control.json       production.json
       |                 |
       +--------+--------+
                |
                v
Pure offline comparator
                |
                v
comparison.json
```

The collector handles one already-open project and one already-current timeline
per invocation. It never loads or switches project/timeline state.

The comparator reads two JSON documents and never imports or contacts Resolve.

### 4.2 Why one snapshot per invocation

The Resolve scripting API exposes full project/timeline detail primarily for
the current project. Automatically loading the second project would mutate the
active Resolve context and violate this mission's read-only boundary.

Therefore, a future authorized operator must manually pre-position Resolve
before each snapshot:

1. Control context:
   - Project: `redline-os-test-duplicate`
   - Timeline: `RLO-LIVE-ASM-92701_TIMELINE`
2. Production-like context:
   - Project: `RLC-E9001_MASTER`
   - Timeline: `RLC-E9001_TIMELINE`

Manual pre-positioning is not authorized by this construction mission. It is a
future execution-contract requirement.

## 5. Snapshot evidence contract

### 5.1 Required root fields

A complete snapshot contains:

```json
{
  "schema_version": "1.0",
  "mission": "Phase 14 — Dual Project/Timeline Read-Only Snapshot Probe",
  "captured_at": "UTC timestamp",
  "snapshot_complete": true,
  "expected_context": {},
  "session": {},
  "project_manager": {},
  "project": {},
  "target_timeline": {},
  "media_pool": {},
  "pre_guard": {},
  "post_guard": {},
  "ambiguity_policy": {}
}
```

Missing required sections or `snapshot_complete != true` make a comparison
invalid.

### 5.2 Optional observation envelope

Optional API values use this envelope:

```json
{
  "source_method": "GetSetting",
  "status": "observed",
  "value_type": "dict",
  "value": {},
  "error": null
}
```

Allowed statuses:

- `observed`
- `unavailable`
- `error`

An arbitrary Resolve bridge object is never converted with `repr()` or `str()`.
Unsupported values become structured errors.

### 5.3 Session controls

The collector records:

- product name;
- version tuple/list, when available;
- version string, when available.

At least one usable version representation is required. Session identity is
captured again after collection; any change fails closed.

The offline comparator refuses comparison when the two snapshots do not expose
the same Resolve version identity.

### 5.4 Project-manager metadata

Optional read-only observations:

- project list in the current project-manager folder;
- project attributes in the current project-manager folder.

These fields may expose project record dates, notes, collaboration flags, or
other version-dependent attributes. They are evidence only and cannot prove a
cause.

### 5.5 Project evidence

The collector records:

- exact current project name;
- project settings dictionary, when available;
- complete timeline count and timeline inventory;
- exact-name duplicate detection;
- render preset name inventory, when available;
- sanitized render queue inventory;
- current render format/codec, mode, and settings, when available.

Current render context is marked context-sensitive. It may reflect prior Deliver
page or preset activity and is not treated as intrinsic project identity.

### 5.6 Timeline evidence

The target timeline records:

- exact name;
- unique ID, when available;
- start and end frame, when available;
- start timecode, when available;
- timeline settings, when available;
- marker dictionary, when available;
- complete required video/audio track counts;
- optional subtitle track count;
- complete item inventory for every observed track.

A required track count or item collection that is malformed or incomplete stops
the snapshot.

### 5.7 Timeline-item evidence

Each timeline item records:

- track type and one-based track index;
- zero-based item index in the returned collection;
- item name;
- unique ID;
- start, end, and duration;
- left/right offsets;
- source start/end frame;
- enabled state;
- associated media-pool item metadata.

Optional accessors may be unavailable on a specific Resolve version or item
type. Unavailability is recorded without inventing a value.

### 5.8 Media-pool evidence

The media-pool hierarchy records:

- folder name and full hierarchy path;
- clips in each folder;
- complete subfolder traversal;
- clip name;
- media ID and unique ID, when available;
- complete clip property dictionary, when available.

If a folder name is missing or non-string, the deterministic sentinel is used:

```text
<folder-name-unavailable>
```

Repeated or cyclic folder handles fail closed and report both the first and
repeated hierarchy paths.

### 5.9 Guard evidence

The pre- and post-collection guards contain:

- project name;
- timeline count;
- current timeline name;
- target timeline name;
- literal rendering-in-progress boolean;
- queue count;
- sanitized queue fingerprint.

Collection is allowed only when:

- project name exactly matches the expected value;
- current and target timeline names exactly match the expected value;
- rendering is literally `False`;
- render queue count is zero.

Any pre/post difference fails as snapshot identity drift.

### 5.10 Output atomicity and no-overwrite contract (Phase 14.1, corrected in rev2)

Both `snapshot` and `compare` write output through `write_json_no_overwrite()`:

1. The complete JSON document is serialized in memory (`json.dumps`) and
   round-tripped through `json.loads` to validate completeness before any
   disk write occurs.
2. `validate_output_path()` rejects an already-existing output path (file or
   directory) and rejects a missing parent directory, all before Resolve is
   contacted for `snapshot`. This probe never creates a directory on the
   caller's behalf.
3. The validated JSON text is written to an OS-backed, exclusively created
   temporary file (`tempfile.mkstemp()`, prefixed `.{name}.tmp-`) in the same
   destination directory as the final path, guaranteeing both paths share a
   filesystem. **Rev1 used a hand-rolled UUID name with a plain `open(...,
   "w")`, which could not guarantee exclusive creation; rev2 replaced it with
   `mkstemp()`'s OS-level exclusive-create semantics.** The written file is
   flushed and `fsync`'d before publication is attempted.
4. Publication is a create-only `os.link()` from the temp file to the final
   path. Unlike a plain rename, `os.link()` raises `FileExistsError` if the
   destination exists, on both Windows and POSIX, so a race after the
   pre-flight check still cannot silently replace existing evidence — the
   race is reported as `output_path_already_exists` and the raced-in
   destination is left untouched.
5. Temp-file removal is **attempted** after every write attempt, success or
   failure. This is not an unconditional guarantee: if the OS-level removal
   itself fails, that failure is never silently swallowed — it is raised as
   its own `output_temp_cleanup_failed` error (§7), whose details record
   whether publication had already succeeded. If publication had already
   succeeded when cleanup failed, the completed final output is left intact
   and the run is **not** reported as successful; nothing deletes a
   completed output to "fix" a cleanup failure. Every other output-writing
   failure mode (`output_temp_create_failed`, `output_write_failed`,
   `output_publish_failed`) is structured with a safe `error_type` and a
   `published` boolean, and never includes an authorization value in its
   message or details.

## 6. Closed read-only API surface

Every dynamically dispatched Resolve method must appear in the source's
`READ_ONLY_RESOLVE_METHODS` allowlist.

The allowlist covers only getters used for:

- Resolve product/version identity;
- project-manager/current-project inspection;
- project/timeline enumeration and settings;
- media-pool hierarchy and clip metadata;
- render queue/preset/context inspection;
- timeline track/item metadata.

The source separately defines `PROHIBITED_RESOLVE_METHODS`. Static tests verify
that:

- the allowlist and prohibited set do not overlap;
- no prohibited method is directly called;
- no direct `DaVinciResolveScript` import statement exists.

The connection function contains the module name only as a future dynamic import
target. In the published Phase 14 commit (`7e37d5f`) it was unreachable
because a hard-disable check executed first. **In the unstaged Phase 14.1
revision this is no longer accurate**: there is no hard-disable constant.
The connection function is unreachable instead because
`enforce_execution_interlock()` must pass — an exact, byte-for-byte matching
`--execution-authorization` value — before `run_snapshot_command()` proceeds
to output-path validation or connection. See §2.1 and
`docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md`.

## 7. Fail-closed error classes

Representative snapshot stop codes:

| Code | Meaning |
|---|---|
| `live_execution_disabled` | Construction artifact cannot contact Resolve (pre-14.1 published commit `7e37d5f`). |
| `live_execution_authorization_missing` | Phase 14.1: `--execution-authorization` was not supplied. |
| `live_execution_authorization_invalid` | Phase 14.1: supplied value is not a well-formed revision identifier. |
| `live_execution_revision_mismatch` | Phase 14.1: supplied value does not equal `EXECUTION_REVISION_ID`. |
| `output_path_already_exists` | Phase 14.1: output path already exists, or was created by something else during publication; will not be overwritten. |
| `output_path_is_directory` | Phase 14.1: output path is an existing directory. |
| `output_parent_directory_missing` | Phase 14.1: output parent directory does not exist. |
| `output_temp_create_failed` | Phase 14.1 rev2: the OS-backed exclusive-create temporary file could not be created. |
| `output_write_failed` | Phase 14.1 rev2: writing or fsyncing the temporary file failed; no final output is published. |
| `output_publish_failed` | Phase 14.1 rev2: the create-only publish (`os.link`) failed for a reason other than the destination already existing. |
| `output_temp_cleanup_failed` | Phase 14.1 rev2: the temporary file could not be removed after use; surfaced explicitly rather than swallowed, and distinguishes whether publication had already succeeded. |
| `resolve_module_import_failed` | Phase 14.1 rev3: importing `DaVinciResolveScript` raised (any exception, not just an absent module). |
| `resolve_scriptapp_call_failed` | Phase 14.1 rev3: calling `scriptapp("Resolve")` raised. |
| `project_identity_mismatch` | Current project is not the exact expected project. |
| `expected_timeline_missing` | Expected timeline was not found. |
| `duplicate_expected_timeline` | More than one exact-name timeline matched. |
| `current_timeline_mismatch` | Current timeline differs from the expected target. |
| `invalid_count` | Required count is boolean, negative, or non-integer. |
| `invalid_collection` | Required collection has an invalid outer type. |
| `rendering_active` | Resolve reports an active render. |
| `render_queue_not_empty` | Render queue is not empty. |
| `repeated_media_pool_folder_handle` | Repeated/cyclic hierarchy handle detected. |
| `snapshot_identity_drift` | Guarded state changed during collection. |
| `resolve_session_drift` | Product/version identity changed during collection. |
| `unsupported evidence type` | A bridge handle or unsupported value reached JSON normalization. |

No Resolve-collection failure triggers cleanup, because the collector
performs no authorized live mutation. This does not extend to output
writing: as of Phase 14.1 rev2, a failure during output publication
(`write_json_no_overwrite()`) does attempt temp-file cleanup, and — per
§5.10 — a cleanup failure itself is reported as a distinct, structured
error rather than silently ignored.

## 8. Offline comparison contract

### 8.1 Comparison classifications

Each compared leaf is classified as one of:

- `equal`
- `different`
- `unavailable_on_control`
- `unavailable_on_production`
- `unavailable_on_both`
- `structurally_invalid`
- `context_sensitive`

A version mismatch produces an overall `incomparable` result with no property
records.

### 8.2 Expected identity normalization

The two contexts intentionally have different project and target timeline
names. Before property comparison, these expected names are normalized to:

```text
<expected-project>
<expected-timeline>
```

This prevents known identity labels from being misreported as candidate
root-cause differences. Other timeline names remain unchanged so unexpected
inventory differences stay visible.

### 8.3 Overall outcomes

Possible overall outcomes:

- `incomparable`
- `ambiguous_due_to_structural_errors`
- `differences_observed`
- `no_exposed_intrinsic_difference_observed_with_gaps`
- `no_exposed_intrinsic_difference_observed`

These outcomes describe exposed API evidence only.

### 8.4 Mandatory interpretation limits

Every comparison report states:

1. A difference is a candidate discriminator, not a proven cause.
2. Equality does not rule out hidden Resolve state.
3. Current render context is context-sensitive, not intrinsic identity.
4. A comparison does not authorize repair or a mutating experiment.

## 9. API limitations

This design cannot reliably obtain:

- an explicit read-only answer to whether `AddRenderJob()` would succeed;
- the hidden rejection reason used by Resolve queue acceptance;
- a corruption or project-health flag;
- a repair recommendation;
- a complete settings dictionary for a named preset without loading it;
- a reliable project dirty/unsaved-state flag;
- inactive-project timeline/media details without switching projects;
- UI-only warnings or disabled-control state;
- proof that Resolve can create an output file without a write or queue action;
- internal project/timeline state not exposed through the scripting API.

The probe must not convert these limitations into assumptions.

## 10. Mocked validation matrix

**70 tests total** in `tests/unit/test_phase14_resolve_context_snapshot.py`
as of the current revision (rev6) — see
`docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md` §6 for the full, current
inventory and mapping. (Historical note: the suite held 46 tests as of
Phase 14.1 rev2; 8 more were added in rev3 and 16 more in rev4, for the
current total of 70. Rev5 and rev6 changed no test count, only identifiers
and documentation.) Coverage:

- module import without Resolve import;
- execution interlock: missing authorization stops before connection;
  malformed-format authorization stops before connection; well-formed but
  mismatched authorization stops before connection; leading-whitespace,
  trailing-whitespace, and whitespace-only authorization are each rejected
  as malformed (no `.strip()` normalization); correct authorization reaches
  the mocked connection boundary;
- valid complete mocked snapshot;
- wrong project;
- duplicate exact timeline;
- current timeline mismatch;
- active rendering;
- nonempty queue with sanitized evidence;
- boolean timeline count rejection;
- repeated/cyclic media-pool folder detection;
- pre/post identity drift;
- unsupported bridge object rejection without `repr()`;
- cyclic JSON container rejection;
- optional absent accessor classification;
- queue value sanitization;
- intrinsic vs context-sensitive comparison;
- unavailable-value comparison;
- Resolve version mismatch;
- incomplete snapshot rejection;
- offline compare without Resolve import or execution authorization;
- `--print-sha256` without execution authorization;
- static absence of direct Resolve import and prohibited calls;
- allowlist/prohibited-set disjointness;
- no `sqlite3`/`REDLINE_DB_PATH` text reference;
- hash printing without connection;
- output writer: existing output file/directory rejected before connection;
  existing comparison output not overwritten; serialization failure occurs
  before any disk write (does not by itself prove post-creation cleanup);
  forced temp-name collision and a generic temp-creation failure both
  produce `output_temp_create_failed` without touching the destination; a
  write/fsync failure produces `output_write_failed` and leaves no final
  output; a generic `os.link()` failure produces `output_publish_failed` and
  removes the temp file; a destination-created-during-publication race
  produces `output_path_already_exists` and preserves the raced-in
  destination; a temp-cleanup failure is surfaced as
  `output_temp_cleanup_failed` rather than swallowed, and preserves an
  already-published final output; a successful write leaves exactly one
  final JSON file; `main()` returns exit code `2` with a structured error
  for a controlled output-write failure rather than an uncaught traceback;
- authorization values are never present in snapshot evidence or in
  structured error output.

## 11. Safe construction-time commands

The following commands do not contact Resolve:

```powershell
python -m py_compile `
  scripts\phase14_resolve_context_snapshot.py `
  tests\unit\test_phase14_resolve_context_snapshot.py

pytest -q tests\unit\test_phase14_resolve_context_snapshot.py

python scripts\phase14_resolve_context_snapshot.py --print-sha256
```

Offline comparison is safe only when it reads previously reviewed JSON files:

```powershell
python scripts\phase14_resolve_context_snapshot.py compare `
  --control .\control.json `
  --production .\production.json `
  --output .\comparison.json
```

The following command is intentionally blocked in this construction artifact:

```powershell
python scripts\phase14_resolve_context_snapshot.py snapshot `
  --expected-project RLC-E9001_MASTER `
  --expected-timeline RLC-E9001_TIMELINE `
  --output .\production.json
```

In the published Phase 14 commit (`7e37d5f`), this returns
`live_execution_disabled` before any Resolve import or contact. **In the
unstaged Phase 14.1 revision this command is different**: the same
invocation without `--execution-authorization` now returns
`live_execution_authorization_missing`; supplying the current
`EXECUTION_REVISION_ID` (`phase14.1-live-interlock-construction-rev6`) is
required to reach the connection function, and even then, live execution is
not authorized by this document alone — since rev3, it also requires a
verified authorization manifest (§14) that does not exist yet (see §12).

## 12. Future live-capture authorization requirements

**Historical note (accurate through Phase 14.1 rev1/rev2, superseded from
rev3 onward):** earlier text here said "enabling execution requires a
source change and therefore a new hash," implying the enabling revision was
still in the future. **That enabling revision now exists** — the unstaged
Phase 14.1 source in this repository (currently rev6) already carries the
execution interlock and is live-capable pending authorization. What remains
outstanding is not a further source change but the founder-authorization
step itself, which since rev3 takes the form of an external authorization
manifest (§14), never a source-embedded value. A separately numbered
mission (not this construction review) must, before any live capture:

- generate the authorization manifest (§14) only after the current Phase
  14.1 revision's commit exists and has been independently verified;
- have that manifest independently reviewed;
- have the founder authorize the manifest's exact SHA-256, which in turn
  transitively binds the exact repository commit, all four approved file
  hashes (probe, test, contract, runbook), the execution revision
  identifier, the exact Resolve version, and the two approved contexts —
  every one of those is a manifest field, not a separate requirement to
  restate here;
- confirm abort conditions, expected exit classifications, and evidence
  preservation requirements match what `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md`
  and `scripts/phase14_live_snapshot_runbook.ps1` already implement;
- confirm no mutation or cleanup is authorized by a successful capture.

No manifest exists yet. This construction/static-review mission does not
generate one — see §14's explicit statement that no manifest is created
during construction review, and `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md`
§0 for the exact post-commit sequence.

## 13. Repository integration and publication

**Historical note:** the paragraph below describes the *original* Phase 14
construction bundle, before it was integrated into the published commit
`7e37d5f01249cc2b97714b0266a8c3caca1fabc3`. It is no longer the current
state and must not be read as present-tense instructions.

> This bundle was created outside the canonical repository. No repository
> file, Git reference, runtime database, Resolve state, or remote state was
> changed. A future founder decision is required before: copying these
> files into the repository; updating `docs/ROADMAP.md`; updating
> `docs/CHANGELOG.md`; staging or committing; pushing or opening a pull
> request. Suggested future commit subject, only after separate publication
> authorization: `feat: add Phase 14 read-only context comparison probe`.

**Current state (as of Phase 14.1 rev6):** the six Phase 14.1 files already exist
inside the canonical repository working tree — they are not "outside" it,
and there is nothing left to "copy in." They are unstaged and uncommitted.
The commit subject `feat: add Phase 14 read-only context comparison probe`
suggested above was never used for this purpose; the actual Phase 14
commit's subject was `feat: add Phase 14 read-only snapshot probe`
(`7e37d5f`). A distinct, not-yet-used subject is needed for the eventual
Phase 14.1 commit — for example:

```text
feat: add Phase 14.1 live-execution interlock and manifest-bound runbook
```

Staging, committing, and pushing all still require separate, explicit
founder authorization, per the standing project discipline — this document
proposes wording, it does not grant that authorization.

## 14. Authorization manifest schema (Phase 14.1, introduced in rev3, unchanged through rev6)

**No manifest of this shape exists yet.** It is generated only after Phase
14.1 is committed and published, entirely outside this construction/static-
review mission, and is itself independently reviewed before a founder binds
authorization to its exact SHA-256. Nothing in this section creates,
authorizes, or executes a manifest.

### 14.1 Exact shape

```json
{
  "schema_version": 1,
  "mission": "phase14.1-live-snapshot",
  "repository_root": "C:\\Users\\pj198\\Documents\\redline-os",
  "origin_url": "git@github.com:Choice283/redline-os.git",
  "authorized_commit": "<40-lowercase-hex>",
  "execution_revision_id": "phase14.1-live-interlock-construction-rev6",
  "probe_sha256": "<64-lowercase-hex>",
  "test_sha256": "<64-lowercase-hex>",
  "contract_sha256": "<64-lowercase-hex>",
  "runbook_sha256": "<64-lowercase-hex>",
  "resolve_product_version": "<exact-normalized-version>",
  "contexts": {
    "Control": {
      "project": "redline-os-test-duplicate",
      "timeline": "RLO-LIVE-ASM-92701_TIMELINE"
    },
    "Production": {
      "project": "RLC-E9001_MASTER",
      "timeline": "RLC-E9001_TIMELINE"
    }
  }
}
```

### 14.2 Field notes

- `schema_version` — integer, must currently be exactly `1`.
- `mission` — must be exactly `phase14.1-live-snapshot` (case-sensitive).
- `repository_root` / `origin_url` — must exactly match the runbook's own
  hardcoded expectations (`C:\Users\pj198\Documents\redline-os` and
  `git@github.com:Choice283/redline-os.git`), case-sensitive. This is a
  cross-check, not the sole source of truth for either value.
- `authorized_commit` — exactly 40 lowercase hex characters. This, not any
  value embedded in the runbook, is what the runbook verifies `HEAD`,
  `origin/master`, and GitHub's `refs/heads/master` against.
- `execution_revision_id` — must exactly equal the probe's
  `EXECUTION_REVISION_ID` constant for the committed revision.
- `probe_sha256` / `test_sha256` / `contract_sha256` / `runbook_sha256` —
  each exactly 64 lowercase hex characters, one per approved file. Note
  `runbook_sha256` describes the manifest-consuming runbook's own bytes —
  see §2.2's self-hash-binding point; there is no circularity here because
  the manifest is generated and hashed *after* the runbook is committed, so
  the runbook's hash is a known, fixed fact by the time the manifest is
  written, unlike rev2's attempt to have the runbook contain its own
  eventual commit SHA.
- `resolve_product_version` — the exact, single designated comparison value
  (see §2.2; the runbook records `ProductVersion` as canonical and
  `FileVersion` alongside it for evidence only).
- `contexts` — must contain exactly the keys `Control` and `Production`, no
  more, no fewer, no duplicates, each with non-empty `project` and
  `timeline` string fields matching the canonical values shown above
  exactly.

### 14.3 What the manifest replaces

Nothing in the runbook trusts a repository commit, a file hash, an
execution revision identifier, or a Resolve version from any source other
than a manifest whose own SHA-256 the operator supplied on the command line
and the runbook independently verified. The runbook's own hardcoded
constants (`$repo`, `$expectedOriginUrl`, `$expectedRevisionId`,
`$expectedMission`, the two context project/timeline pairs) exist only to
cross-check the manifest's claims against what this specific runbook
revision was built to expect — they are not themselves sufficient
authorization for anything.

### 14.4 Manifest validation error codes (rev4)

`ManifestValidationError.code`, distinct from the `SnapshotError` codes in
§7 above (a different exception class, raised only by
`validate_authorization_manifest_bytes()` / the `validate-manifest` CLI
command, never during snapshot collection). None of these ever contain a
manifest field's *value* — at most a known schema field *name*:

| Code | Meaning |
|---|---|
| `manifest_not_utf8` | Manifest bytes are not valid strict UTF-8. |
| `manifest_duplicate_key` | A JSON object key repeats at some depth. |
| `manifest_not_valid_json` | Bytes are valid UTF-8 but not valid JSON. |
| `manifest_root_not_object` | The parsed document's root is not a JSON object. |
| `manifest_unexpected_top_level_fields` | The top-level key set is not exactly the twelve required fields. |
| `manifest_schema_version_invalid` | `schema_version` is not the literal integer `1` (a JSON boolean is rejected). |
| `manifest_field_not_string:<field>` | The named field is required to be a string and is not. |
| `manifest_contexts_invalid` | `contexts` is not an object with exactly the keys `Control` and `Production`. |
| `manifest_context_fields_invalid` | A context object's key set is not exactly `project`/`timeline`. |
| `manifest_context_field_not_string` | A context's `project` or `timeline` value is not a string. |

## 15. Stop condition

The construction mission stops after:

- source completion;
- mocked test completion;
- static safety review;
- architecture contract completion;
- SHA-256 generation;
- delivery for founder review.

No live execution follows from construction approval.

**Agents advise. Paul decides.**
