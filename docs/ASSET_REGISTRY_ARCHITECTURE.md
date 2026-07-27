# Persistent Asset Registry V1 Architecture

Milestone 10 designs the first persistent Asset Registry for Redline OS. This
document is architecture only. It does not define implementation code, database
schema changes, migrations, tests, MCP changes, or Resolve behavior.

## Mission

Persistent Asset Registry V1 should give Redline OS a reliable operational
record of approved production assets that are expected to exist on the local
workstation or approved shared storage.

The registry records local operational state. It does not approve assets, define
creative meaning, invent Asset IDs, or replace the external Redline Production
System.

## Scope

V1 should cover:

- externally approved Asset IDs;
- local path declarations and resolved local paths;
- approved-root association;
- current file availability;
- point-in-time verification facts;
- lifecycle state;
- source/provenance;
- timestamps and diagnostic status;
- explicit config-to-registry reconciliation.

V1 should not cover:

- creative meaning or narrative role;
- brand interpretation or visual style standards;
- licensing decisions;
- approval workflow;
- aliases, variants, or multi-replica asset placement;
- checksum or duplicate-content detection;
- asset copying, moving, deletion, download, proxying, or transcoding;
- MCP, dashboard, render, archive, Resolve, or manifest implementation changes.

## Authority Model

Redline OS consumes external standards. It must not become a competing creative
or production authority.

| Source | Authority | Not Authority For |
|---|---|---|
| Redline Production System | Asset ID definition, approved metadata vocabulary, naming conventions, folder conventions, creative and production standards. | Local file availability, SQLite row existence, point-in-time filesystem observations. |
| `config/assets.yaml` | Desired-state declaration and explicit reconciliation input for Redline OS to ingest approved assets. | Persistent operational state after reconciliation, proof of file existence, creative approval. |
| SQLite registry | Redline OS local operational state: known Asset ID records, local path state, lifecycle state, verification state, timestamps, diagnostics. | External approval, creative metadata authority, file existence at future times. |
| Filesystem | Current physical existence and observable file properties at a verification moment. | Asset approval, historical reproducibility, permanent availability. |
| Runtime verification result | Point-in-time observation produced by a specific validation or reconciliation run. | Permanent proof that a file will exist later. |
| MCP presentation layer | Transport exposure for registry service operations in a future milestone. | Validation, lifecycle rules, persistence policy, filesystem policy. |

Approved repository contract for V1: the external Redline Production System
remains authoritative for Asset IDs and production standards. Persistent Asset
Registry V1 stores only Redline OS local operational and verification state.

## Founder Decision Status

Already resolved by repository contracts for V1:

- external Redline Production System standards own Asset IDs;
- Redline OS does not define, generate, reinterpret, or approve Asset IDs;
- Persistent Asset Registry V1 stores local operational and verification state
  only.

These are not implementation blockers after architecture approval.

Open expansion decisions:

- whether a later version stores broader approved production metadata;
- whether formal external documentation exists for Asset-ID format validation;
- whether formal external documentation defines approved asset categories.

Safe V1 fallback:

- treat Asset IDs as required opaque external identifiers;
- require non-empty string values;
- enforce uniqueness;
- do not validate a format that is not formally defined;
- defer asset type/category persistence unless supplied by an approved external
  source and required by a later approved milestone.

## Current State

`config/assets.yaml` currently lists approved Asset IDs, descriptions for
operator/debugging visibility, filenames relative to `config.paths.assets_path`,
and default assets required for each episode.

`AssetManager` currently owns:

- config-backed asset lookup;
- default required-asset lookup;
- joining `paths.assets_path` with configured filenames;
- basic filesystem `is_file()` checks;
- returning found and missing Asset IDs;
- raising `MissingAssetsError` for blocking callers.

`AssetManager` does not currently own:

- persistence;
- database transactions;
- durable lifecycle state;
- checksum or file identity;
- approved-root containment beyond the configured asset root;
- MCP transport rules;
- Resolve, media import, timeline placement, render, or archive behavior.

## Proposed Component Model

Recommended V1 design:

```text
External/config asset declaration
    -> AssetManager
    -> validation and reconciliation policy
    -> AssetRepository interface
    -> SQLite AssetRepository implementation
```

The minimal implementation direction after architecture approval should be:

- keep MCP handlers thin;
- keep config loading passive;
- add a repository boundary for persistent registry operations;
- let `AssetManager` orchestrate validation, filesystem observation, lifecycle
  transitions, reconciliation, and repository writes;
- keep SQL out of MCP handlers, config loaders, EpisodeManager, MediaManager,
  TimelineBuilder, and Resolve adapters.

V1 chooses this component model:

- `AssetManager`: the sole public core domain service for asset registry
  operations in V1. It owns public registry operations, orchestration,
  validation-policy coordination, reconciliation planning, reconciliation
  application, filesystem observation coordination, lifecycle-transition
  enforcement, conversion between domain models and repository inputs/results,
  operation-level logging, and service-level transaction scope.
