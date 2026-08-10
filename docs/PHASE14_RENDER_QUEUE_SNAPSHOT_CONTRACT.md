# Phase 14 Render Queue Read-Only Snapshot Probe Contract

Status: **Construction and offline testing only.** Rev3. No live execution
has occurred against Rev1, Rev2, or Rev3. **Rev3 has not itself been
independently reviewed or approved as of this document** — it corrects the
two remaining evidence-integrity findings independent review raised against
Rev2 (§0) and is submitted for review, not a claim that review has already
passed.
Mission: **Phase 14 — Render Queue Read-Only Snapshot Probe Construction /
Rev2 → Rev3 Correction**
Files: `scripts/phase14_render_queue_snapshot.py`,
`tests/unit/test_phase14_render_queue_snapshot.py`
Construction commit (parent checkpoint verified before work began, across
Rev1, Rev2, and Rev3):
`2652cd1414f5afdf2580ec4ef42e1d0bb4b5a660`

This document does not authorize commit, push, or live Resolve execution.
Construction of this probe does not by itself change Phase 14's status or
authorize a live Broadcast Master queue attempt.

## 0. Revision history

**Rev1** (construction): initial architecture and implementation. Submitted
for independent source review.

**Rev1 independent review findings** (all corrected in Rev2; see the
referenced sections below for exactly what changed):

1. BLOCKING — exact queue-closure semantics (§6.3): `exactly_one_matching_job`
   was true even with additional queue entries present, producing a
   false-pass through `run_compare_command()`'s exit code.
2. BLOCKING — snapshot invariant validation (§6.2): `validate_queue_snapshot_document()`
   checked structural shape only, not internal consistency; a forged
   snapshot with mismatched expected/observed context, active rendering, or
   a wrong declared queue count could still reach a successful
   classification.
3. HIGH — conflicting job-ID aliases (§6.1): two recognized alias keys with
   different values were silently resolved to the first, precedence-ordered
   match.
4. HIGH — strict JSON / non-finite floats (§6.4): inherited Rev8's
   permissive `json.dumps()`/`json.loads()` defaults, which accept
   NaN/Infinity/-Infinity — not valid RFC 8259 JSON.
5. HIGH — final rendering/context bracket (§6.5): no context/rendering
   verification occurred after the second (final) queue read.
6. Documentation accuracy (§3.1): `connect_resolve_read_only` was described
   as "pure"/"Resolve-contact-free" alongside genuinely pure helpers, and
   filesystem-touching helpers were imprecisely called "pure."

**Rev2**: corrected all six Rev1 findings above. New execution revision
identifier minted per §8. **Independent exact-source review confirmed Rev2
correctly resolved all six Rev1 findings — Rev2's architecture and
corrections are accepted — but Rev2 itself did not pass review**: two
further evidence-integrity gaps were independently reproduced (§0.1),
both BLOCKING.

### 0.1 Rev2 independent review findings (both corrected in Rev3)

1. BLOCKING — cross-validate normalized Job ID against preserved fields
   (§6.6): `validate_queue_snapshot_document()` checked `job_id`/
   `job_id_status` and the preserved `fields` payload independently of each
   other. A forged entry such as `{"job_id": "expected", "job_id_status":
   "identified", "fields": {"JobId": "OTHER"}}` — internally contradictory
   evidence no honest collection could produce — still reached
   `exact_single_job_match`.
2. BLOCKING — evidence envelope must match an actual Rev3 snapshot (§6.7):
   the validator tolerated unknown top-level keys and did not validate
   `captured_at` at all. A forged document with a missing, null, NaN, or
   malformed `captured_at`, or an arbitrary extra top-level key, could
   still reach a successful comparison.

**Rev3** (this revision): corrects both findings above. New execution
revision identifier minted per §8 (Rev2's identifier, and Rev1's, are both
now explicitly rejected by the execution interlock and by
`ACCEPTED_COLLECTOR_REVISIONS`). **Rev3 has not itself been independently
reviewed or approved.**

## 1. Purpose

The RLC-E9901 Broadcast Master queue-attempt harness
(`scripts/rlc_e9901_queue_attempt_harness.py`) classified its most recent
run `PRODUCTION_QUEUE_PATH_ACCEPTED`: the production `render queue` CLI
exited `0`, the SQLite `render_jobs` row matched exactly, and stdout
corroborated a Resolve job ID. That classification is proof of the
**production queue path**, not independent proof of **Resolve's own queue
state** — the harness's only Resolve contact is one fresh getter-only
preflight subprocess run *before* the mutation, never after.

