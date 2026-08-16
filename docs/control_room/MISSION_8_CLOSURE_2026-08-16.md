# Control Room V0 Mission 8 Closure

## Purpose

Mission 8 extended the Project Detail screen's live GitStatus block with
a read-only Current Working Tree Change Detail drill-down: the
repository-relative file paths currently staged, unstaged, untracked, or
mid-conflict in the *live, uncommitted* working tree -- distinct from
Checkpoint Change Set Detail (Mission 7), which answers the same
"which files changed" question for one *historical, resolved* commit.
The answer comes from one single, authoritative `git status` read, never
parsed from closure-document prose and never a second Git invocation
that could disagree with the existing CLEAN/DIRTY classification.

## Published Checkpoint

SHA:
`31d82e05bb3a3f7719a58ce6e50ae950f6631d0e`

Subject:
`feat: add Control Room V0 Current Working Tree Change Detail`

Parent:
`7d8e440c6909eb127f59d2228f1ee590684a9692`

## Delivered Capability

- `GitReader._read_working_tree()` issues exactly one
  `git --no-optional-locks status --porcelain=v2 -z --untracked-files=all
  --renames` call and derives both the coarse `WorkingTreeStatus`
  (CLEAN/DIRTY) and the full per-path `list[WorkingTreeChange]` detail
  from that same output -- never a second `git status` invocation, so
  the CLEAN/DIRTY pill and the change-path detail can never disagree
  about whether the tree is dirty. `--no-optional-locks` closes off the
  one narrow way a plain `git status` can otherwise write to disk (an
  opportunistic index stat-cache refresh) as a side effect of what
  should be a purely read-only call. `--renames` is explicit so rename
  detection does not silently depend on a checkout's local
  `status.renames`/`diff.renames` configuration.
