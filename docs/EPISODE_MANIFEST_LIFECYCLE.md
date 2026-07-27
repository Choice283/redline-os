# Episode Manifest Lifecycle

**Status:** Implemented in `src/redline_core/manifest/` for Milestone 09. Live
Resolve execution remains outside pure manifest validation. Controlled live
verification passed on 2026-07-27.

Episode Manifest V1 is a non-mutating input layer for existing V1 Episode
Assembly. It does not create episodes, modify SQLite during validation, or talk
to Resolve before execution.

## Successful Flow

```text
draft manifest
    -> load
    -> parse YAML
    -> schema validation
    -> path/domain validation
    -> ValidatedEpisodePlan
    -> EpisodeBuildDefinition
    -> EpisodeManager builds existing episode
    -> existing episode status lifecycle continues
```

## Core Lifecycle Rules

Episode creation is separate. The manifest references an explicit existing
episode ID and does not create the episode row, working folder, or Resolve
project.

Manifest loading occurs before assembly. The manifest layer must fail before
`EpisodeManager.build_episode(...)` is called if syntax, schema, domain, or path
validation fails.

Validation is non-mutating. It does not edit the source manifest, copy media,
import media, create timelines, add markers, place clips, update SQLite, or
connect to Resolve.

EpisodeManager remains responsible for episode lookup and execution
eligibility. It owns nonexistent episode failures, assembled rerun rejection,
failed-episode rejection, stale-status behavior, and status updates.

A successfully loaded manifest is not automatically historically frozen. V1
requires input immutability during loading and validation, but does not yet
persist snapshots, checksums, manifest paths, or build-history records.

A `ValidatedEpisodePlan` represents validation at a point in time. It is
deterministic intent, not guaranteed historical reproducibility. Media files may
be deleted, replaced, or changed; symlink or junction targets may change; file
permissions and filesystem availability may change; and active configuration,
including approved roots, may change between validation and execution. Changing
a manifest after assembly does not rewrite build history because build history
does not exist yet. Operators must treat assembled manifests carefully until
snapshot/checksum support exists.

Controlled live verification has shown that a validated manifest can translate
into the existing `EpisodeBuildDefinition` and execute through
`EpisodeManager.build_episode(...)`. Pure manifest loading and validation still
perform no Resolve or SQLite work.

## Manifest And Existing Episode Creation

The V1 manifest starts after episode creation:

```text
create_episode(...)
    -> SQLite episode row
    -> working folder
    -> duplicated Resolve project
    -> manifest-driven assembly may be run later
```

The manifest contains `episode.id`, not `episode.number`, `project_name`, or
`timeline_name`. Project and timeline names remain derived by existing
configuration and existing manager behavior.

## Translation Into Assembly

After validation, a `ValidatedEpisodePlan` translates into:

```text
EpisodeBuildDefinition(
    episode_id=<manifest episode.id>,
    media_paths=<ordered normalized absolute paths>,
    markers=<ordered MarkerDefinition list>,
    bin_name=<assembly.bin_name or "footage">,
)
```

The validated plan stores immutable manifest-owned marker values. Translation
creates fresh existing `MarkerDefinition` objects for `EpisodeBuildDefinition`
each time it is called.

`EpisodeManager.build_episode(...)` then performs the existing verified V1 flow:

```text
media import
    -> media result validation
    -> timeline build and marker application
    -> clip placement
    -> timeline item result validation
    -> SQLite assembled status update
```

## Failure Flow: Syntax Or Schema Failure

```text
draft manifest
    -> load
    -> parse/schema validation fails
    -> ManifestParseError or ManifestSchemaError
    -> no SQLite mutation
    -> no Resolve interaction
    -> no EpisodeManager call
```

Examples:

- malformed YAML;
- empty document;
- missing `schema_version`;
- unsupported schema version;
- unknown fields;
- missing `episode.id`;
- missing `assembly.media`.

## Failure Flow: Path Validation Failure

```text
draft manifest
    -> load
    -> parse
    -> schema validation
    -> path/domain validation fails
    -> ManifestPathError or ManifestValidationError
    -> no SQLite mutation
    -> no Resolve interaction
    -> no EpisodeManager call
```

Examples:

- missing media file;
- directory supplied where a file is required;
- duplicate normalized media paths;
- parent traversal outside approved roots;
- UNC or network path outside active approved roots.

## Failure Flow: Episode Not Found During Execution

```text
draft manifest
    -> valid ValidatedEpisodePlan
    -> EpisodeBuildDefinition
    -> EpisodeManager.build_episode(...)
    -> episode lookup fails
    -> EpisodeBuildError(stage="episode_lookup")
```

This is not a manifest validation failure. SQLite lookup and lifecycle policy
belong to `EpisodeManager`.

## Failure Flow: Episode Status Rejection

```text
draft manifest
    -> valid ValidatedEpisodePlan
    -> EpisodeBuildDefinition
    -> EpisodeManager.build_episode(...)
    -> existing episode status blocks execution
    -> EpisodeBuildError(stage="episode_lookup")
```

Current policy rejects already assembled episodes and failed episodes before
media import. The manifest layer must not reimplement or override this policy.

## Failure Flow: Resolve Execution Failure

```text
draft manifest
    -> valid ValidatedEpisodePlan
    -> EpisodeBuildDefinition
    -> EpisodeManager.build_episode(...)
    -> media import / timeline build / clip placement fails
    -> EpisodeBuildError with the current stage
    -> partial Resolve state may remain
```

V1 manifest validation cannot guarantee successful Resolve execution. Resolve
may reject imports, timeline operations, marker insertion, or clip placement at
runtime.

Callers should validate and execute within the same controlled workflow where
practical. Runtime systems retain their existing defensive checks, including
Resolve import validation, even after successful manifest validation.

## Rerun And Failed-Build Behavior

Rerun and failed-build behavior remains governed by current `EpisodeManager`
policy:

- assembled episodes are rejected before media import;
- failed episodes are not automatically retried in V1;
- status-update failures after Resolve mutation are unsafe;
- in-process stale-status protection does not survive restart;
- no rollback exists.

The manifest layer should report valid intent, not decide recovery policy.

## Persistence Boundaries

V1 does not persist:

- manifest path;
- manifest schema version;
- manifest checksum;
- manifest snapshot;
- validation result;
- validated plan;
- media path list;
- generated media IDs;
- generated TimelineItem IDs;
- build history.

These are future Build History responsibilities.

## Operator Guidance For V1

Operators should treat the manifest file used for assembly as an important input
artifact. Until snapshots and checksums exist, keep the manifest stable after a
manual assembly run if later inspection or reproduction may be needed.

Do not restart and rerun an episode after a status-update failure without
inspecting Resolve and SQLite. The current in-process stale-status guard is not
a durable recovery system.
