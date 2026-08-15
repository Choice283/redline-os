# Control Room V0 Mission 1 Closure

## Purpose

Mission 1 established the smallest approved Control Room V0 foundation: a
local-first, read-only Projects screen that combines live local Git truth
with durable, version-controlled semantic project state for Redline OS,
the sole V0-registered project. It is an instrument panel, not a steering
wheel — no mutation routes exist anywhere in the implementation.

## Published Checkpoint

SHA:
`aa1539f9f3622101e35de87bf37e9fbc4987e9a1`

Subject:
`feat: add Control Room V0 projects dashboard`

Parent:
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`

## Delivered Capability

- Local, read-only Control Room with a single Projects screen.
- Redline OS registered as the first (and only, for V0) project, via
  `config/control_room/projects.yaml`.
- Live Git status (`control_room.git_reader.GitReader`): branch, HEAD,
  working-tree condition, tracking condition, read via a fixed set of
  read-only `git` subprocess calls — never `git fetch`, never mutation.
- Durable semantic project state (`docs/control_room/PROJECT_STATE.yaml`):
  current mission, latest checkpoint, validation posture, semantic
  attention flag.
- FastAPI API boundary (`GET /`, `GET /api/projects`,
  `GET /api/projects/{project_id}`) with no mutation routes.
- Plain HTML/CSS/JS frontend — no Node build tooling, no framework.
- Installed-wheel static asset support: `control_room/static/*` is
  declared in `pyproject.toml` package-data and proven present in a built
  wheel by `tests/unit/control_room/test_packaging.py`.
- Explicit `REDLINE_CONTROL_ROOM_ROOT` checkout model: Control Room V0
  requires an existing Redline OS repository checkout — it is not, and
  architecturally cannot be, a self-contained installed package, since its
  whole purpose is reading a real checkout's live Git state, which `.git/`
  packaging never includes.
- Deterministic path handling: registry/repository/state-file resolution
  is anchored to where the installed `control_room` package's own source
  lives on disk (the real checkout for an editable dev install), never to
  the launching process's current working directory — proven for both
  editable and real installed-wheel launches, including from directories
  unrelated to any Redline OS checkout.
- Declared Control Room/dev dependencies: `fastapi`/`uvicorn` (the
  `control_room` extra) and `httpx2`/`httpx` (Starlette `TestClient`'s
  preferred and deprecated-fallback HTTP dependencies respectively) are
  fully declared, so `pip install -e ".[dev]"` alone runs the complete
  declared Control Room test suite with no manual package installs.

## Source-of-Truth Boundary

- **Git = machine truth.** Branch, HEAD, working-tree/tracking condition
  are read live on every request and never stored in
  `PROJECT_STATE.yaml`.
- **`PROJECT_STATE.yaml` = semantic/operational truth.** Current mission,
  latest checkpoint reference, validation posture, and an explicit
  semantic attention flag — meaning, not machine state.
- **Control Room combines them but owns neither.**
  `ProjectStatusService` composes `ProjectSnapshot` from both sources plus
  the registry, and derives a combined `attention` signal from
  deterministic facts (dirty tree, diverged/error tracking, unresolvable
  checkpoint commit, missing/invalid state file, or the semantic flag) —
  distinct from `state.attention`, the semantic-only flag as authored.

See `docs/CONTROL_ROOM_V0_ARCHITECTURE.md` for the full design.

## Validation

- **Claude focused validation**: `pytest tests/unit/control_room` — 46
  passed (as of the published checkpoint).
- **Codex independent focused validation**: 32 passed (initial
  independent run); full 46-test suite added across two correction
  rounds, re-verified by Claude after each round.
- **Fresh dependency environment proof**: a genuinely fresh, isolated venv
  (no system-site-packages) with only `pip install -e ".[dev]"` installed
  ran `pytest tests/unit/control_room` — 43 passed, zero manual package
  installs (this run resolved Starlette 1.6.0, which requires `httpx2`).
- **Installed-wheel proof**: a real (non-editable) wheel, built and
  installed into a fresh venv with real runtime dependencies, launched
  from a directory unrelated to any Redline OS checkout — fails fast and
  clearly without `REDLINE_CONTROL_ROOM_ROOT` set (`SystemExit` before
  binding a socket), and correctly resolves the intended project with it
  set, including serving static assets.
- **Broad regression classification**: `pytest tests/unit` (local sandbox,
  17 pre-existing collection errors from an unrelated stray `cli` package
  in user site-packages excluded) — 2452 passed, 18 skipped, 4 failed, all
  4 pre-existing/environment-specific (not Control Room). This suite is
  **not claimed green** — see CI section below for the authoritative CI
  run, which collects cleanly.

## Independent Review

Final Codex verdict:

**PASS — READY FOR CHECKPOINT**

Two non-blocking notes recorded, deferred as polish:

1. Stale internal wording/comments about launch-directory-relative paths
   (superseded by the deterministic `_PACKAGE_ROOT`/
   `REDLINE_CONTROL_ROOM_ROOT` anchoring added during review corrections,
   but not every comment in the codebase was swept for pre-correction
   phrasing).
2. The friendly missing-dependency `ImportError` (Codex review Finding 2)
   still appears inside normal Python traceback formatting when raised —
   it is a clear, actionable message, but not a specially formatted or
   traceback-suppressed CLI error.

## CI

Actual observed result for `aa1539f9f3622101e35de87bf37e9fbc4987e9a1`
(GitHub Actions run `31898757597`, read only — not rerun, not repaired):

**failure** — 43 failed, 2670 passed, 7 skipped, 7 warnings (73.79s).

Every failure was individually inspected in the run log. None reference
`control_room`, FastAPI, or any Control Room module. All 43 fall into
already-documented, pre-existing categories:

- Hardcoded Windows-specific absolute paths
  (`C:\Users\pj198\RedlineOSLive\...`,
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`)
  evaluated on the Linux CI runner — `test_rlc_e9901_queue_attempt_harness.py`,
  `test_rlc_e9901_snapshot_preflight_contract.py`.
- Windows-vs-POSIX path separator/backslash differences —
  `test_resolve_script_adapter_render_start.py`,
  `test_rlc_e9901_module_provenance_check.py`.
- Pre-existing archive evidence-path configuration debt (`paths.evidence_path`
  not set) — `test_cli_archive_list.py`.
- Other pre-existing, already-tracked test debt unrelated to path handling
  — `test_archive_manager.py`, `test_cli_archive_create.py`.

**This is Mission 1 correctness, cleanly separated from existing
repository CI portability/stale-test debt**: zero Control Room test
failures observed anywhere in the CI run, and CI success is not being
treated as a Mission 1 closure requirement, consistent with the
documented pre-existing debt this repository has carried since before
Mission 1 began (see `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md`).

## V1 Safety

Confirmed: `v1.0.0^{commit}` remains
`a41eb57012fbd80ae1be536d8e91ab74f459bc32`. The tag object itself,
`39160ff653b2db6e816a79db00ce75e911e7e668`, is unchanged. No tag was
created, moved, or deleted at any point during Mission 1 implementation,
review, or publication.

## Deferred Work

Explicitly preserved, not started, not scheduled:

- CI portability/stale-test repair (Windows-hardcoded paths, Python 3.11
  interpreter path, archive evidence-path configuration).
- Windows YAML path fixture debt.
- Python 3.11 sandbox/harness portability.
- Stale internal comment/docstring polish (the two non-blocking Codex
  notes above).
- Context Engine.
- Agent routing / agent chat UI.
- Hermes integration.
- Automation of any kind (automatic Mission Cards, automatic checkpoints).
- Mission 2 definition — no scope, objective, or timeline for a next
  mission is implied or proposed by this document.

## Closure

Control Room V0 Mission 1 is formally closed.

Next work requires a new Founder-authorized mission.

Agents advise. Paul decides.