A separately authorized Rev8 getter-only context snapshot
(`scripts/phase14_resolve_context_snapshot.py`) subsequently attempted to
close that gap and correctly stopped with `render_queue_not_empty`: that
collector's own safety model requires an *empty* render queue before it
will complete, because it exists to capture two clean, comparable
Control/Production baselines. It is not designed to observe a queue that
already has something in it, and its invariant must not be weakened just to
make a post-queue observation possible — doing so would silently change
what the already-reviewed Rev8 collector is proven to guarantee.

This probe is the deliberate, separate complement: it inspects an
**existing, possibly non-empty** render queue without mutating Resolve, so
a queue-attempt result can be independently corroborated by observing the
actual Resolve queue entry and its Resolve job ID. It is generically
parameterized (expected project/timeline are caller-supplied) so it is
reusable for future Redline OS queue-state evidence collection generally,
not only for RLC-E9901.

**This construction does not itself prove RLC-E9901 queue closure.** No
live snapshot has been captured. See §9.

## 2. Distinction from `phase14_resolve_context_snapshot.py`

| | Rev8 collector | This probe |
|---|---|---|
| Purpose | Two-context Control/Production comparison baseline | Single-context existing-queue inspection |
| Render queue precondition | Must be **empty**, fails closed otherwise | Any count **permitted**, including non-empty |
| Scope of capture | Full project/timeline/media-pool/render-context tree | Current project identity, current timeline identity, rendering state, render queue only |
| Resolve method surface | 30-method allowlist | 6-method allowlist |
| Reused by this probe | Pure helpers only (see §4) | — |
| Modified by this construction | **No** — byte-identical, unmodified | — |

Both probes coexist because they answer different questions at different
moments: Rev8 answers "are these two clean contexts identical before I do
anything," and this probe answers "what, exactly, is currently sitting in
the render queue."

## 3. Architecture decision

Three approaches were evaluated, as required by the construction mission:

- **A — import pure helpers from Rev8.** Rev8's own module docstring states
  "The module may be imported and its pure comparison functions may be
  exercised freely." Genuinely pure, Resolve-contact-free helpers are
  reused this way (see §4).
- **B — a new reusable module under `src/`.** Rejected. Every existing
  Phase 14 / RLC-E9901 probe deliberately lives under `scripts/` as a
  self-contained, independently hash-pinned construct, isolated from the
  `redline_core`/`mcp_server` business-logic tree specifically so it can
  never be accidentally imported by a production code path (the
  RenderManager/ResolveAdapter composition root, the MCP server, the CLI).
  Moving read-only Resolve-inspection code into `src/redline_core/resolve/`
  — alongside the real, mutation-capable `ResolveScriptAdapter` — would
  break that isolation for no benefit: this probe's genericity (parameters,
  not hardcoding) already satisfies "reusable for future queue-state
  evidence collection" without moving it into the business-logic tree.
- **C — a narrowly self-contained probe, Rev8 untouched.** Selected, in
  combination with A: a new file under `scripts/`, reusing Rev8's already
  multiply-reviewed pure helpers by ordinary import (not duplication, not
  hash-pinned dynamic loading — Rev8's own docstring already licenses plain
  import of its pure functions), while writing new, narrower logic only
  where Rev8's existing behavior does not fit this probe's different
  invariants (see §5). Rev8's source bytes and published SHA-256 are
  unchanged by this construction.

### 3.1 What is imported from Rev8, and why each is safe

**Corrected in Rev2, Finding 6.** Rev1 described every name in this list,
including `connect_resolve_read_only`, as "pure" and "Resolve-contact-free"
in the same sentence. That was imprecise in two distinct ways, both
corrected here:

Genuinely pure (no I/O, no Resolve, deterministic) — none of them contact
Resolve, and none of them are closed over Rev8's own
`READ_ONLY_RESOLVE_METHODS` allowlist, so importing them cannot widen this
probe's own Resolve surface:

`SnapshotError`, `UnsupportedEvidenceType`, `normalize_json_value`,
`QUEUE_JOB_ID_KEYS`, `require_nonempty_string`, `require_collection`,
`PROHIBITED_RESOLVE_METHODS`.

Never contact Resolve, but **not pure** — they read the wall clock or
inspect/write local filesystem state, so calling them is not
referentially transparent, even though none of them is a Resolve-safety
concern:

- `utc_now` — reads the wall clock.
- `load_json`, `script_sha256` — read local files.
- `validate_output_path`, `write_json_no_overwrite` — inspect and write
  local filesystem state.

