# Phase 14.1 Live-Execution Enablement — Static Review Report

Status: **Unstaged construction and static review only. Not committed. Not authorized for live use.**
Mission: **Phase 14.1 — Live Snapshot Enablement Construction and Static Review, revision 7 (native-process compatibility correction)**
Base commit reviewed against: `39c0b0522b26e7cfca5e23ea661a4f532de7b5d4` ("feat: finalize Phase 14.1 snapshot enablement controls")
Execution revision identifier for THIS revision (rev7) only: `phase14.1-live-interlock-construction-rev7`
Every other revision identifier appearing anywhere below (`...-rev1` through `...-rev6`) is historical and does not apply to the current source. Rev6 was published at commit `39c0b0522b26e7cfca5e23ea661a4f532de7b5d4` and is superseded by this unstaged Rev7 correction candidate.
This document itself is an unstaged proposed supporting artifact and has no authorization-manifest SHA-256 binding of its own. The four current manifest-bound exact-byte artifacts are the comparison contract, live PowerShell runbook, Python snapshot probe, and focused test file; `.gitattributes` enforces LF checkout determinism for those four paths.

## 0. Revision history

- **rev1** (first Phase 14.1 construction pass): introduced the execution
  interlock and a UUID-plus-`open()` atomic writer. Passed compilation and
  its own 36 focused tests, but did not receive independent review before
  this document originally, incorrectly, stated no corrections were
  pending.
