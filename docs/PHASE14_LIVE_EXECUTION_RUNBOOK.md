# Phase 14.1 Live Execution Runbook (Rev8 proposed; not authorized or run) — rev8

Status: **Rev8 proposed. Not authorized. Not executed. Rev7 was published at `bb80516e10e3a8164ff470b21a52e8a9f2051020`; no Rev8 preflight occurred, no Resolve scripting contact occurred, no Phase 14 SQLite access occurred, and no snapshot execution occurred during Rev8 construction. Rev8 is itself an unstaged construction candidate: the five-file working tree is modified (unstaged) as part of Rev8 authoring, not pristine, and was not committed during Rev8 construction.**
Companion script: `scripts/phase14_live_snapshot_runbook.ps1` (also proposed, not executed)
Base commit reviewed against: `bb80516e10e3a8164ff470b21a52e8a9f2051020` ("fix: harden Phase 14.1 Windows process compatibility")
Execution revision identifier this runbook targets: `phase14.1-live-interlock-construction-rev8`

This document and the script it describes exist so that a future,
separately authorized mission has an exact, already-reviewed procedure to
execute rather than improvising one at the moment of live contact. Neither
this document nor the script authorizes anything by existing.

The Rev8 published checkpoint must include the repository-root
`.gitattributes` LF policy for the four authorization-manifest-bound
exact-byte artifacts; otherwise a Windows `core.autocrlf=true` checkout
could change their local bytes and invalidate the reviewed SHA-256
bindings. Rev8 changes only marker normalization in the probe plus the
revision bump above; the native-process helper, Base64 manifest transport,
interlock semantics, and evidence-root design are unchanged from Rev7.

## 0. What's new in rev8

Independent post-Rev7 review found a legitimate DaVinci Resolve
`GetMarkers()` representation — a dict keyed by numeric frame IDs, e.g.
`{12: {...}, 48: {...}}` — that the generic `normalize_json_value` does
not and must not accept (it rejects all non-string mapping keys as
fail-closed policy). Rev7 therefore recorded marker data only as an
`error` observation, discarding the representation.

Rev8 adds a narrow marker-specific normalizer (`normalize_markers`) and
`observe_markers` that convert a frame-ID-keyed marker dict into a
deterministic, frame-sorted JSON array of `{"frame": <int|float>, ...fields}`
sorted by frame id. The generic `normalize_json_value` is NOT broadened: int
keys on a plain dict still raise
`UnsupportedEvidenceType("non-string evidence key ...: int")`.
Malformed marker representations (non-dict outer, non-frame-id keys, bool
keys, NaN/infinity keys, negative numeric keys, arbitrary string keys,
non-dict values, duplicate frames, and reserved `frame` payload keys) fail
closed as `status="error"` observations, never silently coerced.

Marker frame IDs are accepted as numeric only: non-negative int keys and
finite non-negative float keys (including the documented Resolve representation
`{96.0: {'color': 'Green', 'duration': 1.0, 'note': '', 'name': 'Marker 1', 'customData': ''}}`)
are accepted; integral floats such as `96.0` normalize to the canonical
integer `96`, while genuinely fractional finite values are preserved without
truncation. Not all float marker keys are malformed — non-finite
(NaN, ±infinity), negative, and bool keys are rejected, however.

## 0.1 What was new in rev7 (historical — published at `bb80516e10e3a8164ff470b21a52e8a9f2051020`; superseded by rev8)

The published Rev6 runbook received one authorized non-contact preflight
invocation. It stopped before evidence-directory creation with a Python
`-c` `NameError`; no Resolve scripting contact, SQLite access, snapshot,
or repository mutation occurred. A later exact-host compatibility probe did
not reproduce that one-time `NameError`, so Rev7 does not overclaim its
cause.