- `AssetRepository`: the persistence boundary used by `AssetManager`. It owns
  persistent record reads and writes, SQLite query execution, database record
  mapping, transactional execution support, uniqueness checks, and persistence
  conflict reporting.
- SQLite repository implementation: the concrete repository behind the
  interface.

`AssetManager` must not contain raw SQL, own SQLite connections directly,
become an MCP-specific service, own Resolve behavior, move/copy/delete
production assets, or redefine external Asset IDs or standards.

`AssetRepository` must not own filesystem validation, path-policy decisions,
external Asset-ID rules, reconciliation policy, lifecycle decisions, or
service-level atomicity. Repository methods participating in a service-owned
transaction must not commit independently.

`AssetRegistry` is the conceptual subsystem name only. Do not introduce a
separate `AssetRegistry` service in V1.

## Dependency Direction

Allowed:

```text
MCP tools -> AssetManager -> AssetRepository -> SQLite
Config loader -> RedlineConfig
AssetManager -> RedlineConfig
AssetManager -> filesystem
```

Forbidden:

```text
SQLite -> AssetManager
Config loader -> SQLite registry mutation
MCP tools -> raw SQL
EpisodeManager -> raw asset registry SQL
ResolveAdapter -> AssetManager or AssetRepository
Manifest validator -> AssetRepository
```

## Registry Classification

The Persistent Asset Registry is an operational index with ledger-like
timestamps. It is not the creative catalog of record.

It may answer:

- what assets Redline OS currently knows about locally;
- where Redline OS expects a local file to be;
- when that file was last verified;
- what the last verification observed;
- whether the record is declared, active, deprecated, missing, or available.

It must not claim:

- that an Asset ID is externally approved merely because a row exists;
- that a file will still exist after verification;
- that file content is unchanged unless a future checksum feature proves it;
- that it owns creative metadata.

## Public API Recommendation

V1 should expose a small service API to core callers. MCP can wrap these methods
later without becoming part of the domain model.

| Operation | V1 | Behavior |
|---|---|---|
| `list_assets()` | Yes | Read registry records, optionally include last verification state. No filesystem mutation. |
| `get_asset(asset_id)` | Yes | Fetch one registry domain record by external Asset ID. |
| `verify_asset(asset_id)` | Yes | Resolve the asset path and inspect the current file, then update verification and availability state. Idempotent for unchanged state. |
| `plan_reconciliation(config_assets)` | Yes | Pure or non-mutating validation that returns a deterministic plan. |
| `apply_reconciliation(plan)` | Yes | Transactional registry writes from an approved plan. |
| `deprecate_asset(asset_id, reason)` | Yes | Explicit lifecycle transition. No normal hard delete. |
| `register_asset(...)` | No | Deferred. New V1 records are created only by applying explicit reconciliation plans. |
| `delete_asset(...)` | No | Deferred. Normal public hard deletion is prohibited in V1. |

Core APIs should return domain models or result objects, not raw SQLite rows and
not MCP-specific dictionaries.

Existing batch-style asset verification behavior can be preserved as a thin
compatibility wrapper over the V1 service, but the smallest complete persistent
registry API is the six-operation set above.

Assets absent from `config/assets.yaml` cannot be introduced through a separate
manual registration API in V1. Future manual, API, or MCP registration may be
added only if it uses the same declaration validation, path safety, identity,
lifecycle, reconciliation, and transaction rules.

## Persistence Boundary

The `AssetManager` service boundary owns:

- logical transaction scope for mutating service operations;
- reconciliation planning and staleness checks;
- path policy and filesystem observation coordination;
- lifecycle transition policy;
- deciding whether to call repository writes;
- operation-level logging.

The repository boundary owns:

- insert, update, and read queries;
- uniqueness constraints;
- transaction or unit-of-work mechanics requested by `AssetManager`;
- mapping SQLite rows to registry read models;
- handling SQLite failures with typed persistence errors.

Connection ownership should follow the current Redline OS database pattern:
the application context owns one connected database object, and higher-level
managers receive dependencies. A future implementation may extend the current
`Database` wrapper or add a dedicated repository object using the active
connection. Raw SQL must stay behind this boundary.

Current `Database` methods commit independently. Persistent Asset Registry
implementation must add or reuse a transaction-capable database/repository
mechanism rather than calling independently committing methods during
reconciliation.

## Configuration Relationship

`config/assets.yaml` is the desired-state declaration and explicit
reconciliation input for Persistent Asset Registry V1. Bootstrap describes only
the first use of reconciliation against an empty registry; it is not a separate
authority role.

Recommended V1 behavior:

- no startup mutation;
- explicit reconciliation command or service operation;
- dry-run reconciliation plan before writes;
- reads of persistent operational state come from SQLite registry records after
  reconciliation;
- configuration remains declarative input and provenance, not the runtime
  operational store;
- configuration changes have no persistent effect until explicit reconciliation
  is planned and applied;
- deterministic report of additions, unchanged records, path changes,
  conflicts, removals, invalid declarations, and deprecated candidates;
