# Episode Manifest Validation

**Status:** Implemented in `src/redline_core/manifest/` for Milestone 09.
Controlled live verification passed on 2026-07-27.

Episode Manifest V1 validation is layered so pure document checks happen before
any SQLite or Resolve behavior.

## Layer 1: File Loading

Owner: `ManifestLoader`.

Checks:

- manifest file exists;
- manifest file is readable;
- file is decoded as UTF-8;
- file extension is supported.

Recommended V1 extension policy: accept `.yaml` and `.yml`; reject other
extensions unless a caller has already selected an explicit loader by API.

Typical failures:

- file missing;
- permission denied;
- encoding failure;
- wrong extension.

Mutation boundary: no mutation occurs.

## Layer 2: YAML Syntax

Owner: `ManifestLoader`.

Checks:

- valid YAML syntax;
- non-empty document;
- one YAML document only;
- top-level YAML mapping;
- duplicate mapping keys rejected at every level;
- non-string mapping keys rejected where the schema expects named fields;
- arbitrary Python object construction prohibited through safe loading or an
  equivalent safe parser configuration.

Typical failures:

- malformed indentation;
- multiple YAML documents;
- scalar or list at top level;
- null root or empty document;
- duplicate `schema_version`, `episode`, `assembly`, media-entry, or marker
  keys.

PyYAML safe loading alone does not guarantee duplicate-key rejection as an
explicit Redline OS contract. Silent "last value wins" behavior is prohibited.
Duplicate keys must fail during parsing before Pydantic model validation. The
error should identify the duplicate key and, where practical, its location.
This applies to top-level mappings, `episode` mappings, `assembly` mappings,
media-entry mappings, marker mappings, and all future nested mappings.

YAML merge keys (`<<`) are not supported in Episode Manifest V1. The loader
does not call PyYAML merge flattening to support this syntax.

Examples that must fail:

```yaml
schema_version: 1
schema_version: 2
```

```yaml
episode:
  id: FIRST
episode:
  id: SECOND
```

```yaml
assembly:
  bin_name: footage
  bin_name: assets
```

Implementation should also evaluate inexpensive parser guards such as a maximum
manifest file size, alias/anchor expansion protection, and maximum nesting depth
where practical. V1 remains an internal-file feature, so these guards should be
practical rather than an exaggerated external threat model.

Mutation boundary: no mutation occurs.

## Layer 3: Schema Validation

Owner: manifest schema model.

Checks:

- required `schema_version`;
- integer schema version;
- supported schema version;
- required `episode.id`;
- required `assembly.media`;
- correct field types;
- unknown-field rejection;
- valid nesting.

Typical failures:

- `schema_version: "1"`;
- missing `episode`;
- misspelled `assembly.medai`;
- unsupported `render` or `archive` section.

Mutation boundary: no mutation occurs.

## Layer 4: Domain Validation

Owner: `ManifestValidator`.

Checks:

- episode ID is a non-empty string and matches the configured episode ID shape
  where practical;
- `assembly.media` contains at least one entry;
- `assembly.bin_name` is a non-empty string when supplied;
- marker fields match current `MarkerDefinition`: `frame`, `color`, `name`,
  `note`;
- marker frame is an integer `>= 0`;
- marker color is a non-empty string, without inventing a Resolve color
  allowlist;
- marker name is a string, with any stricter empty-name rule documented and
  tested before implementation;
- marker note is a string, defaulting to `""`;
- duplicate normalized media paths are rejected;
- media order is preserved.

`MarkerDefinition` determines the supported execution fields. Manifest V1 does
not add `duration`, `custom_data`, or `customData`. Manifest-domain validation
may be stricter than `MarkerDefinition` for the same fields only where the rule
is explicitly documented and compatible with current execution behavior.

Domain validation must not:

- check whether the episode exists in SQLite;
- check whether the episode status allows assembly;
- inspect Resolve project contents;
- validate marker frame against final timeline duration.

Mutation boundary: no mutation occurs.

## Layer 5: Filesystem And Path Safety

Owner: `ManifestValidator`.

Checks:

- relative paths resolve relative to the manifest file directory;
- resolved paths remain inside the active loaded `config.paths.ingest_path` or
  `config.paths.assets_path`;
- parent-directory traversal cannot escape approved roots;
- paths exist;
- paths are files, not directories;
- duplicate comparison uses normalized resolved paths;
- Windows comparisons account for case-insensitive collisions;
- UNC or network paths remain subject to approved-root containment;
- symlink targets are considered conservatively.

