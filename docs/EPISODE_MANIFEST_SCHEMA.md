# Episode Manifest V1 Schema

**Status:** Implemented in `src/redline_core/manifest/` for Milestone 09.
Controlled live verification passed on 2026-07-27.

Episode Manifest V1 is YAML-only and describes assembly intent for an existing
episode. It contains only fields supported by current V1 Episode Assembly.

## Complete Valid Example

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  bin_name: "footage"
  media:
    - path: "media/Redline OS Import Test.wav"
    - path: "media/Redline OS Import Test.png"
  markers:
    - frame: 0
      color: "Blue"
      name: "Cold Open"
      note: "Episode start"
    - frame: 48
      color: "Yellow"
      name: "Checkpoint"
      note: ""
```

Relative media paths are resolved relative to the manifest file's directory,
then checked against configured approved media roots.

## Minimal Valid Example

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: "media/clip.wav"
```

`assembly.bin_name` defaults to `footage`. `assembly.markers` defaults to an
empty list, which means the manifest supplies no marker override.

Media entries use object form (`- path: ...`) rather than bare strings so the
schema is explicit and field-level validation can point to
`assembly.media[index].path`. This also leaves a controlled extension point for
future approved metadata without changing the basic list shape. Schema version 1
still rejects every unknown media-entry field and translates only `path` values
into ordered `EpisodeBuildDefinition.media_paths`; it does not introduce asset
IDs, roles, track placement, or creative policy.

## V1 Shape

```text
schema_version
episode
    id
assembly
    bin_name
    media
        []
            path
    markers
        []
            frame
            color
            name
            note
```

V1 does not include project names, timeline names, asset IDs, render settings,
archive settings, track placement, effects, graphics, titles, or transitions.

## Field Reference

| YAML path | Type | Required | Default | Constraints | Ownership | Runtime translation target |
|---|---|---:|---|---|---|---|
| `schema_version` | integer | yes | none | Must be exactly `1` in V1. Missing, non-integer, or unsupported versions fail. | Manifest layer | Selects manifest schema parser/validator |
| `episode.id` | string | yes | none | Non-empty string. Should match the configured episode ID pattern format. Execution eligibility remains with `EpisodeManager`. | Manifest layer validates shape; `EpisodeManager` owns lookup/status | `EpisodeBuildDefinition.episode_id` |
| `assembly.bin_name` | string | no | `footage` | Non-empty string after trimming. Top-level Resolve bin behavior is owned by `ResolveAdapter.import_media`. | Manifest layer validates shape | `EpisodeBuildDefinition.bin_name` |
| `assembly.media` | list | yes | none | Must contain at least one item. Order is preserved exactly. | Manifest layer | Ordered `EpisodeBuildDefinition.media_paths` |
| `assembly.media[].path` | string | yes | none | Non-empty string. Resolved relative to the manifest file directory if relative. Must resolve to an existing file inside `config.paths.ingest_path` or `config.paths.assets_path`. Duplicate normalized paths are rejected. | Manifest validator | Normalized absolute media path string |
| `assembly.markers` | list | no | `[]` | Every item must match the current `MarkerDefinition` fields. Order is preserved. | Manifest layer | Ordered `EpisodeBuildDefinition.markers` |
| `assembly.markers[].frame` | integer | yes | none | Must be `>= 0`. Boolean values are not valid integers. This matches the current `MarkerDefinition` frame constraint. | `MarkerDefinition` plus manifest validation | `MarkerDefinition.frame` |
| `assembly.markers[].color` | string | yes | none | Manifest V1 rejects empty color values before execution. It does not define a Resolve color allowlist. | Manifest domain validation plus adapter execution | `MarkerDefinition.color` |
| `assembly.markers[].name` | string | yes | none | Manifest V1 rejects missing or non-string names; empty-name policy must be explicitly tested if stricter validation is added. | Manifest domain validation plus `MarkerDefinition` | `MarkerDefinition.name` |
| `assembly.markers[].note` | string | no | `""` | Optional marker note. | `MarkerDefinition` | `MarkerDefinition.note` |

## Marker Terminology

The canonical V1 marker fields are exactly the current `MarkerDefinition`
fields:

- `frame`
- `color`
- `name`
- `note`

V1 manifest markers do not expose raw Resolve adapter-only fields such as
`duration`, `custom_data`, or `customData`, because `EpisodeBuildDefinition`
currently carries `list[MarkerDefinition]`, and `MarkerDefinition` does not
include those fields.

`MarkerDefinition` determines the supported execution fields. Manifest schema
validation may reject invalid types and missing required marker fields, and
manifest domain validation may reject empty or otherwise unusable values before
Resolve execution where this document explicitly says so. These manifest rules
must not be misattributed to `MarkerDefinition` if the current class does not
enforce them. `TimelineBuilder` and `ResolveAdapter` may retain their existing
execution-time defensive validation. Marker order remains stable.

`ValidatedEpisodePlan` stores immutable manifest-owned marker values. Fresh
existing `MarkerDefinition` objects are created during translation to
`EpisodeBuildDefinition`.

## Unknown Fields

Unknown fields are rejected in V1. This includes unknown top-level keys,
unknown nested keys, misspellings, and future-looking fields.

Rejecting unknown fields protects operators from a manifest that appears to ask
for behavior Redline OS will not execute.

YAML merge keys (`<<`) are not supported in Episode Manifest V1.

## Ordering Behavior

`assembly.media` order is significant and must be preserved through:

```text
manifest media order
    -> ValidatedEpisodePlan.media_paths
    -> EpisodeBuildDefinition.media_paths
    -> media_ids
    -> timeline_item_ids
```

`assembly.markers` order is also preserved into the marker list supplied to
`TimelineBuilder`.

