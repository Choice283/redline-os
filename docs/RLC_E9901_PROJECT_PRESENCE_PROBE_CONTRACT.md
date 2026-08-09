# RLC-E9901 Read-Only Resolve Project-Presence Probe — Contract

Status: **construction revision 3 — live execution prohibited**
Construction revision identifier: `rlc-e9901-project-presence-probe-construction-rev3`
Probe path: `scripts/rlc_e9901_project_presence_probe.py`
Test path: `tests/unit/test_rlc_e9901_project_presence_probe.py`

Rev2 corrected the six findings (four Important, two Minor) from the completed Rev1 independent source review: untested accessor-exception fail-closed paths, an untested output-collision-before-Resolve-contact ordering guarantee, a missing evidence `captured_at` timestamp, an unstated folder-continuity operational precondition (this document, §2), an unhardened falsy-scalar version check, and an unnormalized realistic `GetVersion()` list/tuple shape.

Rev3 corrects the two Minor findings the completed Rev2 independent source review identified in that same hardening work: boolean `True` was still accepted as meaningful version evidence (Rev2 rejected only `None`/`""`/`False`/`0`/`0.0`, a procedurally-scoped rather than semantically-defensible choice), and negative integers were accepted unchallenged by `_normalize_version_components()` even though genuine Resolve version components are never negative. Both are now rejected — see §3 and §6.

Rev1 (SHA-256 `56f4f325087370a413d9bc56665b3f3ffbb2b33af6c7e3a7b862690146bfc7c8`) and Rev2 (SHA-256 `83eab0bb4df456a8aa6344a3c05e998abcc60f52c621ddf1d3882950e317ff6d`) are both superseded. Neither predecessor's execution revision identifier is valid for Rev3's source bytes, and neither must be treated as interchangeable with `rlc-e9901-project-presence-probe-construction-rev3`.

This contract defines a future one-shot, read-only evidence-gathering step. It does not itself authorize live execution. **Neither this document nor the probe it describes authorizes anything by existing.**

Governing rule: **Agents advise. Paul decides.**

## 1. Purpose

The probe answers exactly one question, in three parts, needed before Paul can consider authorizing the RLC-E9901 fresh-episode one-shot live build:

1. Does a DaVinci Resolve scripting connection succeed?
2. Is `RLC-E9901_MASTER` **absent** from the Project Manager's current folder?
3. Is `RLC_MASTER_TEMPLATE` **present** in that same folder?

Nothing else. It does not snapshot a project, does not compare two contexts, does not inspect a timeline, media pool, or render queue. That broader job already belongs to `scripts/phase14_resolve_context_snapshot.py`, which is the wrong shape for this question (it requires a project already open and current; it has no "does project X exist in the library" operation) and is separately gated behind its own manifest/execution-revision/typed-confirmation process. This probe exists because that gap was identified during the immediately preceding read-only live preflight mission and no existing reviewed mechanism filled it.

## 2. Folder scope — why there is no separate "applicable folder" concept

Redline OS's real adapter (`ResolveScriptAdapter.duplicate_project`, `src/redline_core/resolve/adapter.py`) determines project existence purely via `self._project_manager.GetProjectListInCurrentFolder()` — it never calls `SetCurrentFolder`, `OpenFolder`, or any folder-navigation method. Redline OS has no concept of a named target folder; it always operates on whatever Project Manager folder happens to be current when Resolve connects. This probe deliberately mirrors that exact scope so its "absent"/"present" answers mean the same thing the real build path's own collision check would see. It calls the identical accessor.

### 2.1 Operational precondition: session continuity (Rev2, Important Finding 4)

The scope match described above holds only at the instant the probe runs. "Current folder" is Resolve UI-driven, external state this probe deliberately never reads back after the fact and never navigates — it has no `SetCurrentFolder`/`OpenFolder`/`GotoRootFolder`/`GotoParentFolder` call anywhere (§5), so it cannot detect, prevent, or correct a folder change that happens after it exits. Nothing in this repository documents whether DaVinci Resolve's Project Manager "current folder" persists across an application restart, a project close, or a fresh scripting connection, so this contract does not assume a weaker rule than the evidence supports.

