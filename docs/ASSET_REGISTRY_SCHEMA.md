# Persistent Asset Registry V1 Schema

This document describes the conceptual schema for Persistent Asset Registry V1.
It is not a SQL migration and does not modify `schema.sql`.

## Schema Goals

The schema should persist Redline OS local operational state for externally
approved assets while keeping external creative and production authority outside
Redline OS.

The schema should answer:

- which external Asset IDs Redline OS knows about locally;
- where each active V1 asset record expects one local file;
- which approved root contains the resolved path;
- what the last verification observed;
- whether a record is declared, active, missing, or deprecated;
- when the record was registered and last checked;
- where the declaration came from.

The schema should not store creative meaning, editorial role, licensing
interpretation, Broadcast Package redesign, Universe Bible content, or approval
decisions.

## Conceptual Table

Recommended table name: `asset_registry`.

Recommended V1 rule: one active registry record per external Asset ID and one
declared path per registry record. One Asset ID cannot have multiple active
local paths in V1. Two active Asset IDs may not resolve to the same normalized
path; reconciliation reports that as a conflict. Deprecated historical records
may retain formerly shared or reused paths. Aliases, variants, versions, asset
categories, and multiple local replicas are deferred.

## Proposed Fields

| Field | Type | Required | Mutability | Authority | V1 |
|---|---|---:|---|---|---:|
| `id` | integer | Yes | Immutable | SQLite | Yes |
| `asset_id` | text | Yes | Immutable | External standard | Yes |
| `declared_path` | text | Yes | Mutable by reconciliation | Config/declaration | Yes |
| `resolved_path` | text | No | Mutable by reconciliation or verification | Redline OS path policy | Yes |
| `approved_root_id` | text | Yes | Mutable if roots change | Redline OS config | Yes |
| `availability_state` | text | Yes | Mutable by verification | Filesystem observation | Yes |
| `verification_state` | text | Yes | Mutable by verification | Runtime verification | Yes |
| `lifecycle_state` | text | Yes | Mutable by lifecycle rules | Redline OS registry | Yes |
| `file_size_bytes` | integer | No | Mutable by verification | Filesystem observation | Yes |
| `file_modified_at` | text | No | Mutable by verification | Filesystem observation | Yes |
| `last_verified_at` | text | No | Mutable by verification | Runtime verification | Yes |
| `created_at` | text | Yes | Immutable | SQLite/registry | Yes |
| `updated_at` | text | Yes | Mutable on write | SQLite/registry | Yes |
| `source_kind` | text | Yes | Mutable by reconciliation | Redline OS registry | Yes |
| `source_detail` | text | No | Mutable by reconciliation | Redline OS registry | Yes |
| `diagnostic_code` | text | No | Mutable by validation | Redline OS registry | Yes |
| `diagnostic_message` | text | No | Mutable by validation | Redline OS registry | Yes |
| `checksum` | text | No | Deferred | Future verification | Deferred |
| `content_identity` | text | No | Deferred | Future verification | Deferred |
| `asset_type` | text | No | Deferred | External standard | Deferred |
| `version` | text | No | Deferred | External standard | Deferred |
| `variant` | text | No | Deferred | External standard | Deferred |
| `alias_of_asset_id` | text | No | Deferred | External standard | Deferred |

## V1 Field Precision