That compatibility probe did establish a separate deterministic Rev6
incompatibility: the target Windows PowerShell 5.1 / CLR 4 runtime has no
`ProcessStartInfo.ArgumentList`, which Rev6 used for the manifest validator.
Rev7 therefore replaces every Python process boundary with one Windows CRT
argv encoder through `ProcessStartInfo.Arguments`:

- `py.exe` and Python identity resolution use the same helper;
- the identity `python -c` program contains no literal quote character;
- the exact single-read manifest bytes are transported as canonical Base64
  to the probe's new `validate-manifest-base64` command and strictly decoded;
- the eventual snapshot process uses the same helper instead of
  `Start-Process -ArgumentList`.

Native compatibility evidence passed on Windows PowerShell 5.1.26100.8875,
CLR 4.0.30319.42000, and Python 3.11: quote-free identity, difficult argv
round-trip, exact Base64 byte transport, and the real manifest validator all
passed. That compatibility probe did not run Phase 14 preflight, import the
Resolve scripting bridge, contact Resolve, or access SQLite.

## 0.1 What was new in rev6 (historical — published; superseded by rev7)

Rev5 was constructed and staged, then put through a second, independent
read-only staged-diff review. That review found one Important finding (a
stale test-count claim in `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md`
§10, which still said "46 tests" after the suite had grown to 70) and one
Minor finding (two of the six probe-hash checkpoint entries in §9 below
claimed "no other operation sits between" a check and its guarded step,
when a non-mutating path-construction or file-guard call actually sat
between them). The staged candidate was rejected for commit consideration;
the six files were unstaged without discarding content; no commit or
publication occurred. Rev6 fixes both:

- `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md` §10 now states the
  current, verified test count (70) and keeps the prior 46-test figure only
  as clearly labeled Rev2-era historical information.
- §9's checkpoint table below now states precisely what each positioning
  claim can actually guarantee — that no operation capable of modifying or
  replacing the hashed probe file sits between the check and its guarded
  step — rather than the broader "no other operation sits between" claim.
  The non-mutating path-construction and file-guard calls themselves are
  unchanged; only the documentation's claim about them was corrected.

## 0.2 What was new in rev5 (historical — superseded by rev6)

Rev4 was constructed and staged for a read-only staged-diff review (hashing
the actual Git blobs in the index, not just the working tree). That review
found three Important and two Minor findings, all in this script. The
staged candidate was rejected for commit consideration; the six files were
unstaged without discarding content; no commit or publication occurred.
Rev5 fixed all five:

- `Assert-RepoCheckpoint` no longer passes Git's output into `Resolve-Path`
  before checking `$LASTEXITCODE` — every Git call's exit code is checked
  first, before its output is touched by anything that could itself throw,
  with static failure messages that don't depend on what Git printed (§5).
- Six real, individually reachable probe-hash checkpoints replace the
  previous mix of one early general check and a pair of bare, literally
  duplicate post-confirmation checks (§9).
- `Invoke-ValidationCheck`'s catch block now preserves the original
  exception's identity with a bare `throw` instead of manufacturing a new
  `throw "STOP: ..."` (§6).
- The redundant duplicate hash check is gone; pre-confirmation and
  pre-launch are now genuinely distinct checkpoints separated by the typed
  confirmation itself.
- No claim in this document says a check happens "immediately before" a
  step unless the code is actually placed immediately before it.

## 1. Preconditions before this may ever run

1. The Phase 14.1 rev8 correction candidate (the five repository paths
   under the approved construction/hardening scope) has been independently
   reviewed, committed, and published.
2. An authorization manifest (contract §14) has been generated, hashed, and
   independently reviewed.
3. Founder authorization has been given, bound to that manifest's exact
   SHA-256 — which transitively binds the commit, all four file hashes, the
   execution revision identifier, the Resolve version, and the two
   approved contexts. There is no separate list of things to bind; the
   manifest is the binding.
4. Paul has read the full text of `scripts/phase14_live_snapshot_runbook.ps1`.

