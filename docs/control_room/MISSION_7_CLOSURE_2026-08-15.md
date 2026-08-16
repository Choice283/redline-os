# Control Room V0 Mission 7 Closure

## Purpose

Mission 7 extended the existing read-only Mission & Checkpoint History
with a Checkpoint Change Set Detail drill-down, alongside the existing
Mission Scope & Outcome Detail (Mission 6) and Validation & Evidence
Detail (Mission 5). For each historical mission, it exposes the
repository-relative file paths actually changed by that mission's
published implementation checkpoint commit -- derived live from local
Git machine truth, not parsed from closure-document prose. The feature
remains observational only: no diff content, line counts, author,
message, blame, branch history, or working-tree/untracked-file
information is read or returned, and no capability success, risk score,
or recommended action is derived from a changed-file list.

## Published Checkpoint

SHA:
`72cf8a7382e55342d16f0fc7c17c651c9f2d3a07`

Subject:
`feat: add Control Room V0 Checkpoint Change Set Detail`

Parent:
`276c30ddaaadc61f4fdae3af53c6c81d4ea319f5`

## Delivered Capability

- Added `GitReader.read_commit_changed_files(commit)`: a fixed,
  read-only Git argument array (`git diff-tree --root --no-commit-id
  --name-only -r -z <commit>`) against the existing explicit repository
  `cwd`, NUL-delimited (`-z`) so filenames containing spaces cannot be
  misparsed. No shell execution, no network Git, no mutating Git
  operation.
- Closed the revision-input boundary in two layers: `ProjectStatusService`
  only ever calls it with a SHA already verified via `commit_exists()`,
  and the method itself refuses -- before spawning any subprocess -- any
  value that is not a plain hex commit SHA, which also closes off Git
  interpreting a `-`-prefixed value as an option.
- **Merge-commit correction** (independent Codex review finding): a bare
  `git diff-tree` on a merge commit can under-report or omit files the
  merge actually introduced, which would have silently collapsed "merge
  change-set semantics not determined" into "legitimate empty commit."
  `read_commit_changed_files()` now determines parent count first
  (`git rev-list --parents -n 1 <commit>`) and returns an explicit
  unsupported-merge result for any commit with more than one parent,
  rather than guessing at first-parent/combined/union diff semantics.
  Merge commits remain intentionally unsupported in V0.
- **Malformed-output hardening** (post-correction focused review
  finding): a successful (exit 0) `rev-list` result is not trusted at
  face value -- its output must be one or more whitespace-separated
  tokens, and every token must match a full 40-character hex SHA
  exactly, or the result is treated as undetermined and never reaches
  `diff-tree`.
- Extended `MissionHistoryEntry` with `checkpoint_changed_files` and
  `checkpoint_changes_error`, distinguishing a normal non-empty change
  set, a legitimate empty change set (`[]`, not an error), and an
  unavailable change set (`None` + explicit message) -- deliberately
  separate from closure-document `parse_error`, which remains reserved
  for closure-parsing problems only.
- `MissionHistoryReader` remains unchanged and Git-free; enrichment
  against live Git happens in `ProjectStatusService`, in the same loop
  that already resolves `checkpoint_resolved`. No new backend route: the
  fields ride the existing `GET /api/projects/{project_id}` response.
