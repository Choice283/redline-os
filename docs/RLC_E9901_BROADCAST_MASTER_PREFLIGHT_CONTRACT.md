# RLC-E9901 Broadcast Master Read-Only Preflight — Contract

Status: **construction revision 5 — independently source-reviewed, live execution not yet authorized or executed**
Verdict: `RLC-E9901 READ-ONLY BROADCAST MASTER PREFLIGHT TOOLING REV5 — SOURCE REVIEW PASSED`

Six frozen candidate files, at the independently approved hashes below. Before publication authorization, the six files remained unstaged/uncommitted and were independently reviewed at the hashes below; none has been modified since independent source review passed, and — whether or not these files have since been staged, committed, or pushed as part of a separately authorized publication step — the hashes below remain the authoritative, unchanging identity of the exact reviewed bytes.

| File | SHA-256 |
|---|---|
| `scripts/rlc_e9901_snapshot_preflight_contract.py` | `1c57b45c15102d3d73d4b723ba2a1c8734f6e92b9eab5d9e44a6d499f2708e89` |
| `scripts/rlc_e9901_module_provenance_check.py` | `29015a44efbd278da14979ba79b10ac765eca7d62e358a18f22ce1a28529dc35` |
| `scripts/rlc_e9901_preflight_assertion.py` | `aa915a9c567919e545c1f966fe8ab3959ec547b680dc32701338313c5d3302df` |
| `tests/unit/test_rlc_e9901_snapshot_preflight_contract.py` | `a9409c2463ffc2484df78e3f2cb13d23f6ec0ccf6948685a2b74255e3912bb68` |
| `tests/unit/test_rlc_e9901_module_provenance_check.py` | `1738a7e99225cf4271db6ea25ffe8b502b670b0db85f859c4cf3ca2aa5a904e0` |
| `tests/unit/test_rlc_e9901_preflight_assertion.py` | `dabcb01ab1a4eaa2cee806dd4b4288e81fa220444540cab05ad6110e311e8cdb` |

The one production dependency this tooling wraps, unmodified throughout every construction revision (Rev1–Rev5) and every independent review pass:

| File | SHA-256 | `EXECUTION_REVISION_ID` |
|---|---|---|
| `scripts/phase14_resolve_context_snapshot.py` (rev8, published, committed at `33b3242`) | `1b600a26dd54fd6625a9100348c32f2ea4decf9cf02407f9a9344a8c1beeb038` | `phase14.1-live-interlock-construction-rev8` |

Governing rule: **Agents advise. Paul decides.**

## 1. Purpose

This tooling answers exactly one question, read-only: for the specific RLC-E9901 episode, does DaVinci Resolve currently report every fact the eventual Broadcast Master render-queue attempt depends on — correct project/timeline identity, an idle render engine, an empty queue, the required render preset, and a non-zero video payload? It does not queue, start, cancel, or delete a render, and it does not itself decide whether Paul should authorize a live Broadcast Master render — it only produces the evidence that decision would be based on.

It exists because the published rev8 collector (`scripts/phase14_resolve_context_snapshot.py`) is a general-purpose, two-context Control/Production comparison probe whose authorization-manifest and PowerShell runbook layer is hard-bound to that comparison shape and to the historical `RLC-E9001` disposable-episode context (see `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md` §14). RLC-E9901's preflight is a single-context inspection with its own render-specific pass/fail criteria the collector was never designed to evaluate. Rather than editing the published, already-reviewed collector — which would itself require a new `EXECUTION_REVISION_ID`, a new SHA-256, and fresh independent review of the collector's own live-contact safety boundary — this tooling wraps it from the outside, unmodified.

## 2. Architecture

```
execution contract  -->  unchanged rev8 collector  -->  exact snapshot bytes  -->  offline assertion layer
(scripts/rlc_e9901_       (scripts/phase14_             (one JSON file,           (scripts/rlc_e9901_
 snapshot_preflight_       resolve_context_               read back and             preflight_assertion.py)
 contract.py)              snapshot.py, byte-             SHA-256'd by the
                           identical since rev8)           execution contract)
```

