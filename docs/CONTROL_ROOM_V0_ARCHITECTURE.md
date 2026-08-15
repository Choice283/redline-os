# Control Room V0 Architecture

Control Room V0 is the first, smallest approved slice of a Redline OS
"Control Room" instrument panel: a local, read-only Projects screen
(Mission 1) plus a read-only Project Detail screen reached from it
(Mission 3), which in turn shows a read-only Mission & Checkpoint
History section derived from durable closure documents (Mission 4), each
entry of which can be expanded into a read-only Validation & Evidence
Detail drill-down (Mission 5) and a read-only Mission Scope & Outcome
Detail drill-down (Mission 6). This document is architecture and V0
scope only — it does not authorize any work beyond what Missions 1, 3,
4, 5, and 6 implement.

## Purpose

Give Paul a single local screen that shows, for each registered project,
whether it needs his attention right now — combining live local Git truth
with durable, version-controlled operational meaning. Control Room is an
instrument panel, not a steering wheel: it never mutates anything.

## Project definition

For Control Room purposes, a **Project** is a software/automation
workspace managed by Redline Control Room and anchored to a local Git
repository plus durable project-state information.

V0 registers exactly one project: **Redline OS**. `RLC-E9901` and other
episode/production proofs are not Control Room Projects — those are
episodes managed *by* Redline OS, a different concept that V0 does not
model.

## Source-of-truth model

Git supplies machine truth. The Project State record supplies
human/operational meaning. Control Room combines them but owns neither.

| Source | Owns | Read by |
|---|---|---|
| Local Git repository | Branch, HEAD, working-tree condition, local tracking-ref comparison; also whether a *historical* checkpoint SHA resolves | `control_room.git_reader.GitReader`, live, on every request |
| `docs/control_room/PROJECT_STATE.yaml` (per project) | *Current* mission, latest checkpoint, validation posture, semantic attention flag — never a history log | `control_room.state_reader.StateReader`, on every request |
| `docs/control_room/MISSION_*_CLOSURE_*.md` (per closed mission) | Historical mission record: title, closure statement, published checkpoint SHA, Validation/Independent Review/CI evidence text, and Purpose/Delivered Capability/Deferred Work scope-and-outcome text | `control_room.mission_history_reader.MissionHistoryReader`, on every request |
| `config/control_room/projects.yaml` | Which projects exist and where their repository/state file live | `control_room.project_registry.ProjectRegistry`, on every request |

Global repository source-of-truth priority (unchanged by this feature):
repository > Git state > tests/production evidence > checkpoints >
durable documentation > agent reports > conversation memory.

A locally-known tracking comparison (ahead/behind/diverged against the
configured upstream) proves only local knowledge of that ref. Control
Room V0 never runs `git fetch`, so this is never "GitHub verified" or
"remote verified" — only "locally known."

## Component boundaries

```
config/control_room/projects.yaml   -- registry (which projects, where)
docs/control_room/PROJECT_STATE.yaml -- per-project current semantic state
docs/control_room/MISSION_*_CLOSURE_*.md -- per-mission historical closure record

src/control_room/
  models.py                  -- typed Pydantic schema for all of the above
  git_reader.py               -- read-only Git subprocess adapter -> GitStatus
  state_reader.py              -- YAML + schema validation -> ProjectState
  mission_history_reader.py    -- discovers + parses closure docs -> list[MissionHistoryEntry],
                                   including verbatim Validation/Independent Review/CI
                                   section text (Validation & Evidence Detail) and
                                   Purpose/Delivered Capability/Deferred Work section
                                   text (Mission Scope & Outcome Detail), via a
                                   fence-aware level-2-heading scanner
  project_registry.py          -- YAML + schema validation -> ProjectDefinition list
  project_status_service.py    -- composes registry + Git + state + history into
                                   ProjectSnapshot, derives the combined `attention`
                                   signal and per-history-entry checkpoint resolution
  app.py                       -- FastAPI boundary; routes call only the service
  static/                      -- plain HTML/CSS/JS Projects + Project Detail
                                   screens (client-side hash routing, no
                                   separate HTML route per screen), including
                                   the Mission & Checkpoint History section and its
                                   per-entry Mission Scope & Outcome Detail and
                                   Validation & Evidence Detail <details> drill-downs
```

The web layer (`app.py`, `static/*`) never runs a Git subprocess and never
parses YAML directly — it only calls `ProjectStatusService` and renders
whatever `ProjectSnapshot` it returns, including degraded states.

## Registry role

