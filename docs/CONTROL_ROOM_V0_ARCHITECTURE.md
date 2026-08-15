# Control Room V0 Architecture

Control Room V0 is the first, smallest approved slice of a Redline OS
"Control Room" instrument panel: a local, read-only Projects screen
(Mission 1) plus a read-only Project Detail screen reached from it
(Mission 3). This document is architecture and V0 scope only — it does
not authorize any work beyond what Mission 1 and Mission 3 implement.

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
| Local Git repository | Branch, HEAD, working-tree condition, local tracking-ref comparison | `control_room.git_reader.GitReader`, live, on every request |
| `docs/control_room/PROJECT_STATE.yaml` (per project) | Current mission, latest checkpoint, validation posture, semantic attention flag | `control_room.state_reader.StateReader`, on every request |
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
docs/control_room/PROJECT_STATE.yaml -- per-project semantic state

src/control_room/
  models.py                  -- typed Pydantic schema for all of the above
  git_reader.py               -- read-only Git subprocess adapter -> GitStatus
  state_reader.py              -- YAML + schema validation -> ProjectState
  project_registry.py          -- YAML + schema validation -> ProjectDefinition list
  project_status_service.py    -- composes the three into ProjectSnapshot,
                                   derives the combined `attention` signal
  app.py                       -- FastAPI boundary; routes call only the service
  static/                      -- plain HTML/CSS/JS Projects + Project Detail
                                   screens (client-side hash routing, no
                                   separate HTML route per screen)
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
backend route, no new query parameter, no new response field.

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

No Claude/Codex/Hermes integration, no agent routing or chat UI, no
Context Engine, no automatic Mission Cards or checkpoints, no Obsidian
integration, no Control Room database, no Resolve or render controls, no
Episode/Asset/Archive Manager UI, no remote hosting, no authentication,
no notifications, no WebSockets, no project discovery, no plugin
architecture, no CI repair, and no work on RLC-E9001, Archive follow-on,
or MCP parity. No `git fetch` — all tracking comparisons are local-only.

## Failure / degraded-state behavior

Every field Control Room cannot resolve degrades explicitly rather than
being invented or causing a crash:

- An invalid/missing/inaccessible repository path yields `GitStatus.repository_valid = False` with `working_tree`/`tracking = NOT_A_REPOSITORY` and a diagnostic in `error`.
- A Git command failure, timeout, or missing `git` executable yields `ERROR` classifications with a diagnostic in `error`; nothing is inferred.
- A missing, malformed, or schema-invalid `PROJECT_STATE.yaml` yields `ProjectSnapshot.state = None` with `state_error` set, and folds into `attention` — it never causes the whole Projects screen to fail to render.
- A missing or malformed registry raises `RegistryError`, surfaced as an HTTP 503 with the diagnostic message (not a silent empty list).
- The frontend renders whatever the API returns, including `UNKNOWN`/`ERROR` values and a missing `state`, rather than assuming success — on both the Projects screen and the Project Detail screen, and including a project id with no matching registry entry (`404`, rendered as an explicit "not found" message, never a synthesized snapshot).

## Future extension boundary

Nothing in this document authorizes work beyond Mission 1 (Projects
screen) and Mission 3 (Project Detail screen, reached by selecting a
project card). Any further Control Room capability (additional projects,
project auto-discovery, additional screens, agent integration, mutation
of any kind, Resolve contact) requires a separate, explicitly authorized
mission per `CLAUDE.md` — Control Room V0 does not pre-approve its own
successors.
