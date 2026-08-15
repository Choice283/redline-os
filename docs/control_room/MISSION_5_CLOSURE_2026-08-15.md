# Control Room V0 Mission 5 Closure

## Purpose

Mission 5 added a read-only Validation & Evidence Detail drill-down to
the existing Control Room Project Detail screen. Each historical mission
entry can now expand the verbatim `## Validation`, `## Independent
Review`, and `## CI` sections from its durable closure document, whichever
are present. The feature remains observational only: it does not rerun
tests, reinterpret evidence, edit records, create checkpoints, contact CI,
or introduce database, agent, automation, Resolve, Hermes, or Context
Engine capability.

## Published Checkpoint

SHA:
`8d6e97b2417efc95262b9ec341d9c3e439cf5881`

Subject:
`feat: add Control Room V0 Validation & Evidence Detail`

Parent:
`3143dd88eccc081779a307a20517388991935978`

## Delivered Capability

- Extended `MissionHistoryEntry` with optional `validation_section`,
  `independent_review_section`, and `ci_section` fields.
- Extended `MissionHistoryReader` to read those fields fresh from
  `docs/control_room/MISSION_*_CLOSURE_*.md` records on every request.
- Section extraction is fence-aware: level-2 headings inside active
  triple-backtick or triple-tilde Markdown fences are treated as ordinary
  evidence text, not section starts or boundaries.
- Preserved raw/verbatim section text, with no structured parsing of test
  counts, verdicts, CI status, or review outcome.
- Rendered the evidence sections in the existing Project Detail mission
  history UI as escaped read-only `<details>` content.
- Rendered missing optional evidence sections explicitly as not recorded,
  without treating absence as a malformed closure document.
- Documented the Validation & Evidence Detail source-of-truth boundary in
  `README.md` and `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`.

## Source-of-Truth Boundary

- **Git = machine truth.** Live branch, HEAD, working-tree/tracking state,
  and historical checkpoint resolution continue to be read from the local
  repository on every request.
- **`PROJECT_STATE.yaml` = current semantic state only.** It records the
  current mission/checkpoint/validation posture and does not store mission
  history or validation evidence.
- **Closure documents = historical mission records and evidence text.**
  Validation & Evidence Detail is parsed fresh from
  `docs/control_room/MISSION_*_CLOSURE_*.md`.
- **The web layer never reads files, runs Git, parses YAML, writes state,
  or triggers validation.** It only renders `ProjectSnapshot` data
  returned by `ProjectStatusService`.

## Validation

- **Focused Control Room suite**:
  `.\.venv-codex\Scripts\python.exe -m pytest tests/unit/control_room -q -p no:cacheprovider`
  passed under intended dependency/network conditions: 83 passed in
  54.83s.
- **Fence-specific regressions**:
  `.\.venv-codex\Scripts\python.exe -m pytest tests/unit/control_room/test_mission_history_reader.py -q -k "fenced or fence" -p no:cacheprovider`
  passed: 3 passed, 16 deselected.
- A non-escalated sandbox run of the focused suite produced 1 failure and
  82 passes; the sole failure was the known nested-pip socket denial in
  `test_installed_wheel_path_resolution_from_unrelated_cwd`, not a
  Control Room behavior failure.
- The real Mission 1-4 evidence parse fingerprint remained unchanged:
  Mission 1 exposes Validation, Independent Review, and CI; Missions 2-4
  expose Validation and Independent Review, with CI absent.
- **Broad regression**: not rerun for this focused correction round. The
  previous Mission 5 broad gate remains the mission-level regression
  evidence.
- **Route verification**: runtime route introspection showed only
  `GET /`, `GET /api/projects`, and `GET /api/projects/{project_id}`.
- **Mutation scan**: `src/control_room` contains no Mission 5 write path,
  filesystem-write route, execution capability, database write,
  POST/PUT/PATCH/DELETE route, mission editing, checkpoint creation,
  automation, Resolve, Hermes, Context Engine, agent integration, or
  CI-repair capability.

## Independent Review

Independent Codex review initially found one blocking parser issue:
Markdown headings inside fenced code blocks were being treated as real
document headings. The correction round replaced regex-only section
extraction with a deterministic fence-aware Markdown line scanner and
added regressions for tilde fences, fake fenced Validation headings, and
backtick fences. Focused same-directory read-only re-review returned:
PASS -- focused correction accepted.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No V1 tag was created, moved, or deleted during
Mission 5.

## Deferred Work

Explicitly out of scope for Mission 5, unchanged by this closure:

- Additional projects or project auto-discovery.
- Additional Control Room screens beyond Projects and Project Detail.
- Mission creation, mission editing, checkpoint creation, validation
  reruns, CI repair, or a history database/event log.
- Context Engine, agent routing, Hermes integration, automation of any
  kind.
- Resolve, render, episode, asset, archive, or production controls.
- Broad CI portability/stale-test repair and unrelated installed-package
  smoke debt.

## Closure

Control Room V0 Mission 5 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