**Not pure, and not merely "Resolve-contact-free" either** — this is Rev8's
own deliberate live Resolve connection boundary function, reused unchanged:

- `connect_resolve_read_only` — *importing* it performs no Resolve contact
  (proven by `test_module_import_does_not_contact_resolve`). *Calling* it
  is exactly the point at which this probe — deliberately, and only after
  `enforce_execution_interlock` has already passed — contacts Resolve.
  Rev1's wording materially understated what calling this function does;
  this document and the module docstring now describe it separately from
  the two groups above.

As of Rev2, `queue_job_id` (Rev8's precedence-ordered alias lookup
function) is **no longer imported** — see Finding 3 (§6.1) for why.
`QUEUE_JOB_ID_KEYS` (the plain tuple of recognized alias names) is still
imported and reused; only the lookup function was replaced.

### 3.2 What is deliberately NOT imported, and why

- `_resolve_method` / `call_required` / `observe_optional` — closed over
  Rev8's own 30-method allowlist. Importing and calling them here would
  silently grant this probe access to every method on Rev8's broader list,
  defeating "smallest getter-only allowlist" (§4) and this module's own
  static allowlist tests (`test_dynamic_dispatch_does_not_reuse_rev8_broader_allowlist`).
  This module defines its own `_resolve_method`/`call_required`, closed
  over its own six-method `READ_ONLY_RESOLVE_METHODS`.
- `enforce_execution_interlock` — closed over Rev8's own
  `EXECUTION_REVISION_ID` constant. Reusing it would either validate
  against the wrong revision identifier or require weakening it to accept
  a parameter, changing already-reviewed Rev8 behavior. This module
  defines its own interlock function, closed over its own
  `EXECUTION_REVISION_ID` (§8).
- Rev8's `queue_inventory` — reduces each entry to `{type, keys, job_id}`
  and never fails closed on a duplicate or malformed job ID (appropriate
  for Rev8's own "did anything change" comparison, not for this probe's
  acceptance-proof role). This module has its own
  `normalize_queue_entry`/`normalize_render_queue` (§6).
- (Rev2) Rev8's `queue_job_id` — see Finding 3, §6.1: its fixed
  alias-precedence lookup returns only the first matching alias's value,
  which would hide exactly the cross-alias conflict this probe must now
  detect. This module collects every recognized alias's value itself.

## 4. Getter-only Resolve surface

Exactly six methods, the smallest set that satisfies the required design
properties (verify current project identity, verify current timeline
identity, verify rendering is inactive, read the render queue):

```
GetProjectManager
GetCurrentProject
GetName
GetCurrentTimeline
IsRenderingInProgress
GetRenderJobList
```

No other method is reachable through this module's dynamic dispatch
(`_resolve_method`/`call_required`); calling any name outside this set
raises `QueueSnapshotError("accessor_not_allowlisted", ...)` before any
attribute lookup on the Resolve handle.

## 5. Prohibited surface

