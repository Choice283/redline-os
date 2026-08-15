# Control Room V0 Mission 3 Closure

## Purpose

Mission 3 added a dedicated, read-only Project Detail screen for Redline
OS, reached by selecting the project card on the existing Projects
screen, with navigation back to the Projects screen. It is an instrument
panel extension, not a steering wheel — no mutation routes exist
anywhere in the implementation, and no new backend route was added at
all.

## Published Checkpoint

SHA:
`8f20ac48aedda97fe0a6d228a46f3a9fa3b510d2`

Subject:
`feat: add Control Room V0 Project Detail screen`

Parent:
`b752d03f419c98b20b76b6dc0e9d4b4a30681ef7`

## Delivered Capability

- Each project card on the Projects screen (`static/app.js`,
  `renderProject()`) is now a link (`<a class="card" href="#/projects/<id>">`)
  to that project's Detail screen.
- A dedicated, read-only Project Detail screen renders the full
  `ProjectSnapshot` for the selected project: name, summary, attention
  state, live Git branch/HEAD/working-tree/tracking condition, current
  mission, latest checkpoint, and validation status/summary
  (`renderProjectDetail()`, reusing the existing
  `renderGitStatus()`/`renderState()` helpers verbatim).
- A `← Back to Projects` link returns to the Projects screen (`#/`).
- Implemented as pure client-side hash routing (`#/projects/<id>`)
  inside the single page `GET /` already serves — `static/index.html`
  gained a second `<main id="detail" hidden>` container;
  `static/app.js` toggles visibility on `hashchange` and (re)fetches the
  relevant endpoint. **No new backend route was added.** The Detail
  screen calls the existing `GET /api/projects/{project_id}` endpoint
  exactly as-is — same response shape, same 404-on-unknown-id behavior.
- Degraded/error states are not invented: an unknown project id renders
  an explicit "not found" message (from the existing 404 response); a
  missing/invalid `PROJECT_STATE.yaml` renders the existing
  "Project state unavailable" message via `renderState()`; Git read
  errors render via the existing `renderGitStatus()` error text — all
  identical to the Projects-screen precedent, reused rather than
  reinvented.
- `docs/CONTROL_ROOM_V0_ARCHITECTURE.md` gained a `## Frontend
  navigation` section documenting the hash-routing design, and updated
  its intro, component-boundary tree, read-only-guarantees, degraded-
  state, and future-extension-boundary sections to reflect both screens.
- `README.md`'s Control Room section now describes the Detail screen and
  its navigation.

## Source-of-Truth Boundary

Unchanged from Mission 1/2:

- **Git = machine truth.** Read live via `GitReader` on every request,
  including every Detail-screen fetch.
- **`PROJECT_STATE.yaml` = semantic/operational truth.**
- **The web layer never runs Git or parses YAML directly** — the Detail
  screen, like the Projects screen, only calls
  `ProjectStatusService` (via the existing `GET /api/projects/{project_id}`
  route) and renders whatever `ProjectSnapshot` it returns.

## Validation

- **Focused Control Room suite**: `pytest tests/unit/control_room` — 52
  passed (46 pre-existing + 6 new in
  `tests/unit/control_room/test_detail_view.py`, covering: the served
  shell includes the detail container; served `app.js` wires up card
  navigation and hash routing; `GET /api/projects/{project_id}` returns
  every field the Detail screen renders; that same endpoint surfaces a
  missing-state degraded snapshot rather than inventing one; unknown
  project ids return 404 rather than a synthetic snapshot; and no
  mutation-capable route exists anywhere in the app).
- **Broad regression**: `pytest tests/unit` (17 pre-existing collection
  errors from an unrelated stray `cli` package in user site-packages
  excluded, matching Mission 1's documented exclusion) — 2458 passed, 18
  skipped, 4 failed. All 4 failures are pre-existing and
  environment-specific, none touching `control_room`:
  `test_installed_cli_asset_list_smoke.py`,
  `test_installed_mcp_startup_smoke.py`, `test_installed_wheel_smoke.py`,
  and `test_phase14_resolve_context_snapshot.py` (native-process-helper
  "identity mismatch" under PowerShell). Pass/skip/fail counts match
  Mission 1's documented baseline (2452/18/4) plus exactly the 6 tests
  Mission 3 adds — zero regressions.
- **Live browser verification**: ran the server locally
  (`python -m control_room.app`), confirmed in a real browser that
  clicking a project card navigates to the Detail screen showing every
  required field, the `← Back to Projects` link returns to the Projects
  screen (`document.getElementById('detail').hidden` /
  `document.getElementById('projects').hidden` toggled correctly), and
  navigating directly to `#/projects/does-not-exist` renders the
  explicit not-found message rather than any invented data.
- Confirmed zero mutation routes: `grep` for
  `@app.post|@app.put|@app.patch|@app.delete` and any `.post(`/`.put(`/
  `.patch(`/`.delete(` call across `src/control_room` — no matches.

## Independent Review

Not performed. Codex independent review was authorized only if justified
by implementation risk or findings; the implementation stayed within the
authorized scope (no new backend route, no new dependency, no schema
change) and no findings emerged that warranted it.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No tag was created, moved, or deleted during
Mission 3.

## Deferred Work

Explicitly out of scope for Mission 3, unchanged by this closure:

- Additional projects, project auto-discovery.
- Additional Control Room screens beyond Projects and Project Detail.
- Context Engine, agent routing, Hermes integration, automation of any
  kind.
- Resolve, render, episode, asset, archive, or production controls.
- CI portability/stale-test repair (still the pre-existing debt
  documented in Mission 1's closure and confirmed unchanged by the broad
  regression run above).

## Closure

Control Room V0 Mission 3 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