- Rendered a third read-only `<details>` disclosure ("Checkpoint Change
  Set Detail") per history entry, alongside the existing two, with
  changed-file paths HTML-escaped and explicit messages for the empty
  and unavailable states.
- Added regressions for: root-commit extraction, multiple changed files,
  repository-relative nested paths, filenames containing spaces,
  NUL-delimited parsing safety, legitimate empty change sets, unknown/
  unresolved commits, non-SHA revision rejection (proven without
  invoking Git), Git command timeout degradation, a genuine non-trivial
  merge commit (proven to introduce a real file and still degrade as
  unavailable, never `[]`), malformed successful `rev-list` output
  (proven never to reach `diff-tree`), service-level composition for all
  three outcome states, non-contamination of `parse_error`, unchanged
  Mission 5/6 rendering, safe frontend escaping, the route/mutation
  invariant, and compatibility with the real Missions 1-6 checkpoints
  already published in this repository.
- Documented the Checkpoint Change Set Detail source-of-truth boundary,
  the read-only Git operation, the merge/malformed-output degradation
  rules, and updated non-goals in `README.md` and
  `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`.

## Source-of-Truth Boundary

- **Git = machine truth.** Live branch, HEAD, working-tree/tracking
  state, historical checkpoint resolution, and now each checkpoint's own
  file-path change set are all read from the local repository on every
  request.
- **`PROJECT_STATE.yaml` = current semantic state only.** It does not
  store mission history, validation evidence, scope/outcome text, or
  checkpoint change sets.
- **Closure documents = historical mission records, evidence text, and
  scope/outcome text.** They are never the source of a checkpoint's
  changed-file list -- that question is answered only by Git.
- **The web layer never reads files, runs Git, parses YAML, writes
  state, or triggers validation.** It only renders `ProjectSnapshot`
  data returned by `ProjectStatusService`.

## Validation

- **Focused Control Room suite** (final, after both correction rounds):
  `pytest tests/unit/control_room -q` -- **114 passed**.
- **Broad regression** (Mission 7 implementation environment,
  17 pre-existing `cli`-package collection errors excluded, matching
  every prior mission's documented exclusion): **2517 passed, 18
  skipped, 4 failed.** The 4 failures are the same pre-existing,
  environment-specific families observed at every prior mission gate in
  this environment (`test_installed_cli_asset_list_smoke.py`,
  `test_installed_mcp_startup_smoke.py`, `test_installed_wheel_smoke.py`,
  `test_phase14_resolve_context_snapshot.py`), reviewed and classified
  as outside `control_room`. Not rerun for the two subsequent focused
  correction rounds (merge-commit degradation, malformed-`rev-list`
  hardening), which stayed entirely within `GitReader`/service/test
  scope -- the implementation broad gate above remains the mission-level
  regression evidence, per the correction-round authorization.
- **Real Missions 1-6 compatibility**: verified after each correction
  round. All six real, published checkpoints continue to resolve and
  yield their existing non-empty change sets -- none of the real history
  is a merge commit, so all are on the unaffected normal-commit path.
- **Route verification**: runtime route introspection showed only
  `GET /`, `GET /api/projects`, and `GET /api/projects/{project_id}`.
- **Mutation/security scan**: `src/control_room` contains no Mission 7
  write path, filesystem-write route, shell execution, network Git
  operation, mutating Git verb invocation, database write,
  POST/PUT/PATCH/DELETE route, mission editing, checkpoint creation,
  automation, Resolve, Hermes, Context Engine, or agent-integration
  capability.

## Independent Review

Verdict: **PASS -- READY FOR CHECKPOINT DECISION.**

Two correction rounds preceded this verdict:

1. **Blocking finding (semantic defect):** a non-trivial merge commit
   could return an empty changed-file list via a bare `git diff-tree`,
   incorrectly collapsing "merge change-set semantics not safely
   determined" into "legitimate empty commit." Corrected by detecting
   parent count first and degrading any commit with more than one parent
   as explicitly unavailable, with a real, non-trivial three-way-merge
   regression proving the commit resolves, genuinely introduces a file,
   and still does not return `[]`.
2. **Focused hardening (defensive parser correction):** a successful
   `rev-list` result was not validated before being interpreted as a
   parent count. Corrected to require every output token to match a full
   40-character hex SHA exactly, with a regression proving malformed
   output (a fake successful `rev-list` returning non-SHA text) degrades
   explicitly and never reaches `diff-tree`.

Both corrections were re-verified with the focused suite, the specific
new regression run independently, and a re-run of the real Missions 1-6
compatibility check, each passing cleanly.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No V1 tag was created, moved, or deleted during
Mission 7.

## Deferred Work

Explicitly out of scope for Mission 7, unchanged by this closure:

- Merge-commit change-set semantics (first-parent, combined, or union
  diff) -- merge commits remain intentionally unsupported in V0, not a
  gap scheduled for a specific future mission.
- Diff content, line counts, commit author/email/message, blame
  information, branch history graphs, or parent-range comparisons.
- Working-tree changes or untracked files.
- Derived impact/risk/change scores, affected-subsystem inference,
  mission-success inference, or recommended-action generation from a
  changed-file list.
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
- Mission 8 definition -- no scope, objective, or timeline for a next
  mission is implied or proposed by this document.

## Closure

Control Room V0 Mission 7 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
