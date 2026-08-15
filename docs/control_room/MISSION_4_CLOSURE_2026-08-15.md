# Control Room V0 Mission 4 Closure

## Purpose

Mission 4 added a read-only Mission & Checkpoint History section to the
existing Control Room Project Detail screen. The section shows completed
Control Room missions from durable closure documents under
`docs/control_room/`, with checkpoint SHA resolution checked live against
the local repository. It remains an instrument panel, not a steering
wheel: no mutation route, database, history table, checkpoint creation,
mission editing, agent integration, or automation was introduced.

## Published Checkpoint

SHA:
`04c17b41a7194bb5ec271a740202e05728bf39a0`

Subject:
`feat: add Control Room V0 mission history`

Parent:
`f67305d2fd18a9bef2ad276bdb5a9d9c9441e16b`

## Delivered Capability

- Added `control_room.mission_history_reader.MissionHistoryReader`, a
  read-only parser that discovers direct children of `docs/control_room/`
  matching `MISSION_<n>_CLOSURE_<YYYY-MM-DD>.md`.
- Added `MissionHistoryEntry` and embedded `mission_history` in the
  existing `ProjectSnapshot` response. No new backend route was added;
  the Detail screen continues to use `GET /api/projects/{project_id}`.
- Historical mission title, mission number, completion status, published
  checkpoint SHA, closure document path, and closure date are derived from
  durable closure records. `PROJECT_STATE.yaml` remains current semantic
  state only, never the history store.
- Checkpoint SHA parsing is scoped to the `## Published Checkpoint`
  section, so unrelated earlier SHA blocks cannot be mistaken for the
  published checkpoint.
- Each historical checkpoint is resolved live via
  `GitReader.commit_exists` against the configured repository. Unresolved
  or unknown checkpoints are surfaced explicitly rather than treated as
  valid.
- History ordering is deterministic by numeric mission number, then
  closure document, so Mission 10 sorts after Mission 2.
- Malformed or incomplete closure records degrade into visible
  `parse_error` entries without preventing other records from rendering.
- The Project Detail frontend renders the history section, unresolved
  checkpoint notes, parse errors, closure document paths, and closure
  dates safely with HTML escaping and no editing controls.
- `README.md` and `docs/CONTROL_ROOM_V0_ARCHITECTURE.md` now document the
  Mission & Checkpoint History source-of-truth boundary, discovery rules,
  no-database/no-route scope, and failure behavior.

## Source-of-Truth Boundary

- **Git = machine truth.** Live branch, HEAD, working-tree/tracking state,
  and historical checkpoint resolution are read from the configured local
  repository on every request.
- **`PROJECT_STATE.yaml` = current semantic state only.** It records the
  current mission/checkpoint/validation posture and does not store mission
  history.
- **Closure documents = historical mission records.** Mission history is
  parsed fresh from `docs/control_room/MISSION_*_CLOSURE_*.md`.
- **The web layer never reads files, runs Git, or parses YAML directly.**
  It only renders `ProjectSnapshot` data returned by
  `ProjectStatusService`.

## Validation

- **Focused Control Room suite**:
  `.\.venv-codex\Scripts\python.exe -m pytest tests/unit/control_room -q -p no:cacheprovider`
  passed under intended dependency/network conditions: 69 passed in
  38.65s.
- A non-escalated sandbox run produced 1 failure and 68 passes; the sole
  failure was the known nested-pip socket denial in
  `test_installed_wheel_path_resolution_from_unrelated_cwd`, not a
  Control Room behavior failure.
- **Broad regression**:
  `.\.venv-codex\Scripts\python.exe -m pytest tests/unit -q -p no:cacheprovider`
  produced 2695 passed, 18 skipped, 28 failed, 6 warnings. The failures
  were classified as pre-existing/non-Mission-4 families: Windows YAML
  temp-config path escaping, installed-package dependency smoke issues,
  and one Python/native-process identity expectation.
- **Route verification**: runtime route introspection showed only
  `GET /`, `GET /api/projects`, and `GET /api/projects/{project_id}`.
- **Mutation scan**: `src/control_room` contains no Mission 4 write path,
  database write, POST/PUT/PATCH/DELETE route, mission editing,
  checkpoint creation, or automation capability.

## Independent Review

Independent Codex review found one important checkpoint-parsing issue and
two notes. The correction round fixed the checkpoint parser to read only
from `## Published Checkpoint`, added the unrelated-earlier-SHA regression
test, added the Mission 10 numeric-ordering test, and corrected stale
architecture wording. A focused same-directory read-only re-review then
returned: PASS READY FOR CHECKPOINT.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No V1 tag was created, moved, or deleted during
Mission 4.

## Deferred Work

Explicitly out of scope for Mission 4, unchanged by this closure:

- Additional projects or project auto-discovery.
- Additional Control Room screens beyond Projects and Project Detail.
- Mission creation, mission editing, checkpoint creation, or a history
  database/event log.
- Context Engine, agent routing, Hermes integration, automation of any
  kind.
- Resolve, render, episode, asset, archive, or production controls.
- CI portability/stale-test repair and unrelated installed-package smoke
  debt.

## Closure

Control Room V0 Mission 4 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