- no silent destructive deletion;
- removed config entries should not hard-delete records;
- path changes should require validation and update registry state
  transactionally;
- duplicate or conflicting Asset IDs should block the write plan.

When config and SQLite disagree, the service should report drift. It should not
silently choose one side and mutate state merely because the app started.
Direct SQLite modification outside the repository and `AssetManager` service
boundary is unsupported.

## Filesystem Boundary

For V1, `declared_path` is a non-empty relative file path declared relative to
the resolved active `config.paths.assets_path`. Absolute declared paths are
rejected. Asset files are expected beneath the active resolved
`config.paths.assets_path` unless future architecture explicitly adds more
approved asset roots.

Path resolution order:

1. Read active `config.paths.assets_path`.
2. Resolve the approved asset root.
3. Parse the relative declared path.
4. Reject absolute paths.
5. Combine root and declared path.
6. Resolve or normalize using the documented safety algorithm.
7. Perform component-aware containment.
8. Perform optional filesystem observation.
9. Preserve the original relative declaration.
10. Persist the root-relative declaration as durable path identity and store the
    last resolved path only as operational diagnostic/verification state.

Path policy should use component-aware containment. Raw string-prefix checks are
prohibited. A valid implementation should use `Path.is_relative_to()` or an
equivalent path-aware comparison after resolving the target and approved root.

The declared path remains the portable durable path identity. A stored resolved
path must be recomputed when the active asset root changes and must not be
trusted after configuration or environment changes without validation.

UNC and network paths are not controlled by a separate registry option. They are
valid only when the resolved target is contained beneath an active resolved
approved asset root. If the active approved asset root itself resolves to a UNC
or network location, assets contained beneath that root may be accepted. A UNC
path outside the active approved asset root must be rejected because it is
outside the approved root, not merely because it is a network path.

Filesystem observation is point-in-time. A registry row and a successful
verification do not prove future availability.

## Failure Behavior

The architecture should prefer all-or-nothing registry writes where practical.
Filesystem state cannot be transactionally rolled back, so the service must
record that verification is an observation, not a lock.

Required failure semantics:

- validate reconciliation inputs before writes;
- build an immutable reconciliation plan for mutating reconciliation;
- perform reconciliation validation and filesystem observation before opening
  the write transaction where practical;
- avoid holding SQLite write locks during filesystem scans;
- immediately before writes, check that the reconciliation plan is still current
  for the active database and approved-root context;
- apply registry writes for one reconciliation in one SQLite transaction;
- roll back registry writes on database failure;
- report partial filesystem observations without pretending they are durable;
- treat retry after failed writes as safe and deterministic;
- avoid hard deletion during reconciliation;
- preserve enough diagnostics for operator review.

V1 assumes one Redline OS process performs registry writes at a time unless the
repository can detect conflicts. SQLite locking errors should surface as
persistence failures. Concurrent verification and deprecation must not silently
overwrite newer state. Timestamps for one transaction should use one
service-supplied operation time where practical.

## Security And Production Safety

V1 should protect against:

- path traversal;
- sibling-prefix attacks;
- symlink or junction escapes;
- broken links;
- accidental production/test root mixing;
- duplicate Asset IDs;
- silent path replacement;
- hidden startup mutations;
- full production path leakage in routine logs.
- production/test database confusion;
- production/test approved-root confusion.

The registry must not move, delete, copy, download, transcode, import, archive,
or render asset files.

Test registries must use temporary or explicitly configured test SQLite
databases. Test roots must use temporary or explicitly configured test asset
directories. Tests must not use the active production asset root or write to the
production registry database. Reconciliation plans should identify the registry
and root context they were created against; applying a plan against a different
database or root context must be rejected as stale or incompatible.

## Observability

Registry operations should use structured logging with:

- operation name;
- Asset ID where applicable;
- lifecycle action;
- verification result;
- reconciliation counts;
- conflict counts;
- persistence result;
- duration where useful;
- sanitized path or filename when helpful.

Routine logs should avoid entire configuration documents, raw SQL, secrets,
and unnecessary full production paths.

## MCP Compatibility

Future MCP handlers should:

- validate transport inputs;
- call the registry service;
- translate typed domain results;
- translate typed errors;
- avoid direct SQL;
- avoid owning filesystem policy;
- avoid duplicating lifecycle rules.

Likely future MCP operations are listing registry assets, getting a registry
record, verifying assets, planning reconciliation, applying reconciliation, and
deprecating a record. All MCP implementation remains out of scope for Milestone
10 architecture.

## Deferred Work

Deferred beyond V1 architecture:

- implementation code;
- SQLite schema or migration files;
- tests;
- MCP exposure;
- dashboard/UI;
- direct public registration;
- reactivation;
- checksums and duplicate-content detection;
- aliases, variants, versions, asset categories, and multiple replicas;
- background watchers or scheduled scans;
- cloud storage or remote downloads;
- creative metadata and approval workflow;
- manifest asset-role semantics;
- render/archive/Resolve integration.