This module reuses Rev8's own reviewed `PROHIBITED_RESOLVE_METHODS`
frozenset verbatim (import only widens the *prohibition* scan, never the
allowlist), which includes at minimum: `LoadProject`, `CloseProject`,
`CreateProject`, `DeleteProject`, `SaveProject`, `SetCurrentTimeline`,
`SetSetting`, `SetRenderSettings`, `LoadRenderPreset`, `AddRenderJob`,
`DeleteRenderJob`, `DeleteAllRenderJobs`, `StartRendering`,
`StopRendering`, and more (see Rev8's own module for the complete set).
`tests/unit/test_phase14_render_queue_snapshot.py::test_prohibited_resolve_methods_absent_from_source`
statically parses this probe's own AST and asserts none of these names
appear anywhere as an attribute access or string literal — not merely that
they are unused at runtime.

## 6. Queue entry normalization, validation, and comparison

`normalize_render_queue(raw_jobs)`:

1. Validates the top-level return value via Rev8's `require_collection`
   (list/tuple, or Resolve's documented falsy-empty-queue return) —
   anything else fails closed with `invalid_collection`.
2. Normalizes each entry via `normalize_queue_entry(item, index)`:
   - A non-dict entry fails closed (`queue_entry_malformed`).
   - A non-string key fails closed (`queue_entry_key_not_string`).
   - The job ID is classified via `_job_id_key_status` (§6.1).
   - Every other field passes through Rev8's `normalize_json_value`, which
     itself fails closed (`queue_entry_fields_unrepresentable`) on any
     value it cannot represent as safe JSON — never stringifies or
     `repr()`'s an arbitrary bridge object.
3. After all entries normalize, any two `"identified"` entries sharing the
   same job ID fail closed (`duplicate_render_queue_job_id`) — a duplicate
   would make downstream acceptance comparison ambiguous by construction.

### 6.1 Finding 3 (HIGH) — conflicting job-ID aliases

**Rev1 behavior:** `_job_id_key_status` called Rev8's `queue_job_id()`,
which scans the recognized alias keys (`JobId`/`JobID`/`jobId`/`job_id`/
`Id`/`ID`/`id`) in a fixed precedence order and returns the *first* match.
An entry such as `{"JobId": "3c0af847-...", "job_id": "DIFFERENT-ID"}`
silently classified as `"identified"` with the higher-precedence alias's
value, discarding the conflicting lower-precedence alias's value without
any indication a conflict existed.

**Rev2 correction:** `_job_id_key_status` now collects every recognized
alias's normalized value (`str(value).strip()`, matching Rev8's own
normalization) into a `{normalized_value: [keys]}` map:

- Zero usable values → `"unidentified"`.
- Exactly one distinct usable value (whether from one alias or several
  agreeing aliases, e.g. `{"JobId": "same", "job_id": "same"}`) →
  `"identified"`.
- More than one distinct usable value (e.g. `{"JobId": "one", "job_id":
  "two"}`) → `"conflicting"`, which `normalize_queue_entry` turns into a
  fail-closed `queue_entry_job_id_conflicting` error — never silently
  resolved by precedence.
- Any recognized alias mapped to an unsupported value type (a dict/list) →
  `"malformed"`, unchanged from Rev1, still fail-closed.

`queue_job_id` is no longer imported from Rev8 for this purpose (§3.1);
`QUEUE_JOB_ID_KEYS` is still reused for the alias-name list itself.

### 6.2 Finding 2 (BLOCKING) — snapshot invariant validation

**Rev1 behavior:** `validate_queue_snapshot_document()` checked only:
`schema_version`, `snapshot_complete is True`, the presence of five
required top-level keys, and that `render_queue` was a list. Independent
review reproduced a synthetic snapshot with `observed_context` differing
from `expected_context`, `rendering_in_progress: true`,
`render_queue_count: 999` against an actual one-entry queue, and an entry
whose `index` did not match its queue position — and it still reached
`compare_expected_job_id`'s classification logic and could produce
`exactly_one_matching_job`.

**Rev2 correction:** `validate_queue_snapshot_document()` now additionally
checks, in order, failing closed at the first violation:

- **Document identity:** `mission` matches exactly; `collector` is an
  object with exactly `{name, revision}`; `collector.name` equals
  `COLLECTOR_NAME`; `collector.revision` is a member of
  `ACCEPTED_COLLECTOR_REVISIONS` (§8.1).
- **Context:** `expected_context`/`observed_context` are each objects with
  exactly `{project, timeline}`; both fields in both objects are non-empty
  strings; **`observed_context.project == expected_context.project`** and
  **`observed_context.timeline == expected_context.timeline`**. A
  legitimately collected snapshot always satisfies this — Rev2's
  `_verify_context_and_rendering_inactive` (§6.5) only ever lets collection
  proceed when the observed identity already equals the expected identity
  — so a document where they differ could not have been honestly produced
  by this probe.
- **Rendering:** `rendering_in_progress is False` — the identity check,
  not equality (`!=`), so `True`, `None`, `0`, `1`, `"false"`, or any other
  non-`bool`-`False` value fails closed with `snapshot_rendering_not_false`.
- **Queue structure:** `render_queue_count` is a non-negative `int` (not
  `bool`) and equals `len(render_queue)` exactly. Every entry: is a dict
  with exactly `{index, job_id, job_id_status, fields}`; `index` is a
  non-negative `int` equal to its position in the list (deterministic,
  in-order); `job_id_status` is `"identified"` or `"unidentified"` (never
  `"malformed"`/`"conflicting"` — those can never legitimately appear in a
  completed document, §6.1); `identified` requires a non-empty string
  `job_id`; `unidentified` requires `job_id is None`; identified job IDs
  are unique across the whole document; `fields` is a dict with string
  keys, representable as safe JSON, and contains no non-finite float
  (§6.4, applied here defensively to catch a forged input file, not only
  this probe's own output).

### 6.3 Finding 1 (BLOCKING) — exact queue-closure semantics

**Rev1 behavior:** `compare_expected_job_id` classified a match as
`"exactly_one_matching_job"` whenever exactly one identified entry equaled
the expected job ID, regardless of how many *other* entries (identified or
unidentified) were also present. `run_compare_command()`'s exit code was
`0` whenever that classification held, so a queue containing the expected
job plus an unrelated job — or the expected job plus an unidentified entry
— still exited `0`.

**Rev2 correction:** `compare_expected_job_id` now returns exactly one of
five mutually exclusive classifications, computed from
`render_queue_count`, `identified_job_id_count`, `unidentified_entry_count`,
and `matching_job_count` — but the caller never has to combine them itself;
`classification` alone is authoritative:

| Classification | Condition |
|---|---|
| `exact_single_job_match` | `matching_job_count == 1 and render_queue_count == 1 and identified_job_id_count == 1` — the **only** success outcome |
| `zero_matching_jobs` | expected job ID not found among identified entries |
| `ambiguous_due_to_unidentified_entries` | expected job ID matched exactly once, but at least one unidentified entry is also present |
| `expected_job_present_with_additional_jobs` | expected job ID matched exactly once, plus at least one other *identified* job, no unidentified entries |
| `no_expected_job_id_supplied` | `--expected-job-id` omitted; observational only |

A `matching_job_count > 1` is defensively treated as an invariant violation
(`duplicate_identified_job_id_in_validated_snapshot`) rather than a normal
classification: §6.2's validator already requires identified job IDs to be
unique, so this should be unreachable for any snapshot that passed
validation — reaching it anyway means the validated invariant was somehow
violated, which fails closed rather than silently picking a match.

`run_compare_command()` exits `0` (with `--expected-job-id` supplied) if
and only if `classification == "exact_single_job_match"`; every other
classification, including `expected_job_present_with_additional_jobs` and
`ambiguous_due_to_unidentified_entries`, exits `3`.

### 6.4 Finding 4 (HIGH) — strict JSON / non-finite floats

**Rev1 behavior:** Rev8's imported `normalize_json_value` passes `float`
values through unchanged with no finiteness check, and Rev8's imported
`write_json_no_overwrite` calls `json.dumps(...)`/`json.loads(...)` with
Python's permissive defaults (`allow_nan=True`), which accept and
round-trip `NaN`/`Infinity`/`-Infinity` — tokens RFC 8259 does not define.
A queue entry field containing a non-finite float would silently reach
disk as non-standard JSON.

**Rev2 correction (does not modify Rev8):** a new local, probe-owned strict
layer:

- `require_finite_json_value(value)` recursively walks an already
  `normalize_json_value`'d value and raises
  `non_finite_float_in_evidence` on the first non-finite `float`
  (`math.isfinite(...)`).
- `write_strict_json_no_overwrite(path, value)` calls
  `require_finite_json_value`, then a redundant explicit
  `json.dumps(normalized, allow_nan=False)` re-validation, then delegates
  to Rev8's unchanged `write_json_no_overwrite` for the actual create-only
  atomic write.

Applied at three points: inside `collect_render_queue_snapshot` itself
(so an in-memory collected snapshot containing a non-finite float raises
before it is even returned, independent of whether it is ever written),
in both CLI write paths (`run_snapshot_command` and `run_compare_command`
both now call `write_strict_json_no_overwrite`, not
`write_json_no_overwrite` directly), and defensively inside
`validate_queue_snapshot_document` (§6.2) against a forged *input* file.

### 6.5 Finding 5 (HIGH) — final rendering/context bracket

**Rev1 behavior:** context/rendering verification occurred only
immediately before each of the two `GetRenderJobList()` reads (`_capture_guard`
called twice: pre, post). No verification occurred after the second read
returned — rendering could begin, or the current project/timeline could
change, in the window between the second read completing and the snapshot
being finalized, without ever being observed.

**Rev2 correction:** the verification logic was factored out into
`_verify_context_and_rendering_inactive` (identity + rendering check, no
queue read), which `_capture_guard` calls before its own queue read.
`collect_render_queue_snapshot` now calls this verification a **third**
time, directly, after both queue reads have completed and been compared
for drift, with **no** further queue read of its own:

```
verify expected current project/timeline      [call 1]
IsRenderingInProgress -> false                 [call 1]
GetRenderJobList -> A                          [call 1]

verify expected current project/timeline       [call 2]
IsRenderingInProgress -> false                 [call 2]
GetRenderJobList -> B                          [call 2]

verify expected current project/timeline again [call 3]
IsRenderingInProgress -> false                 [call 3]

require normalized A == normalized B
```

No new Resolve method name was introduced — the third call reuses exactly
the same `GetProjectManager`/`GetCurrentProject`/`GetName`/
`GetCurrentTimeline`/`IsRenderingInProgress` sequence the first two calls
already use; `READ_ONLY_RESOLVE_METHODS` is unchanged (still six methods,
verified by its own test). The third call's observed
project/timeline/rendering values — not the second call's — are what the
published snapshot's `observed_context`/`rendering_in_progress` report,
since they are the most recently confirmed-consistent state before
finalization. If the third call finds a mismatched project/timeline or
active rendering, it fails closed exactly like the first two calls do.

### 6.6 Rev3 Finding 1 (BLOCKING) — cross-validate normalized Job ID against preserved fields

**Rev2 behavior:** `validate_queue_snapshot_document()` validated an
entry's `job_id`/`job_id_status` (§6.2, per-entry shape/status/uniqueness
checks) and its `fields` payload (representable as safe JSON, finite) as
two independent concerns — never checking that the two actually agree.
Independent review reproduced a forged entry —
`{"job_id": "3c0af847-bddd-43ee-8b79-a7b64cb915b4", "job_id_status":
"identified", "fields": {"JobId": "OTHER"}}` — that still reached
`exact_single_job_match`, even though `normalize_queue_entry()` (§6, live
collection) could never have honestly produced it: the stored `job_id` is
always *derived from* the entry's own `fields` at collection time, so a
document where they disagree could not have come from a real collection
run.

**Rev3 correction:** for every entry, after the existing `fields`
structural checks, `validate_queue_snapshot_document()` calls
`_job_id_key_status(fields)` — the exact same function live collection
uses — and requires the result to agree with the entry's stored
`job_id_status`/`job_id`:

- `_job_id_key_status(fields)` returns `"malformed"` →
  `snapshot_render_queue_entry_fields_job_id_malformed` (fails closed
  regardless of what the entry's stored `job_id_status` claims).
- returns `"conflicting"` →
  `snapshot_render_queue_entry_fields_job_id_conflicting` (likewise).
- returns a status that disagrees with the entry's stored
  `job_id_status` → `snapshot_render_queue_entry_job_id_status_disagrees_with_fields`.
- returns `"identified"`, agrees on status, but disagrees on the derived
  job ID value itself → `snapshot_render_queue_entry_job_id_disagrees_with_fields`.

An entry with agreeing aliases in `fields` (e.g. `{"JobId": "expected",
"job_id": "expected"}`) still validates successfully — this check requires
agreement with the derived canonical value, not textual identity with
every raw field.

### 6.7 Rev3 Finding 2 (BLOCKING) — evidence envelope must match an actual Rev3 snapshot

**Rev2 behavior:** the validator's top-level check (`_REQUIRED_SNAPSHOT_SECTIONS`)
only confirmed six of the ten fields this collector actually produces were
*present* — it never rejected an unexpected additional top-level key, and
`captured_at` was never validated at all (not even for type). Independent
review confirmed a forged document with `captured_at` missing, `null`,
`NaN`, or an arbitrary extra top-level key could all still reach a
successful comparison.

**Rev3 correction:** `_REQUIRED_TOP_LEVEL_KEYS` is the complete, exact set
of ten keys this collector ever produces (`schema_version`, `mission`,
`captured_at`, `collector`, `expected_context`, `observed_context`,
`rendering_in_progress`, `render_queue_count`, `render_queue`,
`snapshot_complete`). The validator now requires `set(snapshot) ==
_REQUIRED_TOP_LEVEL_KEYS` exactly — no missing key, no extra key — as one
of its first checks (`snapshot_top_level_keys_invalid` on violation).
`captured_at` is validated by `_validate_captured_at()`: it must be a
non-empty string (`snapshot_captured_at_invalid` otherwise — this alone
rejects `None`, and a `NaN` value is caught even earlier by the
whole-document finiteness check below, since `NaN` is a `float`, not a
`str`), it must match `_CAPTURED_AT_PATTERN`
(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$` — exactly this
collector's `utc_now()` shape: microsecond-resolution UTC with a literal
trailing `Z`, never a numeric offset, so any non-UTC or offset-bearing
timestamp is rejected by shape alone) — `snapshot_captured_at_malformed`
otherwise — and it must parse as a genuine calendar instant via
`datetime.strptime` (rejecting shape-valid-but-impossible values like
month `13` or hour `99`) — `snapshot_captured_at_not_parseable` otherwise.

Additionally, `require_finite_json_value(snapshot)` is now called once,
on the **complete** document, as the validator's very first structural
check — before the top-level key-set check, before any field-level
validation. This supersedes Rev2's narrower per-entry
`require_finite_json_value(fields, ...)` call (removed as redundant,
since the whole-document walk already recurses into every entry's
`fields`): a non-finite float anywhere in the document — not only inside
an entry's `fields` — now fails closed with the same
`non_finite_float_in_evidence` code.

## 7. Evidence schema

```json
{
  "schema_version": "1.0",
  "mission": "Phase 14 — Render Queue Read-Only Snapshot Probe",
  "captured_at": "2026-08-10T00:00:00.000000Z",
  "collector": {
    "name": "phase14_render_queue_snapshot",
    "revision": "phase14.2-render-queue-snapshot-construction-rev3"
  },
  "expected_context": {"project": "...", "timeline": "..."},
  "observed_context": {"project": "...", "timeline": "..."},
  "rendering_in_progress": false,
  "render_queue_count": 1,
  "render_queue": [
    {
      "index": 0,
      "job_id": "3c0af847-bddd-43ee-8b79-a7b64cb915b4",
      "job_id_status": "identified",
      "fields": {"JobId": "3c0af847-bddd-43ee-8b79-a7b64cb915b4", "...": "..."}
    }
  ],
  "snapshot_complete": true
}
```

Written via `write_strict_json_no_overwrite` (§6.4), which enforces strict
finite-only JSON before delegating to Rev8's own
`write_json_no_overwrite` for the actual publication: full serialization is
validated in memory, then published via a same-directory temp file and a
create-only atomic link (`os.link`, which raises on an existing
destination on both Windows and POSIX) — an existing output path is never
overwritten. `compare`'s comparison-result output is written through the
same strict writer (§6.4).

## 8. Execution interlock

Identical shape to Rev8's, bound to this module's own revision identifier,
minted fresh for Rev3 because source behavior changed (§0.1's two
findings):

```
EXECUTION_REVISION_ID = "phase14.2-render-queue-snapshot-construction-rev3"
```

`snapshot` requires `--execution-authorization <exact value above>`. A
missing, malformed, or mismatched value fails closed
(`live_execution_authorization_missing` /
`live_execution_authorization_invalid` /
`live_execution_revision_mismatch`) before output-path validation, before
`DaVinciResolveScript` import, and before any Resolve connection. The
interlock is a deliberate execution control, not a credential. Both Rev1's
identifier (`...-rev1`) and Rev2's (`...-rev2`) are explicitly rejected by
Rev3 — the interlock check is byte-exact, not "starts with" or "any known
revision."

**Construction of this probe does not authorize live execution.** A future
founder authorization for live use must bind: the exact repository commit,
this exact source SHA-256, this exact `EXECUTION_REVISION_ID`, the exact
expected project/timeline, and the exact evidence output path.

### 8.1 Accepted collector-revision policy for offline comparison

`compare_expected_job_id` (via `validate_queue_snapshot_document`, §6.7)
only accepts a snapshot whose own `collector.revision` is a member of
`ACCEPTED_COLLECTOR_REVISIONS`, currently exactly
`{"phase14.2-render-queue-snapshot-construction-rev3"}` — this exact
revision, and no other. No prior revision's live evidence exists (Rev1 and
Rev2 were never executed live), and accepting a different revision's output
would mean trusting a document collected under different, possibly weaker,
validation semantics than the ones this exact source now enforces. Remains
fail-closed to exactly the current revision in Rev3 — no concrete reason to
widen it was identified during this correction's architecture review. A
future revision that legitimately needs to accept additional historical
revisions must do so by deliberately widening this frozenset, reviewed as
its own change — not by loosening the equality check itself.

### 8.2 Additional hardening: `expected_job_id` shape (Rev3)

`compare_expected_job_id()` now requires a non-`None` `expected_job_id`
argument to be a non-empty string — checked before snapshot validation.
`None` (the "observational only" query, `no_expected_job_id_supplied`) is
unaffected; a whitespace-only or non-string value now fails closed
(`expected_job_id_invalid`) instead of being silently treated as an
ordinary query that simply never matches any queue entry. No legitimate
CLI invocation is affected: `argparse` only ever supplies `None` or an
actual string for `--expected-job-id`.

## 9. Usage examples (not yet authorized for live invocation)

Collect a snapshot (requires future live authorization):

```
python scripts\phase14_render_queue_snapshot.py snapshot ^
  --expected-project RLC-E9901_MASTER ^
  --expected-timeline RLC-E9901_TIMELINE ^
  --output <evidence-dir>\render_queue_snapshot.json ^
  --execution-authorization phase14.2-render-queue-snapshot-construction-rev3
```

Offline acceptance comparison (never contacts Resolve; usable today against
any already-collected snapshot file):

```
python scripts\phase14_render_queue_snapshot.py compare ^
  --snapshot <evidence-dir>\render_queue_snapshot.json ^
  --expected-job-id 3c0af847-bddd-43ee-8b79-a7b64cb915b4 ^
  --output <evidence-dir>\render_queue_comparison.json
```

`compare` exits `0` (with `--expected-job-id` supplied) if and only if the
comparison classifies `exact_single_job_match` (§6.3); every other
classification (`zero_matching_jobs`,
`ambiguous_due_to_unidentified_entries`,
`expected_job_present_with_additional_jobs`) exits `3`. Omitting
`--expected-job-id` always exits `0` (`no_expected_job_id_supplied`, an
observational-only run).

### 9.1 Expected future RLC-E9901 closure workflow

1. Obtain a separate, explicit founder authorization binding this exact
   probe's commit, SHA-256, `EXECUTION_REVISION_ID`, the expected
   `RLC-E9901_MASTER` / `RLC-E9901_TIMELINE` context, and a fresh evidence
   path.
2. Run `snapshot` once, live, against that authorization.
3. Run `compare` offline against the resulting snapshot with
   `--expected-job-id 3c0af847-bddd-43ee-8b79-a7b64cb915b4` (the Resolve
   job ID already reported by the queue-attempt harness's own stdout
   corroboration).
4. `exact_single_job_match` is the independent Resolve-side confirmation
   the queue-attempt harness's `PRODUCTION_QUEUE_PATH_ACCEPTED`
   classification alone cannot provide — the render queue contains exactly
   one entry, it is identified, and its job ID equals the expected one.
   Any other classification is evidence of a discrepancy, not proof of
   one — it does not by itself authorize repair, deletion, or a retry.

This construction performs none of these steps. No live snapshot exists as
of this document.

## 10. Limitations

- This probe proves what the render queue currently contains at the moment
  of capture; it does not prove *when* a given job was added, does not
  observe rendering progress or completion, and does not distinguish a job
  added by this repository's own harness from one added manually through
  the Resolve UI.
- `job_id_status: "unidentified"` entries (no known job-ID key present with
  a usable value) are preserved in evidence but excluded from
  `compare_expected_job_id`'s matching count; their mere presence, however,
  is sufficient by itself to keep an otherwise-matching queue out of
  `exact_single_job_match` (`ambiguous_due_to_unidentified_entries`,
  §6.3) — an unidentified entry can neither confirm nor rule out a
  match, so Rev2 treats its presence as blocking formal closure rather
  than as something to silently ignore.
- Rev2's third context/rendering guard (§6.5) still cannot observe Resolve
  state between the moment it returns and the moment the snapshot is
  actually written to disk — a vanishingly small window compared to Rev1's
  completely unguarded post-read gap, but not literally zero. Equality/
  absence of drift among all three guard calls does not rule out Resolve
  state this probe's six-method surface cannot observe.
- This probe does not itself resolve Phase 14's separate, still-open
  Broadcast Master queue-acceptance root-cause question for any project
  other than the one it is pointed at; it is an evidence-collection tool,
  not a root-cause diagnostic.
- `ACCEPTED_COLLECTOR_REVISIONS` (§8.1) means `compare` can only evaluate
  a snapshot collected by this exact Rev3 source — a Rev1 or Rev2 snapshot
  (neither exists) or a future Rev4 snapshot would all be rejected at
  validation, by design.
- The Rev3 Finding 1 cross-validation (§6.6) proves internal consistency
  between an entry's stored `job_id`/`job_id_status` and its own preserved
  `fields` — it does not, and cannot, prove that `fields` itself is an
  honest, unmodified copy of what Resolve actually returned; that
  assurance comes from the snapshot having been produced by this exact
  collector revision in the first place (`ACCEPTED_COLLECTOR_REVISIONS`),
  not from any property this validator can check about the bytes alone.
- The Rev3 Finding 2 `captured_at` check (§6.7) proves the timestamp is a
  well-formed, real UTC calendar instant in this collector's exact emitted
  shape — it does not prove the timestamp is accurate, recent, or that the
  system clock that produced it was correct.
