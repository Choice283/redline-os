# Control Room V0 Mission 9 Closure

## Purpose

Mission 9 added read-only Closed-State Currency to the Project Detail
screen's state/checkpoint area: whether the repository has moved beyond
the latest formally *closed* Control Room state -- the commit that
introduced the closure document `PROJECT_STATE.yaml`'s
`latest_checkpoint.document` field records. "Closed state" is the
locked term, never "Published State," and because Control Room V0 never
runs `git fetch`, this is local Git history only, never "GitHub
verified" or "remote verified," exactly like the existing tracking
ahead/behind comparison. Observation only: this value is never fed into
`_derive_attention()`.

## Published Checkpoint

SHA:
`d321209b424c0b8b3b042a2b7a90508754f963fb`

Subject:
`feat: add Control Room V0 Closed-State Currency Detail`

Parent:
`e5fc6fb6bc6b8e62f01fa8b1582baa744ef4e159`

This is the frozen Mission 9 *implementation* checkpoint -- distinct
from Mission 9 *closure/publication*, which this document and its
accompanying `PROJECT_STATE.yaml`/`CHANGELOG.md` updates record
separately, matching Missions 1-8 precedent (the closure record is
never squashed into or backdated onto the implementation checkpoint).

## Delivered Capability

- **Source-of-truth chain**, computed fresh on every snapshot/request,
  never cached and never written back into `PROJECT_STATE.yaml`:
  `PROJECT_STATE.yaml.latest_checkpoint.document` -> strict canonical
  path validation (Layer 1) -> exact match against an independently
  discovered, provably repository-relative `MissionHistoryReader`
  `closure_document` entry (Layer 2) -> Git resolves the exact
  closure-document introduction commit
  (`GitReader.read_path_introduction_commit()`) -> compare against live
  HEAD (`GitReader.read_closed_state_currency()`) -> one of four locked
  states.
- **Two-layer closure-path validation** (`project_status_service.py`,
  not `GitReader` or `MissionHistoryReader`). Layer 1
  (`_validate_canonical_closure_path`) rejects rather than normalizes:
  empty, an embedded NUL, an absolute Windows or POSIX path, a
  drive-qualified path, a UNC path, a leading or trailing `/`, a
  backslash, a `.`/`..` segment, a double slash, a leading `-`, Git
  pathspec magic such as `:(...)`, a bare leading `:`, or anything
  `posixpath.normpath()` would change. Layer 2
  (`_closure_path_is_proven`) requires the Layer-1-validated candidate
  to string-match a `closure_document` `MissionHistoryReader` itself
  already discovered, *and* independently re-resolves
  `repository_path / candidate` to prove it stays inside
  `repository_path`, that its parent directory is exactly
  `history_dir`, and that it names a real file on disk -- closing the
  gap where `MissionHistoryReader`'s own defensive bare-filename
  fallback could otherwise coincidentally pass Layer 1 and
  string-match.
- **`GitReader.read_path_introduction_commit(path)`** runs the fixed,
  read-only `git --literal-pathspecs log --no-renames --format=%H
  --diff-filter=A HEAD -- <path>`. `--literal-pathspecs` disables Git's
  own pathspec-magic parsing entirely. Exactly one non-empty, full
  40-character hex SHA line is accepted; zero lines, more than one line
  (an ambiguous addition history -- never resolved by guessing
  newest/oldest), or a malformed line are each a distinct `UNAVAILABLE`
  with an explicit `detail`.
- **`GitReader.read_closed_state_currency(closed_state_sha, head_sha)`**
  revalidates both arguments as full 40-character hex SHAs before any
  subprocess runs, then `git merge-base --is-ancestor <closed> <head>`
  (exit `0` = ancestor; exit `1` = a valid, successful `NOT_ANCESTOR`
  result, no `rev-list` run; any other exit = a genuine Git failure,
  `UNAVAILABLE`). Only when ancestry is `True` does `git rev-list
  --count <closed>..<head>` run; its output must be exactly one
  ASCII-decimal-digit token (`^[0-9]+$`) or the result is `UNAVAILABLE`
  -- ancestry stays proven, the count is never guessed.
- **Four locked states** (`models.ClosedStateCurrencyStatus`, exposed as
  `ProjectSnapshot.closed_state_currency`): `CURRENT` (ancestor, `0`
  commits beyond -- zero is legitimate machine truth, never treated as
  missing), `AHEAD` (ancestor, `N > 0` commits beyond, observation only,
  no recommendation text), `NOT_ANCESTOR` (resolved but not an
  ancestor of current HEAD, so a linear count is not computed at all,
  not merely omitted), `UNAVAILABLE` (malformed/unproven document path,
  zero or multiple introduction commits, malformed Git output, or a
  Git/subprocess failure -- `detail` always explains why).