- A hand-written porcelain-v2 parser decodes the ordinary (`1`),
  rename/copy (`2`), unmerged (`u`), and untracked (`?`) record shapes,
  NUL-delimited (`-z`) so a filename containing a space cannot be
  misparsed. `WorkingTreeChange` is one record per path: a file both
  staged and further modified in the working tree is one record with
  both `index_status` and `worktree_status` set, never two disconnected
  entries. A rename/copy record carries `original_path` and a `kind`
  (`RENAMED`/`COPIED`, derived from the score field's `R`/`C` prefix);
  status codes and paths only -- no diff content, line counts, or
  rename/copy similarity score is read or exposed.
- **Two-tier failure design.** A subprocess-level failure (Git not
  found, timeout, non-zero exit) still fails the whole `GitStatus`
  exactly as before this mission, routing through the existing
  `_error_status()` path. A narrower failure -- the subprocess succeeds
  but a record inside its output does not match any recognized
  porcelain-v2 shape -- degrades only `working_tree_changes` (to `None`
  with an explicit `working_tree_changes_error`), leaving
  `repository_valid`, `branch`, `head_sha`, and `tracking` intact, since
  none of those depend on successfully decoding every record.
- **Strict malformed-output degradation, never a partial list.** An
  unrecognized record type (including an impossible `!` ignored-file
  record, since `--ignored` is never passed), a malformed field count,
  an empty `path`/`original_path`, or a rename/copy score field not
  matching `^[RC][0-9]+$` each invalidate the *entire* detail list
  rather than silently dropping just that one record. Status-letter
  (X/Y) validation is scoped per record type: ordinary and rename/copy
  records reject `R`/`C`/`U` combinations Git itself can never produce
  for those record types; unmerged records keep the broader documented
  letter union.
- Model gains `WorkingTreeChangeKind` and `WorkingTreeChange`, plus two
  `GitStatus` fields (`working_tree_changes`, `working_tree_changes_error`).
  No service-layer enrichment code was needed: the fields ride straight
  through the existing `GitReader.read_status()` call in
  `ProjectStatusService._build_snapshot()`. No new backend route: rides
  the existing `GET /api/projects/{project_id}` response.
- Frontend adds a fourth escaped `<details>` disclosure ("Current
  Working Tree Change Detail") on the Project Detail screen's Git status
  block, grouped by change kind, with explicit messages for the clean
  and unavailable states.
- Documented the single-authoritative-read design, the two-tier failure
  boundary, the `--no-optional-locks` rationale, and the per-record-type
  status-letter scoping in `README.md` and
  `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`.

## Source-of-Truth Boundary

- **Git = machine truth.** Live branch, HEAD, working-tree/tracking
  state, the current working tree's own change paths (Mission 8),
  historical checkpoint resolution, and each historical checkpoint's own
  file-path change set (Mission 7) are all read from the local
  repository on every request.
- **`PROJECT_STATE.yaml` = current semantic state only.** Still stores
  no live Git facts and no mission history.
- **Closure documents = historical mission records, evidence text, and
  scope/outcome text.** Never the source of a working-tree change list
  -- that question is answered only by Git.
- **The web layer never reads files, runs Git, parses YAML, writes
  state, or triggers validation.** It only renders `ProjectSnapshot`
  data returned by `ProjectStatusService`.

## Validation

- **Focused Control Room suite** (final, after all correction rounds):
  `pytest tests/unit/control_room -q` -- **139 passed** (114 pre-existing
  + 25 Mission 8: 16 initial + 7 round-1 correction + 2 round-3
  correction).
- **Mission-8-specific**: `pytest
  tests/unit/control_room/test_working_tree_change_detail.py -q` -- **25
  passed**, covering ordinary/rename/copy/unmerged/untracked record
  decoding, the staged-and-further-modified single-record case, the
  real-Git rename-detection boundary (empirically verified: `--renames`
  only detects a *staged* rename, never an unstaged filesystem move),
  the two-tier failure design, empty-path/empty-original-path hardening,
  malformed rename/copy score hardening, illegal-`U`-status hardening
  for ordinary/rename records, service composition (no enrichment code
  needed), served frontend wiring, the read-only/no-new-routes
  invariant, and compatibility with this repository's own real, live
  working tree.
- **Broad regression** (implementation environment, 17 pre-existing
  `cli`-package collection errors excluded, matching every prior
  mission's documented exclusion -- exact command
  `python -m pytest tests/unit -q --continue-on-collection-errors`,
  empirically re-verified necessary on this machine/pytest version: a
  plain `pytest tests/unit -q` with no flag aborts entirely with
  "Interrupted: 17 errors during collection" and runs zero tests):
  **2536 passed, 18 skipped, 4 failed**, reproduced identically three
  times. The 4 failures are the same pre-existing, environment-specific
  families observed at every prior mission gate in this environment
  (`test_installed_cli_asset_list_smoke.py`,
  `test_installed_mcp_startup_smoke.py`, `test_installed_wheel_smoke.py`,
  `test_phase14_resolve_context_snapshot.py`), unrelated to
  `control_room`. Zero `control_room` failures. Zero new failure or
  collection-error families.
- **Route verification**: no new route; API surface remains exactly
  `GET /`, `GET /api/projects`, `GET /api/projects/{project_id}`.
- **Mutation/security scan**: `src/control_room` contains no Mission 8
  write path, filesystem-write route, shell execution, network Git
  operation, mutating Git verb invocation, database write,
  POST/PUT/PATCH/DELETE route, mission editing, checkpoint creation,
  automation, Resolve, Hermes, Context Engine, or agent-integration
  capability.

## Independent Review

Verdict (round 3, final): **PASS -- READY FOR CHECKPOINT DECISION.**

Codex's own local OS-level sandbox is broken on this machine (Windows
ACL/junction failure -- Access Denied modifying `C:\Users\Default`,
requiring Administrator rights this session neither has nor attempted to
obtain). This is an environment gap, not a code defect, and was not
worked around by disabling Codex's sandbox or modifying the OS. Instead,
review proceeded via a static independent-review fallback: a complete
package of the full raw uncommitted diff, the full contents of the new
test file, `git status`/`diff --stat` output, and all test evidence was
supplied verbatim to Codex, with explicit instructions not to attempt
any tool call, shell command, or repair -- a purely textual/static
adversarial review.

Three rounds preceded this verdict:

1. **Round 1 (BLOCKED -- CORRECTION REQUIRED):** an empty `path`/
   `original_path` in a recognized porcelain-v2 record shape, and a
   rename/copy score field validated only by its first character
   (accepting malformed suffixes like `Rabc`/`C-1`), each silently
   produced a structured record instead of degrading the whole list.
   Corrected: every parsed path/original_path is checked non-empty, and
   the score field must match `^[RC][0-9]+$`. Seven new targeted tests
   added, including a direct structural test of copy-kind (`C` prefix)
   derivation.
2. **Round 2 (PASS WITH NON-BLOCKING FINDINGS):** both round-1
   corrections explicitly re-verified. One new, explicitly
   non-blocking finding: status-letter validation used one shared
   letter union across every record type, silently accepting an
   impossible `U` on an ordinary or rename/copy record (Git only ever
   emits `U` for its own unmerged record type).
3. **Round 3 (PASS -- READY FOR CHECKPOINT DECISION):** `--no-optional-
   locks` added to the single status invocation; status-letter
   validation split per record type (ordinary and rename/copy now
   reject `R`/`C`/`U`; unmerged intentionally kept the broader union,
   not narrowed without stronger confidence in Git's exact
   conflict-combination alphabet). Both corrections independently
   re-verified against the diff, plus a full re-review of the entire
   supplied diff. No further findings.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No V1 tag was created, moved, or deleted during
Mission 8.

## Deferred Work

Explicitly out of scope for Mission 8, unchanged by this closure:

- Diff content, line counts, rename/copy similarity score, commit
  author/email/message, blame information, branch history graphs, or
  any historical-commit comparison (that remains Checkpoint Change Set
  Detail's, Mission 7's, territory).
- Ignored files (`--ignored` is never passed; a `!` record appearing
  under this fixed invocation is treated as malformed output, not a
  feature to expose).
- Pagination or truncation of a very large change set (e.g. an
  accidentally-untracked large directory expanded by
  `--untracked-files=all`) -- no limit exists in V0, matching the
  existing precedent for Checkpoint Change Set Detail.
- Narrowing unmerged-record status-letter validation beyond the general
  documented union -- deliberately not attempted without stronger
  confidence in Git's exact conflict-combination alphabet across
  versions.
- Additional projects or project auto-discovery.
- Additional Control Room screens beyond Projects and Project Detail.
- Mission creation, mission editing, checkpoint creation, validation or
  test reruns, CI execution or repair, or a history/evidence/change-set
  database or event log.
- Context Engine, agent routing, Hermes integration, automation of any
  kind.
- Resolve, render, episode, asset, archive, or production controls.
- Broad CI portability/stale-test repair and unrelated installed-package
  smoke debt.
- Repairing this machine's local Codex OS-level sandbox (Windows ACL/
  junction permission gap) -- explicitly not attempted; the static
  independent-review fallback exists precisely so this repair is never
  a precondition for Mission 8's own review.
- Mission 9 definition -- no scope, objective, or timeline for a next
  mission is implied or proposed by this document.

## Closure

Control Room V0 Mission 8 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
