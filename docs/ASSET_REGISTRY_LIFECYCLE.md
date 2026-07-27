# Persistent Asset Registry V1 Lifecycle

This document defines the proposed lifecycle behavior for Persistent Asset
Registry V1. It separates lifecycle intent, current availability, and
verification result so a single ambiguous status field does not hide important
differences.

## State Separation

The registry tracks three related concepts:

- lifecycle state: Redline OS policy and operator intent for a registry record;
- availability state: current filesystem observation;
- verification state: result of the latest verification operation.

These must not be treated as the same thing.

Example: an active asset can be missing after a later verification. A deprecated
asset can still exist on disk. A verified asset can become unavailable after
verification.

## Lifecycle States

Recommended V1 lifecycle states:

| State | Meaning |
|---|---|
| `declared` | A desired-state declaration has been reconciled into the registry, but the asset has not yet completed a successful file verification. |
| `active` | The asset has completed a successful verification as an approved-root-contained regular file and participates in normal registry use unless later deprecated. |
| `deprecated` | The record is intentionally excluded from normal active use and retained for history or operator awareness. |

Unsafe declarations or unsafe resolved paths are validation errors. They must
not be persisted as normal registry records or lifecycle states. `invalid` is
not a persistent V1 lifecycle state.

## Availability States

Recommended V1 availability states:

| State | Meaning |
|---|---|
| `unknown` | No current filesystem observation has been recorded, an infrastructure failure prevented observation, or a root/config change made the stored observation stale. |
| `available` | Latest verification found a regular file at the resolved path beneath the approved root. |
| `missing` | Latest verification did not find the file. |
| `non_file` | Latest verification found something other than a regular file. |

Availability is point-in-time. `unsafe_path` is not a V1 availability state;
unsafe paths are validation errors.

## Verification States

Recommended V1 verification states:

| State | Meaning |
|---|---|
| `unverified` | No verification has been run for the current declaration. |
| `verified` | Latest verification completed and produced a normal filesystem observation. |
| `failed` | Verification could not complete because of an infrastructure or persistence failure. |

Missing files and non-file paths are ordinary verification observations for
valid registered records. Infrastructure failures, such as permission errors or
unexpected filesystem errors, use `failed` with a diagnostic reason.

## Creation Transition

Declaration input comes from explicit reconciliation of `config/assets.yaml`.
Startup must not silently mutate the registry.

Recommended transition:

```text
no record
    -> declared
```

Creation requires:

- externally approved Asset ID;
- valid declaration fields;
- no active duplicate Asset ID;
- no active duplicate normalized resolved path;
- path-policy validation;
- repository transaction success.

## Verification Transition

Verification observes the filesystem and updates verification facts.

Successful file verification:

```text
declared or active
    -> active
availability_state = available
verification_state = verified
```

Missing file:

```text
declared or active
    -> same lifecycle state
availability_state = missing
verification_state = verified
diagnostic_code = missing_file
```

Non-file path:

```text
declared or active
    -> same lifecycle state
availability_state = non_file
verification_state = verified
diagnostic_code = non_file_path
```

Infrastructure failure:

```text
declared or active
    -> same lifecycle state
availability_state = unknown
verification_state = failed
diagnostic_code = infrastructure_failure
```

Unsafe path:

```text
declaration or path update
    -> validation error
    -> no normal registry record is created or updated
```

Verification should be safe to repeat. It must not move, copy, delete, import,
render, archive, or modify asset files.

## State Invariants

Allowed normal combinations:

| Lifecycle | Availability | Verification | Meaning |
|---|---|---|---|
| `declared` | `unknown` | `unverified` | Declaration was reconciled, no verification attempt completed. |
| `declared` | `missing` | `verified` | Valid path policy, but the file was missing during observation. |
| `declared` | `non_file` | `verified` | Valid path policy, but the target was not a regular file. |
| `declared` | `unknown` | `failed` | Verification could not complete because of infrastructure failure. |
| `active` | `available` | `verified` | Successful verification found an approved-root-contained regular file. |
| `active` | `missing` | `verified` | Previously active asset is currently missing. |
| `active` | `non_file` | `verified` | Previously active asset currently resolves to a non-file target. |
| `active` | `unknown` | `failed` | Previously active asset could not be checked because of infrastructure failure. |
| `deprecated` | any previous valid value | any previous valid value | Record is excluded from normal active use and preserves last observation. |

Recommended V1 rule: successful first verification transitions `declared` to
`active`. Later missing or non-file observations do not automatically change
lifecycle from `active`; availability and verification record the current
observation. This avoids treating temporary filesystem loss as lifecycle
invalidation.

Forbidden combinations:

