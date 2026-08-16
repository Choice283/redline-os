# Control Room V0 Architecture

Control Room V0 is the first, smallest approved slice of a Redline OS
"Control Room" instrument panel: a local, read-only Projects screen
(Mission 1) plus a read-only Project Detail screen reached from it
(Mission 3), which in turn shows a read-only Mission & Checkpoint
History section derived from durable closure documents (Mission 4), each
entry of which can be expanded into a read-only Validation & Evidence
Detail drill-down (Mission 5), a read-only Mission Scope & Outcome
Detail drill-down (Mission 6), and a read-only Checkpoint Change Set
Detail drill-down sourced from live Git rather than closure prose
(Mission 7). The Project Detail screen's live GitStatus block itself can
also be expanded into a read-only Current Working Tree Change Detail
drill-down showing the repository's own current, uncommitted change
paths (Mission 8). The Project Detail screen's state/checkpoint area
additionally shows read-only Closed-State Currency: whether the
repository has moved beyond the latest formally closed Control Room
state, derived fresh from local Git history against the recorded
closure document (Mission 9). This document is architecture and V0
scope only — it does not authorize any work beyond what Missions 1, 3,
4, 5, 6, 7, 8, and 9 implement.

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
| Local Git repository | Branch, HEAD, working-tree condition (including the current, uncommitted change paths themselves — Mission 8), local tracking-ref comparison; whether a *historical* checkpoint SHA resolves; the file-path change set of a resolved historical checkpoint commit; and, for Closed-State Currency (Mission 9), the commit that introduced the recorded closure document and its ancestry/commit-count relationship to live HEAD | `control_room.git_reader.GitReader`, live, on every request |
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
                                   (including the current working-tree change
                                   detail, Mission 8, from the same status read
                                   that determines CLEAN/DIRTY), commit_exists(),
                                   read_commit_changed_files() (one resolved
                                   commit's file-path change set),
                                   read_path_introduction_commit() (the single
                                   commit that added a validated path -- Mission 9),
                                   and read_closed_state_currency() (ancestry +
                                   commit-count of a resolved closed-state commit
                                   against live HEAD -- Mission 9)
  state_reader.py              -- YAML + schema validation -> ProjectState
  mission_history_reader.py    -- discovers + parses closure docs -> list[MissionHistoryEntry],
                                   including verbatim Validation/Independent Review/CI
                                   section text (Validation & Evidence Detail) and
                                   Purpose/Delivered Capability/Deferred Work section
                                   text (Mission Scope & Outcome Detail), via a
                                   fence-aware level-2-heading scanner -- never runs Git
                                   (Mission 9's Closed-State Currency composition reuses
                                   this module's discovery output rather than adding a
                                   second closure-file discovery mechanism)
  project_registry.py          -- YAML + schema validation -> ProjectDefinition list
  project_status_service.py    -- composes registry + Git + state + history into
                                   ProjectSnapshot, derives the combined `attention`
                                   signal, per-history-entry checkpoint resolution, and
                                   per-history-entry checkpoint change-set enrichment
                                   (Mission 8's working-tree change detail requires no
                                   composition code here at all -- it rides through
                                   unmodified as part of the GitStatus GitReader.read_status()
                                   already returns); also owns Closed-State Currency's
                                   two-layer closure-path validation
                                   (_validate_canonical_closure_path,
                                   _closure_path_is_proven) and the composition that
                                   turns a validated path into a ClosedStateCurrency
                                   (Mission 9) -- observation only, never fed into
                                   `_derive_attention()`
  app.py                       -- FastAPI boundary; routes call only the service
  static/                      -- plain HTML/CSS/JS Projects + Project Detail
                                   screens (client-side hash routing, no
                                   separate HTML route per screen), including
                                   the Mission & Checkpoint History section and its
                                   per-entry Mission Scope & Outcome Detail,
                                   Validation & Evidence Detail, and Checkpoint Change
                                   Set Detail <details> drill-downs, the Project
                                   Detail screen's own GitStatus-level Current Working
                                   Tree Change Detail <details> drill-down (Mission 8),
                                   and the Project Detail screen's state/checkpoint-area
                                   Closed-State Currency block (Mission 9, plain
                                   <dl>/<dt>/<dd>, no new <details> disclosure)
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
--show-current`, `status --porcelain=v2 -z --untracked-files=all
--renames` (Mission 8; see below), `rev-parse --abbrev-ref
--symbolic-full-name @{u}`, `rev-list --left-right --count HEAD...@{u}`,
`cat-file -e <sha>^{commit}` to verify a checkpoint reference,
`diff-tree --root --no-commit-id --name-only -r -z <sha>` (Mission 7) to
read one resolved commit's file-path change set, `--literal-pathspecs
log --no-renames --format=%H --diff-filter=A HEAD -- <path>` (Mission 9)
to resolve the single commit that added a validated repository-relative
path, `merge-base --is-ancestor <sha> <sha>` (Mission 9) to test ancestry,
and `rev-list --count <sha>..<sha>` (Mission 9) to count commits between
two already-ancestry-proven commits) against an explicit `cwd`, using
argument arrays rather than shell strings so Windows paths containing
spaces resolve correctly, and `-z` (NUL-delimited output) for both
`status` and `diff-tree` so a filename containing a space or newline
cannot be misparsed into two paths. It never runs a mutating or network
Git command (no add, commit, checkout, switch, reset, clean, stash,
fetch, pull, push, merge, rebase, or tag).

**`--no-optional-locks status --porcelain=v2 -z --untracked-files=all
--renames` is one single, authoritative read (Mission 8).**
`_read_working_tree()` issues this exactly once and derives both the
coarse `WorkingTreeStatus` (CLEAN/DIRTY) and the full per-path
`working_tree_changes` detail from that same output — never two
separate `git status` invocations, so the CLEAN/DIRTY pill and the
change-path detail can never disagree about whether the tree is dirty.
`--no-optional-locks` closes off the one narrow way a plain `git status`
can otherwise write to disk (an opportunistic index stat-cache refresh)
as a side effect of what should be a purely read-only call. `--renames`
is passed explicitly so rename detection does not silently depend on a
checkout's local `status.renames`/`diff.renames` configuration. This
single read still has two distinct failure tiers: if the subprocess
itself fails (not
found, timeout, non-zero exit), the whole `GitStatus` degrades via
`_error_status()` exactly as before Mission 8 (branch, HEAD, tracking —
all of it). If the subprocess succeeds but a record in its output does
not match one of the five documented porcelain-v2 shapes (or is a
malformed instance of one), only `working_tree_changes` degrades to
`None` with `working_tree_changes_error` set — branch, HEAD, and
tracking remain intact, since the coarse CLEAN/DIRTY classification
needs only to know whether the raw output is empty, not to decode every
record. `working_tree_changes` is never a partial/best-effort list: any
unrecognized or malformed record (including a `!` ignored-file record,
which can never legitimately appear since `--ignored` is never passed)
invalidates the entire list, mirroring the malformed-output lesson
`read_commit_changed_files()` (Mission 7) already applies to `rev-list`
output.

**`read_commit_changed_files()`'s revision-input boundary.** Every other
`GitReader` call takes no caller-supplied argument beyond the configured
repository path; this one takes a commit SHA, so it is the one place a
value could, in principle, reach `git` as something other than what
Control Room already knows about. Two independent constraints close that
off: (1) the caller (`ProjectStatusService`) only ever passes a SHA
already resolved via `commit_exists()` on this exact same historical
entry, and (2) `read_commit_changed_files()` itself refuses, before
spawning any subprocess, any value that does not match `^[0-9a-f]{7,40}$`
— rejecting a branch name, `HEAD`-relative expression, or a `-`-prefixed
string `git` might otherwise interpret as an option. Control Room never
accepts a Git revision from a request; the only revisions it ever queries
are ones its own closure-document parser already extracted and its own
`GitReader` already verified resolve to a real commit.

**`read_path_introduction_commit()` and `read_closed_state_currency()`'s
input boundaries (Mission 9).** `read_path_introduction_commit(path)`
takes a repository-relative path, not a revision, but that path only
ever reaches this method after both closure-path validation layers
described under "Closed-State Currency" below — never a raw
`PROJECT_STATE.yaml` field value. `--literal-pathspecs` (a top-level Git
option, hence placed before the `log` subcommand) disables Git's own
pathspec-magic parsing entirely, so even a validated-but-adversarial
path string cannot be reinterpreted as `:(exclude)`-style magic. Exactly
one non-empty, full 40-character hex SHA line is accepted as a
successful result; zero lines, more than one line (an ambiguous
addition history), or a malformed line are each a distinct
`UNAVAILABLE`, never a best-effort newest/oldest guess.
`read_closed_state_currency(closed_state_sha, head_sha)` revalidates
both arguments as full 40-character hex SHAs itself, on top of the
service already only ever passing a Git-resolved `closed_state_commit`
and the live `git_status.head_sha` — never a branch name or other
caller-influenced revision reaches `merge-base --is-ancestor` or
`rev-list --count`.

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

## Checkpoint Change Set Detail

Each Mission & Checkpoint History entry can also be expanded into a
third read-only drill-down (same `<details>`/`<summary>` mechanism, no
new route, no new hash segment): Checkpoint Change Set Detail
(Mission 7) — the drill-down is
`Projects → Project Detail → Mission & Checkpoint History → Checkpoint Change Set Detail`.

Unlike Mission Scope & Outcome Detail and Validation & Evidence Detail,
this is **not** closure-document prose — it answers a machine-truth
question the closure document cannot: *which repository files did this
published checkpoint commit actually change?* The answer comes
exclusively from `GitReader.read_commit_changed_files()`, a read-only
`git diff-tree --root --no-commit-id --name-only -r -z <sha>` against the
already-resolved checkpoint SHA (see "Git role" above for the
revision-input boundary). `MissionHistoryReader` never runs Git — this
enrichment happens in `ProjectStatusService._read_mission_history()`,
in the same per-entry loop that already calls `commit_exists()`, exactly
mirroring how the *current* `latest_checkpoint`'s validity is already
established.

**Three distinct, explicit states, exposed as
`MissionHistoryEntry.checkpoint_changed_files` /
`.checkpoint_changes_error` — never conflated:**

- **A normal change set.** `checkpoint_changed_files` is a non-empty list
  of repository-relative paths (e.g. `src/control_room/models.py`);
  `checkpoint_changes_error` is `None`.
- **A legitimately empty change set.** The commit itself changed no
  tracked files (an empty commit, or a genuinely no-op checkpoint).
  `checkpoint_changed_files` is `[]`, `checkpoint_changes_error` is
  `None` — rendered as an explicit "this checkpoint commit changed no
  files" message, never treated as a failure.
- **Unavailable.** The change set could not be determined at all — the
  entry has no checkpoint commit, the checkpoint did not resolve, Git
  failed, or Git timed out. `checkpoint_changed_files` is `None`,
  `checkpoint_changes_error` explains why. This is a dedicated field,
  deliberately separate from closure-document `parse_error` — a Git
  query failure is not a closure-document parsing problem, and the two
  are never overloaded onto one field.

**Scope is deliberately narrow — file paths only.** No diff hunks, no
source-file contents, no added/deleted line counts, no commit author,
email, or message, no blame information, no branch-history graph, no
parent-range comparison, no closure-commit changes, no working-tree
changes, and no untracked files. `git diff-tree --name-only` reports
only paths; nothing else is parsed from its output, and no other Git
command is run to enrich it. A changed file is not treated as proof a
capability succeeded — Mission 7 derives no impact score, risk score,
change score, affected-subsystem label, success verdict, recommended
action, or next mission from this list.

**No arbitrary file access, no arbitrary revision.** The queried commit
is always a SHA this same request already extracted from a closure
document and already verified resolves via `commit_exists()` — never a
user-supplied revision, branch name, or path. `read_commit_changed_files()`
itself additionally refuses anything that is not a plain hex SHA before
spawning a subprocess, independent of what the caller passes.

**No re-execution, no mutation.** `diff-tree` reads two already-existing
tree states; nothing is checked out, staged, committed, or fetched.

Verified against all six real, committed Missions 1–6 checkpoints
(`tests/unit/control_room/test_checkpoint_change_set.py::test_real_mission_1_through_6_checkpoints_have_a_determined_change_set`):
every real checkpoint SHA resolves and yields a non-empty change set with
no `checkpoint_changes_error` and no `parse_error`.

## Current Working Tree Change Detail

The Project Detail screen's own live GitStatus block (not a Mission &
Checkpoint History entry) can be expanded into a read-only Current
Working Tree Change Detail drill-down (Mission 8) — the path is
`Projects → Project Detail → Current Working Tree Change Detail`.

Unlike Checkpoint Change Set Detail, which answers "what did one
*historical, resolved* commit change," this answers a live question
about the repository's *current, uncommitted* state: *which paths are
right now staged, unstaged, untracked, or mid-conflict?* The answer
comes exclusively from `GitReader._read_working_tree()`'s single
`git --no-optional-locks status --porcelain=v2 -z --untracked-files=all
--renames` read (see
"Git role" above), exposed as `GitStatus.working_tree_changes` /
`.working_tree_changes_error`, alongside the `working_tree`
(CLEAN/DIRTY) field that same read already produced. `ProjectStatusService`
requires no new composition code for this field — it rides through
`GitReader.read_status()` unmodified, exactly as `working_tree` itself
always has.

**One record per path, never a flat multi-list.** `working_tree_changes`
is `list[WorkingTreeChange]`, one entry per repository-relative path,
each carrying `path`, `original_path` (set only for a rename/copy),
`index_status`/`worktree_status` (the raw single-character porcelain X/Y
codes, `None` when that dimension has no change), and `kind`
(`TRACKED`/`RENAMED`/`COPIED`/`UNTRACKED`/`CONFLICTED`). A file that is
both staged and further modified in the working tree is one record with
both `index_status` and `worktree_status` set — never two disconnected
entries for the same path.

**Three distinct, explicit states, exposed as `GitStatus.working_tree_changes` /
`.working_tree_changes_error` — never conflated:**

- **A normal change set.** `working_tree_changes` is a non-empty list;
  `working_tree_changes_error` is `None`.
- **A legitimately clean tree.** `working_tree_changes` is `[]`,
  `working_tree_changes_error` is `None` — rendered as an explicit
  "working tree is clean" message, never treated as a failure.
- **Unavailable.** `working_tree_changes` is `None`,
  `working_tree_changes_error` explains why — either the whole `git
  status` read failed (in which case the rest of `GitStatus` is also
  degraded, per "Git role" above) or a record inside a successful read
  could not be decoded (in which case branch/HEAD/tracking remain
  intact; see "Git role" above for why this is a narrower failure).

**Real Git rename-detection behavior, verified empirically, not
assumed** (`tests/unit/control_room/test_working_tree_change_detail.py`):
`--renames` only detects a *staged* rename (index vs HEAD) as a `RENAMED`
record with `original_path` set. A rename made in the working tree
without staging it (a plain filesystem move, no `git add`) is reported
by Git itself as a plain delete of the old path plus a plain untracked
add of the new path — two ordinary records, not one `RENAMED` record.
`GitReader` does not attempt to infer a rename Git itself did not
detect.

**Scope is deliberately narrow — status codes and paths only.** No diff
content, no added/deleted line counts, no rename/copy similarity score,
no commit metadata (there is no commit yet to have metadata), no
ignored files (`--ignored` is never passed), and no derived
impact/risk/change score, affected-subsystem label, or recommended
action from this list — matching the same non-goals Checkpoint Change
Set Detail (Mission 7) already established for the paths-only boundary.

**No pagination in V0.** A very large working-tree change set (e.g. an
accidentally-untracked build directory, further amplified by
`--untracked-files=all`'s per-file expansion of untracked directories)
is rendered in full, same as Checkpoint Change Set Detail — an explicit
V0 non-goal, not a silent truncation.

Verified against this repository's own real, live working tree
(`tests/unit/control_room/test_working_tree_change_detail.py::test_real_repository_working_tree_changes_is_internally_consistent`):
`working_tree_changes` is always internally consistent with the coarse
`working_tree` classification from the same read (CLEAN implies `[]`,
DIRTY implies a non-empty list), for whatever the checkout's real state
happens to be at test time — deliberately not pinned to a fixed
clean/dirty value, since that is not durable across a real checkout's
lifetime.

## Closed-State Currency

The Project Detail screen's state/checkpoint area shows a read-only
Closed-State Currency block (Mission 9) — the path is
`Projects → Project Detail → Closed-State Currency`, a plain
`<dl>`/`<dt>`/`<dd>` next to the existing checkpoint summary, not a new
`<details>` disclosure and not a new screen.

**The question it answers.** Has the repository moved beyond the latest
*formally closed* Control Room state — the commit that introduced the
closure document `PROJECT_STATE.yaml`'s `latest_checkpoint.document`
field records? This is observation only: it never recommends
checkpointing, committing, or publishing, and it never feeds
`_derive_attention()` (see "Attention derivation" below). "Closed state"
is the locked term — never "Published State" — and because Control Room
V0 never runs `git fetch`, this is local Git history only, never
"GitHub verified" or "remote verified," exactly like the existing
tracking-ahead/behind comparison.

**Source-of-truth chain**, computed fresh on every snapshot/request,
never cached and never written back into `PROJECT_STATE.yaml`:

```
PROJECT_STATE.yaml.latest_checkpoint.document
        |
strict canonical path validation (Layer 1)
        |
exact match against independently discovered
MissionHistoryReader closure_document, proven genuinely
repository-relative (Layer 2)
        |
Git resolves the exact closure-document introduction commit
(GitReader.read_path_introduction_commit)
        |
closed-state commit
        |
compare against live HEAD (GitReader.read_closed_state_currency)
        |
CURRENT / AHEAD / NOT_ANCESTOR / UNAVAILABLE
```

**Two-layer closure-path validation.** `PROJECT_STATE.yaml.latest_checkpoint.document`
is authored semantic state, not automatically trusted as Git input —
both layers live in `project_status_service.py`, not `GitReader` (which
owns only the Git reads it's asked to run) or `MissionHistoryReader`
(which stays Git-free and is not given the responsibility of deciding
whether an authored path corresponds to a real entry).

- **Layer 1 — strict canonical syntax** (`_validate_canonical_closure_path`).
  Rejects rather than normalizes: empty, an embedded NUL, an absolute
  Windows or POSIX path, a drive-qualified path, a UNC path, a leading or
  trailing `/`, a backslash, a `.`/`..` segment, a double slash, a
  leading `-`, Git pathspec magic such as `:(...)`, a bare leading `:`,
  or anything `posixpath.normpath()` would change are all refused
  outright. Backslashes are never silently converted to forward slashes,
  and `.`/`..` segments are never silently collapsed.
- **Layer 2 — independently discovered, provably repository-relative
  membership** (`_closure_path_is_proven`). The Layer-1-validated
  candidate must exactly match a `closure_document` string
  `MissionHistoryReader` itself already discovered scanning
  `history_dir` — no second closure-file discovery mechanism is added.
  That string match alone is not trusted, though:
  `MissionHistoryReader._relative_document_path()` has a defensive
  fallback that can return a bare filename (no directory component) if
  its history directory were ever unexpectedly outside the repository,
  and a bare filename could pass Layer 1 (it contains no illegal
  characters) and, pathologically, still string-match a discovered
  entry. Layer 2 additionally resolves `repository_path / candidate`
  *independently* of whatever `MissionHistoryReader` did internally, and
  requires all three: the resolution stays inside `repository_path` (no
  traversal/escape), its parent directory is exactly `history_dir` (the
  real directory that was scanned), and it names a real file on disk.
  Only then is `candidate` treated as a genuine repository-relative Git
  path; otherwise the result is `UNAVAILABLE`.

**Closed-state commit resolution.** `GitReader.read_path_introduction_commit()`
runs the fixed, read-only `git --literal-pathspecs log --no-renames
--format=%H --diff-filter=A HEAD -- <validated-path>` (see "Git role"
above for its input-boundary guarantees). Exactly one non-empty, full
40-character hex SHA line is accepted; zero lines, more than one line
(an ambiguous addition history — never resolved by picking
newest/oldest), or a malformed line are each `UNAVAILABLE` with an
explicit `detail`.

**Current-HEAD relationship.** `GitReader.read_closed_state_currency()`
revalidates both the resolved `closed_state_commit` and live
`git_status.head_sha` as full hex SHAs, then runs `git merge-base
--is-ancestor <closed> <head>` — exit `0` is ancestor, exit `1` is a
valid, successful NOT_ANCESTOR result (no `rev-list` is run in this
case), any other exit is a Git failure (`UNAVAILABLE`). Only when
ancestry is `True` does `git rev-list --count <closed>..<head>` run;
its successful output must be exactly one non-negative-integer token,
or the result is `UNAVAILABLE` (ancestry was still proven, but the count
was not, so it is never guessed).

**Four locked states**, modeled as `models.ClosedStateCurrency` /
`ClosedStateCurrencyStatus` and exposed as `ProjectSnapshot.closed_state_currency`:

- **CURRENT** — the closed-state commit is an ancestor of HEAD and
  `commits_since_closed_state == 0`. Zero is legitimate machine truth,
  never treated as missing.
- **AHEAD** — the closed-state commit is an ancestor of HEAD and
  `commits_since_closed_state > 0`. Observation only — no "checkpoint
  now," "needs review," or "publish these" text is ever generated.
- **NOT_ANCESTOR** — the closed-state commit resolved successfully but
  is not an ancestor of current HEAD, so a linear commits-beyond count
  is not computed at all (not merely omitted). Because the closed-state
  commit is resolved via `git log HEAD -- <path>`, it can only ever be
  found among commits already reachable from that same, freshly-read
  HEAD — so this state is only reachable in practice if the repository's
  live HEAD itself changed between the two independent Git reads inside
  one request (e.g. an external, out-of-band branch switch or reset
  concurrent with a request), which is exactly why the two reads stay
  independent rather than reusing one cached HEAD value.
- **UNAVAILABLE** — currency could not be reliably determined: a
  malformed or unproven closure-document path, zero or multiple
  introduction commits, malformed Git output, or a Git/subprocess
  failure. `detail` always explains why; never a guessed or partial
  result.

**No new route.** `ClosedStateCurrency` rides through the existing
`GET /api/projects` and `GET /api/projects/{project_id}` responses on
`ProjectSnapshot.closed_state_currency`, exactly like Mission 8's
working-tree change detail rides through `GitStatus`.

**No attention integration.** Closed-State Currency is observation only
and is deliberately excluded from `_derive_attention()` — AHEAD,
NOT_ANCESTOR, and UNAVAILABLE do not, by themselves, set
`attention.required`. A future mission would need separate, explicit
Founder authorization to change that.

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

Closed-State Currency (Mission 9) is deliberately **not** in this list —
see "Closed-State Currency" above. `AHEAD`, `NOT_ANCESTOR`, and
`UNAVAILABLE` currency results do not, by themselves, set
`attention.required`.

Raw classifications are preserved rather than flattened into one
red/green status — e.g. a documented `pass_with_exception` validation
result and a `CLEAN`/`SYNCHRONIZED` Git state can coexist without
producing a false "action required," and a dirty working tree does not
get silently absorbed into a validation summary that claims otherwise.

## V0 non-goals

No Claude/Codex/Hermes runtime integration, no agent routing or chat UI, no
Context Engine, no automatic Mission Cards or checkpoints, no Obsidian
integration, no Control Room database or history/evidence table (mission
history, validation evidence, mission scope/outcome text, checkpoint
change sets, working-tree change detail, and closed-state currency are
all read fresh on every request, never stored), no automatic historical
test or evidence reruns, no derived scoring or classification of
historical outcomes (no success score, capability count,
remaining-work count, priority, next-mission, or recommended action),
no impact/risk/change score or affected-subsystem label derived from a
checkpoint's change set or the current working-tree change detail, no
diff hunks, source-file contents, added/deleted line counts, rename/copy
similarity scores, commit author/email/message, blame information, or
branch-history graphs displayed anywhere (Checkpoint Change Set Detail
and Current Working Tree Change Detail are both paths-and-status-codes
only), no Resolve or render controls, no Episode/Asset/Archive Manager
UI, no remote hosting, no authentication, no notifications, no
WebSockets, no project discovery, no plugin architecture, no CI repair,
and no work on RLC-E9001, Archive follow-on, or MCP parity. No `git
fetch` — all tracking comparisons, and Closed-State Currency (Mission
9), are local-only, never "GitHub verified" or "remote verified." No
recommendation text, "checkpoint now," "needs review," "publish these,"
or any other suggested-action wording is ever generated from Closed-State
Currency — it is observation only, and no separate "PublishedStateCurrency"
concept exists (the locked term is Closed State).

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
- A historical checkpoint whose change set cannot be determined (no checkpoint commit recorded, checkpoint unresolved, or a Git command failure/timeout) yields `checkpoint_changed_files = None` with `checkpoint_changes_error` set, rendered as an explicit "change set unavailable" message — this never becomes, or is derived from, closure-document `parse_error`.
- A checkpoint commit that genuinely changed no tracked files yields `checkpoint_changed_files = []` with `checkpoint_changes_error = None`, rendered as an explicit "this checkpoint commit changed no files" message — an empty result is never treated as an error.
- A `git status` subprocess failure severe enough to fail the read outright (not found, timeout, non-zero exit) yields `working_tree = ERROR` and fails the whole `GitStatus`, exactly like any other Mission-1-era Git read failure — branch, HEAD, and tracking all degrade together, not just the working-tree detail.
- A record inside a *successful* `git status` read that does not match a recognized porcelain-v2 shape (or is a malformed instance of one, including an impossible `!` ignored-file record) yields `working_tree_changes = None` with `working_tree_changes_error` set, rendered as an explicit "working tree change detail unavailable" message — but leaves `working_tree`, `branch`, `head_sha`, and `tracking` intact, since only the per-record decode failed, not the coarse read.
- A clean working tree yields `working_tree_changes = []` with `working_tree_changes_error = None`, rendered as an explicit "working tree is clean" message — an empty result is never treated as an error, exactly like a legitimately empty checkpoint change set.
- A file that is both staged and further modified in the working tree yields exactly one `WorkingTreeChange` record with both `index_status` and `worktree_status` set — never two disconnected entries for the same path.
- A `latest_checkpoint.document` value that fails strict canonical-syntax validation (Layer 1), or that cannot be proven to be an independently discovered, genuinely repository-relative `MissionHistoryReader` entry (Layer 2), yields `closed_state_currency.status = UNAVAILABLE` with `detail` explaining which check failed — the configured value is never coerced, normalized, or partially trusted.
- Zero or more than one commit adding the configured closure-document path yields `UNAVAILABLE` with an explicit `detail` — an ambiguous addition history is never resolved by guessing newest or oldest.
- A closed-state commit that is not an ancestor of live HEAD yields `status = NOT_ANCESTOR` with `commits_since_closed_state = None` — this is a determined result, not an unavailable one, and is worded accordingly ("is not an ancestor," never "could not be determined").
- A malformed `git rev-list --count` result (extra tokens, a negative or non-numeric token, empty output) yields `UNAVAILABLE` even though ancestry was already proven `True` — the count is never guessed once ancestry is known.

## Future extension boundary

Nothing in this document authorizes work beyond Mission 1 (Projects
screen), Mission 3 (Project Detail screen, reached by selecting a project
card), Mission 4 (Mission & Checkpoint History section on the Detail
screen), Mission 5 (Validation & Evidence Detail drill-down per history
entry), Mission 6 (Mission Scope & Outcome Detail drill-down per history
entry), Mission 7 (Checkpoint Change Set Detail drill-down per history
entry, sourced from live Git), Mission 8 (Current Working Tree Change
Detail drill-down on the live GitStatus block, sourced from a single
live `git status` read), and Mission 9 (Closed-State Currency on the
Project Detail screen's state/checkpoint area, sourced from a
Git-resolved closure-document introduction commit compared to live
HEAD). Any further Control Room capability (additional projects, project
auto-discovery, additional screens, a history/evidence/change-set
database, automatic historical test/evidence reruns, diff content or
commit-metadata display, derived scoring or classification of historical
outcomes or changes, feeding Closed-State Currency into
`attention.required`, agent integration, mutation of any kind, Resolve
contact) requires a separate, explicitly authorized mission per
`CLAUDE.md` — Control Room V0 does not pre-approve its own successors.