- **No new route.** `ClosedStateCurrency` rides through the existing
  `GET /api/projects` and `GET /api/projects/{project_id}` responses on
  `ProjectSnapshot.closed_state_currency`, composed entirely in
  `ProjectStatusService` -- no enrichment needed in `GitReader` beyond
  the two new narrowly-scoped read methods, and `MissionHistoryReader`
  stays Git-free, contributing only its already-discovered
  `closure_document` entries to Layer 2.
- **No attention integration.** Closed-State Currency is deliberately
  excluded from `_derive_attention()`; `AHEAD`, `NOT_ANCESTOR`, and
  `UNAVAILABLE` do not, by themselves, set `attention.required`. A
  future mission would need separate, explicit Founder authorization to
  change that.
- Frontend adds a plain `<dl>`/`<dt>`/`<dd>` Closed-State Currency block
  to the Project Detail screen's state/checkpoint area (`app.js`,
  `renderClosedStateCurrency()`) -- not a new `<details>` disclosure,
  not a new screen. Verbatim state text, no recommendation wording.
- Documented the source-of-truth chain, both validation layers, the
  input-boundary guarantees of both new `GitReader` methods, the
  four-state contract, and the attention-exclusion decision in
  `README.md` and `docs/CONTROL_ROOM_V0_ARCHITECTURE.md` ("Closed-State
  Currency" section).

## Source-of-Truth Boundary

- **Git = machine truth.** Branch, HEAD, working-tree/tracking state,
  the current working tree's own change paths (Mission 8), historical
  checkpoint resolution, each historical checkpoint's file-path change
  set (Mission 7), and now the closure-document introduction commit and
  its ancestry/commit-count relationship to live HEAD (Mission 9) are
  all read from the local repository on every request.
- **`PROJECT_STATE.yaml` = current semantic state only.** Still stores
  no live Git facts and no mission history; `latest_checkpoint.document`
  is authored semantic state, never automatically trusted as Git input
  without passing both closure-path validation layers first.
- **Closure documents = historical mission records, evidence text, and
  scope/outcome text.** `MissionHistoryReader` stays Git-free; Mission 9
  reuses its already-discovered `closure_document` entries for Layer 2
  rather than adding a second closure-file discovery mechanism.
- **The web layer never reads files, runs Git, parses YAML, writes
  state, or triggers validation.** It only renders `ProjectSnapshot`
  data returned by `ProjectStatusService`, including
  `closed_state_currency`.

## Read-Only Guarantees

Mission 9 introduces no mutation capability. `read_path_introduction_commit()`
and `read_closed_state_currency()` run only `git log`, `git merge-base
--is-ancestor`, and `git rev-list --count` -- no add, commit, checkout,
switch, reset, clean, stash, fetch, pull, push, merge, rebase, or tag.
No filesystem-write route, shell execution, network Git operation,
database write, or POST/PUT/PATCH/DELETE route was added anywhere in
`src/control_room`.

## API/Frontend Integration Boundary

`ClosedStateCurrency` rides the existing `GET /api/projects` and
`GET /api/projects/{project_id}` responses on the existing
`ProjectSnapshot` model -- no new route, no new request parameter. The
frontend adds one rendering function (`renderClosedStateCurrency()`)
consuming that existing response field; neither the HTML/JS frontend
nor `app.py`'s routes touch `GitReader`, `StateReader`, or
`ProjectRegistry` directly.

## Validation Evidence

- **Mission-9-specific**: `pytest
  tests/unit/control_room/test_closed_state_currency.py -q` --
  **55 passed**, covering `read_path_introduction_commit()` (exactly-one
  / zero / two-addition-ambiguity / malformed-output / invocation-shape),
  `read_closed_state_currency()` (ancestor-zero-beyond,
  ancestor-with-commits-beyond, not-ancestor skips count, merge-base
  hard failure, non-SHA-revision rejection, valid count parsing,
  malformed count parsing including the corrected non-ASCII-digit
  regression, subprocess failure), both closure-path validation layers
  (canonical-form acceptance/rejection, Layer 2 real-file/discovered-set/
  history-dir/fallback-bare-filename hardening), the four composed
  states end-to-end (`CURRENT`/`AHEAD`/`NOT_ANCESTOR`/`UNAVAILABLE`,
  including the malformed-path and not-a-discovered-entry `UNAVAILABLE`
  paths), the attention-exclusion invariant for `AHEAD`/`NOT_ANCESTOR`,
  served frontend/route wiring (rides the existing project-list route,
  no new route), the Git-free invariant for `MissionHistoryReader`, and
  compatibility with this repository's own real, live Closed-State
  Currency (`test_real_redline_os_repository_closed_state_currency`,
  cross-checked against an independently issued Git subprocess call,
  never a hardcoded SHA).
- **Targeted malformed-count regression** (the corrected finding):
  `pytest tests/unit/control_room/test_closed_state_currency.py -k
  test_read_closed_state_currency_count_parsing_malformed -q` --
  **8 passed** (`-1\n`, `3 4\n`, `abc\n`, `\n`, empty, `3.5\n`, and the
  two corrective-review regression cases `"²\n"` and `"²"`
  -- U+00B2 SUPERSCRIPT TWO).
- **Focused Control Room suite**: `pytest tests/unit/control_room -q`
  -- **194 passed** (139 pre-existing through Mission 8 + 55 Mission 9).
- **Real Mission 8 closed-state proof**, reproduced independently
  outside the test harness during the corrective re-review: closure
  document `docs/control_room/MISSION_8_CLOSURE_2026-08-16.md` has
  exactly one introduction commit,
  `e5fc6fb6bc6b8e62f01fa8b1582baa744ef4e159`, which matched repository
  HEAD at the time of the proof -- `git merge-base --is-ancestor`
  returncode `0` (ancestor) and `git rev-list --count` `0` -- status
  **CURRENT**, `commits_since_closed_state = 0`.
- **Mutation/security scan**: `src/control_room` contains no Mission 9
  write path, filesystem-write route, shell execution, network Git
  operation, mutating Git verb invocation, database write,
  POST/PUT/PATCH/DELETE route, mission editing, checkpoint creation,
  automation, Resolve, Hermes, Context Engine, or agent-integration
  capability.
- **Route verification**: no new route; API surface remains exactly
  `GET /`, `GET /api/projects`, `GET /api/projects/{project_id}`.

## Independent Review History

**Initial review -- REJECT MISSION 9 COMMIT GATE.** One MEDIUM finding:
`src/control_room/git_reader.py::read_closed_state_currency()` used
Python's `str.isdigit()` to validate `git rev-list --count` output.
`str.isdigit()` accepts certain non-ASCII Unicode digit characters (for
example U+00B2 SUPERSCRIPT TWO, `"²"`) that `int()` then rejects
with an uncaught `ValueError` -- crashing the read instead of degrading
to `UNAVAILABLE` like every other malformed-output case in this module.

**Corrective implementation.** Added a strict, compiled ASCII-decimal
pattern, `_NON_NEGATIVE_INTEGER_PATTERN = re.compile(r"^[0-9]+$")`,
replacing the `str.isdigit()` count-token check in
`read_closed_state_currency()`. Added two regression cases,
`"²\n"` and `"²"`, to the existing
`test_read_closed_state_currency_count_parsing_malformed` parametrized
test.

**Corrective re-review -- APPROVE MISSION 9 COMMIT GATE.**
Independently verified, including direct reproduction of the previously
failing case outside the test harness: `"²".isdigit()` is `True`
but `int("²")` raises `ValueError`; the corrected pattern's
`.match()` returns `False` for the same input. Calling the real
`GitReader.read_closed_state_currency()` with `_run` monkeypatched to
return `"²\n"` for `rev-list` no longer raises -- it degrades
cleanly to `(True, None, "unexpected git rev-list output while counting
commits since the closed state: '²\\n'")`: ancestry stays proven,
only the count degrades to `UNAVAILABLE`, exactly per the four-state
contract. Confirmed the 8 targeted malformed-count cases, the 55-test
Mission 9 suite, and the 194-test focused Control Room suite all passed
matching the reported counts exactly; confirmed the correction touched
only `git_reader.py` (the regex fix) and the new test file, with no
`isdigit`/regex/validation-related change leaking into `models.py`,
`project_status_service.py`, `app.js`, `README.md`, or the architecture
doc; independently reproduced the real Mission 8 closed-state
`CURRENT`/`0` proof; confirmed repository/index/HEAD/upstream/stash/tag
state was unchanged by the review itself.

**Known LOW/informational findings, intentionally not made blockers.**
The original independent review also reported four non-blocking LOW/
informational findings, in addition to the one MEDIUM finding above.
Per explicit Founder scoping, the corrective-implementation and
corrective-re-review rounds addressed only the MEDIUM finding: none of
the four below were corrected, none are Mission 9 requirements, and
none altered the APPROVE MISSION 9 COMMIT GATE verdict.

1. **LOW -- Git path-history simplification.** `git log
   --diff-filter=A` (used by `read_path_introduction_commit()`) relies
   on Git's normal path-history simplification; in an unusual
   independent-parallel-addition merge scenario it could resolve one
   candidate introducing commit rather than surface the ambiguity. This
   is inherent to the Mission-9-mandated Git invocation itself, not an
   implementation deviation, and no current Redline OS closure document
   was affected.
2. **LOW -- Test cleanup.** `test_mission_history_reader_module_never_
   imports_subprocess` contains a `.replace()` expression determined to
   be functionally redundant/dead logic. Harmless -- it does not weaken
   the adjacent assertion proving the invariant.
3. **LOW -- Frontend defense-in-depth.** The `CURRENT`/`AHEAD` branches
   in `app.js`'s `renderClosedStateCurrency()` do not independently
   guard against a null `commits_since_closed_state`. Current backend
   guarantees make this state unreachable, so it was not treated as a
   blocker.
4. **LOW/informational -- Broad-suite passed-count difference.** The
   broad-regression passed count was observed to be 9 higher than could
   be explained solely by the 53 original Mission 9 tests. HEAD was
   unchanged and no new failure family appeared; considered likely
   environmental/collection nondeterminism and intentionally left
   uninvestigated.

## Real-Repository Proof

`test_real_redline_os_repository_closed_state_currency` cross-checks
the full composition against the actual Redline OS repository the test
suite lives in, using an independently issued Git subprocess call
(never a hardcoded SHA) as the expected value, so it keeps proving the
architecture as HEAD moves forward with future missions rather than
going stale the moment a new commit lands. At Mission 9 checkpoint time,
this resolved to closure document
`docs/control_room/MISSION_8_CLOSURE_2026-08-16.md`, introduction/closed-
state commit `e5fc6fb6bc6b8e62f01fa8b1582baa744ef4e159`, status
`CURRENT`, `commits_since_closed_state = 0` -- independently reproduced
outside the test harness during the corrective re-review with the same
result.

## V1 Safety

`v1.0.0^{commit}` remains `a41eb57012fbd80ae1be536d8e91ab74f459bc32`,
confirmed unchanged. No V1 tag was created, moved, or deleted during
Mission 9.

## Deferred Work

Explicitly out of scope for Mission 9, unchanged by this closure:

- Feeding Closed-State Currency into `attention.required` -- deliberately
  excluded; would require separate, explicit Founder authorization.
- Diff content, commit metadata, or any historical-commit comparison
  beyond ancestry and a linear commit count (that remains Checkpoint
  Change Set Detail's, Mission 7's, and Current Working Tree Change
  Detail's, Mission 8's, territory).
- Narrowing or reinterpreting the four locked states, or introducing a
  fifth state or a separate "PublishedStateCurrency" concept.
- `git fetch`, remote/GitHub-verified currency, or any network Git
  operation.
- Additional projects or project auto-discovery.
- Additional Control Room screens beyond Projects and Project Detail.
- Mission creation, mission editing, checkpoint creation, validation or
  test reruns, CI execution or repair, or a history/evidence/change-set
  database or event log.
- Context Engine, agent routing, Hermes integration, automation of any
  kind.
- Resolve, render, episode, asset, archive, or production controls.
- Acting on any of the four LOW/informational findings recorded under
  "Independent Review History" above -- none is implemented, corrected,
  or investigated further by this mission.
- Mission 10 definition -- no scope, objective, or timeline for a next
  mission is implied or proposed by this document.

## Mission 9 Completion Criteria

All of the following are satisfied as of this closure:

- Approved architecture (Closed-State Currency section,
  `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`).
- Implementation checkpoint frozen at
  `d321209b424c0b8b3b042a2b7a90508754f963fb`, exact scope: `README.md`,
  `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`, `src/control_room/git_reader.py`,
  `src/control_room/models.py`, `src/control_room/project_status_service.py`,
  `src/control_room/static/app.js`,
  `tests/unit/control_room/test_closed_state_currency.py`.
- Independent review completed, including one corrective-implementation
  round and one corrective re-review round, ending
  **APPROVE MISSION 9 COMMIT GATE**.
- Mission 9 suite: 55 passed. Full focused Control Room suite: 194
  passed. Real Mission 8 closed-state proof: `CURRENT`, `0` commits
  beyond, independently reproduced.
- Zero mutation, zero new routes, zero attention-signal integration,
  `v1.0.0` unchanged.

## Next-Mission Boundary

This document authorizes nothing beyond Mission 9 as delivered at
checkpoint `d321209b424c0b8b3b042a2b7a90508754f963fb`. No Mission 10
scope, objective, or timeline is implied or proposed. Any further
Control Room capability -- including feeding Closed-State Currency into
`attention.required`, remote/GitHub-verified currency, or any capability
listed under "Deferred Work" above -- requires a separate,
explicitly Founder-authorized mission per `CLAUDE.md`.

## Closure

Control Room V0 Mission 9 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