`run_authorized_rlc_e9901_preflight()` (the one live-capable orchestration function, reachable only through this module's `run-live-preflight` CLI subcommand) performs, strictly in order: the full repository authorization gate; the collector's source-identity check (disk-bytes SHA-256, never an import); the offline checker's source-identity check and load (also hash-verified before being loaded, and loaded only after the repository gate has already passed — see §3); the exact Python 3.11.9 interpreter check; and the absolute/protected/fresh evidence-path check. Only if every one of those passes does it launch the collector's `snapshot` subcommand — exactly once, as an unmodified external subprocess, with `--execution-authorization` bound to the collector's own reviewed `phase14.1-live-interlock-construction-rev8` identifier. It then requires exit code `0`, requires the exact authorized output file to exist, reads and SHA-256s those exact bytes, and hands them to the offline assertion layer for evaluation — never a different file, never re-read from a different path (§13).

A companion `scripts/rlc_e9901_module_provenance_check.py` answers a separate, narrower question relevant only to the future, still-unbuilt `render queue` command (not this preflight): when that command eventually runs with the RLC-E9901 workspace as its process CWD, does `cli`/`redline_core` actually resolve under the canonical repository `src`, or could a stray same-named directory or stale environment silently shadow it? It is included in this tooling's review scope because it shares the same non-Resolve-contacting safety discipline, not because the preflight itself depends on it.

## 3. Live safety boundary

- The construction/static-review process that produced Rev1–Rev5 never itself invoked `run-live-preflight`, `run_authorized_rlc_e9901_preflight()`, or any other path that launches the collector. Every verification performed during construction and review used only the safe subcommands (`verify-checkpoint`, `verify-collector`, `verify-checker`, `verify-python`, `preview-snapshot`) or mocked/monkeypatched unit tests — never a real `subprocess.run` against the collector.
- `run-live-preflight` **is** the reviewed live boundary, by design — it is not a bypass or an oversight. It is simply not authorized for execution by this document, and has not been executed as of Rev5.
- The offline checker (`rlc_e9901_preflight_assertion.py`) is loaded only after `verify_repository_checkpoint()` has already succeeded, by its exact canonical absolute path via `importlib.util.spec_from_file_location()` — never through ordinary `sys.path`-based package resolution, and only after its own disk-bytes SHA-256 is independently verified. A tampered or drifted checker is rejected by that hash check before any of its code executes.
- There is exactly one Resolve-contacting subprocess launch site in the entire tooling — the single `subprocess.run(...)` call inside `run_authorized_rlc_e9901_preflight()` that invokes the collector — and zero retry loops anywhere in the call chain.

## 4. Getter-only nature of the Resolve contact

The unmodified rev8 collector's live contact is restricted to a closed, static allowlist it owns and enforces itself, `READ_ONLY_RESOLVE_METHODS`, covering only: Resolve product/version identity (`GetProductName`, `GetVersion`, `GetVersionString`); project-manager/current-project inspection (`GetProjectManager`, `GetCurrentProject`, `GetProjectListInCurrentFolder`, `GetProjectAttributesInCurrentFolder`); project/timeline enumeration and settings (`GetName`, `GetTimelineCount`, `GetTimelineByIndex`, `GetCurrentTimeline`, `GetMediaPool`, `GetSetting`); render queue/preset/context inspection (`IsRenderingInProgress`, `GetRenderJobList`, `GetRenderPresetList`, `GetRenderPresetNames`, `GetCurrentRenderFormatAndCodec`, `GetCurrentRenderMode`, `GetRenderSettings`); media-pool hierarchy (`GetRootFolder`, `GetSubFolderList`, `GetClipList`); and timeline/item metadata (`GetStartFrame`, `GetEndFrame`, `GetStartTimecode`, `GetTrackCount`, `GetItemListInTrack`, `GetMarkers`, `GetStart`, `GetEnd`, `GetDuration`, `GetLeftOffset`, `GetRightOffset`, `GetSourceStartFrame`, `GetSourceEndFrame`, `GetMediaPoolItem`, `GetUniqueId`, `GetClipEnabled`, `GetMediaId`, `GetClipProperty`). The collector's own accessor-resolution helpers (`_resolve_method()`, `observe_optional()`, `call_required()`) check every dynamically dispatched method name against this set before ever calling `getattr` on a live Resolve object; a name outside the set raises `accessor_not_allowlisted` and is never dispatched.

**The RLC-E9901 execution layer does not import the collector module and does not reference `READ_ONLY_RESOLVE_METHODS` (or any other collector symbol) directly at all.** Instead, it binds the collector by its canonical source path, its exact SHA-256 (computed by reading raw disk bytes only — never by importing or executing the collector), and its `EXECUTION_REVISION_ID`, and then, once every pre-flight check has passed, executes those exact reviewed bytes as the one external subprocess (§13). The getter-only property described above is therefore the collector's own, already-reviewed, already statically-tested behavior — the wrapper neither copies nor re-implements it; it relies on the source-hash/revision binding to guarantee the exact bytes carrying that behavior are what actually runs.

## 5. Prohibited Resolve mutations

The collector's own `PROHIBITED_RESOLVE_METHODS` set — part of the exact reviewed rev8 source this tooling is hash-bound to, statically disjoint from the allowlist above, and enforced by the same accessor-resolution helpers — forbids: `LoadProject`, `CloseProject`, `CreateProject`, `DeleteProject`, `SaveProject`, `SetCurrentTimeline`, `SetCurrentFolder`, `SetSetting`, `SetRenderSettings`, `LoadRenderPreset`, `AddRenderJob`, `DeleteRenderJob`, `DeleteAllRenderJobs`, `StartRendering`, `StopRendering`, `CreateEmptyTimeline`, `CreateTimelineFromClips`, `ImportTimelineFromFile`, `AppendToTimeline`, `AddItemListToMediaPool`, `ImportMedia`, `AddSubFolder`, `DeleteFolders`, `MoveFolders`, `DeleteClips`, `MoveClips`, `AddMarker`, `DeleteMarkerAtFrame`, `DeleteMarkersByColor`, `SetName`, `SetClipProperty`, `SetClipEnabled`.

This is the collector's own existing safety boundary, covered by its own reviewed static tests (asserting the allowlist and prohibited set remain disjoint, and that no prohibited method is ever directly called anywhere in its source). **The RLC-E9901 wrapper does not separately import, copy, or independently re-verify this set at runtime** — its own safety property is narrower and different: the source-hash/`EXECUTION_REVISION_ID` binding in §3 and §6, checked before every launch, which guarantees the exact reviewed bytes carrying this exact prohibition are the bytes that execute, not a drifted or substituted copy.

## 6. Python interpreter requirement

Exactly `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`, version `3.11.9`. `verify_python_interpreter()` spawns the candidate interpreter itself and checks its own reported `sys.executable`/`sys.version_info`, rather than trusting a path string — this is required because DaVinci Resolve's `DaVinciResolveScript` module is not built for the Python 3.13 ABI and crashes with a Windows access violation under it (Mission 39E, `docs/ROADMAP.md`).

## 7. Authorized Resolve version

Exactly `21.0.3.7`, bound as `EXPECTED_RESOLVE_VERSION` in the offline checker — the exact version used for every live Phase 14 verification recorded in the repository (Mission 39E's workstation-configuration verification; the 2026-07-29 live queue verification, `docs/ARCHITECTURE.md` §3.5). `GetVersion()`'s documented `[major, minor, patch, build, suffix]` shape is validated against the repository's own reviewed evidence value, `[21, 0, 3, 7, ""]` (the collector's own Phase 14 test double); a non-empty suffix, a malformed field, or two observed version accessors that disagree with each other all fail closed rather than silently pass, and a future Resolve build carrying a non-empty suffix or a different version requires its own renewed review of this binding, not a silent pass under the current one.

## 8. Expected project and timeline

Project: `RLC-E9901_MASTER`. Timeline: `RLC-E9901_TIMELINE`. Both the collector's own live guard (rejecting the snapshot before it is ever written if the current/target identities do not match) and the offline checker's independent post-hoc checks (actual `project.name`, actual `target_timeline.name`, and both guards' `project_name`/`current_timeline_name`/`target_timeline_name` fields) must all agree with these exact values before the offline checker will report a passing preflight.

## 9. Required render preset

`Redline Broadcast Master` must be observed present (an `"observed"` status, not merely captured data) in the render-preset inventory reported by `GetRenderPresetList()` (or its `GetRenderPresetNames()` fallback).

## 10. Video-payload requirement

The target timeline's video track group's own item-count observation must itself be `"observed"` with a valid non-negative, non-boolean integer equal to the actual number of returned tracks, and the total video `TimelineItem` count summed across those tracks must be strictly greater than zero — an unavailable or malformed count observation is disqualifying, not skipped. This directly encodes the Phase 14 Test D finding (`docs/CHANGELOG.md`, `docs/ROADMAP.md`) that a Control timeline stopped being queue-acceptable the moment its sole video `TimelineItem` was removed, with every other reviewed fact unchanged.

## 11. Render-queue and rendering-state requirements

Rendering must be observed literally `False` (identity-checked, not merely equal to a falsy value) both before and after snapshot capture. The render queue must be observed empty at every level the snapshot exposes: the guard-level `queue_count` (a non-boolean integer zero, not merely `== 0`, which a stray `False` would otherwise satisfy), the project-level `render_queue.count`/`render_queue.items`, and the guard `queue_fingerprint` lists — all mutually cross-checked so guard-level and project-level queue evidence cannot silently disagree.

## 12. Evidence output path requirements

The authorized evidence output path must be absolute; a relative path is rejected before any Resolve-capable subprocess is even constructed. Once resolved, it must not fall inside any protected root: `C:\Users\pj198\Documents\redline-os` (the repository), `C:\Users\pj198\RedlineOSLive\RLC-E9901` (the RLC-E9901 workspace), `C:\Users\pj198\RedlineOSLive\Runtime` (the runtime database directory), or `C:\Users\pj198\RedlineOSLive\Evidence` (the separately-located preserved Redline evidence directory — outside the RLC-E9901 workspace tree, and protected as its own entry). The output file itself must not already exist, and its parent directory must already exist — this tooling never auto-creates an evidence directory. The one canonicalized path that passes these checks is the exact same path used to build the collector command and, later, to read and hash the resulting evidence — never substituted between capture and evaluation.

## 13. One collector subprocess, zero retries

Exactly one `subprocess.run(...)` call launches the collector, whether the attempt succeeds, fails, times out, or the collector cannot even be started. No branch of `run_authorized_rlc_e9901_preflight()` re-attempts that call. No branch deletes, rewrites, or repairs whatever (if anything) exists at the evidence path afterward — a failed attempt's partial or absent evidence is preserved exactly as found. Collector `stdout`/`stderr` are preserved verbatim (via a JSON-safe, lossless `CapturedOutput` representation that never coerces non-UTF-8 partial output through `str(bytes)`) for every outcome, including a subprocess launch failure or timeout, so a human reviewer can independently read the collector's own structured failure classification.

## 14. Snapshot-capture success versus overall preflight success

These are two explicitly distinct, separately reported outcomes. `snapshot_capture_status` answers only "was the JSON document itself complete and well-formed" — required root fields present, `snapshot_complete is True`. `render_preflight_status` is evaluated only when capture is complete, and requires every one of thirteen render-specific checks (§§7–11 above, plus exact identity and no-guard-drift checks) to pass. **A snapshot capture alone can never, by itself, produce an overall preflight PASS** — a capture failure short-circuits to `render_preflight_status = "not_evaluated"` before any render-specific check runs, and a complete-but-failing capture reports `"failed"`, never a silent pass.

## 15. What this tooling does not authorize or do

- **This tooling does not authorize or execute `render queue`.** It performs no Resolve mutation of any kind, queues nothing, and its passing result is evidence for a future, entirely separate authorization decision — not that authorization itself.
- **This tooling does not call `StartRendering()`.** Neither the collector nor this wrapping tooling calls it, references it outside `PROHIBITED_RESOLVE_METHODS`'s own listing, or contains any code path capable of reaching it.

## 16. Interpretation limit

`Redline Broadcast Master` appearing in the observed preset-name inventory proves only that Resolve currently lists a preset by that exact name for the current project. **It does not prove that a future `LoadRenderPreset()` call will accept it, or that a future `AddRenderJob()` call will succeed.** Three controlled live queue attempts against the historical `RLC-E9001_MASTER` project all failed with `AddRenderJob()` returning an empty string despite matching preset/context evidence (`docs/ROADMAP.md`, Missions 39D/39D.2/39D.3) — this preflight closes the specific, evidenced zero-video-payload precondition Phase 14 Test D identified, and nothing more.

## 17. Operator example — NOT AUTHORIZED FOR EXECUTION

The shape of the eventual live invocation, once a separate, explicit founder authorization exists binding the exact repository commit and evidence path:

```
C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe C:\Users\pj198\Documents\redline-os\scripts\rlc_e9901_snapshot_preflight_contract.py run-live-preflight --authorized-commit <COMMIT> --output <FRESH_ABSOLUTE_EVIDENCE_PATH>
```

This example shows the command's shape only. It is **not authorized for execution** by this document, has not been executed as of Rev5, and requires its own separate, explicit founder authorization — naming the exact repository commit and the exact fresh, absolute, unprotected evidence path — before it may be run.

## 18. Revision history

- **Rev1**: initial construction. Rejected by independent review, which found: the reviewed wrapper was not actually the live execution path (the printed future command invoked the collector directly, bypassing the new safety gates entirely); collector code could be imported before its source/hash was verified; the offline checker could false-pass wrong actual project/timeline identities and a wrong Resolve version; and live capture and offline classification were not provenance-bound to the same evidence bytes (nothing prevented substituting a different snapshot file between the two).
- **Rev2**: corrected every Rev1 finding above — one reviewed live entry point (`run-live-preflight`) routed through the wrapper; collector identity verified by disk-bytes SHA-256 before any import; offline checks against actual (not merely declared) identities and Resolve version; one combined orchestration function binding capture and evaluation to the same read-back, re-hashed bytes. Independent review of Rev2 then found: checker code still loaded before the repository checkpoint gate could reject a bad state; five distinct malformed/contradictory snapshot states could still false-pass (boolean queue counts, contradictory project-level queue evidence, an unobserved product identity, contradictory Resolve version accessors, an optional rather than required video track-count observation); the evidence output path was insufficiently protected and bound (relative paths accepted, no protected-location checks); and collector failure `stdout`/`stderr` were captured but discarded on a non-zero exit.
- **Rev3**: corrected every Rev2 finding above — checker loaded only by exact canonical path after the repository gate, and only after its own hash verification; all five false-pass gaps closed with stricter, cross-consistency-checked assertions; absolute/protected/fresh evidence-path enforcement (repository, RLC-E9901 workspace, runtime directory); collector `stdout`/`stderr` preserved verbatim for every outcome. Independent review of Rev3 then found: the documented five-field `GetVersion()` shape (`[major, minor, patch, build, suffix]`) was being rejected as malformed, even for the repository's own reviewed evidence value; and the separately-located preserved `RedlineOSLive\Evidence` directory was missing from the protected evidence-path roots.
- **Rev4**: corrected both Rev3 findings above — five-field `GetVersion()` normalization implemented against the repository's own reviewed evidence shape; `RedlineOSLive\Evidence` added as a fourth protected root. Independent review of Rev4 then found: a non-empty `GetVersion()` suffix was validated for type but silently discarded during normalization, letting an unreviewed build/suffix combination pass as if it matched the authorized version; and `subprocess.TimeoutExpired`'s partial output (which can be raw `bytes` on Python 3.11 even under `text=True`) was not represented losslessly or JSON-safely.
- **Rev5**: corrected both Rev4 findings above — the suffix must now be exactly the empty string, not merely string-typed; subprocess-captured output (all outcome paths, not only timeouts) is now represented through a JSON-safe, lossless `CapturedOutput` structure. **Rev5 passed independent source review; see the frozen hashes at the top of this document. It has not been executed live.**

Agents advise. Paul decides.
