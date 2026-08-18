# Redline OS — CI Test Architecture

**Governance: Agents advise. Paul decides.**

This document records the CI portability architecture implemented under the
"CI Portability + Trustworthy Signal Restoration" mission. It supersedes no
prior mission's authorization scope — it documents test-execution semantics
only. It does not authorize, imply, or begin Mission 1B-A2-3 or any other
implementation work.

## 1. Two test semantics

Redline OS's `tests/unit` suite (`tests/integration` is Resolve-only and is
never run in CI at all — unchanged, see `docs/ARCHITECTURE.md` §2) contains
two distinct kinds of test, distinguished by what they prove:

- **Portable unit tests** (the default, unmarked). Deterministic, fully
  mocked or `tmp_path`-scoped, no dependency on any specific machine's
  filesystem layout, installed interpreter path, or production workspace.
  These are expected to pass identically on any host that can install the
  project's declared dependencies — a hosted `ubuntu-latest` GitHub Actions
  runner, a contributor's laptop, or Paul's own workstation.

- **Workstation-contract tests** (`@pytest.mark.workstation`). Their explicit
  subject matter — not an incidental dependency — is Paul's real, specific
  workstation identity: the canonical repository path
  (`C:\Users\pj198\Documents\redline-os`), the exact Python 3.11.9
  interpreter path, and the real RLC-E9901 production workspace/evidence
  roots. They exist to prove that a future live, mutation-bearing production
  invocation (`scripts/rlc_e9901_queue_attempt_harness.py`,
  `scripts/rlc_e9901_snapshot_preflight_contract.py`) is bound to exactly the
  reviewed source, exactly the reviewed interpreter, and exactly the real
  production paths before it is ever allowed to run — see each module's own
  docstring for the full construction/review history. Reproducing this proof
  on a different machine would be meaningless (a hosted runner cannot "be"
  Paul's workstation) or would require weakening the fail-closed guarantee
  these tests exist to provide. They are correct to fail everywhere except
  the one machine they are about.

No other test in the repository currently carries this marker. The durable
rule this document commits to:

- **Portable tests must run successfully on supported developer
  environments and on hosted CI.** If one doesn't, the fixture or test is
  repaired — see §2 — not marked `workstation` and not skipped.
- **`workstation` tests are exactly the tests whose subject is Paul's
  literal workstation identity** (the canonical repository path, the exact
  Python 3.11.9 interpreter path, the real RLC-E9901 production
  workspace/evidence roots) — never a catch-all for "currently inconvenient
  elsewhere."
- **A test is never moved into `workstation` merely because it is
  inconvenient on another OS.** A test belongs there only when its own
  assertions are *about* a real, specific machine identity. If a
  conceptually portable test merely happens to reference a Windows-shaped
  path incidentally, that is a portability bug to fix at the source, not
  grounds for exclusion.
- **Accidental path/fixture coupling is repaired, not excluded.** A test
  that is conceptually portable but happens to break on one OS because of
  how its fixture builds a string, path, or file is a bug in that fixture,
  fixed at the fixture — see §2 for the concrete case this repository hit.
- **Exact-head GitHub Actions terminal SUCCESS is required for
  CI-verified publication** — see §8.

## 2. Accidental path/fixture coupling: the Windows-YAML fixture repair

A focused root-cause review found 13 `tests/unit/test_cli_*.py` files whose
own `write_isolated_config_dir()`-style helper built `folder_structure.yaml`
and `paths.yaml` by hand-interpolating a `tmp_path`-derived filesystem path
directly into a **double-quoted** YAML scalar (e.g.
`f'root_path: "{tmp_path / "_episodes"}"\n'`). On Windows, any path under
`C:\Users\...` contains the two characters `\U`, which YAML's double-quoted
scalar grammar interprets as the start of an 8-hex-digit Unicode escape —
a deterministic parse failure for every such path, on every Windows
machine, always. This was never a `workstation`-scoped concern (these are
ordinary portable CLI end-to-end tests with no dependency on any specific
machine's identity) and was never visible on hosted `ubuntu-latest` CI
(POSIX temp paths don't start with `C:\Users`) — it was accidental,
OS-incidental fixture coupling, exactly the class of defect this document
commits to repairing rather than excluding.

**Fix**: each affected `folder_structure.yaml`/`paths.yaml` write now
serializes an ordinary Python `dict` through `yaml.safe_dump()` instead of
hand-building a quoted scalar string. `yaml.safe_dump()` chooses correct,
safe quoting for whatever bytes the value actually contains, so this holds
for any future path shape on any OS — not just today's specific `\U`
collision. No other part of each fixture (`naming.yaml`, `assets.yaml`,
`render_presets.yaml`, `timeline_template.yaml`, return values, seeded
directory structure) was changed, and no production configuration-loading
semantics changed: `redline_core.config.loader.load_config()` still reads
ordinary YAML produced by a real serializer, which is strictly more
standard-compliant input than the hand-built strings it replaced.

## 3. Hosted CI command

```
pytest tests/unit -v -m "not workstation" --cov=redline_core --cov-report=term-missing
```

This is exactly what `.github/workflows/ci.yml` runs. GREEN means the
complete portable-unit contract passed. RED means an actual, actionable
regression in portable `redline_core`/`control_room`/CLI logic — not
environment noise, and never accepted merely because a prior run was also
red (see §8).

## 4. Why workstation tests are excluded from hosted CI

`ubuntu-latest` is not Paul's workstation: the canonical repository path, the
pinned Python 3.11.9 interpreter, and the real RLC-E9901 production
workspace/evidence directories simply do not exist there. Running the
`workstation`-marked tests unmodified on such a runner does not degrade
gracefully — it fails in ways that look identical to a real regression
(`source_file_unreadable`, `git_command_failed`, `FileNotFoundError` on the
interpreter path, Windows-literal path strings misparsed as `PosixPath`),
which is exactly the false-signal problem this mission was chartered to fix.

This exclusion is `-m "not workstation"`, applied per-test (or, for
parametrized tests, per-parametrize-case) — never a blanket per-file or
per-directory exclusion. Both `tests/unit/test_rlc_e9901_queue_attempt_harness.py`
(184 collected tests) and `tests/unit/test_rlc_e9901_snapshot_preflight_contract.py`
(65 collected tests) contain a large majority of genuinely portable tests
(fully mocked `subprocess`/filesystem, `tmp_path`-scoped fake repositories)
alongside a minority that are workstation-bound; only the individually
verified workstation-bound tests carry the marker (19 test IDs in the
harness file across 13 test functions — three of them parametrized over the
harness's eight pinned "mutation-bearing" source files, see §5; 23 test
functions / 23 test IDs in the snapshot-preflight file). The remaining 165
and 42 tests in those two files respectively continue to run, and must
continue to pass, in hosted CI.

## 5. Workstation-suite correction: stale "still matches Rev7" assumptions

`test_rlc_e9901_queue_attempt_harness.py`'s pinned
`_MUTATION_BEARING_SOURCE_SHA256` hashes (in
`scripts/rlc_e9901_queue_attempt_harness.py`) are frozen historical
evidence, recorded at Rev7 (commit `2652cd1`) — **never modified by this
mission**, see §7. What changed is this test file's own present-day
*expectation* of which of the eight pinned files still match those frozen
bytes. The original test architecture assumed only the four `render start`
path files (Rev2 Finding 9) had drifted; a direct audit run on Paul's real
workstation showed two more — `src/cli/main.py` and
`src/redline_core/runtime/composition.py` — had since drifted too, via
unrelated, legitimate later Redline OS V2 Recovery work (commits `e298194`
and `c1c7f32`), which the original test's hardcoded "four untouched files"
list and "first mismatch is `render_commands.py`" assertion never
accounted for.

The test file now defines the split explicitly and re-derivably
(`_FILES_STILL_MATCHING_REV7_PINS`, `_FILES_DRIFTED_SINCE_REV7`) and proves
both halves: `test_mutation_bearing_source_files_still_matching_historical_pins`
(parametrized over the 2 files that genuinely still match today) and
`test_mutation_bearing_source_files_drifted_since_rev7_no_longer_match_pins`
(parametrized over the 6 that don't) — together partitioning all eight
pinned files by real present-day match status, so the fail-closed guarantee
(`verify_mutation_bearing_source_identity()` must reject current master
whenever *any* pinned file has drifted) is proven for the complete pin set,
not merely for whichever file happened to be first in dict order. No pin
value was changed to make this pass — only the test's own stale assumption
about which files were still pinned-correct.

## 6. How to run the workstation suite explicitly

On Paul's real workstation only, with the repository checked out at
`C:\Users\pj198\Documents\redline-os` and the real Python 3.11.9 interpreter
present at its pinned path:

```
pytest tests/unit -v -m workstation
```

This is a manual invocation. No self-hosted runner or scheduled job invokes
it as part of this mission; wiring one up is future, separately authorized
work.

## 7. Full-history checkout requirement

`actions/checkout@v4`'s default `fetch-depth: 1` produces a shallow clone
containing only the pushed commit — no historical commit objects. Control
Room's checkpoint-resolution proof
(`tests/unit/control_room/test_checkpoint_change_set.py`) calls
`git cat-file -e <sha>^{commit}` against historical mission-checkpoint
commits (`src/control_room/git_reader.py`), which requires those commit
objects to actually be present locally. `.github/workflows/ci.yml` now sets
`fetch-depth: 0` (full history) so this check runs against real repository
state instead of failing on a checkout artifact indistinguishable from a
genuine regression.

## 8. Exact-head GitHub Actions SUCCESS as the publication-verification rule

A Redline OS publication is not CI-verified until the GitHub Actions run for
the exact pushed HEAD terminates SUCCESS. Comparing today's failure set to a
prior run's identical failure set is legitimate forensic evidence that a
specific change introduced no *new* failures — it is not, and must never
become, a substitute for a real gate. With the fixes and exclusions in this
document in place, the hosted CI command in §3 is expected to be green at
HEAD; from this point forward, red means investigate, not "compare to
yesterday." A future Mission Lifecycle skill may adopt this rule directly;
this document does not create that skill.
