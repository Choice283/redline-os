# Persistent Asset Registry V1 Validation

This document defines validation behavior for Persistent Asset Registry V1. It
is architecture only and does not add tests or implementation.

## Validation Layers

V1 should separate validation into these layers:

| Layer | Kind | Mutating | Notes |
|---|---|---:|---|
| Input/model validation | Pure | No | Required fields, types, empty strings, unknown fields if structured models are used. |
| External Asset-ID contract validation | Pure | No | Only checks rules supplied by the approved external standard. Redline OS must not invent a new Asset-ID format. |
| Path-policy validation | Filesystem/path dependent | No | Resolve paths and enforce approved-root containment. |
| Filesystem observation | Filesystem dependent | No by itself | Checks existence, regular file type, file size, and modification time. |
| Registry conflict validation | Persistence dependent | No | Detect duplicate Asset IDs, stale records, path conflicts, lifecycle conflicts. |
| Lifecycle transition validation | Persistence dependent | No | Confirms requested state transition is allowed. |
| Reconciliation validation | Mixed | No during planning | Produces a deterministic plan before writes. |
| Reconciliation apply | Persistence dependent | Yes | `AssetManager` applies an approved plan transactionally through `AssetRepository`. |

Validation should favor non-mutating planning before persistence changes.

## Asset-ID Validation

The external Redline Production System is authoritative for Asset IDs. Redline
OS may validate Asset-ID structure only when the external contract is already
known.

Safe V1 fallback: if no formal Asset-ID contract is available to the
implementation, V1 validates only that `asset_id` is a non-empty string and that
duplicate active IDs are rejected. The architecture should not invent a pattern
such as `RLG-###` unless that is confirmed as the external standard.

Asset IDs are immutable once registered. To replace an incorrect Asset ID,
deprecate the old record and create the correct externally approved ID through
explicit config reconciliation.

## Path Policy

For V1, the active approved asset root is `config.paths.assets_path`.
Additional asset roots are deferred unless approved by future architecture.
`declared_path` is a non-empty relative file path declared relative to that
root. Absolute declared paths are rejected in V1.

Path validation order:

1. Read active `config.paths.assets_path`.
2. Resolve the approved root.
3. Parse the relative declared path.
4. Reject absolute paths.
5. Combine root and declared path.
6. Resolve or normalize using the documented safety algorithm.
7. Perform component-aware containment.
8. Perform optional filesystem observation.
9. Preserve the original relative declaration.
10. Persist the root-relative declaration as durable path identity and store the
    last resolved path only as operational diagnostic/verification state.

Validation must:

- resolve the approved root;
- resolve the candidate path;
- use component-aware containment;
- reject absolute declared paths;
- reject raw string-prefix checks;
- reject traversal outside the approved root;
- reject sibling-prefix escapes;
- account for Windows case behavior in duplicate comparisons;
- treat broken symlinks as invalid;
- evaluate symlink or junction containment by resolved target where platform
  behavior permits.

Recommended containment rule:

```text
candidate_resolved.is_relative_to(approved_root_resolved)
```

or an equivalent path-aware implementation.

If the active approved root is:

```text
C:\media\approved
```

then this sibling is not contained:

```text
C:\media\approved-evil
```

## UNC And Network Paths

UNC and network paths are not controlled by a separate registry option.

A UNC or network asset path is valid only when its resolved target is contained
beneath an active resolved approved asset root. If the approved asset root itself
resolves to a UNC or network location, assets contained beneath that root may be
accepted.

A UNC path outside the active approved asset root must be rejected because it is
outside the approved root, not merely because it is a network path.

## Filesystem Observation

Filesystem observation should check:

- path exists;
- path is a regular file;
- size in bytes;
- modification timestamp;
- whether resolved target remains under the approved root.

Observation is point-in-time. A successful check does not prove future
availability or historical reproducibility.

V1 should not perform media inspection beyond basic file facts. Checksums are
deferred unless explicitly approved before implementation.

Normal verification outcomes for a valid registered record:

- file exists and is a regular file: `availability=available`,
  `verification=verified`;
- file is missing: `availability=missing`, `verification=verified`, diagnostic
  code such as `missing_file`;
- path exists but is not a regular file: `availability=non_file`,
  `verification=verified`, diagnostic code such as `non_file_path`.

These are domain results, not exceptions. Unexpected filesystem access or
permission failures are infrastructure failures and should be wrapped.

## Registry Conflict Validation

Registry validation should detect:

- duplicate active Asset IDs;
- duplicate active normalized resolved paths;
- config declarations that conflict with existing registry paths;
- registry records whose paths no longer match active config declarations;
- records removed from config;
- deprecated records that an operator tries to use as active;
- stale records after approved root changes.

Conflicts should be represented in a deterministic plan or typed error. The
service should not silently resolve conflicts by overwriting records.

## Config Reconciliation Validation

Reconciliation from `config/assets.yaml` is the only declaration-creation write
path in V1 and must be explicit.

Recommended phases:

1. Load current config normally.
2. Normalize declarations into stable declaration models.
3. Validate all declarations.
4. Read current registry state.
5. Build a deterministic reconciliation plan.
6. Return the plan for dry-run review.
7. Recheck that the plan is still current for the active database and approved
   root context.
8. Apply the plan transactionally only when requested.

Startup should not mutate the registry.

Plan results should include:

- new records;
- unchanged records;
- path changes;
- removed declarations;
- explicit deprecation candidates or deprecation actions;
- deprecated candidates;
- invalid declarations;
- conflicts;
- no-op entries;
- summary counts.

