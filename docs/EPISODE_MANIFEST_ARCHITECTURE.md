# Episode Manifest Architecture

**Status:** Implemented in `src/redline_core/manifest/` for Milestone 09.
Controlled live verification passed on 2026-07-27.

## Purpose

Episode Manifest V1 defines the architecture for a durable, YAML-only episode
input document that answers one question:

```text
What explicit existing episode should Redline OS assemble, using which ordered
media files and optional markers?
```

The manifest is not a marketing roadmap, a creative bible, a render contract,
or an archive contract. It is a machine-readable assembly intent document that
will be translated into the already verified V1 Episode Assembly path.

## Architectural Context

Redline OS has a verified assembly path:

```text
EpisodeManager
    -> MediaManager
    -> TimelineBuilder
    -> ResolveAdapter
```

The manifest layer must sit before that path:

```text
Manifest file
    -> Manifest Loader
    -> Manifest Validator
    -> ValidatedEpisodePlan
    -> EpisodeBuildDefinition
    -> EpisodeManager
    -> MediaManager
    -> TimelineBuilder
    -> ResolveAdapter
```

This protects the current responsibility boundaries and keeps durable file
parsing out of runtime orchestration.

## Responsibility Boundaries

`EpisodeManager` owns episode creation, episode lookup, status transitions,
rerun rejection, stale-status behavior, and assembly orchestration. It must not
read YAML, parse schema versions, resolve manifest-relative paths, migrate
manifest documents, or enforce creative policy.

`MediaManager` owns media import delegation and ingest scanning. It must not
parse manifests or decide manifest schema validity.

`TimelineBuilder` owns timeline-name derivation from config, marker application,
and clip-placement delegation. It must not read manifest files or own manifest
versioning.

`ResolveAdapter` owns Resolve API calls and Resolve-specific failure
normalization. It must not know where a manifest came from.

The manifest layer owns durable manifest syntax, schema version, path safety,
domain normalization, and translation into existing runtime inputs.

## Data Flow

V1 data flow is intentionally one-way:

```text
YAML manifest on disk
    -> parsed mapping
    -> EpisodeManifest
    -> ValidatedEpisodePlan
    -> EpisodeBuildDefinition
    -> EpisodeManager.build_episode(...)
    -> EpisodeBuildResult
```

The source manifest file is read-only. V1 does not copy, rewrite, annotate,
snapshot, checksum, or persist the source manifest.

A `ValidatedEpisodePlan` is validation at a point in time: deterministic
intent, not guaranteed historical reproducibility. Media files, symlink or
junction targets, file permissions, filesystem availability, and active
configuration can change between validation and execution. V1 does not snapshot
or hash media, persist the manifest, persist the plan, or freeze configuration;
runtime systems keep their existing defensive checks.

## Why EpisodeManager Must Not Parse Manifests

`EpisodeManager` is already the owner of mutation-heavy orchestration: it calls
media import, timeline build, clip placement, and SQLite status updates. Adding
YAML parsing and path-policy behavior to it would couple durable document
format decisions to execution policy.

Keeping manifest parsing outside `EpisodeManager` gives Redline OS:

- pure validation that performs no Resolve calls;
- pure validation that performs no SQLite mutation;
- testable manifest behavior without a database or Resolve adapter;
- future schema migration ownership in one place;
- room for future render/archive planning without bloating
  `EpisodeBuildDefinition`.

## EpisodeManifest Responsibility

`EpisodeManifest` is the proposed durable model for the YAML file. It should
represent serialized user intent as written, after syntax parsing and schema
coercion but before filesystem/domain normalization is complete.

It owns:

- `schema_version`;
- explicit existing episode reference;
- assembly media list;
- optional assembly bin name;
- optional marker override list.

It must not own:

- project name;
- timeline name;
- folder structure;
- status transitions;
- Resolve objects;
- imported media IDs;
- TimelineItem IDs.

## ManifestLoader Responsibility

`ManifestLoader` should read a YAML file and produce `EpisodeManifest`.

It owns:

- file existence and readability checks;
- UTF-8 text loading;
- YAML syntax handling through `PyYAML`;
- single-document enforcement;
- top-level mapping enforcement;
- clear load/parse errors.

It must not:

- resolve media paths against approved roots;
- connect to Resolve;
- read or write SQLite;
- create or assemble an episode.

## ManifestValidator Responsibility

`ManifestValidator` should transform an `EpisodeManifest` into a
`ValidatedEpisodePlan`.

It owns:

- supported `schema_version` checks;
- unknown-field rejection;
- required-field validation;
- marker-domain validation against the current `MarkerDefinition` contract;
- media path resolution relative to the manifest file directory;
- approved media root enforcement against the active loaded
  `config.paths.ingest_path` and `config.paths.assets_path`;
- duplicate normalized path detection, including Windows case normalization;
- missing-path and file-versus-directory checks.

It must not:

- decide whether the episode currently exists in SQLite;
- decide whether the episode status permits assembly;
- connect to Resolve;
- call `EpisodeManager`.

## ValidatedEpisodePlan Responsibility

`ValidatedEpisodePlan` is the implemented runtime-intent model. It represents a
manifest that has passed schema, domain, and path validation.

It contains:

- explicit `episode_id`;
- ordered normalized absolute `media_paths`;
- canonical `bin_name`;
- ordered immutable manifest-owned marker values.

It provides a translation method into the existing execution contract. During
translation, fresh existing `MarkerDefinition` objects are created for the
returned `EpisodeBuildDefinition`; mutable assembly-layer marker objects are not
stored inside `ValidatedEpisodePlan`.

```text
ValidatedEpisodePlan.to_build_definition() -> EpisodeBuildDefinition
```

