# Redline OS — CI Portability + Trustworthy Signal Restoration Closure

## Governance

Agents advise. Paul decides. This mission is CI/test-infrastructure work,
not a Mission 1B-A2-x sub-mission — it sits outside that mission's
hierarchy and neither blocks nor unblocks it. This document closes **only**
the CI Portability + Trustworthy Signal Restoration mission.

## Mission identity

**CI Portability + Trustworthy Signal Restoration.**

## Why the mission existed

Hosted GitHub Actions (`ubuntu-latest`, Python 3.11,
`pytest tests/unit -v --cov=redline_core --cov-report=term-missing`) had
been **red for 32 consecutive `master` pushes**, from `40f8c7bca0` ("feat:
add RLC-E9901 render preflight tooling") through the mission's authorized
baseline `406c00237ee4806acb54025f9bebdf6aa5d11131` ("docs: record Prep2
blocker-closure verdict"). The known CI failure set at that baseline was
**44 failing tests**, independently classified into two categories:

```
A–F  =  6  actionable/portable failures
G–H  = 38  workstation-contract failures
TOTAL = 44
```

Repeated read-only investigation (recorded separately, pre-dating this
closure) had already established that comparing today's red run to a
prior run's identical red run is legitimate forensic evidence that a
change introduced no *new* failures, but is not, and must never become, a
substitute for a real green/red gate. This mission's purpose was to
restore GitHub Actions as a trustworthy portable-regression signal —
fixing what was genuinely broken and portable, and correctly excluding
only what is genuinely bound to Paul's real workstation identity — rather
than accepting historical red CI as a permanent condition.

## Implemented architecture

- `actions/checkout@v4` (`.github/workflows/ci.yml`) now runs with
  `fetch-depth: 0` (full history), not the default shallow depth-1 clone.
- `pyproject.toml` declares a new `workstation` pytest marker alongside
  the existing `resolve` marker.
- Hosted CI now runs
  `pytest tests/unit -v -m "not workstation" --cov=redline_core --cov-report=term-missing`
  — the unit suite with only workstation-contract tests excluded.
- **`workstation` tests are exactly the tests whose subject is Paul's
  literal workstation identity** — the canonical repository path, the
  exact Python 3.11.9 interpreter path, and the real RLC-E9901 production
  workspace/evidence roots — never a catch-all for "currently inconvenient
  on another OS."
- Portable defects were **repaired at the source**, never relabeled as
  `workstation` to make them disappear from hosted CI.
- No `continue-on-error`, `xfail`, `|| true`, blanket skip, broad platform
  exclusion, or weakened assertion was used anywhere as a green-CI
  mechanism.

Full architecture detail, durable definitions, and the exact hosted-CI
command live in `docs/CI_TEST_ARCHITECTURE.md`, updated by this mission's
implementation commit.

## Portable corrections (Families A–F)

Six previously-failing tests were genuinely portable and were repaired,
not excluded:

- **A** — `tests/unit/control_room/test_checkpoint_change_set.py`'s
  real-historical-checkpoint resolution now succeeds because CI performs a
  full-history checkout (`fetch-depth: 0`); the test itself required no
  change — `git cat-file -e <sha>^{commit}` needs the commit objects a
  shallow clone never fetched.
- **B** — `tests/unit/test_archive_manager.py`'s "conflicting manifest"
  fixture is now substantively different from the canonical manifest
  (different `episode.id`, explicit `newline=""`), rather than relying on
  incidental Windows `\n`→`\r\n` translation that happened to differ by
  accident on one OS and not another.
- **C/D** — `tests/unit/test_cli_archive_create.py` and
  `tests/unit/test_cli_archive_list.py`'s own `write_isolated_config_dir()`
  fixtures now configure `paths.evidence_path` (Mission 15G.1's real
  requirement), matching the pattern `test_archive_manager.py::make_manager()`
  already used.
- **E** — `tests/unit/test_resolve_script_adapter_render_start.py`'s one
  Windows-backslash-literal `expected_output_path` test fixture was
  changed to a forward-slash equivalent (parses identically and correctly
  as either `WindowsPath` or `PosixPath`). `src/redline_core/resolve/adapter.py`
  was not touched — no evidence of a production defect was found.
- **F** — `tests/unit/test_rlc_e9901_module_provenance_check.py`'s
  `build_pythonpath()` test now splits on `os.pathsep` instead of a
  hardcoded `";"`. Production `build_pythonpath()`
  (`scripts/rlc_e9901_module_provenance_check.py`) already used
  `os.pathsep` and was not touched.

## Windows YAML fixture defect (discovered and corrected)

Running the corrected portable suite for real, on Windows, surfaced a
separate, pre-existing, systemic defect, not part of the original 44:
**24 failing tests across 13 `tests/unit/test_cli_*.py` files.**

**Root cause**: each affected file's `write_isolated_config_dir()`-style
helper built `folder_structure.yaml`/`paths.yaml` by hand-interpolating a
`tmp_path`-derived filesystem path directly into a **double-quoted** YAML
scalar (e.g. `f'root_path: "{tmp_path / "_episodes"}"\n'`). Any path under
`C:\Users\...` contains the two characters `\U`, which YAML's
double-quoted-scalar grammar reads as the start of an 8-hex-digit Unicode
escape — a deterministic parse failure on every Windows machine, always.
This never manifested on hosted `ubuntu-latest` CI (POSIX temp paths don't
start with `C:\Users`), which is why it was never part of the original
44-failure classification, and it was never a `workstation`-scoped
concern — these are ordinary portable CLI end-to-end tests with no
dependency on any specific machine's identity.

**Correction**: each affected `folder_structure.yaml`/`paths.yaml` write
now serializes an ordinary Python `dict` through `yaml.safe_dump()`
instead of a hand-built quoted-scalar string, across all 13 files
individually (a shared helper was considered and rejected as higher-risk
than the repeated fix, given each fixture's non-identical return values
and seeded content). No other part of any fixture changed, and **no
production configuration-loading semantics changed** —
`redline_core.config.loader.load_config()` still reads ordinary YAML,
produced by a real serializer instead of a hand-built string.

All 24 originally-failing tests were individually re-run and pass.

## Workstation-contract taxonomy

Final collected counts, verified by `pytest --collect-only`:

```
tests/unit/test_rlc_e9901_queue_attempt_harness.py
    184 total  |   19 workstation  |  165 portable

tests/unit/test_rlc_e9901_snapshot_preflight_contract.py
     65 total  |   23 workstation  |   42 portable

TOTAL WORKSTATION SELECTION: 42
```

This is **44 test IDs more precise coverage, not additional CI
exclusion of previously portable behavior**: the total rose from the
original 38 CI failures because a stale, four-case historical-pin test
(`test_mutation_bearing_source_files_untouched_by_render_start_correction_still_match_pins`)
was replaced by two explicit, re-derivable proofs covering the *complete*
eight-file pinned set — see "Historical-pin correction" below. No
previously-portable test was reclassified as `workstation`; every one of
the 42 was individually traced to a mechanism genuinely bound to Paul's
real workstation identity (a hardcoded `CANONICAL_REPOSITORY_ROOT`,
`EXPECTED_PYTHON_EXECUTABLE`, `PRODUCTION_CWD`, or `PROTECTED_EVIDENCE_ROOTS`
literal) before being marked.

## Historical-pin correction

`scripts/rlc_e9901_queue_attempt_harness.py`'s
`_MUTATION_BEARING_SOURCE_SHA256` pins — frozen historical evidence,
recorded at Rev7 (commit `2652cd1`) — **remain frozen, byte-for-byte,
unmodified by this mission.**

A direct audit of all eight pinned files against those frozen bytes found:

```
6 of 8 files have legitimately drifted since Rev7
2 of 8 files still match the historical Rev7 bytes exactly
```

The original test architecture assumed only four files (the `render
start` path correction, Rev2 Finding 9) had drifted, and hardcoded that
`src/cli/main.py` and `src/redline_core/runtime/composition.py` were still
"untouched." That assumption was stale: unrelated, legitimate later
Redline OS V2 Recovery work (commits `e298194` "feat: add degraded-source
recovery planning" and `c1c7f32` "feat: add healthy-source system
restore") had since modified both files too. This mission corrected the
**stale test expectations**, not the historical evidence:

- the "still matches Rev7" test now covers exactly the 2 files that
  genuinely still match (`src/redline_core/render/plan.py`,
  `config/render_presets.yaml`);
- a new complementary test covers all 6 drifted files, proving each is
  correctly detected as a mismatch;
- the harness's fail-closed guarantee — it must remain intentionally
  unable to authorize a live queue attempt against later,
  differently-reviewed production bytes — is proven for the complete
  eight-file pin set, not merely whichever file happened to be first in
  dict-iteration order.

No frozen SHA was updated. No historical evidence value was rewritten. The
harness still fails closed against current `master`'s changed bytes.

## Validation evidence

- **Portable suite** (`pytest tests/unit -m "not workstation"`):
  **3144 passed, 18 skipped, 42 deselected, 0 failed.**
- **Workstation-contract suite** (`pytest tests/unit -m workstation`, run
  for real on Paul's real Windows workstation):
  **42 passed, 0 failed.**
- **Recovery gates** (`test_backup_manager.py`, `test_backup_paths.py`,
  `test_cli_archive_recover.py`, `test_cli_backup_commands.py`,
  `test_cli_recovery_planning_commands.py`, `test_recovery_classification.py`,
  `test_recovery_planning.py`): **136 passed, 0 failed.**
- `git diff --check`: clean at every stage (pre-stage, staged, and
  post-commit).
- RLC-E9901 execution-layer scripts: **unchanged** —
  `git diff --stat -- scripts/` empty at every stage;
  `test_mutation_bearing_source_pins_are_exactly_the_historically_reviewed_values`
  passed throughout.
- Frozen `v1.0.0^{commit}`: unchanged at
  `a41eb57012fbd80ae1be536d8e91ab74f459bc32`.
- **Checkpoint implementation commit**: `0300d00f86ddc6b7cbca0afbc58a93bcb7000ea5`
  (`ci: restore trustworthy hosted test signal`), parent
  `406c00237ee4806acb54025f9bebdf6aa5d11131` — 21 files changed (20
  modified, 1 new: `docs/CI_TEST_ARCHITECTURE.md`). No `src/` or `scripts/`
  path appears in that commit.
- Blocking findings: **NONE.**

## Publication attempt and correction

### First publication attempt — NOT CI-VERIFIED

Published exact HEAD: `3b615e5a5fced58f90d38f5f57060b589192a9c3` (the
closure commit itself, parent `0300d00f86ddc6b7cbca0afbc58a93bcb7000ea5`).

| Field | Value |
|---|---|
| GitHub Actions run | `32199082931` |
| Workflow | `CI` |
| Conclusion | **`FAILURE`** |
| Observed result | `1 failed, 3142 passed, 19 skipped, 42 deselected` |
| Failing test | `tests/unit/test_rlc_e9901_module_provenance_check.py::test_build_pythonpath_has_src_first_then_resolve_modules` |

The publication therefore did **NOT** earn CI-VERIFIED PUBLICATION.

### Root cause

The first Family F portability correction had changed the assertion to
reverse `os.pathsep.join(...)` using `result.split(os.pathsep)`. That
verification strategy was itself invalid whenever a fixture value contains
the host's own path-separator character: on Ubuntu, `os.pathsep == ":"`,
while the test's Windows-drive-style fixture values contain `C:` — a
literal colon of their own. Splitting on `:` therefore corrupted the
drive-letter-style fixture values themselves (`"C:/repo/src"` split into
`"C"` and `"/repo/src"`), not merely the intended join point. Production
`build_pythonpath()` (`scripts/rlc_e9901_module_provenance_check.py`) was
never defective and remained unchanged throughout.

### Correction

Corrective commit: `6d641e3e9b90e4abb54bdf8f32b5f6fc6e8ca41c`

Subject: `test: fix portable PYTHONPATH assertion`

The corrected test now compares the produced value directly to
`os.pathsep.join([str(src), str(modules)])` instead of splitting it back
apart. No production code changed. No `workstation` marker taxonomy
changed. No historical pin changed. No published history was amended,
reset, rebased, squashed, or force-pushed — the correction was added as a
new commit on top of the already-published closure HEAD
(`3b615e5`), exactly as `docs/CI_TEST_ARCHITECTURE.md`'s publication
discipline requires.

### Correction validation

- Exact failing test, alone: **1 passed.**
- Full `test_rlc_e9901_module_provenance_check.py`: **14 passed.**
- Portable suite (`pytest tests/unit -m "not workstation"`):
  **3144 passed, 18 skipped, 42 deselected, 0 failed.**
- Workstation-contract suite (`pytest tests/unit -m workstation`, run for
  real on Paul's real workstation): **42 passed, 0 failed.**
- Recovery gates: **136 passed, 0 failed.**
- Historical RLC-E9901 scripts/pins: **unchanged** — `git diff --stat --
  scripts/` empty;
  `test_mutation_bearing_source_pins_are_exactly_the_historically_reviewed_values`
  passed.
- Frozen `v1.0.0^{commit}`: unchanged at
  `a41eb57012fbd80ae1be536d8e91ab74f459bc32`.

## CI publication rule

**A Redline OS publication is not CI-verified merely because local tests
pass.** A publication earns **CI-VERIFIED PUBLICATION** only when the
GitHub Actions run corresponding to the exact published HEAD terminates
**SUCCESS**. A red run may never be accepted merely because the same
failures existed previously — comparing today's failure set to a prior
run's identical failure set is legitimate forensic evidence that a change
introduced no *new* failures; it is not, and must never become, a
substitute for a real gate. This rule is recorded durably in
`docs/CI_TEST_ARCHITECTURE.md` §8 and restated here as this mission's
governing publication standard.

**The successful local correction above does NOT retroactively make
`3b615e5a5fced58f90d38f5f57060b589192a9c3` CI-verified.** That exact SHA's
GitHub Actions run (`32199082931`) already terminated `FAILURE` and that
verdict is permanent for that SHA — it is never reclassified as
acceptable. The mission remains **NOT CI-VERIFIED** until a newly
published exact HEAD — one containing corrective commit `6d641e3` and this
durable documentation — receives its own GitHub Actions terminal
conclusion of **SUCCESS**.

## Scope boundaries

- **No Mission 1B-A2-3 implementation.** Mission 1B-A2 as a whole remains
  **IN PROGRESS**. Mission 1B-A2-3 remains **NOT IMPLEMENTED / NOT
  AUTHORIZED**.
- No `redline-mission-lifecycle` (or any other) Claude Code skill was
  created by this mission.
- No `src/` production source was modified anywhere in this mission.
- No RLC-E9901 execution-layer script
  (`scripts/rlc_e9901_queue_attempt_harness.py`,
  `scripts/rlc_e9901_snapshot_preflight_contract.py`,
  `scripts/rlc_e9901_module_provenance_check.py`,
  `scripts/rlc_e9901_preflight_assertion.py`) was mutated.
- Historical `_MUTATION_BEARING_SOURCE_SHA256`/`_REVIEWED_*` pins and the
  historical preflight evidence binding remain frozen and untouched.
- `docs/control_room/PROJECT_STATE.yaml` staleness remains explicitly
  outside this mission's scope and was not touched.
- No unrelated roadmap, recovery-architecture, or A2-3 documentation was
  opportunistically updated.

## Next action

A newly published exact HEAD — containing corrective commit `6d641e3` and
this updated documentation — must receive its own GitHub Actions terminal
conclusion of **SUCCESS** before any further step. Only after that
exact-head SUCCESS is confirmed is the next authorized step creating the
reusable Claude Code skill `redline-mission-lifecycle`. Only after that
skill exists and has been reviewed should Control Room return to Mission
1B-A2-3. **This document does not create that skill, does not publish
(push) anything, and does not authorize Mission 1B-A2-3.**

## Closure

CI Portability + Trustworthy Signal Restoration is formally closed,
locally, in source. Implementation checkpoint
`0300d00f86ddc6b7cbca0afbc58a93bcb7000ea5` and the original closure commit
`3b615e5a5fced58f90d38f5f57060b589192a9c3` were reviewed, accepted, and
published (pushed) once — see "Publication attempt and correction" above
for the full record of that attempt's `FAILURE` conclusion (run
`32199082931`) and the corrective commit `6d641e3e9b90e4abb54bdf8f32b5f6fc6e8ca41c`
that followed it. This document and the accompanying `docs/CHANGELOG.md`
update record that correction; they have not yet been committed as of the
writing of this revision, and the correction commit `6d641e3` has not yet
been re-published.

Mission 1B-A2 remains **in progress**, unaffected by this mission. Mission
1B-A2-3 remains unauthorized and unimplemented. The historical RLC-E9901
queue-attempt harness's pinned source identity remains untouched.

Next work — including this documentation's own commit, publication (push)
of the corrective commit and this documentation, waiting on and confirming
a fresh exact-head GitHub Actions SUCCESS, creation of the
`redline-mission-lifecycle` skill, and any return to Mission 1B-A2-3 —
requires its own separate, explicit Founder-authorized step.

Agents advise. Paul decides.