If any declaration is invalid or conflicting, the default V1 behavior should be
to block writes until the operator corrects the issue or explicitly chooses a
safe supported action.

Config additions may plan record creation. Config path changes may plan a path
update on the same registry record. Config removals do not automatically
hard-delete records. Asset ID changes are treated as one declaration removed and
another added; Asset IDs are never mutated. Ordering must be deterministic.
Stale plans must be rejected before writes. Applying the same successfully
applied plan twice must not duplicate records.

## Immutable Plan Recommendation

V1 should use a non-mutating reconciliation plan object before writes. This fits
the Episode Manifest V1 pattern of separating validated intent from mutation,
while staying simpler than manifest execution.

The plan should be deterministic and safe to log in summarized form. It should
not contain secrets or full configuration documents.

## Error Mapping

Recommended validation errors:

| Error | Layer | Meaning |
|---|---|---|
| `InvalidAssetDeclarationError` | Input/model | Declaration is malformed or missing required fields. |
| `InvalidAssetIdError` | Asset-ID contract | Asset ID violates known external contract. |
| `UnregisteredAssetError` | Registry lookup | Requested Asset ID is not registered for the operation. |
| `DuplicateAssetIdError` | Registry conflict | More than one active declaration or row claims an Asset ID. |
| `AssetConflictError` | Registry conflict | Config and registry disagree in a way that cannot be auto-applied. |
| `UnsafeAssetPathError` | Path policy | Path escapes approved roots or violates path policy. |
| `StaleAssetRecordError` | Registry conflict | Stored record is no longer compatible with active roots or declarations. |
| `InvalidAssetLifecycleTransitionError` | Lifecycle | Requested transition is forbidden. |
| `StaleReconciliationPlanError` | Reconciliation | Plan no longer matches active registry/config/root context. |
| `AssetPersistenceError` | Persistence | SQLite/repository operation failed. |
| `AssetReconciliationConflictError` | Reconciliation | Plan contains conflicts that block writes. |

Implementation should avoid too many near-duplicate exception classes. Related
errors may share a base type and stable diagnostic codes.

`MissingAssetFileError` and `NonFileAssetPathError` should not be used for
ordinary `verify_asset(...)` outcomes. If retained later, they must be limited
to operations that require immediate file availability as a precondition and
documented there.

Wrapped infrastructure failures require cause chaining, user-safe messages,
sanitized diagnostics, and future MCP translation that does not leak SQL or
internal exception details.

## Test Matrix

Future tests should cover the following after implementation is approved.

### Model And Domain Tests

- valid declaration;
- missing Asset ID;
- empty Asset ID;
- invalid external ID where a contract exists;
- unknown fields if strict models are used;
- invalid lifecycle state;
- forbidden lifecycle transition;
- allowed state combinations;
- forbidden state combinations;
- declared-to-active transition.

### Path Tests

- path inside approved root;
- path outside approved root;
- sibling-prefix escape;
- traversal escape;
- missing file;
- directory supplied as file;
- broken symlink;
- symlink escape;
- junction behavior where supported;
- Windows case normalization;
- UNC path under approved UNC root;
- UNC path outside approved root.

### Persistence Tests

- create record through reconciliation;
- duplicate Asset ID rejection;
- same-path duplicate conflict;
- get by Asset ID;
- list active records;
- update verification state;
- deprecate record;
- rollback on transaction failure;
- stale record handling;
- SQLite error wrapping;
- timestamp behavior;
- idempotent repeated verification.
- repository methods not independently committing inside reconciliation.

### Reconciliation Tests

- empty config;
- all declarations new;
- all declarations unchanged;
- path changed;
- declaration removed from config;
- duplicate config Asset IDs;
- invalid declaration among valid declarations;
- dry-run plan;
- stale reconciliation plans;
- plans bound to database and root context;
- no partial write on validation failure;
- deterministic ordering;
- direct registration unavailable in V1;
- Asset ID immutability.

### Architecture Isolation Tests

- no Resolve import;
- no EpisodeManager dependency;
- no MCP dependency in core registry service;
- no production filesystem mutation;
- no asset-file movement;
- no manifest schema dependency;
- no startup reconciliation;
- no startup mutation.

### Integration Tests

- temporary SQLite database;
- temporary approved asset root;
- temporary asset files;
- process restart preserves registry rows;
- missing-file transition;
- restored-file transition;
- active asset becoming missing;
- active asset becoming non-file;
- deprecated verification rejection;
- idempotent deprecation;
- explicit reconciliation apply;
- rollback of full reconciliation write set;
- no SQLite lock held during filesystem scanning;
- production/test database confusion;
- production/test root confusion;
- safe error cause chaining;
- sanitized diagnostics;
- structured logging fields.

Platform-specific tests for junctions, Windows case behavior, and UNC roots may
skip when the platform or test environment cannot create those conditions.

Test registries must use temporary or explicitly configured test SQLite
databases. Test roots must use temporary or explicitly configured test asset
directories. Tests must not use the active production asset root or write to the
production registry database. Live verification, if later required, must use
disposable test assets and an isolated registry database. No Resolve interaction
is required for Asset Registry V1 verification.

## Non-Goals

Validation does not:

- approve creative assets;
- redefine Asset IDs;
- guarantee future file availability;
- guarantee content identity;
- modify Resolve;
- import media;
- move, copy, or delete files;
- update SQLite except during explicit apply operations.