## Empty Media List Behavior

`assembly.media` must not be empty in V1. Current
`EpisodeManager.build_episode(...)` rejects empty `media_paths` before manager
calls, so the manifest validator should fail this earlier as a manifest/domain
validation error.

## Empty Marker List Behavior

`assembly.markers: []` is valid. If the manifest supplies an empty marker list,
the translated `EpisodeBuildDefinition.markers` should be an empty list. Current
assembly behavior still imports and places clips when no markers are supplied.

If `assembly.markers` is omitted, V1 should also translate to an empty list. A
future schema may define whether omission means "use configured defaults", but
V1 should avoid ambiguity.

## Duplicate Media Behavior

Duplicate media entries are rejected after path resolution and normalization.
On Windows, duplicate comparison must account for case-insensitive path
collisions.

Example duplicate after normalization:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: "media/clip.wav"
    - path: "./media/../media/CLIP.wav"
```

Expected failure: duplicate normalized media path.

## Path Interpretation

Relative media paths are resolved relative to the manifest file directory, not
the current working directory.

The conceptual V1 path algorithm is:

1. Resolve the manifest path and use its directory as the base for relative
   media paths.
2. Resolve the active loaded `config.paths.ingest_path`.
3. Resolve the active loaded `config.paths.assets_path`.
4. For each media path, leave absolute paths absolute before resolution; join
   relative media paths to the manifest directory, then resolve the result.
5. Confirm that the resolved media target is contained within at least one
   resolved approved root.

Resolved paths must:

- remain inside either `config.paths.ingest_path` or `config.paths.assets_path`;
- exist;
- be files, not directories;
- not resolve through parent-directory traversal outside an approved root.

Containment must use path-aware component comparison such as
`Path.is_relative_to()` or an equivalent implementation. Raw string-prefix
checks are prohibited. For example, if the approved root is:

```text
C:\media\approved
```

then this sibling is not contained:

```text
C:\media\approved-evil
```

Configured roots and media targets must use consistent normalization. On
Windows, duplicate comparison must account for drive-letter and path-case
normalization, and duplicate checks happen after absolute resolution. Broken
symlinks fail validation. Symlink and junction containment should be based on
the resolved target where platform behavior permits. The manifest file itself
does not need to live under an approved media root; media may be valid under
either approved root even when the manifest is stored elsewhere.

UNC and network media paths are not controlled by a separate manifest option,
and V1 has no manifest-specific network-path enablement flag. A UNC or network
media path is valid only when its resolved target is contained beneath at least
one active resolved approved root. If an active approved root itself resolves to
a UNC or network location, media contained beneath that root may be accepted.
Normal file existence, file-type, duplicate-path, symlink/junction, and
containment validation still applies. A UNC path outside both active approved
roots must be rejected because it is outside the approved roots, not merely
because it is a network path.

The validator must not copy, rewrite, relocate, or import files.

Path validation does not eliminate time-of-check/time-of-use risk. Files,
symlink targets, junction targets, permissions, and active configuration can
change after validation.

## Schema-Version Behavior

Required:

```yaml
schema_version: 1
```

Rejected:

- missing `schema_version`;
- string values such as `"1"`;
- floats such as `1.0`;
- unsupported integers such as `2`.

V1 does not include a migration framework. Future migration ownership belongs
to the manifest layer, not `EpisodeManager`.

## Unsupported Examples

Render sections are not supported:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: "media/clip.wav"
render:
  preset: "broadcast_master"
```

Expected failure: unknown top-level field `render`.

Project and timeline names are not supported:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
  project_name: "RLC-E025_MASTER"
assembly:
  timeline_name: "RLC-E025_TIMELINE"
  media:
    - path: "media/clip.wav"
```

Expected failure: unknown fields. Project and timeline names remain
config-derived.

Asset roles are not supported:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: "media/clip.wav"
      role: "dialogue"
      asset_id: "RLG-001"
```

Expected failure: unknown media fields `role` and `asset_id`.

## Invalid Examples

Missing media:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media: []
```

Expected failure: `assembly.media` must contain at least one item.

Invalid marker:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: "media/clip.wav"
  markers:
    - frame: -1
      color: "Blue"
      name: "Bad"
```

Expected failure: marker frame must be `>= 0`.

Path outside approved roots:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: "../../outside/clip.wav"
```

Expected failure: resolved path escapes approved media roots.

UNC path outside active approved roots:

```yaml
schema_version: 1
episode:
  id: "RLC-E025"
assembly:
  media:
    - path: \\unapproved-server\share\clip.mov
```

Expected failure: the resolved UNC target is outside both active approved roots.
This example does not imply that every UNC path is invalid.

## Canonical Terminology

Use:

- Episode Manifest: durable YAML source document.
- EpisodeManifest: parsed schema model.
- ValidatedEpisodePlan: normalized runtime intent.
- EpisodeBuildDefinition: current assembly execution input.
- media path: local file path supplied for import.
- media ID: Resolve MediaPoolItem ID returned by import.
- TimelineItem ID: Resolve timeline item ID returned by placement.

Do not use "asset role", "render plan", "archive plan", "project name", or
"timeline name" as V1 manifest fields.

## Explicit Omissions From V1

V1 omits:

- JSON support;
- schema migrations;
- manifest checksum persistence;
- manifest path persistence;
- manifest snapshots;
- build history;
- rollback;
- forced rebuild/reset;
- failed-build retry redesign;
- cross-process locking;
- MCP manifest tools;
- render sections;
- archive sections;
- export verification;
- asset IDs;
- asset roles;
- creative policy;
- arbitrary track placement;
- transitions;
- titles;
- graphics;
- effects;
- linked audio/video placement cardinality;
- dedicated Resolve timeline-bin organization.