## 2. Invocation shape

Live capture:

```powershell
powershell -File scripts\phase14_live_snapshot_runbook.ps1 `
    -Context Control `
    -ExecutionAuthorization "phase14.1-live-interlock-construction-rev8" `
    -AuthorizationManifest "<path to the reviewed manifest JSON>" `
    -ExpectedManifestSha256 "<64-lowercase-hex, provided out of band by the founder authorization>"
```

Preflight (non-contact) — identical invocation plus `-PreflightOnly`:

```powershell
powershell -File scripts\phase14_live_snapshot_runbook.ps1 `
    -Context Control `
    -ExecutionAuthorization "phase14.1-live-interlock-construction-rev8" `
    -AuthorizationManifest "<path to the reviewed manifest JSON>" `
    -ExpectedManifestSha256 "<64-lowercase-hex>" `
    -PreflightOnly
```

One process, start to finish, never pasted statement-by-statement.
`$ErrorActionPreference = "Stop"` combined with `Set-StrictMode -Version
Latest` aborts the entire remaining script on the first terminating error.

## 3. Preflight mode (`-PreflightOnly`)

Runs every check the live-capture path runs, in the same order, up to —
but never including — the typed confirmation and the Resolve-contacting
process launch:

1. Authorization-manifest hash verification and duplicate-key-safe exact
   schema validation.
2. This runbook's own self-hash verification (`$PSCommandPath` against the
   manifest's `runbook_sha256`), plus the canonical repository copy.
3. Repository, remote, commit, and test/contract artifact hashes (the probe
   hash is checked separately as checkpoints 1-3 of six, §9).
4. The exact Python 3.11 interpreter, resolved once.
5. Resolve's exact product version (read from `Resolve.exe`'s file version
   info — no scripting-module import) and the required
   `RESOLVE_SCRIPT_API`/`RESOLVE_SCRIPT_LIB`/`PYTHONPATH` configuration.
6. A unique **preflight** evidence directory (named distinctly from a live-
   capture evidence directory, so the two are never confused), into which
   the probe, this runbook, the contract, and the manifest are copied and
   each rehashed against its manifest-verified value.

**No `Read-Host` call and no `Start-Process` launch of the snapshot command
exist anywhere on this code path** — the branch ends with a plain `return`
before either would be reached; both are textually below that `return` in
the script. Checkpoints 1-4 of six (§9) are attempted in preflight mode;
checkpoints 5-6 (the pre-launch pair) stay `not_run` in
`execution_validation.json`, because the branch returns before either could
be reached. A successful preflight writes `preflight_result.json` —
including a full snapshot of every tracked validation key's state — and
prints, verbatim:

```text
Resolve contact: false
Snapshot execution: false
Preflight complete: true
```

followed by an explicit per-checkpoint summary (pre-copy/post-copy/
pre-confirmation: attempted; pre-launch: not_run; Read-Host: not called;
probe launch: not called), then packages the preflight evidence directory
into a ZIP, create-only (no `Compress-Archive -Force`), and verifies it
with the same full-read integrity check the live-capture path uses. The
script exits `0` only if every preflight check passed; any single failed
check throws, same as the live-capture path, and the (preflight) evidence
directory is preserved.

A normal, non-preflight invocation is unaffected by any of this and still
requires the exact case-sensitive typed confirmation before Resolve is ever
contacted (§7).

## 4. Single-byte-read manifest binding and Base64 transport

The manifest is still read as raw bytes exactly once
(`[System.IO.File]::ReadAllBytes($AuthorizationManifest)`). Those bytes are
hashed directly, strict-UTF-8-decoded, retained in memory, written verbatim
to the evidence copy, and converted to canonical Base64 for the validator
subprocess. Rev8 passes that ASCII-only Base64 value through the tested
Windows CRT argv encoder to:

```text
python phase14_resolve_context_snapshot.py validate-manifest-base64 <payload>
```

The probe performs strict Base64 decoding and passes the decoded bytes
unchanged to the same duplicate-key-safe exact-schema validator used by the
stdin `validate-manifest` command. The runbook never re-reads or
re-serializes the source manifest. The evidence copy is still produced from
the original in-memory byte array and rehashed against the original digest.

## 5. Reparse-point guarding, working-directory independence, and repository-root ordering

`Assert-OrdinaryFile` (exists, is a file, is not a directory, does not
carry `FileAttributes.ReparsePoint`) is applied to: the authorization
manifest, this script's own executing path (`$PSCommandPath`), the
canonical repository runbook copy, the repository probe/test/contract
files, the resolved Python executable, `Resolve.exe`, and every artifact
copied into the evidence directory. `Assert-OrdinaryDirectoryNotReparsePoint`
is applied to the freshly created evidence directory itself. Every local
Git command is written as `git -C $repo ...`; the repository root is
independently re-verified via `git -C $repo rev-parse --show-toplevel`
against the canonical path, so the script's behavior does not depend on
what directory it happens to be launched from. Unchanged from rev4.

**New in rev5:** `Assert-RepoCheckpoint` used to call `Resolve-Path` on
`git -C $repo rev-parse --show-toplevel`'s raw output before checking
whether that Git call had even succeeded — a failure meant `Resolve-Path`
threw its own exception on empty or garbage input before the intended
"STOP: unable to resolve repository root" message could run. Every
Git-output-consuming step in that function now captures the command's
output and its exit code separately, checks the exit code first, and only
then does anything with the output that could itself throw. Failure
messages are static text, not raw command output.

## 6. Exception-safe validation and top-level failure capture

Every recorded validation check — in both preflight and live-capture mode
— runs inside `Invoke-ValidationCheck`, which wraps the check's own
evaluation in `try`/`catch`. A check that itself throws while running (a
bad file read, a JSON parse failure, a missing property, a hashing error)
is caught, recorded `false` with the failure code and the real exception's
`GetType().FullName`, persisted to `execution_validation.json`, and only
then re-raised — never left to crash the script with a stale or missing
validation file. Separately, a top-level `try`/`catch`, active from the
moment the evidence directory is created, writes `runbook_failure.json` for
any otherwise-unclassified terminating exception before the script exits
nonzero, recording the exception type and message but never the
authorization value or manifest contents.

**New in rev5:** the catch block's re-raise is now a bare `throw`, not
`throw "STOP: ..."`. A bare `throw` inside a `catch` re-raises the exact
exception object currently being handled — so `runbook_failure.json`
(written by the outer handler) now reports the same real exception type
that `execution_validation.json`'s `failure_exception_type` already
recorded, instead of a wrapping `RuntimeException` manufactured from a
string. No bare, unwrapped hash-check `if (...) { throw ... }` remains
anywhere in the script outside this mechanism.

## 7. Confirmation and failure handling (live-capture mode only)

Immediately before the single Resolve-contacting invocation, the script
requires a **case-sensitive** typed confirmation phrase
(`CONFIRM-CONTROL-SNAPSHOT` / `CONFIRM-PRODUCTION-SNAPSHOT` — a lowercase
or mixed-case variant does not pass). After execution:

- **Process fails to start:** `execution_record.json` records
  `processStarted: false` and a safe exception-type name; the
  `exit_code_zero` validation check is recorded `false`; the script exits
  nonzero; no retry is attempted or authorized.
- **Nonzero probe exit:** the same evidence-preservation and nonzero-exit
  behavior applies.
- **Any single failed validation check:** recorded `false` with a
  `failure_code`, and every check after it remains `"not_run"` — never
  silently missing or stuck at a prior value.

## 8. Success-evidence validation (live-capture mode only)

Before classifying a capture as successful or packaging anything, all of
the following are required and recorded via `Invoke-ValidationCheck`:

```text
exit_code_zero
output_exists_as_file
output_hash_computed
json_parses
snapshot_complete_is_true
expected_project_matches
expected_timeline_matches
pre_post_guard_identity_matches
success_stdout_empty
success_stderr_empty
repository_checkpoint_unchanged
repository_probe_hash_unchanged
copied_probe_hash_unchanged
```

(In addition to the six probe-hash checkpoints in §9, which are tracked
separately and run earlier.) Both stdout **and** stderr must be empty for a
successful capture — the probe's own CLI contract never prints to stdout on
a successful `snapshot` invocation. The raw snapshot JSON text is held only
long enough in memory to parse and check the fields above; it is never
printed, on success or failure.

## 9. Six real probe-hash checkpoints

The evidence-directory probe copy (never the mutable repository path) is
hashed against the manifest's `probe_sha256` at six points, each tracked as
its own key in `execution_validation.json`, each reached through
`Invoke-ValidationCheck`:

| # | Key | Positioned |
|---|---|---|
| 1 | `repository_probe_hash_pre_copy` | Checked just before the repository probe file is copied into evidence. One intervening line constructs the destination path string; no operation capable of modifying or replacing the hashed source file sits between this check and the `Copy-Item` call. |
| 2 | `evidence_probe_hash_post_copy` | Checked just after that copy. An intervening `Assert-OrdinaryFile` guard call reads the copy's file attributes but does not modify or replace its bytes. |
| 3 | `repository_probe_hash_pre_confirmation` | After baselines are written, before the branch splits into preflight-or-live-capture — runs in **both** modes. |
| 4 | `evidence_probe_hash_pre_confirmation` | Same position as #3. |
| 5 | `repository_probe_hash_pre_launch` | After the typed confirmation succeeds, checked just before the process launches — live-capture mode only. |
| 6 | `evidence_probe_hash_pre_launch` | Same position as #5. |

Checkpoints 3/4 and 5/6 are genuinely distinct — separated by the typed
confirmation itself, not the same check run twice with nothing in between,
which is what rev4 did for what were then called the "before confirmation"
and "before launch" checks. In `-PreflightOnly` mode, checkpoints 1-4 are
attempted and 5-6 stay `not_run`, because that branch returns before either
could be reached. Any single mismatch at any checkpoint stops the run.

## 10. Evidence packaging

Create-only (no `Compress-Archive -Force`); a pre-existing ZIP at the
computed path stops the run. After creation, a full-read integrity check
runs over every ZIP entry via .NET's `System.IO.Compression.ZipFile`,
reporting source-file count, ZIP entry count, ZIP size, ZIP SHA-256, and
PASS/FAIL. The evidence directory and ZIP are retained either way; neither
is deleted, and neither is uploaded, by this script, ever. Preflight and
live-capture evidence use distinct directory-name prefixes
(`phase14.1-preflight-evidence-...` vs. `phase14.1-live-evidence-...`) so
the two are never mistaken for one another. Unchanged from rev4.

## 11. Sensitive evidence handling

`GetClipProperty()` can expose absolute local file paths in a real
snapshot. The snapshot JSON body is never printed by this script, in any
mode. Evidence is retained locally only, packaged but never uploaded, and
requires independent review before any interpretation, comparison, or
second capture — a successful capture explicitly does not authorize any of
those, and neither does a successful preflight. Unchanged from rev4.

## 12. Non-claims

`-ExecutionAuthorization` is a deliberate execution interlock, not a
credential and not a security boundary against an adversary who can
already edit the source. The authorization manifest, the self-hash
binding, and the reparse-point guards raise the bar against *accidental*
execution of the wrong bytes, the wrong commit, or a spoofed path; they are
not designed to resist an adversary who already has write access to this
repository or this operator's machine. It stops accidents, not adversaries.
Unchanged from rev4.

**Agents advise. Paul decides.**