| Field | Purpose | Logical Type | Required/Nullable | Default | Update Rule | Index/Constraint |
|---|---|---|---|---|---|---|
| `id` | Internal persistence identity. | Integer | Required | SQLite generated | Never updated. | Primary key. |
| `asset_id` | Immutable external Asset ID. | Text | Required | None | Never updated; Asset ID changes are removal/deprecation plus new declaration. | Unique for active records. |
| `declared_path` | Durable portable path identity from config. | Text | Required | None | Updated only by explicit reconciliation path-change action. | Part of active same-path conflict checks after resolution. |
| `resolved_path` | Last resolved absolute operational path for diagnostics and verification. | Text | Nullable | Null | Recomputed during reconciliation or verification; invalidated by root/context changes. | Unique for active non-null normalized values. |
| `approved_root_id` | Root key that resolved path was checked under. | Text | Required | `assets_path` | Updated only when reconciliation validates against the active root. | Indexed for root-change audits. |
| `lifecycle_state` | Registry participation state. | Text enum | Required | `declared` | Updated by service transition rules only. | Indexed; constrained to `declared`, `active`, `deprecated`. |
| `availability_state` | Latest normal filesystem observation. | Text enum | Required | `unknown` | Updated by verification or root/context invalidation. | Indexed; constrained to `unknown`, `available`, `missing`, `non_file`. |
| `verification_state` | Latest verification completion state. | Text enum | Required | `unverified` | Updated only by completed verification attempts or infrastructure failure. | Constrained to `unverified`, `verified`, `failed`. |
| `file_size_bytes` | Observed file size. | Integer | Nullable | Null | Set on available regular-file observation; cleared or left null otherwise. | None in V1. |
| `file_modified_at` | Observed file modification timestamp. | Text timestamp | Nullable | Null | Set on available regular-file observation; cleared or left null otherwise. | None in V1. |
| `last_verified_at` | Time of completed verification attempt. | UTC text timestamp | Nullable | Null | Updated only after completed verification attempts. | Indexed for stale-verification queries. |
| `created_at` | Immutable first registration and persistence creation time. | UTC text timestamp | Required | Service operation time | Never updated. | None. |
| `updated_at` | Last persistent record mutation time. | UTC text timestamp | Required | Service operation time | Updated on every persistent mutation. | None. |
| `source_kind` | Provenance category. | Text enum | Required | `config` | Updated only by reconciliation/migration. | Constrained to V1-supported values. |
| `source_detail` | Short provenance detail. | Text | Nullable | `config/assets.yaml` for config reconciliation | Updated only by reconciliation/migration. | None. |
| `diagnostic_code` | Stable latest diagnostic result. | Text | Nullable | Null | Updated by validation, verification, or reconciliation outcomes. | Optional index if operator queries need it. |
| `diagnostic_message` | Sanitized latest diagnostic message. | Text | Nullable | Null | Updated with diagnostic code; no full production paths unless explicitly safe. | None. |

Enum values should be stored as stable text strings for SQLite portability.
`created_at` replaces a separate `first_registered_at` field in V1 to avoid
redundant timestamps.

## Field Details

### `id`

Internal database row identity. It is not the Asset ID, file identity, content
identity, or external approval record.

Validation: generated by SQLite.

### `asset_id`

Immutable external identifier approved outside Redline OS.

Validation: non-empty string. Any format validation must come from an existing
external Asset-ID contract. Redline OS must not invent a replacement standard.

Default: none; required on creation.

Constraint recommendation: unique among non-deprecated active records. Asset ID
changes are not updates; they are handled as removal/deprecation plus a new
declaration.

### `declared_path`

Portable root-relative file path declared by `config/assets.yaml` and
reconciled into the registry.

Default: none; required on creation.

Validation: non-empty relative path, not absolute, parseable as a filesystem
path, no traversal outside the resolved active asset root after combination and
resolution. Configuration filenames currently stored in `config/assets.yaml`
conform to this relative-path model.

Update rule: path changes update the same registry record only through explicit
reconciliation. The external Asset ID remains immutable.

### `resolved_path`

Last resolved absolute path used for containment checks, diagnostics, and
verification. It is operational state, not durable path identity.

Default: null until path resolution occurs.

Validation: resolved with platform-aware path handling and component-aware
containment. Raw string-prefix checks are prohibited.

Update rule: recomputed during reconciliation or verification. Root changes
invalidate trust in stored resolved paths; they must be recomputed before use.

### `approved_root_id`

Identifier for the approved root that contained `resolved_path` at the time of
validation. For V1 this is expected to identify `config.paths.assets_path`.

If root configuration changes, stored paths may become stale and should require
reconciliation or verification.

Default: `assets_path` for V1 records created from `config/assets.yaml`.

### `availability_state`

Current local availability derived from the latest filesystem observation.

Recommended values:

- `unknown`;
- `available`;
- `missing`;
- `non_file`.

Availability is point-in-time and must not be treated as permanent.
Unsafe paths are validation errors, not persisted availability values.

### `verification_state`

Result of the latest verification operation.

Recommended values:

- `unverified`;
- `verified`;
- `failed`.

Verification state should be separate from lifecycle state and availability
state.

### `lifecycle_state`

Registry-managed state for operator intent and policy.

Recommended values:

- `declared`;
- `active`;
- `deprecated`.

Lifecycle state is not the same as file availability. An active record may be
missing. A deprecated record may still point at a file.

### File facts