`config/control_room/projects.yaml` answers exactly one question: *which
projects should Control Room display?* It declares each project's `id`,
`name`, `repository` path, and `state_file` path. It must never duplicate
live Git status or semantic project state — both are read fresh from
their own sources on every request.

## Path resolution and deployment

**Control Room V0 requires an existing Redline OS repository checkout — it
is not, and architecturally cannot be, a self-contained installed package**
(Codex review "Prove the path design under an installed wheel": Option A,
chosen over Option B). Its whole purpose is reading a real checkout's live
Git state (`GitReader` shells out to `git` against a real `.git` directory);
`.git/` is never packaged into a wheel, so no amount of bundling
`config/`/`docs/` into the package could make `GitStatus` self-contained.
Determined empirically, not assumed: a real wheel built and installed into
a fresh venv, launched from a directory unrelated to any Redline OS
checkout, has `_PACKAGE_ROOT` resolve into that venv's `site-packages`
tree — see `tests/unit/control_room/test_installed_wheel_path_resolution.py`.

Registry, repository, and state-file resolution is anchored deterministically
rather than to the launching process's current working directory (Codex
review Finding 3). `app._resolve_base_dir()` picks, in order: an explicit
argument, the `REDLINE_CONTROL_ROOM_ROOT` environment variable, or
`_PACKAGE_ROOT` — the directory the installed `control_room` package's own
source lives in (`src/control_room/app.py`'s grandparent directory). For an
editable dev install that *is* the real Redline OS checkout, so `python -m
control_room.app` finds it correctly from any CWD — this is the normal
development path and needs no configuration. For a real installed
(non-editable) wheel, `_PACKAGE_ROOT` resolves into site-packages, which
correctly has no `config/control_room/projects.yaml`, so
`REDLINE_CONTROL_ROOM_ROOT` must be set explicitly to the checkout's path.
`main()` runs `_preflight_registry_check()` before binding a socket: a
`RegistryError` (registry genuinely unlocatable) raises `SystemExit` with a
message naming `REDLINE_CONTROL_ROOM_ROOT` explicitly, so a misconfigured
installed-wheel launch fails immediately and clearly rather than starting a
server that would only 503 on the first request. (A missing/invalid
`PROJECT_STATE.yaml` or a dirty working tree are not preflight failures —
those are normal, displayable degraded `ProjectSnapshot` states, not reasons
to refuse to start.) Either way — preflight failure or a 503 from a route
called directly — an installed `redline-control-room` launched from an
unrelated directory can never silently reinterpret that directory as the
Redline OS project. `REDLINE_CONTROL_ROOM_REGISTRY` overrides the registry
path itself; if given as a relative path it resolves against the same
anchor, never against CWD. This is deliberately not project auto-discovery:
there is no search or heuristic guessing, only a fixed, documented default
location plus one explicit override variable.

FastAPI/uvicorn (the `control_room` extra) are imported lazily inside
`_import_fastapi()`/`main()`, not at module import time (Codex review
Finding 2) — `redline-control-room` is always installed by the base
package, but running it without the `control_room` extra installed raises
one clear `ImportError` naming the fix, mirroring
`mcp_server.server.create_server()`'s existing deferred-import convention
for its own optional `mcp` extra, rather than a raw import traceback.

## Project-state role

`docs/control_room/PROJECT_STATE.yaml` stores only semantic/operational
meaning: current mission, latest checkpoint reference, validation
posture, and an explicit semantic `attention` flag. It never stores
current Git branch, working-tree status, HEAD, ahead/behind counts, or
tracking synchronization — those come from live Git only. If the code and
this document ever appear to disagree on that boundary, the code (and
`models.ProjectState`, which has no such fields) is authoritative.

## Git role

`GitReader` runs a fixed set of read-only `git` subprocess calls
(`rev-parse --is-inside-work-tree`, `rev-parse HEAD`, `branch
--show-current`, `status --porcelain`, `rev-parse --abbrev-ref
--symbolic-full-name @{u}`, `rev-list --left-right --count HEAD...@{u}`,
and `cat-file -e <sha>^{commit}` to verify a checkpoint reference) against
an explicit `cwd`, using argument arrays rather than shell strings so
Windows paths containing spaces resolve correctly. It never runs a
mutating or network Git command (no add, commit, checkout, switch, reset,
clean, stash, fetch, pull, push, merge, rebase, or tag).

## Read-only guarantees

Control Room V0 may read Git, YAML, and repository files. It may not
modify project state, modify repository files through the UI, run
Resolve, start renders, invoke any agent, create missions or checkpoints,
commit changes, or repair CI. There are no mutation routes in `app.py`
(no POST/PUT/PATCH/DELETE on `/api/projects*`), and the frontend issues
only `GET /api/projects` (Projects screen) and
`GET /api/projects/{project_id}` (Project Detail screen).

## API boundary

- `GET /` — the Projects screen (static HTML/CSS/JS).
- `GET /api/projects` — `list[ProjectSnapshot]` for every registered project.
- `GET /api/projects/{project_id}` — a single `ProjectSnapshot`, 404 if the id is not in the registry.

Only registry-listed project ids are reachable through the API — the
routes never accept an arbitrary filesystem path. The server binds to
`127.0.0.1` by default; it is not exposed to the LAN.

## Frontend navigation

The Project Detail screen (Mission 3) is pure client-side view selection
inside the single page `GET /` already serves — it does not add a second
HTML route. `static/index.html` declares two `<main>` containers
(`#projects`, `#detail`); `static/app.js` toggles which is visible based
on `location.hash`:

- No hash, or any hash not matching `#/projects/<id>` — the Projects
  screen is shown, and `GET /api/projects` is (re)fetched.
- `#/projects/<id>` — the Project Detail screen is shown, and
  `GET /api/projects/{project_id}` is fetched for that id.

Each project card rendered on the Projects screen is a link
(`<a class="card" href="#/projects/<id>">`) to that project's detail
hash; the Detail screen renders a `← Back to Projects` link back to `#/`.
A `hashchange` listener re-renders on navigation. This reuses the
existing `GET /api/projects/{project_id}` endpoint exactly as-is — no new
backend route and no new query parameter. Mission 4 later extends the
same `ProjectSnapshot` response with `mission_history`, still without
adding a separate history route.

## Mission & Checkpoint History

The Project Detail screen's Mission & Checkpoint History section (Mission
4) shows every historical Control Room mission, derived fresh on every
request — never persisted, never cached, never stored in
`PROJECT_STATE.yaml`, which remains a current-state record only, not an
event log.