## EpisodeBuildDefinition Responsibility

`EpisodeBuildDefinition` remains the existing assembly input consumed by
`EpisodeManager.build_episode(...)`.

Current fields:

- `episode_id: str`
- `media_paths: list[str]`
- `markers: list[MarkerDefinition] = []`
- `bin_name: str = "footage"`

It is an orchestration input, not a durable schema. The manifest layer may
produce it, but V1 should not turn it into a YAML parser or expand it to cover
future render/archive behavior.

## EpisodeManager Responsibility

`EpisodeManager` remains responsible for:

- looking up the existing episode by `episode_id`;
- rejecting nonexistent episodes;
- rejecting already assembled episodes;
- rejecting failed episodes under the current V1 rerun policy;
- coordinating media import, timeline build, marker application, clip placement,
  result validation, and SQLite status update;
- raising stage-aware `EpisodeBuildError`.

Manifest validation must not duplicate these lifecycle decisions.

## Relationship To Configuration

The manifest layer consumes an already loaded `RedlineConfig`. It should follow
the repository's existing config conventions: YAML input, Pydantic models, and
explicit validation.

Configuration must be loaded before filesystem/path validation. For V1, the
only approved media roots are the active loaded `config.paths.ingest_path` and
`config.paths.assets_path`; the manifest layer does not invent or configure
separate manifest-specific roots. If those configured roots are relative, they
must be interpreted using the same configuration-loading context and base
semantics already used by Redline OS.

Configuration remains the source for:

- episode ID and project-name patterns;
- timeline-name pattern;
- folder structure;
- render presets;
- approved asset registry;
- global path settings.

Environment-specific configuration may change the active approved roots between
machines or runs, so manifest validation must be performed with the same active
configuration intended for execution.

The manifest must not redefine naming conventions, folder structure, project
names, timeline names, Asset IDs, or Broadcast Package standards.

## Relationship To SQLite

SQLite remains the source of truth for pipeline state. Manifest loading and pure
validation must not mutate SQLite.

V1 does not add columns for:

- manifest path;
- manifest checksum;
- manifest schema version;
- validation status;
- build history.

Those belong to a future Build History subsystem.

## Relationship To Resolve

Manifest loading and pure validation must not interact with DaVinci Resolve.
Resolve connection, project loading, media import, timeline creation, marker
insertion, and clip placement remain execution concerns below
`EpisodeManager`.

Live Resolve verification belongs to the later implementation milestone, not to
architecture approval.

## Relationship To External Standards

Redline OS consumes Redline Universe and Redline Production System standards. It
does not define them.

Manifest V1 must not invent:

- Asset IDs;
- asset roles;
- creative policy;
- Broadcast Package standards;
- Universe Bible rules;
- folder or naming conventions.

When those external contracts are explicitly available and approved, later
manifest versions may reference them.

## Implemented Module Layout

```text
src/redline_core/manifest/
    __init__.py
    models.py
    loader.py
    validator.py
    exceptions.py
```

`__init__.py` exports the public internal manifest API and typed
exceptions.

`models.py` defines `EpisodeManifest`, nested schema models, and
`ValidatedEpisodePlan`.

`loader.py` loads YAML files and constructs `EpisodeManifest`.

`validator.py` validates and normalizes an `EpisodeManifest` into a
`ValidatedEpisodePlan`.

`exceptions.py` defines the manifest exception hierarchy.

## Implemented Internal API

The implementation provides this internal Python API:

```python
load_manifest(path) -> EpisodeManifest

validate_manifest(
    manifest,
    *,
    manifest_path,
    config,
) -> ValidatedEpisodePlan

ValidatedEpisodePlan.to_build_definition() -> EpisodeBuildDefinition
```

The boundary remains: load and validate first, then translate into
`EpisodeBuildDefinition`. These calls do not query SQLite, call
`EpisodeManager`, or interact with DaVinci Resolve.

Controlled live verification confirmed this boundary by loading and validating
a YAML manifest before creating a fresh `EpisodeBuildDefinition` and passing
only that definition into `EpisodeManager.build_episode(...)`.

## Non-Goals

V1 explicitly does not implement:

- episode creation from a manifest;
- JSON manifests;
- schema migrations;
- render sections;
- archive sections;
- manifest snapshots;
- manifest checksums;
- manifest path persistence;
- build history;
- rollback;
- forced rebuild/reset;
- failed-build retry redesign;
- cross-process locking;
- MCP manifest tools;
- export verification;
- creative policy validation;
- asset IDs or asset roles;
- arbitrary track placement;
- transitions, titles, graphics, or effects.
- linked audio/video placement cardinality;
- dedicated Resolve timeline-bin organization.

## Future Extension Points

Future schema versions may add:

- manifest snapshot/checksum persistence;
- build-history records;
- recovery and reset workflows;
- render planning once real render behavior is implemented and verified;
- archive planning once archive policy is formalized;
- asset-role validation once external production-system contracts are approved;
- MCP tools after path safety and internal execution are verified.

## Architectural Decision Record Summary

Decision: Use a YAML-only Validated Episode Plan architecture for V1.

Rationale:

- The repository already uses YAML and Pydantic for durable config.
- The existing `EpisodeBuildDefinition` contract is sufficient for V1 assembly.
- A plan layer keeps durable manifest intent separate from execution inputs.
- `EpisodeManager` stays transport- and serialization-agnostic.
- Render/archive contracts remain deferred until their real behavior is ready.

Consequences:

- V1 implementation work can stay narrow.
- Manifest validation can be unit-tested without SQLite or Resolve.
- Future schema versions have a stable place to grow without changing
  `EpisodeManager` prematurely.