Configuration must be loaded before filesystem/path validation. The manifest
layer does not invent or configure separate manifest-specific roots in V1. The
approved roots are exactly the active loaded `config.paths.ingest_path` and
`config.paths.assets_path`; a media file may be located under either root.
`MediaManager.import_media(...)` may technically accept broader paths today, but
Manifest V1 intentionally enforces this narrower approved-root boundary.

If configured roots are relative, they must be interpreted using the same
configuration-loading context and base semantics already used by Redline OS.
Environment-specific configuration may change the active roots between
environments, so validation must use the same active loaded configuration
intended for execution.

Conceptual containment algorithm:

1. Resolve the manifest path.
2. Resolve each approved configured root.
3. Resolve each media path. Absolute paths remain absolute before resolution;
   relative media paths are first joined to the manifest directory, then the
   resulting target is resolved.
4. Confirm that the resolved media target is contained within at least one
   resolved approved root.

Containment must use `Path.is_relative_to()` or an equivalent component-aware
implementation. Raw string-prefix containment is prohibited. If the approved
root is `C:\media\approved`, the sibling `C:\media\approved-evil` must not be
treated as contained.

Configured roots and media targets must use consistent normalization. Duplicate
checks occur after absolute resolution; on Windows they must account for
drive-letter and case-insensitive path collisions. Parent traversal is rejected
when its resolved result escapes approved roots. Symlink and junction
containment must be based on the resolved target where platform behavior
permits. Broken symlinks fail validation. The manifest file does not need to be
inside an approved media root, and an asset may be valid when the manifest is
stored elsewhere.

UNC and network media paths are not controlled by a separate manifest option,
and V1 has no manifest-specific network-path enablement flag. A UNC or network
media path is valid only when its resolved target is contained beneath at least
one active resolved approved root. If an active approved root itself resolves to
a UNC or network location, media contained beneath that root may be accepted.
Normal file existence, file-type, duplicate-path, symlink/junction, and
containment validation still applies. A UNC path outside both active approved
roots must be rejected because it is outside the approved roots, not merely
because it is a network path.

Mutation boundary: no mutation occurs. Validation must not rewrite, copy,
relocate, or import files.

A `ValidatedEpisodePlan` is validation at a point in time: deterministic
intent, not guaranteed historical reproducibility. V1 does not snapshot media
files, hash media files, persist the manifest, persist the validated plan, or
freeze active configuration. Media files, symlink targets, junction targets,
permissions, approved roots, and filesystem availability may change between
validation and execution. Resolve import and execution layers may still fail
after successful manifest validation, and runtime systems retain their existing
defensive checks. Callers should validate and execute within the same controlled
workflow where practical.

## Layer 6: Execution Validation

Owner: existing runtime subsystems, not pure manifest validation.

Checks owned by `EpisodeManager`:

- episode exists in SQLite;
- episode status permits build;
- assembled reruns are rejected;
- failed episodes are rejected under current V1 policy;
- status transitions and status-update failures are handled.

Checks owned by Resolve execution:

- Resolve adapter is connected;
- Resolve project can be loaded;
- media import succeeds;
- timeline operations succeed;
- marker insertion succeeds;
- clip placement succeeds.

Mutation boundary: execution may mutate SQLite and Resolve.

## Implemented Exception Taxonomy

The implementation defines a small typed hierarchy:

```text
ManifestError
├── ManifestLoadError
├── ManifestParseError
├── ManifestSchemaError
│   └── ManifestVersionError
└── ManifestValidationError
    └── ManifestPathError
```

`ManifestError`: base class for all manifest failures. Safe to catch broadly.
Occurs before mutation when used by loader/validator.

`ManifestLoadError`: file access problem. Typical causes: missing file,
permission error, unsupported extension, encoding failure. Should wrap the
original filesystem exception where useful. Safe to expose later through MCP
after path redaction policy exists.

`ManifestParseError`: YAML syntax or document-shape problem. Typical causes:
malformed YAML, empty document, multiple documents. Should wrap PyYAML parser
errors. Safe to expose with source location.

`ManifestSchemaError`: field-shape problem after YAML parsing. Typical causes:
missing required fields, unknown fields, wrong types, invalid nesting. Usually
wraps Pydantic validation errors. Safe to expose if messages do not leak local
paths unnecessarily.

`ManifestVersionError`: missing, non-integer, or unsupported schema version.
Subclass of `ManifestSchemaError`. Safe to expose.

`ManifestValidationError`: domain validation problem. Typical causes: invalid
episode ID shape, empty media list, invalid marker field, invalid bin name,
duplicate media paths. Safe to expose.

`ManifestPathError`: path safety or filesystem validation problem. Typical
causes: path outside approved roots, missing file, directory instead of file,
or duplicate normalized path. A UNC or network path outside approved roots is a
path-outside-root failure, not a categorical network-path failure. Should avoid
printing more filesystem detail than needed in future external APIs.

