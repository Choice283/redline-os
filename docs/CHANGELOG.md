# Changelog

## Control Room V0 -- Mission 4 closure

Control Room V0 Mission 4 is formally closed. Added a read-only Mission &
Checkpoint History section to the existing Project Detail screen, derived
fresh from durable `docs/control_room/MISSION_*_CLOSURE_*.md` records and
embedded in the existing `ProjectSnapshot` response as `mission_history`.
No backend route, database, history table, mutation route, mission editor,
checkpoint creator, agent integration, or automation was introduced.
Published checkpoint `04c17b41a7194bb5ec271a740202e05728bf39a0`
(`feat: add Control Room V0 mission history`, parent
`f67305d2fd18a9bef2ad276bdb5a9d9c9441e16b`). Focused Control Room suite:
69 passed. Broad regression: 2695 passed, 18 skipped, 28 failed --
failures classified as pre-existing or environment-specific and unrelated
to Mission 4. Independent review found one checkpoint-parsing issue and
two notes; the correction round scoped parsing to `## Published
Checkpoint`, added unrelated-earlier-SHA and Mission 10 ordering
regression tests, and corrected architecture wording. Focused read-only
re-review returned PASS READY FOR CHECKPOINT. Zero mutation routes
confirmed; `v1.0.0` untouched. `docs/control_room/PROJECT_STATE.yaml`
updated to reflect closure; see
`docs/control_room/MISSION_4_CLOSURE_2026-08-15.md` for the full closure
record. No Mission 5 is authorized or implied by this entry.

## Control Room V0 — Mission 3 closure

Control Room V0 Mission 3 is formally closed. Added a dedicated,
read-only Project Detail screen: project cards on the Projects screen
are now links to a Detail screen showing the full `ProjectSnapshot`
(name, summary, attention, live Git branch/HEAD/working-tree/tracking,
current mission, latest checkpoint, validation status/summary), with a
back link to the Projects screen. Implemented as pure client-side hash
routing (`#/projects/<id>`) inside the existing single-page shell — no
new backend route was added; the Detail screen reuses
`GET /api/projects/{project_id}` exactly as-is. Published checkpoint
`8f20ac48aedda97fe0a6d228a46f3a9fa3b510d2` (`feat: add Control Room V0
Project Detail screen`, parent
`b752d03f419c98b20b76b6dc0e9d4b4a30681ef7`). Focused Control Room suite:
52 passed (6 new). Broad regression: 2458 passed, 18 skipped, 4 failed —
all 4 pre-existing/environment-specific, unrelated to `control_room`,
matching Mission 1's documented baseline plus exactly the 6 tests this
mission adds. Zero mutation routes confirmed; `v1.0.0` untouched.
`docs/control_room/PROJECT_STATE.yaml` updated to reflect closure; see
`docs/control_room/MISSION_3_CLOSURE_2026-08-15.md` for the full closure
record. No Mission 4 is authorized or implied by this entry.

## Control Room V0 — Mission 2 closure

Control Room V0 Mission 2 is formally closed. Documentation/governance
correction only: removed the stale `CLAUDE.md` Section 14 standing-state
snapshot referring to Mission `39I.2o`, checkpoint `736bf8011012e94fe1e-
2825951d2e2a132fdf77b`, and Phase 14, which conflicted with the newer
durable Control Room state and was at risk of being treated as
authoritative for future startup reconstruction. Published checkpoint
`90755179a2921c1b80d67633ad020eec372afd39` (`docs: correct CLAUDE.md
standing-state authority model`, parent
`3e896a1ffd581df677b3290a827dd88b1676f880`). `CLAUDE.md` Section 14 now
states a permanent rule to derive current standing state from live Git
plus `docs/control_room/PROJECT_STATE.yaml` plus its referenced
checkpoint document, and no longer duplicates volatile values. No
application code, tests, or UI changed; `v1.0.0` untouched; the
historical Mission 39I.2o / Phase 14 record itself was not reinterpreted
or repaired. `docs/control_room/PROJECT_STATE.yaml` updated to reflect
closure; see `docs/control_room/MISSION_2_CLOSURE_2026-08-15.md` for the
full closure record. No Mission 3 is authorized or implied by this entry.

## Control Room V0 — Mission 1 closure

Control Room V0 Mission 1 is formally closed. Published checkpoint
`aa1539f9f3622101e35de87bf37e9fbc4987e9a1` (`feat: add Control Room V0
projects dashboard`, parent `a41eb57012fbd80ae1be536d8e91ab74f459bc32`).
Independent Codex review verdict: PASS — READY FOR CHECKPOINT. CI for the
published checkpoint observed failed (43 failed, 2670 passed, 7 skipped);
every failure individually inspected and confirmed pre-existing
Windows-hardcoded-path/Python-3.11-interpreter/RLC-E9901-evidence-path
debt unrelated to Control Room — zero Control Room test failures
observed. `docs/control_room/PROJECT_STATE.yaml` updated to reflect
closure; see `docs/control_room/MISSION_1_CLOSURE_2026-08-15.md` for the
full closure record. No Mission 2 is authorized or implied by this entry.

## Control Room V0 — Mission 1 final correction clarifications

Two remaining issues found on top of the Mission 1 review corrections below:

- **`httpx2`** — latest Starlette (1.6.0, confirmed by inspecting its own
  `testclient.py` and PyPI metadata) tries `import httpx2 as httpx` first,
  falling back to the older, now-deprecated `httpx` only if `httpx2` is
  absent, and raising if neither is present. The `dev` extra now declares
  both `httpx2>=2.0.0` and `httpx>=0.27.0,<0.29.0`, mirroring Starlette's
  own `full` extra exactly. Verified in a genuinely fresh, isolated venv
  (no system-site-packages): `pip install -e ".[dev]"` alone, then
  `pytest tests/unit/control_room` — 43/43 pass, zero manual installs.
  (This run also caught and fixed a real bug in
  `tests/unit/control_room/test_packaging.py`'s own wheel-build fallback,
  which only handled "setuptools present but too old," not "setuptools
  absent entirely" — the exact condition a fresh venv hits.)
- **Installed-wheel path resolution** — determined empirically (built a
  real wheel, installed into a fresh venv, launched from a directory
  unrelated to any Redline OS checkout) rather than assumed: `_PACKAGE_ROOT`
  resolves into the installing venv's `site-packages`, which has no
  `config/control_room/projects.yaml`. Confirms Control Room V0 requires an
  existing Redline OS checkout (**Option A**) — it cannot be a
  self-contained package, since its whole purpose is reading a real
  checkout's live Git state, which `.git/` packaging never includes.
  `main()` now runs a preflight registry check before binding a socket:
  `RegistryError` raises `SystemExit` naming `REDLINE_CONTROL_ROOM_ROOT`
  explicitly, so a misconfigured installed-wheel launch fails immediately
  and clearly instead of starting a server that would only 503 later.
  README and the architecture doc now say this explicitly. New test:
  `tests/unit/control_room/test_installed_wheel_path_resolution.py` proves
  both halves (fails without a root, resolves correctly with one) against
  a real installed wheel.

## Control Room V0 — Mission 1 review corrections

Independent Codex review corrections on top of Control Room V0 Mission 1,
before commit. Four findings addressed:

- **Packaging** — `pyproject.toml` package-data now includes
  `control_room = ["static/*"]`, so a built wheel actually contains
  `static/index.html`/`app.js`/`styles.css`; regression proof added at
  `tests/unit/control_room/test_packaging.py` (builds a real wheel,
  inspects its member list).
- **Dependency/console-script mismatch** — `control_room.app` now defers
  its FastAPI/Starlette imports into `_import_fastapi()`/`main()`'s
  lazy `import uvicorn`, mirroring `mcp_server.server.create_server()`'s
  existing pattern for its own optional `mcp` extra: `redline-control-room`
  stays installed by the base package, but running it without `pip install
  -e ".[control_room]"` now raises one clear `ImportError` instead of a raw
  traceback. The module-level `app = create_app()` (eager, always required
  fastapi) was removed since nothing needed it beyond
  `python -m control_room.app`.
- **Fragile CWD-anchored paths** — registry/repository/state-file
  resolution no longer falls back to the launching process's current
  working directory. The default anchor is now `_PACKAGE_ROOT` (where the
  installed `control_room` package's own source lives — the real repo root
  for an editable dev install, regardless of CWD), overridable via
  `REDLINE_CONTROL_ROOM_ROOT`. An installed `redline-control-room` launched
  from an unrelated directory can no longer silently reinterpret that
  directory as the Redline OS project. Not auto-discovery: no search or
  heuristic, only a fixed default plus one explicit override. Regression
  tests added at `tests/unit/control_room/test_path_resolution.py`,
  including launch from a directory with its own decoy registry.
- **Undeclared test dependency** — `httpx` (required by
  `fastapi.testclient.TestClient`, used in `test_app.py`) is now declared
  in the `dev` extra, which also now pulls in `redline-os[control_room]`
  (self-referencing extra) so `pip install -e ".[dev]"` alone is
  sufficient to collect and run every test `tests/unit` declares,
  including Control Room's.

See `docs/CONTROL_ROOM_V0_ARCHITECTURE.md`'s new "Path resolution and
deployment" section for the full rationale.

## Control Room V0 — Mission 1: Read-only Projects screen

First post-V1 feature work. Adds `src/control_room`, a local-first,
read-only Control Room with a single Projects screen showing Redline OS.
Combines live local Git truth (`control_room.git_reader.GitReader`, a
read-only `git` subprocess adapter) with durable semantic project state
(`docs/control_room/PROJECT_STATE.yaml`, read by
`control_room.state_reader.StateReader`) via
`control_room.project_status_service.ProjectStatusService`, which also
derives a combined attention signal from deterministic Git/state facts.
`config/control_room/projects.yaml` registers exactly one project
(`redline-os`) for V0. Exposed over FastAPI (`GET /`, `GET /api/projects`,
`GET /api/projects/{project_id}`; no mutation routes) with a plain
HTML/CSS/JS frontend, bound to `127.0.0.1` by default. No Resolve
contact, no agent integration, no repository mutation. See
`docs/CONTROL_ROOM_V0_ARCHITECTURE.md` for the full design, source-of-
truth model, and V0 non-goals.

Preserves — rather than flattens — the V1 validation record: the
Projects screen shows `pass_with_exception` / "CI remains red from
documented portability/stale-test debt" as authored in
`PROJECT_STATE.yaml`, never a bare pass/fail.

## V1 Closure Documentation Correction: RLC-E9901 Production Render Lifecycle Evidence Reconciliation

Documentation-only correction to the V1 closure mission below. The first
version of `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md` (and the README/ROADMAP/
MILESTONES edits accompanying it) described `RLC-E9901`'s Broadcast Master
render-queue acceptance as part of an undifferentiated "Phase 14 open and
BLOCKED" status, without distinguishing it from the separate `RLC-E9001`
disposable queue-acceptance experiment (Missions 39D.1–39D.3, which remain
genuinely unresolved and are unaffected by this correction). Control Room
recovered later external evidence — a 2026-08-11 RLC-E9901 production render
lifecycle, authorized and executed by Paul Jones outside the repository —
that this correction independently re-verified read-only before adopting it,
rather than accepting it on assertion alone.

- **Independently re-verified, not merely restated**: all four evidence
  files at `C:\Users\pj198\RedlineOSLive\...` confirmed to exist, with
  freshly recomputed SHA-256 matching exactly (`RLC-E9901_MASTER.mov`,
  `RLC-E9901_render_start_execution_20260811T191453Z.json`,
  `RLC-E9901_final_ignition_rev5_snapshot_20260811T184233Z.json`,
  `RLC-E9901_final_ignition_rev5_comparison_20260811T184233Z.json`); the
  rendered master's size (132,364,925 bytes) and SHA-256 confirmed; and the
  live `C:\Users\pj198\RedlineOSLive\Runtime\redline.db` queried directly,
  read-only, confirming `render_jobs` row `id=1` (`status=complete`,
  `resolve_job_id=3c0af847-bddd-43ee-8b79-a7b64cb915b4`) and `episodes` row
  `RLC-E9901` (`status=rendered`), matching the evidence bundle's own
  self-report exactly. Git independently confirmed the referenced checkpoint
  commit `0a0614bbb90af64b51766a434c920291ce2f027b` exists and precedes the
  render-start timestamp by roughly 56 minutes.
- **`docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md`**: §3 rewritten to describe two
  distinct Phase 14 threads (`RLC-E9001` unresolved, `RLC-E9901` complete)
  instead of one undifferentiated blocked status; §4 restructured into 4.1
  (assembly, unchanged), 4.2 (tooling source review, unchanged — the
  reviewed harness *scripts* were still never invoked live, which is a
  narrower and distinct claim from "no live render occurred"), 4.3 (the new
  render-lifecycle evidence table), and 4.4 (an explicitly preserved
  provenance gap: how RLC-E9901's queue entry was originally created was not
  re-traced by this correction, only the queue-confirmation-through-
  completion chain from the Rev5 snapshot onward); §1/§2/§8 updated for
  consistency; a correction note added near the top.
- **`docs/ROADMAP.md`**: the Phase 14 section's opening status line rewritten
  to describe the two threads explicitly instead of one blanket status; one
  new dated entry added at the end of the Phase 14 list (not editing any
  prior entry) recording the 2026-08-11 evidence and this correction's
  independent re-verification, with the provenance gap stated explicitly.
- **`README.md`**: status line updated; a new paragraph added after the
  existing RLC-E9901 tooling-review paragraphs (which remain accurate for
  what they specifically describe — reviewed harness scripts never
  live-invoked) clarifying that RLC-E9901's actual production render
  lifecycle, executed through the ordinary CLI rather than those scripts,
  is separately complete; the `start_render()` capability bullet and the
  "Construction-only" `render start` section corrected to state live
  verification occurred for RLC-E9901 on 2026-08-11, while preserving the
  Rev1–Rev4 construction/review history unchanged as historical record.
- **`MILESTONES.md`**: new "RLC-E9901 Production Render Lifecycle" Verified
  Milestone entry added (independently re-verified evidence table, and the
  provenance-gap limitation stated explicitly); the Future Milestones
  Broadcast-Master bullet narrowed to `RLC-E9001` only; one Current System
  Capabilities bullet clarified to name `RLC-E9001` explicitly rather than
  make an unscoped Phase 14 claim.
- **RLC-E9001 explicitly not touched**: no statement about RLC-E9001's own
  three documented `AddRenderJob()` failures (Missions 39D.1–39D.3) was
  altered, weakened, or removed. It remains a separate, unresolved,
  non-V1-blocking thread.
- No source code, test, or CI workflow changed. No live Resolve contact. No
  RLC-E9901 mutation — every check performed by this correction was
  read-only (file existence, SHA-256 recomputation, one read-only SQLite
  `SELECT`).

## V1 Release Candidate Closure Documentation

Documentation-only mission reconciling the repository against its actual
completed V1 state and producing the durable V1 closure record. No source
code, test, or CI workflow changed. RLC-E9901 production evidence and
Archive Rev1 archive/database state were not touched.

- **New `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md`.** The durable V1
  closure record: V1 status (complete, subject to a documented CI
  exception), the release-candidate base commit
  (`1bca6575d2d9aa345d2c08671560d10e73916b66`) and its functional parent
  (`32a870524deb806e09a403b4bf28e968f46350f0`), a summary of major validated
  capabilities, an explicit statement that Phase 14's open Broadcast Master
  queue-acceptance blocker does not gate V1, the RLC-E9901 and Archive Rev1
  evidence summaries, deferred V2 work, new-computer resume instructions,
  and the stop condition (STOP V1 development after release audit/tag
  absent a genuine release-blocking defect).
- **CI exception independently confirmed, not merely restated.** This
  mission read the actual GitHub Actions run for the release-candidate base
  commit via `gh run view --log-failed` (run `31656054733`, `ubuntu-latest`,
  Python 3.11): `43 failed, 2624 passed, 7 skipped, 7 warnings`. The full
  43-test failure list was independently re-derived from that log and
  confirmed to partition exactly into four classes with zero unclassified
  remainder: 39 Windows-specific RLC-E9901 production/preflight/module-
  provenance tests executed on Ubuntu CI, 1 Windows-path render test hitting
  Linux `pathlib` semantics, 1 Archive "conflicting manifest" fixture that
  becomes byte-identical to the canonical manifest on Linux due to newline
  handling, and 2 stale Archive Rev1 CLI fixtures predating the Mission
  15G.1 `evidence_path` authority requirement. No demonstrated V1
  production-code regression was found among the 43 failures.
- **README.md**: status line updated from "Phase 13 complete; Phase 14 open
  and blocked" to "V1 complete; Phase 14 Broadcast Master queue acceptance
  open and blocked (not a V1 blocker)"; added a pointer to the new closure
  document alongside the existing pause-checkpoint pointer.
- **docs/ROADMAP.md**: added an explicit note at the top of the Phase 14
  section that the still-open Broadcast Master queue-acceptance blocker does
  not block V1, pointing at the new closure document's §3; added the closure
  document to the "Where to look" index.
- **MILESTONES.md**: added a pointer to the new closure document.
- **CI status**: red at the release-candidate base commit, unchanged by this
  mission and not authorized for repair here — see the classification above
  and `docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md` §6.
- **Deferred V2 items recorded, not implemented**: Missions 15I–15L, MCP
  `video_item_count` transport consistency, broader MCP parity, Control Room
  UI, Context Engine, Hermes integration, skill/automation cleanup, general
  refactoring, CI portability/stale-test repairs, any further Phase 14 live
  attempt, `start_render()` live verification, and linked video/audio
  placement cardinality verification.

## Unreleased - Phase 15 Mission 15H: Archive Failure + Recovery Validation (synthetic tests only)

Mission 15H proves Archive Manager Rev1 remains safe under failure and implements the narrow recovery path for a verified final package whose DB registration failed. No live archive operation is authorized by this mission. Three failure states are frozen and never blurred: **PRE-PUBLISH FAILURE** (no final package, no `archives` row, episode `'rendered'`), **VERIFIED_UNREGISTERED** (a complete, independently-verified final package exists, no `archives` row, episode `'rendered'`), and **REGISTERED COMPLETE** (package + row + episode `'archived'`, all consistent). Recovery registers a package that is already independently proven valid — it never repairs, rebuilds, replaces, or re-seals one, and a failed attempt never damages the active episode workspace or a previously published final package. Every test remains synthetic (`tmp_path` archive trees, temporary SQLite, `monkeypatch`/direct-attribute failure injection); no production archive root, RLC-E9901, live `redline.db`, or Resolve connection was touched.

- **New `package.derive_final_package_path(archive_root, episode_id, archive_id)`** (`redline_core/archive/package.py`): a pure, read-only shared primitive for `<archive_root>/episodes/<episode_id>/<archive_id>` — the single source of truth for where an archive's final package lives. Extracted from `build_staged_package()`'s own inline computation (which now calls it too, behavior unchanged) specifically so `ArchiveManager`'s new create-retry check and `recover_archive()` can never silently drift from the publication path into a second, competing formula.
- **`ArchiveManager.create_archive()` gained one new step, `_reject_existing_final_package()`, run immediately after `archive_id` derivation.** `archive_id` does not incorporate supplemental evidence/metadata identity (Mission 15G's frozen boundary), so the *same* `archive_id` can be re-derived by a later attempt whose current evidence/config/software state differs from an earlier one's. If a package already exists at the canonical destination for that `archive_id`, it is never overwritten or rebuilt over: this step independently re-verifies whatever is already there using the published `package.verify_archive_package()` (never a weaker check) and, if it verifies clean, raises the *same* `ArchiveVerifiedUnregisteredError` a failed DB commit raises — one consistent operator signal regardless of when `VERIFIED_UNREGISTERED` is discovered, always pointing at `recover_archive()`. A corrupt/identity-conflicting existing package propagates its verification failure unchanged — fail closed, never touched, human investigation required.
- **New core entry point: `ArchiveManager.recover_archive(episode_id, *, archive_id: str) -> ArchiveRecoveryResult`.** `archive_id` is required and explicit — recovery never scans the archive root guessing which package to register. Orchestration: validate `archive_id`'s strict shape → derive the canonical path → verify the finalized package (published verifier, unchanged) → read its sealed `episode.json`/`render_job.json` restore metadata only after verification succeeds → cross-check current DB state → commit via the existing `Database.commit_verified_archive()` guarded transaction, never a manually-reimplemented one.
  - Never rebuilds identity from current source: no `ArchiveContentPlan` reconstruction, no re-hashing the active workspace, no re-reading current ingest/assets/evidence, no recomputing `archive_id`. Proven directly: recovery succeeds after the active workspace is modified, after the configured evidence source directory is deleted, and after the evidence config itself changes.
  - Sealed metadata (Mission 15G's `payload/metadata/episode.json`/`render_job.json`) is the registration-context authority, read through the same safe-open primitive every package read in this codebase uses, only after the whole package has independently verified, and structurally validated before use (new `ArchiveRecoveryMetadataError` on malformed/inconsistent metadata) — a process restart between the original failed `create_archive()` and a later `recover_archive()` call does not make recovery impossible.
  - Current DB state is still cross-checked, never bypassed: the sealed render-job snapshot's identity-critical fields (output path, Resolve job ID, project/timeline identity, preset) are compared against the *live* `render_jobs` row (new `ArchiveRecoveryConflictError` on disagreement); the current episode must still be `'rendered'` (unless the exact matching registration already exists, the idempotent case); any existing `archives` row must exactly match or recovery fails closed rather than overwrite/repair it; a legacy row reuses `ArchiveLegacyRecordError` unchanged.
  - Idempotent: a second call after a successful recovery (DB row exactly matches, episode already `'archived'`) returns `classification: "already_registered"` — never a second row, never a misleading error, never a package mutation.
  - A DB-commit failure during recovery is caught the same way `create_archive()` catches its own `ArchiveCommitError`: re-raised as the same `ArchiveVerifiedUnregisteredError`, so the package remains exactly `VERIFIED_UNREGISTERED` and a later retry remains possible. Proven across three states in one test (create fails → still-VU → recover fails → still-VU → recover retries → REGISTERED COMPLETE) with package hashes captured and required byte-for-byte identical at every step.
  - `archive_id` shape validated strictly (new `_validate_recovery_archive_id()`): exactly `f"{episode_id}-a1-"` plus 12 lowercase hex characters — closes path-traversal vectors before the value ever becomes a filesystem path component.
  - New immutable result `ArchiveRecoveryResult` (`episode_id`, `archive_id`, `archive_path`, `manifest_sha256`, `render_job_id`, `classification`). New exception hierarchy: `ArchiveRecoveryError` (base), `ArchiveRecoveryNotFoundError`, `ArchiveRecoveryConflictError`, `ArchiveRecoveryMetadataError` — four new types; every existing filesystem-integrity exception is reused unchanged wherever its meaning already applies.
- **No SQLite schema change.** No `recovery_state`/`recovery_attempt`/`recovered_at`/unregistered-flag column exists anywhere — the filesystem (a valid final package) plus existing DB state (no matching row) already represent `VERIFIED_UNREGISTERED` completely. `commit_verified_archive()`'s signature and guarded transaction are byte-for-byte unchanged.
- **No package or source repair anywhere.** Nothing rehashes, rewrites, or reseals a package's manifest/sidecar/metadata/`PACKAGE_COMPLETE`; nothing deletes or copies files back into a package; nothing restores source workspace/ingest/assets/evidence files. Corruption is reported, never repaired — a corrupt `VERIFIED_UNREGISTERED` package fails closed on both `create_archive()` retry and `recover_archive()`.
- **No archive closure evidence.** Remains Mission 15L's concern, unchanged from Mission 15G's own boundary.
- **Canonical transport extended, additively.** CLI: `redline archive recover <episode_id> --archive-id <archive_id>` (`--archive-id` required, no `--force`, no arbitrary package-path option). MCP: `archive_recover(episode_id, archive_id)` (both required, no repair/force mode). Both surface `ArchiveVerifiedUnregisteredError` with the same `classification: "verified_unregistered"` shape `archive create`/`archive_create` already use. Zero Resolve dependency in the recovery path. `create`/`verify`/`list`/`recover` remain the complete canonical archive vocabulary on both transports; `archive episode`/`archive_episode` are not resurrected. MCP server tool count: 19 → 20.
- **Existing tests updated for the new create-retry precision, not weakened**: `test_create_archive_rejects_destination_collision` (manager) and `test_run_archive_create_destination_already_exists` (CLI) previously asserted a bare `ArchiveDestinationCollisionError`/generic "already exists" message for a garbage directory at the canonical destination; both now assert the more precise package-verification failure `_reject_existing_final_package()` produces, plus that the garbage content is left byte-for-byte untouched with no manifest/sidecar/`PACKAGE_COMPLETE` sealing and no archive database row. `test_installed_mcp_startup_smoke.py`'s embedded startup-probe script had its expected tool set/count updated to stay honest, matching the Mission 15F precedent for the same test.
- **Tests:** `test_archive_manager.py` gained a full recovery suite (core success/idempotency, package byte-for-byte immutability across every state, rejection for every failure mode — package absent, 9 unsafe/malformed `archive_id` shapes, corrupt manifest, bad sidecar, missing `PACKAGE_COMPLETE`, payload corruption, missing/malformed/mismatched render metadata, render job missing/not-complete/identity-conflicting in DB, conflicting existing archive row, legacy archive row — three-state DB-failure-then-retry with hash proofs, source/evidence/config independence after `VERIFIED_UNREGISTERED`, create-retry classification for both valid and corrupt existing packages, pre-publish failure injection at two architectural boundaries, and a stale-`.staging`-partial non-interference proof): **101 passed** (file total, up from 67). New `test_cli_archive_recover.py` (**15 passed**: transport success/idempotency/conflict/not-found/unsafe-archive-id, output printing, argument parsing including the deliberate absence of `--force`/an arbitrary package-path flag, a direct `recover_archive()` call). `test_mcp_tools.py` gained `archive_recover` registration/call/structured-result/idempotency coverage and its canonical-tool-set proof was extended: **70 passed** (file total, up from 66). Full `tests/unit`: **2632 passed, 24 failed, 18 skipped** — the remaining 24 failures are the known Windows temp-path/YAML double-quoted scalar fixture family. **Zero new or different failure root causes.**
- **Resolve/live-database/production-media/RLC-E9901 contact: zero.** No live `redline.db`, no production archive root, no RLC-E9901 or other production filesystem path, no Resolve connection anywhere in source or tests. Mission 15I, 15J, 15K, and 15L remain unstarted and out of scope.

## Unreleased - Phase 15 Mission 15G.1: Episode-Scoped Evidence Authority (synthetic tests only)

Mission 15G's evidence-collection portion was blocked on a genuine, repository-proven gap: no authoritative rule existed for associating an arbitrary on-disk file with a specific episode. Control Room and Paul froze the missing authority — `<configured evidence root>/<episode_id>/` is the entire, exclusive evidence scope for that episode; the directory boundary is authoritative, a filename is not — and Mission 15G.1 implements exactly that, closing the blocker without reopening any part of Mission 15G's already-accepted identity contract (`content_set_digest`/`archive_id` still derive only from `ArchiveContentPlan`; evidence is sealed, non-identity-bearing supplemental content, exactly like the four restore-metadata snapshots already published). Every test remains synthetic (`tmp_path` evidence trees, temporary SQLite); no production evidence root, RLC-E9901, or Resolve connection was touched.

- **New optional config field: `PathsConfig.evidence_path: str | None = None`** (`redline_core/config/schema.py`). Backward-compatible by construction — every existing `paths.yaml` (including this repository's own checked-in `config/paths.yaml`) predates this field and continues to load unchanged, resolving to `None`. No machine-specific live path (e.g. an operator's real home directory) is hard-coded anywhere in source or the checked-in example config — verified directly by a structural test. `docs/CONFIG.md` gained a new "Episode-scoped evidence root" section documenting the two-state contract below.
- **New `redline_core/archive/evidence.py`: `resolve_episode_evidence(*, evidence_root, episode_id) -> EpisodeEvidencePlan`.** The narrow, read-only resolver that is the single authority for "does this file belong to this episode." Never scans the whole evidence root for a filename match and never inspects anything outside the exact derived `<evidence_root>/<episode_id>/` directory. Built almost entirely from reused Mission 15C machinery, not a second tree walk: `integrity.validate_source_root()` proves the configured root itself is safe (existing, a genuine directory, not a symlink/junction/reparse point) before anything else happens; `integrity.build_source_inventory()` then walks the episode directory exactly as it would an episode workspace — rejecting any unsafe object anywhere in the subtree, detecting case-colliding relative-path identities (Archive Rev1's Windows-target policy), and returning already-verified per-file SHA-256/size, which become `FileArchiveSupplement` fingerprints with zero additional hashing. Episode-directory existence semantics are frozen and distinct: the directory simply not existing is a valid, ordinary zero-evidence result (`EpisodeEvidencePlan(supplements=(), directories=())`); the configured root itself missing/unsafe, or the episode directory existing but being an unsafe object (file, symlink, junction, reparse point), both fail closed (`ArchivePathError`/`ArchiveUnsafeFilesystemObjectError`, reused unchanged from Mission 15C — no new exception type needed for filesystem safety). One new exception, `ArchiveEvidenceIdentityConflictError`: a `.json` evidence file with its own top-level `episode_id` field is preserved when that field agrees with the owning directory, but fails closed when it disagrees — malformed JSON or JSON with no `episode_id` field is never rejected on that basis alone; it is preserved as opaque evidence, since no repository-defined schema requires every evidence file to parse. Evidence is classified with exactly one controlled vocabulary term, `production_evidence` — no semantic meaning is ever inferred from a filename.
- **`ArchivePackagePlan` gained `supplement_directories: tuple[str, ...] = ()`** (`redline_core/archive/supplement.py`), a directory-only companion to `supplements` for exactly one case `supplements` alone cannot represent: an evidence subdirectory containing no file of its own. Mirrors `ArchiveContentPlan.workspace_inventory.directories`'s own first-class empty-directory preservation rather than silently dropping it. `build_package_plan()` gained a keyword-only `supplement_directories` parameter, validated for emptiness/absoluteness and for collision against every supplement/content file path, exactly like the existing supplement-path collision check.
- **`package.py` extended, additively, to stage/verify supplement directories.** New `_create_supplement_directories()` pre-creates every supplement-only directory before any file copy — the same directory-first ordering `_copy_and_verify_workspace_files()` already uses for empty workspace subdirectories. `_expected_payload_contents()`/`_expected_payload_contents_from_manifest()` both extended (not duplicated) to include `supplement_directories` in the same independent full-tree reconciliation every other payload path already goes through, so a missing or unexpected evidence directory is detected by the exact same single verification algorithm as a missing/unexpected file — no second, evidence-specific verifier was added. The sealed manifest's top-level `directories[]` array (previously workspace-only) now also carries supplement directories, sorted together deterministically; `summary.directory_count` is deliberately left workspace-directory-only, unchanged, matching the pre-existing convention that external-artifact/supplement-file-implied directories were never separately counted there either.
- **`ArchiveManager.create_archive()` orchestration extended in exactly one new place**: content-plan resolution → `archive_id` derivation (unchanged) → **new**: `_resolve_configured_evidence()` → evidence supplements are merged with the four existing metadata supplements into one `build_package_plan()` call, evidence directories passed through `supplement_directories` → package build/verify/publish → `commit_verified_archive()` (unchanged) → `ArchiveResult`. Every evidence-authority failure raises before any package staging begins and therefore before any DB commit — proven directly by dedicated tests confirming the episode remains `'rendered'`, no `archives` row exists, and the episode workspace/evidence source are both left completely untouched.
- **Narrow same-day correction: an unconfigured evidence authority is fail-closed, not an authoritative zero-evidence result.** The original session implemented `evidence_path is None` as a lenient third state (zero evidence, no error), reasoned from the mission's own "if backward compatibility creates a conflict here: STOP and surface it" escape hatch, since the strict alternative would have broken every one of the ~2500 currently-passing tests (none of which set `evidence_path`, a field that did not exist before this mission). **Control Room rejected that as the canonical archive-completeness contract** — a missing authority is not equivalent to an authoritative zero-evidence result — and required the correction: `evidence_path is None` now raises a new `ArchiveEvidenceConfigurationError` (`redline_core/archive/exceptions.py`) from `_resolve_configured_evidence()`, before any `ArchivePackagePlan` construction, package staging, publication, or DB commit. Deliberately not `ArchivePathError` — there is no path to even evaluate yet; this is a configuration-completeness failure, not a filesystem-safety one. `PathsConfig.evidence_path` itself stays optional at the config-schema level (an existing `paths.yaml` without it still loads unchanged, proven directly) — only `create_archive()`'s eligibility gate is fail-closed; configuration parsing and archive-creation eligibility are deliberately independent concerns. Every archive-creation test fixture not specifically exercising evidence configuration (`test_archive_manager.py`'s `make_manager()`, gaining a `with_evidence_authority: bool = True` parameter; the `PathsConfig` builders in `test_cli_archive_create.py`/`test_cli_archive_verify.py`/`test_cli_archive_list.py`/`test_mcp_tools.py`) was updated to configure a real, empty, synthetic `tmp_path`-scoped evidence root by default — an authoritative-zero-evidence state, not "unconfigured" — so the authority gate itself was never weakened merely to avoid touching fixtures. No CLI/MCP transport change accompanies this correction: the new exception surfaces through each transport's existing broad `ArchiveError` handling, unchanged.
- **No SQLite schema change.** No column was added to `archives`/`episodes`/`render_jobs` for evidence. Configuration owns evidence-root authority; the Archive Manifest owns preserved evidence identity — exactly the boundary the mission specified.
- **No CLI/MCP transport change.** No `--evidence-root`/`--evidence`/`--no-evidence` flag or equivalent was added to either transport — evidence authority comes entirely from configuration, so an operator cannot bypass canonical ownership per invocation.
- **Identity invariants, proven directly**: evidence affects `content_set_digest`? **No.** Evidence affects `archive_id`? **No.** Evidence affects the Archive Manifest SHA-256? **Yes**, because supplements are sealed package content. Proven at the `package.py` level with a single `ArchiveContentPlan` and two different evidence sets (`test_supplements_do_not_change_content_set_digest_but_do_change_manifest_sha`, pre-existing from Mission 15G, reused unchanged since the identity contract is the same one) and at the `ArchiveManager` level with real evidence toggled on/off across parallel synthetic episodes (`test_create_archive_evidence_does_not_change_content_set_digest_or_archive_id`, `test_create_archive_same_content_evidence_present_vs_absent_same_digest_different_manifest_sha`).
- **Tests:** new `test_archive_evidence.py` (22 test functions / 26 collected cases with one parametrization: ownership/containment, nested paths, same-basename-different-directory, empty-directory preservation, five unsafe-episode-id shapes, four filesystem-safety failure modes — three of them symlink/junction-privilege-gated skips matching this repository's established convention, one exercised via a synthetic monkeypatch proof of exception propagation since a real case-collision cannot be constructed on a case-insensitive Windows filesystem — and JSON structured-identity handling: matching/conflicting/opaque/malformed/non-JSON). `test_config.py` gained 3 (evidence_path defaults to `None` against the real example config, no hard-coded machine path in the checked-in `paths.yaml`, an explicit non-default value round-trips through the schema). `test_archive_package.py` gained 4 (empty supplement directory staged and preserved, missing/unexpected supplement directory detected by `archive verify`, a supplement directory colliding with a supplement file path rejected at plan-construction time). `test_archive_manager.py` gained 9 net (one test rewritten from the incorrect "unconfigured authority archives successfully" premise into `test_create_archive_no_evidence_authority_configured_fails_closed`, proving the typed exception plus no package/no DB row/episode still `'rendered'`/source untouched; a new `test_create_archive_paths_config_without_evidence_path_still_loads` isolating the config-parsing-vs-eligibility distinction; configured evidence automatically resolved and copied; a configured-but-episode-absent root archives with zero evidence; another episode's evidence excluded; a missing configured root fails closed before any DB commit and leaves the episode `'rendered'`; an unsafe episode evidence path fails closed with the source directory provably untouched; the two identity-invariant proofs). Full `tests/unit`: **2575 passed, 29 failed, 18 skipped** — the same 29 pre-existing failures as the Mission 15G baseline, confirmed identical by name. **Zero new or different failures.**
- **Resolve/live-database/production-media/RLC-E9901 contact: zero.** No live `redline.db`, no production archive root, no production evidence directory, no RLC-E9901 or other production filesystem path, no Resolve connection anywhere in source or tests. Mission 15H, Mission 15I, Mission 15J, and Mission 15L remain unstarted and out of scope.

## Unreleased - Phase 15 Mission 15G: Archive Evidence + Restore Metadata (synthetic tests only; evidence-collection portion blocked)

Mission 15G was authorized to enrich the published Rev1 package with episode-scoped production evidence, an episode metadata snapshot, a selected render-job metadata snapshot, an effective configuration snapshot, and software/runtime identity — without changing preservation semantics, the archive DB transaction, or the public CLI/MCP vocabulary. Repository investigation (§5/§6/§7 of the mission brief) found **no authoritative repository-defined evidence-source mapping**: the only two "evidence" concepts that exist are the Asset Registry Reconciliation Engine's `RegistryIdentityEvidence` (asset content-hash identity evidence — an unrelated concept, not production/process evidence) and the Phase 14/RLC-E9901 live-Resolve queue-snapshot probes (`scripts/phase14_render_queue_snapshot.py`, `scripts/rlc_e9901_queue_attempt_harness.py`), which write to a caller-supplied `--output` path per manual invocation with no persisted episode-scoped directory convention or registry, and which this mission's own governing instructions explicitly prohibit accessing. Per the mission's own instruction not to invent an evidence-source contract silently, **the evidence-collection portion is blocked**: `ArchiveManager` resolves zero evidence and constructs zero `FileArchiveSupplement` instances. The restore-metadata (episode/render-job/config/software) side was fully implemented, tested, and wired in, together with the general package-plan/supplement architecture that a future evidence-resolution mission can populate. See `MISSION_15G_EVIDENCE_SOURCE_MAPPING_BLOCKED` in the mission report for the exact minimal architecture/config addition Paul would need to authorize before evidence collection can proceed. Every test remains synthetic (`tmp_path` workspace/ingest/assets/archive-root, temporary SQLite); no production archive root, RLC-E9901, live `redline.db`, or Resolve connection was touched.

- **New `redline_core/archive/supplement.py`**: the package-plan/supplement layer. `ArchivePackagePlan(content: ArchiveContentPlan, supplements: tuple[...])` sits alongside, never inside, `ArchiveContentPlan` — the identity-bearing preservation payload and its sealed-but-non-identity-bearing supplements are deliberately two different objects, so `content_set_digest`/`archive_id` (still derived from `ArchiveContentPlan` alone) can never be affected by what supplements happen to exist. Two supplement shapes: `FileArchiveSupplement` (an already-existing file elsewhere on disk, copied independently — the shape a future evidence-resolution mission would populate; no caller in this mission constructs one) and `GeneratedArchiveSupplement` (in-memory canonical JSON bytes, `sha256`/`size_bytes` always derived from `canonical_bytes` by the one recommended constructor `build_generated_supplement()`, never computed by hand). `build_package_plan()` validates supplement path uniqueness (against each other and against `content`'s own `workspace/…`/`external/…` paths) and sorts deterministically. New `ArchiveSupplementPlanError` (mirrors `ArchiveContentPlanError`'s convention: a caller/`ArchiveManager` construction bug, not a user-facing archive failure).
- **New `redline_core/archive/metadata_snapshot.py`**: four pure snapshot builders, each a function of already-resolved, in-memory inputs only (no DB read, no config load, no filesystem access, no clock) — `ArchiveManager` snapshots its already-loaded `Episode`/`RenderJob`/`RedlineConfig` exactly once, at orchestration time, so a concurrent write can never be observed mid-build.
  - `build_episode_snapshot()` → `payload/metadata/episode.json`: every persisted `Episode` field except the internal SQLite surrogate `id` (not restoration-relevant; `episode_id` is the authoritative identity). Snapshotted *before* `commit_verified_archive()` runs, so `status` reads `"rendered"` even though the live DB row transitions to `"archived"` immediately afterward — this is intentional pre-archive provenance, proven directly by `test_create_archive_episode_snapshot_reflects_pre_commit_rendered_status`.
  - `build_render_job_snapshot()` → `payload/metadata/render_job.json`: every persisted `RenderJob` field for the selected job; `RenderJob.id` is renamed to `render_job_id` (real data, clarified for a standalone document with no surrounding SQLite context).
  - `build_config_snapshot()` → `payload/metadata/config_snapshot.json`: the complete effective `RedlineConfig` via its own canonical `model_dump(mode="json")` — never a hand-maintained parallel schema, never a broad `vars()`/`dataclasses.asdict()`-style dump. Fails closed (new `ConfigSnapshotSecretFieldError`) if `RedlineConfig` or any nested model declares a field whose name matches a keyword from a fixed secret-bearing blocklist (`password`, `secret`, `token`, `api_key`, `credential`, `private_key`, `auth`), walked recursively over the Pydantic *schema* (not a particular instance) so a currently-empty/default secret field would still be caught. `RedlineConfig` as it exists today (`naming`, `folder_structure`, `render_presets`, `paths`, `assets`, `timeline`) declares no such field — verified directly by a structural test — so this is a guard against a future config field being archived by accident, not evidence one exists now. Absolute paths in `paths`/`folder_structure` are included deliberately: supplemental provenance, never part of package identity, so a relocated/restored archive's config snapshot differing from the original does not change `content_set_digest`/`archive_id`.
  - `build_software_snapshot()`/`resolve_software_identity()` → `payload/metadata/software.json`: `redline_os_version` via `importlib.metadata.version("redline-os")`, `python_version`/`platform_*` via `sys`/`platform` — network/subprocess-free, proven directly by a test with no mocking of either. `repository_revision` is always `null`: no supported git-revision-discovery helper exists anywhere in this repository today (confirmed by repository search — the Asset Registry Reconciliation Engine's own `repository_revision` field is caller-supplied, never self-discovered), and shelling out to `git` would be exactly the "fragile command for decorative data" this mission's own instructions prohibit. `build_software_snapshot()` itself is a pure function of explicit keyword arguments (the dependency-injection seam item 41 asked for); `resolve_software_identity()` is the one, separate, non-pure function that actually reads the environment.
  - Every snapshot is canonical JSON (UTF-8, `sort_keys=True`, compact separators) and carries no newly-captured wall-clock timestamp — the Archive Manifest's own `created_at_utc` already records when the package was built; a source record's own genuine persisted timestamps (`Episode.created_at`, `RenderJob.updated_at`, etc.) are preserved unchanged.
- **`redline_core/archive/package.py` extended, backward-compatibly, to a package-plan-aware builder.** `build_staged_package()`/`build_archive_package()` now accept either a bare `ArchiveContentPlan` (every pre-Mission-15G caller and every existing Mission 15D/15E.2 test — treated as a package plan with zero supplements via a new `_coerce_package_plan()`) or a Mission 15G `ArchivePackagePlan`; every existing call site needed zero changes beyond one internal test that called the now-renamed `_build_manifest(package_plan=…)` keyword directly. New `_stage_supplements()` dispatches file-backed supplements through the same copy-and-verify pipeline `_copy_and_verify_external_artifacts()` already uses (safe-open source, post-copy source re-hash, destination hash-verify) and generated supplements through a new write-and-verify path (`_write_and_verify_generated_supplements()`: exclusive-create write of `canonical_bytes`, then the *destination* is independently re-hashed — never trusting the in-memory hash alone — new `ArchiveSupplementCopyError` on mismatch). `_expected_payload_contents()`/`_verify_payload_completeness()` were extended (not duplicated) to include supplement paths in the same independent full-tree reconciliation every other payload file already goes through; a new `_reconcile_supplements()` re-verifies every file-backed supplement's source immediately before sealing, mirroring `_reconcile_complete_content_plan()`'s existing source-stability guarantee (a generated supplement has no external source to re-check — its bytes are already fixed at plan-construction time, and the write-and-verify step already re-hashes what actually landed on disk). Archive Manifest Rev1 gained a new top-level `supplements[]` array (one entry per supplement: `archive_relative_path`/`classifications`/`sha256`/`size_bytes`/`source_kind`/`supplement_kind`/`original_absolute_path`) — additive; `schema_version` stays `1`. `summary.file_count`/`summary.total_bytes` now include supplements; `summary.directory_count` stays workspace-directory-only, unchanged (matching the pre-existing convention that external-artifact directories were never separately counted there either). `_validate_sealed_manifest_structure()` gained supplement structural validation (mirroring the existing `artifacts[]` validation, plus a cross-check that no supplement path collides with an artifact path); `verify_archive_package()`'s existing single reconciliation algorithm therefore already detects supplement tampering (content change, deletion, or a stripped `supplements` manifest key) exactly like any other package content — no second, separate verification policy was added, per the mission's explicit instruction. `PackageResult`/`StagedPackage` gained a `supplement_count` field.
- **`ArchiveManager.create_archive()` orchestration extended**: after `ArchiveContentPlan` is resolved and *before* `archive_id` is derived, unchanged, from `plan.content_set_digest` — the four generated metadata supplements are built from the already-loaded `episode`/`selected_job`/`self.config` (never a second DB/config read) via a new `_build_metadata_supplements()`, wrapped into an `ArchivePackagePlan` via `build_package_plan()`, and that plan (not the bare content plan) is what's passed to `package.build_archive_package()`. `archive_id` derivation, `commit_verified_archive()`'s signature/transaction, and the `VERIFIED_UNREGISTERED` boundary are all byte-for-byte unchanged — proven directly by `test_create_archive_archive_id_still_derived_only_from_content_set_digest` and the full existing `ArchiveVerifiedUnregisteredError` test coverage passing unmodified. No evidence supplement is ever constructed — proven directly by `test_create_archive_never_produces_evidence_supplements` (no `production_evidence` classification, no `supplement_kind: "file"` entry, ever, in a package this mission's `ArchiveManager` produces).
- **No SQLite schema change.** No column was added to `archives`/`episodes`/`render_jobs` for evidence, metadata, config, or software identity — all of it lives only in the sealed package, exactly as the mission required. `commit_verified_archive()`'s signature and guarded transaction (Mission 15B) are untouched.
- **No archive closure evidence.** Nothing under a future `<archive_root>/_evidence/<episode-id>/<archive-id>_closure.json` (or repository-consistent equivalent) is created by this mission — that remains Mission 15L's concern, post-publication/post-commit, and therefore cannot truthfully live inside a package sealed before the DB commit.
- **No CLI/MCP transport change.** `archive create`/`archive verify`/`archive list` and `archive_create`/`archive_verify`/`list_archives` are byte-for-byte the same public surface Mission 15F published — no `--evidence`/`--metadata` flag or equivalent was added; enrichment happens automatically inside `ArchiveManager`, exactly as the mission required.
- **Tests:** new `test_archive_supplement.py` (15: `GeneratedArchiveSupplement`/`build_generated_supplement()` fingerprint/validation, `FileArchiveSupplement` validation, `build_package_plan()` success/determinism/collision-rejection against workspace and external-artifact paths, and the identity-boundary proof that different supplement sets never change `content_set_digest`). New `test_archive_metadata_snapshot.py` (15: all four snapshot builders' fields/determinism/canonical-JSON shape, the config secret-field guard firing on both a nested and a top-level synthetic secret-bearing field, and `resolve_software_identity()` requiring no network/subprocess). `test_archive_package.py` gained 10 (generated-supplement success, the identity-boundary proof end to end — same `content_set_digest`, different `manifest_sha256` — backward-compatible bare-`ArchiveContentPlan`-vs-wrapped-zero-supplement byte-identity, tampered/missing generated-supplement detection, stripped-`supplements`-key manifest tampering detection, file-backed-supplement copy success, and file-backed-supplement source-changed-fails-closed): **50 passed, 2 skipped** (file total, up from 42/2). `test_archive_manager.py` gained 8 (all four metadata supplements present with correct classifications/paths, zero evidence supplements ever produced, the pre-commit-`"rendered"`-status proof, render-job/config/software snapshot content correctness, archive-id identity invariance, and tampered-metadata-supplement detection via `verify_archive()`): **59 passed** (file total, up from 51). Full `tests/unit`: **2536 passed, 29 failed, 15 skipped** — the same 29 pre-existing failures as the Mission 15F baseline (2490/29/15), confirmed identical by name via a stash-based before/after comparison. **Zero new or different failures.**
- **Resolve/live-database/production-media/RLC-E9901 contact: zero.** No live `redline.db`, no production archive root, no production evidence directory, no RLC-E9901 or other production filesystem path, no Resolve connection anywhere in source or tests. Mission 15H (`VERIFIED_UNREGISTERED` recovery), Mission 15I (closure), and Mission 15L (post-commit archive closure evidence) remain unstarted and out of scope; evidence-source-mapping architecture remains an open founder decision.

## Unreleased - Phase 15 Mission 15F: Canonical CLI/MCP Archive Transport + Read-Only Verification (synthetic tests only)

Mission 15E/15E.2 published the non-destructive Archive Rev1 core (`ArchiveManager.create_archive()`) but left the public CLI/MCP surface pointed at `archive_episode()`, the Mission 15E temporary compatibility bridge. Mission 15F does not redesign or weaken that core — it makes the Rev1 transport canonical (`archive create`/`archive_create`, `archive list`/`list_archives` extended for Rev1 fields) and adds the one capability the core never had: read-only proof that a *committed* archive is still valid (`archive verify`/`archive_verify`), reusing Mission 15D's own staging-time reconciliation algorithm rather than a second, independent one. The legacy `archive episode`/`archive_episode` transport surface and the `ArchiveManager.archive_episode()` compatibility bridge itself are retired entirely — there is exactly one canonical way to archive an episode now. Every test remains synthetic (`tmp_path` workspace/ingest/assets/archive-root, temporary SQLite); no production archive root, RLC-E9901, or Resolve connection was touched.

- **New `package.verify_archive_package(archive_path, *, expected_episode_id, expected_archive_id)`** (`redline_core/archive/package.py`). Read-only, filesystem-only verification of an already-published, finalized Rev1 package — no `StagedPackage`, no DB, no Resolve. `_verify_payload_completeness()`'s payload-reconciliation logic was extracted into a shared `_reconcile_payload_contents()` so staging-time verification (expectations from an in-memory `ArchiveContentPlan`) and this new finalized-package verifier (expectations derived from the sealed package's own `archive_manifest.json`, via a new `_expected_payload_contents_from_manifest()`) share one algorithm, not two. Checks, each re-deriving trust from disk rather than assuming an earlier success still holds: the package root is a genuine non-symlinked directory (`integrity.validate_source_root()`, reused); the root contains only the four permitted entries (`archive_manifest.json`, `archive_manifest.sha256`, `PACKAGE_COMPLETE`, `payload/`); every control file is read through the same safe-open primitive every other file read in this module uses (`integrity.open_stable_source()`, via a new `_read_safe_file_bytes()`) — never a plain, unverified read; `PACKAGE_COMPLETE` is present and exactly empty; the sidecar is in the writer's exact format (a new `_parse_manifest_sha256_sidecar()` — one lowercase-64-hex-character line; both `\n` and `\r\n` termination are accepted, since `Path.write_text()`'s platform newline translation means the writer's own real on-disk bytes differ by OS) and its digest matches the manifest's actual SHA-256; the manifest is valid JSON and passes full structural validation (a new `_validate_sealed_manifest_structure()` — `schema_version`, non-empty `archive_id`/`episode_id` matched against the caller-supplied expected identity, well-formed `content`/`artifacts`/`directories`/`summary`/`verification`) — a corrupted-but-consistently-rehashed manifest fails here even though its bytes already matched the sidecar, since hash equality alone is never treated as structural proof; the complete `payload/` tree reconciles exactly against the manifest's own `artifacts`/`directories` (zero missing/unexpected files or directories, zero hash/size mismatches — the shared reconciliation algorithm, which itself fails closed on any symlink/junction/reparse point via Mission 15C's `build_source_inventory()`); and the manifest's own `summary` counts are cross-checked against what was actually, independently verified. Never repairs, rewrites, or deletes; raises the existing `ArchivePathError`/`ArchiveUnsafeFilesystemObjectError`/`ArchivePackageVerificationError` family, not a second parallel one.
- **New `ArchiveManager.verify_archive(episode_id) -> ArchiveVerificationResult`** (`redline_core/archive/manager.py`). Owns the DB read and the DB-vs-filesystem identity cross-check; delegates every byte/hash/structure check to `package.verify_archive_package()` unchanged. New `ArchiveNotFoundError` if no committed `archives` row exists (never scans the archive root attempting recovery — Mission 15H's concern); reuses `ArchiveLegacyRecordError` for a pre-Rev1 row (never pretended to be Rev1); new `ArchiveManifestMismatchError` if the row's `manifest_sha256`/`manifest_path` disagree with what was actually verified on disk (distinct from `ArchivePackageVerificationError`, since the package itself may be perfectly self-consistent — only the DB's record of it has drifted). Mutates nothing; idempotent (proven directly by a dedicated test); never contacts Resolve.
- **Canonical CLI**: `redline archive create <episode_id> [--render-job-id <id>] [--manifest <path>]` calls `create_archive()` directly (never through the retired bridge); `redline archive verify <episode_id>` calls `verify_archive()` directly. `redline archive episode` is retired from the parser entirely — not registered, not an alias, argparse's own standard "invalid choice" error. `archive list`'s serialization gained `archive_id`/`archive_state` (additive to the original three fields) so legacy and Rev1 rows are distinguishable without a second call; `list` still never performs package verification.
- **Canonical MCP**: `archive_create(episode_id, render_job_id=None, manifest_path=None)`, `archive_verify(episode_id)`, `list_archives()` (extended the same way as the CLI). The legacy `archive_episode` tool is not registered — the server now exposes 19 tools, not 18.
- **`ArchiveVerifiedUnregisteredError` transport semantics preserved through the canonical surface, on both transports.** A DB-commit failure after a successful, verified publication is reported with a distinct `classification: "verified_unregistered"` (carrying the exception's own episode_id/archive_id/archive_path/manifest_path/manifest_sha256), never collapsed into a generic "archive failed, nothing happened" — the operator needs to know a verified package exists on disk even though the episode never transitioned to `archived`. No recovery is attempted; that remains Mission 15H's concern.
- **`ArchiveManager.archive_episode()` retired from the core.** Full repository search for `archive_episode` classified every hit before removal:
  - **Production transport call sites** (`src/cli/archive_commands.py`, `src/mcp_server/tools/archive_tools.py`) — migrated to call `create_archive()`/`verify_archive()` directly.
  - **`src/redline_core/archive/manager.py`** — the method itself removed; `create_archive()`/`verify_archive()`/`list_archives()` are the only public archive operations now.
  - **Unit tests** — migrated, not left pointing at a removed method: `tests/unit/test_archive_manager.py`'s two wrapper-delegation tests (`archive_episode()` non-destructive; a second call raises) were removed outright, since the properties they proved are already covered by existing `create_archive()`-focused tests in the same file and there is no wrapper left to test delegation *from*. `tests/unit/test_cli_archive_episode.py` was removed; its coverage was rebuilt against the canonical commands as new `tests/unit/test_cli_archive_create.py`/`tests/unit/test_cli_archive_verify.py`. `tests/unit/test_cli_archive_list.py`'s fixture helper (`archive_episode()` → renamed `create_and_archive_episode()`) now calls `create_archive()` directly. `tests/unit/test_mcp_tools.py`'s archive-tool tests migrated to `archive_tools._archive_create`/`_archive_verify`, and gained a `FastMCP`-shaped fake-registration test proving the exact `{archive_create, archive_verify, list_archives}` tool set. `tests/unit/test_installed_mcp_startup_smoke.py`'s embedded startup-probe script (an already-failing baseline test for an unrelated wheel-build/pip-install environment reason) had its expected tool set/count updated to stay honest regardless.
  - **Historical/frozen documents, left unedited by design**: `docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md` (a dated verification snapshot citing `test_cli_archive_episode.py` by name as point-in-time evidence) and `docs/BUILD_COMMAND_SPEC.md` (a Phase 13 design-rationale doc citing `archive_episode()`'s Mission 8-era behavior) are frozen historical records, not living references.
  - **Out-of-scope observation, not fixed here**: `src/redline_core/db/database.py`'s `create_archive_record()` docstring and `src/redline_core/db/models.py`'s `ArchiveState` docstring both still describe `archive_episode()`'s Mission 8-era destructive behavior — already stale before this mission (it stopped being true as of Mission 15E) and out of Mission 15F's authorized transport-surface scope; a future `redline_core.db` documentation pass should update them.
  - Updated: `docs/MCP_TOOLS.md` (Archive section, tool count 18→19), `README.md` (CLI usage examples, archive prose section, module-list tool count), `docs/ARCHITECTURE.md` (new Mission 15F subsection; the Mission 8/15E historical note extended to point at this entry rather than dangle a reference to a deleted test file).
- **Tests:** `test_archive_package.py` gained 24 (`verify_archive_package()`: valid package, read-only/no-mutation, missing manifest/sidecar/marker, non-empty marker, manifest SHA mismatch, 3 malformed-sidecar shapes, wrong episode_id/archive_id, unsupported schema_version, missing/unexpected payload file, payload size/hash mismatch, missing/unexpected directory, corrupted summary counts, unexpected root entry, symlinked payload file, junction'd payload directory, symlinked package root — the last two skip cleanly without link-creation privilege, matching this repository's established convention): **42 passed, 2 skipped** (file total). `test_archive_manager.py` gained 12 (`verify_archive()`: valid archive, no archive row, unknown episode, legacy row, DB path missing on disk, DB manifest_path/manifest_sha256 mismatch, corrupted package, no DB/episode/workspace mutation, Resolve independence, idempotency) and lost 2 (`archive_episode()` wrapper-delegation tests, folded into existing coverage): **51 passed** (file total; net +10 from the prior 41). New `test_cli_archive_create.py` (17, 2 of them the same pre-existing YAML-escaping baseline failure under a new name — see below) and `test_cli_archive_verify.py` (9), replacing the removed `test_cli_archive_episode.py` (15, 2 of them that same baseline failure under its old name). `test_cli_archive_list.py` gained 2 Rev1-field/legacy-row tests and 1 existing test updated for the new print columns. `test_mcp_tools.py` gained 10 archive-tool tests (was 3). Full `tests/unit`: **2490 passed, 29 failed, 15 skipped** — the 29 failures are the same pre-existing root causes as the Mission 15E/15E.2 baseline (2433 passed/29 failed/13 skipped); two of those 29 changed *names* only (`test_main_archive_episode_*` → `test_main_archive_create_*`), same Windows-path/YAML-escaping root cause, since the command they exercise was renamed as part of this mission's own retirement work, not a new failure. The 2 additional skips are new, legitimate symlink-creation-privilege skips (`test_verify_archive_package_symlinked_payload_file_rejected`/`_symlinked_root_rejected`), matching this repository's established convention for a link-creation test on an environment without admin/Developer Mode. **Zero new or different failure root causes.**
- **Resolve/live-database/production-media contact: zero.** No live `redline.db`, no RLC-E9901 or other production filesystem path, no Resolve connection anywhere in source or tests. Mission 15G (production evidence, DB metadata snapshot, configuration snapshot, software/repository identity) and Mission 15H (VERIFIED_UNREGISTERED/unregistered-package recovery) remain unstarted and out of scope.

## Unreleased - Phase 15 Mission 15E.2: Manifest Provenance + Complete Archive Content (synthetic tests only, Mission 15E remains uncommitted pending this work)

Mission 15E's own architecture-review session found that a successful Rev1 package, as built, captured the episode workspace and rendered master but not the original episode manifest or manifest-referenced ingest/assets media — Resolve imports those by reference and never copies them into the workspace, so `SourceInventory(episode.folder_path)` alone could not truthfully represent them. Mission 15E.2 closes that gap: a new build-layer manifest-provenance persistence step, a new complete-content-plan model, and an extended package builder and `ArchiveManager` that together preserve the workspace, the render master, the original manifest, and every manifest-referenced source file — deriving archive identity from all of it, not a workspace-only subset. Every test remains synthetic (`tmp_path` workspace/ingest/assets/archive-root, temporary SQLite); no production archive root, RLC-E9901, or Resolve connection was touched.

- **New `src/redline_core/build/manifest_provenance.py`.** `persist_manifest_provenance()`, called from `BuildOrchestrator.build_prepared()` right after a successful `episode_manager.build_episode()`, copies the original manifest byte-for-byte (streamed, never re-parsed) into `<episode.folder_path>/project/episode_manifest/<original-filename>` and writes a deterministic `manifest_provenance.json` (schema_version 1: `manifest_sha256`, `original_manifest_path` as non-authoritative provenance only, `original_manifest_filename`, `media: [{source_root, source_relative_path}, ...]`) beside it — root-relative media identity, computed from the already-approved-root-contained `ValidatedEpisodePlan.media_paths`, specifically so recovery at archive time never depends on the manifest's now-irrelevant original directory (the existing manifest validator resolves *relative* media paths against that directory, which is exactly why a byte-for-byte copy alone would not have been sufficient). A build that cannot safely persist this required provenance raises (`ManifestProvenanceError`, subclassing `BuildOrchestrationError`) rather than reporting success. Injected into `BuildOrchestrator` via a new `manifest_provenance_persister` constructor parameter, matching its existing DI pattern for every other build stage (`target_parser`/`manifest_resolver`/`manifest_loader`/`manifest_validator`) — orchestration-sequencing tests stay decoupled from real filesystem I/O. **No `episodes.manifest_path` DB column was added** — the canonical workspace copy plus provenance record is the approved persistence model, deliberately not a DB pointer to an external file that could later disappear.
- **New `src/redline_core/fsutil.py`.** The generic four-checkpoint safe-open/hash primitive (`open_stable_source()`/`hash_stable_file()`) was extracted from `redline_core.archive.integrity` verbatim, with exception types made injectable, so the build layer could reuse it without depending on `redline_core.archive` (a backwards layering dependency with no counterpart anywhere else in this repository, even though not a literal import cycle). `integrity.py`'s own `open_stable_source()`/`hash_stable_file()` are now thin, behavior-preserving delegations (identical exceptions, identical messages) — one real implementation, not two. Every pre-existing Mission 15C/15D test passes unmodified against the refactor (one test's `monkeypatch` target moved from `integrity._HASH_CHUNK_SIZE` to `fsutil._HASH_CHUNK_SIZE`, since that constant's owning module changed; every `os.fstat`/`os.lstat` monkeypatch continues to work unchanged, since Python's module-singleton `os` object is shared regardless of which module's `import os` reference is patched).
- **New `src/redline_core/archive/content.py`: the hybrid `ArchiveContentPlan`.** `workspace_inventory: SourceInventory` (Mission 15C, unchanged) plus `artifacts: tuple[ArchiveArtifact, ...]` — scattered individual files, either workspace *classification overlays* (no independent copy; e.g. "this workspace file is also the render master") or genuinely external artifacts (their own copy, under `external/...`). Rejected alternatives (recorded in `docs/ARCHITECTURE.md`): one `SourceInventory` per external file would either archive an entire ingest/assets root for one referenced file or force an awkward synthetic staging root; flattening the workspace into a per-file list would discard Mission 15C's proven tree-walk/empty-directory semantics for the one case that already fits them. `ArchiveManager` owns constructing the plan; `package.py` only ever consumes an already-resolved one. New `ArchiveSourceKind` (`workspace`/`source_media`/`episode_manifest`) and `ArchiveClassification` (`workspace`, `render_master`, `episode_manifest`, `manifest_provenance`, `source_media`, `ingest_media`, `asset_media` — a small closed vocabulary, manifest-only, never SQLite, never generated from arbitrary input) enums. `build_content_plan()` deterministically orders artifacts and defensively rejects two artifacts sharing an `archive_relative_path` or an `absolute_source_path` (a real construction bug).
- **Physical-path dedup, never hash-based.** The dedup key is the resolved absolute source path, decided by `ArchiveManager` when it builds the plan. Two files with identical bytes but different original paths are archived separately — collapsing them by hash would destroy restore semantics, proven by a dedicated test. A physical file already captured by the workspace tree-copy gets an additional classification tag on its single existing artifact entry, never a second copy — proven for the render master, the canonical manifest, and the canonical provenance record, plus the defensive (structurally near-unreachable, since Resolve imports by reference) case of manifest-referenced media that happens to already live in the workspace.
- **`content_set_digest`: the new package identity authority**, replacing the workspace-only `source_set_digest` (Mission 15D/15E), which could have let two archives with identical workspaces but different external content collide on the same identity. Canonical schema-versioned JSON (`workspace.source_set_digest` plus a sorted `artifacts[]` list of `{archive_relative_path, classifications, sha256, size_bytes, source_kind, source_relative_path, source_root}`) SHA-256'd, computed from already-trusted fingerprints — never rereading bytes solely for the aggregate, and deliberately excluding `absolute_source_path` and every machine/attempt-specific field (so an approved root relocating with the same logical layout does not change identity, proven by a dedicated test). Lives entirely in the manifest/filesystem identity layer, never SQLite. **Archive ID now derives from it**: `f"{episode_id}-a1-{content_set_digest[:12]}"` — same complete plan, same ID; any change to required preservation content, a different one.
- **External source-media destination mapping**: `external/source_media/{ingest,assets}/<relative-to-that-root>`, mirroring exactly how Mission 15C computes workspace `relative_path` — collision-safe (two same-named files under different roots/subdirectories can never collide) and provenance-legible. Every candidate is reconstructed as `<currently configured root> / source_relative_path` and re-verified through `integrity.hash_stable_file()` on that exact candidate path — the manifest validator's own `Path.resolve(strict=True)` (which follows links) is never trusted as the final filesystem-safety authority a second time.
- **`package.py` extended to consume the complete content plan — one canonical payload layout, not two.** `payload/workspace/...` (Mission 15D's proven tree-copy, path-shifted from the old bare `payload/...`; every existing Mission 15D test migrated to the new prefix) plus, only when artifacts require it, `payload/external/source_media/{ingest,assets}/...` and `payload/external/episode_manifest/...`. Per-artifact copy verification (safe-open source descriptor, post-copy source re-verify, destination verify) is the same pipeline Mission 15D already proved for workspace files, now reused unchanged for external artifacts. Completeness verification and the pre-sealing reconciliation pass (both still run twice: once after copying, once again immediately before publication) now cover the entire staging payload — workspace files/directories, every external artifact, and a freshly-recomputed `content_set_digest` required to still equal the planned one. `PackageResult`/`StagedPackage` gained `content_set_digest`/`workspace_source_set_digest` (replacing the old single `source_set_digest` field). The sealed Archive Manifest Rev1 gained a `content` block (`content_set_digest`, `workspace_source_set_digest`, `workspace_root`) replacing the old top-level `source` block (avoiding two competing identity authorities in one document), and every `artifacts[]` entry gained `classifications`/`source_kind`/`source_root`/`source_relative_path`/`original_absolute_path`.
- **`ArchiveManager.create_archive()` gained the legacy fallback**: a new keyword-only `manifest_path: str | Path | None = None`. Canonical provenance present, no override: canonical is authority. Canonical present, override supplied: accepted only if its SHA-256 matches the canonical manifest exactly, otherwise rejected — a caller can never substitute a different manifest for an episode's recorded build provenance. Canonical absent, override supplied: loaded/validated at its real original location through the existing, unmodified manifest loader/validator (relative media resolved against *that* directory, proven by a dedicated test), becoming an explicit `external/episode_manifest/<filename>` artifact — legacy and canonical episodes differ only in how their content plan is resolved, never in package-builder behavior. Canonical absent, no override: fails closed (`ArchiveManifestProvenanceError`), never guessed from the working directory, episode ID, or either approved root. `archive_episode()` (the Mission 15E compatibility wrapper) does **not** expose this parameter — a Mission 15F transport decision.
- **Render-master `InventoryFile` correction** (the narrow issue the Mission 15E architecture-review session flagged): after the workspace inventory is built, `_require_render_master_is_inventory_file()` now requires the selected render job's output to equal the `absolute_source_path` of an actual, already safety-proven `InventoryFile` — not merely a path that exists and resolves inside the workspace (which `Path.is_file()`/`is_relative_to()` alone would accept even for a symlink). The cheap pre-inventory `is_relative_to()` check remains as a fast pre-filter, no longer the safety authority.
- **DB commit boundary unchanged in shape.** `commit_verified_archive()` is reached only after the *complete* content package publishes; no new SQLite columns (`content_set_digest`, classifications, per-artifact paths/hashes all remain manifest-only). `VERIFIED_UNREGISTERED` behavior is unchanged.
- **New exceptions**: `ArchiveManifestProvenanceError` (`archive/exceptions.py` — every canonical-provenance and legacy-manifest resolution failure: missing/malformed/unsupported-schema/SHA-mismatched provenance, an invalid `source_root`, a path escape, a conflicting override) and `ManifestProvenanceError` (`build/manifest_provenance.py`, subclassing `BuildOrchestrationError`).
- **Narrow post-review correction: canonical manifest provenance media identities are unique — duplicate identities fail closed, never deduplicated.** Control Room reviewed the completed Mission 15E.2 report and flagged one gap: `ArchiveManager._build_content_plan()` silently deduplicated canonical `manifest_provenance.json` media entries sharing a `(source_root, source_relative_path)` identity, treating a duplicate as ordinary redundant input. Since canonical provenance is generated once, by a single already-validated build, a duplicate identity there is never legitimate — it indicates tampering, corruption, or a manual/unsupported edit. Both ends of the contract now enforce this, using the same unconditionally-case-folded identity `archive.integrity._normalized_identity_key()` already applies to workspace paths (kept as small module-local copies per this codebase's `_is_windows()` convention, not a cross-module import): **writer** (`map_media_paths_to_approved_roots()`) rejects two validated media paths that would collide once normalized (`ManifestProvenanceError`, fails the build); **reader** (`_discover_canonical_provenance()`) rejects a `manifest_provenance.json` whose `media` list contains two colliding entries (`ArchiveManifestProvenanceError`), before `ArchiveContentPlan` construction, package staging, publication, DB commit, or episode status transition. The pre-existing `_build_content_plan()` dedup-by-identity step is unchanged and remains correct for its one remaining case: the legacy explicit-manifest fallback, where a manifest legitimately referencing the same approved media file from more than one `assembly.media[]` entry is ordinary redundant input, not tampering — canonical entries can no longer reach that step carrying a duplicate to begin with.
- **New tests**: `tests/unit/test_build_manifest_provenance.py` (7: byte-for-byte preservation, root-relative media mapping surviving manifest relocation, deterministic provenance JSON, missing-root and missing-`project`-subfolder failures, a deterministic mid-copy source-mutation failure via the same `os.fstat` call-count technique Mission 15D's own tests use, and a no-silent-partial-success proof). `tests/unit/test_archive_content_plan.py` (15: root-mapping collision-safety, same-hash-different-paths preserved separately, same-physical-path multi-classification collapse, duplicate-path/duplicate-destination rejection, six aggregate-digest change/no-change cases including root-relocation stability, archive-ID determinism, a complete workspace+ingest+assets+legacy-manifest package with full layout/manifest/publication verification, and two external-source-mutation-timing failure cases). `tests/unit/test_archive_manager.py` grew from 26 to 41 (+15: no-provenance-no-fallback failure, legacy fallback success with byte-preserved manifest, legacy relative-media-resolved-against-original-directory, conflicting-override rejection, matching-override acceptance, six canonical-provenance malformation failures — missing provenance/multiple manifests/SHA mismatch/unsupported schema/malformed JSON/invalid source_root — missing-referenced-media failure, the render-master `InventoryFile` correction, and (the narrow correction above) exact-duplicate and case-equivalent-duplicate canonical provenance media identity, each proving no final package, no archive DB row, `'rendered'` status retained, and the source workspace untouched). `test_build_orchestrator.py`'s existing 14 tests updated (constructor DI wiring, `calls`/`completed_stages` sequences extended by one stage) — zero behavioral regressions, all still green. CLI/MCP compatibility fixtures (`test_cli_archive_episode.py`, `test_cli_archive_list.py`, `test_mcp_tools.py`) updated to seed canonical provenance so `archive_episode()` succeeds under the complete-content contract; one CLI test's hand-computed `archive_id` updated from the old workspace-only formula to the new content-bound one.
- **Tests:** focused (`test_archive_manager.py` + `test_archive_content_plan.py`): **56 passed**. Provenance (`test_build_manifest_provenance.py`): **9 passed**. Mission 15B/15C/15D neighboring (`test_archive_package.py`, `test_archive_integrity.py`, `test_archive_rev1_db_contract.py`): **77 passed, 4 skipped** (same real-symlink-privilege skips as every prior Phase 15 mission). `test_build_orchestrator.py`: **14 passed**. Manifest loader/validator (untouched, confirmed unaffected): **59 passed, 2 skipped**. CLI/MCP compatibility: **73 passed, 4 failed** (the same pre-existing YAML-escaping bug, identical by name to baseline, untouched). Full `tests/unit`: **2433 passed, 29 failed, 13 skipped** — the 29 failures are identical by name to the Mission 15E baseline (2394 passed/29 failed/13 skipped); the +39 passed delta is exactly this mission's new test count (13 + 15 + 7 + the narrow correction's 4). **Zero new or different failures.**
- **Resolve/live-database/production-media contact: zero.** No live `redline.db`, no RLC-E9901 or other production filesystem path, no Resolve connection anywhere in source or tests. Mission 15E remains uncommitted pending this work; Mission 15F (CLI/MCP transport migration) and Mission 15G (production evidence, DB metadata snapshot, configuration snapshot, software/repository identity) remain unstarted and out of scope.

## Unreleased - Phase 15 Mission 15E: Archive Manager Rev1 Orchestration (synthetic tests only, live archive not yet authorized)

Mission 15E wires the three already-published Phase 15 layers — Mission 15B's guarded `Database.commit_verified_archive()`, Mission 15C's filesystem integrity engine, and Mission 15D's package builder — into `ArchiveManager.create_archive()`, the new authoritative Rev1 archive path: copy-only, render-eligibility gated, non-destructive, Resolve-independent, `folder_path`-preserving. Every test uses a synthetic `tmp_path` workspace/archive-root and a temporary SQLite DB; no production archive root, RLC-E9901, or Resolve connection was touched.

- **New `ArchiveManager.create_archive(episode_id, *, render_job_id=None) -> ArchiveResult`.** Eligibility, checked fail-closed before any filesystem copy begins: episode exists; an existing `archives` row is checked *first* (independent of episode status, so a stale/orphaned row is never masked by a generic "not rendered" error) — a committed Rev1 row raises the pre-existing `EpisodeAlreadyArchivedError` unchanged, a legacy row raises the new `ArchiveLegacyRecordError` and is never reclassified as verified Rev1; `episode.status == 'rendered'`; `folder_path` set and a real directory; no active assembly claim (Mission 15A's invariant); no render job for the episode still `claiming`/`queued`/`rendering` (SQLite is the sole authority — Resolve is never contacted); a render job is selected (below); the selected job's `output_path` exists on disk and resolves inside the episode workspace.
- **Render job selection.** An explicit `render_job_id` must belong to the episode and be `'complete'`, or `ArchiveRenderSelectionError` names exactly which condition failed. With no explicit ID: exactly one `'complete'` job auto-selects; zero or more than one both fail closed — never latest/highest/first-guessed, per approved architecture.
- **Deterministic archive identity**, never timestamp-derived: `f"{episode_id}-a1-{source_set_digest[:12]}"`, computed only after the source inventory is built — stable for an unchanged source set, safe as a directory-name component.
- **Ordering**: `integrity.build_source_inventory(folder_path)` → derive `archive_id` → one clock read shared between the package's `created_at_utc` and the DB's `verified_at` (an optional `ArchiveManager(config, db, clock=...)` constructor param, matching Mission 15D's own injected-clock pattern — `ArchiveManager(config, db)` still works unchanged everywhere it's already constructed) → `package.build_archive_package(...)` (Mission 15D, unmodified, unduplicated) → only once that succeeds, `db.commit_verified_archive(...)` (Mission 15B, unmodified). Never a manually-reimplemented transaction.
- **New `ArchiveVerifiedUnregisteredError`** (`archive/exceptions.py`): raised when `commit_verified_archive()` fails *after* a successful, verified, published package — carries the verified package's own episode_id/archive_id/archive_path/manifest_path/manifest_sha256 for a future recovery path. Not an `archive_state` DB value (no `archives` row exists to hold one). The package is left exactly where it published; the episode remains `'rendered'`. Recovery/retry for this state, and for a pre-existing final-package directory found with no DB row (Mission 15D exposes no public primitive to independently re-verify an *arbitrary* existing final package without re-copying — Mission 15E does not invent one and fails closed on that collision via Mission 15D's own existing check instead), are both explicitly deferred to a later mission.
- **External-artifact reconciliation (required design finding).** The completed render master is *proven*, not assumed, to always live inside the episode workspace: `redline_core/render/plan.py`'s `build_render_output_plan()` computes every render's `output_path` under `episode_directory / preset.output_subfolder` and structurally enforces `output_directory.relative_to(episode_directory)`, raising otherwise — `create_archive()` additionally re-verifies this at runtime as defense in depth. Raw ingest media and approved graphics referenced by an episode's assembly manifest are a genuinely different, real gap: `MediaManager.organize_bins()` only imports *references* into Resolve's media pool (`resolve.import_media()`) and never copies ingest-path/assets-path files into the workspace, so that media permanently lives outside the single `SourceInventory` root Mission 15D's package API can represent today. Mission 15E does not extend the package builder to a multi-source shape to cover this from inside orchestration — recorded as a Mission 15G / package-API-extension concern, not silently dropped.
- **Legacy `archive_episode()` retained as a safe compatibility wrapper — a Mission 15E session decision, not the original brief's default.** The existing CLI (`cli/archive_commands.py`) and MCP (`mcp_server/tools/archive_tools.py`) entry points still call `ArchiveManager.archive_episode()` by name; Mission 15F, not 15E, owns transport migration. Rather than retiring it to a raising stub (which would have broken those currently-passing transport tests as an unavoidable side effect, argued and decided against in-session) or leaving its old `shutil.move()` body live (which item 2 of the mission explicitly prohibited), it now does exactly one thing: `return self.create_archive(episode_id)` — no branching, no destructive fallback, no dual semantics. Both transports' success-path serialization was updated to read the new `ArchiveResult` shape (`_archive_result_to_dict()` alongside the existing, untouched `_archive_to_dict()` that `list_archives()` still uses for raw `ArchiveRecord` rows) — no command/tool was renamed or added.
- **Existing CLI/MCP archive tests updated in place** (`test_cli_archive_episode.py`, `test_cli_archive_list.py`, `test_mcp_tools.py`'s `archive_tools` section): the tests that asserted the old destructive behavior (folder moved, `folder_path` became the archive path, a bare unrendered folder was archivable) now seed a properly rendered episode with a real completed render job and assert the new non-destructive success shape — they were exercising behavior this mission intentionally eliminated, not a stable contract. Four CLI tests remain failing for the same pre-existing, unrelated YAML double-quoted-scalar escaping bug in `write_isolated_config_dir()` documented since Mission 15B; untouched and unaffected either way. Parser/print/canned-dict tests in both files were not touched.
- **`tests/unit/test_archive_manager.py` rewritten**: 26 tests (was 6) covering successful archive (source preserved, package verified, DB row complete/schema-1, episode archived, render job unchanged, `folder_path` exactly unchanged — both inline and as a dedicated test), every non-rendered episode status, missing folder, active assembly claim, no completed render job, an active render job blocking archive even alongside a valid completed one (parametrized over claiming/queued/rendering), ambiguous multiple completed renders, explicit render selection, wrong render-job ownership, missing render output, a second `create_archive()` call after a committed archive, a legacy archive record, destination collision, the mandatory DB-commit-failure-after-publication case (`ArchiveVerifiedUnregisteredError`, package/source left intact, episode still rendered), a monkeypatched proof that `shutil.move`/`shutil.rmtree`/`Path.unlink` are never called on the success path, a static AST-based architecture test proving `manager.py` imports nothing Resolve-related (same style as `test_rlc_e9901_queue_attempt_harness.py`'s existing Resolve-import tests), and both `archive_episode()`-specific tests (delegates safely, raises `EpisodeAlreadyArchivedError` on a second call).
- **New exceptions** in `src/redline_core/archive/exceptions.py`: `ArchiveEligibilityError`, `ArchiveRenderSelectionError`, `ArchiveLegacyRecordError`, `ArchiveVerifiedUnregisteredError`. `EpisodeAlreadyArchivedError` and every Mission 15C/15D exception are reused unchanged wherever they already describe the failure accurately.
- **Tests:** focused (`test_archive_manager.py`): **26 passed**. Mission 15B/15C/15D (`test_archive_package.py`, `test_archive_integrity.py`, `test_archive_rev1_db_contract.py`): **77 passed, 4 skipped** (same 4 real-symlink-privilege skips as every prior Phase 15 mission). Neighboring CLI/MCP archive tests (`test_cli_archive_episode.py`, `test_cli_archive_list.py`, `test_mcp_tools.py`): **73 passed, 4 failed** — the 4 failures are the pre-existing YAML-escaping bug noted above, identical by name to baseline. Full `tests/unit`: **2394 passed, 29 failed, 13 skipped** — the 29 failures are identical by name to the Mission 15D published baseline (2374 passed/29 failed/13 skipped); the +20 passed delta is exactly this mission's growth in `test_archive_manager.py`. **Zero new or different failures.**
- **Resolve/live-database/production-media contact: zero.** No live `redline.db`, no RLC-E9901 or other production filesystem path, no Resolve connection anywhere in source or tests. No CLI/MCP command or tool was renamed or added (Mission 15F scope); the two transport source files received only the minimal `ArchiveResult`-serialization compatibility edit described above.

## Unreleased - Phase 15 Mission 15D: Archive Package Builder (synthetic-test-only filesystem copies, not yet consumed)

Mission 15D implements the package-construction layer a future Archive Manager Rev1 orchestration mission will consume: turning an already-verified Mission 15C `SourceInventory` into a sealed, hash-verified, atomically-published package directory. This is the first Phase 15 mission authorized to perform filesystem copies — but only against synthetic `tmp_path` fixtures; it does not archive RLC-E9901, does not use a production archive root, does not write SQLite, and does not contact Resolve. `ArchiveManager`, the CLI, MCP, and `Database.commit_verified_archive()` remain completely untouched and unconsumed by this new module.

- **New module `src/redline_core/archive/package.py`.** Two-phase API: `build_staged_package()` copies, verifies, and seals a complete package at `<archive-root>/.staging/<archive-id>.<attempt-id>.partial/` without publishing it; `publish_package()` independently re-verifies that sealed package and atomically renames it to `<archive-root>/episodes/<episode-id>/<archive-id>/`. `build_archive_package()` is a convenience wrapper calling both in sequence. The two-step split (rather than one opaque call) is what let this mission's own tests deliberately tamper with a sealed package between sealing and publication — several of the required failure tests depend on that seam existing. New immutable models `StagedPackage` and `PackageResult` (the latter deliberately carries no DB/episode-status field — filesystem package construction and DB registration are distinct boundaries).
- **Destination collision policy fails closed twice.** `build_staged_package()` checks the final destination before any copying begins — before any I/O against the source happens at all. `publish_package()` rechecks immediately before the rename, closing the race window between the two calls (proven by a dedicated test that creates the final destination directory *after* staging is sealed but *before* publish is called). Publication uses `os.rename()`, never `os.replace()` — on this repository's target Windows filesystem, `os.rename()` raises rather than silently replacing an existing destination directory, which is the never-overwrite guarantee required here; the explicit pre-rename recheck does not rely on that OS behavior alone.
- **Per-file copy + verification reuses Mission 15C's primitives directly — no second hashing routine.** Each file is copied with a chunked `shutil.copyfileobj()` (destination opened `'xb'`, never overwriting), then the *source* is re-hashed with `integrity.hash_stable_file()` and required to still match the inventory's recorded hash/size (source changed since the inventory was built → `ArchiveSourceChangedError`, without deleting, moving, or otherwise touching the source), then the *destination* is hashed with the same primitive and required to match too (mismatch → `ArchiveCopyVerificationError`). Reusing `hash_stable_file()` for the destination also gets destination object-safety for free — a copied file unexpectedly becoming a symlink/junction, or disappearing, fails closed with Mission 15C's own `ArchiveUnsafeFilesystemObjectError`/`ArchiveSourceChangedError`.
- **Completeness is independently verified twice, not assumed from per-copy success.** The recreated source topology lives under its own `payload/` subdirectory of the staging path (kept separate specifically so it can never collide with the manifest/sidecar/marker files written alongside it). After every file is copied, `payload/` is re-enumerated with a full `integrity.build_source_inventory()` walk — not a weaker duplicate traversal — and compared against the original inventory for missing files, unexpected files, missing directories, unexpected directories, hash mismatches, and size mismatches; any nonzero count raises `ArchivePackageVerificationError`. The identical check runs again, unconditionally, as the first step of `publish_package()`'s pre-publication re-verification, which is what catches a destination corrupted (or a stray file injected, or a file removed) after staging was originally verified but before publication.
- **Archive Manifest Rev1**, written only after every check above passes: canonical JSON (UTF-8, `sort_keys=True`, compact separators — no incidental whitespace) with top-level `schema_version` (1), `archive_id`, `episode_id`, `created_at_utc`, `source` (`source_root`, `source_set_digest`), `artifacts` (`source_relative_path`, `archive_relative_path` prefixed `payload/`, `size_bytes`, `sha256`, per file), `directories` (archive-relative, `payload/`-prefixed), `summary` (`file_count`, `directory_count`, `total_bytes`), and `verification` (`algorithm: "sha256"`, `completeness: "verified"`). Artifact/directory list order is preserved exactly from the already-deterministically-sorted `SourceInventory` — the manifest builder never re-sorts and never depends on dict/set iteration order, proven by a test asserting byte-identical manifests across two independent full builds of the same inventory. `created_at_utc` comes from an injected `Clock = Callable[[], datetime]` (default `datetime.now(timezone.utc)`), not monkeypatched global state, so tests can hold it fixed. Database episode/render-job snapshots, production evidence, and software/repository identity are deliberately **not** populated — this mission does not possess them; that is explicitly deferred to Mission 15G/orchestration.
- **Sealing order, and why it's provable.** `archive_manifest.json` is written first; its SHA-256 is then computed by reading the just-written file back through `hash_stable_file()` (not re-hashing the in-memory bytes) into `archive_manifest.sha256`; only then is the empty `PACKAGE_COMPLETE` marker written. A dedicated test corrupts a copy mid-loop (via a monkeypatched `_copy_file_chunked` that writes wrong bytes for the first file, deterministic, no thread timing) and asserts the resulting leftover staging directory contains neither the manifest, the sidecar, nor the marker — a failure before sealing cannot produce anything that looks sealed.
- **New exceptions** in `src/redline_core/archive/exceptions.py`: `ArchivePackageError` (base), `ArchiveDestinationCollisionError`, `ArchiveCopyVerificationError`, `ArchivePackageVerificationError`, `ArchivePublicationError`. Mission 15C's `ArchiveSourceChangedError`, `ArchiveUnsafeFilesystemObjectError`, and `ArchivePathError` are reused as-is everywhere they already describe the failure accurately (source mutation, destination object-safety, and a defense-in-depth destination-path-escape check on top of Mission 15C's already-normalized relative paths), per this mission's explicit instruction not to multiply exception types.
- **New tests:** `tests/unit/test_archive_package.py` — 15 tests, all passing. Successful build (nested tree + empty directory, source untouched, payload byte/hash-identical, empty directory reproduced, manifest + sidecar + marker all valid, `PackageResult` fields correct), empty-directory preservation (dedicated), manifest determinism (both the internal builder directly, and full byte-identical manifests across two independent end-to-end builds), destination collision before any build work begins, atomic-publication collision race (destination appears between sealing and publish), source changed after the inventory was built, source changed during the copy window (deterministic monkeypatch of the copy step, not thread timing), destination corruption / a missing copied artifact / an unexpected injected artifact / manifest tampering — each detected by `publish_package()`'s pre-publication re-verification and each proven to leave the final destination unpublished and the source untouched, `PACKAGE_COMPLETE` ordering (a mid-copy failure leaves no manifest/sidecar/marker in the abandoned staging directory), and two `episode_id`/`archive_id` path-separator-rejection tests (defense in depth, since both become literal path-name components).
- **Tests:** focused (`test_archive_package.py`): **15 passed**. Neighboring archive regression (`test_archive_integrity.py`, `test_archive_manager.py`, `test_archive_rev1_db_contract.py`): **63 passed, 4 skipped** — identical to the Mission 15C published baseline (same 4 real-symlink-privilege skips). Full `tests/unit`: **2369 passed, 29 failed, 13 skipped** — the 29 failures are identical by name to the Mission 15C published baseline (2354 passed/29 failed/13 skipped); the +15 passed delta is exactly this mission's new focused test file. **Zero new or different failures.** (This session's environment had a stray, unrelated `cli` package installed in user site-packages that shadows this repository's own `src/cli` package and breaks `pytest`'s default collection of every CLI test file with an `ImportError` unless invoked with `PYTHONPATH=src` — already documented as a supported invocation in `README.md`. This is a pre-existing local-environment condition, not caused by this mission and not repaired by it; the full-suite run above used `PYTHONPATH=src` specifically to route around it and obtain an honest count. It affects zero archive/integrity/package tests.)
- **Resolve/live-database/production-media contact: zero.** No `ArchiveManager`, `Database`, CLI, or MCP code touched or exercised. No RLC-E9901 or any other production filesystem path referenced anywhere in source or tests. No production archive root used — every test constructs its own `tmp_path`-based `archive_root`.
- **Narrow source-integrity correction (same Mission 15D, applied before publication approval, not a new mission).** Two related gaps in the source guarantee above were closed:
  1. **The copy read itself is now protected, not just hashed afterward.** New `integrity.open_stable_source()` — a context manager extracted from `hash_stable_file()`'s own body — yields `(handle, size_bytes)` after proving the same four checkpoints `hash_stable_file()` already proved (pre-open pathname `lstat`, opened-descriptor `fstat` matching it, a second `fstat` matching that once the caller's block completes without raising, and a final post-close pathname `lstat`); `hash_stable_file()` is refactored to consume it (identical public signature, identical exceptions, identical error messages), and `package._copy_file_chunked()` now reads from the same yielded handle via `shutil.copyfileobj()` instead of a plain `Path.open()`. This closes the gap where the copy's own `open()` had no way to refuse a pathname swapped for a different object between the original inventory and the moment the copy itself opened it. It is additional to, not a replacement for, the pre-existing separate post-copy source re-hash and destination hash — both still run unchanged.
  2. **A final whole-source-tree reconciliation runs before sealing.** New `package._reconcile_complete_source_set()` rebuilds a fresh `SourceInventory` from the original inventory's own root via `integrity.build_source_inventory()` and requires its `source_set_digest` to still equal the digest of the `SourceInventory` the package was built from — the same deterministic digest Mission 15C already defines, not a second tree-comparison format. Runs once, immediately after payload completeness verifies and strictly before `archive_manifest.json`/`.sha256`/`PACKAGE_COMPLETE` are written, closing the gap that per-file re-hashing cannot: a file or directory *added* since the inventory was built has no prior entry to be re-verified against. A mismatch fails closed (`ArchiveSourceChangedError`); the fresh inventory is used only for the comparison and is discarded, never adopted, never used to rebuild the package.
  - **Implementation note:** `open_stable_source()`'s internal cleanup uses `with fh:` (relying on the opened file object's own context-manager protocol) rather than calling `fh.close()` directly, specifically so it stays compatible with Mission 15C's own existing `test_hash_stable_file_reads_in_bounded_chunks_not_whole_file` test double (which implements `__enter__`/`__exit__` but not a bare `.close()`) — that pre-existing test required no changes.
  - **New tests** (`tests/unit/test_archive_package.py`, +5, now 20 total): two copy-path safe-descriptor tests mirroring Mission 15C's own `hash_stable_file()` mutation tests exactly (opened-handle-vs-pre-open-identity mismatch, and opened-handle-changes-during-streaming), both deterministic via the identical inode/device-matched `os.fstat` call-count monkeypatch technique Mission 15C's own tests use (patching `integrity.os.fstat`, which the copy path now goes through); and three source-set-reconciliation tests (a new file added after the inventory was built, a new empty directory added, and a file renamed — the missing original path is caught even earlier, by the copy loop's own `open_stable_source` pre-open check, which is a valid and equally fail-closed outcome). Every new test asserts the source tree is untouched (or, where the test itself intentionally mutated it, that the mutation was preserved and not "repaired") and that no leftover staging directory contains a manifest, sidecar, or `PACKAGE_COMPLETE`. Each of the two new-entry tests was verified to actually depend on the new reconciliation step by temporarily removing the call and confirming both then fail to raise.
  - **Tests:** focused (`test_archive_package.py`): **20 passed** (15 prior + 5 new). Mission 15C integrity + neighboring archive regression: **63 passed, 4 skipped** — unchanged from this mission's own prior run (`test_hash_stable_file_reads_in_bounded_chunks_not_whole_file` and every other pre-existing `test_archive_integrity.py` test pass unmodified against the refactored `hash_stable_file()`/new `open_stable_source()`). Full `tests/unit`: **2374 passed, 29 failed, 13 skipped** — the 29 failures are identical by name to this mission's own prior run and to the Mission 15C published baseline; the +5 passed delta is exactly the new tests. **Zero new or different failures.**
  - **Resolve/live-database/production-media contact: zero**, same as above. `ArchiveManager`, the CLI, MCP, and `Database.commit_verified_archive()` remain untouched.

## Unreleased - Phase 15 Mission 15C: Archive Inventory & SHA-256 Integrity Engine (read-only primitives, not yet consumed)

Mission 15C implements the transport-neutral filesystem integrity layer a future Archive Manager Rev1 (Mission 15D+) will consume to build verified archive packages. It performs **no filesystem mutation whatsoever** — no copying, no destination/staging creation, no archive execution — and is not wired into `ArchiveManager`, the CLI, MCP, `commit_verified_archive()`, or Resolve in any way. Every test operates on `tmp_path` fixtures; no production media was read or inspected.

- **New module `src/redline_core/archive/integrity.py`.** Read-only primitives: `validate_source_root()`, `build_source_inventory()`, `hash_stable_file()`, plus the immutable `InventoryDirectory`/`InventoryFile`/`SourceInventory` models. Deliberately kept as one module (not split into `models.py`/`fsops.py`) — the whole surface is small enough that splitting it would be file-count churn without a real boundary to justify it.
- **Root/object safety.** Every filesystem object (the root itself, and every discovered entry) is classified via `os.lstat()` before being trusted: a symlink, a Windows junction, or any other reparse point is rejected outright (`ArchiveUnsafeFilesystemObjectError`), regardless of what it points to — inside the root, outside it, or as the root itself. Windows junction detection uses `os.stat_result.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT` (stdlib-only, no elevated privileges, available since Python 3.5) rather than `Path.is_junction()` (3.12+ only, and this repo supports 3.10+) — **empirically verified** against a real `New-Item -ItemType Junction` in this repository's actual environment: `Path.is_symlink()` returns `False` for a genuine junction (confirming it alone is insufficient), while the `st_file_attributes` check correctly returns `True`. Anything that is neither a regular file, a directory, nor a rejected link (named pipe, device, socket, etc.) is also rejected, never silently skipped.
- **Streaming SHA-256 with stability proof, strengthened to the opened-handle level (narrow correction, same session).** `hash_stable_file()` now validates four checkpoints, not two: (1) a pre-open pathname `lstat()` (also the safety check), (2) `os.fstat()` on the just-opened file descriptor, required to match #1 — closing the gap where `open()` would silently follow a symlink that appeared at the path after #1's check, since `open()` itself has no way to refuse that, (3) `os.fstat()` on the same descriptor again after streaming every chunk (never `read_bytes()`), required to match #2, and (4) a final pathname `lstat()` after closing, required to match #1. All four compare the same fingerprint (size, `mtime_ns`, inode/device where the platform reports them). Any mismatch raises `ArchiveUnsafeFilesystemObjectError` (wrong object type) or `ArchiveSourceChangedError` (identity changed) and returns no hash. Still self-contained and stdlib-only — no filesystem locking, no Win32 reparse APIs, no double-hashing.
- **Deterministic recursive inventory.** Every entry's identity is `(source root, normalized relative path)`, not an absolute path alone; relative paths are POSIX-style (`/`-separated) and case-insensitively collision-checked (`_register_relative_identity()`/`ArchiveInventoryError`) unconditionally — not only on Windows — since a Rev1 package targets a Windows production filesystem regardless of which OS built it. Final ordering is an explicit sort by case-folded relative path, not filesystem enumeration order. Directories are first-class inventory entries (not just files), so an empty directory required by the production folder structure is preserved for a future restore.
- **Tree-mutation reconciliation.** After the main pass, the tree is re-enumerated (structure only, no re-hash) and compared against the initial enumeration; any file/directory added or removed in between raises `ArchiveSourceChangedError`. Documented limitation (module docstring): this is not a filesystem lock — a precisely-timed replacement with identical size/mtime could theoretically evade both this and the per-file stability check. No locking is attempted, per the mission's explicit constraint; the module fails closed on every mutation it is able to observe.
- **Source-set digest.** A canonical logical representation (`{"schema_version": 1, "directories": [...], "files": [{"path", "size_bytes", "sha256"}, ...]}`), serialized as UTF-8 JSON with sorted keys and compact separators, then SHA-256'd — not a concatenation of raw file bytes. Same tree → same digest; content change, rename, add, delete, or empty-directory add/remove → different digest. This is an internal integrity primitive, not the future Archive Manifest Rev1 document, and is not stored in SQLite (consistent with Mission 15B's "SQLite is pipeline state, not media/filesystem content" boundary).
- **New exceptions** in `src/redline_core/archive/exceptions.py`: `ArchivePathError`, `ArchiveUnsafeFilesystemObjectError`, `ArchiveSourceChangedError`, `ArchiveInventoryError` (all subclass the existing `ArchiveError`). `ArchiveIntegrityError` was deliberately **not** added — Mission 15C has no source/destination comparison yet to raise it for; it will be added when a mission actually needs it.
- **Reuse review:** `redline_core/asset/path_policy.py` and `asset/reconciliation/canonical.py` were reviewed (per Mission 15A's finding) and used only as a *pattern* reference (canonical-root resolution, `hashlib` usage) — their actual code was not imported or reused, since `path_policy.py` validates a single declared file path against one approved root and does not reject a *working* symlink (only a broken one), which is weaker than Archive Rev1's reject-all-symlinks policy and not built for recursive-tree walking. No changes were made to the Asset Registry subsystem.
- **New tests:** `tests/unit/test_archive_integrity.py` — 34 tests (30 passed, 4 skipped; +2 from the opened-handle correction below). Root validation, basic inventory (files/directories/counts/bytes), streaming-hash correctness and chunked-read structural proof, deterministic source-mutation detection via monkeypatching (pathname-level, opened-handle-vs-pathname mismatch, opened-handle-during-streaming mutation, and tree-level add/remove), symlinked file/directory/root rejection (skipped in this session's environment only because it lacks the admin/Developer Mode privilege real symlink creation requires — confirmed by direct attempt, not assumed), real Windows junction rejection (root and nested — these ran for real, not skipped, since junction creation needs no elevated privilege), a synthetic reparse-point-detection unit test independent of real link creation, deterministic ordering across differing creation order, source-set digest stability and sensitivity (content/rename/add/delete/empty-dir), and synthetic normalized-identity-collision rejection (not dependent on a real Windows filesystem permitting a case-only duplicate).
- **Tests:** focused (`test_archive_integrity.py`): **30 passed, 4 skipped**. Neighboring archive/asset regression: unchanged from established baseline (same 4 pre-existing YAML-escaping CLI failures; 444 asset path_policy/reconciliation tests unaffected). Full `tests/unit`: **2354 passed, 29 failed, 13 skipped** — the 29 failures are identical by name to the Mission 15B published baseline (2324 passed/29 failed/9 skipped); the +30 passed delta is exactly this mission's test file (the +4 skipped are the same real-symlink tests, unchanged). **Zero new or different failures.**
- **Resolve/live-database/production-media contact: zero.** No `ArchiveManager`, `Database`, CLI, or MCP code touched. No RLC-E9901 or any other production filesystem path referenced anywhere in source or tests.

## Unreleased - Phase 15 Mission 15B: Archive Manager Rev1 Database Contract (foundation only, not yet consumed)

Mission 15A (architecture reconciliation, read-only) confirmed the existing `ArchiveManager.archive_episode()` is destructive (`shutil.move()`), ungated on render status, rewrites `episode.folder_path` to the archive location, and performs three separate unguarded commits (archive insert, episode-status update, episode-path update) with no hashing, manifest, staging, or recovery model. Mission 15B implements **only the SQLite/model foundation** a future, non-destructive Archive Manager Rev1 will consume — it does **not** change `ArchiveManager`'s behavior at all. The existing destructive archive path is still exactly what runs today; this entry does not claim otherwise.

- **`archives` table evolved in place**, via the repository's existing additive-migration pattern (`schema.sql` + `Database.init_schema()` + a new `_migrate_add_archive_rev1_columns()` + `PRAGMA table_info(...)` + `ALTER TABLE ... ADD COLUMN`) — no new table, no migration framework. New columns: `archive_id TEXT`, `archive_schema_version INTEGER NOT NULL DEFAULT 0`, `archive_state TEXT NOT NULL DEFAULT 'legacy'`, `manifest_path TEXT`, `manifest_sha256 TEXT`, `render_job_id INTEGER REFERENCES render_jobs(id)`, `verified_at TEXT`. The existing `episode_id TEXT NOT NULL UNIQUE` constraint is unchanged and continues to enforce one committed archive per episode.
- **Legacy rows are explicitly, automatically classified, never fabricated.** The `DEFAULT 0` / `DEFAULT 'legacy'` migration backfills every pre-existing `archives` row to `archive_schema_version = 0`, `archive_state = 'legacy'` the moment the migration runs; the other new columns stay `NULL` for those rows. No historical row is or can be silently reclassified as a verified Rev1 archive.
- **New `db.models.ArchiveState` enum** (`LEGACY`, `COMPLETE` — deliberately only these two; `VERIFIED_UNREGISTERED` is explicitly *not* an `archive_state` value, since it describes the absence of a committed archive row, not a state of one). `ArchiveRecord` gains the seven new fields (all typed, all optional/defaulted for legacy compatibility); `from_row()` reads the migrated schema.
- **New `Database.commit_verified_archive()`** — the one authoritative transactional writer for Rev1 archives. In one SQLite transaction: an `INSERT ... SELECT ... WHERE` re-tests every precondition (episode exists and is `rendered`; the named render job exists, belongs to the episode, and is `complete`; no archive row already exists for the episode) against the database's actual state at execute time — not an earlier read — so a zero-row insert (and this method raising) is the real authorization failure, not a stale pre-check; a separate pre-check pass exists only to produce a precise error message. The subsequent `UPDATE episodes SET status = 'archived' ... WHERE episode_id = ? AND status = 'rendered'` must affect exactly one row or the method raises. Both statements share one `with self.conn:` block, so a failure at either point rolls back the entire transaction — an archive row can never survive without its episode transition, or vice versa. This method never writes `episodes.folder_path`. New `ArchiveCommitError` exception.
- **Existing `Database.create_archive_record()` retained, now documented as legacy-only** — it is still the method `ArchiveManager.archive_episode()` calls (unchanged in this mission); a row inserted through it always gets the schema defaults (`archive_schema_version=0`, `archive_state='legacy'`), the same classification as genuinely historical rows, because it never touches the new columns. It must not be used by Archive Manager Rev1.
- **New tests:** `tests/unit/test_archive_rev1_db_contract.py` (15 tests) — fresh-DB schema shape, legacy-DB migration (hand-built pre-Rev1 `archives` table + historical row, verified preserved and correctly classified after `init_schema()`), successful guarded commit, rejection of non-rendered episode / wrong render-job ownership / every non-`complete` render-job status / an already-archived episode, direct proof the `UNIQUE` constraint still backs the one-archive invariant, a forced mid-transaction failure proving atomic rollback (archive insert does not survive a failed episode transition), and `ArchiveRecord` insert/reload/list round-trip for both legacy and Rev1 rows.
- **Explicitly not implemented in this mission:** SHA-256 hashing (filesystem, source, or destination), archive manifests, filesystem copy/inventory/tree-walking, staging directories, atomic filesystem rename/publication, collision detection, `ArchiveManager` Rev1 orchestration, any CLI/MCP `archive create`/`archive verify` surface, and no DaVinci Resolve or RLC-E9901 access of any kind. The existing destructive `ArchiveManager` has not been touched or replaced.
- **Tests:** focused (`tests/unit/test_archive_rev1_db_contract.py`): **15 passed**. Archive/DB-adjacent regression (`test_archive_manager.py`, `test_cli_archive_episode.py`, `test_cli_archive_list.py`, `test_db.py`, `test_db_schema_resource.py`): **52 passed, 4 failed** — all 4 failures are a pre-existing, unrelated YAML double-quoted-scalar escaping bug in `write_isolated_config_dir()` test helpers (a `C:\Users\...` path's `\U` substring is parsed as a Unicode escape), confirmed present and unmodified by this mission. Full `tests/unit` regression, compared directly against this same HEAD with Mission 15B's tracked changes stashed out: baseline **29 failed, 2297 passed, 9 skipped**; with Mission 15B **29 failed, 2312 passed, 9 skipped** — identical 29 failures by name in both runs; the +15 passing tests are exactly the new focused suite. Mission 15B introduces zero new or different failures. `git diff --check` exits `0`.
- **Resolve/live-database contact: zero.** No `RenderManager`/`ResolveAdapter` code touched. No live Phase 14 runtime SQLite database accessed. No RLC-E9901 filesystem access. Nothing staged, committed, or pushed.

## Unreleased - Phase 14 Render Queue Snapshot Probe Rev5 (post-status temporal rebracket; construction-only, not live-verified)

Independent Rev4 source review completed and returned a publication-blocking finding rather than an approval: `POST_STATUS_REBRACKET_REQUIRED` / `REV4_REQUIRES_CORRECTION`. Rev4's own `GetRenderJobStatus()` calls ran *after* the pre-existing "final" identity/rendering guard (Rev2 Finding 5's own third guard), and nothing re-established project identity, timeline identity, `rendering == false`, or queue stability *after* those calls before evidence was published — a published Rev4 snapshot could theoretically combine a `rendering=false` observation from before the status-fetch window with a `JobStatus=Ready` observation from during/after it, with no proof the two were ever simultaneously true. This entry documents the Rev5 correction. See `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §12 for the full record; the Rev4 finding itself is preserved there, not erased or reinterpreted.

- **Post-status rebracket added.** New `_post_status_rebracket()`, called once, strictly after every `GetRenderJobStatus()` call and strictly before the snapshot dict is constructed. Re-verifies project identity, timeline identity, and `IsRenderingInProgress() is False` (reusing `_verify_context_and_rendering_inactive()` unchanged), **and** re-reads the render queue a third time (`GetRenderJobList()`), requiring it to normalize identically to the already drift-verified queue — fails closed (`post_status_queue_drift`) otherwise. **Option B chosen over Option A** (context/rendering re-guard alone): the queue's own identity claims (count, exact job presence, output binding) are exactly what `JobStatus` is meant to be combined with for a single, simultaneous final-ignition proof, so queue stability across the status-fetch window is explicitly re-proven, not merely assumed via context stability alone.
- **Published evidence now uses the post-status guard's fresh values.** `observed_context`/`rendering_in_progress` come from the new fourth guard, never from the third (pre-status) guard's now-stale observation.
- **No new Resolve method introduced.** The allowlist remains the same seven methods Rev4 introduced — `GetRenderJobList` is simply read a third time (allowlisted since Rev1); no new method name, no widened surface.
- **Call-sequence shape:** four context/rendering guards and three `GetRenderJobList()` reads (was three guards / two reads through Rev4). `GetRenderJobStatus()` itself is unchanged — still Rev4's addition, still called only for identified entries, still using the pre-status guard's project handle, still sanitized identically strictly.
- **Revision identifier bumped:** `EXECUTION_REVISION_ID` / `ACCEPTED_COLLECTOR_REVISIONS` = `phase14.2-render-queue-snapshot-construction-rev5`; Rev1/Rev2/Rev3/Rev4 identifiers and any snapshot document carrying one of them are explicitly rejected, consistent with existing policy (not broadened). A Rev4 snapshot document in particular must not be trusted as Rev5 evidence — it carries no post-status rebracket guarantee.
- **Everything else preserved unchanged:** non-empty-queue support, `GetRenderJobStatus`/`job_status` schema and fail-closed sanitization, offline `compare` (still zero Resolve contact), the optional `--expected-job-status` assertion (still exact case-sensitive, still offline), evidence create-only/collision-safe publication, zero SQLite dependency, zero reachable Resolve mutation. `scripts/phase14_resolve_context_snapshot.py` (Rev8 collector) untouched, byte-identical. No production render-start code (`RenderManager.start_render`, `ResolveAdapter.start_render`, `StartRendering` call sites) changed.
- **Files changed:** `scripts/phase14_render_queue_snapshot.py`, `tests/unit/test_phase14_render_queue_snapshot.py` (18 new/updated tests: 6 new adversarial temporal-rebracket scenarios — rendering starts after status fetch, project identity changes after status fetch, timeline identity changes after status fetch, stable post-status state passes, fresh post-status values gate publication, post-status queue re-read drift/stability — plus revision-identity, allowlist, and call-count assertions updated from 3-guard/2-read to 4-guard/3-read), `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` (new §12, plus stale Rev3-era literal revision-ID examples in §7/§8/§9 corrected to the current value). No other file changed.
- **Tests:** focused (`tests/unit/test_phase14_render_queue_snapshot.py`, Python 3.11.9): **249 passed**. Render/Phase14/RLC-E9901-focused (`-k "render or phase14 or rlc_e9901"`): **1194 passed**. Full `tests/unit` regression (network-sensitive `test_installed_db_bootstrap_smoke.py` test deselected, per its already-established Rev4-review non-determinism): **2301 passed, 24 failed, 9 skipped** — the exact same 24 pre-existing Windows-temp-path/YAML-escaping CLI fixture failures as every prior baseline, by name. `git diff --check` exits `0`.
- **Resolve contacts during this construction: zero.** `StartRendering()`/`AddRenderJob()`/`DeleteRenderJob()`/`StopRendering()`/`run-live-preflight`/`snapshot` (live subcommand) executions: **zero**. SQLite writes: **zero**. Nothing staged, committed, or pushed.
- **This entry does not authorize live execution.** The post-status rebracket, like the rest of `snapshot`'s live path, has not been exercised against a real, running Resolve instance under Rev5 — only mocked unit tests exercise it. A separate, explicit founder authorization is required first, exactly as for every prior revision. Rev5 has not itself been independently reviewed or approved as of this entry.

## Unreleased - Phase 14 Render Queue Snapshot Probe Rev4 (target-job status; construction-only, not live-verified)

RLC-E9901 final-ignition tool-selection review traced the real, live-captured
`RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json` /
`RLC-E9901_render_queue_comparison_rev3_20260810T234031Z.json` evidence back
to `scripts/phase14_render_queue_snapshot.py` (not the empty-queue-only
`phase14_resolve_context_snapshot.py`) and found its one remaining gap: the
target job's own `JobStatus` (needed to prove `Ready` before any future,
separately authorized `StartRendering()`), which `GetRenderJobList()` does
not return. See `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §11 for the
full design record.

- **New getter: `GetRenderJobStatus`.** Added to `READ_ONLY_RESOLVE_METHODS`
  (six methods → seven; no other name added). `snapshot` (live collection)
  calls it once per **identified** queue entry, using the current-project
  handle the existing final identity/rendering guard already confirmed,
  only after the existing pre/post drift check has already proven the
  queue is stable. `compare` (offline evaluation) gains **zero** new
  Resolve calls — the `snapshot`/`compare` boundary is unchanged.
- **New evidence field: `job_status`.** Per queue entry, alongside the
  existing `index`/`job_id`/`job_id_status`/`fields`. Always a trustworthy
  non-empty string for an `"identified"` entry, always `null` for an
  `"unidentified"` one — any malformed/missing/falsy `GetRenderJobStatus`
  response fails the **entire** snapshot collection closed
  (`render_job_status_missing` / `render_job_status_invalid` /
  `render_job_status_field_missing` / `render_job_status_field_invalid`)
  rather than publishing a placeholder value, mirroring the existing
  `job_id`/`job_id_status` fail-closed contract exactly.
  `validate_queue_snapshot_document()` enforces the identical invariant on
  any input document; `_REQUIRED_ENTRY_KEYS` is now five keys, not four.
- **New optional offline assertion: `compare --expected-job-status`.**
  Inspects the already-captured `job_status` of whatever entry
  `--expected-job-id` resolves to, only once that resolves unambiguously to
  `exact_single_job_match`; fails closed (`expected_job_status_invalid` /
  `expected_job_status_requires_expected_job_id`, or a `job_status_check`
  classification of `"not_applicable"`/`"status_mismatch"` mapped to a
  nonzero CLI exit code) rather than ever treating a missing, ambiguous, or
  mismatched status as `Ready`. Case-sensitive exact match, no
  normalization. Omitting the flag reproduces Rev3's exact existing output
  shape and exit codes for every other field — additive, backward
  compatible.
- **Revision identifier bumped:** `EXECUTION_REVISION_ID` /
  `ACCEPTED_COLLECTOR_REVISIONS` = `phase14.2-render-queue-snapshot-construction-rev4`;
  Rev1/Rev2/Rev3 identifiers and any snapshot document carrying one of them
  are explicitly rejected. `SCHEMA_VERSION` deliberately left at `"1.0"`,
  consistent with Rev1→Rev2→Rev3 precedent (cross-revision compatibility is
  gated by `collector.revision`, not `schema_version`).
- **Files changed:** `scripts/phase14_render_queue_snapshot.py`,
  `tests/unit/test_phase14_render_queue_snapshot.py` (56 new tests, plus
  targeted fixture/helper updates so `_REQUIRED_ENTRY_KEYS`'s new fifth key
  doesn't break pre-existing raw-dict test entries),
  `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` (new §11). No change to
  `scripts/phase14_resolve_context_snapshot.py` (the Rev8 collector — its
  own empty-queue invariant is untouched, byte-identical SHA-256
  re-verified), `scripts/rlc_e9901_snapshot_preflight_contract.py`,
  `scripts/rlc_e9901_preflight_assertion.py`, `RenderManager.start_render`,
  `ResolveAdapter.start_render`, or any other production render-start code.
- **Tests:** focused (`tests/unit/test_phase14_render_queue_snapshot.py`,
  Python 3.11.9): **231 passed**. Render/Phase14/RLC-E9901-focused
  (`-k "render or phase14 or rlc_e9901"`): **1176 passed**. Full
  `tests/unit` regression: **2283 passed, 25 failed, 9 skipped**. All 25
  failures independently confirmed pre-existing and unrelated: 24 are the
  already-documented Windows-temp-path/YAML-escaping CLI fixture failures
  (`test_cli_archive_*`, `test_cli_asset_*`, `test_cli_episode_*` —
  `yaml.scanner.ScannerError` parsing a pytest tmp path inside
  `folder_structure.yaml`, unrelated to this change's files); the 25th
  (`test_installed_db_bootstrap_smoke.py::test_installed_package_initializes_database_outside_repo`)
  is a network-dependent `pip install` bootstrap check failing on
  `setuptools>=68` distribution lookup, also unrelated and consistent with
  this suite's known flakiness. `git status --short` confirms only the two
  intended files changed throughout. `git diff --check` exits `0`.
- **Resolve contacts during this construction: zero.**
  `StartRendering()`/`AddRenderJob()`/`DeleteRenderJob()`/`StopRendering()`/
  `run-live-preflight`/`snapshot` (live subcommand) executions: **zero**.
  SQLite writes: **zero** (this probe has no database dependency at all —
  statically confirmed, no `sqlite`/db-import reference anywhere in its
  source). Nothing staged, committed, or pushed.
- **This entry does not authorize live execution.** `snapshot`'s live path,
  including the new `GetRenderJobStatus` call, has not been exercised
  against a real, running Resolve instance under Rev4 — only mocked unit
  tests exercise it. A separate, explicit founder authorization — binding
  the exact source SHA-256, `EXECUTION_REVISION_ID`, expected
  project/timeline, and a fresh evidence path — is required first, exactly
  as for every prior revision.

## Unreleased - Production Render Start Path Rev4 Narrow Correction (construction-only; not live-verified)

Independent exact-source review of the Rev3 bundle below **ACCEPTED** the overall start-pathway architecture and safety model. One narrow BLOCKING integration mismatch remained, evidence-backed against a real Resolve queue snapshot rather than speculative. This entry documents the Rev4 correction. Fully offline: `Resolve contacts: 0`, `StartRendering calls: 0`, `AddRenderJob/DeleteRenderJob/StopRendering calls: 0`, `production queue attempts: 0`, nothing staged/committed/pushed. See `docs/RENDER_START_PATH_CONSTRUCTION.md` §8 for the full record and `docs/ARCHITECTURE.md` §3.8 for the corrected design.

- **Finding 1 (BLOCKING) — Resolve's `OutputFilename` includes the extension.** `ResolveScriptAdapter._require_exact_queued_output_destination()` compared the matched queue entry's `OutputFilename` against `Path(expected_output_path).stem` (the extensionless filename). Live getter-only evidence captured from a real, running Resolve Studio 21.0.3.7 instance (`RLC-E9901_render_queue_snapshot_rev3_20260810T233837Z.json`, SHA-256 `f2afab5c4e2fb04821c928511341801e3ae6c232ed9fbbe70151c369710c8975`, independently re-verified against the file on disk) shows Resolve reports the complete filename, extension included (`"OutputFilename": "RLC-E9901_MASTER.mov"`, not `"RLC-E9901_MASTER"`) — so Rev3's check would have failed closed before `StartRendering()` for every real queued job. Corrected to compare against `Path(expected_output_path).name` instead. No extension stripped from the persisted path; none inferred from codec/format/preset. `TargetDir` binding, the `SetRenderSettings()`/`LoadRenderPreset()` prohibition, and every other Rev3-accepted property are unchanged.
- **Regression tests added:** `test_start_render_extension_bearing_output_filename_matches_and_starts` (queue entry shaped exactly like the real observed evidence passes and starts exactly once) and `test_start_render_extensionless_output_filename_fails_closed` (the Rev3-incorrect stem-only shape fails closed, zero `StartRendering()` calls) in `tests/unit/test_resolve_script_adapter_render_start.py`. The file's shared fixture constant was renamed `EXPECTED_OUTPUT_STEM` → `EXPECTED_OUTPUT_FILENAME` and now derives `Path(OUTPUT_PATH).name`, so every existing Finding-3 test exercises the corrected shape.
- **Mock fidelity documentation corrected.** `MockResolveAdapter.start_render()`'s docstring no longer claims its `CustomName`-vs-stem check is "logically equivalent" to real Resolve's `OutputFilename` representation. The check itself is unchanged (retained as an internal mock-fidelity detail — `queue_render_job()` only ever receives the extensionless stem from its caller, and this correction does not introduce speculative preset/format extension-inference logic to manufacture a complete filename); the docstring now states explicitly that it models queue-*input* identity, not the queue-*readback* shape, and that the real-adapter tests are authoritative for `OutputFilename`'s actual representation.
- **Static safety:** one AST test's allowed-attribute set updated from `{..., "stem"}` to `{..., "name"}` to match the corrected implementation. No new attribute surface, no prohibited name added. Still exactly one `StartRendering` call site; still zero start-path reachability into `AddRenderJob`/`DeleteRenderJob`/`DeleteAllRenderJobs`/`StopRendering`/`SetRenderSettings`/`LoadRenderPreset`/`LoadProject`/`SetCurrentTimeline`.
- Files changed from Rev3: `src/redline_core/resolve/adapter.py`, `src/redline_core/resolve/mock.py` (docstring only), `tests/unit/test_resolve_script_adapter_render_start.py`, `tests/unit/test_resolve_adapter_start_render_static_safety.py` (one assertion), `docs/RENDER_START_PATH_CONSTRUCTION.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `README.md`. No changes to `render/manager.py`, `render/exceptions.py`, `resolve/exceptions.py`, `db/database.py`, `cli/render_commands.py`, `test_render_manager.py`, `test_cli_render.py`, or `test_rlc_e9901_queue_attempt_harness.py` — re-verified passing unchanged.
- Focused (adapter start + static safety + manager + CLI render + historical harness, Python 3.11.9): **385 passed**. Render-focused regression (`-k render`): **566 passed**. Full `tests/unit` regression: **2219 passed, 24 failed, 9 skipped**. Independently re-verified against the unmodified baseline (`git stash` to `3c345ee`, same Python 3.11.9): **2065 passed, 25 failed, 9 skipped**. Exact failure-set comparison (by test name): **24 shared** (pre-existing Windows-temp-path/YAML-escaping fixture failures, out of scope), **1 baseline-only** (the pre-Rev2 hash-pin test name, unchanged since Rev2), **0 Rev4-only**. `git diff --check` exits `0`.
- Resolve contacts during this correction: **zero**. `StartRendering()`/`AddRenderJob()`/`DeleteRenderJob()`/`StopRendering()` calls: **zero**. Production queue attempts: **zero**. Nothing staged, committed, or pushed.
- **`start_render()` still has not been verified against a live Resolve instance.** This entry does not authorize live execution of `render start`, `StartRendering()`, or any RLC-E9901 production operation.

## Unreleased - Production Render Start Path Rev3 Correction (construction-only; not live-verified)

Independent exact-source review of the Rev2 bundle below accepted Rev2's architecture but returned it not yet approved for publication or live execution: 7 further findings, 4 blocking. This entry documents the Rev3 correction. Fully offline: `Resolve contacts: 0`, `StartRendering calls: 0`, `AddRenderJob/DeleteRenderJob/StopRendering calls: 0`, `production queue attempts: 0`, nothing staged/committed/pushed. See `docs/RENDER_START_PATH_CONSTRUCTION.md` §7 for the full finding-by-finding record and `docs/ARCHITECTURE.md` §3.8 for the corrected design.

- **Findings 1/2 — strict render-queue Job-ID and timeline alias resolution.** New start-pathway-owned `ResolveScriptAdapter._strict_alias_value()`, deliberately separate from the legacy, precedence-based `_render_job_id_from_job()` that `queue_render_job()`'s reconciliation and `cancel_render()` continue to use unchanged. Inspects every present recognized alias for a field rather than the first in precedence order: agreeing values are accepted, a `bool`/`int`/`dict`/any other non-string or blank value is malformed and fails closed, and conflicting valid values fail closed. A malformed queue entry anywhere in the list — not only one that superficially overlaps the requested job ID — fails the whole lookup closed. Applied to both job-ID matching and the matched entry's timeline identity.
- **Finding 3 — bind the actual queued output destination.** `ResolveAdapter.start_render()` gained a fourth required keyword-only argument, `output_path: str`. New `ResolveScriptAdapter._require_exact_queued_output_destination()` strictly resolves the matched queue entry's `TargetDir`/`OutputFilename` (same alias rules as Findings 1/2) against the directory/stem derived from `output_path`; never calls `SetRenderSettings()` or `LoadRenderPreset()` to reconcile a mismatch. `RenderManager.start_render()` threads the job's persisted `output_path` through. `MockResolveAdapter.start_render()` gained the same parameter and enforces the same logical binding against its own `TargetDir`/`CustomName` queue metadata.
- **Finding 4 — stop inferring safety from an exact `False` `StartRendering()` return.** The documented contract is only `StartRendering(...) --> Bool`, with no stronger guarantee that `False` proves no side effect occurred. `_invoke_start_rendering_and_reconcile()` now resolves `True`/`False`/an exception/any non-boolean return identically, via the same bounded getter-only reconciliation poll used since Rev2 for the other three outcomes — confirmed `Rendering` is success regardless of the raw signal; not confirmed always raises `RenderStartReconciliationRequiredError`, including for an exact `False`. `StartRendering()` is still never called a second time under any outcome.
- **Finding 5 — corrected Resolve-contact-boundary wording.** Manager-level preconditions no longer claim to run "before any Resolve contact" — `redline_core.runtime.composition.build_application_services()` connects the Resolve adapter unconditionally before any CLI command dispatches, so contact may already have occurred. Wording corrected throughout `render/manager.py`, `render/exceptions.py`, `docs/ARCHITECTURE.md` §3.8, and `docs/RENDER_START_PATH_CONSTRUCTION.md` to say "before the start-specific `ResolveAdapter.start_render()` call" instead. Four test names in `tests/unit/test_render_manager.py` renamed from `..._before_resolve_contact` to `..._before_adapter_start_call`.
- **Finding 6 — persisted identity hardening.** New `RenderManager._require_usable_persisted_string()`: a non-`str` persisted `resolve_job_id`/`project_name`/`timeline_name`/`output_path` is rejected outright (never coerced), and a blank or leading/trailing-whitespaced value is rejected rather than silently `.strip()`-ed and accepted.
- **Finding 7 — wording corrections.** The start-time output collision message changed from "Resolve queue submission was not attempted" (correct for the pre-existing queue-time check it mirrors, wrong for a start operation) to "Render start mutation was not attempted." The Rev3 review-bundle manifest accurately describes its own checksum model (Rev2's manifest incorrectly claimed `MANIFEST.md` was omitted from `SHA256SUMS.txt`; the actual Rev2 bundle included `MANIFEST.md`'s hash and omitted `SHA256SUMS.txt`'s own hash instead).
- New/changed test files: `tests/unit/test_resolve_script_adapter_render_start.py` (rewritten, 85 tests — adds strict-alias adversarial coverage for Findings 1–3 and the unified-`False`-reconciliation regressions for Finding 4), `tests/unit/test_resolve_adapter_start_render_static_safety.py` (rewritten, 14 tests — extends the start-pathway scope to the two new helpers), `tests/unit/test_render_manager.py` (13 new tests — persisted-identity hardening, output-destination-mismatch propagation, renamed wording tests), `tests/unit/test_cli_render.py` (unchanged; re-verified passing against the new manager/adapter behavior).
- Focused (adapter start + static safety + manager + CLI render + historical harness, Python 3.11.9): **383 passed**. Render-focused regression (`-k render`): **564 passed**. Full `tests/unit` regression: **2217 passed, 24 failed, 9 skipped**. Independently re-verified against the unmodified baseline (`git stash` to `3c345ee`, same Python 3.11.9): **2065 passed, 25 failed, 9 skipped**. Exact failure-set comparison (by test name): **24 shared** (pre-existing Windows-temp-path/YAML-escaping fixture failures, out of scope), **1 baseline-only** (`test_verify_mutation_bearing_source_identity_passes_against_real_published_source`, the pre-Rev2 test name — still does not exist post-Rev2, so this is expected and unchanged from the Rev2 comparison), **0 Rev3-only**. `git diff --check` exits `0`.
- Documentation corrected: `docs/RENDER_START_PATH_CONSTRUCTION.md` (new §7, finding-by-finding), `docs/ARCHITECTURE.md` §3.8 (rewritten for the Rev3 design), `docs/ROADMAP.md` and `README.md` (updated to note the Rev2 review outcome and Rev3 correction).
- Resolve contacts during this correction: **zero**. `StartRendering()`/`AddRenderJob()`/`DeleteRenderJob()`/`StopRendering()` calls: **zero**. Production queue attempts: **zero**. Nothing staged, committed, or pushed.
- **`start_render()` still has not been verified against a live Resolve instance.** This entry does not authorize live execution of `render start`, `StartRendering()`, or any RLC-E9901 production operation.

## Unreleased - Production Render Start Path Rev2 Correction (construction-only; not live-verified)

Independent exact-source review of the Rev1 construction bundle below returned **REVISION REQUIRED**: 10 findings, 8 blocking. This entry documents the Rev2 correction. Fully offline: `Resolve contacts: 0`, `StartRendering calls: 0`, `AddRenderJob/DeleteRenderJob/StopRendering calls: 0`, `production queue attempts: 0`, nothing staged/committed/pushed. See `docs/RENDER_START_PATH_CONSTRUCTION.md` §6 for the full finding-by-finding record and `docs/ARCHITECTURE.md` §3.8 for the corrected design.

- **Findings 1/2 — project and timeline identity binding.** `ResolveAdapter.start_render()` changed from `start_render(resolve_job_id: str) -> None` to `start_render(*, project_name: str, timeline_name: str, resolve_job_id: str) -> None`. `RenderManager.start_render()` now sources `project_name`/`timeline_name` from the persisted `RenderJob` and rejects a missing/blank value before any Resolve contact. `ResolveScriptAdapter.start_render()` independently verifies, getter-only and before any mutation call: `GetCurrentProject().GetName() == project_name` exactly (never `LoadProject()`), and exactly one `GetRenderJobList()` entry resolves to `resolve_job_id` with that entry's own `TimelineName == timeline_name` (never `SetCurrentTimeline()`). `MockResolveAdapter.start_render()` was updated to the same signature and enforces the same project/timeline match against its own stored queue metadata, so unit tests can prove mismatch rejection, not just the success path.
- **Finding 3 — exact-False `IsRenderingInProgress()` guard.** Changed from "reject only if exactly `True`" (silently permitting `None`/`0`/`1`/a string/a container/any other value through) to "proceed only if exactly `False`"; every other observed value now fails closed before any mutation call.
- **Findings 4/5/6 — mutation-attempt boundary and outcome matrix.** `start_render()` now runs every pre-mutation guard before delegating to a new `_invoke_start_rendering_and_reconcile()`, the only place `StartRendering()` is called. New `RenderStartReconciliationRequiredError` (`redline_core.resolve.exceptions`): raised whenever `StartRendering()` has actually been invoked and its outcome cannot be positively confirmed via a getter-only reconciliation poll — covers an exception from `StartRendering()` itself, a return value that is neither `True` nor `False` (Bool-contract violation), and a `True` return whose postcondition poll times out. An exact `False` return remains an immediate, non-reconciliation `RenderJobError` (Resolve's own unambiguous rejection signal). In every ambiguous case, if the getter-only poll independently confirms `JobStatus == "Rendering"`, `start_render()` succeeds regardless of the unusual signal that produced the ambiguity. `StartRendering()` is never called a second time under any outcome — proved structurally by the extended static-safety AST suite, which now also proves `LoadProject`/`SetCurrentTimeline` are absent from the whole start pathway (5 functions: `start_render`, `_require_exact_current_project`, `_require_exact_queued_job_identity`, `_invoke_start_rendering_and_reconcile`, `_poll_for_rendering`), not just the original 2.
- **Finding 7 — DB persistence failure after confirmed live start.** New `Database.transition_render_job_to_rendering(job_id) -> bool`: a guarded `UPDATE render_jobs SET status = 'rendering' ... WHERE id = ? AND status = 'queued'`, returning whether exactly one row was affected. `RenderManager.start_render()` only calls this after the adapter call has returned normally (Resolve independently confirmed `Rendering`). A transition exception, a zero/multiple-row result, or a reload failure afterward each raise the new manager-level `RenderStartPersistenceReconciliationRequiredError` (`redline_core.render.exceptions`) — a split-brain condition distinct from Finding 6's adapter-level uncertainty — and `RenderManager` never compensates by calling `StopRendering()`, deleting the Resolve job, or invoking `start_render()` again.
- **Finding 8 — start-time output collision.** `RenderManager.start_render()` now rechecks the persisted `job.output_path` before any Resolve contact: missing/blank raises `RenderJobNotStartableError`; an existing file at that path raises `RenderOutputCollisionError`. Additional to (not a replacement for) the existing queue-time collision check, since the filesystem can change between queueing and starting.
- **Finding 9 — historical queue-attempt hash pins.** `scripts/rlc_e9901_queue_attempt_harness.py`'s `_MUTATION_BEARING_SOURCE_SHA256` pins (a historical evidence binding for the separately reviewed `render queue` pathway) are **unchanged** — proved by a new byte-for-byte snapshot-equality test. This correction legitimately modifies four of those eight pinned files (`render_commands.py`, `render/manager.py`, `resolve/adapter.py`, `db/database.py`); the old test that asserted current on-disk bytes still matched the historical pins was replaced with `test_verify_mutation_bearing_source_identity_fails_closed_against_current_master`, which asserts the harness is now intentionally, provably unable to authorize a live queue attempt against current bytes (exact error code and exact first-mismatched file), plus a parametrized test proving the four *untouched* pinned files still match exactly. **Correction to the Rev1 entry below:** re-running the full suite against the unmodified `3c345ee` checkpoint via `git stash` for this Rev2 pass shows the hash-pin test was already failing at that baseline — `src/redline_core/db/database.py` already did not match its pin before Rev1's construction began — so Rev1's claim that this failure was a "construction-only" consequence specifically of its own changes was not accurate; it was already broken upstream of Rev1 for an unrelated, pre-existing reason. This does not change Finding 9's required fix (the pins stay unchanged either way), but the historical narrative is corrected here rather than repeated.
- New/changed test files: `tests/unit/test_resolve_script_adapter_render_start.py` (61 tests, rewritten for the new signature and every Rev2 finding), `tests/unit/test_resolve_adapter_start_render_static_safety.py` (12 tests, rewritten for the 5-function start pathway and the `LoadProject`/`SetCurrentTimeline` prohibition), `tests/unit/test_render_manager.py` (11 new `start_render`-related tests added), `tests/unit/test_cli_render.py` (2 new failure-category cases added), `tests/unit/test_rlc_e9901_queue_attempt_harness.py` (Finding 9: 1 test replaced, 2 tests added).
- Focused (adapter start + static safety + manager + CLI render + historical harness, Python 3.11.9): **344 passed**. Render-focused regression (`-k render`): **525 passed**. Full `tests/unit` regression: **2178 passed, 24 failed, 9 skipped**. Independently re-verified against the unmodified baseline (`git stash` to `3c345ee`, same Python 3.11.9): **2065 passed, 25 failed, 9 skipped**. Exact failure-set comparison (by test name, not just counts): **24 tests fail in both baseline and Rev2** (all pre-existing Windows-temp-path/YAML-escaping `test_cli_*_end_to_end` fixture failures, unrelated to rendering — out of scope for this correction); **1 baseline-only failure**, `test_verify_mutation_bearing_source_identity_passes_against_real_published_source` (this exact test no longer exists in Rev2 — replaced per Finding 9 above, not merely fixed to pass); **0 Rev2-only failures**. `git diff --check` exits `0` (only benign LF/CRLF-on-checkout warnings, no whitespace errors).
- Documentation corrected: `docs/RENDER_START_PATH_CONSTRUCTION.md` (new §6, finding-by-finding), `docs/ARCHITECTURE.md` §3.8 (rewritten for the Rev2 design; the rejected "current-project-only is acceptable because status/cancel already do it" and unqualified "a fresh `start_render()` call is safe" claims are struck through and corrected in place, not silently removed), `docs/ROADMAP.md` and `README.md` (updated to note the Rev1 review outcome and Rev2 correction).
- Resolve contacts during this correction: **zero**. `StartRendering()`/`AddRenderJob()`/`DeleteRenderJob()`/`StopRendering()` calls: **zero**. Production queue attempts: **zero**. Nothing staged, committed, or pushed.
- **`start_render()` still has not been verified against a live Resolve instance.** This entry does not authorize live execution of `render start`, `StartRendering()`, or any RLC-E9901 production operation.

## Unreleased - Production Render Start Path (construction; not live-verified)

- Adds the missing reusable production pathway to start an already-queued render: `ResolveAdapter.start_render(resolve_job_id) -> None` (interface + `MockResolveAdapter` + `ResolveScriptAdapter`), `RenderManager.start_render(job_id) -> RenderJob`, and CLI `redline render start <job_id>`, completing the render lifecycle (`queue`/`status`/`list`/`cancel`/`start`) through the existing CLI → RenderManager → ResolveAdapter → Resolve layering rather than an ad-hoc `DaVinciResolveScript` script. See `docs/ARCHITECTURE.md` §3.8 and the new `docs/RENDER_START_PATH_CONSTRUCTION.md` for the full architecture investigation, design rationale, and live-authorization-harness analysis.
- `ResolveScriptAdapter.start_render()` uses the exact job-ID-targeted `StartRendering([resolve_job_id], isInteractiveMode=False)` form, verified from the local Resolve Scripting README (`StartRendering([jobIds...], isInteractiveMode=False) --> Bool`), never the zero-argument "start every queued job" form. Precondition (all before any mutation call): connected, valid job ID, job exists, job's own status is exactly `Ready` (rejecting already-`Rendering`, every terminal status, and any unrecognized status with a distinct message each — mirroring `cancel_render()`'s exact status-branch structure), and `IsRenderingInProgress()` is not `True` (refusing to start while any render — including an unrelated one — is already active). `StartRendering()` is reachable from exactly one call site in the whole adapter module, called at most once per invocation, never inside a loop — proved structurally by a dedicated static AST test file, not merely by convention. A `False` return is an immediate, unambiguous rejection; a truthy return is independently confirmed via a bounded (5 attempts, 0.1s apart — the same budget `cancel_render()`'s own postcondition wait already established) getter-only poll of `GetRenderJobStatus()` for `JobStatus == "Rendering"`, never retrying `StartRendering()` itself.
- `RenderManager.start_render()` rejects a missing DB job (`RenderJobNotFoundError`), a job with no persisted `resolve_job_id` (new `RenderJobMissingResolveIdError`), and any job not currently `QUEUED` (new `RenderJobNotStartableError`) — each before any Resolve contact. On adapter success it writes `RenderJobStatus.RENDERING` to SQLite immediately, mirroring `cancel_render()`'s existing eager-write pattern for `CANCELLED` rather than `get_render_status()`'s poll-and-reconcile pattern — justified because the adapter's own postcondition wait has already independently confirmed the transition via a getter before returning. On adapter failure, no DB write happens; the row stays `QUEUED`.
- CLI `render start <job_id>` remains thin (argument parsing → `RenderManager` → output formatting only) and reports Redline job ID, Resolve job ID, status, and output path. Its "Render start confirmed" header and printed `Status: rendering` reflect an already-established fact (the adapter's own postcondition), not a pending request.
- Neither `RLC-E9901` nor its specific Resolve job ID (`3c0af847-bddd-43ee-8b79-a7b64cb915b4`) appear anywhere in the new production code (verified by grep across every changed file) — those identifiers are reserved for a possible future, separately authorized one-shot harness, deliberately not built as part of this construction (see `docs/RENDER_START_PATH_CONSTRUCTION.md` §4 for the full justification: no live evidence of `StartRendering()`'s real-world failure modes exists yet to design a harness's evidence model around, unlike the queue-attempt harness's Mission-39D-derived precedent).
- New tests: 26 in `tests/unit/test_resolve_script_adapter_render_start.py` (adapter-level: invalid/missing job ID, not connected, project manager/project unavailable, job absent, malformed status, successful start, already-rendering, all four terminal statuses, unsupported status, conflicting active render, `False` return, raised exception, exact job ID and `isInteractiveMode=False` passed, exactly-one-call, no `AddRenderJob`/`DeleteRenderJob`/etc., postcondition tolerates one lagging poll, postcondition-never-confirmed fails closed without retry, postcondition `None` response, job-ID-list-not-everything targeting); 7 new in `tests/unit/test_render_manager.py` (unknown job, missing `resolve_job_id` via `claim_render_output()` without finalizing, successful start, all five non-`QUEUED` statuses rejected, adapter failure propagates without a DB write, no second adapter call after a rejected re-start); 7 new/updated in `tests/unit/test_cli_render.py` (parser registration, manager invocation, no accidental queue/cancel call, output identity/status, missing-job/Resolve-failure exit-code mapping, failure-output stream, full dispatch); 8 in the new `tests/unit/test_resolve_adapter_start_render_static_safety.py` (function-scoped AST proof of the one-call/no-loop/no-prohibited-method guarantees, described above).
- Focused: **41 passed** (26 adapter + 7 manager tests specific to `start_render`, plus the 8 static-safety tests). Combined render-focused regression (`-k render`, Python 3.11.9): **468 passed**. Full `tests/unit` regression (Python 3.11.9): **2119 passed, 25 failed, 9 skipped** — independently re-verified against the unmodified baseline (`git stash`): the baseline itself already has **25 failed, 2065 passed** (24 pre-existing Windows-temp-path/YAML-escaping `test_cli_*_end_to_end` fixture failures, unrelated to rendering, plus one intermittent `pip`-wheel-build smoke test), so this construction's *only* net-new item in the failure set is `test_rlc_e9901_queue_attempt_harness.py::test_verify_mutation_bearing_source_identity_passes_against_real_published_source` — an **expected, correct** consequence of legitimately modifying three of that already-published, hash-pinned harness's eight pinned "mutation-bearing" source files (`adapter.py`, `manager.py`, `render_commands.py`); updating that harness's pinned hashes is out of scope for this construction and would require its own separately authorized correction pass. `git diff --check` exited `0` both before and after the stash comparison.
- Resolve contacts during this construction: **zero**. `StartRendering()`/`AddRenderJob()`/`DeleteRenderJob()` calls: **zero**. Production queue attempts: **zero**. Nothing staged, committed, or pushed.
- **`start_render()` has not been verified against a live Resolve instance.** This entry does not authorize live execution of the new `render start` command, `StartRendering()`, or any RLC-E9901 production operation.

## Unreleased - Phase 14 Render Queue Read-Only Snapshot Probe (Rev3): Correction

- Independent exact-source review confirmed that Rev2 (`scripts/phase14_render_queue_snapshot.py`) correctly resolved all six Rev1 findings — Rev2's architecture and corrections are accepted — but Rev2 itself did not pass review: two further BLOCKING evidence-integrity gaps were independently reproduced and are corrected in this Rev3 revision. **Rev3 has not itself been independently reviewed or approved as of this entry.** New execution revision identifier minted: `phase14.2-render-queue-snapshot-construction-rev3` (both Rev1's `...-rev1` and Rev2's `...-rev2` are now explicitly rejected by the interlock and by `ACCEPTED_COLLECTOR_REVISIONS`). Full finding-by-finding detail in `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §0/§0.1 and §6.6/§6.7.
- **Finding 1 (BLOCKING, cross-validate normalized Job ID against preserved fields):** Rev2's `validate_queue_snapshot_document()` validated an entry's `job_id`/`job_id_status` and its preserved `fields` payload independently, so a forged entry such as `{"job_id": "3c0af847-bddd-43ee-8b79-a7b64cb915b4", "job_id_status": "identified", "fields": {"JobId": "OTHER"}}` — internally contradictory evidence no honest collection could produce — still reached `exact_single_job_match`. The validator now re-derives each entry's canonical job-ID classification from that entry's own `fields` via `_job_id_key_status()` (the identical function live collection uses) and requires it to agree exactly with the stored `job_id`/`job_id_status`, failing closed on disagreement (`snapshot_render_queue_entry_job_id_status_disagrees_with_fields` / `snapshot_render_queue_entry_job_id_disagrees_with_fields`) and on any malformed or conflicting alias discoverable within `fields` itself, exactly as live collection would (`snapshot_render_queue_entry_fields_job_id_malformed` / `snapshot_render_queue_entry_fields_job_id_conflicting`). Agreeing aliases (e.g. `{"JobId": "expected", "job_id": "expected"}`) still validate successfully.
- **Finding 2 (BLOCKING, evidence envelope must match an actual Rev3 snapshot):** the validator tolerated unknown top-level keys and never validated `captured_at` at all; a forged document with `captured_at` missing, `null`, `NaN`, or an arbitrary extra top-level key could all still reach a successful comparison. The validator now requires the document's top-level keys to be *exactly* the ten keys this collector ever produces (`snapshot_top_level_keys_invalid` on any missing or extra key) and validates `captured_at` as a non-empty string matching this collector's exact `utc_now()` shape (`YYYY-MM-DDTHH:MM:SS.ffffffZ`, microsecond-resolution UTC, literal trailing `Z` — rejecting any non-UTC/offset timestamp by shape alone) that also parses as a genuine calendar instant, not merely a shape-matching string (`snapshot_captured_at_invalid` / `snapshot_captured_at_malformed` / `snapshot_captured_at_not_parseable`). The *complete* accepted document, not merely each entry's `fields`, is now required to be strict, finite-only JSON — `require_finite_json_value(snapshot)` is now called once on the whole document as the validator's first structural check, superseding (and removing, as redundant) Rev2's narrower per-entry-`fields` call.
- **Additional hardening (not one of the two findings above):** `compare_expected_job_id()` now requires a non-`None` `expected_job_id` to be a non-empty string; a whitespace-only or non-string value now fails closed (`expected_job_id_invalid`) rather than being silently treated as an ordinary zero-match query. No legitimate CLI invocation is affected — `argparse` only ever supplies `None` or an actual string for `--expected-job-id`.
- The accepted Rev2 corrections are all preserved and re-verified unregressed: exact-single-job closure semantics, full context/rendering/count/index validation, conflicting-Job-ID-alias detection during collection, strict finite-only JSON, post-second-queue-read context/rendering verification, the closed six-method Resolve allowlist (unchanged: `GetProjectManager`/`GetCurrentProject`/`GetName`/`GetCurrentTimeline`/`IsRenderingInProgress`/`GetRenderJobList`, verified by static AST inspection and by dedicated tests), the execution interlock, create-only evidence writing, and offline-only expected-job comparison. Rev8 (`scripts/phase14_resolve_context_snapshot.py`) was not modified and remains byte-identical.
- Test suite extended for Rev3: **166 passed** (up from Rev2's 119), adding dedicated coverage for both findings (all 7 required Finding-1 scenarios: valid, valid agreeing aliases, top-level-ID-contradicts-fields, identified-claim-with-no-usable-id, unidentified-claim-with-hidden-id, conflicting-aliases-in-fields, malformed-alias-in-fields; all 9 required Finding-2 scenarios: valid/missing/None/NaN/empty-string/malformed/non-UTC captured_at, extra top-level key, missing-any-required-top-level-key parametrized across all ten keys) plus the whole-document (not just entry-`fields`) strict-JSON proof and the `expected_job_id` hardening tests. The `entry()` test helper was updated to build self-consistent `fields` by default (matching Rev3's new cross-validation requirement) unless a test explicitly overrides `fields` to construct a deliberate contradiction.
- Ran under the project-documented Python 3.11.9 interpreter (`C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`, discovered read-only, not guessed): focused suite **166 passed**; broader Phase 14/RLC-E9901 regression with **no artificial exclusions** (the previously documented `cli`-package-shadowing issue remains absent under this interpreter, as observed in the Rev2 correction): **742 passed, 0 failed**. `git diff --check` exited `0`. Static AST inspection re-confirms `READ_ONLY_RESOLVE_METHODS` is unchanged: exactly `GetProjectManager`/`GetCurrentProject`/`GetName`/`GetCurrentTimeline`/`IsRenderingInProgress`/`GetRenderJobList`, no new Resolve method name introduced.
- Resolve contacts during this correction: **zero**. `AddRenderJob()`/`DeleteRenderJob()`/`StartRendering()` calls: **zero**. Production queue attempts: **zero**. Live snapshot collection: **never invoked**. Nothing staged, committed, or pushed.
- **This entry does not claim RLC-E9901 independent render-queue closure, and does not claim Rev3 has passed independent review.** The production queue path remains `PRODUCTION_QUEUE_PATH_ACCEPTED` with the exact Resolve job ID (`3c0af847-bddd-43ee-8b79-a7b64cb915b4`) still pending independent Resolve-side confirmation. Phase 14 remains open and BLOCKED on the separate, still-open Broadcast Master queue-acceptance root cause.

## Unreleased - Phase 14 Render Queue Read-Only Snapshot Probe (Rev2): Correction

- Independent exact-source review of the Rev1 construction (`scripts/phase14_render_queue_snapshot.py`) accepted the architecture and getter-only boundary but found six findings — five BLOCKING/HIGH correctness gaps, one documentation-accuracy issue — all corrected in this Rev2 revision. **Rev2 has not itself been independently reviewed or approved as of this entry.** New execution revision identifier minted: `phase14.2-render-queue-snapshot-construction-rev2` (Rev1's `...-rev1` is now explicitly rejected by the interlock). Full finding-by-finding detail in `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §0 and §6.
- **Finding 1 (BLOCKING, exact queue-closure semantics):** Rev1's `exactly_one_matching_job` classification was true even when additional queue entries existed, so `run_compare_command()` exited `0` on a false-pass. `compare_expected_job_id()` now returns exactly one of five mutually exclusive classifications — `exact_single_job_match` (the only success outcome; requires `render_queue_count == 1 and identified_job_id_count == 1 and matching_job_count == 1`), `zero_matching_jobs`, `ambiguous_due_to_unidentified_entries`, `expected_job_present_with_additional_jobs`, `no_expected_job_id_supplied` — and the CLI exits `0` if and only if the classification is `exact_single_job_match`.
- **Finding 2 (BLOCKING, snapshot invariant validation):** `validate_queue_snapshot_document()` checked structural shape only; a forged snapshot with mismatched observed/expected project or timeline, `rendering_in_progress: true`, a wrong declared `render_queue_count`, or an out-of-order entry index could still reach a successful classification. The validator now additionally checks document identity (schema version, mission, collector name, and an explicit `ACCEPTED_COLLECTOR_REVISIONS` policy — currently exactly this Rev2 revision), `observed_context == expected_context` (project and timeline), `rendering_in_progress is False` exactly (not merely falsy), `render_queue_count == len(render_queue)`, and every entry's exact shape/positional index/status/job-ID validity/uniqueness/finite-field content, before any comparison logic runs.
- **Finding 3 (HIGH, conflicting job-ID aliases):** Rev1 reused Rev8's `queue_job_id()`, which silently resolves `{"JobId": "one", "job_id": "two"}` to the first, precedence-ordered alias. `_job_id_key_status()` now collects every recognized alias's normalized value and fails closed (`queue_entry_job_id_conflicting`) the moment more than one distinct value is present; agreeing aliases (`{"JobId": "same", "job_id": "same"}`) still classify `identified`. `queue_job_id` is no longer imported from Rev8 for this purpose; `QUEUE_JOB_ID_KEYS` is still reused.
- **Finding 4 (HIGH, strict JSON / non-finite floats):** Rev8's imported `normalize_json_value`/`write_json_no_overwrite` permit NaN/Infinity/-Infinity through Python's permissive `json` defaults (not valid RFC 8259 JSON). Rev8 is unmodified. A new local, probe-owned strict layer (`require_finite_json_value`, `math.isfinite`-based; `write_strict_json_no_overwrite`, adding an explicit `json.dumps(..., allow_nan=False)` re-validation before delegating to Rev8's unchanged writer) is applied inside `collect_render_queue_snapshot` itself and at both CLI write paths (`snapshot` and `compare`), and defensively inside the validator against a forged input file.
- **Finding 5 (HIGH, final rendering/context bracket):** Rev1 verified project/timeline identity and `IsRenderingInProgress()` only immediately before each of the two `GetRenderJobList()` reads, with no check after the second read. A new `_verify_context_and_rendering_inactive()` helper (identity + rendering check, no queue read) is now called a third time, with no further queue read, strictly after the second `GetRenderJobList()` call returns; its observed values are what the published snapshot reports. No new Resolve method name was introduced — `READ_ONLY_RESOLVE_METHODS` remains exactly the same six methods, reused a third time.
- **Finding 6 (documentation accuracy):** Rev1 described `connect_resolve_read_only` as "pure"/"Resolve-contact-free" alongside genuinely pure helpers. Corrected throughout the module docstring and `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §3.1: importing it performs no Resolve contact, but *calling* it is this probe's own deliberate live Resolve connection boundary. `validate_output_path`/`write_json_no_overwrite`/`load_json`/`script_sha256` are now described as never contacting Resolve, not as "pure" (they inspect/write filesystem state). Rev8 was not modified to make this correction.
- Test suite rewritten and extended for Rev2: **119 passed** (up from Rev1's 53), adding coverage for every finding above, including the exact required scenarios: sole expected job (success), expected + unrelated identified job (nonzero), expected + unidentified entry (nonzero), unrelated-only queue (nonzero), empty queue (nonzero), theoretically ambiguous multiple match (fails closed at validation before reaching classification), the exact adversarial forged-snapshot regression from independent review (mismatched project/timeline, `rendering_in_progress: true`, `render_queue_count: 999`, entry index `37` — fails closed), NaN/Infinity/-Infinity rejection at both collection and both write paths, and the full three-call Finding-5 state-transition matrix (rendering false/false/true after B, project changes after B, timeline changes after B, stable state passes) via a new call-sequence-aware fake Resolve object family.
- Ran under both interpreters. Python 3.13.5 (`C:\Python313\python.exe`, this session's default): focused suite **119 passed**; combined Phase 14/RLC-E9901 regression (excluding the same previously documented `cli`-package-shadowing collection errors): **628 passed, 1 failed** (the same known Python-3.11-vs-3.13 `test_rev7_native_process_helpers_round_trip_on_windows` fixture failure). Python 3.11.9 (`C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`, discovered read-only from this repository's own already-published `EXPECTED_PYTHON_EXECUTABLE`/`EXPECTED_PYTHON_VERSION` constants in `scripts/rlc_e9901_queue_attempt_harness.py`, not guessed): focused suite **119 passed**; combined Phase 14/RLC-E9901 regression **695 passed, 0 failed** — under 3.11, both the `cli`-package-shadowing collection errors and the native-process-helper interpreter-identity failure **disappear entirely**, confirming both were purely artifacts of this workstation's default Python 3.13 environment, not genuine regressions. `git diff --check` exited `0` under both runs.
- Resolve contacts during this correction: **zero**. `AddRenderJob()`/`DeleteRenderJob()`/`StartRendering()` calls: **zero**. Live snapshot collection: **never invoked**. Nothing staged, committed, or pushed.
- **This entry does not claim RLC-E9901 independent render-queue closure, and does not claim Rev2 has passed independent review.** The production queue path remains `PRODUCTION_QUEUE_PATH_ACCEPTED` with the exact Resolve job ID (`3c0af847-bddd-43ee-8b79-a7b64cb915b4`) still pending independent Resolve-side confirmation. Phase 14 remains open and BLOCKED on the separate, still-open Broadcast Master queue-acceptance root cause.

## Unreleased - Phase 14 Render Queue Read-Only Snapshot Probe (Rev1): Construction

- Adds a new, generically parameterized (not RLC-E9901-specific) Phase 14 render queue read-only snapshot probe at `scripts/phase14_render_queue_snapshot.py`, with a matching focused mocked unit test suite (`tests/unit/test_phase14_render_queue_snapshot.py`, 53 tests), documented in full in the new `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md`. This is the deliberate complement to the published Rev8 collector (`scripts/phase14_resolve_context_snapshot.py`), which refuses to complete a snapshot against a non-empty render queue by design (`render_queue_not_empty`) — this probe exists specifically to inspect an existing, possibly non-empty queue without mutating Resolve, closing the independent-Resolve-job-ID-observation gap left after the RLC-E9901 queue-attempt harness's `PRODUCTION_QUEUE_PATH_ACCEPTED` classification. Rev8's source bytes and published SHA-256 are unchanged by this construction; genuinely pure, Resolve-contact-free helpers (`SnapshotError`, `normalize_json_value`, `queue_job_id`, `validate_output_path`, `write_json_no_overwrite`, `connect_resolve_read_only`, and others) are reused by ordinary import per Rev8's own module docstring ("may be imported and its pure comparison functions may be exercised freely"); the getter-only Resolve dispatch and execution interlock are deliberately NOT imported from Rev8 (both are closed over Rev8's own broader allowlist / own revision identifier) and are instead small, self-contained, independently reviewable functions closed over this probe's own six-method allowlist (`GetProjectManager`, `GetCurrentProject`, `GetName`, `GetCurrentTimeline`, `IsRenderingInProgress`, `GetRenderJobList`) and its own `EXECUTION_REVISION_ID` (`phase14.2-render-queue-snapshot-construction-rev1`). See `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §3 for the full architecture-option evaluation (A/B/C) and rationale.
- Render queue entries normalize deterministically per entry: job ID extraction reuses Rev8's own reviewed key-variant precedence (`JobId`/`JobID`/`jobId`/`job_id`/`Id`/`ID`/`id`) via `queue_job_id`, classified explicitly as `identified`/`unidentified`/fail-closed-`malformed`; every other field passes through Rev8's `normalize_json_value` (never stringifies or `repr()`'s an arbitrary bridge object); a non-dict entry, a non-string key, or two `identified` entries sharing the same job ID each fail closed. A separate, offline-only `compare` subcommand classifies an expected Resolve job ID against a previously collected snapshot as `exactly_one_matching_job` / `zero_matching_jobs` / `multiple_matching_jobs_ambiguous`, and reports `has_unexpected_additional_jobs` independently — this comparison makes zero Resolve contact.
- Focused test suite: **53 passed**, covering import safety, the execution interlock, output-collision-before-Resolve-contact ordering, project/timeline identity and rendering-active guards, empty/single/multiple/drifting queue states, all seven job-ID key spellings, missing/ambiguous/duplicate job-ID handling, malformed queue type/entry handling, offline acceptance comparison (exact match, zero match, unexpected additional jobs, zero Resolve contact), evidence-output determinism/no-overwrite, and static AST proof that no prohibited Resolve method name (including `AddRenderJob`, `DeleteRenderJob`, `StartRendering`) appears anywhere in this probe's own source, plus that this probe's dispatch does not silently inherit Rev8's broader allowlist. Combined Phase 14 / RLC-E9901 focused regression (excluding this local machine's pre-existing, previously documented `cli`-package-shadowing collection errors): **628 passed, 1 failed** — the 1 failure is the same pre-existing, previously documented `test_rev7_native_process_helpers_round_trip_on_windows` Python-3.11-vs-3.13 interpreter-identity fixture failure, unrelated to this change. `git diff --check` exited `0`.
- Resolve contacts during this construction: **zero**. `AddRenderJob()`/`DeleteRenderJob()`/`StartRendering()` calls: **zero**. Live snapshot collection: **never invoked** — `run_snapshot_command()`/the `snapshot` CLI subcommand was exercised only against injected fake Resolve handles in the mocked test suite.
- **This entry does not claim RLC-E9901 independent render-queue closure.** The production queue path remains `PRODUCTION_QUEUE_PATH_ACCEPTED` with the exact Resolve job ID (`3c0af847-bddd-43ee-8b79-a7b64cb915b4`) still pending independent Resolve-side confirmation; this construction makes that confirmation possible in a future authorized run, it does not perform it. See `docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md` §9.1 for the exact future closure workflow. Phase 14 remains open and BLOCKED on the separate, still-open Broadcast Master queue-acceptance root cause.

## Unreleased - RLC-E9901 Broadcast Master Queue Attempt Harness (Rev7): Independent Source Review Passed

- Adds a new, RLC-E9901-specific one-shot production `render queue` attempt harness at `scripts/rlc_e9901_queue_attempt_harness.py`, with a matching focused test suite (`tests/unit/test_rlc_e9901_queue_attempt_harness.py`), documented in full in the new `docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md`. The harness does not reimplement `RenderManager`/`ResolveAdapter` business logic; the sole mutation-bearing operation remains exactly one real production CLI process launch (`python -m cli.main render queue RLC-E9901 broadcast_master`), reachable only through the harness's own `run-queue-attempt` CLI subcommand.
- Throughout the Rev1→Rev7 construction and review cycle, independent exact-source review found and corrected a series of classification, evidence-binding, and false-pass gaps — see `docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md` §15 for the complete, itemized revision history. **Rev7 has passed independent exact-source review.**
- Focused regression: **175 passed**. Combined queue/render/preflight regression: **596 passed**. Broad `tests/unit`: **1900 passed, 24 failed, 9 skipped** — the same established, pre-existing Windows-path/YAML-escaping fixture failures documented elsewhere in this changelog, unrelated to this harness.
- Resolve contacts throughout the Rev1→Rev7 construction and review cycle: **zero**. Fresh live queue-attempt preflights: **zero**. Queue attempts: **zero**. Render jobs queued: **zero**. Renders started: **zero**.
- **This entry, and passing source review, does not authorize or execute a live Broadcast Master queue attempt.** `run_authorized_queue_attempt()` — the harness's one live-capable orchestration function, reachable only through its `run-queue-attempt` CLI subcommand — was never invoked during construction or any review pass.

## Unreleased - RLC-E9901 Broadcast Master Read-Only Preflight Tooling (Rev5): Independent Source Review Passed

- Adds a new, RLC-E9901-specific, single-context read-only preflight tooling layer at `scripts/rlc_e9901_snapshot_preflight_contract.py`, `scripts/rlc_e9901_module_provenance_check.py`, and `scripts/rlc_e9901_preflight_assertion.py`, with matching focused test suites, documented in full in the new `docs/RLC_E9901_BROADCAST_MASTER_PREFLIGHT_CONTRACT.md`. The published rev8 collector (`scripts/phase14_resolve_context_snapshot.py`, `EXECUTION_REVISION_ID = phase14.1-live-interlock-construction-rev8`) is wrapped, unmodified and byte-identical, rather than edited — its own manifest/runbook layer is hard-bound to a two-context Control/Production comparison shape RLC-E9901's single-context preflight does not fit, and editing it would itself require a new execution revision and fresh review of its live-contact boundary.
- Five independent-review passes (Rev2 through Rev5) found and corrected: a checker-import-ordering defect that let checker code execute before the repository checkpoint could reject a bad state; five distinct offline-checker false-pass gaps (boolean queue counts, contradictory project-level queue evidence, an unobserved product identity, contradictory Resolve version accessors, an optional rather than required video track-count observation); an unbound evidence output path (accepted relative paths, did not protect the repository, the RLC-E9901 workspace, the runtime directory, or the separately-located preserved `RedlineOSLive\Evidence` directory); discarded collector failure evidence on a non-zero exit; a `GetVersion()` five-field `[major, minor, patch, build, suffix]` normalization bug that rejected the repository's own reviewed evidence value; and, most recently, a non-empty `GetVersion()` suffix silently discarded during normalization plus non-lossless/non-JSON-safe handling of `subprocess.TimeoutExpired`'s partial output. See `docs/RLC_E9901_BROADCAST_MASTER_PREFLIGHT_CONTRACT.md` §18 for the full revision history.
- **This tooling does not authorize or execute a live Broadcast Master render queue attempt, and none of the five review-and-correction passes executed one.** `run_authorized_rlc_e9901_preflight()` — the tooling's one live-capable orchestration function, reachable only through its `run-live-preflight` CLI subcommand — was never invoked during construction or any review pass; every verification used only non-Resolve-contacting subcommands (`verify-checkpoint`, `verify-collector`, `verify-checker`, `verify-python`, `preview-snapshot`) or mocked unit tests.
- Distinguishes, and the offline checker enforces, two separate outcomes: `snapshot_capture_status` (was the collector's JSON document itself complete and well-formed) and `render_preflight_status` (do all thirteen render-specific checks — exact project/timeline identity, rendering inactive, render queue empty and mutually consistent, Resolve product/version identity, `Redline Broadcast Master` observed, positive video-item count, no pre/post guard drift — also pass). A snapshot capture alone can never by itself produce an overall preflight PASS.
- **Broadcast Master queue acceptance remains a separate, not-yet-proven objective from this preflight tooling and from RLC-E9901's own closed assembly proof** (see `docs/ROADMAP.md`'s Phase 14 entry immediately below this one for the current standing status of each). This preflight tooling exists to gather the evidence a future live attempt would need; it does not itself resolve, or claim to resolve, the still-open production Broadcast Master queue-acceptance root cause documented across Missions 39D/39D.2/39D.3.

### Verification

- Focused regression (all three RLC-E9901 preflight-tooling test files — `test_rlc_e9901_snapshot_preflight_contract.py`, `test_rlc_e9901_module_provenance_check.py`, `test_rlc_e9901_preflight_assertion.py`): **147 passed**.
- Full `tests/unit` regression: **1725 passed, 24 failed, 9 skipped** — the identical 24 pre-existing, previously documented Windows-temp-path/YAML failures, unrelated to this tooling, no new or different failure.
- `git diff --check` exit code `0`.
- Resolve API contacts across all five construction/review passes: zero. No `DaVinciResolveScript` import, no live snapshot, no render queued, no render started, and no mutation of RLC-E9901's Resolve project/timeline, runtime database, workspace, or preserved evidence occurred at any point.
- This entry records that Rev5 passed independent source review as of the review pass described above. Passing source review was not itself, and is not retroactively, an authorization to stage, commit, or push these files, or to contact Resolve live — each of those actions requires its own separate, explicit founder authorization at the time it is taken, whether or not this specific publication was later separately authorized. See `docs/RLC_E9901_BROADCAST_MASTER_PREFLIGHT_CONTRACT.md` for the complete contract and `docs/ROADMAP.md`'s Phase 14 entry for standing status.

## Unreleased - Assembly Payload Evidence Closure: video_item_count Reaches BuildResult, CLI Output, and Durable Logging

- Closes the evidence gap found during RLC-E9901 one-shot live-build authorization preparation: `EpisodeManager.build_episode()` has computed `EpisodeBuildResult.video_item_count` since the prior "Assembly Video-Payload Observability" entry, but nothing external to that one in-memory object ever exposed it — `BuildOrchestrator.BuildResult` dropped the field entirely, the CLI's `_print_build_result()` never printed it, it was never persisted to SQLite, and (a separately confirmed root cause) the log line that recorded it used `EpisodeManager`'s module-level `logging.getLogger(__name__)` — `"redline_core.episode.manager"` — a logger namespace `configure_logging()` (`src/redline_core/logging/setup.py`) never attaches handlers to; only the `"redline_os"` tree reaches the console/rotating-file handlers. The record was silently dropped, not merely hard to find.
- **Production build success and Phase 14 assembly-proof success remain distinct concepts, unchanged by this entry.** `video_item_count == 0` is still a valid, non-rejecting V1 result — the production build still reaches `ASSEMBLED` and exits `0` regardless of the count. `EpisodeManager` still does not, and must not, treat "no video payload" as a build failure; that policy remains `RenderManager`'s exclusive, preset-scoped `requires_video_payload` preflight, unchanged by this entry. This entry only makes the already-computed value observable — it changes no build/assembly/render decision.
- `BuildResult` (`src/redline_core/build/orchestrator.py`) gains one new required field, `video_item_count: int`, populated directly from `EpisodeBuildResult.video_item_count` in `_build_result()` — passed through verbatim, never recomputed, no new Resolve call introduced. `cli/build_commands.py`'s `_print_build_result()` prints `Video item count: <N>` in the existing `Build complete` summary block, immediately after `Clips placed:`.
- Logger-namespace correction: `EpisodeManager.build_episode()` now resolves its local `logger` via the existing `get_episode_logger(episode.episode_id)` helper (`src/redline_core/logging/setup.py`) — the same helper `create_episode()` already uses, and the same pattern `resolve/adapter.py` already established for its own queue-identity diagnostic logger — instead of the module-level logger. This is a narrow, one-method logger-source change: no logger namespace was renamed, no other module's logging changed, and every existing log message's wording is unchanged; only which logger object emits `build_episode()`'s own messages changed, so they now reach `configure_logging()`'s console and rotating-file handlers under `"redline_os.episode"`.
- Out-of-scope observation, not acted on: `mcp_server/tools/episode_tools.py`'s `_episode_build_result_to_dict()` (used by the MCP `episode assemble` tool, which calls `EpisodeManager.build_episode()` directly, bypassing `BuildOrchestrator`/CLI entirely) also omits `video_item_count` from its returned dict. This is a separate transport with the same underlying gap, but outside the `redline build`/`BuildOrchestrator` pathway this entry was scoped to close.
- Seven new/updated focused tests prove: `EpisodeBuildResult.video_item_count` propagates into `BuildResult` verbatim for both a zero and a positive count, without disturbing any unrelated field (`test_build_orchestrator.py`); the CLI's `Build complete` output includes the exact count for zero, a default, and a positive value, and a zero count does not alter any other success field (`test_cli_build.py`); the `payload_observation` stage's log record now reaches a handler under the `"redline_os"` namespace with the correct `video_item_count=<N>` text, exercised via `MockResolveAdapter` with no Resolve contact (`test_episode_manager.py`). Four existing `BuildResult(...)` fixture-construction sites (`test_build_orchestrator.py`, `test_build_render_workflow.py`, `test_cli_build.py`, `test_cli_render.py`) gained the one new required keyword argument — mechanical, no assertion on unrelated behavior changed.
- No Resolve mutation surface changed, no render-queue behavior changed, no `EpisodeStatus` transition semantics changed, no retry/idempotency behavior changed, no database schema changed, and no manifest schema changed.

### Verification

- Focused regression: `pytest tests/unit/test_episode_manager.py tests/unit/test_build_orchestrator.py tests/unit/test_cli_build.py tests/unit/test_cli_render.py tests/unit/test_build_render_workflow.py tests/unit/test_mcp_tools.py -q` — **195 passed**.
- Full `tests/unit` regression: **1578 passed, 24 failed, 9 skipped** — exactly `+5` passed over the prior established baseline of 1573 (matching the 5 net-new tests: 2 in `test_build_orchestrator.py`, 2 in `test_cli_build.py`, 1 in `test_episode_manager.py`), with the identical 24 failing node IDs previously traced to a pre-existing, unrelated Windows-temp-path/YAML double-quoted-scalar issue in `test_cli_*` end-to-end fixtures (`redline_core/config/loader.py` failing before any Resolve contact). No new or different failure appeared.
- `git diff --check` exit code `0`.
- Resolve API contacts during this correction: zero. No `DaVinciResolveScript` import, no live build, no SQLite access to live Phase 14 state, and no mutation of the RLC-E9901 workspace or its evidence artifacts occurred during this entry's implementation or verification.
- This entry does not authorize live Resolve contact, the RLC-E9901 live build, staging, commit, or push. See `docs/ROADMAP.md`'s Phase 14 entry for standing status.

## Unreleased - Assembly Video-Payload Observability: Post-Placement Inspection in Episode Manager

- Adds a read-only, post-placement video-payload observation to `EpisodeManager.build_episode()`, closing the observability gap identified by the Phase 14 root-cause investigation (repository-only; see the renderability preflight entry below): every existing assembly gate (manifest schema, import-count validation, TimelineItem-ID-count validation) is a counting/string-shape gate and none of them ever inspects resulting track content, so `RenderManager`'s renderability preflight was the first and only place in the pipeline with explicit knowledge of actual video TimelineItem count — and it runs only much later, at render-queue time, after `ASSEMBLED` has already been persisted.
- The new step runs immediately after TimelineItem-ID validation succeeds and before `EpisodeBuildResult` is constructed or `ASSEMBLED` is persisted. It reuses — does not duplicate — the exact same `ResolveAdapter.get_video_timeline_item_count(project_name, timeline_name)` `RenderManager` already calls. `EpisodeBuildResult` (`src/redline_core/episode/models.py`) gains one new required field, `video_item_count: int`, documented as the actual observed post-placement count, not a count of requested/imported/placed media.
- This is observational only, by deliberate design: a count of `0` is a valid, non-rejecting V1 result. Episode Manifest V1 has no media-role or track-placement contract (`docs/EPISODE_MANIFEST_ARCHITECTURE.md` §Non-Goals), so `EpisodeManager` does not invent a hidden "every assembled episode must contain video" requirement — that remains `RenderManager`'s exclusive, preset-scoped `requires_video_payload` policy, entirely unchanged by this addition. `ASSEMBLED` now precisely means "requested media passed the existing import/placement contracts and resulting video payload was observed" — not "renderable by every preset."
- Inspection failure (Resolve cannot reliably report the count) is treated categorically differently from an observed zero: it fails closed as a new `EpisodeBuildError` stage, `payload_observation` (`src/redline_core/episode/manager.py`), following the exact existing stage-failure pattern — `_build_error()` releases the assembly claim as `failed`, so `ASSEMBLED` is never persisted on this path, exactly as for existing media-import, timeline-build, and clip-placement failures.
- `tests/unit/test_episode_manager.py`'s `FakeTimelineBuilder` test double now optionally registers the built timeline and an observed `video_item_count` (default `1`, preserving all existing tests' prior behavior) into the shared `MockResolveAdapter`, via a `.resolve` attribute `make_manager()` back-fills after construction — no existing test's call signature or assertions on unrelated behavior changed. Five new tests prove: the observation runs after `place_clips()`; a `video_item_count=1` observation is recorded verbatim in `EpisodeBuildResult`; a `video_item_count=0` observation is recorded verbatim **and assembly still reaches `ASSEMBLED`** (the critical V1-contract test); inspection failure raises `EpisodeBuildError(stage="payload_observation")` with the correct `completed_stages`/`placed_count` context and preserved `__cause__`; and that failure does not persist `ASSEMBLED` (episode status is `FAILED`). Two pre-existing tests were updated to reflect the new stage, not weakened: `test_build_episode_happy_path_delegates_in_order_and_preserves_result_order` now expects `video_item_count=1` on its `EpisodeBuildResult` equality assertion, and `test_build_episode_assembled_status_update_failure_is_stage_aware` now expects `payload_observation` in its `completed_stages` tuple, since that stage now legitimately completes before the status-update failure that test exercises. `tests/unit/test_mcp_tools.py` and `tests/unit/test_build_orchestrator.py` gained one keyword argument each at their existing `EpisodeBuildResult(...)` fixture-construction sites (mechanical, required for the dataclass to compile) — no assertion in either file changed.
- Evidence correction: an earlier repository-only investigation could not determine from committed repository evidence alone whether the production-like `RLC-E9001`/`RLC-E9001_MASTER` episode was ever built through `EpisodeManager.build_episode()`. Separate historical live evidence (the disposable Mission 39D SQLite registration for `RLC-E9001`/`RLC-E9001_MASTER`) shows that episode's recorded status was `created`, not `assembled` — so `RLC-E9001`'s historical zero-video state is not evidence that this assembly pipeline itself lost video, and must not be documented as such. It remains evidence only that the general observability gap this change closes was real and previously unguarded.
- No manifest schema change, no manifest schema version change, no `RenderPreset` schema change, no `RenderManager` renderability-policy change, no CLI behavior change, no MCP behavior change, no Resolve queue-reconciliation change, and no Resolve placement-semantics change are part of this entry.

### Verification

- Focused `EpisodeManager` regression: `pytest tests/unit/test_episode_manager.py -q` — **57 passed**.
- Broader related regression: `pytest tests/unit/test_episode_manager.py tests/unit/test_build_orchestrator.py tests/unit/test_mcp_tools.py tests/unit/test_render_manager.py tests/unit/test_render_manager_renderability_preflight.py tests/unit/test_resolve_script_adapter_video_item_count.py tests/unit/test_resolve_mock.py tests/unit/test_config.py tests/unit/test_composition.py -q` — **226 passed**, confirming the renderability preflight, resolve mock/adapter, config, and composition suites are unchanged by this addition.
- Full `tests/unit` regression on the current, unstashed working tree: **1296 passed, 5 failed, 9 skipped, 15 collection errors** — exactly `+5` passed over the prior established baseline of 1291 (matching the 5 new tests added, 0 removed), with the identical 5 failing node IDs and identical 15 collection-error modules as previously traced (installed-wheel `setuptools.build_meta` unavailability, one Python-3.11-vs-3.13 native-process `identity mismatch`, and `cli`-package shadowing from an unrelated globally-installed package) — reproduced without any stash-based comparison, per the standing prohibition on using `git stash`/`git stash pop` to establish a baseline.
- `git diff --check` exit code `0`.

## Unreleased - Renderability Preflight: Video-Payload Precondition Before Resolve Queue Mutation

- Adds a reusable, transport-independent renderability preflight to `RenderManager.queue_render()`, called after collision rejection and before the SQLite output claim, so a non-renderable timeline is rejected before any SQLite mutation or Resolve queue mutation (`LoadRenderPreset`, `SetRenderSettings`, `AddRenderJob`) is attempted. This turns the completed Phase 14 Test D finding (below) into a standing safety capability rather than a one-off diagnostic.
- `RenderPreset` (`src/redline_core/config/schema.py`) gains an explicit, preset-scoped `requires_video_payload: bool` field, default `False`. `config/render_presets.yaml` sets `requires_video_payload: true` for `broadcast_master` only, citing the Test D evidence; `youtube_1080p` and any future preset remain ungoverned by this rule unless separately approved. This keeps "video is required" a preset-level capability declaration, not a universal Resolve rule.
- `ResolveAdapter` (`src/redline_core/resolve/adapter.py`) gains one new interface method, `get_video_timeline_item_count(project_name, timeline_name) -> int`. `ResolveScriptAdapter` implements it with the same `Timeline.GetTrackCount("video")` / `Timeline.GetItemListInTrack("video", index)` calls verified during Test D evidence capture, and fails closed (`TimelineOperationError`) on a missing capability, an invalid track count, an unexpected exception, or a non-list item-list response, rather than assuming renderability when inspection data is unavailable. `MockResolveAdapter` implements the same method deterministically from an in-memory count (default `0`), plus a test-only `set_video_timeline_item_count()` helper so unit tests can construct both renderable and non-renderable mock timelines without a live Resolve instance.
- A new `RenderTimelineNotRenderableError(RenderError)` (`src/redline_core/render/exceptions.py`) is raised by `RenderManager._enforce_renderability()` when a preset requires video and zero video TimelineItems are found. The message names the target timeline, target project, preset, and the failed requirement, and states explicitly that Resolve queue submission was not attempted — kept a distinct type from the existing Mission 39D/39D.2 post-`AddRenderJob()` reconciliation exceptions (`RenderQueueIdentityUnresolvedError`, `RenderQueueAcceptanceNotObservedError`), since this failure occurs before any Resolve mutation is attempted, not after an ambiguous one. `src/cli/render_commands.py` and `src/mcp_server/tools/render_tools.py` map it to a `"render timeline not renderable"` category alongside the other pre-acceptance render failures.
- Nine focused tests in `tests/unit/test_render_manager_renderability_preflight.py` and eleven in `tests/unit/test_resolve_script_adapter_video_item_count.py` prove: `broadcast_master` with zero video TimelineItems fails preflight with a message naming project/timeline/preset; the failure occurs before the SQLite output claim (a fresh claim for the same output succeeds immediately after); `ResolveAdapter.queue_render_job()` is never called on that path, so `LoadRenderPreset`/`SetRenderSettings`/`AddRenderJob` are unreachable; a timeline with at least one video item passes preflight and queues exactly as before; a preset without `requires_video_payload` is not subjected to the Broadcast Master rule even with zero video items; unavailable/invalid Resolve inspection data (`TimelineOperationError`) propagates and fails closed rather than being treated as renderable; and the mock adapter's video-item count is deterministic and test-controllable. `tests/unit/test_render_manager.py`'s shared fixture and every hand-built `MockResolveAdapter` subclass instance across its reconciliation/collision/persistence tests now place one mock video item, so those pre-existing tests continue to exercise the same queue path as before under the new precondition — their behavior is otherwise unchanged.
- `tests/unit/test_config.py` gains two assertions proving the real `config/render_presets.yaml` loads `broadcast_master.requires_video_payload is True` and `youtube_1080p.requires_video_payload is False`.
- Native verification: focused slice (`test_render_manager.py`, the two new preflight test files, `test_config.py`) **62 passed**. Full `tests/unit` regression on the current, unstashed working tree: **1291 passed, 5 failed, 9 skipped, 15 collection errors**. Direct traceback analysis of every failure/error (not a stash-based before/after diff) attributes all 20 to this local machine's environment, not to this change: 4 of the 5 failures (`test_installed_cli_asset_list_smoke.py`, `test_installed_db_bootstrap_smoke.py`, `test_installed_mcp_startup_smoke.py`, `test_installed_wheel_smoke.py`) raise `BackendUnavailable: Cannot import 'setuptools.build_meta'` while building a wheel, because this local Python 3.13 environment's `setuptools` install is missing/broken that backend; the 5th (`test_phase14_resolve_context_snapshot.py::test_rev7_native_process_helpers_round_trip_on_windows`) raises `identity mismatch` because that test requires the interpreter under test to report Python 3.11.x and this run's interpreter is 3.13; and all 15 collection errors are every `test_cli_*`/`test_installed_*` module that does `from cli import ...`, which resolves (confirmed via `cli.__file__`/`cli.__path__`) to an unrelated globally-installed `cli` PyPI package in this machine's Roaming site-packages, shadowing the local editable `src/cli` earlier on `sys.path`. None of these 20 tracebacks reference any changed implementation file. No independently recorded exact prior local 1291/5/9/15 baseline exists to prove bit-for-bit historical equivalence — CI (`.github/workflows/ci.yml`) runs Python 3.11 with a clean `pip install -e ".[dev]"` and would not exhibit any of these three conditions. The precise claim is therefore that these 20 items are independently evidenced as environment-specific to this local workstation and unrelated to this diff, not that an exact historical baseline was proven identical. `git diff --check` exit code `0`.
- This entry does not authorize live Resolve contact, another Test D-style attempt, or any change to Phase 14's status. Phase 14 remains open and BLOCKED per the entry below; this preflight prevents Redline OS from re-attempting a known-non-renderable Broadcast Master queue request, it does not resolve the still-open production queue-acceptance root cause. No staging, commit, or push is authorized by this entry.

## Unreleased - Phase 14 Test D: Live Execution Result (Rejected, No Queue Mutation Observed)

- Records the completed, single authorized live Test D execution and its independently reviewed evidence chain, bound to repository commit `aedae2ece9009153573b1ac5d0e0657a90513209`, harness SHA-256 `eeae8f315737fbdd14d0be715fa004642879c787d53dc03040b52770f72ff847`, and execution contract SHA-256 `e4b9cfdc1121f322a42633c6da4e15c54de4bb8f55a28812b9f516d421814b1d`, run under Python 3.11.9. Repository-before evidence confirmed branch `master`, HEAD `aedae2ece9009153573b1ac5d0e0657a90513209`, a clean working tree, and origin `git@github.com:Choice283/redline-os.git`.
- The operator manually removed exactly one TimelineItem, `Redline OS Assembly Test Image.png`, from the disposable Control timeline `RLO-LIVE-ASM-92701_TIMELINE` in project `redline-os-test-duplicate`, leaving the PNG in the Media Pool and the audio TimelineItem (`Redline OS Assembly Test Audio.wav`, Media Pool unique ID `b88773bf-c80f-4f23-b346-077f09419e23`, start 86400, end 86424, duration 24, enabled) untouched. No retry was authorized; the harness performed exactly one `AddRenderJob()` call.
- Immediately before the call, the harness verified DaVinci Resolve Studio 21.0.3.7 with track state `audio: 1 track / 1 item`, `video: 1 track / 0 items`, `subtitle: 1 track / 0 items`; markers unchanged at frame 0 (Blue, "Assembly Start", "Live V1 marker A") and frame 48 (Yellow, "Assembly Beat", "Live V1 marker B"); project/timeline settings SHA-256 `71430f17446c1b4d2019f4ff4d73b6a9ab4154124255c31eecfd7cd3f21d355c` unchanged; the full Media Pool inventory unchanged, including the retained PNG (unique ID `fdded4d6-0e2d-43f0-9007-2cae51bca76a`); timeline start `86400` and end `86424` stable across all four snapshots (initial, pre-render-context, final pre-add guard, post-`AddRenderJob()`); and active render context `format=mov`, `codec=DNxHRHQX_10` under the `Redline Broadcast Master` preset targeting `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests\phase14-test-d-no-video` with no output collision.
- `AddRenderJob()` returned an empty string (`type: str`, `value: ""`). The render queue held `0` jobs before and after the call. The harness classified the result `rejected`; process exit code `16`; `post_errors: []`; `evidence_errors: []`; `rendering` remained `false`.
- Evidence chain, independently reviewed: `pre_add_evidence.json` (SHA-256 `7f184665cd71b30a8966ea24ce22f2b86848db267fb7525d53b5ad8d6fa68b8c`), `add_render_job_result.json` (SHA-256 `a265b86991dade052f3dff442169043988ccb1cce456c725b1a1262a3d6d48df`), `post_add_evidence.json` (SHA-256 `136fd81a4bd68217091b99bf661d0c8332aac1f4b5a6e88de00c0327fc0c56b1`), `test_d_result.json` (SHA-256 `b38d6b6ff7c995be737f2035d5754567da7a139efb302848440031b4f7050a01`).
- Approved engineering conclusion: in the tested DaVinci Resolve Studio 21.0.3.7 / Redline Broadcast Master configuration, the previously queue-accepting Control timeline stopped being queueable when its only video TimelineItem was removed while audio, markers, Media Pool inventory, project/timeline settings, preset, and active `mov`/`DNxHRHQX_10` render context remained otherwise consistent. This strongly supports treating the presence of a renderable video timeline payload as a required precondition for the tested `broadcast_master` render path. This is not generalized into a universal rule for every Resolve preset or every audio-only Resolve workflow.
- This entry records the finding only. It does not by itself change Phase 14's BLOCKED status, authorize Control timeline restoration or cleanup, authorize another live queue attempt, or authorize commit/push. See the renderability preflight entry above for how this finding was turned into a repository safety capability, and Phase 14 in `docs/ROADMAP.md` for status.

## Unreleased - Phase 14 Test D r2 Native Verification, Repository Review, and Exact-Byte Hardening

- Records the Rev8 Control-vs-Production comparison result that motivated Test D: exposed project and target-timeline settings matched while the disposable Control timeline contained one enabled video item and the production-like target contained zero video items. Missing video payload remains a leading hypothesis only, not a causal conclusion.
- Construction r1 established the original-disposable-Control experiment topology but repository review found two Important live-readiness blockers: pre-add state was not durably checkpointed before the one-shot `AddRenderJob()` call, and active Broadcast Master render format/codec were recorded but not enforced as an isolation gate.
- Construction r2 corrects both findings without redesigning the experiment. `pre_add_evidence.json` must be durably persisted before the sole `AddRenderJob()` call; direct-return and post-add observations are independently checkpointed; evidence-write failure stops before queue mutation. `GetCurrentRenderFormatAndCodec()` is now mandatory and must report exactly `mov` / `DNxHRHQX_10` before the queue call, otherwise execution fails closed.
- Exact-byte r2 local integration retained the reviewed construction hashes. Native Windows Python 3.11.9 verification passed: compilation PASS, focused Test D suite **35 passed**, and combined Phase 14 snapshot/Test D regression slice **136 passed**. HEAD remained `33b324220b3fbfe66def17b0e6587d55042e4c92` and the Git index remained empty.
- Independent r1-to-r2 review found no remaining Critical or Important harness-correctness issue from those two corrections, but identified one publication-readiness gap: Git warned that LF working-tree content could later be converted to CRLF. Because Test D review/publication binds exact SHA-256 values to the construction artifacts, `.gitattributes` now pins the execution contract, static review, harness, and focused test to `text eol=lf`.
- The `.gitattributes` hardening is policy-only and does not change the r2 construction bytes. Repository verification requires all four artifact SHA-256 values to remain exact, their working-tree bytes to remain LF-only, and `git check-attr` to report `text: set` / `eol: lf` for each path.
- Exact r2 hashes: contract `7fd8dc545761231c5b9bcfb9db083ada61caf6f11b7c0b40a4c55904f6cef5f8`; static review `f45a706c0bfe17c916b065ee484a69a51902f29babe1f03cf90c54a88a9731c8`; harness `11bc77403910d67dff342eb20af73cd75ac39d47f9baedf2023c0fa015d68d7a`; focused test `fa23102e3177b64e8ab8a5892b3aa913e9e3d282405a67c9915009b15152d4f4`.
- Construction r2 is **PASS FOR PUBLICATION REVIEW** but remains live-execution prohibited. `EXECUTION_ENABLED = False`; no staging, commit, push, Resolve contact, Control timeline mutation, queue mutation, or SQLite access is authorized by this entry.

## Unreleased - Phase 14 Test D r3 Corrections and Canonical Publication-Candidate Transition

- An independent review of the r2 staged diff (the reviewed r2 publication candidate held in the Git index) found two further Important findings and required them corrected before publication, without redesigning the experiment or touching the r1/r2 corrections already in place.
- Finding 1: in r2, a failure writing `add_render_job_result.json` immediately after the sole `AddRenderJob()` call could abort `execute_test_d()` before the post-call queue/rendering/identity/timeline/Media Pool observations ran. Construction r3 catches that failure (and any later failure writing `post_add_evidence.json`), records it in an in-memory `evidence_errors` list, still runs every read-only post-call observation, and forces the final result to `inconclusive` whenever either write fails. No retry is introduced.
- Finding 2: in r2, `validate_test_d_snapshot()` permitted an arbitrary post-removal timeline end frame, and a unit test exercised the unconstrained value `99999`. Construction r3 restricts the accepted end frame to exactly `86424` (Resolve shrinks the timeline to the retained audio item's end) or `86544` (Resolve retains the reviewed pre-removal Control end); any other value, non-integer, or boolean now fails closed before render-context mutation or queue submission.
- Both corrections were independently re-verified against the r3 working tree: the end-frame gate runs inside `_pre_add_snapshot()`, called three times before the sole `AddRenderJob()` call, so it is enforced before queue mutation and not merely documented; the evidence-failure handling was exercised by two new focused tests proving post-call observation continues and the result is forced to `inconclusive` in both failure cases.
- Exact-byte r3 hashes were independently re-verified against the working tree immediately before this canonical-documentation update: execution contract `d68f7fbb613629b6c6d3d52f145ed7486e1068219874e05cf34b84c8a000c8db`; static review `18300fa053a1cb422e3786c593f5fa8b5df59e4a780702d8603827d60d881a71`; harness `9b0c43585399af0b42752ed52dc3616fd58ab4c83359f1db7fa63d28c8b22238`; focused tests `117b7c401e1cc445de3af5baf6ad47309defd20a7295b108382535edb126de2d`.
- Native Windows Python 3.11.9 verification reproduced: compilation PASS, focused Test D suite **41 passed**, combined Phase 14 focused regression slice **142 passed**. HEAD remained `33b324220b3fbfe66def17b0e6587d55042e4c92` throughout construction and review; the Git index retained the reviewed r2 publication-candidate state unchanged until this canonical-documentation-and-staging transition, explicitly and separately authorized by Paul Jones.
- Independent r3 review found no remaining Critical or Important finding: exactly one AST-visible `AddRenderJob()`/`LoadRenderPreset()`/`SetRenderSettings()` call each, no `sqlite3` import, no render start/stop/deletion, no project/timeline mutation by the harness, `EXECUTION_ENABLED = False`, and `git diff --check` reported no whitespace/line-ending errors against the four r3 files.
- This entry, together with `docs/ROADMAP.md` and `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, brings the canonical documentation to construction r3. The resulting eight-path staged set (`.gitattributes`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`, `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, `docs/PHASE14_TEST_D_STATIC_REVIEW.md`, `scripts/phase14_test_d_queue_attempt.py`, `tests/unit/test_phase14_test_d_queue_attempt.py`) is the r3 canonical publication candidate. This entry does not authorize commit, push, Resolve contact, Control timeline mutation, `AddRenderJob()`, or SQLite access. `EXECUTION_ENABLED` remains `False`.

## Unreleased - Phase 14 Test D r4 Temporal End-Frame Stability Correction

- The final independent review of the staged r3 publication candidate found one Important finding: the r3 accepted-value end-frame gate (`86424` or `86544`) checked each of the three pre-`AddRenderJob()` snapshots in isolation, so a run could observe `86424` at one snapshot and `86544` at another without failing, because both values individually remained justified. That let the end frame drift mid-run behind two individually-valid values — a second, unauthorized experimental variable.
- Construction r4 adds temporal stability on top of the unchanged accepted-value set. The first Test D snapshot in a run (`initial`) binds whichever of `86424`/`86544` it observes as that run's expected end frame via a new `expected_end_frame` parameter threaded through `validate_test_d_snapshot()` and `_pre_add_snapshot()`. The second and third pre-`AddRenderJob()` snapshots (`pre_render_context`, `final_guard`) must match that bound value exactly; a mismatch raises and fails closed before `AddRenderJob()` is called. The post-call timeline observation is checked against the same bound value; a mismatch there is recorded as a post-call error using the existing observational, non-mutating mechanism and forces the result to `inconclusive`. No repair, retry, or restoration is introduced anywhere in this correction.
- Added seven focused tests: two granular `validate_test_d_snapshot(expected_end_frame=...)` match/mismatch cases, and five `execute_test_d()`-level scenarios — drift at the pre-render-context snapshot (fail closed, zero `AddRenderJob()` calls), drift surviving to the final pre-add guard (fail closed, zero calls), drift appearing only in the post-call observation (exactly one call, forced `inconclusive`, no retry), and stable `86424` and stable `86544` runs (each remains valid and reaches `accepted`).
- Native Windows Python 3.11.9 verification: compilation PASS, focused Test D suite **48 passed** (41 existing + 7 new), combined Phase 14 focused regression **149 passed** (142 existing + 7 new). Exact AST-visible mutation counts unchanged: one `AddRenderJob()`, one `LoadRenderPreset()`, one `SetRenderSettings()`; no prohibited render/navigation/content mutation, no `sqlite3` import, `DaVinciResolveScript` import still confined to `connect_live_resolve()`.
- Exact-byte r4 hashes, independently computed against the working tree: execution contract `e4b9cfdc1121f322a42633c6da4e15c54de4bb8f55a28812b9f516d421814b1d`; static review `1b05e10ce6efb11672338b2265a667599fc9937b14d39cfe3a77712a08bac4a5`; harness `a70d0df5a7fe91a1315e19cb56f16cda50ba1044af4e4dbc515017f0f8ca123d`; focused tests `9c40d6821932d4c6201604521a150924204b17b047a96c1f80a5fb444ddc1b64`.
- Construction r4 was performed strictly as an unstaged working-tree layer over the seven authorized files (`docs/CHANGELOG.md`, `docs/ROADMAP.md`, `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, `docs/PHASE14_TEST_D_STATIC_REVIEW.md`, `scripts/phase14_test_d_queue_attempt.py`, `tests/unit/test_phase14_test_d_queue_attempt.py`). The existing staged r3 eight-path publication candidate, including `.gitattributes`, was left untouched in the Git index; this entry does not stage, unstage, commit, or push. `EXECUTION_ENABLED` remains `False`; live execution, Resolve contact, Control video-item removal, and `AddRenderJob()` remain prohibited.

## Unreleased - Phase 14 Test D r4 Publication-Candidate Index Integration and Documentation Reconciliation

- This entry is a separate, later authorization from the r4 construction entry immediately above; it does not modify or reinterpret the construction step, which genuinely staged nothing. Four distinct authorizations exist for Test D and must not be conflated: **construction** (writing/correcting the harness, tests, and contract as an unstaged working-tree layer), **index integration** (staging already-reviewed bytes with zero further edits), **commit/push** (not yet granted), and **live execution** (not yet granted, and gated on a future separately reviewed execution-enablement revision).
- Paul Jones separately authorized the Phase 14 Test D r4 publication-candidate index integration. Under that authorization, the seven reviewed r4 paths were staged exactly as previously reviewed, with no further edits; the existing staged `.gitattributes` blob was preserved unchanged and not restaged. The Git index now contains the exact eight-path r4 publication candidate (`.gitattributes`, `docs/CHANGELOG.md`, `docs/ROADMAP.md`, `docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, `docs/PHASE14_TEST_D_STATIC_REVIEW.md`, `scripts/phase14_test_d_queue_attempt.py`, `tests/unit/test_phase14_test_d_queue_attempt.py`), and the working tree is clean relative to the index.
- Independently re-verified after integration: HEAD remained `33b324220b3fbfe66def17b0e6587d55042e4c92`; the four hash-bound staged artifacts matched their reviewed r4 SHA-256 values (listed in the construction entry above) exactly when hashed directly from the Git index, not merely the working tree; `git check-attr` reported `text: set` / `eol: lf` for all four; native Windows Python 3.11.9 compilation passed; the focused Test D suite reproduced **48 passed**; the combined Phase 14 focused regression reproduced **149 passed, 1327 deselected**; and `git diff --cached --check` exited 0.
- A subsequent final staged-diff publication review of the complete eight-path `git diff --cached` found no code or safety-boundary defect, but found that `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md`, `docs/ROADMAP.md`, and this file's r4 construction entry still described construction r4 as unstaged after the index integration above had already completed. This entry, together with corrections to `docs/PHASE14_TEST_D_REPOSITORY_REVIEW.md` and `docs/ROADMAP.md`, reconciles that documentation-status gap under a separate, explicit founder authorization limited to those three files. No byte of the harness, tests, execution contract, static review, or `.gitattributes` was touched by this reconciliation.
- `EXECUTION_ENABLED` remains `False`. This entry does not authorize commit, push, Resolve contact, Control timeline mutation, `AddRenderJob()`, SQLite access, or live Test D execution. Phase 14 remains open and BLOCKED.

## Unreleased - Phase 14 Test D Execution-Enablement r1 Construction and Static/Native Verification

- Constructs the smallest separately reviewable execution-enablement revision (`phase14-test-d-video-payload-isolation-execution-enablement-r1`) on top of the published, immutable Phase 14 Test D r4 publication candidate (commit `9b26fa0886ae32bf30f30c2384861dfd0338f5a4`, `feat: add Phase 14 Test D r4 isolation controls`). The r4 experiment design and Resolve mutation path are frozen and unchanged; this revision only makes the harness live-capable through its existing explicit `--execute` path.
- `EXECUTION_ENABLED` changes from `False` to `True` only in this new revision. The static r1-r4 founder-authorization phrase gate is replaced by `build_required_authorization()`, which derives the exact required authorization text from the invocation's expected repository commit, expected harness SHA-256, and expected execution-contract SHA-256, together with the fixed Control project/timeline identity and the fixed one-shot scope (exactly one manual video-item removal, exactly one queue attempt, no retry, no Production access, no rendering, no cleanup, no second submission, no additional mutation). A missing, malformed, or non-exact authorization fails before evidence-directory creation, before `DaVinciResolveScript` import, before `scriptapp("Resolve")`, and before any Resolve mutation.
- The frozen r4 experiment core is unchanged: `execute_test_d()`, `validate_test_d_snapshot()`, `_pre_add_snapshot()`, queue-outcome classification, durable `pre_add_evidence.json` behavior, post-mutation evidence observation, temporal end-frame stability, the Media Pool/timeline/project invariants, the exact `mov` / `DNxHRHQX_10` render-context gate, and the Resolve queue-mutation sequence are all byte-for-byte identical to the published r4 commit.
- The published r4 execution contract (`docs/PHASE14_TEST_D_EXECUTION_CONTRACT.md`, SHA-256 `e4b9cfdc1121f322a42633c6da4e15c54de4bb8f55a28812b9f516d421814b1d`), static review, repository review, and `.gitattributes` are unmodified.
- Adds `docs/PHASE14_TEST_D_ENABLEMENT_STATIC_REVIEW.md` (base commit, immutable contract hash, exact enablement diff, authorization-binding architecture, unchanged experiment core, and test/static results) and `docs/PHASE14_TEST_D_LIVE_EXECUTION_RUNBOOK.md` (a PROPOSED / NOT AUTHORIZED description of the future live sequence only).
- Replaces two tests whose sole purpose was asserting r4's hard-disable (`test_construction_revision_is_hard_disabled`, `test_execute_request_stops_before_resolve_connection`) with nine enablement-specific gate tests. Native Windows Python 3.11.9 verification: compilation PASS, focused Test D suite **55 passed** (48 existing minus 2 replaced plus 9 new), combined Phase 14 focused regression **156 passed**, 1327 deselected. Exact AST-visible mutation counts unchanged: one `AddRenderJob()`, one `LoadRenderPreset()`, one `SetRenderSettings()`; no prohibited render/navigation/content mutation; no `sqlite3` import; `DaVinciResolveScript` import still confined to `connect_live_resolve()`. `git diff --check` exit 0.
- Exact-byte enablement-r1 hashes, independently computed against the working tree: harness `eeae8f315737fbdd14d0be715fa004642879c787d53dc03040b52770f72ff847`; focused tests `e6bf6b023f21e7c0d92a249eadb59369fedb6ef59ce3cc50c3fcd273872680d3`.
- This construction and its static/native verification does not authorize live Test D execution, Resolve contact, Control video-item removal, `AddRenderJob()`, render-queue mutation, `StartRendering()`, SQLite access, or Production access. No staging, commit, or push is authorized by this entry. Phase 14 remains open and BLOCKED.

## Unreleased - Phase 14.1 Rev7 Native-Process Compatibility Correction

- Records the single authorized Rev6 non-contact preflight failure: the
  runbook stopped before evidence-directory creation with a Python `-c`
  `NameError`. No Resolve scripting contact, SQLite access, snapshot,
  project/timeline mutation, render-queue mutation, staging, commit, or push
  occurred.
- Records that a later exact-host compatibility probe did not reproduce the
  one-time `NameError`; Rev7 therefore does not assert an unproved
  deterministic cause. The same probe confirmed a separate deterministic
  incompatibility: Windows PowerShell 5.1 / CLR 4 exposes no
  `ProcessStartInfo.ArgumentList`, which Rev6 used for manifest validation.
- Replaces every Phase 14.1 Python process boundary with one Windows CRT argv
  encoder using `ProcessStartInfo.Arguments`; replaces the JSON-bearing
  identity command with a quote-free field-delimited probe; transports the
  exact single-read manifest bytes as strict Base64 to the new
  `validate-manifest-base64` non-contact command; and uses the same helper
  for the eventual snapshot subprocess.
- Mints execution revision identifier `phase14.1-live-interlock-construction-rev7`. This construction does not
  authorize preflight or live execution; a future published Rev7 checkpoint
  requires a newly reviewed authorization manifest and separate founder
  authorization.
- Adds eight focused tests, bringing the Phase 14.1 focused suite from 70 to
  78: two Base64 CLI tests, five static runbook guards, and one real native
  Windows PowerShell-to-Python argv/validator round-trip. All are non-contact
  and do not access SQLite.

- Pins the four Phase 14.1 authorization-manifest-bound artifacts to
  `text eol=lf` in `.gitattributes`, preventing a Windows
  `core.autocrlf=true` checkout from changing their reviewed byte sequences
  and invalidating SHA-256/self-hash bindings. Rev7 validation now verifies
  both Git attributes and LF working-tree/index state for those four files.

## Unreleased - Phase 14 Snapshot Probe: Dual Project/Timeline Read-Only Construction and Independent Review

- Adds a dual project/timeline read-only snapshot and offline comparison
  probe at `scripts/phase14_resolve_context_snapshot.py`, a mocked unit
  test suite at `tests/unit/test_phase14_resolve_context_snapshot.py`, and
  a companion contract at
  `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md`. The dual project/timeline
  snapshot probe has been constructed to support a future read-only
  comparison of the disposable control context (`redline-os-test-duplicate`
  / `RLO-LIVE-ASM-92701_TIMELINE`) and the production-like context
  (`RLC-E9001_MASTER` / `RLC-E9001_TIMELINE`) without identifying causation
  by itself.
- The source, mocked tests, and comparison contract were independently
  reviewed. The probe's live `snapshot` CLI path is hard-disabled by
  `SNAPSHOT_EXECUTION_ENABLED = False`, checked before the Resolve
  connection function is ever called. The source contains no direct
  `DaVinciResolveScript` import, and the independent AST safety scan passed:
  zero calls to any method in the source's `PROHIBITED_RESOLVE_METHODS` set
  (covering project/timeline switching, preset loading, render-settings
  mutation, and all render-queue mutation), and the dynamic Resolve
  accessor allowlist and the prohibited set are confirmed disjoint.
- Dedicated Python compilation passed against the repository copies. The
  focused mocked suite passed with 23 tests. No Resolve contact occurred,
  no SQLite access occurred, and no live project or timeline snapshot was
  captured at any point in construction, review, or this documentation
  update.
- The repository copies of the three files match their independently
  verified SHA-256 hashes:
  - `scripts/phase14_resolve_context_snapshot.py`:
    `cf2dfb1670e4d62a4aabd7847c4f1f019d3333d23b6ceff5aecc4de649e78340`
  - `tests/unit/test_phase14_resolve_context_snapshot.py`:
    `35445df167dc7f2411b904fe5e1df8e81ed8357ea7fa1192d998c35ac9bf8ca4`
  - `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md`:
    `f0ce726e6d94334ae2eebfc23a23b991104dc47f1bd167a6d2f3f69d25d3e7b9`
  The construction hash is not a live-execution authorization hash. A
  future live-capture mission must define a separately reviewed execution
  contract, generate a new SHA-256, and receive explicit founder
  authorization bound to that exact source revision and repository commit.
- No live Resolve snapshot has been captured and no comparison against a
  live production-like context has occurred. The production-like render
  rejection root cause documented in the Phase 14 Test B/Test C entry below
  remains unresolved. **Phase 14 remains open and BLOCKED**, not complete,
  pending a separately authorized live-capture process.
- Documentation-and-source entry. No production application code,
  configuration, dependencies, or Resolve/SQLite state changed as part of
  this update. The only source and test additions are the three independently
  reviewed Phase 14 files listed above, preserved exactly at their verified
  hashes, together with the canonical documentation updates recording their
  status.

## Unreleased - Phase 14 Test B and Test C: Project x Preset Isolation Matrix Completed

- Executes Phase 14 Test B: a live one-shot attempt of the custom
  `Redline Broadcast Master` preset against the disposable
  `redline-os-test-duplicate` project (timeline
  `RLO-LIVE-ASM-92701_TIMELINE`), completing the disposable-project /
  custom-preset cell of the Phase 14 project x preset isolation matrix.
  Preconditions (empty valid queue, inactive rendering, matched
  project/timeline identity, preset presence, repository gates) were
  verified before execution.
- Test B confirmed queue acceptance by post-execution queue-state recovery,
  not by the original harness's direct return value or exit code. The
  original harness's terminal JSON/exit-code output was cleared before being
  captured; the following are therefore not known and are not asserted: the
  direct `AddRenderJob()` return value, the original process exit code, and
  whether the original harness itself classified the outcome as
  `direct_job_id_confirmed` or `fallback_single_job_confirmed`. A separately
  authorized read-only recovery probe instead confirmed exactly one matching
  render-queue job existed post-execution:
  - Job ID `d346ae41-6aa2-4457-a7b1-affb7e72a020`
  - Timeline `RLO-LIVE-ASM-92701_TIMELINE`
  - Target directory `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests`
  - Output filename `phase14-test-b-redline-broadcast-master.mov`
  - Video format QuickTime, video codec Avid DNxHR HQX 10-bit, audio codec aac
  - Rendering remained inactive
- The accepted job was manually removed after inspection. Final read-only
  verification confirmed `queue_count=0`, `queue_empty=true`,
  `queue_items=[]`, `extracted_job_ids=[]`, `unidentified_items=[]`,
  `rendering_inactive=true`, probe exit code `0`.
- Approved disposable control/read-only probe SHA-256:
  `97edbb7c241ae2791c3a0a0724dfdae9b03fe08bba099a869dbe7d9b1ff990c9`.
  Approved Test B harness SHA-256:
  `5e9d93997b6a718583bf4311251a2478dfedabe9bfa05de6d9688403ac82cf30`.
- Executes Phase 14 Test C: a live one-shot attempt of the built-in
  `YouTube - 720p` preset against the production-like `RLC-E9001_MASTER`
  project (timeline `RLC-E9001_TIMELINE`), completing the
  production-project / built-in-preset cell of the matrix. All
  preconditions passed (repository gates, Python 3.11.9, founder
  authorization phrase match, exact project/timeline identity, single
  matching timeline in inventory, `YouTube - 720p` present exactly once,
  valid empty queue, `IsRenderingInProgress()` literally `False`, output
  directory present with no stem collision, and stable project/timeline
  identity immediately before mutation).
- `LoadRenderPreset("YouTube - 720p")` returned `True`;
  `SetRenderSettings(...)` returned `True`; `AddRenderJob()` returned an
  empty string. The queue was empty both before and after the call. The
  harness classified the outcome `queue_job_rejected` (exit code 16):
  "AddRenderJob() returned no usable typed ID and the queue was unchanged."
  No render job was accepted, no rendering started, and no cleanup was
  required.
- Approved Test C production read-only preflight probe SHA-256:
  `f4dfda3fbfc79e02922cec029508f40bc8e4b04b9c434bd8a3f3701287821c9d`.
  Approved Test C harness SHA-256:
  `8dc0b4bf70680ec27486deb9bdae761c3f8fad945eb51034ff9bb5b04b6e95b0`.
- Completes the Phase 14 project x preset isolation matrix:

  | Project context | YouTube - 720p | Redline Broadcast Master |
  |---|---|---|
  | Disposable control project | Accepted | Accepted |
  | RLC-E9001_MASTER | Rejected | Rejected |

- The completed matrix shows that queue rejection follows the
  `RLC-E9001_MASTER`/`RLC-E9001_TIMELINE` context across both tested
  presets: both presets were accepted in the disposable control context and
  rejected in the production-like context. This rules out either preset
  being universally incapable of queue acceptance. The evidence does not
  yet identify the exact project- or timeline-level cause; the specific
  mechanism (project-specific state, timeline-specific state, project or
  timeline render eligibility, internal project/timeline configuration
  differences, or a project-specific interaction with Resolve queue
  acceptance) remains an open hypothesis, not a conclusion.
- Phase 14 remains **open and BLOCKED**. Test B and Test C are each
  individually complete as evidence-gathering activities; the broader
  production queue-acceptance problem is not resolved. No further live
  Resolve mutation is authorized. The next allowed planning activity is
  repository-only review and read-only comparison design; no Test D design
  or authorization is included in this entry.
- Documentation-only entry. No application code, tests, configuration,
  dependencies, scripts, SQLite, environment variables, or Resolve state
  changed as part of this documentation update.

## Unreleased - Canonical Claude Operating Instructions

- Adds `CLAUDE.md` at the repository root as the canonical, permanent Redline
  OS governance document for both Claude Cowork and Claude Code sessions,
  covering the authority model, default read-only/planning-only mode,
  repository-mutation and commit/publication controls, the DaVinci Resolve
  safety boundary, runtime-database protections, testing rules, evidence
  standards, scope control, and stop conditions already governing Redline OS
  repository work.
- Normalizes the document's applicability wording so it explicitly names
  both Claude surfaces, and removes a machine-specific filesystem path in
  favor of repository-neutral language. No governance meaning, authority
  assignment, or safety boundary was changed.

## Unreleased - Phase 14 Mission 39I.2o: Resolve Content-Identification Probe (Static Review)

- Creates and statically hardens a read-only content-identification probe at
  `runtime/mission39i_resolve_content_read_only_probe.py`, narrowly scoped to
  identify existing media-pool clips and timeline items in the disposable
  `RLC-E9001_MASTER` project without any project, timeline, media, or
  render-queue mutation.
- Correction rounds r1 through r9 completed source-level hardening, covering
  structural collection/count/element/boolean validation, complete timeline
  discovery with no early return and closed handling of duplicate exact-name
  matches, and accurate raised-vs-None error attribution for required Resolve
  handles. R9 received independent source-level approval.
- Repeated and cyclic media-pool folder handles fail closed as structured
  errors with complete first- and repeated-encounter hierarchy attribution,
  rather than being silently dropped or under-attributed.
- Folder-hierarchy components are string-only by construction, using the
  deterministic sentinel `UNAVAILABLE_FOLDER_NAME = "<folder-name-unavailable>"`
  in place of any unavailable, `None`, or non-string `GetName()` result.
  Unsupported-object representations remain confined to general normalized
  evidence fields and cannot enter hierarchy paths or repeated-folder
  diagnostics.
- Import, connection, and project-access failures (`DaVinciResolveScript`
  import, `scriptapp("Resolve")`, `GetProjectManager()`, `GetCurrentProject()`)
  are all converted into reported connection failures rather than risking an
  uncaught, evidence-free crash.
- Mutation safety passed static review: no create, import, rename, save,
  delete, move, queue, start, stop, or cancel Resolve method is invoked, and
  the probe's only dynamic dispatch is restricted to a closed, seven-name
  read-only accessor allowlist.
- The probe was not run or imported, and DaVinci Resolve was not contacted,
  at any point during creation or review. Live execution remains prohibited
  and requires separate, explicit founder authorization tied to a specific
  reviewed script hash and repository commit.
- Approved r9 probe file SHA-256:
  `510c211ee8e14de65891f47c8e041d79a9821e701a05f3efdae4dd515a0ae111`,
  recorded against repository HEAD `5f506e32d39f1a6068d69eb215f1b67688cf08c6`.

## Unreleased - Phase 14 Mission 39I.2f: Local Runtime Path Hygiene

- Ignores workstation-local `.claude/` state and the generated `_episodes/`
  episode working root so dry-review Git metadata sees no permitted local
  runtime directories as versionable repository content.
- Keeps `.claude/` verification metadata-only and records that `_episodes/` is
  generated from `config/folder_structure.yaml`, not source content.
- Removes the empty `.agents/` local directory after verifying it contained no
  files or child directories.
- Updates the Mission 39I Gate 1 contract so ignored local/runtime directories
  do not need to appear as untracked paths, while any visible untracked path
  still fails closed.

## Unreleased - Phase 14 Mission 39I.2a: Dry-Review Gate 1 Metadata Correction

- Corrects the Mission 39I harness repository gate so `.claude/` can remain
  an expected untracked path even when the harness subprocess can read a
  global Git ignore file that hides it from default `git status --porcelain`.
- Records raw default Git status, tracked-only status, untracked-path metadata,
  and `.claude/` Git metadata separately before parsing. `.claude/` remains
  verified through Git metadata only and must remain untracked.
- Adds focused regression coverage for the hidden-by-ignore case without
  inspecting `.claude/` contents.
- Does not run the harness with `--execute`, access Resolve, call
  `AddRenderJob()`, execute the queue command, change SQLite/configuration, or
  authorize a live Mission 39I attempt.

## Unreleased - Phase 14 Mission 39I.1: Controlled Queue Attempt Script Review Harness

- Adds a fail-closed Mission 39I live queue-attempt harness at
  `scripts/mission39i_live_queue_attempt.py` for review before any live use.
  The harness records a timestamped evidence package under the operating
  system temporary directory, encodes the seven preflight gates, requires an
  explicit `--expected-repository-commit` live pin supplied by the reviewed
  contract/authorization record, and fixes the future live command to the
  Python 3.11 module form:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m cli.main render queue RLC-E9001 broadcast_master`.
- The harness defaults to dry review and stops before Resolve access. Future
  live execution requires `--execute`, the reviewed script SHA-256, the exact
  reviewed repository commit, the exact founder authorization phrase, and a
  manual observation JSON file.
- Adds mocked unit coverage for the fixed command, dry-review stop boundary,
  script-hash guard, explicit repository-commit pin validation, sanitized
  queue inventory, acceptance-not-observed classification, and the rule that
  structural queue changes alone do not prove acceptance.
- Does not authorize or perform a live Resolve connection, `AddRenderJob()`,
  render start, render cancellation/deletion, configuration change, dependency
  change, SQLite mutation, or Windows YAML fixture repair.

## Unreleased - Phase 14 Mission 39H: Broadcast Master Queue Diagnostic Enrichment

- Improves post-`AddRenderJob()` diagnostics without changing render queue
  submission behavior, retry behavior, cleanup semantics, production
  configuration, or the authoritative job-ID multiset acceptance rule.
- Adds sanitized queue-inventory diagnostics for reconciliation failures:
  queue item counts, item types, dictionary key names, usable job IDs,
  missing-ID counts, non-dictionary item counts, and a diagnostic-only
  structural before/after comparison. Raw queue object values are not logged.
- Expands the pre-add diagnostic context with requested project, requested and
  current timeline names, preset name, normalized target-directory
  existence/type/read-access status, and sanitized render-settings keys/value
  types when Resolve exposes them.
- Maps MCP `queue_render` failures for `RenderQueueAcceptanceNotObservedError`
  and `RenderQueueIdentityUnresolvedError` to the same category strings used by
  the CLI while preserving the existing `success`/`error` response fields.
- Does not perform a live Resolve queue submission, start rendering, inspect a
  live render queue, change SQLite schema or data, alter environment variables,
  or authorize another Broadcast Master queue attempt.

## Unreleased - Phase 14 Mission 39F: Formal Mission 39D/39E Closure Record

- Formally closes Mission 39D. The queue-failure classification and diagnostic
  work is complete, the authorized one-shot Mission 39D.3 live revalidation
  completed, Resolve did not observably accept a new queue job, postflight
  cleanup was verified, and queue acceptance is not characterized as
  successful.
- Formally closes Mission 39E. The workstation configuration investigation and
  read-only validation are complete: Python 3.11.9 is operational for the
  current Resolve integration, Python 3.13 is incompatible with the current
  Resolve scripting import because it crashes with Windows access violation
  `0xC0000005`, and the read-only adapter connection observed
  `RLC-E9001_MASTER`, `RLC-E9001_TIMELINE`, zero render queue jobs, rendering
  inactive, and probe exit code `0`.
- Keeps Phase 14 open and BLOCKED. Broadcast Master queue acceptance remains
  unproven because Resolve returned an empty `AddRenderJob()` result and no
  new queue job ID was observed. No further live queue submission is
  authorized without a new root-cause investigation, a separately reviewed
  attempt contract, and fresh explicit founder authorization.
- Documentation-only closure record. No application code, tests,
  configuration, dependencies, scripts, SQLite, environment variables, Resolve
  state, or render queue state changed.

## Unreleased - Phase 14 Mission 39D.3: Live Queue Revalidation and Phase Checkpoint

- Performed one fully reviewed, freshly authorized, one-shot live queue
  revalidation against the production-like `RLC-E9001_MASTER` project,
  executed against published commit `2e36a41` under the Mission 39D.2
  behavior. All
  seven ordered preflight gates passed (publication pin including local
  `origin/master` and live remote `refs/heads/master`, filesystem,
  environment, read-only SQLite, read-only Resolve, and a fresh Gate 7
  re-observation immediately before launch); the production
  `render queue RLC-E9001 broadcast_master` command was invoked exactly
  once.
- `AddRenderJob()` again returned an empty string. The pre-add diagnostic
  context captured genuinely live values this time — `render_format='mov'`,
  `render_codec='DNxHRHQX_10'` — confirming the expected Broadcast Master
  output format/codec were observed as active at the moment of the call.
  This rules out an absent or different format/codec observation; it does
  not identify the cause or rule out other Resolve-side conditions. The
  root cause remains unresolved. The result was classified
  `RenderQueueAcceptanceNotObservedError`. A temporary active-output claim
  was acquired before the Resolve call and released after the failure, per
  `RenderManager.queue_render()`'s existing claim/release sequence;
  postflight found zero render-job rows and zero active output claims, the
  episode remained `created`, no output file appeared, and the repository
  remained unchanged.
- Evidence directory:
  `%TEMP%\redline-mission39d3-live-revalidation-20260801T194713957967Z`.
  Reviewed script SHA-256:
  `39AE6DC8D891185F2A6CEB778A8D0FDC13E24F7126CABB59E133C2A6C429B0EC`.
- This is the third controlled live attempt against the disposable
  episode. Across all three, the live queue path failed closed and ended
  with consistent postflight state; the attempts successively exposed the
  missing-ID condition (pre-39D.1), validated the identity-unresolved
  diagnostics (post-39D.1.1), and validated the final
  acceptance-not-observed classification (this attempt). None has observed
  Resolve accept the request. No further live attempt is authorized
  without new root-cause investigation, a separately reviewed contract,
  and fresh explicit authorization.
- Phase 14 ("First Live Episode") is now recorded as **open and BLOCKED**
  rather than complete; the verified checkpoint evidence remains the Mission
  39D.3 result. See `docs/ROADMAP.md`. This was a documentation-only entry:
  no production code changed.

## Unreleased - Phase 14 Mission 39D.2: Empty AddRenderJob() Result Classification and Diagnostics

- Adds `RenderQueueAcceptanceNotObservedError(RenderJobError)` in
  `redline_core.resolve.exceptions`, a sibling of
  `RenderQueueIdentityUnresolvedError` reserved for one exact evidence
  shape: `AddRenderJob()` returned an empty string, the after-phase
  `GetRenderJobList()` snapshot itself succeeded, contained no unidentified
  item, and the before/after job-ID multisets are exactly equal (no new
  candidate). This is a positive claim -- no accepted render job was
  observed by job-ID comparison, not that the queue is unchanged in every
  respect -- rather than the weaker "identity is uncertain" claim
  `RenderQueueIdentityUnresolvedError` makes. Every other empty-string
  outcome (snapshot failure, unidentified item, multiple candidates) still
  raises `RenderQueueIdentityUnresolvedError` unchanged; multiset
  *equality* is required, not merely zero new candidates, so that an
  existing job disappearing with zero new candidates also stays on the
  more cautious path. This classification only runs when reconciliation
  does not already resolve to a single successful candidate; a
  disappearance that coincides with exactly one new candidate is
  unaffected and still succeeds directly, unchanged from before this
  slice.
- This is a direct response to a real, fully-authorized, evidence-preserved
  live Resolve queue attempt against the production-like `RLC-E9001_MASTER`
  project, which returned exactly this shape (`add_result_type=str,
  add_result_repr=''`, `before_job_ids=[]`, `after_job_ids=[]`,
  `candidate_job_ids=[]`) and was, until this slice, classified only as the
  more cautious identity-unresolved outcome.
- Adds `ResolveScriptAdapter._capture_pre_add_render_context()`, called once
  in `queue_render_job()` immediately after render settings are applied and
  before `AddRenderJob()`. Known request values (`timeline_name`,
  `target_dir`, `custom_name`) are the exact already-applied local values,
  never recomputed; the additional read-only `GetCurrentRenderFormatAndCodec()`
  inspection is fully defensive -- attribute discovery, invocation, and
  result parsing are wrapped in one try/except, since a bridged Resolve
  object's attribute lookup can itself raise a non-`AttributeError`
  exception that a bare `getattr(obj, name, default)` would not suppress --
  and never blocks `AddRenderJob()`. `render_mode` has no confirmed
  read-only getter on this adapter surface today and remains `"unavailable"`
  until one is verified against a live Resolve instance.
- Renames `_log_render_queue_identity_unresolved()` to
  `_log_render_queue_reconciliation_failure()` and adds a deterministic
  `reconciliation_outcome` field (`acceptance_not_observed` or
  `identity_unresolved`) plus the new pre-add context fields
  (`timeline_name`, `target_dir`, `custom_name`, `render_format`,
  `render_codec`, `render_mode`), appended after the existing diagnostic
  field bundle. Existing field names, order, and format are unchanged.
  Logging remains best-effort and cannot mask either domain exception.
- Adds a distinct CLI failure category, `"render queue acceptance not
  observed"`, in `cli.render_commands._run_render_queue`.
- `RenderManager` is unchanged -- its existing generic queue-exception
  boundary already releases the active SQLite claim and re-raises the
  original exception for any exception type, including this new one.
- Updates the render-queue failure-boundary section of
  `docs/ARCHITECTURE.md`, which had not been updated since before Mission
  39D.1 and still described every post-`AddRenderJob()` reconciliation
  failure as plain `RenderJobError`.
- Implemented and validated with mocks only -- no live Resolve connection,
  no `runtime\mission39d.sqlite` interaction, and no new queue attempt was
  made as part of this slice.

## Unreleased - Phase 14 Mission 39D.1.1: Route Queue-Identity Diagnostics to the Application Log

- The queue-identity diagnostic now emits through the configured `redline_os`
  application logger namespace and is proven to reach the rotating file
  handler in a temporary-directory test. Previously,
  `_log_render_queue_identity_unresolved()` logged via the adapter module's
  routine `logging.getLogger(__name__)` logger (`redline_core.resolve.adapter`),
  which is not a descendant of `redline_os` and therefore never reached
  `logs/redline_os.log` in a real run -- `configure_logging()`
  (`redline_core.logging.setup`) only installs handlers on `redline_os` and
  its descendants. A new dedicated `_render_queue_identity_logger =
  logging.getLogger("redline_os.resolve.adapter")` is used only at that one
  diagnostic call site; the adapter's routine logger is unchanged, and no
  other adapter log line was moved.
- Adds a direct file-routing proof to `tests/unit/test_logging_setup.py`
  (`test_application_child_logger_message_reaches_file`) confirming a child
  logger under `redline_os.*` reaches the configured rotating file handler.
- Adds an adapter-level integration test using a real `configure_logging()`
  call (rather than only `caplog`) to prove the queue-identity diagnostic
  bundle actually lands in `redline_os.log`. That test saves and restores
  the process-wide `redline_os` logger's handlers, level, and propagation
  around the real `configure_logging()` call so it cannot leak logging state
  into later tests in the same session, and closes only its own owned
  handlers so the temporary log file isn't held open on Windows.
- This is a logging-route correction only: queue behavior, exception
  classification, claim release, database finalization, episode status, and
  the CLI failure category are all unchanged. Implemented and validated
  with mocks and a real-but-isolated `configure_logging()` call only -- no
  live Resolve connection, no `runtime\mission39d.sqlite` interaction, and
  no new Mission 39D queue attempt.

## Unreleased - Phase 14 Mission 39D.1: Render Queue Identity-Unresolved Classification

- Adds `RenderQueueIdentityUnresolvedError(RenderJobError)` in
  `redline_core.resolve.exceptions`, raised only when `AddRenderJob()` has
  returned something other than explicit `False` and no direct job ID was
  obtained, and Redline subsequently cannot prove the identity of exactly one
  newly queued Resolve job — a snapshot fetch failure, an unidentifiable
  after-phase queue item, zero new candidates, multiple ambiguous candidates,
  or any other unexpected error while reconciling. Before-phase failures and
  standalone `list_render_jobs()` remain plain `RenderJobError`, unchanged.
- Adds `ResolveScriptAdapter._reconcile_after_add()`, replacing the inline
  after-phase reconciliation in `queue_render_job()`: a single
  `GetRenderJobList()` snapshot (`_get_render_jobs_snapshot`) is fetched once
  and reused for both ID extraction and diagnostic logging — no second
  Resolve observation. `_derive_new_render_job_id()`'s candidate logic is
  extracted into a pure `_compute_new_job_id_candidates()` helper but is
  otherwise behaviorally unchanged.
- Logs the full diagnostic bundle (`add_result` type/repr, before/after job
  IDs, after-list item count/types/keys, candidate IDs, and the underlying
  reconciliation error's type/repr) via one centralized, best-effort logging
  helper before raising. Logging is guaranteed never to mask the domain
  exception, including when `logger.error()` itself fails.
- Adds a distinct CLI failure category, `"render queue identity unresolved"`,
  in `cli.render_commands._run_render_queue`, so this condition is no longer
  indistinguishable from an ordinary Resolve connection or configuration
  failure.
- This slice is a response to an uncertain Mission 39D live queue outcome
  (`AddRenderJob()` returned no usable job ID) reviewed and reconciled
  read-only: the live workstation was left in a clean, consistent state
  (empty Resolve queue, zero SQLite render rows, episode status unchanged, no
  output file) — nothing required adoption or cleanup. This slice adds no
  polling, retries, sleeps, or new Resolve job-ID keys; those remain
  deferred pending evidence from a future controlled live attempt made with
  this logging in place. Implemented and validated with mocks only — no live
  Resolve connection or `runtime\mission39d.sqlite` interaction was made as
  part of this slice, and no new live queue attempt has been authorized.

## Unreleased - Phase 14 Mission 39C: Broadcast Master Preset Provisioning

- Activates the founder-approved Broadcast Master export filename standard in
  canonical config: `broadcast_master` now uses `filename_template:
  "{project_name}"`, `file_extension: ".mov"`, `output_subfolder: "exports"`,
  and `collision_policy: "reject"` while still mapping to the Resolve preset
  `Redline Broadcast Master`.
- Records live read-only Resolve verification for the disposable
  `RLC-E9001_MASTER` project: `GetRenderPresetList()` returned
  `Redline Broadcast Master`, `Preset found: True`, the queue remained empty,
  and no rendering was started.
- Leaves `youtube_1080p` incomplete and fail-closed until a separate approved
  YouTube export filename standard exists.
- Leaves Mission 39D not started; controlled live queue validation still
  requires review, commit, publication, and explicit authorization.

## Unreleased - Phase 14 Mission 39B: Deterministic Render Queueing

- Adds a deterministic render output contract to `render_presets.yaml`:
  queueable presets can provide `filename_template`, explicit
  `file_extension`, and `collision_policy: reject`.
- Keeps incomplete presets fail-closed before Resolve submission, SQLite
  render-job insertion, or output filesystem mutation. Mission 39C later
  activates the approved Broadcast Master `{project_name}.mov` standard while
  leaving unrelated presets incomplete unless separately approved.
- Adds immutable render output planning so one queue request calculates one
  canonical output directory, filename stem, extension, and full expected
  output path before Resolve or SQLite mutation.
- Changes render queue ordering so `RenderManager.queue_render(...)` rejects
  exact output-file collisions and matching inspectable Resolve queue jobs, then
  atomically claims the active output path in SQLite before Resolve queue
  mutation.
- Adds active-output uniqueness for `claiming`, `queued`, and `rendering`
  render jobs so concurrent queue requests cannot own the same output path.
- Changes Resolve queue submission to use an explicit prepared request:
  project, timeline, Resolve preset, `TargetDir`, and `CustomName`.
- Finalizes an active SQLite output claim only after Resolve accepts the job and
  returns a usable Resolve job ID. Resolve rejection releases the claim and
  creates no queued row.
- Adds best-effort compensation for database finalization failure after Resolve
  acceptance by deleting the newly accepted Resolve job; failed compensation
  surfaces a reconciliation-required error containing the Resolve job ID.
- Maps MCP render `ResolveError` failures for queue, status, and cancel into
  structured error responses, and includes `project_name` and `timeline_name`
  in MCP render-job responses.
- Keeps `render queue` enqueue-only: it does not call `StartRendering`, poll
  status, build, archive, overwrite, retry, or provision Resolve presets.
- Records that Mission 39B added the mechanism but did not yet activate a
  production filename standard.

### Verification

- Focused CLI render regression:
  `pytest tests/unit/test_cli_render.py -q` - 27 passed.
- Focused Mission 39B review-correction regression:
  `pytest tests/unit/test_config.py tests/unit/test_db.py
  tests/unit/test_render_manager.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_cli_render.py tests/unit/test_resolve_mock.py -q` - 134
  passed.
- Focused active-output claim correction regression:
  `pytest tests/unit/test_render_manager.py tests/unit/test_db.py -q` - 50
  passed.
- Focused MCP correction regression:
  `pytest tests/unit/test_mcp_tools.py -q` - 57 passed.
- MCP startup smoke and tool regression:
  `pytest tests/unit/test_mcp_tools.py
  tests/unit/test_installed_mcp_startup_smoke.py -q` - 58 passed.
- Render/config/composition regression:
  `pytest tests/unit/test_cli_render.py tests/unit/test_build_render_workflow.py
  tests/unit/test_render_manager.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_resolve_script_adapter_render_status.py
  tests/unit/test_resolve_script_adapter_render_cancel.py
  tests/unit/test_resolve_mock.py tests/unit/test_config.py
  tests/unit/test_composition.py tests/unit/test_db.py -q` - 199 passed.
- Mission 38A build preflight regression:
  `pytest tests/unit/test_cli_build.py -q` - 26 passed.
- Historical local Windows full unit suite:
  `pytest tests/unit -q` - 1236 passed, 9 skipped, and the same 24 accepted
  Windows YAML fixture failures.
- Published GitHub Actions CI for `origin/master` after the platform-neutral
  manifest-path assertion correction: 1268 passed, 1 skipped.
- Repository hygiene: `git diff --check`.

## Unreleased - Phase 14 Mission 38A: Build Preflight Before Mutable Composition

- Corrects the live-build preflight boundary discovered during the first
  Mission 38 production-like episode attempt: a missing `Episode_9001` manifest
  correctly failed, but full application composition had already initialized
  the default `redline.db`.
- Adds `redline_core.build.BuildPreflight` and immutable
  `PreparedBuildRequest` so `redline build` can parse the target, resolve the
  manifest path, load the manifest, and validate the manifest with
  configuration only.
- Adds `BuildOrchestrator.build_prepared(...)` so the CLI can hand off the
  already validated request after mutable application composition without
  loading or validating the manifest again.
- Updates CLI build dispatch so target, manifest resolution, manifest YAML,
  manifest schema, manifest media-path, and target/manifest identity failures
  occur before SQLite initialization, Resolve connection, or persistent logging
  artifact creation.
- Allows `build_application_services(...)` to reuse a preloaded
  `RedlineConfig`, preserving a single config object across preflight and full
  application composition.
- Does not change manifest policy, target syntax, episode manager policy,
  retry behavior, Resolve adapter behavior, render behavior, archive behavior,
  MCP behavior, database schema, or the accepted Windows YAML fixture failures.

### Verification

- Focused Mission 38A regression:
  `pytest tests/unit/test_cli_build.py tests/unit/test_build_orchestrator.py
  tests/unit/test_composition.py -q` - 50 passed.
- Related parser/manifest/build-render/render CLI regression:
  `pytest tests/unit/test_build_target.py tests/unit/test_manifest_resolution.py
  tests/unit/test_manifest_loader.py tests/unit/test_manifest_validator.py
  tests/unit/test_build_render_workflow.py tests/unit/test_cli_render.py -q` -
  135 passed, 2 skipped.
- Original live-run hygiene reproduction:
  `python -m cli.main build Episode_9001` - exit code 1 with missing-manifest
  failure; `Test-Path .\redline.db` and the isolated
  `REDLINE_LOG_DIR` check both returned `False`.
- Full accepted unit suite:
  `pytest tests/unit -q` - 1188 passed, 9 skipped, 24 accepted Windows YAML
  fixture failures.

## Unreleased - Phase 13 Mission 37: Documentation and Verification

- Closes Phase 13 through documentation alignment and verification evidence
  only.
- Updates README, architecture, roadmap, and build-command specification
  language so the documented command surfaces match implementation:
  `redline build TARGET [--manifest MANIFEST_PATH] [--force]` and
  `redline render {queue,status,list,cancel}`.
- Records that `redline build` remains assembly-only; render commands remain
  render-only; no combined CLI command exists in Phase 13.
- Records the implemented `BuildRenderWorkflow` boundary as transport-neutral
  sequencing from a successful `BuildResult` into one
  `RenderManager.queue_render(...)` call.
- Preserves the documented ownership boundaries: CLI parses transport inputs,
  `BuildOrchestrator` owns build-stage sequencing, existing manifest
  components own manifest policy, `EpisodeManager` owns episode/assembly
  policy, and `RenderManager` owns render policy.
- Does not change runtime code, CLI behavior, workflow sequencing,
  application composition, tests, retry policy, polling behavior, rollback,
  repair, archive behavior, SQLite access, Resolve access, or the accepted
  Windows YAML fixture failures.

### Verification

- Command help verified with Python 3.11 and `PYTHONPATH=src`:
  `python -m cli.main --help`; `python -m cli.main build --help`;
  `python -m cli.main render --help`; `python -m cli.main render queue --help`;
  `python -m cli.main render status --help`;
  `python -m cli.main render list --help`;
  `python -m cli.main render cancel --help`.
- Focused Phase 13 regression:
  `pytest tests/unit/test_build_orchestrator.py tests/unit/test_cli_build.py
  tests/unit/test_cli_render.py tests/unit/test_build_render_workflow.py
  tests/unit/test_composition.py -q` — 72 passed.
- Relevant render regression:
  `pytest tests/unit/test_render_manager.py tests/unit/test_resolve_mock.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_resolve_script_adapter_render_status.py
  tests/unit/test_resolve_script_adapter_render_cancel.py -q` — 103 passed.
- Full suite:
  `pytest tests/unit -q` — 1179 passed, 9 skipped, 24 accepted Windows YAML
  fixture failures.
- Repository hygiene: `git diff --check`, source-diff guard, documentation
  consistency searches, and `git status --short`.

## Unreleased - Phase 13 Mission 36: Build to Render Integration

- Adds `redline_core.workflows.BuildRenderWorkflow` as the transport-neutral
  build-to-render composition owner.
- Introduces immutable `BuildRenderResult`, containing the original successful
  `BuildResult` and the `RenderJob` returned by `RenderManager.queue_render(...)`.
- Wires `ApplicationServices` to expose one approved `BuildOrchestrator` and
  one `BuildRenderWorkflow` that reuses the same `EpisodeManager` and
  `RenderManager` instances already built by the composition root.
- Sequences `BuildOrchestrator.build(...)` exactly once before
  `RenderManager.queue_render(...)` exactly once. Render queueing occurs only
  after the build call returns successfully.
- Bridges only `BuildResult.target.episode_id` and the caller-supplied preset
  name into `RenderManager.queue_render(...)`; the workflow does not recompute
  targets, reload manifests, query persistence, inspect Resolve, derive project
  names, or evaluate render eligibility.
- Preserves existing build and render exceptions. Build failures prevent render
  invocation; render failures propagate after the successful build is preserved.
- Does not add a CLI command, alter standalone `redline build`, alter
  standalone `redline render`, archive, poll, retry, cancel automatically,
  roll back, repair, overwrite, access SQLite directly, call raw Resolve APIs,
  duplicate build policy, duplicate render policy, or repair unrelated Windows
  YAML fixtures.

### Verification

- Focused Mission 36 tests:
  `pytest tests/unit/test_build_render_workflow.py -q`.
- Mission 33-35 regression:
  `pytest tests/unit/test_build_orchestrator.py tests/unit/test_cli_build.py
  tests/unit/test_cli_render.py -q`.
- Relevant render regression:
  `pytest tests/unit/test_render_manager.py -q`.
- Composition regression:
  `pytest tests/unit/test_composition.py -q`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "sqlite3|DaVinciResolveScript|load_manifest|validate_manifest|archive|subprocess|Path\\.cwd|rollback|repair|overwrite|poll|retry"
  src/redline_core/workflows tests/unit/test_build_render_workflow.py`;
  `git diff -- src/cli/build_commands.py src/cli/render_commands.py`;
  `rg -n
  "ASSEMBLED|QUEUED|RENDERING|COMPLETED|FAILED|eligible|transition|retry|poll|cancel|rollback|repair|overwrite"
  src/redline_core/workflows`.

## Unreleased - Phase 13 Mission 35: CLI Render Surface

- Adds the top-level `redline render` CLI resource as a thin transport over
  the existing `RenderManager`.
- Exposes only render operations already supported by the manager:
  `render queue <episode_id> <preset_name>`, `render status <job_id>`,
  `render list <episode_id>`, and `render cancel <job_id>`.
- Routes render commands through the existing `ApplicationServices`
  composition path and uses `services.render_manager`; no composition change
  was required.
- Passes episode IDs, preset names, and Redline render-job database IDs through
  unchanged, with integer syntax validation for job IDs handled by argparse.
- Renders deterministic operator output for queue, status, list, and cancel
  results, including explicit build/archive exclusions for queue and cancel.
- Maps known render, episode, preset, and Resolve failures to exit code `1`
  with deterministic stderr messages while leaving unexpected failures to the
  existing top-level CLI guard and logger.
- Adds focused CLI tests for root registration, subcommand parsing, argument
  pass-through, single manager invocation, output formatting, zero-job listing,
  failure mapping, `--mock-resolve` composition pass-through, generic failure
  handling, and `redline build` render independence.
- Does not modify `redline build`, invoke `BuildOrchestrator`, parse or
  validate manifests, create episodes, assemble timelines, access SQLite
  directly, access raw Resolve APIs, duplicate render eligibility or state
  policy, add render-to-build coupling, archive, roll back, repair, overwrite,
  poll, retry, or repair unrelated Windows YAML fixtures.

### Verification

- Focused Mission 35 tests:
  `pytest tests/unit/test_cli_render.py -q`.
- Mission 34 regression:
  `pytest tests/unit/test_cli_build.py -q`.
- Mission 33 regression:
  `pytest tests/unit/test_build_orchestrator.py -q`.
- Relevant render regression:
  `pytest tests/unit/test_render_manager.py tests/unit/test_resolve_mock.py
  tests/unit/test_resolve_script_adapter_render_queue.py
  tests/unit/test_resolve_script_adapter_render_status.py
  tests/unit/test_resolve_script_adapter_render_cancel.py -q`.
- Help verification:
  `python -m cli.main --help`; `python -m cli.main render --help`;
  `python -m cli.main render queue --help`;
  `python -m cli.main render status --help`;
  `python -m cli.main render list --help`;
  `python -m cli.main render cancel --help`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "BuildOrchestrator|parse_build_target|resolve_manifest_path|load_manifest|validate_manifest|create_episode|build_episode|sqlite3|DaVinciResolveScript|archive|rollback|repair|overwrite|subprocess"
  src/cli/render_commands.py tests/unit/test_cli_render.py`;
  `rg -n "QUEUED|RENDERING|COMPLETED|FAILED|CANCELLED|eligible|transition|retry|poll"
  src/cli/render_commands.py`.

## Unreleased - Phase 13 Mission 34: CLI redline build

- Adds the top-level `redline build TARGET` CLI command as a thin transport
  over the existing `BuildOrchestrator`.
- Supports the approved `TARGET` argument, optional `--manifest` path, and
  `--force` flag. The CLI passes the target unchanged, passes the current
  working directory explicitly, passes `--manifest` through unchanged, and maps
  `--force` only to `allow_unsafe_retry=True`.
- Uses the existing `build_application_services(...)` composition path and
  creates `BuildOrchestrator` from approved application services.
- Renders deterministic operator output for the assembly-only build result,
  including target identity, manifest path, episode create/reuse status, final
  state, project and timeline names, media/marker/clip counts, warnings, and
  explicit `Render queued: no` / `Archive performed: no` lines.
- Maps known build, manifest, episode, and Resolve failures to exit code `1`
  with a deterministic stderr message while leaving unexpected failures to the
  existing top-level CLI guard and logger.
- Adds focused CLI tests for parser registration, argument pass-through,
  single orchestrator invocation, result rendering, warning rendering, failure
  mapping, service composition, and `main(...)` dispatch.
- Does not duplicate target parsing, manifest selection, manifest loading,
  manifest validation, identity checks, episode lifecycle policy, retry policy,
  assembly logic, persistence, Resolve behavior, render behavior, archive
  behavior, rollback, repair, overwrite behavior, or unrelated Windows YAML
  fixture repairs.

### Verification

- Focused Mission 34 tests:
  `pytest tests/unit/test_cli_build.py -q`.
- Phase 13 regression:
  `pytest tests/unit/test_build_target.py tests/unit/test_manifest_resolution.py
  tests/unit/test_build_orchestrator.py -q`.
- CLI help verification:
  `redline --help`; `redline build --help`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "parse_build_target|resolve_manifest_path|load_manifest|validate_manifest|get_episode_status|create_episode|build_episode|sqlite3|DaVinciResolveScript|render|archive|rollback|repair|overwrite|subprocess"
  src/cli/build_commands.py src/cli/main.py tests/unit/test_cli_build.py`.

## Unreleased - Phase 13 Mission 33: Build Orchestrator

- Adds a transport-neutral `redline_core.build.BuildOrchestrator` that
  coordinates the approved build stages from target parsing through episode
  assembly without adding CLI behavior.
- Introduces immutable build reporting types: `BuildResult`, `BuildStage`,
  `BuildOrchestrationError`, and `ManifestIdentityMismatchError`.
- Reuses the existing Phase 13 target parser and manifest resolver, the
  existing Episode Manifest loader and validator, and the existing
  `EpisodeManager` lookup, creation, and `build_episode(...)` APIs.
- Enforces the composition-level invariant that the validated manifest
  `episode.id` must match the target-derived episode ID before any episode
  lookup, creation, assembly, SQLite mutation, or Resolve work can occur.
- Delegates create/reuse eligibility, assembly claims, failed-state retry
  handling, terminal-state rejection, persistence transitions, and Resolve
  interactions to `EpisodeManager`.
- Passes `allow_unsafe_retry` through only to the existing
  `EpisodeManager.build_episode(..., allow_unsafe_retry=...)` parameter.
- Adds focused orchestration tests for new and existing episodes, explicit
  manifest pass-through, identity mismatch, manifest load/validation failures,
  episode creation failure, manager policy failure propagation, assembly
  failure propagation, unsafe-retry pass-through, and result immutability.
- Documents the build orchestration boundary in `docs/ARCHITECTURE.md`.
- Does not add a CLI command, render behavior, archive behavior, direct
  database access, raw Resolve access, rollback, repair, overwrite behavior,
  automatic retry, new force semantics, or unrelated Windows YAML fixture
  repairs.

### Verification

- Focused Mission 33 tests:
  `pytest tests/unit/test_build_orchestrator.py -q`.
- Phase 13 regression:
  `pytest tests/unit/test_build_target.py tests/unit/test_manifest_resolution.py -q`.
- Relevant manager/manifest regression:
  `pytest tests/unit/test_manifest_loader.py tests/unit/test_manifest_validator.py
  tests/unit/test_manifest_integration.py tests/unit/test_episode_manager.py -q`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "sqlite3|DaVinciResolveScript|argparse|typer|click|render|archive|sys\\.exit|subprocess|rollback|repair|overwrite"
  src/redline_core/build tests/unit/test_build_orchestrator.py`;
  `rg -n "ASSEMBLED|FAILED|RENDER|ARCHIVE|allow_unsafe_retry|state"
  src/redline_core/build/orchestrator.py`.

## Unreleased - Phase 13 Mission 32: Manifest Resolution

- Adds a pure `redline_core.build` manifest resolver that consumes an existing
  `BuildTarget`, an optional explicit manifest path, and an injected working
  directory to select exactly one Episode Manifest path.
- Introduces an immutable `ManifestResolution` result containing the normalized
  manifest path and resolution source (`explicit`, `default_yaml`, or
  `default_yml`).
- Adds deterministic `ManifestResolutionError` failures for invalid resolver
  inputs, invalid explicit manifest extensions, missing explicit paths,
  non-file explicit paths, invalid working directories, and missing default
  candidates.
- Applies the approved Phase 13 precedence: explicit manifest paths win over
  defaults; otherwise `<target>.yaml` is checked before `<target>.yml`, and
  `.yaml` wins when both regular files exist.
- Adds focused filesystem-selection tests for explicit paths, default
  candidates, source reporting, path normalization, immutability, type checks,
  working-directory checks, and original-target filename derivation.
- Clarifies `docs/BUILD_COMMAND_SPEC.md` so the default `.yaml`/`.yml`
  behavior matches the approved Mission 32 precedence.
- Does not load YAML, parse manifest documents, validate schemas, compare
  manifest identity, create or reuse episodes, call managers, access SQLite,
  connect Resolve, add CLI behavior, render, archive, or repair unrelated
  Windows YAML fixtures.

### Verification

- Focused Mission 32 tests:
  `pytest tests/unit/test_manifest_resolution.py -q`.
- Mission 31 regression:
  `pytest tests/unit/test_build_target.py -q`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "yaml|sqlite|Resolve|EpisodeManager|ApplicationServices|CoreServices|argparse|typer|click|render|archive|open\\("
  src/redline_core/build tests/unit/test_manifest_resolution.py`.

## Unreleased - Phase 13 Mission 31: Build Target Parsing

- Adds a pure `redline_core.build` target parser for canonical Phase 13 build
  targets such as `Episode_0001`.
- Introduces an immutable `BuildTarget` result containing the original target,
  normalized episode number, and canonical episode ID derived from the supplied
  `NamingConfig`.
- Rejects non-canonical targets deterministically through `BuildTargetError`,
  including wrong case, missing or extra digits, extensions, path-like inputs,
  whitespace, non-digit suffixes, and `Episode_0000`.
- Adds focused parser tests covering valid targets, invalid syntax, number
  policy, immutability, supplied naming configuration, and non-mutation of the
  naming configuration.
- Anchors the root build-artifact ignore rule so the new `redline_core.build`
  source package is visible to Git.
- Does not add filesystem access, manifest resolution, YAML loading, CLI
  commands, manager calls, SQLite access, Resolve access, render behavior,
  archive behavior, orchestration, dependencies, or Windows YAML fixture
  repairs.

### Verification

- Focused Mission 31 tests:
  `pytest tests/unit/test_build_target.py -v`.
- Scope verification:
  `git diff --check`; `git diff --stat`; `git diff`; `git status --short`;
  `rg -n
  "Path|open\\(|yaml|sqlite|Resolve|EpisodeManager|ApplicationServices|CoreServices|argparse|typer|click|os\\.environ|getenv|render|archive"
  src/redline_core/build tests/unit/test_build_target.py`.

## Unreleased - Phase 13 Mission 30: Canonical Build Command Specification

- Adds `docs/BUILD_COMMAND_SPEC.md` as the canonical Phase 13 contract for
  `redline build Episode_0001`.
- Defines the initial build command as a production composition boundary that
  parses an `Episode_0001` target, resolves and validates an Episode Manifest
  V1 file, creates or reuses the episode through existing manager policy, and
  stops after successful assembly.
- Records the canonical decisions for target syntax and normalization,
  manifest resolution, create/reuse semantics, build stages, ownership
  boundaries, dedicated build orchestration, render exclusion, archive
  exclusion, success/failure contracts, re-execution semantics, and minimum
  result requirements.
- Maps Missions 31-37 to the approved build contract and updates the roadmap:
  Phase 12 is complete, Phase 13 is in progress, and Mission 30 is complete.
- Does not change runtime code, tests, scripts, MCP tools, Resolve behavior,
  manager policy, database schema, deployment behavior, CI, or the accepted
  Windows YAML fixture failures.

### Verification

- Documentation/specification verification:
  `git diff --check`; `git diff --stat`; `git diff --
  docs/BUILD_COMMAND_SPEC.md docs/ROADMAP.md docs/CHANGELOG.md README.md
  docs/ARCHITECTURE.md`; `rg -n
  "redline build|Episode_0001|manifest|orchestrat|render|archive|idempoten|force|result|Phase 13|Mission 30"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 30 changes only architecture and
  specification documentation.

## Unreleased - Phase 12 Mission 29: Align CI Workflow With Canonical Release Branch

- Updates `.github/workflows/ci.yml` so the existing CI workflow runs for
  `push` and `pull_request` events targeting the canonical `master` branch.
- Preserves the existing workflow name, mocked unit-test job, Python version,
  editable development install, pytest command, and coverage arguments.
- Updates the roadmap while keeping Phase 12 in progress.
- Does not add release publishing, artifact uploads, package builds, deployment
  jobs, matrix testing, new operating systems, new Python versions, dependency
  changes, linting, formatting checks, security scanning, runtime code, tests,
  architecture updates, release tagging, or Windows YAML fixture repairs.

### Verification

- Workflow/configuration verification:
  `git diff --check`; `git diff --stat`; `git diff --
  .github/workflows/ci.yml docs/CHANGELOG.md docs/ROADMAP.md`;
  `Get-Content .github/workflows/ci.yml`; `rg -n
  "main|master|branches:" .github/workflows/ci.yml docs/ROADMAP.md
  docs/CHANGELOG.md`; `git status --short`.
- No unit tests were required because Mission 29 changes only CI branch
  configuration and mission documentation.

## Unreleased - Phase 12 Mission 28: Production Workstation Deployment Documentation

- Adds `docs/DEPLOYMENT.md` as the canonical production-workstation deployment
  runbook for the existing installed workflow verified by Missions 22-27.
- Documents supported workstation assumptions, Python and DaVinci Resolve Studio
  prerequisites, wheel installation, MCP optional-dependency installation,
  configuration/database/log locations, Resolve scripting variables, CLI and
  MCP verification, deployment evidence, and known deployment limitations.
- Links the deployment guide from `README.md` and updates the roadmap while
  keeping Phase 12 in progress.
- Does not add package publishing, installers, deployment automation, service
  wrappers, containers, release pipelines, rollback mechanisms, upgrade policy,
  troubleshooting procedures, CI changes, production code changes, tests, or
  Windows YAML fixture repairs.

### Verification

- Documentation-only verification:
  `git diff --check`; `git diff --stat`; `rg
  "deploy|deployment|workstation|wheel|REDLINE_CONFIG_DIR|REDLINE_DB_PATH|REDLINE_LOG_DIR|redline-mcp|Resolve"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 28 changes documentation only.

## Unreleased - Phase 12 Mission 27: Recovery and Restart Runbook Documentation

- Adds `docs/RECOVERY.md` as the canonical operator runbook for process
  interruption, failed episode assembly, persisted assembly claims, partial
  Resolve mutations, safe `--force` usage, render recovery states,
  SQLite/Resolve drift, and evidence preservation.
- Distinguishes persisted Redline state inspection from external Resolve state
  inspection, normal retry from forced retry, and operator review from manual
  SQLite mutation. Direct SQLite mutation is explicitly not documented as a
  routine recovery procedure.
- Links the runbook from `README.md` and corrects the MCP tools reference's
  stale real-Resolve verification wording without changing MCP behavior.
- Does not change production code, tests, retry policy, rollback behavior,
  reconciliation behavior, deployment guidance, upgrade policy, CI, or the
  known Windows YAML fixture failures.

### Verification

- Documentation-only verification:
  `git diff --check`; `git diff --stat`; `rg
  "rollback|retry|force|assembly claim|restart|recovery|Resolve|SQLite|render"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 27 changes documentation only.

## Unreleased - Phase 12 Mission 26: First-Run Installed Operator Workflow Documentation

- Documents the first-run installed operator workflow now verified by Missions
  22-25: install from a built wheel or package, select isolated config,
  database, and log paths, verify the installed CLI with `redline asset list`,
  and verify MCP startup with `redline-mcp --mock-resolve`.
- Separates installed operator usage from editable development setup. The docs
  keep `pip install -e`, `scripts/bootstrap_db.py`, and
  `python -m mcp_server.server` as source-checkout instructions only, and state
  that installed operators do not need `PYTHONPATH=src`.
- Clarifies when mock Resolve is appropriate for startup and client wiring, and
  when a real DaVinci Resolve Studio session plus Resolve scripting environment
  variables are required.
- Does not change production code, tests, CLI commands, MCP behavior, database
  schema, recovery policy, deployment policy, upgrade policy, CI, or the known
  Windows YAML fixture failures.

### Verification

- Documentation-only verification:
  `git diff --check`; `git diff --stat`; `rg
  "pip install -e|scripts/bootstrap_db.py|python -m mcp_server.server|PYTHONPATH"
  README.md docs`; `git status --short`.
- No unit tests were required because Mission 26 changes documentation only.

## Unreleased - Phase 12 Mission 25: Installed MCP Startup Smoke Verification

- Adds an installed MCP startup smoke test that builds the Redline OS wheel,
  installs it into an isolated temporary virtual environment, and verifies the
  installed MCP startup path from a working directory outside the repository
  checkout.
- Verifies Redline OS's wheel metadata declares the `mcp` optional dependency
  extra and uses a deterministic local MCP test wheel so the smoke does not
  silently depend on developer-environment packages or network access.
- Confirms installed startup without `PYTHONPATH=src`: the smoke imports
  `mcp_server.server`, finds the installed `redline-mcp` console script,
  initializes logging, loads an isolated config directory, initializes a
  temporary SQLite database, composes `ApplicationServices` with
  `MockResolveAdapter`, creates the FastMCP server, and observes all 18 expected
  tool registrations.
- Does not call `mcp.run()`, connect to live Resolve, change MCP tools, alter
  CLI behavior, modify database schema, redesign bootstrap, or repair the known
  Windows YAML fixture failures.

### Verification

- Focused Mission 25 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_mcp_startup_smoke.py -q` -> 1 passed.
- Targeted installed/MCP regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_mcp_startup_smoke.py
  tests\unit\test_mcp_tools.py tests\unit\test_installed_wheel_smoke.py -q`
  -> 55 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1073
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 25 adds no new full-suite failures.

## Unreleased - Phase 12 Mission 24: Installed Non-Help CLI Smoke Verification

- Adds an installed CLI smoke test that builds the Redline OS wheel, installs it
  into an isolated temporary virtual environment, and runs the installed
  `redline asset list` console entrypoint from a working directory outside the
  repository checkout.
- Verifies non-help operator startup without `PYTHONPATH=src`: the command loads
  an isolated config directory through `REDLINE_CONFIG_DIR`, initializes logging
  through `REDLINE_LOG_DIR`, composes `CoreServices`, delegates to
  `AssetManager.list_available_assets()`, returns expected asset-list output,
  and exits with code 0.
- Confirms the smoke path does not require `REDLINE_DB_PATH`, create a
  `redline.db` in the command working directory, connect to Resolve, add a new
  CLI command, touch MCP startup, or duplicate asset-list policy.

### Verification

- Focused Mission 24 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_cli_asset_list_smoke.py -q` -> 1 passed.
- Targeted installed-smoke regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_cli_asset_list_smoke.py
  tests\unit\test_installed_wheel_smoke.py
  tests\unit\test_installed_db_bootstrap_smoke.py -q` -> 3 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1072
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 24 adds no new full-suite failures.

## Unreleased - Phase 12 Mission 23: Installed Database Bootstrap Verification

- Adds an installed-package database bootstrap smoke test that builds the
  Redline OS wheel, installs it into an isolated temporary virtual environment,
  runs from a working directory outside the repository checkout, imports
  `Database` from the installed package, and initializes a temporary SQLite
  database through `Database.connect()` and `Database.init_schema()`.
- Verifies the canonical core tables (`episodes`, `render_jobs`, and
  `archives`) through SQLite metadata after initialization. The smoke path does
  not execute `scripts/bootstrap_db.py`, use `PYTHONPATH=src`, connect to
  Resolve, add a public bootstrap command, or duplicate schema SQL.
- Preserves database ownership in `redline_core.db`; scripts and transports
  remain operational entrypoints only.

### Verification

- Focused Mission 23 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_db_bootstrap_smoke.py -q` -> 1 passed.
- Targeted installed/bootstrap/resource regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_db_bootstrap_smoke.py
  tests\unit\test_installed_wheel_smoke.py
  tests\unit\test_db_schema_resource.py -q` -> 7 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1071
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 23 adds no new full-suite failures.

## Unreleased - Phase 12 Mission 22: Installed Wheel Smoke Verification

- Adds an installed-wheel smoke test that builds the Redline OS wheel, installs
  it into an isolated temporary virtual environment, and verifies behavior from
  a working directory outside the repository checkout.
- The smoke test confirms that the installed `redline_core` package imports,
  `redline_core.db/schema.sql` and `redline_core.asset/schema.sql` are readable
  through package resources, and the installed `redline` console entrypoint
  exists and runs `redline --help`.
- The test avoids Resolve-dependent commands, global environment mutation, new
  build dependencies, schema changes, bootstrap redesign, CLI/MCP redesign, and
  Windows YAML fixture repair. `redline --help` is used as the console smoke
  command because argparse exits before any config, database, logging, or
  Resolve startup side effects.

### Verification

- Focused Mission 22 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_wheel_smoke.py -q` -> 1 passed.
- Targeted packaging/database/composition regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_installed_wheel_smoke.py
  tests\unit\test_db_schema_resource.py tests\unit\test_composition.py -q`
  -> 17 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1070
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 22 adds no new full-suite failures.
- The smoke test first attempts `python -m pip wheel ... --no-deps
  --no-build-isolation`; on this workstation that path reports
  `invalid command 'bdist_wheel'` because the active interpreter does not
  provide the wheel build command. It then falls back to pip's existing PEP 517
  isolated wheel build, still with `--no-deps`, and verifies the built wheel
  archive contains both packaged SQL resources before installing it into the
  temporary virtual environment.

## Unreleased - Phase 12 Mission 21: Package Core DB Schema Resource

- Moves `Database.init_schema()` from a source-tree-relative
  `Path(__file__).parent / "schema.sql"` lookup to the packaged
  `redline_core.db` resource boundary via `importlib.resources.files()`.
- Adds `redline_core.db/schema.sql` to setuptools package data so the core
  SQLite schema is available in editable installs, wheels, and packaged
  deployments.
- Preserves the existing schema SQL, initialization flow, automatic
  `assembly_claim_*` migration, commit behavior, and visible exception
  behavior. Missing or unreadable schema resources still raise from the
  resource/database boundary instead of being silently repaired or wrapped in a
  new policy type.
- Does not modify SQL schema contents, introduce schema versioning, add
  migrations, redesign database bootstrap, change CLI/MCP contracts, alter
  Resolve behavior, publish packages, or repair the known Windows YAML fixture
  failures.

### Verification

- Focused Mission 21 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_db_schema_resource.py -q` -> 5 passed.
- Targeted DB/composition/bootstrap regression was run with the PowerShell-
  expanded `tests\unit\test_db*.py`, `tests\unit\test_composition*.py`, and
  `tests\unit\test_bootstrap*.py` file list -> 37 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1069
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 21 adds no new full-suite failures.
- `python -m build` could not be used in this environment because the `build`
  module is not installed. A temporary no-dependency wheel was built with
  `python -m pip wheel . --no-deps`; inspecting the wheel confirmed both
  `redline_core/asset/schema.sql` and `redline_core/db/schema.sql` are
  included.

## Unreleased - Phase 12 Mission 20: Logging and Diagnostics Baseline

- Hardens `redline_core.logging.setup.configure_logging()` without changing the
  logging architecture or startup callers. CLI and MCP continue to pass only
  `REDLINE_LOG_DIR` and `REDLINE_LOG_LEVEL` values into the shared logging
  boundary.
- Repeated configuration now replaces only Redline-owned console/file handlers,
  identified by an internal ownership marker, so pytest, embedding
  applications, and third-party libraries can keep unrelated handlers attached
  to the `redline_os` logger.
- Invalid log levels now raise `LoggingConfigurationError` deterministically.
  Supported configured levels remain the documented `DEBUG`, `INFO`, `WARNING`,
  and `ERROR`, with case-insensitive input. Directory creation and file-handler
  failures remain visible and are not swallowed.
- Documents default level, console behavior, file logging path resolution,
  directory creation, invalid-level startup failures, and basic operator
  diagnostics in `README.md` and `docs/CONFIG.md`.
- Does not add JSON logging, retention policy, redaction, telemetry, tracing,
  packaging changes, deployment scripts, recovery workflows, Resolve changes,
  database changes, CLI/MCP feature expansion, or Windows YAML fixture repair.

### Verification

- Focused Mission 20 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_logging_setup.py -q` -> 14 passed.
- Targeted logging/CLI/MCP startup regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_logging_setup.py tests\unit\test_cli*.py
  tests\unit\test_mcp*.py -q` was attempted, but pytest received the wildcard
  literally in this PowerShell environment. Re-running with the PowerShell-
  expanded file list completed with 185 passed and 24 failed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1064
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 20 adds no new full-suite failures.

## Unreleased - Phase 11 Mission 19: MCP `assemble_episode`

- Adds the MCP `assemble_episode(...)` tool as a thin transport wrapper over
  the existing `EpisodeManager.build_episode()` assembly owner. The tool
  accepts the manager's explicit assembly inputs (`episode_id`, ordered
  `media_paths`, optional marker dicts, `bin_name`, and
  `allow_unsafe_retry`) and constructs the existing `EpisodeBuildDefinition`
  domain input before making exactly one high-level assembly call.
- Serializes the existing `EpisodeBuildResult` fields used by the CLI assembly
  path: `episode_id`, `project_name`, `timeline_name`, `media_paths`,
  `media_ids`, `markers_applied`, and `timeline_item_ids`.
- Does not load or validate manifests, verify assets, import media directly,
  build timelines directly, place clips directly, queue renders, write SQLite
  directly, call Resolve directly, or introduce retry behavior. Assembly order,
  validation, retry policy, persistence, and Resolve interactions remain owned
  by `EpisodeManager.build_episode()`.
- Known `EpisodeBuildError` failures return the neighboring episode-tool
  structured envelope: `{"success": False, "error": "..."}`. Unexpected
  non-assembly exceptions are not broadly wrapped.

### Verification

- Focused Mission 19 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -k "assemble_episode" -q` -> 11 passed, 42
  deselected.
- Full MCP tool tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -q` -> 53 passed.
- Targeted episode/MCP regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py tests\unit\test_episode_manager.py -q` -> 105
  passed. The originally requested `tests\unit\test_episode*.py` wildcard form
  was also attempted, but pytest received it literally in this PowerShell
  environment.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1050
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 19 adds no new full-suite failures.

## Unreleased - Phase 11 Mission 18: MCP `validate_manifest`

- Adds the MCP `validate_manifest(manifest_path)` tool as a thin transport
  wrapper over the existing `redline_core.manifest.load_manifest()` and
  `validate_manifest()` public API. The MCP layer passes the manifest path
  through unchanged and serializes the resulting `ValidatedEpisodePlan`.
- The success response is deterministic and includes `manifest_path`, `valid`,
  `episode_id`, `bin_name`, resolved `media_paths`/`media_count`, and
  `markers`/`marker_count`. Manifest loading, duplicate-key rejection, schema
  validation, path containment, and UNC-path handling remain owned by
  `redline_core.manifest`.
- Known manifest failures return the neighboring episode-tool structured
  envelope: `{"success": False, "error": "..."}`. Unexpected non-manifest
  exceptions are not broadly wrapped. The tool performs no episode creation,
  assembly, SQLite writes, manager calls, Resolve calls, or manifest repair.

### Verification

- Focused Mission 18 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -k "validate_manifest" -q` -> 12 passed, 30
  deselected.
- Full MCP tool tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -q` -> 42 passed.
- Targeted MCP/manifest regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py tests\unit\test_manifest_loader.py
  tests\unit\test_manifest_validator.py tests\unit\test_manifest_integration.py
  -q` -> 102 passed, 2 skipped. The originally requested
  `tests\unit\test_manifest*.py` wildcard form was also attempted, but pytest
  received it literally in this PowerShell environment.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1039
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 18 adds no new full-suite failures.

## Unreleased - Phase 11 Mission 17: MCP `place_clips`

- Adds the MCP `place_clips(project_name, timeline_name, clip_ids)` tool as a
  thin transport wrapper over the existing `TimelineBuilder.place_clips()`
  capability. The tool preserves the builder contract and serializes the
  returned TimelineItem IDs as `timeline_item_ids` with a deterministic
  `placed_count`.
- Basic MCP transport-shape validation rejects missing primitive inputs and
  malformed `clip_ids` before delegation. Empty clip lists are delegated to the
  builder so existing timeline placement policy remains centralized.
- The tool does not resolve clip IDs, import media, select timelines, write to
  SQLite, call the Resolve adapter directly, or duplicate clip-placement policy.
  Timeline-builder domain exceptions follow the neighboring timeline-tool
  behavior and are not broadly wrapped.

### Verification

- Focused Mission 17 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -k "place_clips" -q` -> 9 passed, 21
  deselected.
- Full MCP tool tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py -q` -> 30 passed.
- Targeted timeline/MCP regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_mcp_tools.py
  tests\unit\test_resolve_script_adapter_clip_placement.py -q` -> 93 passed.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1027
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 17 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 16: real Resolve `cancel_render`

- Implements `ResolveScriptAdapter.cancel_render(resolve_job_id) -> None` for
  real Resolve, preserving the existing public adapter contract. The lookup is
  scoped to the currently loaded Resolve project and leaves `RenderManager`,
  SQLite, CLI, and MCP contracts unchanged.
- Queued renders are cancelled through `Project.DeleteRenderJob(job_id)`.
  Resolve Studio 21.0.3.7 returns `True` for a known queued job, removes the
  job from the render queue, and makes `GetRenderJobStatus(job_id)` return
  `None`; unknown jobs return `False` and are reported as `RenderJobError`.
- Active renders are cancelled through project-scoped `Project.StopRendering()`
  only after Redline verifies that the requested job is the sole active render.
  `StopRendering()` returns `None` on Resolve Studio 21.0.3.7, so success is
  verified through postconditions: `IsRenderingInProgress()` becomes `False`
  and the requested job's `JobStatus` becomes `Cancelled`.
- A successfully stopped active job is intentionally left in Resolve's render
  queue with status `Cancelled`. Redline does not delete it automatically
  because queue cleanup is separate from cancellation and a post-stop delete
  failure could leave SQLite inconsistent with Resolve.
- Terminal statuses (`Complete`, `Failed`, `Cancelled`, and `Canceled`) are
  rejected with `RenderJobError`, matching the existing mock policy even though
  live probing showed Resolve permits deleting completed queue entries.
- Adds focused fake-Resolve unit coverage in
  `tests/unit/test_resolve_script_adapter_render_cancel.py`.

### Verification

- Focused Mission 16 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_cancel.py -q` -> 29 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_cancel.py
  tests\unit\test_resolve_script_adapter_render_status.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py -q` ->
  103 passed.
- Live adapter-level verification against disposable project
  `redline-os-test-duplicate` confirmed queued cancellation removes a `Ready`
  job and active cancellation transitions a `Rendering` job to `Cancelled`
  without deleting it automatically. The probe-created active queue entry was
  deleted afterward as manual cleanup.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 1018
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 16 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 15: real Resolve `get_render_status`

- Implements `ResolveScriptAdapter.get_render_status(resolve_job_id) -> str`
  for real Resolve, preserving the existing public adapter contract. The lookup
  is scoped to the currently loaded Resolve project through
  `ProjectManager.GetCurrentProject()` and uses
  `Project.GetRenderJobStatus(resolve_job_id)` as the authoritative live-status
  API.
- Live API probing on Resolve Studio 21.0.3.7 confirmed that
  `GetRenderJobList()` returns render-job inventory and metadata but does not
  include live status. `GetRenderJobStatus(job_id)` returns a dictionary
  containing `JobStatus` and `CompletionPercentage` for known jobs and `None`
  for unknown jobs.
- Maps verified/approved Resolve statuses to Redline strings: `Ready` ->
  `queued`, `Rendering` -> `rendering`, `Complete` -> `complete`, `Failed` ->
  `failed`, and both `Cancelled`/`Canceled` -> `cancelled`. Unknown
  well-formed statuses return `unknown`, so `RenderManager` preserves the
  stored DB status instead of guessing.
- Rejects empty/non-string job IDs, missing current projects, malformed known
  job responses, and unavailable project managers with `RenderJobError` or
  `ResolveConnectionError` as appropriate. Unexpected Resolve API exceptions
  are wrapped in `RenderJobError` with the original exception preserved as
  `__cause__`.
- Adds focused fake-Resolve unit coverage in
  `tests/unit/test_resolve_script_adapter_render_status.py`. No manager,
  database, CLI, MCP, polling, progress persistence, project-searching, or
  cancellation behavior changed.
- At Mission 15 close, the remaining Phase 10 real-Resolve gap was
  `cancel_render`; Mission 16 resolves that gap.

### Verification

- Focused Mission 15 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_status.py -q` -> 28 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_status.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py -q` ->
  74 passed.
- Live adapter-level verification against disposable project
  `redline-os-test-duplicate` and Resolve job
  `6ac314da-9c99-41eb-bf79-621e5f6b7edc` returned `queued`.
- Full `tests\unit` was executed with Python 3.11.9 and completed with 989
  passed, 9 skipped, and 24 failed. The failure set remains the known
  unrelated Windows YAML fixture portability defect described in Mission 14;
  Mission 15 adds no new full-suite failures.

## Unreleased - Phase 10 Mission 14: real Resolve `queue_render`

- Implements `ResolveScriptAdapter.queue_render(project_name, preset_name,
  output_path) -> str` for real Resolve. This is enqueue-only: it applies the
  named Resolve render preset, applies the output directory through
  `SetRenderSettings({"TargetDir": ...})`, adds exactly one render job with
  `AddRenderJob()`, and returns the Resolve render job ID. It does not start
  rendering, poll status, cancel jobs, add CLI commands, change MCP contracts,
  add manifest render sections, or alter `RenderManager` policy.
- Adds a documented adapter boundary in `docs/ARCHITECTURE.md` before the
  production-code change. `RenderJobError` remains the domain-specific render
  failure type. Unexpected Resolve API exceptions are wrapped as
  `RenderJobError` with the original exception preserved as `__cause__`.
- Handles Resolve's version-sensitive `AddRenderJob()` return shape without
  guessing: if `AddRenderJob()` returns a usable scalar ID (`str` or `int`),
  that ID is returned directly; otherwise the adapter compares
  `GetRenderJobList()` snapshots from before and after queueing and accepts
  exactly one newly appeared job ID. Missing, duplicate, or ambiguous
  candidates raise `RenderJobError`. If a job was queued but ID extraction or
  reconciliation fails, no automatic rollback or deletion is attempted; manual
  Resolve/SQLite reconciliation may be required.
- Failure boundaries covered explicitly: disconnected adapter, unknown project,
  empty preset name, preset-load rejection, output-setting rejection,
  `AddRenderJob()` rejection, missing job ID, ambiguous job ID, and unexpected
  Resolve API exceptions. Logging includes project/preset/job context without
  unnecessarily exposing full output filesystem paths.

### Verification

- Focused Mission 14 tests:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_resolve_script_adapter_render_queue.py` -> 15 passed.
- Targeted Resolve/render regression:
  `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe -m pytest
  tests\unit\test_render_manager.py tests\unit\test_resolve_mock.py
  tests\unit\test_resolve_script_adapter_import_media.py
  tests\unit\test_resolve_script_adapter_timeline.py
  tests\unit\test_resolve_script_adapter_clip_placement.py
  tests\unit\test_resolve_script_adapter_render_queue.py
  tests\unit\test_mcp_tools.py` -> 192 passed.
- Live verification passed on 2026-07-29 with DaVinci Resolve Studio
  21.0.3.7 and Python 3.11.9 against the disposable
  `redline-os-test-duplicate` project, built-in `YouTube - 720p` preset, and
  `C:\Users\pj198\Documents\redline-os\.artifacts\render-tests` output
  directory. `AddRenderJob()` returned
  `6ac314da-9c99-41eb-bf79-621e5f6b7edc`, and the post-call
  `GetRenderJobList()` contained exactly one job with that same `JobId`.
  `get_render_status` and `cancel_render` remain unimplemented for real
  Resolve.

### Known unrelated regression limitation

- Full `tests\unit` was executed with Python 3.11.9 and completed with 961
  passed, 9 skipped, and 24 failed. The failures are pre-existing CLI
  end-to-end fixture portability defects: Windows paths are embedded in
  double-quoted YAML, causing PyYAML to interpret sequences such as `\U` as YAML
  escapes. Mission 14 does not change the affected CLI fixtures or YAML-
  generation logic. Repair is deferred to a separate focused maintenance
  mission.

## Unreleased - Phase 9 Mission 13: `redline episode assemble` CLI + atomic assembly claim

- Adds `redline episode assemble <manifest_path> [--force]` — the mutating
  counterpart to Mission 12's `validate-manifest`, and the first CLI action
  to reach `EpisodeManager.build_episode()`. A thin wrapper over the
  existing `load_manifest()` -> `validate_manifest()` ->
  `.to_build_definition()` -> `build_episode()` pipeline. Routed through
  `ApplicationServices`, the same composition tier as every other mutating
  `episode` action — no `cli/main.py` dispatch change needed, unlike
  Mission 12.
- Preceded by `docs/adr/ADR-0001-episode-assembly-retry-policy.md`, the
  project's first ADR: found that the existing rerun guard (an in-memory
  `_unsafe_rerun_episode_ids` set) provided zero protection through the CLI
  transport, since a fresh `EpisodeManager` is constructed on every CLI
  invocation. Replaced with an atomic, persisted assembly claim.
- `redline_core` changes (the first this Phase 9 initiative has required):
  - `schema.sql` / `database.py`: two new nullable `episodes` columns,
    `assembly_claim_token` and `assembly_claimed_at`, added via a new
    `Database._migrate_add_assembly_claim_columns()` migration (runs from
    `init_schema()`, no try/except — a failed migration fails application
    startup outright, per ADR-0001's explicit migration-failure policy).
    New `Database.claim_episode_for_assembly(episode_id, claim_token, *,
    allow_unsafe_retry=False) -> bool` and
    `Database.release_assembly_claim(episode_id, claim_token, status)`
    (token-owned: only releases a claim matching the caller's own token).
  - `episode/manager.py`: `build_episode()` gained a keyword-only
    `allow_unsafe_retry: bool = False` parameter (CLI's `--force` maps to
    it). `_get_existing_episode_for_build()` replaced with
    `_claim_episode_for_build()`, which claims the episode atomically
    before any Resolve mutation begins and threads the resulting
    `claim_token` through every `_build_error()` call site. The old
    in-memory `_unsafe_rerun_episode_ids` set is gone entirely.
  - `db/models.py`: `Episode` gained `assembly_claim_token` /
    `assembly_claimed_at` fields (and `from_row()` reads them), so the
    claim state the schema/database layer added is actually readable back
    through the model — caught and fixed during this mission's own test
    writing, not part of the original #46/#47 slices.
- **Two correctness issues found in review before this mission was
  committed, both fixed prior to commit:**
  1. The originally proposed forced-claim `UPDATE` guarded only by `status
     NOT IN (terminal...)`, with no dependency on the existing claim token
     at all — so two concurrent forced (`--force`) callers racing the same
     dangling claim could both satisfy that guard and both acquire it,
     violating ADR-0001's single-claimant invariant. Fixed by replacing it
     with `Database._claim_episode_for_assembly_cas()`: a diagnostic
     `SELECT` of the current `(status, assembly_claim_token)`, followed by
     a compare-and-swap `UPDATE` whose `WHERE` clause is pinned to exactly
     that observed pair (`IS NULL` when the observed token is `None`). The
     `SELECT` authorizes nothing; the guarded `UPDATE`'s rowcount remains
     the sole authority on acquisition. A genuinely sequential second
     forced call (one that freshly observes the first's already-committed
     token) can still legitimately take over — that's an operator issuing
     `--force` twice with accurate current information, not a race, and is
     not what this guards against.
  2. `release_assembly_claim()` originally logged an error and returned
     silently when no row matched the given token (rowcount 0) — on the
     success path, this could let `build_episode()` return an
     `EpisodeBuildResult` even though the episode was never actually
     marked `assembled` and the claim was never actually cleared. Fixed:
     `release_assembly_claim()` now raises a new
     `AssemblyClaimReleaseError` on a rowcount-0 release. Both existing
     call sites already had `except Exception` handling (the final
     success-path release, and `_build_error()`'s own failure-cleanup
     release), so this converts correctly into `EpisodeBuildError` (stage
     `status_update`) without needing new branching logic at either site.
- Full exhaustive status matrix enforced by `_claim_episode_for_build()`:
  `created`/`assets_verified`/`media_organized`/`timeline_built` claimable
  normally; `failed` and an active/unresolved claim from a prior attempt
  blocked without `--force`, claimable with it; `assembled`/
  `render_queued`/`rendered`/`archived` always blocked, no override under
  any flag, ever.
- `--force` is a pure transport-vocabulary translation, not a policy
  decision: the CLI passes it straight through as `allow_unsafe_retry` and
  never inspects episode status or claim state itself. The `--force`
  warning banner prints whenever the flag was passed, before checking the
  result, including on a failed (e.g. terminal-status-blocked) attempt.
- New tests: 15 DB-level tests (`test_db.py` — claim/release/token-owned-
  release/migration-idempotency/legacy-table-upgrade, plus 5 added for the
  CAS correctness fix: two racers on the same dangling claim resulting in
  exactly one success, a second racer failing against already-superseded
  state, `IS NULL` handling for a never-claimed episode, and terminal
  status rejected without attempting the update), 11 new `EpisodeManager`
  tests plus 3 rewritten ones (`test_episode_manager.py` — full status
  matrix, dangling-claim block/override, forced-retry-after-failure, plus
  2 added for the release-failure fix: a real (non-monkeypatched) token
  mismatch during the final release converts to `EpisodeBuildError`
  instead of a success result, and a positive proof that the claim is
  durably committed — visible via a second, independent DB connection —
  before `MediaManager.import_media()` runs), and 14 new CLI tests
  (`test_cli_episode_assemble.py` — success/failure payload shapes,
  `--force` warning banner, argument parsing, and an in-process `main()`
  end-to-end proof that `--force` actually unblocks a `FAILED` episode
  through the real CLI entry point). Full suite: 978 passed, 1 skipped (up
  from Mission 12's 938 passed, 1 skipped).
- **Phase 9 (Episode Production Pipeline) is now complete.** A post-
  implementation gap review found no remaining capability: `redline_core.manifest`'s
  entire public surface (`load_manifest()`, `validate_manifest()`) is called
  from the CLI (`validate-manifest` directly; `assemble` via
  `.to_build_definition()`), and `EpisodeManager.build_episode()` is now
  CLI-reachable via `assemble`. See `docs/ROADMAP.md`'s Phase 9 row.
- Manual smoke test: an in-process script sharing one `MockResolveAdapter`
  across sequential `main()` invocations (required, since the mock adapter
  is in-memory only and separate CLI processes don't share it) verified,
  against the real CLI entry point: a successful assemble; an ordinary
  retry blocked by the now-`assembled` terminal status; the same retry
  still blocked with `--force` (terminal statuses are never overridable);
  a `FAILED` episode blocked without `--force`; and the same episode
  successfully retried with `--force`. Repo working tree stayed clean
  throughout.

## Unreleased - Phase 9 Mission 12: `redline episode validate-manifest` CLI

- Adds `redline episode validate-manifest <manifest_path>` as an eighth
  `episode` action — the first Phase 9 mission, per the approved Phase 9
  Architecture Proposal and Mission 12 Implementation Contract. A thin,
  read-only wrapper over the existing, already-tested
  `redline_core.manifest.load_manifest()` and `.validate_manifest()`. No
  `redline_core` code changed: `EpisodeManager`, `TimelineBuilder`,
  `MediaManager`, `AssetManager`, `ArchiveManager`, the Resolve adapter,
  and the manifest loader/validator/models are all unmodified.
- Routed through `CoreServices`, not `ApplicationServices` — the first
  `episode` action to need only config, confirmed directly against
  `validate_manifest()`'s real signature (`RedlineConfig` only, no `db`,
  no `resolve`). `cli/main.py` now branches on `args.action` within the
  `episode` resource for this one case, dispatching to a new, separate
  `episode_commands.run_validate_manifest()` rather than adding an eighth
  branch to the existing `run()` (which stays typed `ApplicationServices`,
  unchanged, for the other seven actions). See `docs/ARCHITECTURE.md` for
  the full reasoning, including why a general per-action dispatch
  mechanism was deliberately not introduced for what's currently a single
  demonstrated case.
- Argument shape deviates from every other `episode` action on purpose:
  takes `manifest_path`, not `episode_number` — episode identity comes
  from inside the manifest file (`episode.id`), not from an operator-typed
  number, the same kind of contract-driven deviation `archive episode
  <episode_id>` already established.
- Result payload: `episode_id`, `bin_name`, `media_paths`, `media_count`,
  `markers` (each with `frame`/`color`/`name`/`note`), `marker_count` — all
  read directly off the existing `ValidatedEpisodePlan`, no new fields
  invented. Zero configured markers is a successful result
  (`marker_count: 0`), matching the manifest schema's own optional-markers
  default.
- Exception handling: catches exactly `ManifestLoadError`,
  `ManifestParseError`, `ManifestSchemaError`, `ManifestValidationError` —
  verified to transitively cover their subclasses `ManifestVersionError`
  and `ManifestPathError` via the actual class hierarchy in
  `redline_core/manifest/exceptions.py`, not a convenience catch of the
  shared `ManifestError` root. `str(exc)` passed through unchanged.
- No `--mock-resolve` needed or read by this command.
- New tests: `tests/unit/test_cli_episode_validate_manifest.py` (14 tests),
  including a gating `main()` end-to-end test that runs with neither
  `REDLINE_DB_PATH` set nor `--mock-resolve` passed — direct proof the new
  `CoreServices` routing actually took effect, mirroring the same proof
  `test_cli_asset_list.py` already established for `asset list`. Full
  suite: 938 passed, 1 skipped (up from Mission 11B's 924 passed, 1
  skipped).
- Manual smoke test: ran the installed `redline` console script directly
  against a real manifest file, with neither `REDLINE_DB_PATH` nor
  `--mock-resolve` set — a valid manifest (exit 0, full reported fields)
  and a missing-file manifest (exit 1, exact underlying error message).
  Repo working tree stayed clean throughout.
- Mission 13 (`episode assemble`) was blocked pending a separate
  architecture decision on rerun/recovery policy at the time this mission
  landed; resolved via ADR-0001 and implemented — see the Mission 13 entry
  above.

## Unreleased - Mission 11B: `redline episode place-clips` CLI

- Adds `redline episode place-clips <episode_number> [clip_id ...]` as a
  seventh `episode` action, as a thin wrapper over the existing,
  already-tested `TimelineBuilder.place_clips()`. This is the last
  `TimelineBuilder` public method to gain CLI exposure — `apply_markers()`
  remains internal-only (no natural episode-scoped argument shape; see
  Mission 11's architecture review).
- Unblocked directly by Mission 11A: `timeline_name` is resolved via
  `TimelineBuilder.timeline_name_for_episode()` — a pure call, no Resolve
  side effects — rather than by calling `build_timeline_for_episode()`
  again, which would have silently re-applied (duplicated) markers as an
  unrelated side effect.
- `clip_ids` are passed through completely unchanged: same order, no
  deduplication. Zero clip IDs is a successful no-op (`placed_count: 0`)
  — the adapter itself never touches the project or timeline when given
  an empty list, so this is the existing contract, not a CLI-invented
  distinction.
- Result payload echoes back both the requested `clip_ids` and the
  returned `timeline_item_ids`, since `place_clips()` preserves order
  position-for-position between them — real operator value, unlike
  `build-timeline`'s omitted `timeline_id`.
- Exception tuple matches Mission 10's: `EpisodeNotFoundError`,
  `ProjectNotFoundError`, `TimelineOperationError`, messages passed
  through unchanged; `ResolveConnectionError` remains owned by the
  top-level CLI boundary. No `mcp_server` changes.
- No new manager-level tests: `TimelineBuilder.place_clips()` and
  `timeline_name_for_episode()` both already have complete, independent
  coverage from Missions 10 and 11A. `tests/unit/test_cli_episode_place_clips.py`
  (17 tests) is CLI transport coverage only.
- No composition change: `ApplicationServices` already provided
  everything this command needs.
- Full suite: 924 passed, 1 skipped (up from Mission 11A's 911 passed, 1
  skipped).
- Smoke testing used two distinct categories, since mock Resolve state
  cannot survive across separate `redline` process invocations: an
  in-process smoke test (one shared `MockResolveAdapter` instance across
  `create` → `build-timeline` → `organize-bins` → `place-clips`, proving
  both the successful placement and the genuine "timeline not found"
  failure when `place-clips` runs before `build-timeline`), and an
  installed-script smoke test for the cases that don't need cross-process
  state (parser/`--help` behavior, zero-clip success, unknown-episode
  failure). A separately-invoked "project not found" case was also
  confirmed directly against the installed script, since a freshly
  started process's mock adapter has no projects at all.

## Unreleased - Mission 11A: pure timeline-naming helper (internal refactor, no CLI change)

- Adds `TimelineBuilder.timeline_name_for_episode(episode_id: str) -> str`,
  a pure method that formats `config.timeline.timeline_name_pattern` for a
  given `episode_id`. No Resolve, no SQLite, no logging, no mutation —
  reads one config field and returns a string.
- `TimelineBuilder.build_timeline_for_episode()` now calls this helper
  instead of inlining the `.format()` call. No observable behavior change:
  identical input produces the identical `timeline_name` it always did,
  proven by every existing `test_timeline_builder.py` assertion passing
  unmodified.
- `EpisodeManager.build_episode()`'s own pre-computation of `timeline_name`
  (used for early-stage error context before a real timeline exists) also
  now calls `self.timeline_builder.timeline_name_for_episode(...)` instead
  of independently reformatting the same pattern. This removes a
  pre-existing duplication — `EpisodeManager` was computing the identical
  value a second time, independently of `TimelineBuilder`, before this
  change — rather than merely preventing a new one. No observable
  behavior change here either: every existing `test_episode_manager.py`
  assertion (including the one checking `EpisodeBuildError.timeline_name`
  on a clip-placement failure) passes unmodified.
- This mission exists solely to resolve a real architectural blocker
  found while reviewing Mission 11's `place_clips` CLI candidate: neither
  `apply_markers()` nor `place_clips()` can be safely exposed by a
  transport without a way to obtain `timeline_name` that doesn't
  duplicate the naming pattern or re-trigger `build_timeline_for_episode()`'s
  marker-duplication side effect. A future `place-clips` CLI command can
  now call `services.timeline_builder.timeline_name_for_episode(episode_id)`
  directly. No CLI, MCP, Resolve, composition, or database change is part
  of this mission — `place-clips` itself remains deferred.
- Scope note: `tests/unit/test_episode_manager.py`'s hand-rolled
  `FakeTimelineBuilder` test double needed `timeline_name_for_episode()`
  added to it as well, to keep that file's existing tests passing against
  the refactored `EpisodeManager.build_episode()` call site — a necessary
  consequence of keeping the existing regression suite genuinely
  unmodified in behavior, not a scope expansion.
- New tests: two direct `timeline_name_for_episode()` tests in
  `tests/unit/test_timeline_builder.py`, proving the helper is
  pattern-driven (a second, different pattern/episode_id combination
  produces a different result) rather than hardcoded. Full suite: 911
  passed, 1 skipped (up from Mission 10's 909 passed, 1 skipped).

## Unreleased - Mission 10: `redline episode build-timeline` CLI

- Adds `redline episode build-timeline <episode_number>` as a sixth
  `episode` action, as a thin wrapper over the existing, already-tested
  `TimelineBuilder.build_timeline_for_episode()`. Continues the
  Resolve-driven CLI layer begun in Mission 9; `apply_markers()` and
  `place_clips()` (the other two `TimelineBuilder` public methods) remain
  internal-only primitives — used by `EpisodeManager.build_episode()`'s
  manifest flow — and are not exposed as independent CLI/MCP surfaces in
  this mission. Timeline IDs also remain internal: the CLI result and
  output report only `episode_id`, `project_name`, `timeline_name`, and
  `markers_applied`, never `timeline_id`.
- `episode_number` is resolved via the same `EpisodeManager.get_episode_status()`
  call every other `episode` action uses. No markers override is ever
  passed to the manager: `TimelineBuilder` owns timeline naming
  (`config.timeline.timeline_name_pattern`) and configured marker
  selection (`config.timeline.markers`) entirely on its own; the CLI does
  not re-derive the timeline name pattern itself anywhere.
- No new composition tier: `ApplicationServices` already provides
  everything this command needs (DB via `EpisodeManager` for episode
  resolution, Resolve via `TimelineBuilder` for the build/marker calls) —
  confirmed sufficient during architecture review, same tier every other
  `episode` action already uses.
- Zero configured markers is a successful result (`markers_applied: 0`),
  not an error, matching the manager's own behavior.
- Exception handling: catches exactly `EpisodeNotFoundError` (own
  episode-number resolution step), `ProjectNotFoundError`, and
  `TimelineOperationError` (both from `redline_core.resolve.exceptions`),
  messages passed through unchanged. `ResolveConnectionError` is excluded
  from this command-local tuple for the same reason established in
  Mission 9 — connection happens during `build_application_services()`,
  already owned by `main()`'s top-level boundary. `mcp_server/tools/timeline_tools.py`
  was not modified in this mission.
- **New required manager-level test**, closing a real, previously-uncovered
  gap found during architecture review: `TimelineBuilder.build_timeline_for_episode()`
  reuses an existing Resolve timeline by name (no duplicate timeline
  object is created on a second call — this was already true and already
  tested at the adapter layer), but it always reapplies the full
  configured marker set regardless, so calling it twice against the same
  episode duplicates markers on the timeline. `tests/unit/test_timeline_builder.py`
  now proves this directly (one timeline name after two calls, but `2N`
  stored markers where `N` is the configured count) — this is documented,
  existing behavior, not something this mission introduces or fixes.
- New tests: `tests/unit/test_cli_episode_build_timeline.py` (17 tests)
  plus the one new repeated-build test in `test_timeline_builder.py`.
  Full suite: 909 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script
  (`--mock-resolve`). Unknown-episode failure was run as a genuinely
  separate process invocation (exit 1). The successful-build case, and a
  second call against the same episode demonstrating the real
  marker-duplication behavior above (`markers_applied: 2` reported on
  both calls, not cumulative), were verified by sharing one
  `MockResolveAdapter` instance across `main()` calls — the same
  technique established in Mission 9 for cross-invocation Resolve state.
  Repo working tree stayed clean throughout.

## Unreleased - Mission 9: `redline episode organize-bins` CLI

- Adds `redline episode organize-bins <episode_number> [--bin-name footage]`
  as a fifth `episode` action, alongside `create`/`scan-ingest`/`status`/
  `list`, as a thin wrapper over the existing, already-tested
  `MediaManager.organize_bins()`. This begins the Resolve-driven CLI layer
  described in the Mission 9 architecture review; `MediaManager.import_media()`
  remains an internal-only primitive (used by `EpisodeManager.build_episode()`'s
  manifest flow) and is deliberately not exposed as its own CLI/MCP surface
  in this mission.
- `episode_number` is resolved to an `Episode` record via the existing
  `EpisodeManager.get_episode_status()` — the same call `scan-ingest`/
  `status` already use — giving `episode_id` and `project_name` for free
  (both already stored on the `Episode` record); no new lookup method or
  translation layer was added. `--bin-name` is passed through unchanged,
  defaulting to the manager's own literal default (`"footage"`) rather
  than inventing a new one.
- No new composition tier: `ApplicationServices` already provides
  everything this command's episode-number resolution and media import
  need (DB via `EpisodeManager`, Resolve via `MediaManager`) — confirmed
  sufficient during architecture review, same tier every other `episode`
  action already uses. `--mock-resolve` remains relevant, since this
  command genuinely calls `resolve.import_media()`.
- Zero matching ingest files is a successful result (`clip_count: 0`,
  `clip_ids: []`), not an error — matches `organize_bins()`'s own
  behavior (it returns `[]` without calling Resolve at all when nothing
  matches) and every prior mission's "empty state is still success"
  precedent. No episode-status update, no duplicate detection, no retry
  or rollback logic was added — `organize_bins()` doesn't perform any of
  those today, and this CLI action doesn't invent them.
- Exception handling: catches exactly `EpisodeNotFoundError` (from the
  CLI's own episode-number resolution step), `ProjectNotFoundError`, and
  `MediaImportError` (both from `redline_core.resolve.exceptions`,
  propagating through `MediaManager.import_media()` →
  `resolve.import_media()`), messages passed through unchanged.
  `ResolveConnectionError` is deliberately excluded from this command-local
  tuple — connection happens during `build_application_services()`, before
  this action's handler runs, and is already owned by `main()`'s existing
  top-level exception boundary. Unlike Missions 6-8, there was no
  already-defensive MCP tool to mirror here: `mcp_server/tools/media_tools.py`'s
  `organize_bins` tool has no exception handling of its own (see
  `docs/ARCHITECTURE.md`) — this CLI action's exception tuple was derived
  directly from what the manager/adapter can actually raise, not copied
  from the MCP transport. `mcp_server/tools/media_tools.py` itself was not
  modified in this mission.
- New tests: `tests/unit/test_cli_episode_organize_bins.py` (16 tests)
  plus one new custom-bin-name-forwarding test added to
  `tests/unit/test_media_manager.py` (a direct spy on the Resolve adapter
  call, proving forwarding without coupling to `MockResolveAdapter`'s
  internal clip-ID formatting or storage). Full suite: 895 passed, 1
  skipped.
- Manual smoke test: ran the installed `redline` console script
  (`--mock-resolve`) against an isolated temp config/DB. The zero-match
  and unknown-episode cases were run as genuinely separate process
  invocations (exit 0 and exit 1 respectively). The matched-media success
  case cannot be demonstrated across two separate real CLI invocations
  under `--mock-resolve` — confirmed directly: attempting it produced
  `ProjectNotFoundError`, since `MockResolveAdapter` has no persistence
  and `main()` builds a fresh instance every invocation, so a Resolve
  project created by one process doesn't exist for a separately-invoked
  one. That `ProjectNotFoundError` passthrough is itself a correct,
  real-world confirmation of this mission's failure handling. The
  matched-media success path was then verified directly against the
  installed package's own `cli.main.main()`, sharing one
  `MockResolveAdapter` instance across two calls (the same technique the
  automated end-to-end test uses) — episode created, clip imported,
  correct fields reported, exit 0. Repo working tree stayed clean
  throughout.

## Unreleased - Mission 8: `redline archive episode <episode_id>` CLI

- Adds the mutating `redline archive episode <episode_id>` action to the
  existing `archive` resource group (alongside Mission 7's `archive
  list`), as a thin wrapper over the existing, already-tested
  `ArchiveManager.archive_episode()`. `episode_id` is passed through
  completely unchanged — no type coercion, no `episode_number →
  episode_id` translation layer, resolving the argument-type finding
  recorded in Mission 7: the manager has always taken a raw string
  identifier (e.g. `"RLC-E025"`), never an episode number, and no call
  site anywhere in the repo has ever translated one into the other.
- Success output reports only the three fields on the manager's returned
  `ArchiveRecord` (`episode_id`, `archive_path`, `archived_at`) — reusing
  the existing `_archive_to_dict` from Mission 7 — with no additional
  Database or filesystem reads. Deliberately **no per-step progress
  checklist** (unlike `episode create`'s ✓ lines): this command reports
  the outcome, not `ArchiveManager`'s internal algorithm, so the CLI
  output stays correct even if the manager's internal steps change later
  (e.g. if its three DB writes are ever made transactional). See
  `docs/ARCHITECTURE.md` for where that internal-implementation detail
  now lives instead.
- Exception handling exactly mirrors the existing MCP tool
  (`mcp_server/tools/archive_tools.py._archive_episode`): catches
  `EpisodeNotFoundError` (from `redline_core.episode.exceptions`),
  `EpisodeAlreadyArchivedError`, and `ArchiveError` (both from
  `redline_core.archive.exceptions`) in one tuple, `str(exc)` passed
  through unchanged — no translation, no enrichment. Exit code `0` on
  success, `1` on any of the three exception types.
- Closes the one previously-uncovered `ArchiveManager` branch identified
  during Mission 8's architecture review: a pre-existing folder already
  sitting at the archive destination path with no matching archive
  record. Covered at two independent levels, per explicit instruction:
  `tests/unit/test_archive_manager.py` proves `ArchiveManager` itself
  raises `ArchiveError` for this condition (and that the source folder is
  left untouched, since `shutil.move()` never runs); the CLI's own test
  only proves the CLI passes that manager error through unchanged — it is
  not treated as that branch's only coverage.
- No composition change: `PersistenceServices` (Mission 7) already
  provided everything `archive_episode()` needs (`config.paths.archive_path`,
  `db`) — confirmed sufficient during architecture review, no new tier
  added.
- New tests: `tests/unit/test_cli_archive_episode.py` (11 tests) plus one
  new destination-collision test added to
  `tests/unit/test_archive_manager.py`. Full suite: 881 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script against
  an isolated temp config/DB (outside the repo tree), no `--mock-resolve`
  set. Confirmed both a successful archive (folder moved, DB fields
  updated, correct fields printed) and the destination-collision failure
  (folder left untouched, `ArchiveError` message printed unchanged, exit
  1). Repo working tree stayed clean throughout.

## Unreleased - Mission 7: `redline archive list` CLI + `PersistenceServices` composition path

- Adds the CLI's third resource group, `redline archive list` (no
  arguments), as a thin, read-only wrapper over the existing,
  already-tested `ArchiveManager.list_archives()`. Serialization reuses
  the exact three-field shape (`episode_id`/`archive_path`/`archived_at`)
  the existing MCP `list_archives` tool already uses. Order is whatever
  the DB returns (`SELECT * FROM archives ORDER BY archived_at`, no
  secondary sort key — a real latent nondeterminism on ties, not
  something this mission changes); the CLI does not re-sort. This
  mission adds only `archive list` — the mutating
  `redline archive episode <episode_id>` is deliberately deferred to a
  following mission, sequenced after this strictly smaller, read-only
  command per the same "smallest capability first" discipline every
  prior mission followed.
- New composition path:
  `redline_core.runtime.composition.PersistenceServices` /
  `build_persistence_services()` — configuration-backed services
  requiring SQLite persistence, but not Resolve. This is a third,
  distinct composition boundary alongside `ApplicationServices` (full
  runtime) and `CoreServices` (config-only), not a universal middle
  layer future commands default into; a manager only belongs here if it
  needs config and a DB connection but never touches Resolve, exactly
  `ArchiveManager`'s case. `ApplicationServices`/
  `build_application_services()` and `CoreServices`/
  `build_core_services()` are both **unchanged** — still the same full
  runtime and config-only paths as before. Small private construction
  helpers (`_resolve_config_dir`, `_resolve_db_path`, `_connect_database`)
  were extracted and are now shared by all three public builders, purely
  to avoid duplicating the same few lines a third time; none of the
  three public builders' own behavior changed as a result.
- **Argument-type finding from architecture review, resolved before
  implementation, not after.** This mission was expected to plausibly be
  `redline archive episode <episode_number>`, matching every other
  `episode`-adjacent CLI action so far. Fresh review of
  `ArchiveManager.archive_episode()` found it takes `episode_id: str`
  (e.g. `"RLC-E025"`), not an `episode_number: int` — confirmed against
  every existing call site (the MCP tool, all `test_archive_manager.py`
  tests). When Mission 8 implements the mutating `archive episode`
  command, its argument will be named and typed `<episode_id>` to match
  the real contract, not `<episode_number>` — this is a deliberate,
  reviewed decision, not an oversight, and does not affect this mission's
  read-only `archive list` (which takes no arguments at all).
- `list_archives()` has no failure modes of its own to report (no
  filtering, no arguments, nothing that can raise per the existing,
  already-tested manager) — `_run_archive_list()` always returns
  `success: True`, matching the existing MCP tool's shape exactly.
- New tests: `tests/unit/test_cli_archive_list.py` (10 tests) plus 4 new
  `build_persistence_services()` tests added to
  `tests/unit/test_composition.py`. Full suite: 870 passed, 1 skipped.
- Manual smoke test: ran the installed `redline` console script against
  an isolated temp config/DB (outside the repo tree) with no
  `--mock-resolve` flag set — `archive list` printed "No archives found."
  on an empty DB and correctly displayed a seeded archived episode
  (`RLC-E025`) after one was created directly via `ArchiveManager`,
  confirming the command genuinely never depends on Resolve. Repo working
  tree stayed clean throughout (smoke test ran entirely under `/tmp`, not
  inside the repo).

## Unreleased - Mission 6: `redline asset verify` CLI

- Adds `redline asset verify [asset_id ...]`, a thin, read-only wrapper
  over the existing, already-tested `AssetManager.verify_assets_for_episode()`.
  Same `CoreServices` composition path as `asset list` — no DB, no Resolve.
- **Correction from the original Mission 6 framing.** This mission was
  initially sketched as `redline asset verify <episode_number>`, described
  as "the first cross-domain (episode + asset) CLI command." Fresh
  architecture review of `verify_assets_for_episode()`'s actual signature
  found it takes no episode identifier at all — just an optional
  `asset_ids: list[str] | None` override, defaulting to
  `config.assets.required_for_episode` (a single global list, not
  per-episode) when omitted. Every call site in the repo (the MCP tool,
  all existing unit tests) confirms this — none has ever passed an
  episode identifier. Building a CLI command that accepted
  `<episode_number>` and then didn't use it for anything would have been
  misleading UI, the same category of correction as Mission 2's original
  "ingest media" sketch and Mission 1's manifest/log lines. The command
  matches the real contract instead: no episode argument, not a
  cross-domain command.
- `found`/`missing` in the result dict reuse the existing MCP tool's exact
  shape (bare asset-ID strings, `all_present` bool) rather than inventing
  a richer one. A CLI-only `checked` list is built for display (`asset_id`,
  `status`, `path`) — but its `status` is assigned strictly from the
  manager's own `found`/`missing` result, never from a second
  `.is_file()` check in the CLI; the manager stays the sole authority on
  whether an asset is present. `path` is a display-only string built from
  `config.assets.get(asset_id).filename`, shown as `(not registered)`
  when no definition exists. Effective input order (explicit override, or
  `required_for_episode` when omitted) and duplicate asset IDs are both
  preserved as given, not re-sorted or deduplicated — matching the
  manager's own behavior exactly.
- Handles a real correctness trap at the argparse boundary: `nargs="*"`
  gives `[]` when no `asset_id` is passed, but the manager treats `[]`
  ("verify zero assets") and `None` ("use the configured default set")
  as different things. `asset_commands.run()` converts an empty parsed
  list to `None` before calling the handler, so `redline asset verify`
  with no arguments correctly triggers the default set rather than
  silently verifying nothing. Tested explicitly, both at the handler level
  and end-to-end through `main()`.
- Exit code is `0` for any completed verification, including one that
  finds missing assets — mirrors the existing MCP tool's `success: True`-
  always contract (missing assets is a reported result, not an operation
  failure). Exit `1` is reserved for genuine operational failures, handled
  by the existing top-level exception boundary in `main()` — no new logic
  needed for that.
- New tests: `tests/unit/test_cli_asset_verify.py` (14 tests). Full suite:
  858 passed, 1 skipped.

## Unreleased - Mission 5: `redline asset list` CLI + config-only composition path

- Adds the CLI's second resource group, `redline asset list` (no
  arguments), as a thin, read-only wrapper over the existing,
  already-tested `AssetManager.list_available_assets()`. Serialization
  reuses the exact three-field shape (`asset_id`/`description`/`filename`)
  the existing MCP `list_available_assets` tool already uses. Order is
  whatever the manager returns (config declaration order in
  `config/assets.yaml`) — not re-sorted; this ordering was never an
  explicitly asserted contract at the `redline_core` layer (the existing
  unit test checks membership via a set, not order), so this is presented
  as "current behavior," not a documented guarantee, and preserved as-is.
- New composition path: `redline_core.runtime.composition.CoreServices` /
  `build_core_services()` — configuration-backed services requiring
  neither SQLite nor Resolve (no adapter constructed or connected at all),
  scoped to exactly that dependency boundary rather than serving as a
  general "core" layer future commands default into; a manager only
  belongs here if it needs nothing but config, exactly
  `list_available_assets()`'s case. `ApplicationServices`/
  `build_application_services()` is **unchanged** —
  still the full runtime for the MCP server and every `episode` command.
  This was the first mission where a command actually demonstrated the
  need for the capability-specific construction deferred back in Mission
  1 — architecture review surfaced that `asset list` would otherwise fail
  without Resolve running despite touching nothing Resolve-related, which
  is exactly the situation that deferral was meant to avoid once a real
  case showed up.
  - Scoped narrowly per explicit instruction: no generic dependency-tier
    framework, no lazy DI container, no rework of Missions 1-4's
    `episode` commands (still on `ApplicationServices`, untouched).
  - `main.py` now selects the composition path per resource group before
    dispatch, rather than building one runtime unconditionally — routing
    logic, not new architecture.
  - Verified structurally, not just by inspection: a test monkeypatches
    `Database.connect`/`ResolveScriptAdapter.connect`/`.__init__` to raise
    if called, then calls `build_core_services()` and confirms no
    exception — proving the independence claim rather than assuming it
    from the implementation reading the same way twice.
  - Verified at the CLI-invocation level too: `redline asset list` runs
    successfully with `REDLINE_DB_PATH` unset and no `--mock-resolve`
    flag, and no `redline.db` file appears afterward — the real, visible
    payoff of the fix.
- New tests: `tests/unit/test_cli_asset_list.py` (9 tests), plus 3 new
  `build_core_services()` tests added to `tests/unit/test_composition.py`.
  Full suite: 844 passed, 1 skipped.

## Unreleased - Mission 4: `redline episode list` CLI + CLI module split

- Adds a fourth CLI action, `redline episode list` (no arguments), as a
  thin, read-only wrapper over the existing, already-tested
  `EpisodeManager.list_episodes()`. No filtering, pagination, or alternate
  ordering added — none exists on the underlying method (`SELECT * FROM
  episodes ORDER BY episode_number`, no `LIMIT`/`OFFSET`), so none was
  invented for the CLI either. Empty state ("No episodes found.") is a
  successful result (exit 0), matching the manager's own contract — zero
  episodes was never an error case anywhere in the stack.
- Splits `src/cli/` into a thin `main.py` (parser assembly, logging setup,
  building `ApplicationServices`, dispatch, exit-code translation) plus a
  new `episode_commands.py` holding every `episode` action's logic —
  `_run_*`/`_print_*` handler pairs, `_episode_to_dict`, subparser
  registration, and dispatch. This was one of the two trigger points
  agreed on in Mission 2 (`episode list` becoming a fourth action, or a
  new resource group appearing) for reconsidering the single-file
  structure; the other (a new resource group, e.g. `asset`) hasn't
  happened yet.
  - Mechanical move only: no generic command registry, base command
    classes, shared result dataclasses, printer framework, or DI
    container was introduced alongside the split.
  - Existing Mission 1-3 tests (`test_cli_episode_create.py`,
    `test_cli_episode_scan_ingest.py`, `test_cli_episode_status.py`) pass
    **unmodified** — `cli/main.py` re-exports the moved names
    (`_run_episode_create`, `_print_episode_create_result`, etc.) as thin
    aliases for backward compatibility, so no test file needed to change
    its imports.
- New tests: `tests/unit/test_cli_episode_list.py` (8 tests). Full suite:
  833 passed, 1 skipped.

## Unreleased - Mission 3: `redline episode status` CLI

- Adds a third CLI action, `redline episode status <episode_number>`, as a
  thin, read-only wrapper over the existing, already-tested
  `EpisodeManager.get_episode_status()`. No computed health checks,
  readiness inference, media counts, asset verification, or build
  validation — only what's already persisted on the `Episode` row.
- Extends the shared `_episode_to_dict()` helper (used by `episode create`
  since Mission 1) with three additional fields: `id`, `created_at`,
  `updated_at`. Purely additive — `episode create`'s own output doesn't
  reference the new keys, and a dedicated test
  (`test_episode_create_output_unaffected_by_new_fields`) proves its output
  is unchanged. `created_at`/`updated_at` are passed through as-is: they're
  already deterministic `TEXT` columns (SQLite's `datetime('now')`) by the
  time they reach the `Episode` dataclass, not Python `datetime` objects,
  so no new formatting/parsing logic was introduced to make them
  "JSON-safe" — that safety already existed.
- Architecture review for this mission also produced a full inventory of
  every `redline_core` capability not yet CLI-exposed (see
  `docs/ARCHITECTURE.md` §5.1 note). Render commands (`queue_render`,
  `get_render_status`, `cancel_render`) were explicitly ruled out for any
  near-term CLI mission — the real Resolve adapter methods behind them are
  still stubbed per this README's own "Still open" note, so a CLI surface
  over them today would front a non-functional real-Resolve path.
- `src/cli/main.py` stays a single file — reassess only when `episode list`
  becomes a fourth action or a new top-level resource group (e.g. `asset`)
  is introduced, per the explicitly agreed trigger points.
- New tests: `tests/unit/test_cli_episode_status.py` (9 tests). Full suite:
  825 passed, 1 skipped.

## Unreleased - Mission 2: `redline episode scan-ingest` CLI

- Adds a second CLI command, `redline episode scan-ingest <episode_number>`,
  as a thin, read-only wrapper over the existing, already-tested
  `MediaManager.scan_ingest_for_episode()`. Zero new business logic:
  matching is still purely by episode-ID substring in the filename,
  regardless of extension (a `.txt` file matches exactly as readily as a
  `.mov`), and a missing ingest folder is treated the same as "no
  matches" — the existing method's behavior, not a new distinction
  invented for this slice.
- Deliberately does **not** add media-type classification (video/audio/
  graphic), duplicate detection, file copying/moving/renaming, Asset
  Registry insertion, or Resolve media-pool import (that's the separate,
  existing `organize_bins()`, still not CLI-exposed). Confirmed during
  architecture review that none of this is on the approved roadmap or
  built anywhere yet — the Persistent Asset Registry / reconciliation
  engine (Milestone 10) explicitly excludes duplicate-content detection
  from its own scope and covers a different domain (externally-approved
  Universe assets, not raw incoming episode footage). Output ends with an
  explicit disclaimer ("No files were classified, deduplicated, copied,
  moved, imported, or registered.") so a scan is never mistaken for
  completed ingestion.
- `src/cli/main.py` stays a single file for now rather than splitting into
  per-resource command modules — two commands doesn't yet justify that
  structure; revisit when a third command makes the file unwieldy.
- New tests: `tests/unit/test_cli_episode_scan_ingest.py` (9 tests), same
  tmp-path-isolated-config discipline established in Mission 1. Full
  suite: 816 passed, 1 skipped.

## Unreleased - Mission 1: `redline episode create` CLI

- Redline OS is now reachable from a terminal, not just as MCP tool calls.
  Adds a second, sibling transport: `src/cli/` (mirrors `mcp_server/`'s thin
  shape) with one command, `redline episode create <episode_number>`
  (`--mock-resolve` supported, same as `mcp_server.server`'s flag), wired
  via a new `redline` console-script entry point.
- Extracts the shared composition root out of `mcp_server/context.py` into
  a transport-neutral `redline_core/runtime/composition.py`
  (`ApplicationServices` / `build_application_services()`), so both
  transports build Config + Database + Resolve connection + all six
  managers from one place instead of duplicating the wiring.
  `mcp_server/context.py` is now a thin alias (`AppContext =
  ApplicationServices`) delegating to it — no behavior change for the MCP
  server; `tests/unit/test_mcp_tools.py` passes unmodified as proof.
- Deliberately does **not** add `CompositionOptions`/capability-specific
  construction (e.g. skip-Resolve) in this slice — no command yet needs a
  partial runtime, so that flag would have no real caller or acceptance
  test. Add it when the first genuinely Resolve-optional command (e.g.
  `episode inspect`, `config validate`) is actually built.
- Deliberately does **not** add a new "episode manifest" output artifact or
  a dedicated per-episode log file, despite both appearing in the original
  Mission 1 sketch — the former would collide with the existing, differently
  -scoped Episode Manifest V1 (input intent for `build_episode`, not an
  output receipt); the latter is already covered by the existing shared
  `redline_os.log` (`get_episode_logger`). Checklist wording reflects this:
  "Resolve project initialized" rather than "duplicated," since duplication
  is an implementation detail, not what the user needs to know.
- Zero changes to `EpisodeManager`, `MediaManager`, `TimelineBuilder`,
  `RenderManager`, `ArchiveManager`, or `AssetManager` business logic — this
  slice only adds a second way to reach the existing, already-tested
  `EpisodeManager.create_episode()` path.
- New tests: `tests/unit/test_composition.py` (4 tests) and
  `tests/unit/test_cli_episode_create.py` (13 tests). Every test that
  actually calls `create_episode()` uses an in-memory or tmp-path-scoped
  config rather than the real `config/` directory, since the real
  `config/folder_structure.yaml` root_path is a relative `./_episodes` that
  a naive test would otherwise write into the actual repo working tree.
  Full suite: 807 passed, 1 skipped.

## Unreleased - Asset Registry Reconciliation Repository Integration Compatibility (Phase 3 Slice 11)

- No production code changed. This slice adds two integration test files
  only, per the approved "Phase 3 Slice 11 Implementation Contract --
  Integration Compatibility (Roadmap Row 13), Revision 3 (final)":
  `tests/integration/test_snapshot_loading_from_sqlite_repository.py` (6
  tests) and `tests/integration/test_reconciliation_repository_compatibility.py`
  (11 tests) -- 17 tests total, matching the approved contract's test
  matrix 1:1 by number.
- Proves that a `RegistrySnapshot` populated from records read out of a
  real, temporary SQLite database via the existing (Phase 1/2)
  `SQLiteAssetRepository` flows through the unmodified reconciliation
  chain (`validate_reconciliation_inputs` -> `build_indexes` ->
  `build_matching_state` -> `evaluate_record_observability` ->
  `classify_reconciliation` -> `plan_reconciliation` ->
  `serialize_public_plan`) exactly as a `RegistrySnapshot` built from
  in-memory `AssetRegistryRecord` literals already does in the Slice 1-10
  unit tests.
- `AssetRegistryRecord.record_id` is proven immaterial to any serialized
  plan field at current HEAD by direct source inspection (no code path
  between `validate_reconciliation_inputs` and `serialize_public_plan`
  reads it, and every production `RegistryRecordSubject` construction
  passes only `asset_id`) -- not assumed. This is exercised directly: a
  cross-domain equivalence test uses a deliberately different `record_id`
  on its in-memory comparison side, and a reversed-insertion-order test
  across two independently-seeded temporary databases first asserts the
  two databases assigned different `record_id` values for a shared
  `asset_id`, then asserts identical canonical serialized bytes anyway.
- "No writes" and "no schema change" are verified as data-level
  before/after comparisons of repository-visible record state
  (`count_records`, `list_records`) and a direct, read-only
  `sqlite_master` + schema-version snapshot (filtered by `tbl_name` so
  both named and SQLite auto-generated indexes are captured, not just
  objects literally named `asset_registry...`) -- not as a claim that any
  specific repository write method was never called, since the
  reconciliation pipeline never holds a reference to the repository
  object in the first place.
- Component ownership is preserved: the corrected path/root-scope test
  builds its snapshot from `list_records(...)` (a complete registry read)
  and lets `ObservationScope.roots`/`evaluate_record_observability`
  perform the actual scope evaluation, rather than letting
  `get_by_normalized_path(...)` pre-filter which records reconciliation
  ever sees. A separate, explicitly-labeled bridge assertion independently
  confirms `get_by_normalized_path(...)` results are themselves valid
  `RegistrySnapshot` inputs, without claiming that proves scope
  resolution.
- No package-root export change (`__init__.py` and
  `test_package_exports.py` unmodified); no change to
  `src/redline_core/asset/sqlite_repository.py` or any reconciliation
  production module.
- Full existing `tests/unit` suite remains passing unchanged (794 passed,
  1 skipped, 795 total, exit code 0), and the pre-existing repository
  integration tests remain passing unchanged (`test_asset_sqlite_repository.py`,
  `test_asset_database_initialization.py`, 52 tests). Note: this
  repository's `pyproject.toml` sets `testpaths = ["tests/unit"]`, so a
  bare `python -m pytest` does not collect `tests/integration/` at all --
  running `python -m pytest tests/unit tests/integration` explicitly is
  required to exercise this slice's tests (and the pre-existing repository
  integration tests) as part of a genuinely complete regression run: 863
  passed, 1 skipped, 864 total, exit code 0.

## Unreleased - Asset Registry Reconciliation Public Serialization (Phase 3 Slice 10)

- `redline_core.asset.reconciliation.serialization`: new module implementing
  public plan serialization, per the approved "Phase 3 Slice 10
  Implementation Contract -- serialization.py, Revision 3 (final)". Adds
  the public entry point
  `serialize_public_plan(plan, *, limit_policy=DEFAULT_LIMITS) -> dict[str, Any]`,
  which converts one already-built `ReconciliationPlan` (Slice 9 output)
  into a stable, deterministic, JSON-compatible public dictionary.
- Redaction is a **structural allowlist**, not a per-fact `PublicVisibility`
  evaluation: `serialize_public_plan` walks the known, fixed set of fields
  on `ReconciliationPlan`/`ReconciliationPlanItem`/`PlanSummary`/
  `PlanSubject` explicitly, field by field -- never
  `dataclasses.asdict()`, `vars()`, `__dict__`, or any other
  reflection-based dump, so a future domain-model field does not
  automatically appear in public output. `PublicVisibility` and the other
  Slice-1 evidence-model enums remain unused, exactly as they are unused
  by every module built so far; no visibility classification is invented
  or inferred by this slice.
- `RegistryRecordSubject.record_id` is never emitted, whether populated or
  `None` -- `asset_id` is the stable public business identifier;
  `record_id` is an optional internal row reference the approved contract
  deliberately excludes from the public DTO.
- Determinism and the size guard both use one exact canonical byte
  definition:
  `json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")`.
  If that byte length exceeds `limit_policy.max_serialized_public_plan_bytes`,
  `serialize_public_plan` raises the existing `ReconciliationLimitExceededError`
  (no new exception class) with
  `context={"limit_name": "max_serialized_public_plan_bytes", "limit_value": ...}`
  -- no truncation, no partial payload. The function still returns the
  plain public `dict`, never bytes or a JSON string.
- No `PublicPlanSerializer` class exists; `serialize_public_plan` is a bare
  function, matching every other Slice 5-9 module's convention.
- `serialize_public_plan` does not re-run `planner.py`'s domain validation
  or recompute plan state; it projects the already-valid structure it is
  given. One output-integrity check (not a domain revalidation) confirms
  every emitted `evidence_ref` in the DTO this function itself builds
  appears in that same DTO's own top-level `evidence` list.
- `redline_core.asset.reconciliation.__init__.py` is **not** modified.
  `serialize_public_plan` is importable only as
  `redline_core.asset.reconciliation.serialization.serialize_public_plan`,
  matching the established precedent that `build_indexes`,
  `build_matching_state`, `classify_reconciliation`, and
  `plan_reconciliation` are also not package-root exports. This keeps
  `tests/unit/asset/reconciliation/test_package_exports.py` (Slices 1-2,
  unmodified) passing exactly as already approved.
- 26 new test cases across 20 numbered tests (`test_serialization.py`,
  matching the approved contract's test matrix 1:1 by number); full
  existing suite of 558 prior tests remains passing, 584 total, plus 1
  pre-existing unrelated skip.

## Unreleased - Manifest Validator: Avoid Process-Wide os.name Monkeypatch (Task #38)

- `redline_core.manifest.validator`: replaced a direct `os.name` monkeypatch in
  test code with a module-local `_is_windows()` indirection, used internally
  by `_duplicate_key()`. This is a test-hygiene / cross-cutting infrastructure
  fix, unrelated to Phase 3 reconciliation.
- The prior test
  (`test_windows_duplicate_key_strategy_is_case_insensitive`) patched the
  shared, process-wide `os` module's `name` attribute directly
  (`monkeypatch.setattr(manifest_validator.os, "name", "nt")`). Even though
  `monkeypatch` reverts this after the test, the mutation was observed to
  interact badly with pytest's own internal `pathlib.Path()` usage later in
  the same full-suite run, producing an unrelated `WindowsPath`
  `INTERNALERROR` at teardown/report time under certain collection orders.
- Fix: `validator.py` now exposes a small private function
  `_is_windows() -> bool` (returns `os.name == "nt"`), and `_duplicate_key()`
  calls this indirection instead of reading `os.name` directly. The test now
  patches `_is_windows` itself
  (`monkeypatch.setattr(manifest_validator, "_is_windows", lambda: True)`),
  exercising the same Windows-specific casefold branch without mutating any
  shared interpreter state.
- No behavior change to `_duplicate_key()`'s duplicate-key normalization
  logic; the Windows casefold branch itself is unchanged, only how it is
  tested. `tests/unit/test_manifest_validator.py` updated accordingly (1 test
  changed).
- Unrelated to Phase 3 Asset Registry Reconciliation; committed as its own
  isolated commit (`dd5959a`) between Slice 9 (`planner.py`) and Slice 10
  (`serialization.py`), per this project's standing discipline of never
  bundling an infrastructure fix into feature work.

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 9)

- `redline_core.asset.reconciliation.planner`: new module implementing final
  plan assembly, per the approved "Phase 3 Slice 9 Implementation Contract --
  planner.py, Revision 4 (final)". Adds the public entry point
  `plan_reconciliation(inputs, classification_state, *, created_at)`, which
  assembles one immutable `ReconciliationPlan` directly from Slice 8's
  `ClassificationState` -- no `findings.py`/`actions.py` object system.
- Plan item order is exactly `ClassificationState.decisions` order,
  index-for-index; no classification "rank" is invented or stored.
  Deterministic `item_id`s (`item-000001`, `item-000002`, ...) are assigned
  over that same order.
- `ReconciliationPlanItem.findings` and `.actions` are always `()` for every
  item, for every classification, with no exceptions; `evidence_refs` carries
  `ClassificationDecision.evidence_facts` forward unchanged.
  `PlanSummary.severities` and `PlanSummary.action_kinds` are always empty
  mappings. No action-kind mapping, severity table, or other domain policy is
  introduced by this slice -- all deferred to a future `actions.py`/
  `findings.py` contract, per the approved contract's Decisions 2, 3, and 5.
- No `ReconciliationPlanner` class exists; `plan_reconciliation` is a bare
  function, matching every other Slice 5-8 module's convention (contract
  Decision 4).
- `_limit_policy_fingerprint` (private, local to `planner.py`) computes a
  stable SHA-256 fingerprint over `ReconciliationLimitPolicy`'s fields,
  sorted by name; `canonical.py` is not modified (contract Decision 6).
- `redline_core.asset.reconciliation.__init__.py` is **not** modified.
  `plan_reconciliation` is importable only as
  `redline_core.asset.reconciliation.planner.plan_reconciliation`, matching
  the established precedent that `build_indexes`, `build_matching_state`,
  and `classify_reconciliation` are also not package-root exports. This
  keeps `tests/unit/asset/reconciliation/test_package_exports.py` (Slices
  1-2, unmodified) passing exactly as already approved.
- 58 new tests (`test_planner.py`), including a hand-built
  `PrimaryClassification.INVALID_OBSERVATION` decision confirming
  `PlanSummary.invalid_observation_count` actually increments (not just that
  it stays zero for classifications Slice 8's real pipeline can currently
  emit); full existing suite of 500 prior tests remains passing, 558 total,
  plus 1 pre-existing unrelated skip.
- `_verify_plan_invariants` checks each item ID against its exact expected
  position (`item-{index:06d}`), not merely uniqueness -- catching any
  ordering defect, not just collisions.

## Unreleased - Phase 3 Documentation Reconciliation (Post-Slice 8)

- Corrected `docs/ASSET_RECONCILIATION_ARCHITECTURE.md` and
  `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md` to accurately describe
  the bounded string-code evidence convention `matching.py` (Slice 6/7) and
  `classification.py` (Slice 8) already established and documented in their
  own docstrings. No code or tests changed.
- The current implementation uses the bounded string evidence model. The
  original `PlanEvidence`/`ReconciliationFinding`/action-object design
  remains documented as an earlier architectural proposal and is not part
  of the current Phase 3 implementation path — not removed and not judged
  permanently unnecessary. `findings.py`, `actions.py`, and richer
  structured evidence are reclassified as future / re-evaluate after
  `planner.py` and `serialization.py` are implemented.
- `evidence.py`: no rich `PlanEvidence` extension is required for the
  current Phase 3 critical path.
- Roadmap numbering in `docs/ASSET_RECONCILIATION_IMPLEMENTATION_PLAN.md`,
  section 25 is unchanged (rows 9, 10, 11 keep their existing numbers and
  module assignments). Row 11's dependency is corrected to name Slice 8
  directly, with an explicit Sequencing Note rather than a renumbering. The
  note also defines roadmap row numbers and implementation slice numbers as
  independent terminology, so `planner.py`, if built next, is correctly both
  Phase 3 Slice 9 and roadmap row 11 — see the row itself.

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 8)

- `redline_core.asset.reconciliation.classification`: new module implementing
  the central ordered classification engine, per the approved "Slice 8
  Implementation Contract -- Revision 3" (architecture-only session; no code
  changed during contract drafting). Adds `ClassificationDecision`,
  `ClassificationState`, and the public entry point
  `classify_reconciliation(inputs, indexes, matching_state,
  observability_by_asset_id)`.
- Implements a strict 15-rank executable precedence table (first match wins):
  registry identity evidence conflict, registry identity collision,
  authoritative identity conflict, content conflict, duplicate path conflict,
  ambiguous match, unknown authoritative Asset ID, path changed, lifecycle
  conflict, availability changed, record not observed, new unregistered
  observation, unchanged, metadata drift, insufficient scope.
- Four `PrimaryClassification` enum members (`REGISTRY_SNAPSHOT_INVALID`,
  `INVALID_OBSERVATION`, `UNSUPPORTED_OBSERVATION`, `DIAGNOSTIC_ONLY`) are
  documented as intentionally non-executable in this slice and are never
  produced; `DIAGNOSTIC_ONLY` in particular is not a catch-all -- a subject
  that matches no rule raises `ReconciliationInvariantError`
  (`reason_code="classification_no_rule_matched"`) instead.
- `observability_by_asset_id` is an explicit input contract: the caller
  resolves scope (via `scope.evaluate_record_observability`) for every
  unmatched registry record before calling `classify_reconciliation`; a
  missing entry raises `ReconciliationInvariantError`
  (`reason_code="classification_missing_observability_decision"`) rather than
  defaulting silently.
- `SIZE_CONFLICT` is not added to `PrimaryClassification` in this slice
  (deferred to a future dedicated slice, Decision 5a). Pending that slice, a
  size difference with no comparable verified hash classifies as
  `METADATA_DRIFT` with `requires_review=True` and evidence fact
  `size_differs_no_comparable_hash` -- documented as interim, temporary
  policy, not permanent semantics.
- `registry_identity_evidence_conflict` required no new index: computed
  directly from `indexes.registry.record_evidence_by_asset_id`, already
  built by Slice 5.
- `classification.py` imports `indexes.py` directly; the implementation
  plan's advisory import list for this module is corrected to include it
  (Decision 7) -- `findings.py` and `actions.py` do not exist yet in this
  repository and are not part of this slice's dependencies.
- 32 new tests (`tests/unit/asset/reconciliation/test_classification.py`),
  matching the "Slice 8 Implementation Contract -- Revision 3" exhaustive
  test matrix 1:1 by number; all prior Slice 1-7 reconciliation tests and the
  full existing suite (468 tests) remain unchanged and passing (500 total).

## Unreleased - Asset Registry Reconciliation Planning (Phase 3 Slice 7)

- `redline_core.asset.reconciliation.matching`: added strong-identity
  matching (`unique_strong_identity`), extending `build_matching_state`
  after trusted-Asset-ID and exact-path matching (Slice 6). Precedence:
  trusted Asset ID > exact normalized path > unique strong identity.
- Bridges the registry's five-component comparable-evidence key
  (`RegistryEvidenceLookupKey`) and the observation's three-component key
  (`ObservationIdentityKey`) privately inside `matching.py`, without
  modifying `indexes.py`; see `docs/ASSET_RECONCILIATION_ARCHITECTURE.md`
  "Implementation Note: Registry/Observation Identity-Key Bridge" for the
  disclosed semantic consequence of that reduction.
- Adds `registry_identity_collision`, `observation_identity_collision`, and
  `mixed_identity_collision` conflict facts for ambiguous strong-identity
  evidence, and preserves existing trusted-ID/exact-path associations when
  strong identity disagrees with them (`strong_identity_authoritative_conflict`
  / `strong_identity_content_conflict`) rather than overwriting them.
  `indexes.py`, `MatchingState`, and `ConsumedIds` are unchanged.
- 50 new tests (`tests/unit/asset/reconciliation/test_matching_strong_identity.py`);
  all prior Slice 1-6 reconciliation tests remain unchanged and passing.
- Note: Slices 1-6 of this same reconciliation engine (`enums.py`/`models.py`
  through `matching.py`'s trusted-ID/exact-path stage) were implemented and
  approved in prior work but were never given their own changelog entries;
  this is a pre-existing documentation gap, not something this entry
  retroactively fills beyond Slice 7 itself.

## Unreleased - Persistent Asset Registry Architecture

- Added the Milestone 10 Persistent Asset Registry V1 architecture design
  package: `docs/ASSET_REGISTRY_ARCHITECTURE.md`,
  `docs/ASSET_REGISTRY_SCHEMA.md`, `docs/ASSET_REGISTRY_LIFECYCLE.md`, and
  `docs/ASSET_REGISTRY_VALIDATION.md`.
- Documented authority boundaries: the external Redline Production System
  remains authoritative for Asset IDs and production standards,
  `config/assets.yaml` is the desired-state declaration and explicit
  reconciliation input, SQLite owns local Redline OS operational registry state,
  filesystem checks are
  point-in-time observations, and MCP remains a future thin presentation layer.
- Documented the recommended V1 registry shape: one active local registry record
  per external Asset ID, one resolved local path per active record, explicit
  config reconciliation with dry-run planning, transactional apply behavior, no
  startup mutation, and no normal public hard deletion.
- Documented V1 lifecycle, availability, verification, path-safety, error,
  logging, transaction, reconciliation, testing, platform, security, and future
  MCP compatibility models without changing implementation code, tests,
  configuration, SQLite schema, MCP tools, or Resolve integration.
- Focus-corrected the architecture after senior review: `config/assets.yaml` is
  now the desired-state declaration and explicit reconciliation input;
  `AssetManager` is the sole public V1 service; `AssetRepository` is the
  persistence boundary; direct public registration and reactivation are
  deferred; lifecycle, availability, and verification invariants are explicit;
  declared paths are root-relative to `config.paths.assets_path`; service-owned
  transaction scope is documented; ordinary missing/non-file verification
  outcomes are results rather than exceptions; and implementation remains
  pending final senior re-review.

## Unreleased - Episode Manifest Implementation

- Implemented `redline_core.manifest`, the Episode Manifest V1 internal API:
  `load_manifest(...)`, `validate_manifest(...)`, `EpisodeManifest`,
  `ValidatedEpisodePlan`, and typed manifest exceptions.
- Added safe YAML loading with one-document enforcement, UTF-8 reads, top-level
  mapping enforcement, safe construction, non-string mapping-key rejection, and
  duplicate mapping-key rejection at every nested level without mutating PyYAML
  global constructors.
- Added strict Pydantic V2 manifest schema models for `schema_version: 1`,
  `episode.id`, `assembly.bin_name`, object-shaped `assembly.media[].path`, and
  manifest marker fields limited to `frame`, `color`, `name`, and `note`.
- Added manifest domain and filesystem validation: manifest-relative path
  resolution, active `ingest_path` / `assets_path` approved-root containment,
  component-aware path checks, duplicate resolved media-path detection, missing
  file and directory rejection, and UNC/network handling through the same
  approved-root policy.
- Added immutable `ValidatedEpisodePlan` translation into the existing
  `EpisodeBuildDefinition` contract. The plan stores immutable manifest-owned
  marker values and creates fresh existing `MarkerDefinition` objects during
  translation without changing `EpisodeManager`, `MediaManager`,
  `TimelineBuilder`, SQLite, MCP tools, or Resolve adapter code.
- Documented and tested that YAML merge keys (`<<`) are intentionally
  unsupported in Episode Manifest V1.
- Added focused manifest unit and temporary-filesystem integration tests for the
  pure manifest layer, which still must not interact with Resolve.
- Live-verified Episode Manifest V1 on 2026-07-27 against DaVinci Resolve
  Studio 21.0.3.7 with Python 3.11.9: a controlled `RLC-E909` YAML manifest
  loaded, validated, translated into `EpisodeBuildDefinition`, and executed
  through `EpisodeManager.build_episode(...)` using a disposable
  `RLC-E909_MASTER` project duplicated from the approved
  `redline-os-test-duplicate` test project. The run imported two expendable
  media files, applied two manifest markers at frames 0 and 48, placed two
  timeline items, preserved manifest media and marker order, and updated only a
  temporary verification SQLite database.
- The live manifest verification removed the disposable Resolve project and
  temporary manifest/media/database artifacts afterward. The configured
  `RLC_MASTER_TEMPLATE` project was not present in the active Resolve project
  folder, so the documented disposable test project was used as the approved
  template source for this controlled run. No production project or production
  media was modified.
- During manifest live verification, Resolve represented the created
  `RLC-E909_TIMELINE` timeline as a Media Pool item in the target bin. This
  matches the known V1 Episode Assembly behavior and was not treated as an
  unexpected media import.

## Unreleased - Episode Manifest Architecture

- Added the Phase 2 Episode Manifest V1 architecture design package:
  `docs/EPISODE_MANIFEST_ARCHITECTURE.md`,
  `docs/EPISODE_MANIFEST_SCHEMA.md`,
  `docs/EPISODE_MANIFEST_LIFECYCLE.md`, and
  `docs/EPISODE_MANIFEST_VALIDATION.md`.
- Documented the approved YAML-only V1 manifest scope: an explicit existing
  episode ID, ordered media paths, optional bin name, and optional marker
  overrides that translate into `EpisodeBuildDefinition` without making
  `EpisodeManager` parse manifests.
- Documented V1 validation boundaries: manifest parsing and pure validation are
  read-only, make no SQLite mutations, and perform no Resolve interaction.
- Hardened the design package after senior review: approved roots are locked to
  the active loaded `ingest_path` and `assets_path`, duplicate YAML keys must be
  rejected, path containment must use resolved path-aware comparisons, and
  validated plans are documented as deterministic intent rather than guaranteed
  historical reproducibility.
- Explicitly deferred JSON support, schema migrations, manifest persistence,
  build history, rollback, MCP manifest tools, render/archive sections, asset
  roles, creative policy, and advanced timeline placement concepts.

## Unreleased - Episode Assembly

- Added V1 Episode Assembly orchestration through `EpisodeManager.build_episode()`, operating on an existing episode record and delegating media import to `MediaManager` plus timeline creation, marker insertion, and clip placement to `TimelineBuilder`.
- Added `EpisodeBuildDefinition` and `EpisodeBuildResult` for the internal Python assembly API; generated media IDs and TimelineItem IDs are returned in order but are not persisted to SQLite.
- Added stage-aware `EpisodeBuildError` with failed stage, episode ID, completed stages, project/timeline names when known, progress counts, and preserved lower-level causes.
- Added `MediaManager.import_media()` for explicit ordered media path imports while preserving existing ingest-scanning `organize_bins()` behavior.
- Added rerun protection: successfully assembled episodes are marked `assembled` and a second assembly attempt is rejected before media import; failed episodes are not automatically retried because Resolve may already have been mutated.
- Hardened assembly status failures: original stage failures remain primary if marking `failed` also fails, and an `assembled` status-update failure now raises a stage-aware `EpisodeBuildError` instead of returning success or leaking a raw DB exception.
- Documented V1 live-verification limits for Episode Assembly: stale-status rerun protection is in-process only, concurrent/cross-process builds are not protected, and `timeline_id` must not be treated as a stable Resolve UUID yet.
- Added unit coverage for assembly validation, manager call ordering, ordered ID propagation, stage failure boundaries, result validation, partial-state logging, status behavior, and shared application-context dependencies.
- Verified V1 Episode Assembly against Resolve Studio 21.0.3.7 and Python 3.11.9 using the disposable `redline-os-test-duplicate` project with one deterministic WAV and one deterministic PNG: media import, timeline creation, two markers, sequential placement, SQLite `assembled` status update, assembled rerun rejection, and validation failure without mutation all passed.
- Live verification observed that Resolve may represent a newly created timeline as a Media Pool item in the currently active target bin when the project is not using a dedicated Timelines bin. This is accepted Resolve behavior for V1, not an extra media import or assembly failure; Redline OS does not change the project-level "Use Timelines Bin" setting or relocate timelines.
- Remaining V1 limitations: linked video/audio cardinality is unverified, rollback is not implemented, cross-process concurrency protection is not implemented, and the stale-status restart limitation remains.

## Unreleased — Phase 1 (real Resolve connection)

- **Milestone: `ResolveScriptAdapter.connect()` verified against a real, running DaVinci Resolve Studio 21.0.3 instance** (licensed/activated Studio edition, not the free edition). This was the one thing blocked since Phase 0 — it is now unblocked.
- `ResolveScriptAdapter.import_media()` now has a first production implementation: connected-state guard, local path validation, project loading, top-level media pool bin reuse/creation, one-shot `MediaStorage.AddItemListToMediaPool(...)` import, strict partial-import detection, and media item ID extraction via `GetMediaId()` with `GetUniqueId()` fallback.
- Verified `ResolveScriptAdapter.import_media()` against a live DaVinci Resolve Studio project: created a top-level media pool bin, imported one PNG, received a real non-empty `GetMediaId()` value, and confirmed the returned ID matched the item found during live Media Pool inspection.
- Added `MediaImportError` under the Resolve exception hierarchy for import validation, bin setup, Resolve import, and ID extraction failures.
- Added focused unit coverage for the real adapter import path using fake Resolve API objects; no running Resolve instance is required for these tests.
- Current limitation: partial Resolve imports and media-pool current-folder changes are reported as failures but not automatically rolled back yet; cleanup behavior is deferred until it is validated against a live project.
- `ResolveScriptAdapter.build_timeline()` and `.add_markers()` now have first production implementations covered by fake Resolve API unit tests. Existing timelines are reused by exact name; Resolve auto-renaming is rejected; marker validation happens before any Resolve modification; partial marker insertion is reported but not automatically rolled back.
- Added `TimelineOperationError` under the Resolve exception hierarchy for timeline lookup, creation, marker validation, and marker insertion failures.
- Current limitation: created timelines may remain after post-create verification failure, and markers may remain after partial insertion failure; automatic rollback is deferred until deletion/cleanup behavior is validated against live Resolve.
- Verified `ResolveScriptAdapter.build_timeline()` and `.add_markers()` against a live DaVinci Resolve Studio project: created an empty timeline, returned the exact requested timeline name, reused the existing timeline on a repeated call without creating a duplicate, added two markers at frames 0 and 48, and confirmed marker `customData` round-tripped through `Timeline.GetMarkers()`. Resolve created its normal default empty video and audio tracks; no clips were added.
- `ResolveScriptAdapter.place_clips()` now has a first production implementation for Version 1 sequential timeline placement: validates requested clip IDs, rejects duplicate requests, resolves imported Media Pool items recursively by `GetMediaId()` with `GetUniqueId()` fallback, sets the exact-name timeline current, appends the resolved clips in requested order with `MediaPool.AppendToTimeline([...])`, and returns TimelineItem `GetUniqueId()` values.
- Added `MockResolveAdapter.place_clips()` and `TimelineBuilder.place_clips()` so the public adapter contract is available in unit tests and higher-level timeline orchestration without automatically changing episode assembly.
- Hardened V1 placement before live testing: `clip_ids` must be a real list, recursive Media Pool traversal is protected against repeated folder handles/cycles by object identity, placement-time ID fallback now matches import behavior, duplicate TimelineItem IDs are rejected, AppendToTimeline exceptions preserve their cause, and the mock now supports multiple exact-name timelines per project.
- Verified `ResolveScriptAdapter.place_clips()` against a live DaVinci Resolve Studio project using a newly created disposable timeline: one audio-only WAV and one PNG still were placed in requested order, `AppendToTimeline([...])` returned one TimelineItem per requested MediaPoolItem, returned TimelineItem IDs were real non-empty `GetUniqueId()` values, and the physical timeline contained one audio item and one video item on the expected track types.
- Current limitation: partial Resolve placement and current-timeline changes are reported but not automatically rolled back.
- Current follow-up: linked video/audio cardinality still needs live verification; if one source MediaPoolItem can produce multiple returned linked TimelineItems, the strict Version 1 count invariant may need adjustment.
- Root-caused and fixed a hard crash encountered along the way: launching the connection test under Python 3.13 caused an access violation (`0xC0000005`) when `DaVinciResolveScript` loads Resolve's native `fusionscript` module. Resolve's scripting DLL isn't built for the 3.13 ABI. Switching to Python 3.11 (already installed at `C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe`) fixed it immediately — this is not a bug in our code, it's an environment/Python-version requirement, now documented in `README.md`'s Requirements section.
- Verified `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` env vars (set via `scripts/setup_env.ps1`, dot-sourced) resolve correctly against the real install locations on this machine.
- **Still open, same file (`src/redline_core/resolve/adapter.py`):** `queue_render`, `get_render_status`, and `cancel_render` still raise `NotImplementedError`.

## Unreleased — Phase 6/7

- DB: `get_episode_by_episode_id()`, full `render_jobs` CRUD (`create_render_job`, `get_render_job_by_id`, `list_render_jobs_for_episode`, `update_render_job`), full `archives` CRUD (`create_archive_record`, `get_archive_by_episode_id`, `list_archives`). New `ArchiveRecord` model.
- `ResolveAdapter` interface gained `cancel_render()` — implemented in `MockResolveAdapter` (raises if the job doesn't exist or is already in a terminal state), blocked in `ResolveScriptAdapter` same as everything else pending Studio.
- `redline_core.render.manager.RenderManager`: `queue_render()` (async — returns a job ID immediately), `get_render_status()` (polls Resolve and syncs the DB row; bumps the episode to `rendered` on completion), `cancel_render()`, `list_render_jobs_for_episode()`.
- `redline_core.archive.manager.ArchiveManager`: `archive_episode()` (moves the working folder to `paths.archive_path`, records it, marks the episode `archived`; deliberately doesn't gate on render status — see `docs/ARCHITECTURE.md` §9 on keeping business rules minimal), `list_archives()`.
- 20 new tests (`test_render_manager.py`, `test_archive_manager.py`, `cancel_render` cases in `test_resolve_mock.py`) — 69 total.
- MCP: 6 new tools across `render_tools.py` / `archive_tools.py` (`queue_render`, `get_render_status`, `cancel_render`, `list_render_jobs_for_episode`, `archive_episode`, `list_archives`) — **15 tools total**, the complete pipeline from the original architecture doc.
- Re-verified against the real `mcp` package: all 15 tools list correctly, and a real `call_tool('queue_render', ...)` round-trip works after `create_episode`.
- **This closes out the roadmap in `docs/ARCHITECTURE.md` §6** — every manager (Episode/Asset/Media/Timeline/Render/Archive) is built and tested against the mock. The only remaining gap is real Resolve Studio integration beyond `connect()` (Phase 1), blocked on a Studio license.

## Unreleased — Phase 5

- `src/mcp_server`: real MCP server built on the official `mcp` package's `FastMCP`. `context.py` (`AppContext` / `build_context()`) constructs one Config, one DB connection, one Resolve adapter, and all four managers exactly once at startup.
- 9 tools across 4 modules (`tools/episode_tools.py`, `asset_tools.py`, `media_tools.py`, `timeline_tools.py`): `create_episode`, `get_episode_status`, `list_episodes`, `list_available_assets`, `verify_assets_for_episode`, `scan_ingest_for_episode`, `organize_bins`, `build_timeline`, `add_markers`. Full reference in `docs/MCP_TOOLS.md`.
- Every tool's actual logic lives in an underscore-prefixed function with **no dependency on the `mcp` package** — `register()` is the only place that touches FastMCP. This means `tests/unit/test_mcp_tools.py` (11 new tests, 45 total) runs without the optional `[mcp]` extra installed, same as the rest of CI.
- `server.py` entrypoint (`python -m mcp_server.server`) with a `--mock-resolve` flag, so the whole tool surface can be tried today, before Studio is installed. New `[project.scripts]` entry point: `redline-mcp`.
- **Verified for real, not just logic-tested:** installed the `mcp` package and confirmed the actual `FastMCP` server builds, lists all 9 tools with correct schemas, and executes real `call_tool()` round-trips (`create_episode`, `list_episodes`, `verify_assets_for_episode`) — the "Create Episode 025" scenario from `docs/ARCHITECTURE.md` §4 now genuinely works end-to-end against the mock.
- Render/Archive tools intentionally not included — those managers don't exist until Phase 6/7.

## Unreleased — Phase 4

- New config: `MarkerDefinition` / `TimelineTemplateConfig` (`config/timeline_template.yaml`) — timeline naming pattern + the standard marker set (frame/color/name/note) per the Broadcast Package V1.0 spec. Data-driven, not hardcoded.
- `redline_core.timeline.builder.TimelineBuilder`: `build_timeline_for_episode()` (builds the timeline + applies the default marker set, returns a `TimelineBuildResult`), `apply_markers()` (also usable standalone, with an optional marker-set override for special episodes).
- Scope note: Timeline Builder does not duplicate the project (Episode Manager's job) or import media (Media Manager's job) — it only calls `ResolveAdapter.build_timeline()` / `.add_markers()`.
- 4 new tests (`test_timeline_builder.py`) — 34 total, all against `MockResolveAdapter`.
- `ResolveScriptAdapter.build_timeline()` / `.add_markers()` comments updated to reflect they were blocked on a real Studio license, same as the other adapter methods.

## Unreleased — Phase 3

- New config: `AssetDefinition` / `AssetsConfig` (`config/assets.yaml`), `assets_path` added to `PathsConfig` (`config/paths.yaml`). Asset IDs remain sourced from the Universe project — this only records where the approved file lives on disk.
- `redline_core.asset.manager.AssetManager`: `list_available_assets()`, `verify_assets_for_episode()` (non-raising, returns found/missing), `ensure_assets_for_episode()` (raises `MissingAssetsError` if anything's missing).
- `redline_core.media.manager.MediaManager`: `scan_ingest_for_episode()` (filename-convention matching against `ingest_path`), `organize_bins()` (imports matches into the Resolve media pool via `ResolveAdapter.import_media()`).
- 11 new tests (`test_asset_manager.py`, `test_media_manager.py`), all against temp folders + `MockResolveAdapter` — 30 total, no Resolve/Studio required.
- `ResolveScriptAdapter.duplicate_project()` / `.import_media()` comments updated to reflect they're blocked on a real Studio license, not unbuilt logic — the business logic above is fully built and tested against the mock.

## Unreleased — Phase 2

- `redline_core.episode.manager.EpisodeManager`: `create_episode()`, `get_episode_status()`, `list_episodes()`. Orchestrates naming (from config) → DB row → working folder → duplicated Resolve project, in that order, so a partially-failed create still leaves a trackable DB row.
- `redline_core.db.database.Database.update_episode_paths()`: updates `project_path`/`folder_path` independently, added to support the above.
- `redline_core.episode.exceptions`: `EpisodeAlreadyExistsError`, `EpisodeNotFoundError`.
- Tests (`tests/unit/test_episode_manager.py`) covering create, duplicate-create conflict, status lookup (found/not found), and ordering — all against `MockResolveAdapter`, no Resolve/Studio required.
- **Blocked, not skipped:** real Resolve Studio integration (Phase 1 — `duplicate_project()` implemented for real, verified against a live instance) is paused because the workstation currently only has the free edition of Resolve 21. Everything above still works fully against the mock in the meantime.

## Unreleased — Phase 0

- Initial repo scaffold (`src/redline_core`, `src/mcp_server`, `tests/`, `docs/`, `config/`, `scripts/`).
- `redline_core.config`: pydantic schema (`NamingConfig`, `FolderStructureConfig`, `RenderPresetsConfig`, `PathsConfig`) + YAML loader with example config files.
- `redline_core.db`: SQLite schema (`episodes`, `render_jobs`, `archives`) + thin `Database` wrapper with basic episode CRUD.
- `redline_core.logging`: rotating-file + console logging setup, episode-correlated logger adapter.
- `redline_core.resolve`: `ResolveAdapter` interface, `ResolveScriptAdapter` (real, connection-only so far), `MockResolveAdapter` (fully implemented, used by all unit tests).
- Unit test suite (`tests/unit`) covering config, DB, and the mock Resolve adapter — runs in CI with no Resolve dependency.
- CI skeleton (`.github/workflows/ci.yml`) running `pytest tests/unit` on every push/PR.

**Not yet built:** Episode/Asset/Media/Timeline/Render/Archive managers, the MCP server, and any code path that talks to a *real* running Resolve instance beyond `connect()`. See `docs/ARCHITECTURE.md` §6 for the roadmap.