`MissionHistoryReader.read(history_dir, repository_path)`:

1. **Discovers** candidate files by scanning `history_dir` (the directory
   the registry's already-configured `state_file` lives in — the same
   `docs/control_room/` anchor, not a second hardcoded path) for names
   matching `MISSION_<n>_CLOSURE_<YYYY-MM-DD>.md`. The filename is used
   only to enumerate candidates and is never trusted as data on its own.
2. **Parses** each matching file's content deterministically: the H1
   heading for the mission title, the `## Published Checkpoint` section's
   `SHA:` line for the checkpoint commit, and a literal `is formally
   closed.` statement for completion status. `closure_date` is the one
   documented exception sourced from the filename rather than content,
   because no closure document currently encodes its own date as a
   content field; if the filename's date segment is missing or not a
   valid calendar date, `closure_date` is `None`. All level-2-section
   extraction (checkpoint SHA, and every field described under
   "Validation & Evidence Detail" and "Mission Scope & Outcome Detail"
   below) goes through one fence-aware line scanner,
   `_extract_section_body()`: it tracks entry/exit of active
   triple-backtick or triple-tilde Markdown fences and never treats a
   `##`-heading-shaped line inside one as a real section boundary — a
   closure document that quotes a fake `## Validation` heading inside a
   fenced example (as this very mechanism's own regression tests do)
   cannot fool the parser into truncating or misattributing a section.
3. **Never invents a value.** A file that cannot be read, or whose
   content does not match the expected structure, yields a
   `MissionHistoryEntry` with `parse_error` describing exactly what could
   not be determined — never raising, and never causing other entries or
   the Detail screen to fail to render.
4. **Orders deterministically** by `(mission_number is None,
   mission_number, closure_document)` — ascending mission number first,
   with any entry whose number could not be determined sorted last by
   filename, never by filesystem iteration order.

`ProjectStatusService` then resolves each entry's `checkpoint_resolved`
field live via the same `GitReader.commit_exists()` already used to
validate the *current* `latest_checkpoint` — `True`/`False` if the
repository is valid, `None` if it could not be determined (mirroring the
existing checkpoint-validation precedent exactly, applied to historical
checkpoints too). The result is embedded in the existing `ProjectSnapshot`
response as `mission_history: list[MissionHistoryEntry]` — **no new
backend route was added**; both `GET /api/projects` and
`GET /api/projects/{project_id}` already carry it.

## Validation & Evidence Detail

Each Mission & Checkpoint History entry can be expanded (a native HTML
`<details>`/`<summary>` disclosure, no JavaScript state, no new route,
no new hash segment) into a read-only Validation & Evidence Detail view
(Mission 5) — the drill-down is
`Projects → Project Detail → Mission & Checkpoint History → Validation & Evidence Detail`.

`MissionHistoryReader` extracts the verbatim body text of each closure
document's `## Validation`, `## Independent Review`, and `## CI`
sections (whichever are present — reusing the same generic level-2-
section-boundary extraction already used for `## Published Checkpoint`,
now factored into `_extract_section_body()`), exposed as
`MissionHistoryEntry.validation_section` /
`.independent_review_section` / `.ci_section`.

**Deliberately not further decomposed.** Mission 5 does not attempt to
parse a discrete "test count," "validation status" enum, or "review
verdict" out of that prose. Across the four closure documents that exist
today, the wording differs mission to mission — "Claude focused
validation" (Mission 1) vs. "Focused Control Room suite" (Missions 3–4);
Mission 1's Independent Review verdict is a bolded standalone line,
Mission 4's is embedded in a paragraph. A regex tuned to today's wording
would either miss real evidence for at least one mission or need
constant re-tuning as phrasing drifts — either way, a bad tradeoff
against "do not invent missing evidence." Showing each section's actual
text is the reading of proven evidence this mission requires; a reader
who wants the verdict reads it directly, in the words the mission
recorded it in.

**Absence is not malformation.** A closure document missing `## CI`
(true for every mission except Mission 1, which alone recorded an
authoritative external CI run) is not a `parse_error` — `ci_section` is
simply `None`, rendered as an explicit "No ci section recorded in this
closure document" message. Only title/checkpoint/closure-statement
problems set `parse_error`; a legitimately absent optional evidence
section does not.

**No arbitrary file access.** Evidence extraction reads exactly the same
file `MissionHistoryReader.read()` already opened to parse the title and
checkpoint SHA — there is no second file lookup, no path built from a
project id or any other user-controlled input, and discovery itself
never recurses into subdirectories (`Path.iterdir()`, not `rglob()`) or
follows a path outside the registry-configured `docs/control_room/`
directory.

**No re-execution.** This section reads what was proven; it does not
prove it again. No historical test, checkpoint, or review is rerun —
the text shown is exactly what a past mission's closure recorded,
nothing more current and nothing synthesized.

## Mission Scope & Outcome Detail

Each Mission & Checkpoint History entry can also be expanded (a second
native `<details>`/`<summary>` disclosure, alongside Validation &
Evidence Detail — same mechanism, no new route, no new hash segment)
into a read-only Mission Scope & Outcome Detail view (Mission 6) — the
drill-down is
`Projects → Project Detail → Mission & Checkpoint History → Mission Scope & Outcome Detail`.

`MissionHistoryReader` extracts the verbatim body text of each closure
document's `## Purpose`, `## Delivered Capability`, and `## Deferred
Work` sections through the identical fence-aware `_extract_section_body()`
call used for `## Published Checkpoint` and the Mission 5 evidence
sections, exposed as `MissionHistoryEntry.purpose_section` /
`.delivered_capability_section` / `.deferred_work_section`.

**Same discipline as Validation & Evidence Detail, applied here too:**

- **Not synthesized.** Mission 6 does not derive a success score,
  capability count, remaining-work count, priority, next mission, or
  recommended action from this text. It is shown exactly as the closure
  document recorded it.
- **Absence is not malformation.** A closure document missing one of
  these three optional sections yields `None` for that field, rendered
  as an explicit "No \<section\> section recorded in this closure
  document" message — never `parse_error`, which remains reserved for
  title/checkpoint/closure-statement problems only.
- **No arbitrary file access.** Same file, same discovery boundary, same
  non-recursive `docs/control_room/` scan as every other field
  `MissionHistoryReader` produces — no path is ever built from a project
  id, heading name, or any other user-controlled input.
- **No re-execution.** Nothing here reruns a test, a checkpoint, or a
  review; it reads three more named sections of the same already-open
  closure document.

Verified against all five real, committed closure documents
(`tests/unit/control_room/test_mission_history_reader.py::test_real_mission_1_through_5_closure_documents_parse_scope_outcome_cleanly`):
Missions 1–5 all carry non-empty `## Purpose`, `## Delivered Capability`,
and `## Deferred Work` sections and parse with no `parse_error`.

## Attention derivation

`ProjectStatusService` derives a combined `attention` signal from
deterministic facts, distinct from `ProjectState.attention` (the
semantic-only flag authored in YAML):

- Git repository missing, not a Git repository, or a Git read failure
- a dirty working tree
- a diverged tracking state, or a tracking read failure
- the project state file being missing, malformed, or schema-invalid
- the latest checkpoint's commit not resolving in the repository
- the semantic `attention.required` flag being set in `PROJECT_STATE.yaml`

Raw classifications are preserved rather than flattened into one
red/green status — e.g. a documented `pass_with_exception` validation
result and a `CLEAN`/`SYNCHRONIZED` Git state can coexist without
producing a false "action required," and a dirty working tree does not
get silently absorbed into a validation summary that claims otherwise.

## V0 non-goals

No Claude/Codex/Hermes runtime integration, no agent routing or chat UI, no
Context Engine, no automatic Mission Cards or checkpoints, no Obsidian
integration, no Control Room database or history/evidence table (mission
history, validation evidence, and mission scope/outcome text are all
parsed fresh from closure documents on every request, never stored), no
automatic historical test or evidence reruns, no derived scoring or
classification of historical outcomes (no success score, capability
count, remaining-work count, priority, next-mission, or recommended
action), no Resolve or render controls, no Episode/Asset/Archive Manager
UI, no remote hosting, no authentication, no notifications, no
WebSockets, no project discovery, no plugin architecture, no CI repair,
and no work on RLC-E9001, Archive follow-on, or MCP parity. No
`git fetch` — all tracking comparisons are local-only.

## Failure / degraded-state behavior

Every field Control Room cannot resolve degrades explicitly rather than
being invented or causing a crash:

- An invalid/missing/inaccessible repository path yields `GitStatus.repository_valid = False` with `working_tree`/`tracking = NOT_A_REPOSITORY` and a diagnostic in `error`.
- A Git command failure, timeout, or missing `git` executable yields `ERROR` classifications with a diagnostic in `error`; nothing is inferred.
- A missing, malformed, or schema-invalid `PROJECT_STATE.yaml` yields `ProjectSnapshot.state = None` with `state_error` set, and folds into `attention` — it never causes the whole Projects screen to fail to render.
- A missing or malformed registry raises `RegistryError`, surfaced as an HTTP 503 with the diagnostic message (not a silent empty list).
- The frontend renders whatever the API returns, including `UNKNOWN`/`ERROR` values and a missing `state`, rather than assuming success — on both the Projects screen and the Project Detail screen, and including a project id with no matching registry entry (`404`, rendered as an explicit "not found" message, never a synthesized snapshot).
- A missing `docs/control_room/` directory yields an empty `mission_history` list, not an error.
- A closure document whose title, checkpoint SHA, or closure statement cannot be parsed yields a `MissionHistoryEntry` with `parse_error` set describing exactly what was missing, rendered as visible red text under that entry — it does not prevent other, well-formed entries from rendering.
- A historical checkpoint SHA that does not resolve in the repository is rendered with an explicit "does not resolve in repository" note next to it, exactly like the current `latest_checkpoint` case — never silently treated as valid.
- A closure document with no `## Validation`, `## Independent Review`, or `## CI` section yields `None` for that field, rendered as an explicit "No \<section\> section recorded in this closure document" message — never blank, never invented, and not itself a `parse_error` (absence of an optional evidence section is not malformation).
- The same rule applies to `## Purpose`, `## Delivered Capability`, and `## Deferred Work` — a closure document missing any of these yields `None`, rendered the same explicit "not recorded" way, never a `parse_error`.
- A `##`-heading-shaped line inside an active triple-backtick or triple-tilde fence is never treated as a real section boundary for any of the fields above — fenced example text containing a fake heading cannot truncate, extend, or misattribute a section.

## Future extension boundary

Nothing in this document authorizes work beyond Mission 1 (Projects
screen), Mission 3 (Project Detail screen, reached by selecting a project
card), Mission 4 (Mission & Checkpoint History section on the Detail
screen), Mission 5 (Validation & Evidence Detail drill-down per history
entry), and Mission 6 (Mission Scope & Outcome Detail drill-down per
history entry). Any further Control Room capability (additional
projects, project auto-discovery, additional screens, a history or
evidence database, automatic historical test/evidence reruns, derived
scoring or classification of historical outcomes, agent integration,
mutation of any kind, Resolve contact) requires a separate, explicitly
authorized mission per `CLAUDE.md` — Control Room V0 does not pre-approve
its own successors.