- **rev2** (historical — superseded by rev3, then rev4; not the current
  source): applied every correction from an independent review of rev1.
  Summary of what changed and why, in the same order as the review findings:
  1. `EXECUTION_REVISION_ID` changed from `...-rev1` to `...-rev2`, updated
     everywhere it is referenced, because the probe source itself changed —
     an identifier must name the exact bytes it was assigned to.
  2. `enforce_execution_interlock()` no longer calls `.strip()` on the
     supplied value. A value with leading/trailing whitespace, or a
     whitespace-only value, now fails `EXECUTION_REVISION_ID_PATTERN` (whose
     first and last character classes exclude whitespace) and is reported
     `live_execution_authorization_invalid`, not silently trimmed and
     possibly accepted.
  3. The atomic writer was rebuilt on `tempfile.mkstemp()` (OS-backed
     exclusive creation) in place of a hand-rolled UUID name passed to
     `open(..., "w")`, which never had OS-enforced exclusivity.
  4. Every controlled filesystem failure in the writer is now a distinct
     `SnapshotError`: `output_temp_create_failed`, `output_write_failed`,
     `output_publish_failed`, `output_temp_cleanup_failed` (in addition to
     the pre-existing `output_path_already_exists` /
     `output_path_is_directory` / `output_parent_directory_missing`). A temp
     cleanup failure is raised, never swallowed, and distinguishes whether
     publication had already succeeded.
  5. 10 new tests were added (whitespace × 3, temp-collision, generic
     temp-creation failure, write/fsync failure, generic publish failure,
     publish-race, cleanup-failure-surfaced, `main()` exit classification),
     and one existing test was renamed and its docstring corrected because
     it had never actually proven post-creation cleanup (see §6).
  6. The runbook's evidence root moved from inside the repository
     (`redline-os\phase14_evidence\`) to a freshly, exclusively created
     directory under the operator's Documents folder, entirely outside the
     repository, with no `-Force` anywhere in its creation path.
  7. The runbook now copies the exact probe source into the evidence
     directory, hashes the copy, requires it to match the approved hash,
     executes that copy (not the mutable repository path) using a Python
     executable path resolved once and reused (not re-resolved at execution
     time), and reverifies both repository state and the original source
     hash immediately after the typed confirmation and immediately after
     the capture.
  8. A nonzero probe exit now `throw`s (previously a bare top-level
     `return`, which would have let the script report a misleadingly clean
     exit); the evidence directory is preserved either way.
  9. A success-evidence validation block runs before packaging (exit code,
     file-type, hash, JSON parse, `snapshot_complete`, expected-context
     match, pre/post guard identity match, empty stderr, unchanged
     repository/probe-hash after capture), recorded to
     `execution_validation.json`.
  10. Evidence packaging is create-only (no `Compress-Archive -Force`); the
      runbook rejects both a pre-existing evidence directory and a
      pre-existing ZIP, and reports source/entry file counts, ZIP size,
      ZIP SHA-256, and a full-read archive-integrity result.
  11. This document, the contract, and the runbook document were corrected
      for the inaccuracies listed in §7.
- **rev3** (historical — superseded by rev4; not the current source):
  applied every correction from a second independent review, this time
  focused entirely on the runbook, which the rev2 review accepted the
  Python writer changes but found the runbook
  itself not ready. Full detail in contract §2.2 and
  `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §0; summary:
  1. `EXECUTION_REVISION_ID` changed to `...-rev3`, updated everywhere.
  2. **Architectural replacement, not a patch**: rev2's runbook embedded a
     `$expectedRepoCommit` placeholder meant to be replaced with the
     resulting commit SHA after committing the runbook itself — an
     unresolvable self-reference (editing the file to add its own future
     commit's SHA changes the file, which changes the commit, which changes
     the SHA). rev3 removes the embedded commit entirely and requires an
     external, founder-authorized authorization manifest (contract §14),
     generated only after the commit exists.
  3. The runbook now verifies its own executing bytes (`$PSCommandPath`)
     against the manifest's `runbook_sha256` before doing anything else.
  4. All authorization-relevant comparisons in the runbook switched from
     PowerShell's default case-insensitive `-eq`/`-ne` to explicit
     case-sensitive `-ceq`/`-cne`/`-cnotmatch` — the typed confirmation
     phrase and the execution-authorization value were previously
     satisfiable by a lowercase or mixed-case variant.
  5. `EXECUTION_REVISION_ID_PATTERN` fixed to require *both* endpoints
     alphanumeric (rev1/rev2 only constrained the first character; a value
     ending in `.`, `_`, or `-` still passed).
  6. The Python interpreter is resolved once and reused for version
     verification too (`sys.version_info` via the resolved executable, not
     a second `py -3.11 --version` launcher call).
  7. Resolve's version is compared exactly, not with a substring-tolerant
     regex.
  8. The evidence-directory probe copy is rehashed at six points instead of
     rev2's two (see runbook doc §5).
  9. `connect_resolve_read_only()` no longer lets import or connection
     exceptions escape as raw tracebacks (`resolve_module_import_failed`,
     `resolve_scriptapp_call_failed`).
  10. `execution_validation.json` is now written after every individual
      check, not only once all checks pass.
  11. A process that fails to start is itself a recorded, structured
      outcome, not an uncaught exception.
  12. Evidence hashing now covers the copied runbook, contract, and
      manifest, not only the probe.
  13. 8 new tests were added (3 pattern-boundary, 2 minimum/single-char
      boundary, 3 structured Resolve-connection-failure modes).
  14. Contract and runbook documentation corrected for the staleness the
      review found (§7 below).
- **rev4 (historical — constructed and staged for a staged-diff review;
  the staged candidate was rejected for commit consideration; no commit or
  publication occurred; superseded by rev5; not the current source)**:
  applied every correction
  from a third independent review, which conditionally accepted the Python
  probe and writer but found the manifest parser and runbook still
  incomplete. Full detail in contract §2.3 and
  `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §0; summary:
  1. `EXECUTION_REVISION_ID` changed to `...-rev4`, updated everywhere.
  2. **A real non-contact preflight mode**: `-PreflightOnly` runs every
     check up to (never including) the typed confirmation and the
     Resolve-contacting launch — manifest validation, self-hash binding,
     repository/remote/commit/artifact hashes, the exact Python
     interpreter, Resolve's version and environment configuration, and a
     full preflight evidence copy-and-package — with no `Read-Host` and no
     snapshot launch anywhere on that path, exiting `0` only when every
     preflight check passed and explicitly reporting `Resolve contact:
     false`, `Snapshot execution: false`, `Preflight complete: true`.
  3. **Duplicate-key-safe, exact-schema manifest validation**, moved into
     the probe itself (`validate_authorization_manifest_bytes()` plus a new
     `validate-manifest` CLI subcommand) rather than an untestable
     PowerShell-embedded script fragment, because Windows PowerShell 5.1's
     `ConvertFrom-Json` silently resolves a duplicate JSON object key to
     the last value at any depth. The same function is exercised directly
     by 13 new pytest cases and invoked as a subprocess by the runbook, so
     both consumers share exactly one implementation.
  4. **Single-byte-read binding**: the runbook reads the manifest as raw
     bytes exactly once; those same bytes are hashed, strict-UTF-8-decoded,
     piped to the validator's stdin, and written verbatim into the evidence
     copy — never a second read of the source path, never a re-serialization.
  5. **Exception-safe validation**: every recorded check runs inside a
     shared `Invoke-ValidationCheck` helper that catches an exception
     raised while *evaluating* the check itself (a bad file read, a JSON
     parse failure, a missing property, a hashing error) and records it
     rather than letting it crash the script with a stale validation file.
     A top-level `try`/`catch`, active from the moment the evidence
     directory exists, writes `runbook_failure.json` for any
     otherwise-unclassified terminating exception before the script exits
     nonzero.
  6. **Working-directory independence**: every local Git command is rooted
     with `git -C $repo`; the repository root is itself re-verified via
     `git -C $repo rev-parse --show-toplevel` against the canonical path.
  7. **Reparse-point guarding**: a reusable `Assert-OrdinaryFile` helper
     (exists, is a file, is not a directory, does not carry
     `FileAttributes.ReparsePoint`) is applied to the manifest,
     `$PSCommandPath`, the canonical repository runbook copy, the
     repository probe/test/contract files, the resolved Python executable,
     `Resolve.exe`, and every copied evidence artifact; the freshly created
     evidence directory is checked the same way.
  8. Corrected the two rev3 documentation defects this same review found:
     contract §15.1–§15.3 renumbered to §14.1–§14.3 (they sat under a
     section renamed to §14 but were never renumbered themselves), and
     this document's own rev2 and rev3 history entries, which were both
     still labeled "(this revision)" instead of being marked historical
     once superseded.
  9. 16 new tests were added: 1 revision-identifier check plus 13 manifest-
     validator tests (duplicate top-level key, duplicate nested key,
     unexpected top-level field, missing top-level field, unexpected
     context field, unexpected context name, string schema_version, boolean
     schema_version, non-string field, invalid UTF-8, non-object root, a
     field-value-not-leaked check, and a valid-manifest-accepted check) and
     2 CLI round-trip tests (valid manifest accepted, duplicate key
     rejected), all without importing or contacting Resolve.
- **rev5 (historical — staged for review, then rejected; superseded by
  rev6; not the current source)**: rev4 was staged and put
  through a read-only staged-diff review, which found three Important and
  two Minor findings in `scripts/phase14_live_snapshot_runbook.ps1`. The
  staged candidate was rejected for commit consideration; the six files
  were unstaged without discarding content; no commit or publication
  occurred. Full detail in contract §2.4 and
  `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §0; summary:
  1. `EXECUTION_REVISION_ID` changed to `...-rev5`, updated everywhere.
  2. **Repository-root validation ordering fixed**: `Assert-RepoCheckpoint`
     no longer passes Git's output into `Resolve-Path` before checking
     `$LASTEXITCODE` — the exit code of every Git call in that function is
     now captured and checked before its output is touched by anything
     that could itself throw, and failure messages are static rather than
     interpolating raw command output.
  3. **Six real, individually reachable probe-hash checkpoints** replace
     the previous mix of one early general check plus a pair of bare,
     literally duplicate post-confirmation checks:
     `repository_probe_hash_pre_copy`, `evidence_probe_hash_post_copy`,
     `repository_probe_hash_pre_confirmation`,
     `evidence_probe_hash_pre_confirmation`,
     `repository_probe_hash_pre_launch`, `evidence_probe_hash_pre_launch`.
     Every one of them runs through `Invoke-ValidationCheck`; no bare
     post-confirmation hash `if (...) { throw ... }` remains anywhere in
     the file. In `-PreflightOnly` mode the pre-copy/post-copy/
     pre-confirmation checkpoints are attempted and both pre-launch
     checkpoints stay `not_run`, because that branch returns before either
     could be reached — confirmed both by direct code read and by the
     `preflight_result.json` now embedding a full snapshot of `$validation`.
  4. **Original exception identity preserved**: `Invoke-ValidationCheck`'s
     catch block now records `$_.Exception.GetType().FullName` and
     re-raises with a bare `throw` (not `throw "STOP: ..."`), so
     `runbook_failure.json` (written by the outer handler) reports the same
     real exception type as `execution_validation.json`'s
     `failure_exception_type`, rather than a wrapping `RuntimeException`.
  5. **The redundant duplicate check is gone**: pre-confirmation and
     pre-launch are now two checkpoints genuinely separated by the typed
     confirmation itself, not the same check run twice back to back with
     nothing in between.
  6. Documentation no longer says a check happens "immediately before" a
     step unless the code is actually placed immediately before it; while
     making this correction, two further stale "current revision"
     mislabels were found and fixed in the contract (§2.2's rev3 entry and
     the "Current state" note in §13 were still marked current after being
     superseded) — the same class of bug this very item exists to prevent,
     caught by applying the fix to every file, not just the two the review
     named.
  7. No new tests were required for these five fixes — they are PowerShell
     runbook behaviors, verified by the same static/structural review
     method as their rev4 counterparts (§6 below), plus the existing 70
     pytest cases re-confirmed unaffected by a Python-side identifier-only
     change.
- **rev6 (this revision — the current source)**: rev5 was staged and put
  through a second, independent read-only staged-diff review (hashing the
  actual staged Git blobs, not just the working tree). That review found
  one Important finding and one Minor finding, both in documentation, not
  in `scripts/phase14_live_snapshot_runbook.ps1`'s runtime logic. The
  staged candidate was rejected for commit consideration; the six files
  were unstaged without discarding content; no commit or publication
  occurred. Full detail in contract §2.5 and
  `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §0; summary:
  1. `EXECUTION_REVISION_ID` changed to `...-rev6`, updated everywhere.
  2. **Stale test count corrected**: contract §10 said "46 tests total ...
     as of Phase 14.1 rev2" with no historical marking, even though the
     document had by then been revised through rev5 — the actual count had
     grown to 70 (21 unchanged + 2 updated + 13 rev1-new + 10 rev2-new + 8
     rev3-new + 16 rev4-new = 70; see §6 below) three revisions earlier.
     §10 now states 70 as the current count and keeps 46 only as clearly
     labeled Rev2-era historical information.
  3. **Checkpoint-comment precision corrected**: two of the six
     probe-hash checkpoint comments (checkpoints 1 and 2, in both the
     runbook script and `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §9)
     claimed "no other operation sits between" a check and its guarded
     step, when in fact a non-mutating path-construction line
     (checkpoint 1) or an `Assert-OrdinaryFile` guard call (checkpoint 2)
     sat between them. Neither intervening operation can modify or replace
     the hashed file, so there was never a correctness gap — only a
     documentation-precision gap, of the exact kind rev5's own item 6
     existed to prevent. Both comments now state precisely what they can
     guarantee: no operation *capable of modifying or replacing the hashed
     probe* sits between the check and its guarded step. The non-mutating
     operations themselves were left in place, unrearranged, per this
     mission's authorization.
  4. No new tests were required for these two fixes — they are
     documentation-only corrections; the existing 70 pytest cases are
     re-confirmed unaffected by a Python-side identifier-only change (the
     same pattern as rev5's item 7).


- **rev7 (this revision — current unstaged correction candidate)**:
  1. The single authorized Rev6 non-contact preflight stopped before evidence
     creation with a Python `-c` `NameError`. A later exact-host compatibility
     probe did not reproduce that one-time error, so Rev7 records the failure
     without asserting an unproved deterministic cause.
  2. The same compatibility probe established a separate deterministic Rev6
     blocker: the target Windows PowerShell 5.1 / CLR 4 runtime exposes no
     `ProcessStartInfo.ArgumentList`, but Rev6 used that property for the
     manifest-validator subprocess.
  3. Every Python launch now uses one tested Windows CRT argv encoder through
     `ProcessStartInfo.Arguments`. The Python identity program contains no
     literal quote character.
  4. The exact single-read manifest bytes are encoded as canonical Base64 and
     passed through argv to a new `validate-manifest-base64` command. Strict
     decoding feeds the unchanged bytes into the same duplicate-key-safe
     validator. The stdin validator remains available for offline use.
  5. The eventual snapshot process uses the same native-process helper; the
     legacy `Start-Process -ArgumentList` launch is removed.
  6. Target-host evidence passed on Windows PowerShell 5.1.26100.8875,
     CLR 4.0.30319.42000, Python 3.11: quote-free identity, difficult argv
     round-trip, Base64 manifest-byte transport, and the real validator.
     No preflight, Resolve scripting contact, or SQLite access occurred.
  7. Eight focused tests are added (two Base64 CLI tests, five static runbook
     guards, and one native Windows PowerShell process-boundary test), bringing
     the focused total from 70 to 78.

### Rev7 line-ending determinism hardening

The four authorization-manifest-bound artifacts are now pinned to `text eol=lf`
in the repository root `.gitattributes`:

- `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md`
- `scripts/phase14_live_snapshot_runbook.ps1`
- `scripts/phase14_resolve_context_snapshot.py`
- `tests/unit/test_phase14_resolve_context_snapshot.py`

This closes the exact-byte reproducibility gap exposed by the target Windows
Git configuration (`core.autocrlf=true`): Git may no longer check these four
files out as CRLF and thereby silently change the SHA-256-bound bytes. The
working-tree and index EOL states are verified as LF, and `git check-attr`
must report `text: set` and `eol: lf` for all four paths.

## 1. Scope

This revision — rev7, the current source — touches exactly eight repository paths, all unstaged/untracked:

```text
.gitattributes                                         (new; untracked)
docs/CHANGELOG.md                                      (modified)
docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md          (modified)
docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md               (modified — this file)
docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md                 (modified)
scripts/phase14_resolve_context_snapshot.py            (modified)
scripts/phase14_live_snapshot_runbook.ps1              (modified)
tests/unit/test_phase14_resolve_context_snapshot.py    (modified)
```

Seven paths already existed; `.gitattributes` is the single new repository
path added by the authorized Rev7 LF-determinism hardening. No dependency is
added. The existing single focused test artifact remains one of the four
authorization-manifest-bound exact-byte artifacts.

## 2. What changed and why (source)

`EXECUTION_REVISION_ID` is now `phase14.1-live-interlock-construction-rev7`.
Rev7 adds the `validate-manifest-base64` non-contact CLI and replaces the
PowerShell runbook's three Python launch shapes with one tested Windows CRT
argv encoder. The existing execution interlock semantics are unchanged:
missing, malformed, or mismatched authorization still stops before Resolve
import or connection, and only an exact `phase14.1-live-interlock-construction-rev7` match can reach the
snapshot boundary. The Base64 validator strictly decodes argv text and sends
the exact bytes to `validate_authorization_manifest_bytes()`; it does not
import or contact Resolve and does not access SQLite.

`write_json_no_overwrite()` (unchanged since rev2) creates its temporary
file with `tempfile.mkstemp(dir=path.parent)`, which asks the OS for an
exclusively created file rather than assuming a hand-picked UUID name is
free. Every step after that — write, fsync, publish via `os.link()`,
temp-file removal — is wrapped so a failure raises a specific
`SnapshotError` code (`output_temp_create_failed`, `output_write_failed`,
`output_publish_failed`, `output_temp_cleanup_failed`) with only an
exception type name and a `published` boolean in its details, never an
authorization value. See §5.10 of the contract for the exact sequence.

New in rev3: `connect_resolve_read_only()` no longer lets exceptions from
importing `DaVinciResolveScript` or calling `scriptapp("Resolve")` escape as
raw tracebacks. An exception from the importer is now
`resolve_module_import_failed`; an exception from the `scriptapp()` call is
now `resolve_scriptapp_call_failed`; a falsy (but non-raising) result is
still `resolve_connection_failed`, unchanged. All three carry only a safe
`error_type` in their details.

New in rev4: `validate_authorization_manifest_bytes()` and the
`validate-manifest` CLI subcommand (§14.4 of the contract lists its error
codes). This is duplicate-key-safe, exact-schema JSON validation, living in
the probe module specifically so it is directly unit-testable (13 tests
exercise the function itself) rather than existing only as an untestable
fragment embedded in the PowerShell runbook. It never imports or contacts
Resolve and never touches SQLite, matching the safety posture of `compare`
and `--print-sha256`.

The rest of rev4's changes are entirely in the runbook
(`scripts/phase14_live_snapshot_runbook.ps1`) and documentation — see §0
above and `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` for the full detail. The
runbook is not one of the hash-tracked *source* files in the sense of being
imported and unit-tested the way the probe is, but it is one of the six
files under review, and its rev3 rewrite is the majority of this revision's
actual content.

## 3. Explicit non-claims

Unchanged from rev1: this interlock is **not** authentication, **not** a
credential, and **not** a security control against an adversary who can
already edit this file. Its purpose is to prevent *accidental* live contact.

## 4. Preserved mutation boundaries (proof)

Unchanged from rev1 and re-verified against rev2: no `sqlite3` import or DB
path reference (test + manual grep, zero matches); no prohibited Resolve
method called (AST test, unchanged, passes); getter allowlist and prohibited
set remain disjoint (unchanged); no project/timeline load or switch; no
render queue mutation, render start/stop, media import, or settings/marker/
track/clip/preset mutation; queue activity, active rendering, duplicate
timeline, identity mismatch, and pre/post drift all still fail closed. None
of rev2's changes touch `collect_snapshot()`, `enforce_safe_guard_state()`,
`select_expected_timeline()`, `READ_ONLY_RESOLVE_METHODS`, or
`PROHIBITED_RESOLVE_METHODS` — only the interlock and the output writer
changed.

## 5. Sensitive-evidence handling

Unchanged reasoning from rev1 (`GetClipProperty()` may expose absolute local
paths; treat snapshot JSON as sensitive), with one correction: the runbook
no longer stores evidence under the repository (`redline-os\phase14_evidence\`)
at all — see §6 point 6 above and `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md`
§5 for the corrected external evidence-root design. The prior "open item"
about a `.gitignore` entry for that path is now moot, since evidence is no
longer written anywhere under the repository working tree.

## 6. Test inventory

Total: **78 focused tests** in `tests/unit/test_phase14_resolve_context_snapshot.py`. Rev7 renames the revision assertion to `test_execution_revision_id_is_rev7` and adds eight tests: two Base64 manifest-CLI cases, five static PowerShell runbook guards, and one real Windows PowerShell-to-Python argv/validator round-trip. The native test skips only when Windows PowerShell is unavailable; it runs on the target Windows host.

Breakdown (corrected — the prior revision of this document contained an
arithmetically impossible "34 unchanged from 23" claim; the actual figures
are below):

- **21 tests unchanged** from the Phase 14 published commit's original
  23-test suite.
- **2 of the original 23 updated in place** (not new, not unchanged — the
  error taxonomy they assert against changed by design):
  - `test_module_import_does_not_import_resolve_module` — no longer asserts
    the retired `SNAPSHOT_EXECUTION_ENABLED`.
  - `test_snapshot_cli_stops_before_connection` → renamed
    `test_snapshot_cli_stops_before_connection_when_authorization_missing`.
  - (21 unchanged + 2 updated = all 23 original scenarios still covered.)
- **13 tests added in the first Phase 14.1 construction pass** (interlock
  and initial writer coverage).
- **10 tests added in this rev2 corrections pass**: three whitespace-
  authorization tests, forced temp-name collision, generic temp-creation
  failure, write/fsync failure, generic publish failure, publication race,
  cleanup-failure-surfaced, and `main()`'s exit classification for a
  controlled output-write failure.
- **1 existing test renamed and reclassified, not newly added**:
  `test_temp_file_removed_after_controlled_write_failure` (rev1) is now
  `test_serialization_failure_occurs_before_any_disk_write`. Its rev1 name
  and framing overclaimed what it proved: a `json.dumps()` failure happens
  *before* `validate_output_path()` or `tempfile.mkstemp()` are ever
  reached, so no temp file exists to be "removed" in that scenario — there
  is nothing to clean up. Real post-creation cleanup is proven by the three
  new tests named directly below.

- **8 tests added in this rev3 corrections pass**: three pattern-boundary
  rejections (trailing `.`, `_`, `-`), two pattern boundary-length tests
  (minimum two characters accepted, single character rejected), and three
  structured Resolve-connection-failure tests (`resolve_module_import_failed`,
  `resolve_scriptapp_call_failed`, and the pre-existing falsy-handle
  `resolve_connection_failed` path re-confirmed under the new structure).

- **16 tests added in this rev4 corrections pass**: 1 revision-identifier
  check (`test_execution_revision_id_is_rev4`) plus 13 manifest-validator
  tests exercising `validate_authorization_manifest_bytes()` directly
  (valid manifest accepted, duplicate top-level key, duplicate nested
  context key, unexpected top-level field, missing top-level field,
  unexpected context field, unexpected context name, string
  `schema_version`, boolean `schema_version`, non-string field, invalid
  UTF-8, non-object root, and an error-code-never-leaks-field-values check)
  plus 2 tests exercising the `validate-manifest` CLI subcommand end to end
  (valid manifest accepted, duplicate key rejected), all of which assert no
  `DaVinciResolveScript` import occurs.

21 + 2 + 13 + 10 + 8 + 16 = 70 (Rev6 historical subtotal); + 8 Rev7 tests = 78. ✓

| # | Required coverage (rev2 independent-review corrections mission) | Test |
|---|---|---|
| 1 | Leading-whitespace authorization rejected | `test_authorization_leading_whitespace_is_rejected` |
| 2 | Trailing-whitespace authorization rejected | `test_authorization_trailing_whitespace_is_rejected` |
| 3 | Whitespace-only authorization rejected | `test_authorization_whitespace_only_is_rejected` |
| 4 | Forced temp-name collision cannot overwrite an existing file | `test_forced_temp_name_collision_cannot_overwrite_existing_file` |
| 5 | Generic temp-creation failure is structured | `test_generic_temp_creation_failure_is_structured` |
| 6 | Write or fsync failure is structured, leaves no final output | `test_write_failure_is_structured_and_leaves_no_final_output` |
| 7 | Generic `os.link()` failure is structured, removes temp | `test_publish_failure_is_structured_and_removes_temp` |
| 8 | Publication race returns `output_path_already_exists`, preserves destination | `test_destination_created_during_publication_race_preserves_destination` |
| 9 | Temp cleanup failure surfaced, not swallowed | `test_temp_cleanup_failure_is_surfaced_not_swallowed` |
| 10 | Successful writer leaves exactly one final JSON file | `test_successful_write_produces_exactly_one_final_json_file` (rev1, still valid — writer's external contract unchanged) |
| 11 | `main()` returns documented failure exit classification, not a traceback | `test_main_returns_documented_exit_code_for_output_write_failure` |

(The rev1 requirement table — missing/incorrect/mismatched authorization,
existing-output rejection, directory rejection, offline-compare/`--print-sha256`
independence, AST scan, disjointness, no-SQLite, authorization-not-in-evidence,
error-does-not-expose-authorization — is unchanged and still satisfied by the
same rev1 tests; not reproduced here to avoid duplicating
the original mapping table, which remains accurate.)

| # | Required coverage (rev3 independent-review corrections mission) | Test |
|---|---|---|
| 12 | Identifier ending in `.` is rejected | `test_revision_id_pattern_rejects_trailing_dot` |
| 13 | Identifier ending in `_` is rejected | `test_revision_id_pattern_rejects_trailing_underscore` |
| 14 | Identifier ending in `-` is rejected | `test_revision_id_pattern_rejects_trailing_hyphen` |
| 15 | Minimum 2-character identifier accepted | `test_revision_id_pattern_accepts_minimum_two_characters` |
| 16 | Single-character identifier rejected | `test_revision_id_pattern_rejects_single_character` |
| 17 | Importer exception is `resolve_module_import_failed` | `test_resolve_module_import_failure_is_structured` |
| 18 | `scriptapp()` exception is `resolve_scriptapp_call_failed` | `test_resolve_scriptapp_call_failure_is_structured` |
| 19 | Falsy handle (no exception) is still `resolve_connection_failed` | `test_resolve_falsy_handle_still_reports_connection_failed` |

| # | Required coverage (rev4 independent-review corrections mission) | Test |
|---|---|---|
| 20 | Rev4 identifier is set and well-formed | `test_execution_revision_id_is_rev4` |
| 21 | Duplicate top-level manifest key rejected | `test_manifest_duplicate_top_level_key_is_rejected` |
| 22 | Duplicate nested context key rejected | `test_manifest_duplicate_nested_context_key_is_rejected` |
| 23 | Unexpected top-level field rejected | `test_manifest_unexpected_top_level_field_is_rejected` |
| 24 | Missing top-level field rejected | `test_manifest_missing_top_level_field_is_rejected` |
| 25 | Unexpected context field rejected | `test_manifest_unexpected_context_field_is_rejected` |
| 26 | Unexpected context name rejected | `test_manifest_unexpected_context_name_is_rejected` |
| 27 | String `"1"` schema version rejected | `test_manifest_string_schema_version_is_rejected` |
| 28 | Boolean schema version rejected | `test_manifest_boolean_schema_version_is_rejected` |
| 29 | Non-string field rejected | `test_manifest_non_string_field_is_rejected` |
| 30 | Invalid UTF-8 rejected | `test_manifest_invalid_utf8_is_rejected` |
| 31 | Non-object root rejected | `test_manifest_root_not_object_is_rejected` |
| 32 | Valid manifest bytes accepted | `test_valid_manifest_bytes_are_accepted` |
| 33 | Error code never contains a rejected field's value | `test_manifest_error_code_never_contains_field_values` |
| 34 | `validate-manifest` CLI accepts a valid manifest, no Resolve import | `test_validate_manifest_cli_accepts_valid_manifest_without_resolve_import` |
| 35 | `validate-manifest` CLI rejects a duplicate key, no Resolve import | `test_validate_manifest_cli_rejects_duplicate_key_without_resolve_import` |

Items 8 ("Successful `-PreflightOnly` path contains no snapshot launch"), 9
("Preflight mode contains no `Read-Host` path"), 10 ("Failed JSON-property
validation is persisted as `false`"), 11 ("Missing stdout/stderr inspection
is persisted as `false`"), 12 ("Manifest source bytes and evidence-copy
bytes are identical"), 13 ("Every local Git command is rooted with `git -C
$repo`"), and 14 ("Required file checks reject reparse points") from the
rev4 mission are PowerShell runbook behaviors, not importable Python, and
so are covered by **static review** of
`scripts/phase14_live_snapshot_runbook.ps1` rather than pytest:

| Item | Static-review finding |
|---|---|
| 8 | `return` (ending the `-PreflightOnly` branch) appears at the line immediately before the branch's own launch logic; grep confirms `Start-Process -FilePath $pyPath` appears exactly once in the file, inside the live-capture branch, after that `return`. |
| 9 | grep confirms the sole `Read-Host` call site is textually after the `-PreflightOnly` branch's `return` statement (line 543 vs. 533 in the reviewed revision), so the preflight code path cannot reach it. |
| 10, 11 | `Invoke-ValidationCheck` wraps every recorded check's scriptblock in `try`/`catch`; a `Get-Content`/`ConvertFrom-Json`/`Get-Item` failure inside `json_parses`, `success_stdout_empty`, or `success_stderr_empty` is caught, recorded `false` with a safe exception-type name, persisted, and re-thrown, rather than left unrecorded. |
| 12 | The evidence copy is produced by `[System.IO.File]::WriteAllBytes($copiedManifestPath, $manifestBytes)` — the exact in-memory byte array that was hashed and validated, not a fresh read of `$AuthorizationManifest` and not a re-serialization of the parsed object — then rehashed and compared to the original hash as an explicit equality check. |
| 13 | grep confirms every `git` invocation in the file is of the form `git -C $repo ...`; none omit `-C $repo`. |
| 14 | `Assert-OrdinaryFile` and `Assert-OrdinaryDirectoryNotReparsePoint` both check `$item.Attributes -band [System.IO.FileAttributes]::ReparsePoint` and are applied to every path listed in the rev4 mission's item 7. |

## 7. Corrections applied to documentation in this revision

The independent review found these inaccuracies in the rev1 documents;
each is corrected in place in this revision, not left standing alongside a
correction:

1. **Contract §6** claimed the connection function was "unreachable ...
   because the hard-disable check executes first" — true for the published
   `7e37d5f` commit, false for Phase 14.1 (no such constant exists). Fixed
   to name `enforce_execution_interlock()` as the actual gate.
2. **Contract §7** claimed "No failure triggers cleanup because the
   collector performs no authorized live mutation" — true for Resolve
   collection, but rev1's own output writer already had cleanup logic this
   sentence contradicted. Fixed to scope the claim to Resolve collection
   and cross-reference the writer's actual (attempted, not unconditionally
   guaranteed) cleanup behavior.
3. **Contract §5.10 point 3** described the temp file as UUID-named via
   `open(..., "w")` — accurate for rev1, not rev2's `tempfile.mkstemp()`.
   Fixed, with the rev1→rev2 change stated explicitly rather than silently
   replaced.
4. **Contract §5.10 point 5** claimed the temp file "is removed in every
   case ... so failure never leaves a stray temp file" — this is the exact
   overclaim the review flagged: an OS-level cleanup failure can prevent
   removal, and rev1's `except OSError: pass` silently discarded that
   information rather than surfacing it. Fixed to state cleanup is
   *attempted*, and a cleanup failure is *itself* raised as
   `output_temp_cleanup_failed`, not silently absorbed.
5. **Contract §10** (mocked validation matrix) still described "hard-disabled
   snapshot CLI stopping before connection" and did not mention any writer
   test. Fixed to describe the interlock and list the writer failure-mode
   coverage.
6. **Contract §11** claimed the bare `snapshot` command "must return
   `live_execution_disabled`" — true only for the published commit. Fixed
   to state the Phase 14.1 behavior (`live_execution_authorization_missing`)
   separately.
7. **This document (rev1)** contained an arithmetically impossible "34
   tests unchanged from the original 23-test suite" statement. Fixed in §6
   above to the actual, checked arithmetic (21 unchanged + 2 updated + 13
   rev1-new + 10 rev2-new = 46).
8. **This document (rev1)** described the changed-file inventory as three
   files (the ones modified from the Phase 14 baseline) plus three new
   files, without stating plainly that a *subsequent* revision — this one
   — modifies all six of those same paths again in place. Fixed in §1 above.
9. **This document (rev1)**'s broad-regression paragraph reported
   `1330 passed, 24 failed, 9 skipped` against "all 1366 collected" without
   the sum matching (1330+24+9 = 1363, not 1366). Corrected in §8 below
   with the exact recount from a fresh run against this revision.
10. **This document (rev1)**'s readiness verdict stated "no known
    corrections are pending" — falsified by this very corrections mission.
    Fixed in §10 below to describe rev2 as the corrected revision and to
    avoid repeating an unfalsifiable "no corrections pending" claim; a
    verdict states what was checked and when, not a permanent guarantee.
11. **`docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §5** described evidence as
    stored inside the repository (`redline-os\phase14_evidence\`) with an
    "open item" about a `.gitignore` entry. Corrected to describe the
    actual external-evidence-root design now in
    `scripts/phase14_live_snapshot_runbook.ps1`, and the `.gitignore` open
    item was removed as moot.

The rev2 independent review found these further inaccuracies, all corrected
in rev3:

12. **Contract §2** still read as present-tense fact that
    `SNAPSHOT_EXECUTION_ENABLED = False` "enforces this boundary" — despite
    §2.1 immediately below it already explaining the constant was retired.
    Fixed by making §2's own paragraph an explicit "Historical note"
    describing only the published `7e37d5f` commit.
13. **Contract §13** ("Repository integration and publication") was still
    written as forward-looking instructions — "this bundle was created
    outside the canonical repository," "a future founder decision is
    required before copying these files into the repository" — for a state
    that no longer exists; the six files are already inside the repository
    working tree. Fixed by marking the original paragraph an explicit
    historical quote and adding a "Current state" paragraph describing
    reality, including that the previously suggested commit subject was in
    fact already used for the actual `7e37d5f` commit and a new subject is
    proposed for the eventual Phase 14.1 commit.
14. **Contract §12** claimed "enabling execution requires a source change
    and therefore a new hash," phrased as still pending — but the enabling
    revision (Phase 14.1) already exists as of rev1. Fixed to explain that
    what remains outstanding is the authorization-manifest step (§14), not
    a further source change.
15. **`docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md`** repeated the impossible
    "commit, then insert that same commit's SHA into the committed runbook"
    procedure. Removed outright and replaced with the manifest-based
    sequence (§0 of that document).
16. **The runbook itself** (not documentation, but listed here since the
    review's finding was about a defect, not just wording) used PowerShell's
    default case-insensitive `-eq`/`-ne` for the typed confirmation phrase
    and the execution-authorization check, meaning `confirm-control-snapshot`
    would have passed a gate written as `CONFIRM-CONTROL-SNAPSHOT`. Fixed
    with explicit `-ceq`/`-cne` throughout every authorization-relevant
    comparison.
17. **The runbook itself** never verified its own bytes, never rehashed the
    evidence-directory probe copy beyond the initial copy, re-resolved the
    Python interpreter a second time for version checking instead of reusing
    the once-resolved path, and matched the Resolve version with a
    substring-tolerant regex rather than exact equality. All four fixed —
    see contract §2.2 and runbook doc §3/§5 for the corrected behavior.

## 8. Validation run

```text
Interpreter (verified):    C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe
                            Python 3.11.9 (via `py -3.11`)

python -m py_compile scripts/phase14_resolve_context_snapshot.py
                       tests/unit/test_phase14_resolve_context_snapshot.py     -> OK

py -3.11 -m pytest -q tests/unit/test_phase14_resolve_context_snapshot.py     -> 70 passed

python scripts/phase14_resolve_context_snapshot.py --print-sha256             -> matches manual SHA-256 below

python scripts/phase14_resolve_context_snapshot.py validate-manifest
    < a well-formed manifest                                                  -> exit 0, {"valid": true, ...}
    < a manifest with a duplicate top-level key                               -> exit 2, {"valid": false,
                                                                                   "code": "manifest_duplicate_key"}

powershell [Language.Parser]::ParseFile(...runbook.ps1...)                    -> zero parse errors (not executed)

Rev4 non-contact preflight-path static review                                -> see §6's static-review table
                                                                                   above (items 8-14): no
                                                                                   Read-Host or Start-Process
                                                                                   reachable before the
                                                                                   -PreflightOnly branch's
                                                                                   `return`; every git call
                                                                                   uses `-C $repo`; every
                                                                                   listed path is guarded by
                                                                                   Assert-OrdinaryFile /
                                                                                   Assert-OrdinaryDirectoryNotReparsePoint

git diff --check                                                              -> only CRLF/LF line-ending
                                                                                   normalization warnings
                                                                                   (Windows checkout config);
                                                                                   exit code 0, no real
                                                                                   whitespace errors
git status --short                                                            -> 6 modified, all unstaged
                                                                                   (all ` M`, none staged)
```

Broader regression, `py -3.11 -m pytest -q tests/unit` (full directory):
figures for this revision are reported in the final delivery report rather
than duplicated here, since a fresh count is taken at final validation time
for each revision — treat the final delivery report's count for rev4 as
authoritative. Only the focused Phase 14 suite (this file) is bound into
the review bundle produced for each revision; the full-directory broad
regression's complete raw output is not itself archived into the bundle,
only its summary line and failure classification (each rev's delivery
report states this explicitly). The rev1 figure (1330/24/9, which did not
sum correctly), the rev2 figure (1340/24/9), the rev3 figure (1348/24/9),
and the rev4 figure (1364/24/9) are all superseded; all four shared the
same 24 pre-existing, unrelated `test_cli_*` YAML-path failures — the
failing node IDs were diffed programmatically across every pair of
consecutive revisions, not just counted, and found identical each time —
none in Phase 14.

**Rev6 verification (this pass):** `py -3.11 -m pytest -q tests/unit` ->
`24 failed, 1364 passed, 9 skipped in 213.20s` — the same 1364/24/9 figure
recorded for rev4. (Rev5 deferred its own broad-suite figure to a final
delivery report not present in this repository, so no rev5 node-ID list
exists here to diff byte-for-byte against; this comparison is therefore
against the rev4 figure and the qualitative claim above, not a file-level
diff.) All 24 failures are still exactly the `test_cli_*` files below, the
same root cause previously identified (a Windows-path-backslash /
YAML-escape parsing conflict in a `folder_structure.yaml` test fixture,
unrelated to Phase 14):

```text
test_cli_archive_episode.py::test_main_archive_episode_end_to_end_without_mock_resolve
test_cli_archive_episode.py::test_main_archive_episode_unknown_is_clean_error
test_cli_archive_list.py::test_main_archive_list_end_to_end_without_mock_resolve
test_cli_archive_list.py::test_main_archive_list_shows_archived_episode
test_cli_asset_list.py::test_main_asset_list_end_to_end_without_mock_resolve_or_db_path
test_cli_asset_list.py::test_main_asset_list_empty_is_success
test_cli_asset_verify.py::test_main_asset_verify_no_arguments_uses_default_set
test_cli_asset_verify.py::test_main_asset_verify_with_explicit_ids
test_cli_asset_verify.py::test_main_asset_verify_missing_assets_still_exits_zero
test_cli_episode_assemble.py::test_main_assemble_end_to_end_success
test_cli_episode_assemble.py::test_main_assemble_end_to_end_force_unblocks_failed_episode
test_cli_episode_build_timeline.py::test_main_build_timeline_end_to_end
test_cli_episode_create.py::test_main_episode_create_end_to_end
test_cli_episode_create.py::test_main_episode_create_duplicate_is_clean_error
test_cli_episode_list.py::test_main_episode_list_end_to_end
test_cli_episode_list.py::test_main_episode_list_empty_is_success
test_cli_episode_organize_bins.py::test_main_organize_bins_end_to_end
test_cli_episode_place_clips.py::test_main_place_clips_end_to_end
test_cli_episode_scan_ingest.py::test_main_scan_ingest_end_to_end
test_cli_episode_scan_ingest.py::test_main_scan_ingest_unknown_episode_is_clean_error
test_cli_episode_status.py::test_main_episode_status_end_to_end
test_cli_episode_status.py::test_main_episode_status_unknown_episode_is_clean_error
test_cli_episode_validate_manifest.py::test_main_validate_manifest_end_to_end_success_no_db_no_mock_resolve
test_cli_episode_validate_manifest.py::test_main_validate_manifest_end_to_end_failure
```

Zero of these 24 are in `tests/unit/test_phase14_resolve_context_snapshot.py`;
the focused Phase 14 suite's 70/70 pass is unaffected.

## 9. New artifact SHA-256 values

See the final delivery report for this mission (values were finalized only
after all six files reached their corrected state, to avoid publishing a
hash for a file that was edited again afterward). `EXECUTION_REVISION_ID`
embedded in this revision: `phase14.1-live-interlock-construction-rev6`.

## 10. Findings

**Critical:** none found in the rev1, rev2, rev3, rev4, rev5, or rev6 pass.

**Important (found in the rev5 staged-diff review, resolved in rev6):**
- Contract §10 stated "46 tests total ... as of Phase 14.1 rev2" with no
  historical marking, even though the document had by then been revised
  through rev5 and the actual count had grown to 70 three revisions
  earlier (§6 above) — resolved by stating the current count (70) and
  retaining 46 only as clearly labeled Rev2-era historical information.

**Minor (found in the rev5 staged-diff review, resolved in rev6):**
- Two of the six probe-hash checkpoint comments (checkpoints 1 and 2, in
  both the runbook script and `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §9)
  claimed "no other operation sits between" a check and its guarded step,
  when a non-mutating path-construction line or an `Assert-OrdinaryFile`
  guard call actually sat between them — resolved by restating each claim
  as what it can actually guarantee: no operation capable of modifying or
  replacing the hashed probe sits between the check and its guarded step.

**Important (found in the rev4 staged-diff review, resolved in rev5):**
- `Assert-RepoCheckpoint` passed `git -C $repo rev-parse --show-toplevel`'s
  output into `Resolve-Path` before checking `$LASTEXITCODE`, so a failed
  Git call surfaced a confusing `Resolve-Path` exception instead of the
  intended clear message — resolved by checking every Git exit code before
  touching its output.
- The post-confirmation probe-hash checks were bare `if (...) { throw ... }`
  statements outside `Invoke-ValidationCheck`, so their failures did not
  populate `execution_validation.json`'s per-check record the way the other
  tracked checks did — resolved with six real, individually reachable,
  fully wrapped checkpoints.
- A check's own evaluation throwing inside `Invoke-ValidationCheck` was
  re-raised as a new `throw "STOP: ..."`, replacing the original exception
  object, so `runbook_failure.json` recorded a generic `RuntimeException`
  instead of the real type — resolved with a bare `throw` that preserves
  the original exception.

**Minor (found in the rev4 staged-diff review, resolved in rev5):**
- Two adjacent post-confirmation checks hashed the same file with no
  intervening state change — resolved; pre-confirmation and pre-launch are
  now genuinely distinct checkpoints separated by the typed confirmation.
- Documentation described a rehash point as happening "immediately before"
  a copy operation when the actual check was positioned earlier in the
  flow, with unrelated operations in between — resolved; no document now
  makes an "immediately before" claim the code doesn't back up.

**Important (rev3, resolved in rev4):**
- The runbook had no non-contact preflight mode; every check could only be
  exercised by running all the way up to (and risking) the typed
  confirmation — resolved with `-PreflightOnly`.
- Manifest validation relied on PowerShell's `ConvertFrom-Json`, which
  silently resolves a duplicate JSON object key to the last value at any
  depth — resolved by moving validation into the probe as
  duplicate-key-safe, exact-schema, directly unit-tested Python.
- The manifest was read from disk more than once across hashing, parsing,
  and archiving, with no guarantee all three reads observed identical bytes
  — resolved: one read, reused for the hash, the validator's stdin, and the
  evidence copy.
- Validation checks were plain boolean expressions with no exception
  handling around their own evaluation, so a check that itself threw (a bad
  read, a parse failure, a missing property) could crash the script without
  ever updating the validation file — resolved via `Invoke-ValidationCheck`
  and a top-level `runbook_failure.json` safety net.
- Every local Git command relied on the shell's current working directory
  — resolved with `git -C $repo` throughout.
- No path used by the runbook was checked against being a reparse point
  (symlink/junction) — resolved with `Assert-OrdinaryFile` /
  `Assert-OrdinaryDirectoryNotReparsePoint`, applied everywhere the rev4
  mission specified.
- Contract §14's subsections were still numbered §15.1–§15.3 after the
  section itself was renumbered to §14 — resolved.
- This document's rev2 and rev3 history entries were both still labeled
  "(this revision)" after being superseded — resolved; only the current
  revision is ever labeled that way now.

**Important (rev2, resolved in rev3):**
- The runbook embedded a repository commit inside itself via a
  self-referential placeholder that could never be correctly filled in —
  resolved by removing the embedded commit and introducing the external
  authorization manifest (contract §14).
- The runbook never verified its own executing bytes, so a modified copy
  run from outside the repository could pass every other check — resolved
  via `$PSCommandPath` self-hash binding against the manifest's
  `runbook_sha256` (§3 above, runbook doc §3.2).
- Typed confirmation and execution-authorization comparisons were
  case-insensitive by way of PowerShell's default `-eq`/`-ne` — resolved
  with explicit `-ceq`/`-cne` throughout.
- Python version verification re-resolved the interpreter via a second
  `py -3.11 --version` call instead of using the already-resolved path —
  resolved.
- Resolve version matching used substring-tolerant regex matching —
  resolved with exact string comparison against the manifest's
  `resolve_product_version`.
- Repository and remote identity checks did not explicitly verify the
  canonical repository root or origin URL — resolved.
- The evidence-directory probe copy was rehashed at only two points —
  resolved, now six (runbook doc §5).
- A failed validation check skipped writing `execution_validation.json`
  entirely, so a failure's evidence directory recorded nothing about which
  checks had passed — resolved; the file is now written after every
  individual check.
- A process-launch failure was not itself a structured, recorded outcome —
  resolved.
- Evidence hashing covered only the probe copy, not the runbook, contract,
  or manifest copies — resolved, all four now hashed and verified.
- `EXECUTION_REVISION_ID_PATTERN` only constrained the identifier's first
  character — resolved, both endpoints now required alphanumeric.
- `connect_resolve_read_only()` let import/connection exceptions escape as
  raw tracebacks — resolved with two new structured error codes.
- Several contract sections remained stale present-tense descriptions of
  earlier construction states — resolved (§7 above).

**Important (rev1, resolved in rev2):**
- `.strip()` normalization in the interlock could have accepted a padded
  authorization value — resolved (§2 above).
- The UUID-plus-`open()` temp file had no OS-enforced exclusivity — resolved
  (§2, §5.10 of the contract).
- Filesystem failures during output writing were unstructured and could
  silently swallow a cleanup error — resolved (§2, contract §7).
- The runbook evidence root lived inside the repository — resolved (see
  `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md`).
- The runbook re-resolved the Python interpreter at execution time and ran
  the mutable repository path rather than a hashed, evidence-directory copy
  — resolved (see `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §4).
- A nonzero probe exit produced a bare `return`, not a nonzero script exit —
  resolved.
- Several rev1 documentation statements no longer matched the source they
  described — resolved (§7 above).

**Minor (carried forward from rev1, still applicable):**
- `os.link()`-based publication assumes same-volume/hardlink-capable
  filesystem — true for the local evidence directory used here; would need
  a note if evidence were ever redirected to a network share.
- `validate_output_path()`'s missing-parent-directory policy remains
  fail-closed by design (operator must create the directory first); the
  runbook does this as an explicit, logged, create-only step.

**Minor (new in rev2):**
- When both an in-flight write/publish error *and* a cleanup failure occur
  in the same call, Python's standard `finally`-supersedes-`try` exception
  behavior means the cleanup error (`output_temp_cleanup_failed`) becomes
  the actively propagating exception, with the original error chained via
  `__context__` rather than being the primary reported code. This is
  standard, transparent Python behavior (visible in any traceback, not
  hidden), not a custom suppression mechanism, but a caller inspecting only
  `error.code` and not the exception chain would see the cleanup code, not
  the original one. Acceptable for this mission's scope; worth a note if a
  future caller needs to distinguish the two failure causes programmatically.

## 11. Readiness verdict

**Ready for independent source review.**

This is a status of what has been checked as of rev6, not a permanent
guarantee that no further correction will ever be found — the rev1 through
rev5 versions of this document each asserted something close to a
permanent guarantee, and each was subsequently disproved by the next round
of independent review (rev5's own staged-diff review being the most recent
example: a genuine, independently-run review found one Important and one
Minor finding — both documentation-only — in an artifact this document had
called ready). This document does not repeat that framing a sixth time,
and continues to label only the current revision "(this revision)"
anywhere in §0 — the same discipline that caught two further stale
"current" mislabels in the contract during the rev5 pass (§2.2, §13),
beyond the two findings the rev4 review explicitly named, which is itself
evidence for why the discipline matters rather than a reason to relax it.
Ready for Paul, or a separate independent reviewer, to read the six files
directly, with particular attention to
`scripts/phase14_live_snapshot_runbook.ps1`'s six hash checkpoints and the
`Invoke-ValidationCheck` exception-preservation change. Not authorized for
live use, which still requires the separate founder-authorization mission
described in the contract's §12 and §14 — and, as of rev6, an authorization
manifest that does not yet exist.

Six rounds of construction and independent review have now occurred on
this artifact — including two full staged-diff reviews of real Git blob
content (rev4's and rev5's) — with no manifest ever generated and no
commit ever authorized. Worth naming plainly rather than leaving implicit:
every check this document, the contract, and the runbook describe remains
unexercised against a real authorization manifest, because none has
existed at any point across rev1–rev6. The preflight mode added in rev4
was unchanged in rev5 except for its checkpoint tracking, and is
unchanged again in rev6, whose only corrections are documentation-only; it
is designed to be the first thing run once a real manifest exists,
specifically so that gap can be closed without risking Resolve contact.

**Agents advise. Paul decides.**