- `declared + available + verified` after the service has completed the
  successful transition to `active`;
- `active + unknown + unverified`;
- any normal persisted record produced from an unsafe path;
- deprecated records silently returning to active because a file reappears;
- any lifecycle state outside `declared`, `active`, and `deprecated`;
- any availability state named `unsafe_path`.

Invariants should be enforced through domain constructors, service transition
rules, repository checks, and database constraints where practical.

## Missing-File And Restored-File Behavior

When a file disappears, the registry should preserve the record and mark
availability as `missing`. It should not delete or deprecate the record.

When the file returns and passes validation:

```text
declared or active + missing
    -> active + available
verification_state = verified
```

If the file returns at a different path, the path change must go through
reconciliation, not silent verification mutation.

## Path-Change Transition

Path changes should be explicit and observable.

Recommended flow:

```text
current registry record
    -> reconciliation plan shows path_changed
    -> validation succeeds
    -> stale-plan check succeeds
    -> transactional update
    -> availability_state = unknown or result of requested verification
    -> verification_state = unverified unless verification is part of the same operation
```

Path changes preserve the external Asset ID but do not prove file identity or
content identity.

## Deprecation Transition

Deprecation is an explicit lifecycle action.

```text
declared or active
    -> deprecated
```

Deprecation should:

- retain the registry record;
- preserve timestamps and diagnostics;
- remove the record from normal active-use queries by default;
- not delete files;
- not delete config entries;
- not rewrite external Asset IDs.

Hard delete is not part of the public V1 service API. Test fixtures may delete
isolated test rows as part of test cleanup. Deprecating an already deprecated
record with the same reason is idempotent.

## Reactivation

Reactivation is deferred from the public V1 API. A deprecated record must not
silently return to active because a file reappears or a config entry reappears.
Future reactivation must be explicit, logged, and subject to the same
declaration validation, path safety, identity, lifecycle, and transaction rules.

Verification of deprecated records is rejected by default. A future diagnostic
operation may allow read-only verification of deprecated records, but that is
not part of the V1 public API.

## Reconciliation Effects

Config reconciliation should produce a deterministic plan before writes.

Recommended plan actions:

- `add`: config has approved declaration absent from registry;
- `unchanged`: registry and config agree;
- `path_changed`: config path differs from registry path;
- `removed_from_config`: registry active record has no config declaration;
- `deprecate`: explicit action to mark a removed active record deprecated;
- `conflict`: duplicate or incompatible declaration;
- `invalid`: declaration fails validation;
- `noop`: no persistent change is required.

Apply behavior:

- validate the complete plan before writes;
- apply registry writes transactionally;
- block writes if conflicts or invalid declarations exist;
- never hard-delete removed records;
- mark removed active records as deprecated only if the applied plan explicitly
  includes that action;
- represent no-op entries explicitly;
- reject stale plans before writes;
- preserve deterministic ordering.

Config additions may plan record creation. Config path changes may plan a path
update on the same registry record. Config removals do not automatically
hard-delete records. Asset ID changes are treated as one declaration removed and
another added; Asset IDs are never mutated.

Applying the same successfully applied plan twice must not duplicate records.

## Forbidden Transitions

V1 should forbid:

- changing `asset_id` on an existing record;
- silent hard deletion through public API;
- automatic startup reconciliation that mutates SQLite;
- treating a SQLite row as proof of external approval;
- treating a successful verification as permanent availability;
- moving an asset file as part of registry verification;
- silently replacing one active Asset ID with another;
- verification of a path outside the active approved asset root;
- persisting an unsafe path as an ordinary availability state;
- silently returning deprecated records to active.

## Idempotency

Expected idempotent operations:

- listing registry records;
- getting one registry record;
- verifying unchanged available assets;
- verifying unchanged missing assets;
- verifying unchanged non-file observations;
- planning reconciliation against unchanged inputs;
- applying the same already-applied no-op reconciliation plan when current-state
  checks prove it is still safe;
- deprecating an already deprecated record with the same reason.

Non-idempotent or conditionally idempotent operations:

- creating a new record through reconciliation;
- applying a stale reconciliation plan;
- changing a path;
- future reactivation of a deprecated record;
- writes interrupted by process failure.

## Failure Recovery

Failure recovery rules:

- database write failure after filesystem verification leaves the filesystem
  untouched and the registry stale;
- process interruption during a transaction should leave either the old state or
  the committed new state, not a partial reconciliation;
- file removal after verification is expected time-of-check/time-of-use risk and
  should be caught by later verification or runtime checks;
- concurrent verification should be safe only when repository checks prevent
  overwriting newer lifecycle state;
- concurrent deprecation and verification should require repository-level
  conflict handling or lifecycle checks before committing.