`ManifestTranslationError` is not required for the smallest V1 hierarchy.
Translation from a fully validated plan to `EpisodeBuildDefinition` should
normally be deterministic. A translation failure would likely indicate an
internal programming defect unless implementation discovers a realistic runtime
translation failure callers can handle.

YAML exceptions, Pydantic validation exceptions, and filesystem exceptions
should be wrapped with exception chaining where appropriate so original causes
remain available to logs and developers. Human-readable errors should include
relevant manifest field paths. A compact machine-readable error code is
acceptable in V1, but Redline OS should not build an MCP-specific error envelope
for the internal manifest implementation.

## Fail-Fast Versus Aggregate Policy

Recommended V1 policy:

- fail fast for file loading, YAML parsing, and unsupported schema version;
- schema validation may report multiple structured field issues;
- domain/path validation may aggregate independent issues where safe;
- dependent checks should not continue after prerequisite failures.

Aggregation should not become a large framework in V1. A practical list of
field/path errors is enough.

## Error Codes And Source Paths

Future errors should include stable machine-readable codes, such as:

- `manifest.file_missing`
- `manifest.yaml_invalid`
- `manifest.version_unsupported`
- `manifest.field_unknown`
- `manifest.media_empty`
- `manifest.path_outside_root`
- `manifest.path_duplicate`

Errors should also carry a source field path where possible:

```text
assembly.media[1].path
assembly.markers[0].frame
schema_version
```

Human-readable messages should stay clear and actionable. Future MCP exposure
should redact or summarize local filesystem paths when full paths are not
needed by the caller.

## Testing Implications

Unit tests should prove:

- valid readable YAML succeeds;
- missing manifest file fails;
- unreadable manifest file fails where practical;
- invalid encoding fails;
- empty file fails;
- practical file-size limit behavior if adopted;
- no Resolve calls during load/validation;
- no SQLite mutation during load/validation;
- malformed YAML fails;
- duplicate top-level YAML key fails;
- duplicate nested YAML key fails;
- multiple YAML documents fail;
- scalar root fails;
- list root fails;
- null root fails;
- non-string mapping keys fail;
- unsafe Python object tags fail;
- valid anchors/aliases behave as documented if supported;
- excessive alias behavior is guarded if a guard is adopted;
- empty document fails;
- missing `schema_version` fails;
- wrong `schema_version` type fails;
- unknown fields fail;
- unknown nested fields fail;
- unsupported versions fail;
- missing fields fail;
- missing `episode` fails;
- missing `episode.id` fails;
- malformed `episode.id` fails;
- missing `assembly` fails;
- missing `assembly.media` fails;
- malformed media entry fails;
- unknown media-entry field fails;
- omitted markers become an empty list;
- empty markers succeeds;
- malformed marker entry fails;
- unknown marker field fails;
- default bin name is applied;
- valid explicit bin name is preserved;
- invalid or empty bin name fails according to documented V1 policy;
- invalid marker frame fails;
- invalid marker color fails;
- invalid marker name fails;
- invalid marker note fails;
- media order is preserved;
- marker order is preserved;
- duplicate normalized paths fail;
- Windows case-collision duplicates fail;
- relative paths resolve from manifest directory;
- absolute paths resolve correctly;
- media under `ingest_path` succeeds;
- media under `assets_path` succeeds;
- media outside both approved roots fails;
- UNC/network media outside both approved roots fails as outside-root;
- UNC/network media under an active UNC/network approved root succeeds where
  practical;
- parent traversal outside approved roots fails;
- common-prefix sibling paths fail containment;
- directory paths fail;
- missing files fail;
- broken symlink fails;
- symlink escape fails where practical;
- junction escape fails where practical;
- relative configured roots are handled;
- manifest outside approved roots can reference valid media inside an approved
  root;
- empty media list fails;
- empty marker list succeeds;
- valid manifests translate to `EpisodeBuildDefinition` preserving order;
- episode ID is preserved in translation;
- bin name is preserved in translation;
- markers convert correctly;
- source manifest model is not mutated;
- validated plan is not mutated during translation;
- returned collections are copied or immutable according to the eventual
  implementation contract;
- failure does not mutate source objects;
- no EpisodeManager call occurs during parsing or validation;
- parse, schema, domain, and path failures perform no mutation.

Integration tests can later combine manifest validation with a temporary
filesystem, active configuration roots, and translation into the existing
`EpisodeBuildDefinition`. Later internal assembly integration should use mocked
managers first. Controlled live verification on 2026-07-27 covered one
disposable local approved-root workflow; UNC/network approved-root behavior,
symlink and junction platform variants, render/archive behavior, and persistence
remain outside the verified V1 surface.