**Required operational rule:** the read-only presence probe and the future one-shot live build must occur within one continuous Resolve session, with no Project Manager folder navigation between them. Concretely:

- Resolve must not be restarted, and no scripting connection may be closed and reopened, between the probe run and the live build attempt.
- No operator action in the Resolve UI (or any other script) may navigate the Project Manager to a different folder between the two.
- If either condition cannot be positively confirmed, the probe's evidence must be treated as stale and re-captured immediately before the live build attempt, not relied upon from an earlier session.

A future live-build authorization that relies on this probe's evidence must explicitly confirm this continuity was maintained — that confirmation is part of what "binding the exact attempt" means for this probe (§8).

## 3. Architecture

Modeled on the safety idioms already established and reviewed in `scripts/phase14_resolve_context_snapshot.py`, scaled down to this probe's single narrow question:

- No `DaVinciResolveScript` import at module import time — confirmed both by static review and `tests/unit/test_rlc_e9901_project_presence_probe.py::test_no_module_level_resolve_import` (parses the module's AST and asserts no top-level `import`/`from import` names it).
- A deliberate **execution interlock**: the `check` CLI subcommand requires `--execution-authorization` to exactly equal `EXECUTION_REVISION_ID`, checked before output-path validation, before `DaVinciResolveScript` import, and before any Resolve connection. Not a credential or a security boundary — it exists so an operator cannot reach Resolve by accident or by reusing stale instructions.
- A **closed, read-only Resolve-method allowlist** (`READ_ONLY_RESOLVE_METHODS`) — every accessor the probe calls on a live handle is checked against it first. No dynamic dispatch of an arbitrary method name ever occurs.
- A documented **prohibited-method list** (`PROHIBITED_RESOLVE_METHODS`), enforced two ways in the test suite: no prohibited name is ever the target of a method call anywhere in the source (`test_no_prohibited_method_called_anywhere_in_source`), and no prohibited name appears as a string literal anywhere outside its own definition in that list (`test_no_prohibited_method_referenced_as_string_literal_outside_the_list_itself`) — so a future edit that tried to smuggle in dynamic dispatch of a forbidden name via `getattr(obj, "LoadProject")` would fail the static suite even though it never touches the allowlist-checked call path.
- **Create-only, no-overwrite evidence output**, identical discipline to the existing snapshot probe: full in-memory JSON serialization, write to a same-directory temp file, `fsync`, publish via `os.link` (which raises on an existing destination on both Windows and POSIX, unlike a plain rename that silently replaces on POSIX), and always-attempted temp-file cleanup that is never silently swallowed.
- **Fail-closed ambiguity handling**: a non-list return from `GetProjectListInCurrentFolder()`, a non-string or empty-string entry, or more than one exact-name match for either `RLC-E9901_MASTER` or `RLC_MASTER_TEMPLATE` all raise rather than guessing.
- (Rev2) **`GetProjectManager()` and `GetProjectListInCurrentFolder()` raising** is now directly tested (`test_collect_project_manager_accessor_raises_fails_closed`, `test_collect_project_list_accessor_raises_fails_closed`), including proof that the raw exception text never leaks into the structured error, not merely implemented and asserted by inspection.
- (Rev2) **Output-collision-before-Resolve-contact is now directly tested under valid authorization** (`test_main_check_output_collision_with_valid_auth_never_contacts_resolve`): a pre-existing output path with a *correct* `--execution-authorization` still stops the run via a `connect_resolve_read_only` stub that fails the test if ever called, so an accidental reordering of `validate_output_path` before `connect_resolve_read_only` in `run_check_command` would be caught, not merely documented in a code comment.
- (Rev2) **Evidence carries a `captured_at` UTC ISO-8601 timestamp** (`utc_now()`, same convention as `scripts/phase14_resolve_context_snapshot.py`), present in every successful evidence file.
- (Rev2) **`_is_unusable_scalar()` hardens the "usable version observed" gate** so `None`, `""`, `False`, `0`, and `0.0` can never satisfy it, and **`_normalize_version_components()`** narrowly recognizes Resolve's realistic `GetVersion()` list/tuple shape (e.g. `[19, 0, 3, 7]` → `"19.0.3.7"`) without broadening accepted element types.
- (Rev3) **`_is_unusable_scalar()` now rejects `True` as well as `False`** — there is no documented or plausible Resolve scenario where either boolean is a real version value; a boolean return from `GetVersion()`/`GetVersionString()` only ever indicates an anomalous or broken bridge. Rev2's narrower scoping (only the five explicitly-listed values) was closed on procedural rather than semantic grounds, per the Rev2 independent review's explicit challenge.
- (Rev3) **`_normalize_version_components()` now rejects negative integers** (e.g. `[-1, 0, 3]` → `None`) — genuine Resolve version components are never negative, so normalizing one into a version-looking string would be misleading. Zero remains accepted as a valid non-negative component.

## 4. Exact permitted Resolve API calls

```
GetProductName
GetVersion
GetVersionString
GetProjectManager
GetProjectListInCurrentFolder
```

Every one of these is inspection-only in the Resolve scripting interface. A future review must re-approve this exact set before any name is added.

## 5. Explicitly prohibited Resolve API calls

```
GetCurrentProject       LoadProject             CloseProject
CreateProject           DeleteProject           SaveProject
SetCurrentFolder        OpenFolder              GetProjectAttributesInCurrentFolder
GetCurrentFolder        CreateFolder            DeleteFolder
GotoRootFolder          GotoParentFolder        ImportProject
ExportProject           RestoreProject          GetCurrentTimeline
SetCurrentTimeline      SetSetting              SetRenderSettings
LoadRenderPreset        AddRenderJob            DeleteRenderJob
DeleteAllRenderJobs     StartRendering          StopRendering
```

Note `GetProjectAttributesInCurrentFolder` is prohibited here even though the larger snapshot probe allowlists it — this probe has no need for per-project attribute detail beyond the exact-name list, so it is deliberately excluded to keep the allowlist as small as the question requires. `GetCurrentProject` is prohibited because this probe must never depend on, or reveal, whatever project happens to be open at connection time — only the *list* of project names in the current folder.

## 6. Fail-closed success, failure, and abort criteria

**Success (exit 0, evidence written):** the interlock passes, the output path is fresh, `DaVinciResolveScript.scriptapp("Resolve")` returns a usable handle, at least one of `GetVersionString`/`GetVersion` returns a genuinely meaningful value (`None`/`""`/`False`/`True`/`0`/`0.0` never count as of Rev3, and a realistic `GetVersion()` list/tuple of non-negative integers/non-empty strings is normalized rather than rejected or accepted unvalidated — §3), `GetProjectManager()` returns a usable handle, `GetProjectListInCurrentFolder()` returns a list of non-empty strings, and neither target name matches more than once. The written evidence includes a `captured_at` UTC ISO-8601 timestamp (Rev2) and classifies `overall_gate` as exactly one of:

- `ready_for_live_build_authorization_review` — disposable absent, template present.
- `blocked_disposable_project_present` — disposable present (regardless of template).
- `blocked_template_absent` — disposable absent, template also absent.
- `blocked_disposable_present_and_template_absent` — both conditions block.

A `blocked_*` classification is a **successfully completed probe run**, not a probe failure — it is evidence, exactly as directed in Phase E of the founder's read-only live preflight instructions ("Report enough evidence to distinguish... ABSENT / PRESENT / INDETERMINATE").

**Failure (exit 2, structured error to stderr, no evidence file written):** missing/malformed/mismatched execution authorization; output path already exists or its parent is missing (also the one-attempt boundary — see §7); `DaVinciResolveScript` import fails; `scriptapp` is unavailable, raises, or returns a falsy handle; no usable version observed; no usable project manager; `GetProjectListInCurrentFolder()` returns a non-list, or contains a non-string/empty entry; either target name matches more than once (`*_ambiguous`).

**Abort:** any of the above failure conditions stops the run immediately. There is no retry logic anywhere in the probe — a second attempt requires a human to re-invoke it with a fresh output path.

## 7. One-attempt live-execution boundary and cleanup policy

**One-attempt boundary:** enforced mechanically, not by convention. `validate_output_path` requires the `--output` path to not already exist, checked *before* Resolve is contacted. A prior run's evidence file (successful or failed-after-write) permanently occupies its path, so a second invocation against the same path fails closed before any Resolve connection is attempted. A genuinely new attempt requires a human to choose a new, not-yet-existing evidence path — there is no `--force`, no overwrite flag, anywhere in this probe.

**Cleanup policy:** none is required, because none is possible to need. This probe performs **zero mutating Resolve calls** — it never calls `LoadProject`, `SetCurrentFolder`, `CreateProject`, or any other method capable of changing what project or folder is open in Resolve, or capable of altering any Resolve-side state. There is nothing for a future live run to roll back or clean up in Resolve itself. The only filesystem artifact it can produce is the one evidence JSON file at the exact `--output` path the operator supplies; nothing else is written, moved, or deleted.

## 8. What a future founder live-execution authorization must bind

Consistent with `CLAUDE.md` §8's requirement that live Resolve execution authorization identify an exact script, hash, and boundary — not merely a category of permitted action — a future authorization to run this probe live should state:

- the exact repository commit this probe is reviewed against;
- the exact probe path (`scripts/rlc_e9901_project_presence_probe.py`) and its exact SHA-256 (see §9);
- the exact `EXECUTION_REVISION_ID` value the operator must supply (`rlc-e9901-project-presence-probe-construction-rev3` for this revision — see §10; never a Rev1 or Rev2 identifier against Rev3's bytes, or vice versa);
- the exact `--output` evidence path (parent directory pre-created, path itself not yet existing);
- attempt limit: **one** invocation, mechanically enforced per §7;
- success/failure/abort criteria: exactly §6 above;
- cleanup/rollback boundary: none required, per §7;
- (Rev2) explicit confirmation that the session-continuity precondition in §2.1 held between this probe's run and the live build attempt it is meant to justify.

## 9. Frozen candidate probe SHA-256

At construction time, the frozen candidate's SHA-256 (over the exact bytes of `scripts/rlc_e9901_project_presence_probe.py` as written) is reported in the construction mission's final report, and reproducible at any time via:

```powershell
python scripts\rlc_e9901_project_presence_probe.py --print-sha256
```

which never imports or contacts Resolve.

## 10. Revision discipline

`EXECUTION_REVISION_ID` is immutable for this exact source text. Any future change to `scripts/rlc_e9901_project_presence_probe.py` — including a change to this contract's own referenced hash — requires a new identifier and a new SHA-256, minted together, reviewed together, and bound together by a separate founder authorization. Drafting or statically reviewing this contract does not authorize live execution of the probe it describes.

**Revision history:**

- **Rev1** (`rlc-e9901-project-presence-probe-construction-rev1`, SHA-256 `56f4f325087370a413d9bc56665b3f3ffbb2b33af6c7e3a7b862690146bfc7c8`) — initial construction. Superseded; not valid for live use.
- **Rev2** (`rlc-e9901-project-presence-probe-construction-rev2`, SHA-256 `83eab0bb4df456a8aa6344a3c05e998abcc60f52c621ddf1d3882950e317ff6d`) — corrected the six findings from Rev1's completed independent source review. Rev2's own completed independent source review found two Minor findings (boolean `True` still accepted as version evidence; negative integers accepted unchallenged in `_normalize_version_components()`) and no Critical or Important findings. That review also disclosed and closed an unrelated incident: an accidental live Resolve contact made during the Rev2 review itself, and the resulting evidence file's accidental deletion before inspection — both permanently classified INVALID/NON-AUTHORITATIVE and providing no credit toward any future RLC-E9901 live-preflight or project-presence requirement. Superseded by Rev3; not valid for live use.
- **Rev3** (`rlc-e9901-project-presence-probe-construction-rev3`) — this revision. Corrects the two Minor findings from Rev2's completed independent source review (§1 and §3 above). Rev3 itself has not yet completed its own independent source review as of this writing; it is not authorized for live use until that review completes and a separate founder authorization is granted.

**Agents advise. Paul decides.**