`file_size_bytes` and `file_modified_at` are observable file properties recorded
at verification time. They do not prove content identity. File replacement at
the same path may be suspected by changed size or modification time, but V1
does not prove replacement without checksum support.

### Timestamps

`created_at` is the immutable first registration timestamp and persistence
creation time. `updated_at` changes on persistent record mutation.
`last_verified_at` changes only after completed verification attempts.

All timestamps should use the repository's existing SQLite timestamp convention
unless a future architecture decision standardizes otherwise. Recommended V1
timestamp policy is UTC.

### Provenance

`source_kind` describes how the record entered the registry. Recommended values:

- `config`;
- `migration`;
- `test_fixture`.

`source_detail` may store a short user-safe detail such as `config/assets.yaml`.
It should not store entire config documents.

V1-created production records should use `source_kind = config` because
reconciliation is the only declaration-creation write path. `manual`, API, and
MCP registration provenance is deferred.

### Diagnostics

`diagnostic_code` should be stable and machine-readable. `diagnostic_message`
should be concise and user-safe.

Examples:

- `missing_file`;
- `path_outside_approved_root`;
- `duplicate_asset_id`;
- `non_file_path`;
- `stale_config_declaration`.

Diagnostics describe the latest relevant operational result, not an audit
history. Full audit-event tables are deferred to Build History or a later
registry milestone.

## Constraints

Recommended conceptual constraints:

- primary key on `id`;
- unique active `asset_id`;
- unique active normalized `resolved_path` when non-null;
- required `declared_path` and `approved_root_id`;
- constrained state values for availability, verification, and lifecycle;
- `updated_at` changes on mutation;
- no foreign key to episodes in V1.

`resolved_path` may be nullable before first successful resolution, so the
implementation should express requiredness as a domain invariant for records
that have completed reconciliation planning or verification. File facts are
nullable before successful observation.

No episode foreign key should be added for V1. The asset registry is not build
history and not episode placement intent.

## Indexes

Recommended conceptual indexes:

- `asset_id` for lookup;
- normalized active `resolved_path` for same-path duplicate conflict detection;
- `lifecycle_state` for active/deprecated filtering;
- `availability_state` for operator review;
- `last_verified_at` for stale verification queries;
- `approved_root_id` for root-change audits.

## Identity Separation

The schema must keep these concepts separate:

- external Asset ID;
- internal row ID;
- filesystem path;
- file identity;
- content identity.

They are not automatically equivalent.

V1 recommendation:

- one active record per external Asset ID;
- one declared path per registry record;
- one Asset ID cannot have multiple active local paths;
- two active Asset IDs may not resolve to the same normalized path;
- path changes preserve the external Asset ID but require revalidation and
  updated registry state;
- internal row IDs are persistence details and are not exposed as domain
  identity;
- path identity is not file identity;
- path identity is not content identity;
- without checksums, replacement of file content at the same path cannot be
  reliably identified;
- checksum, aliases, versions, variants, asset categories, and replicas are
  deferred.

## Example Records

Example active available record:

```text
id: 1
asset_id: RLG-001
declared_path: RLG-001_lower_third.png
resolved_path: C:\Redline\assets\RLG-001_lower_third.png
approved_root_id: assets_path
availability_state: available
verification_state: verified
lifecycle_state: active
file_size_bytes: 48211
file_modified_at: 2026-07-27T15:22:04Z
source_kind: config
source_detail: config/assets.yaml
diagnostic_code: null
```

Example missing active record:

```text
asset_id: RLG-003
availability_state: missing
verification_state: verified
lifecycle_state: active
diagnostic_code: missing_file
```

Example deprecated record:

```text
asset_id: RLG-002
availability_state: unknown
verification_state: unverified
lifecycle_state: deprecated
diagnostic_code: removed_from_config
```

## Migration Implications

Milestone 10 does not create migrations. Future implementation should decide
whether Redline OS continues the current `CREATE TABLE IF NOT EXISTS` pattern or
adds an explicit migration system before modifying production databases.

Implementation must not silently mutate existing databases at app startup beyond
the already documented schema initialization behavior. Registry table creation,
backfill, and reconciliation should be planned and observable.

## Deferred Schema Work

Deferred fields and tables:

- checksum table or checksum columns;
- aliases;
- variants;
- versions;
- many-path replica table;
- build-history links;
- episode usage records;
- creative metadata;
- external production-system sync metadata beyond basic provenance.
