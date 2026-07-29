# Changelog

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
