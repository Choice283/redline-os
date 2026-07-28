# Asset Registry Reconciliation Planning V1 Architecture

This document defines Milestone 10 Phase 3 architecture for read-only Asset
Registry reconciliation planning. It is architecture only. It does not add
production code, tests, schema changes, migrations, MCP behavior, Resolve
behavior, or plan-application behavior.

## Purpose

The reconciliation planner compares a caller-supplied immutable registry
snapshot with caller-supplied observed media facts and returns a deterministic
plan. The plan explains what appears unchanged, new, missing, moved,
conflicting, unsupported, or review-worthy.

The planner consumes facts. It does not collect observations and does not
execute proposed actions.

```text
observation
    -> matching
    -> classification
    -> proposed action
    -> later execution
```

## Non-Goals

Phase 3 does not:

- write to SQLite;
- mutate `AssetRegistryRecord` objects;
- move, rename, copy, delete, import, archive, render, or modify files;
- scan the filesystem directly;
- resolve arbitrary paths directly;
- calculate checksums or fingerprints unless supplied by the caller;
- persist or generate registry-side identity evidence;
- repair registry records automatically;
- infer creative intent;
- invoke `AssetManager` operations;
- call DaVinci Resolve;
- apply the plan it produces.

## Terminology

- **Registry record**: an immutable `AssetRegistryRecord` loaded from the
  persistent Asset Registry.
- **Registry snapshot**: a tuple of registry records plus snapshot metadata and
  optional detached identity evidence captured before planning.
- **Observation**: caller-supplied facts about one media candidate.
- **Observation scope**: caller-supplied, machine-evaluable statement
  describing which roots, subtrees, lifecycles, filters, or Asset IDs were
  expected to be observable.
- **Match evidence**: the reason one observation may correspond to one registry
  record.
- **Classification**: the primary reconciliation outcome for one plan item.
- **Finding**: a structured supporting fact. One item may have multiple
  findings.
- **Representable mutation proposal**: an inert action payload that a future
  apply phase could represent and review. It is not automatic application
  approval and does not execute anything.

## Observation Contract

Phase 3 should introduce an immutable observation type, provisionally named
`ObservedAsset`. Observations are produced by future scanners, ingest flows,
archive verifiers, manual tools, MCP callers, Resolve-aware tools, or tests.
The planner must treat observations as untrusted input and validate their
shape.

Recommended fields:

| Field | Required | Notes |
|---|---:|---|
| `observation_id` | Yes | Caller-provided stable ID unique within the request. Missing or duplicate IDs make request identity unusable and raise a request-level exception. |
| `source_id` | Yes | Caller-provided stable source instance ID. Required for claimed Asset ID evaluation. |
| `source_kind` | Yes | Stable enum such as `filesystem_scan`, `ingest`, `archive`, `manual`, `mcp`, `resolve`, or `test_fixture`. |
| `observed_at` | Yes | Caller-supplied UTC timestamp. The planner does not call the clock. |
| `observation_scope_id` | Yes | Links the observation to a declared scope. |
| `normalized_resolved_path` | Conditional | Required for path-based matching. Must already be produced by the approved path policy. |
| `resolved_path` | Optional | Sanitized display or diagnostic value. Full paths should be treated as sensitive. |
| `file_name` | Optional | Informational and weak evidence only. |
| `extension` | Optional | Informational and weak evidence only. |
| `availability` | Yes | Uses existing `AssetAvailability`; `available`, `missing`, and `non_file` are normal observations. |
| `verification` | Yes | Uses existing `AssetVerificationState`; normal completed observations use `verified`. |
| `file_size_bytes` | Optional | Required only when availability is `available` and supplied by the observer. |
| `file_modified_at` | Optional | UTC timestamp when supplied. |
| `file_created_at` | Optional | Platform-dependent; never definitive by itself. |
| `media_type` | Optional | Caller-supplied descriptive value, not creative authority. |
| `claimed_asset_id` | Optional | Caller-supplied Asset ID. Authoritative only under the request trust policy below. |
| `content_hash` | Optional | Strong evidence only when algorithm, normalized value, and comparable registry-side evidence are present. |
| `partial_fingerprint` | Optional | Review evidence, not definitive in V1. |
| `filesystem_identity` | Optional | Platform-dependent file ID, volume ID, inode, or similar. Not automatic V1 move evidence. |
| `diagnostics` | Optional | Tuple of structured, sanitized diagnostic facts. |

Prohibited observation behavior:

- observations must not contain mutable file handles, open database
  connections, raw SQLite rows, or executable callbacks;
- observations must not require the planner to touch the filesystem;
- observations must not ask the planner to resolve containment itself;
- observations must not contain full config documents or secrets.

Path facts must be validated before planning. Observations outside approved
roots, broken symlinks, symlink escapes, invalid UNC roots, inaccessible paths,
and unsupported path forms should arrive as either invalid observations or
observations with explicit diagnostic facts. The planner records those facts; it
does not re-run path policy.

Missing files, inaccessible files, directories, symlinks, broken symlinks,
network paths, and incomplete metadata are ordinary input cases. They become
plan findings unless the observation object itself is malformed.

## Trusted Asset ID Policy

Claimed Asset IDs are controlled by a request-level trust policy. The planner
must not maintain global source-trust configuration and must not infer trust
from strings, source names, filenames, caller type, or source kind.

Recommended enum: `AssetIdTrustPolicy`.

- `REJECT_ALL`
- `ALLOW_LISTED_SOURCES`

`ReconciliationRequest` must contain:

- `asset_id_trust_policy`;
- `trusted_asset_id_source_ids`, a tuple of non-empty, unique source IDs.

Each `ObservedAsset` may contain:

- `claimed_asset_id`;
- `source_id`.

Validation rules:

- empty `source_id` values are invalid observations;
- duplicate `trusted_asset_id_source_ids` entries are request-level validation
  errors;
- `claimed_asset_id` without `source_id` is a non-authoritative ID finding
  unless the observation is otherwise malformed;
- `source_id` not in the allowlist makes the claimed ID non-authoritative;
- malformed claimed Asset IDs are item-level `invalid_observation` findings
  when the observation has stable identity, otherwise request-level errors.

Matching rules:

1. A claimed Asset ID is authoritative only when the request policy is
   `ALLOW_LISTED_SOURCES`, the observation `source_id` is in the request
   allowlist, and the claimed Asset ID exists in exactly one registry snapshot
   record.
2. Under `REJECT_ALL`, supplied Asset IDs are not used for matching. The plan
   may preserve a non-authoritative-ID finding, but it must not reject an
   otherwise valid observation merely because it contains a claimed ID.
3. A trusted claimed Asset ID that does not exist produces
   `unknown_authoritative_asset_id`. It blocks fallback matching and mutation
   proposals for that observation.
4. A trusted claimed Asset ID pointing to record A while exact path points to
   record B produces `authoritative_identity_conflict`. Neither signal wins
   automatically.
5. A trusted claimed Asset ID may associate an observation with an existing
   record, including a possible path-change proposal, only when lifecycle rules
   permit it, no path or content evidence conflicts, the target path is valid,
   and review remains possible.

Trusted Asset IDs do not bypass lifecycle restrictions and do not override
conflicting path or content evidence.

## Registry Snapshot Contract

The planner should accept records already loaded by an orchestration layer. It
should not call `AssetRepository` directly.

Recommended type: `RegistrySnapshot`.

Required fields:

- `records`: tuple of `AssetRegistryRecord`;
- `identity_evidence`: tuple of `RegistryIdentityEvidence`;
- `schema_version`: expected to be `"1"`;
- `snapshot_id`: caller-supplied stable identifier;
- `snapshot_created_at`: caller-supplied UTC timestamp;
- `registry_id`: caller-supplied identifier for the database or logical
  registry;
- `approved_root_context`: stable caller-supplied root context or fingerprint
  when available;
- `repository_revision`: optional, because Phase 2 does not yet provide a
  durable revision token.

`RegistryIdentityEvidence` is detached supplemental input, not a Phase 2
database column. Recommended fields:

| Field | Required | Notes |
|---|---:|---|
| `asset_id` | Yes | References exactly one record in the snapshot. |
| `evidence_kind` | Yes | `full_content_hash`, `filesystem_identity`, or future approved kinds. |
| `algorithm` | Conditional | Required for hash evidence. |
| `normalized_value` | Yes | Canonical value for comparison. |
| `normalization_format` | Yes | Stable format identifier. |
| `scope_id` | Optional | Required when evidence has scope-dependent meaning. |
| `source_id` | Yes | Source that produced the evidence. |
| `observed_at` | Yes | UTC timestamp from the evidence source. |

Registry-side strong identity evidence rules:

1. It is supplemental detached input.
2. It is not a new Phase 2 schema column and does not alter
   `AssetRegistryRecord`.
3. Phase 3 does not persist or generate it.
4. The orchestration layer may load it from future providers, sidecars, prior
   verified scans, or other approved sources.
5. Absence of registry-side evidence is valid.
6. Strong-hash move matching is unavailable when comparable registry-side
   evidence is absent.
7. Evidence comparison requires the same `evidence_kind`, algorithm,
   normalization format, and compatible scope where applicable.
8. Opaque digest strings with different or missing algorithms are never
   compared.
9. Partial fingerprints are not definitive V1 identity evidence.
10. Filesystem identity may be recorded as evidence or a finding, but it must
    not independently authorize an automatic V1 path-update proposal.

For V1, the automatic moved-file identity rule is limited to a unique
full-content cryptographic hash with exactly one registry record carrying that
hash evidence, exactly one observation carrying the same algorithm and digest,
no Asset ID conflict, no exact-path conflict, a valid target path, and lifecycle
state that permits a proposal.

Checksum algorithm allowlists and numeric input limits are implementation
policy. The architecture requires algorithm-tagged evidence. Unsupported
algorithms produce unsupported-evidence findings rather than definitive
matches.

### Registry Identity-Evidence Validation

Detached registry evidence is validated before matching. The planner separates
snapshot-structural invalidity from contradictory but structurally valid
registry state.

Snapshot-level exceptions:

- an evidence row lacks stable evidence identity required for deterministic
  processing;
- `asset_id` is malformed;
- an evidence row references an Asset ID not present in
  `RegistrySnapshot.records`;
- required structural fields are absent;
- evidence collection limits are exceeded;
- canonical ordering or identity cannot be established;
- snapshot version is unsupported;
- snapshot invariants fail.

An orphaned evidence row for an unknown registry Asset ID raises
`registry_snapshot_invalid`. It is not an ordinary reconciliation item because
the evidence claims to describe registry state absent from the supplied
snapshot. Public exceptions use stable error codes, safe evidence or Asset IDs
where safe, no raw digest unless explicitly permitted, no raw database error,
no SQL, and no unnecessary absolute path.

Canonical registry evidence identity key:

```text
(
  asset_id,
  evidence_kind,
  canonical_algorithm,
  normalized_value,
  normalized_scope_id,
  normalized_source_id
)
```

Two rows with the same canonical key are exact duplicates. Exact duplicates are
deterministically deduplicated; they do not create multiple matches or conflict
items. Differing `observed_at` values do not make identical identity claims
distinct. If timestamp selection is needed, retain the latest supplied
`observed_at`; when timestamps are equal, use a stable canonical tie-breaker.
Deduplication must not depend on input order.

Same-record evidence conflicts:

- when one Asset ID has multiple comparable full-content evidence values for
  the same evidence kind, algorithm, and applicable scope, but the normalized
  digest values differ, classify `registry_identity_evidence_conflict`;
- neither digest is authoritative;
- that Asset ID is excluded from definitive strong-hash matching;
- planning may continue for unrelated records and observations;
- create a registry-record conflict plan item using `RegistryRecordSubject`;
- attach evidence references for the conflicting claims;
- require review;
- block path-update, verification-update, metadata-update, restoration, or
  missing proposals for that Asset ID when the conflict could affect them;
- exact-path association may still be reported as a fact but must not erase the
  identity-evidence conflict;
- weak evidence cannot resolve the conflict.

Multiple algorithms for one Asset ID are valid when every row is structurally
valid, every algorithm is supported or safely classified as unsupported, and no
two comparable rows for the same algorithm conflict. Compare observations only
against the same canonical algorithm. Algorithms do not vote against each
other. One supported matching algorithm may establish strong evidence only when
no comparable supported algorithm produces contradictory evidence. If
observation evidence matches one supported full-content algorithm for a record
but conflicts with another comparable supported full-content algorithm for the
same record, classify `content_conflict`. Unsupported algorithms are ignored
for definitive matching and represented as unsupported-evidence findings where
useful; unsupported evidence alone does not invalidate the snapshot.

Digest collisions:

| Collision | Outcome | Mutation Proposals |
|---|---|---|
| Same comparable full-content digest on multiple registry Asset IDs | `registry_identity_collision` using `RegistryRecordGroupSubject`; observations carrying that digest may become `ambiguous_match`. | None |
| Same comparable full-content digest on multiple observations | `ambiguous_match` or equivalent observation-group conflict using `ObservationGroupSubject` or `MixedConflictSubject`. | None |
| Same comparable digest non-unique on both sides | `MixedConflictSubject`, safe IDs in canonical order, no arbitrary pairings. | None |

Duplicate content does not imply duplicate asset identity. Collision handling is
deterministic and independent of input order.

| Condition | Outcome | Planning Continues | Eligible For Strong Matching |
|---|---|---:|---:|
| Evidence references unknown Asset ID | `registry_snapshot_invalid` exception | No | No |
| Malformed required evidence structure | `registry_snapshot_invalid` exception | No | No |
| Unsupported algorithm | Unsupported-evidence finding or unavailable evidence | Yes | No |
| Malformed digest for otherwise identifiable evidence row | Apply field-level invalidity tiers | Usually yes | No |
| Exact duplicate evidence row | Deterministic deduplication | Yes | Once |
| Same asset/algorithm conflicting digests | `registry_identity_evidence_conflict` item | Yes | No |
| Same digest on multiple registry records | `registry_identity_collision` item | Yes | No |
| Same digest on multiple observations | Ambiguous observation group | Yes | No |
| Same digest unique on both sides | Eligible strong association | Yes | Yes |
| No comparable registry evidence | No strong-hash association | Yes | No |

## Observation Scope Contract

`ObservationScope` must be immutable and machine-evaluable. A global
`complete=True` flag is insufficient and prohibited.

Recommended `ObservationScope` fields:

| Field | Required | Notes |
|---|---:|---|
| `scope_id` | Yes | Unique within the request. |
| `observed_at` | Yes | UTC timestamp for the scope. |
| `source_id` | Yes | Source that produced this scope declaration. |
| `roots` | Yes | Tuple of `ObservationRootScope`. Empty only for explicit Asset ID scopes. |
| `explicit_asset_ids` | Optional | Canonically sorted tuple for complete explicit-set scans. |
| `explicit_asset_id_completeness` | Conditional | `COMPLETE`, `INCOMPLETE`, or `UNKNOWN` when explicit IDs are supplied. |
| `explicit_asset_id_failures` | Optional | Per-Asset ID access or handling failures for explicit-set scans. |
| `inclusion_filters` | Optional | Machine-evaluable filters. |
| `exclusion_filters` | Optional | Machine-evaluable filters. |

Recommended `ObservationRootScope` fields:

| Field | Required | Notes |
|---|---:|---|
| `normalized_root_key` | Yes | Approved, normalized root key. |
| `completeness` | Yes | `COMPLETE`, `INCOMPLETE`, or `UNKNOWN`. |
| `inaccessible_subtrees` | Optional | Normalized subtree keys excluded by access failure. |
| `access_failures` | Optional | Structured failure codes and affected normalized subtree keys. |

Recommended `ObservationFilters` fields:

- `included_media_types`;
- `included_extensions`;
- `included_lifecycle_states`;
- `included_asset_ids`;
- `excluded_normalized_subtrees`.

Rules:

1. Completeness is evaluated per normalized root or subtree.
2. A registry record is expected to be observable only when its normalized path
   falls under one declared complete root or complete subtree, its path is not
   under an inaccessible or excluded subtree, it satisfies all inclusion
   filters, it is not excluded by any explicit filter, and its lifecycle is
   included where lifecycle filtering exists.
3. Mixed-root scans may contain both complete and incomplete roots.
4. Access failures reduce completeness only for the affected root or subtree.
5. A record outside all declared roots is not expected in scope.
6. A null or invalid registry path cannot be concluded missing from path scope.
7. An explicit Asset ID scope may prove expected observability independently of
   root scope only when the ID is explicitly included and the scan source
   reports complete handling for that explicit set.
8. Exclusions must be normalized and machine-evaluable.
9. Free-form scope notes cannot establish missing status.
10. Invalid observations cannot contribute evidence that a scope was complete.

Scope examples:

| Scope | Expected Missing Conclusion |
|---|---|
| Complete approved root | Records beneath that root may become `record_not_observed` when absent. |
| Complete subdirectory | Only records beneath the complete subdirectory are expected. |
| Filtered media scan | Only records satisfying declared media or extension filters are expected. |
| Inaccessible subtree | Records beneath the failed subtree are not marked missing. |
| Mixed complete/incomplete roots | Complete roots may prove absence; incomplete roots cannot. |
| Explicit asset subset | Only listed Asset IDs may be marked missing when explicit-set handling is complete. |

### Overlapping Scope And Filter Precedence

Scope resolution must not depend on implementation branch order. A record is
proven expected only when at least one applicable channel establishes complete
expected observability and no failure or exclusion invalidates that channel.
Only records proven expected may produce missing proposals.

Path-scope root selection for a registry record with a valid normalized path:

1. Find every declared root containing the normalized record path.
2. Select the most-specific matching root by longest normalized component
   depth, not longest raw string.
3. If roots have equal normalized depth and equivalent normalized keys, merge
   only when their declarations are identical; otherwise reject the request as
   structurally ambiguous.
4. Parent-root completeness does not override a more-specific child
   declaration.
5. Child-root completeness does not affect records outside that child.

| Parent Root | Child Root | Record Under Child | Path-Scope Result |
|---|---|---:|---|
| `COMPLETE` | `INCOMPLETE` | Yes | `INCOMPLETE` |
| `INCOMPLETE` | `COMPLETE` | Yes | `COMPLETE` |
| `COMPLETE` | `UNKNOWN` | Yes | `UNKNOWN` |
| `INCOMPLETE` | No child match | Yes | `INCOMPLETE` |

Within the selected root, apply only inaccessible and excluded subtrees
declared on that selected root. Choose the most-specific matching inaccessible
subtree when multiple entries overlap. Inaccessible means absence was not
proven; inaccessible records cannot receive `mark_missing`, and access failures
are findings, not evidence of deletion. V1 does not let unrelated root
declarations cancel or repair selected-root inaccessible state.

Exclusion wins over inclusion within the selected root:

- excluded subtree means out of expected-observation scope;
- exclusion is not an access failure;
- excluded records do not receive missing findings;
- exclusions must be normalized and validated upstream;
- a more-specific included root does not override an explicit selected-root
  exclusion in V1.

Inclusion filters are conjunctive across dimensions and disjunctive within one
dimension. For example, `included_media_types={video,audio}` and
`included_extensions={.mov,.wav}` means `(video OR audio) AND (.mov OR .wav)`.
Filters must not be interpreted as free-form predicates.

Path scope and explicit-ID scope are independent evidence channels. An
incomplete channel does not cancel an independently complete channel.
Record-specific access failures apply only to the channel that reported them
unless explicitly declared global.

Explicit Asset ID scope rules:

1. Listing an Asset ID alone does not prove complete handling.
2. Explicit scope establishes expected observability only when the ID exists in
   the snapshot, is listed, explicit-set completeness is `COMPLETE`, no
   explicit-item access failure exists, and no explicit exclusion applies.
3. Unknown explicit Asset IDs are request validation errors when the explicit
   set claims registry-record scope.
4. Duplicate explicit Asset IDs are canonically deduplicated.
5. Explicit ID scope can establish expectation independently of path-root
   completeness.
6. Explicit ID completeness does not make unrelated IDs observable.
7. An explicit ID with an invalid or null path may still be expected when the
   explicit-ID channel is complete.
8. If path scope is incomplete but explicit ID scope is complete, the explicit
   channel establishes expected observability for that listed ID.
9. If explicit item handling reports inaccessible, inaccessible wins for that
   explicit channel.
10. If explicit ID scope excludes the ID, exclusion wins.

| Situation | Expected Observable |
|---|---:|
| Complete parent, incomplete child, record under child | No |
| Incomplete parent, complete child, record under child | Yes |
| Complete root, inaccessible matching subtree | No |
| Complete root, excluded subtree | No |
| Complete root, media type filtered out | No |
| Complete root, extension included | Yes, if all other filters pass |
| Incomplete root, complete explicit-ID handling | Yes for listed ID |
| Complete root, explicit item inaccessible | No through explicit channel; path channel is evaluated independently |
| Unknown explicit Asset ID | Request validation error |
| Duplicate explicit IDs | Deduplicate |
| Null record path, complete explicit-ID handling | Yes for listed ID |
| Record outside roots and not explicitly listed | No |

## Matching Evidence

| Evidence | Strength | Definitive in V1 | Conflict Behavior | Notes |
|---|---|---:|---|---|
| Exact normalized path | Authoritative local path | Yes, absent authoritative contradiction | Conflicting records or observations produce duplicate or identity conflicts. | Uses existing normalized path keys. |
| Trusted claimed Asset ID | Authoritative external ID | Yes, when policy allows source and ID exists | Conflicts become `authoritative_identity_conflict`. | Redline OS does not validate external ID formats beyond non-empty strings. |
| Unique full-content hash | Strong detached evidence | Yes for moved-file proposals only under the V1 hash rule | Duplicate or contradictory hash evidence becomes review-required. | Hash must be supplied by caller and comparable to `RegistrySnapshot.identity_evidence`. |
| Filesystem identity | Local evidence | No for automatic V1 move proposals | Conflicts become review-required findings. | Platform-dependent and deferred for automatic matching. |
| Partial fingerprint | Probable evidence | No | Produces `ambiguous_match` or review finding. | Never automatic in V1. |
| Size plus file name | Weak heuristic | No | Produces bounded review-only finding. | Does not prove identity. |
| Size plus timestamp | Weak heuristic | No | Produces bounded review-only finding. | Timestamps are easy to change. |
| File name or extension only | Weak heuristic | No | Produces bounded review-only finding. | Useful for operator display only. |
| Media type | Informational | No | Never matches by itself. | Not creative authority. |

## Matching Conflict Matrix

Authoritative conflicts are not resolved by hierarchy order. Processing
precedence is only an evaluation order, not conflict resolution. Exact path
remains definitive only when no authoritative evidence contradicts it. Strong
hash never overrides a trusted Asset ID or exact-path conflict. Weak evidence
never resolves an authoritative conflict.

| Signal A | Signal B | Result |
|---|---|---|
| trusted Asset ID -> record A | exact path -> record A | association continues |
| trusted Asset ID -> record A | exact path -> record B | `authoritative_identity_conflict` |
| trusted Asset ID -> record A | unique strong hash -> record A | association continues |
| trusted Asset ID -> record A | unique strong hash -> record B | `authoritative_identity_conflict` |
| exact path -> record A | unique strong hash -> record A | association continues |
| exact path -> record A | unique strong hash -> record B | `content_conflict` |
| exact path -> record A | observed hash differs from record A evidence | `content_conflict` |
| trusted unknown Asset ID | any fallback signal | `unknown_authoritative_asset_id`; no fallback |
| duplicate observation path | any identity signal | `duplicate_path_conflict` blocks involved observations |
| duplicate registry path | any identity signal | `duplicate_path_conflict` blocks involved records |

## Matching Hierarchy

The planner evaluates evidence in this order:

1. Validate request, snapshot, scopes, and observations.
2. Group duplicates by observation ID and normalized path.
3. Evaluate trusted claimed Asset IDs under the request policy.
4. Match exact normalized path keys.
5. Match unique strong full-content hash when no authoritative conflict exists.
6. Collect bounded weak heuristic findings.
7. Classify unmatched observations and unmatched records using observation
   scope.

Definitive V1 matches:

- exact normalized-path equality with no authoritative contradiction;
- trusted claimed Asset ID that maps to exactly one record and does not
  conflict with path or hash evidence;
- unique full-content hash for move detection when exactly one record and one
  observation share algorithm-tagged comparable evidence and no path or ID
  conflict exists.

Probable matches are not automatically applied in V1. Weak evidence produces
review findings only.

### Implementation Note: Registry/Observation Identity-Key Bridge (Slice 7)

`RegistryIdentityEvidence` (registry-side, snapshot-supplied) carries a
`normalization_format` and an optional `scope_id` that `AssetObservation`
(caller-supplied) does not carry — the observation model was never given
those two fields, so the registry's full comparable-evidence key and the
observation's comparable-evidence key are structurally different shapes
(five components versus three). Strong-identity matching (`matching.py`)
resolves this by privately projecting every registry key down to the
three-component shape shared with the observation side, purely for
cross-referencing; it never modifies or replaces the registry's full key,
which remains authoritative for registry-internal indexing and collision
detection (`indexes.py`, unchanged by this slice). Two registry evidence rows
that differ only by `normalization_format` or `scope_id` are therefore
treated as the same identity once projected for this cross-side comparison —
a deliberate, disclosed loosening, since the caller-supplied side has no way
to express that distinction in the first place. If projecting a group this
way brings together more than one registry record for a single reduced key,
strong identity treats it as an ambiguous `registry_identity_collision`
rather than picking one arbitrarily.

## Classifications

One plan item has one primary classification and zero or more structured
findings. This avoids contradictory outcomes while preserving multiple facts.

| Classification | Preconditions | Primary Meaning | Proposed Action | Requires Review |
|---|---|---|---|---:|
| `unchanged` | Definitive match and material facts match. | Registry and observation agree. | `no_action` | No |
| `metadata_drift` | Definitive match, same identity/path, changed timestamp or non-conflicting metadata facts. | Registry facts are stale. | `update_observed_metadata` | Depends on source trust |
| `path_changed` | Unique strong identity evidence links one record to one observation at a different approved path. | Asset appears moved or relinked. | `propose_path_update` | Yes by default |
| `record_not_observed` | Record was expected in a complete scope and no matching observation exists. | Asset may be missing from observed set. | `mark_missing` | No for complete trusted scope; otherwise yes |
| `new_unregistered_observation` | Observation has no definitive or ambiguous registry match. | Candidate media is not registered. | `require_operator_review` or `register_candidate_from_observation` | Yes |
| `insufficient_scope` | Absence cannot be evaluated because scope is incomplete, unknown, inaccessible, or filtered out. | No missing conclusion is allowed. | `record_diagnostic_only` | No |
| `registry_identity_evidence_conflict` | One record has contradictory comparable full-content evidence. | Registry-side identity facts disagree. | `flag_conflict` | Yes |
| `registry_identity_collision` | Comparable full-content digest is non-unique across registry records. | Registry-side digest cannot identify one asset. | `flag_conflict` | Yes |
| `duplicate_identity_conflict` | Duplicate observation IDs or equivalent structural identity collisions. | Stable subject identity is impossible. | None for duplicate IDs; request exception | N/A |
| `duplicate_path_conflict` | Duplicate observation path or duplicate non-deprecated registry path. | Observation or registry path set is conflicting. | `flag_conflict` | Yes |
| `authoritative_identity_conflict` | Trusted Asset ID, exact path, or strong hash point to different records. | Authoritative signals disagree. | `flag_conflict` | Yes |
| `unknown_authoritative_asset_id` | Trusted claimed Asset ID is absent from snapshot. | Caller asserted an authoritative ID not known to registry. | `flag_conflict` | Yes |
| `multiple_observations_for_record` | More than one observation definitively matches one record. | Observation collision. | `flag_conflict` | Yes |
| `one_observation_multiple_records` | One observation definitively matches multiple records. | Identity collision. | `flag_conflict` | Yes |
| `ambiguous_match` | Bounded weak or non-definitive evidence suggests possible matches. | Human decision required. | `require_operator_review` | Yes |
| `unsupported_observation` | Observation is structurally valid but unsupported by V1. | Planner cannot use it for matching. | `ignore_unsupported` | No |
| `content_conflict` | Comparable verified full-hash evidence disagrees for same path, trusted ID, or matched record. | Possible replacement or wrong file. | `flag_conflict` | Yes |
| `size_conflict` | Same path or Asset ID but size differs without comparable hash evidence. | Review-required metadata/content drift. | `require_operator_review` | Yes |
| `lifecycle_conflict` | Observation conflicts with lifecycle policy, such as deprecated record observed as active candidate. | Lifecycle requires explicit decision. | `require_operator_review` | Yes |
| `availability_conflict` | Observation availability conflicts with stored state in a way that is not normal drift. | State needs review. | `require_operator_review` | Yes |
| `outside_approved_root` | Caller reports observation outside approved roots. | Unsafe for registry use. | `flag_conflict` | Yes |
| `invalid_observation` | Observation object violates contract but has stable subject identity. | Request contains bad isolated input. | None | Yes |

Request-level `invalid_request`, `registry_snapshot_invalid`, and
`repository_corruption` raise typed exceptions and do not produce a plan.

## Primary Classification Precedence

The highest applicable primary classification wins. All lower-ranked applicable
facts remain structured findings. Action proposals are derived only after the
primary classification and findings are finalized. Conflicting or ambiguous
classifications block automatic mutation proposals. Lifecycle and availability
facts remain visible even when content conflict is primary.

| Rank | Primary Outcome |
|---:|---|
| 1 | `invalid_request` exception, no plan |
| 2 | `registry_snapshot_invalid` exception, no plan |
| 3 | `invalid_observation` |
| 4 | `registry_identity_evidence_conflict` |
| 5 | `registry_identity_collision` |
| 6 | `duplicate_identity_conflict` |
| 7 | `duplicate_path_conflict` |
| 8 | `authoritative_identity_conflict` |
| 9 | `unknown_authoritative_asset_id` |
| 10 | `ambiguous_match` |
| 11 | `unsupported_observation` |
| 12 | `content_conflict` |
| 13 | `lifecycle_conflict` |
| 14 | `availability_conflict` |
| 15 | `size_conflict` |
| 16 | `path_changed` |
| 17 | `metadata_drift` |
| 18 | `unchanged` |
| 19 | `record_not_observed` |
| 20 | `new_unregistered_observation` |
| 21 | `insufficient_scope` |

Multi-conflict example: an observation exact-path matches a record, its
comparable verified full hash conflicts, the record is deprecated, and the
observation is inaccessible. The primary classification is `content_conflict`.
Findings include deprecated lifecycle and inaccessible or availability facts.
The proposed action is `require_operator_review` or `flag_conflict` according
to the action enum chosen by implementation. No metadata, path, availability,
or verification update proposal is allowed.

Size and hash treatment:

- size change with no comparable hash evidence is `size_conflict` or a
  review-required metadata/content-drift finding according to media rules;
- size change with matching verified full hash is `metadata_drift`, not content
  conflict;
- comparable verified hash mismatch is `content_conflict`;
- timestamp-only change is `metadata_drift`;
- extension or name-only change without identity proof is weak evidence or a
  path fact, not moved identity.

## Proposed Actions

Proposed actions are inert representable mutation proposals. They describe what
a future apply phase might do after approval and stale-plan checks.

Separate concepts:

- `proposal_kind`: stable action enum;
- `requires_review`: whether operator review is required before any future
  apply attempt;
- `automatic_application_eligibility`: always undecided in Phase 3 V1.

For Phase 3 V1, all proposals are inert and automatic application eligibility
is not decided. A future apply policy decides whether any proposal may be
executed automatically.

Representable mutation proposals:

- `no_action`;
- `update_observed_metadata`;
- `update_availability`;
- `update_verification_state`;
- `mark_missing`;
- `restore_available_status`;
- `propose_path_update`;
- `require_operator_review`;
- `flag_conflict`;
- `register_candidate_from_observation`;
- `ignore_unsupported`;
- `record_diagnostic_only`.

Prohibited V1 proposals:

- hard delete;
- filesystem move or rename;
- copy, download, transcode, import, archive, render;
- mutation of external Asset IDs;
- automatic creative approval;
- automatic path update from weak evidence.

## Plan Domain Model

Phase 3 should define immutable domain types without copying persistence models
unnecessarily.

Recommended types:

- `ObservedAsset`: one caller-supplied observation.
- `ObservationScope`: root, filter, lifecycle, and completeness boundaries.
- `RegistryIdentityEvidence`: detached evidence linked to records by Asset ID.
- `RegistrySnapshot`: records plus registry metadata and identity evidence.
- `ReconciliationRequest`: snapshot, observations, scopes, trust policy, input
  limits, candidate limits, and injected timestamps/IDs.
- `ReconciliationPlan`: immutable result with derived summary counts and items.
- `ReconciliationItem`: one primary classification, one tagged subject,
  evidence references, findings, and optional proposed action.
- `ReconciliationClassification`: enum listed above.
- `ReconciliationFinding`: structured supporting facts with stable codes.
- `ProposedAction`: enum plus optional action payload.
- `MatchEvidence`: signal type, strength, matched fields, and confidence.
- `MatchConfidence`: `definitive`, `strong`, `weak`, `ambiguous`, `none`.
- `ReconciliationDiagnostic`: sanitized diagnostic code and message.

Required invariants:

- all collections are tuples;
- all timestamps are UTC and caller-supplied;
- caller-generated IDs are unique within the request;
- planner-generated item IDs are deterministic, for example `item-000001`,
  after canonical ordering;
- one item has exactly one primary classification;
- each item has exactly one tagged subject;
- plan item IDs, evidence IDs, and action IDs are unique;
- plan counts are derived from items, never caller-supplied;
- input records and observations are never modified;
- action ordering is deterministic;
- weak evidence cannot produce a representable mutation proposal;
- empty plans are valid only for empty valid snapshots and observations or
  fully out-of-scope inputs.

Serialization should use stable enum string values, sanitized display paths,
record IDs or Asset IDs when safe, observation IDs, and summary counts. It
should not include raw database rows, full schema SQL, secrets, or full
configuration documents.

## Tagged Plan Subjects

Plan subjects are explicit tagged variants, not nullable ID bags.

Recommended tagged union: `ReconciliationSubject`.

| Variant | Fields | Allowed Classification Examples |
|---|---|---|
| `MatchedSubject` | `asset_id`, `observation_id` | `unchanged`, `metadata_drift`, `path_changed`, `content_conflict`, `lifecycle_conflict`, `availability_conflict`, `size_conflict` |
| `RegistryRecordSubject` | `asset_id` | `record_not_observed`, registry-only `insufficient_scope` |
| `ObservationSubject` | `observation_id` | `new_unregistered_observation`, `unsupported_observation`, isolated `invalid_observation`, `outside_approved_root`, `unknown_authoritative_asset_id` |
| `ObservationGroupSubject` | `observation_ids` | duplicate observation path conflicts |
| `RegistryRecordGroupSubject` | `asset_ids` | duplicate registry path conflicts |
| `MixedConflictSubject` | `asset_ids`, `observation_ids` | `authoritative_identity_conflict`, `one_observation_multiple_records`, `multiple_observations_for_record`, complex duplicate path conflicts |
| `RequestSubject` | `request_id` | request-level diagnostics only, never ordinary asset items |

Rules:

- variant tag is mandatory;
- IDs are non-empty, unique, and canonically sorted;
- a matched subject contains exactly one registry ID and one observation ID;
- group variants contain at least two IDs;
- mixed conflict contains at least one ID from both sides;
- request subject is used only for request-level diagnostics;
- no subject variant contains empty placeholder fields;
- public representations use safe IDs, not absolute paths.

## Structured Finding Contract

Recommended `ReconciliationFinding` fields:

| Field | Required | Notes |
|---|---:|---|
| `code` | Yes | Stable machine-readable code. |
| `severity` | Yes | `INFO`, `WARNING`, `CONFLICT`, or `ERROR`. |
| `subject` | Yes | Tagged `ReconciliationSubject`. |
| `evidence_refs` | Yes | Tuple of plan-local evidence IDs. |
| `safe_message` | Yes | Bounded sanitized message. |
| `requires_review` | Yes | Boolean. |
| `blocks_proposals` | Yes | Boolean. |
| `ordering_key` | Yes | Deterministic sort key. |

Findings are sorted by severity rank, code, subject key, and evidence IDs. They
must not embed raw exceptions or expose unnecessary absolute paths. Log-safe
diagnostics may retain additional internal context outside public
serialization.

## Plan-Local Evidence Contract

The planner converts input facts into immutable plan-local `PlanEvidence`
records. Observations and registry snapshots provide input facts; the planner
creates evidence IDs, authority, comparison results, and uniqueness results.
Input evidence IDs are not trusted as plan-local IDs. Caller-provided authority
or uniqueness claims are ignored unless planner validation derives the same
result.

Recommended `PlanEvidence` fields:

| Field | Required | Notes |
|---|---:|---|
| `evidence_id` | Yes | Stable plan-local ID, unique within one plan, assigned after canonical sorting. No random UUID. |
| `evidence_kind` | Yes | Closed enum or versioned stable code set. |
| `authority` | Yes | `AUTHORITATIVE`, `STRONG`, `WEAK`, `CONTEXTUAL`, or `UNSUPPORTED`, assigned by planner policy. |
| `source_kind` | Yes | `observation`, `registry_record`, `registry_identity_evidence`, `request_scope`, or `planner_derived_comparison`. |
| `source_id` | Yes | Safe stable source identifier, not an absolute path or raw database detail. |
| `subject` | Yes | One tagged `ReconciliationSubject` compatible with the source and item. |
| `algorithm` | Conditional | Required for hash or fingerprint evidence; absent for non-algorithmic evidence. |
| `normalized_value` | Conditional | Canonical internal comparison value; not automatically public. |
| `safe_summary` | Yes | Bounded sanitized display summary without uncontrolled metadata. |
| `comparison_result` | Yes | `NOT_COMPARED`, `MATCH`, `MISMATCH`, `INCOMPARABLE`, `UNSUPPORTED`, or `CONFLICTING`. |
| `uniqueness_result` | Yes | `NOT_APPLICABLE`, `UNIQUE_BOTH_SIDES`, `NON_UNIQUE_REGISTRY`, `NON_UNIQUE_OBSERVATION`, `NON_UNIQUE_BOTH_SIDES`, or `UNKNOWN`. |
| `observed_at` | Optional | Caller-supplied or source-carried timestamp; never from planner clock. |
| `public_visibility` | Yes | `PUBLIC_SAFE`, `REDACT_VALUE`, or `INTERNAL_ONLY`. |

Evidence kinds include claimed Asset ID, normalized path, full-content hash,
filesystem identity, file size, timestamp, filename, extension, media type,
scope completeness, access failure, lifecycle state, availability state, and
verification state.

Semantic evidence deduplication key:

```text
(
  evidence_kind_rank,
  authority_rank,
  subject_canonical_key,
  source_kind,
  normalized_source_id,
  canonical_algorithm_or_empty,
  normalized_value_fingerprint,
  comparison_result_rank,
  uniqueness_result_rank
)
```

Sensitive normalized values must not be exposed merely to create ordering keys.
A deterministic, versioned fingerprint of the canonical internal value may be
used for ordering or identity.

Deduplication rules:

- semantically identical plan-local evidence is emitted once;
- evidence referenced by multiple findings or actions may share one
  `evidence_id`;
- contradictory evidence is not deduplicated into one value;
- deduplication cannot depend on input order;
- for semantically identical claims differing only by `observed_at`, retain the
  latest supplied timestamp and use a stable tie-breaker when timestamps are
  equal;
- findings and actions reference evidence IDs rather than copying payloads.

Evidence ordering uses the deduplicated record after timestamp selection:

1. evidence-kind rank;
2. authority rank;
3. subject canonical key;
4. source-kind rank;
5. normalized source ID;
6. canonical algorithm;
7. safe internal value fingerprint;
8. comparison-result rank;
9. uniqueness-result rank;
10. timestamp;
11. deterministic tie-break key.

Sequential IDs such as `evidence-000001` are assigned only after canonical
sorting. No random UUIDs are used.

Public serialization has a separate public-safe evidence representation:

- raw absolute paths are excluded unless an explicitly approved safe display
  path exists;
- normalized path containment keys are not exposed by default;
- full digests are redacted by default;
- filesystem device and inode identifiers are redacted;
- secrets, credentials, raw exceptions, and uncontrolled metadata are
  prohibited;
- safe summaries have finite length;
- public-safe IDs remain stable within the plan;
- `INTERNAL_ONLY` evidence may be omitted from public output;
- omitted internal evidence must not leave dangling public references;
- public findings use safe surrogate references or omit internal references;
- public and internal schemas distinguish redacted value from missing value.

Evidence-reference invariants:

- every finding evidence reference resolves;
- every action evidence reference resolves;
- references are unique and canonically sorted;
- an item may reference evidence owned by its subject or by a compatible
  conflict-group subject;
- no finding references evidence from an unrelated item;
- deleting or redacting internal evidence cannot make public serialization
  structurally invalid.

Uniqueness is represented directly. Strong-hash path-change eligibility
requires `uniqueness_result = UNIQUE_BOTH_SIDES` plus existing no-conflict and
lifecycle conditions.

Evidence examples:

| Example | Kind | Authority | Subject | Source | Comparison | Uniqueness | Public |
|---|---|---|---|---|---|---|---|
| Trusted claimed Asset ID | claimed Asset ID | `AUTHORITATIVE` | `MatchedSubject` | observation | `MATCH` | `NOT_APPLICABLE` | `PUBLIC_SAFE` |
| Exact normalized path agreement | normalized path | `AUTHORITATIVE` | `MatchedSubject` | planner comparison | `MATCH` | `NOT_APPLICABLE` | `REDACT_VALUE` |
| Unique full-hash agreement | full-content hash | `STRONG` | `MatchedSubject` | registry/observation comparison | `MATCH` | `UNIQUE_BOTH_SIDES` | `REDACT_VALUE` |
| Full-hash mismatch | full-content hash | `STRONG` | `MatchedSubject` | planner comparison | `MISMATCH` | `UNKNOWN` | `REDACT_VALUE` |
| Non-unique registry digest | full-content hash | `STRONG` | `RegistryRecordGroupSubject` | registry identity evidence | `CONFLICTING` | `NON_UNIQUE_REGISTRY` | `REDACT_VALUE` |
| Non-unique observation digest | full-content hash | `STRONG` | `ObservationGroupSubject` | observation | `CONFLICTING` | `NON_UNIQUE_OBSERVATION` | `REDACT_VALUE` |
| Weak filename plus size | filename and size | `WEAK` | `MixedConflictSubject` | planner comparison | `NOT_COMPARED` | `NOT_APPLICABLE` | `PUBLIC_SAFE` |
| Inaccessible subtree | access failure | `CONTEXTUAL` | `RegistryRecordSubject` | request scope | `NOT_COMPARED` | `NOT_APPLICABLE` | `PUBLIC_SAFE` |
| Filesystem identity | filesystem identity | `CONTEXTUAL` | `MatchedSubject` | observation | `NOT_COMPARED` | `UNKNOWN` | `INTERNAL_ONLY` |
| Unsupported algorithm | full-content hash | `UNSUPPORTED` | `ObservationSubject` | observation | `UNSUPPORTED` | `UNKNOWN` | `REDACT_VALUE` |

## Action Invariants

- action subjects must agree with item subjects;
- `propose_path_update` requires one Asset ID, one observation ID, validated
  target normalized path, and definitive conflict-free identity;
- `mark_missing` requires a registry-record subject, complete scope evidence
  reference, and no matched observation;
- `register_candidate_from_observation` requires an observation subject and no
  definitive or ambiguous registry match;
- `restore_availability` requires a matched subject, observed accessible state,
  and lifecycle-compatible record;
- `update_verification_state` requires a matched subject and a transition
  permitted by existing Phase 1 verification rules;
- no automatic proposal is attached to conflict or ambiguity classifications.

## Determinism

The same snapshot and observations must produce the same semantic plan.

Deterministic rules:

- sort registry records by `asset_id`, then `record_id`, then normalized path;
- sort observations by normalized path, then claimed Asset ID, then
  observation ID;
- evaluate matching evidence in the fixed hierarchy above;
- sort findings by stable severity, code, subject key, and evidence IDs;
- sort plan items by primary-classification rank, Asset ID, normalized path,
  observation ID, and item ID;
- generate item IDs after sorting;
- use caller-supplied `plan_created_at`; do not call the clock;
- use injected ID factories only when deterministic output is not required.

Canonical item ordering:

1. request or incompatible snapshot blockers;
2. duplicate and conflict items;
3. definitive matched records;
4. missing expected records;
5. new observations;
6. unsupported, insufficient-scope, or informational observations.

## Duplicate Handling

- duplicate observation IDs are request-level validation exceptions because
  deterministic subject identity is impossible;
- duplicate normalized observation paths with distinct observation IDs produce
  local `duplicate_path_conflict` plan items affecting only those observations;
- duplicate non-deprecated registry normalized paths should be impossible after
  Phase 2 validation, but a corrupted snapshot may still be supplied. The
  planner reports `duplicate_path_conflict` and blocks proposals for those
  records;
- duplicate content hash does not imply duplicate Asset ID. Multiple approved
  assets may intentionally share content. Duplicate hashes become findings, not
  automatic merges;
- identity collisions such as one observation matching multiple records or one
  record matching multiple observations require review.

## Missing Scope

A record without a matching observation is not automatically deleted or
missing. The observation scope controls the allowed conclusion.

| Observation Scope | Record Expected in Scope | Observation Absent | Allowed Conclusion |
|---|---:|---:|---|
| Complete approved root or subtree | Yes, if filters include record | Yes | `record_not_observed`, may propose `mark_missing`. |
| Complete selected Asset ID scan | Yes, for selected IDs only | Yes | `record_not_observed`, may propose `mark_missing`. |
| Incomplete scan | Unknown | Yes | `insufficient_scope`; do not mark missing. |
| Unknown completeness | Unknown | Yes | `insufficient_scope`; do not mark missing. |
| Inaccessible root or subtree | No for affected paths | Yes | Availability unknown or infrastructure finding; do not mark missing. |
| Offline network root | No for affected paths | Yes | Availability unknown; do not mark missing. |
| Caller-filtered scan | Outside filter | Yes | No missing conclusion. |
| Deprecated-only excluded scan | Deprecated record | Yes | No missing conclusion. |
| Archive verification scope | Only archived subset | Yes | Scope-specific review; no general registry conclusion. |
| Null or invalid registry path | Unknown | Yes | No path-scope missing conclusion. |

## Lifecycle And Availability

The planner uses existing `AssetLifecycle`, `AssetAvailability`, and
`AssetVerificationState`. It does not redefine enum values.

| Registry State | Observation State | Classification | Proposal | Notes |
|---|---|---|---|---|
| active + available | available exact path | `unchanged` or `metadata_drift` | `no_action` or metadata update | Normal case. |
| active + available | absent in complete scope | `record_not_observed` | `mark_missing` | No delete. |
| active + missing | available exact path | `metadata_drift` | `restore_available_status` | File returned. |
| active + non_file | available exact path | `availability_conflict` | review or update availability | Depends on source trust. |
| declared + unknown | available exact path | `metadata_drift` | update verification or availability | Later apply may transition to active. |
| deprecated | observed | `lifecycle_conflict` unless a higher content or identity conflict applies | `require_operator_review` | No silent reactivation. |
| deprecated | absent | informational | `no_action` | Deprecated records are excluded unless scope includes them. |
| any valid state | outside approved root | `outside_approved_root` | `flag_conflict` | Path policy already produced diagnostic. |
| invalid combination | any | none | raise upstream domain error | Phase 1 constructors should reject this. |

Verification and metadata drift boundaries:

- Phase 3 may propose a verification-state change only when that transition is
  permitted by existing Phase 1 rules;
- Phase 3 does not invent new verification states;
- comparable verified hash mismatch creates `content_conflict`;
- comparable verified hash match may support verification evidence;
- missing hash does not imply verification failure;
- stale timestamp alone does not invalidate prior verification;
- size mismatch without comparable hash is review-required drift, not
  definitive corruption;
- metadata updates must list exact fields proposed;
- observed metadata must not overwrite caller-managed or creative metadata;
- path, lifecycle, availability, and verification proposals remain separate
  action types.

## Path-Policy Interaction

The planner must not create a second containment implementation. The existing
path-policy layer owns:

- path parsing;
- relative-path validation;
- symlink and junction resolution;
- approved-root containment;
- UNC/network path acceptance or rejection;
- case and separator normalization;
- normalized path-key creation.

Observations should carry `normalized_resolved_path` generated by the approved
policy. If the observation lacks a normalized path, the planner cannot use
path-based definitive matching. If the caller reports an outside-root or unsafe
path, the planner records `outside_approved_root` or `invalid_observation`
without attempting to repair it.

UNC/network observations are accepted only when the upstream path policy says
their resolved target is beneath an active approved root.

## Invalid Observation And Partial Success

The V1 planner supports isolated partial success.

Rules:

1. A structurally valid request may contain invalid individual observations.
2. Each invalid observation becomes an `invalid_observation` plan item when it
   has enough stable identity to isolate the failure.
3. Invalid observations do not participate in duplicate-path matching, Asset ID
   matching, exact-path matching, strong-evidence matching, or missing-record
   proof.
4. Valid unrelated observations continue through planning.
5. The entire request raises an exception only when request metadata is
   malformed, snapshot structure is malformed, observation IDs are missing in a
   way that prevents stable subject identity, configured limits are exceeded,
   duplicate observation IDs make deterministic subject identity impossible, or
   an internal invariant fails.
6. Duplicate observation IDs are a request-level validation exception, not
   ordinary plan findings.
7. Duplicate normalized paths with distinct observation IDs are plan conflicts
   affecting only those observations.
8. An invalid observation cannot contribute evidence that a scope scan was
   complete.
9. Missing-record proposals require scope completeness independent of invalid
   observations and must account for access failures.

### Field-Level Invalidity Tiers

Validation uses three deterministic tiers.

| Tier | Scope | Outcome |
|---|---|---|
| Tier 1 | Request or snapshot structural failure | Reject entire request or snapshot; no plan. |
| Tier 2 | Observation structural invalidity | Emit isolated `invalid_observation` item when a stable observation ID exists. |
| Tier 3 | Optional evidence-field invalidity | Ignore only the invalid evidence field, emit a finding, and continue with usable evidence. |

Tier 1 rejects the entire request when request identity is missing or
malformed, duplicate observation IDs prevent deterministic subjects,
observation IDs are missing, snapshot records have invalid structural identity,
registry evidence references unknown records, required scope structure is
malformed, supported version is absent or incompatible, finite limits are
exceeded, canonical deterministic processing cannot be established, or internal
invariants fail.

Tier 2 creates an isolated `invalid_observation` item when a stable observation
ID exists but a required observation field is invalid, such as a malformed
required normalized path fact for a file observation, structurally unsafe
unsupported observation type, missing required accessibility state, mutually
exclusive structural fields, malformed required source identity, or unparseable
metadata structure within allowed bounds. Tier 2 observations do not
participate in matching, prove presence, or prove completeness; unrelated valid
observations continue.

Tier 3 applies when an optional evidence field is malformed but the base
observation remains structurally usable. The planner ignores only that evidence
field for matching, preserves the usable observation, emits a structured
finding, continues with other valid evidence, does not turn malformed optional
evidence into an authoritative conflict, and does not silently treat malformed
evidence as absent without a finding.

| Invalid Field | Result |
|---|---|
| Malformed optional hash digest | Hash unavailable finding; valid path may still be used. |
| Unsupported hash algorithm | Unsupported-evidence finding. |
| Malformed optional filesystem identity | Ignore identity field with finding; retain observation. |
| Oversized optional metadata field | Drop or reject field with finding according to limit policy. |
| Malformed weak timestamp | Ignore timestamp evidence with finding. |
| Malformed claimed Asset ID from untrusted source | Discard claimed ID with non-authoritative invalid-claim finding; other matching may continue. |
| Malformed claimed Asset ID from allowlisted trusted source | `invalid_observation`; do not fall back to path or hash matching. |

## Errors And Diagnostics

| Condition | Exception | Plan Finding | Reason |
|---|---:|---:|---|
| Malformed request object | Yes | No | Caller contract violation. |
| Duplicate observation IDs | Yes | No | Stable subject identity is impossible. |
| Malformed snapshot structure | Yes | No | Snapshot cannot be trusted. |
| Orphaned registry identity evidence | Yes | No | Evidence references registry state absent from snapshot. |
| Invalid observation shape with stable ID | No | Yes | Isolated bad input supports partial success. |
| Optional evidence-field invalidity | No | Yes | Usable observation continues without invalid evidence. |
| Unsupported but valid observation | No | Yes | Planner can continue. |
| Ambiguous match | No | Yes | Ordinary reconciliation result. |
| Duplicate normalized path conflict | No | Yes | Operator-review condition. |
| Repository or persistence failure while loading snapshot | Yes upstream | No | Not a planning result. |
| Corrupt registry row rejected by repository | Yes upstream | No | Snapshot cannot be trusted. |
| Incomplete scan missing a record | No | Yes | Fail safe, no missing conclusion. |
| Stale plan at apply time | Future apply exception | No in Phase 3 | Apply is out of scope. |

Public errors must use stable, sanitized messages. They must not expose raw
database exceptions, full schema SQL, secrets, internal stack traces, or
unnecessary absolute production paths. Diagnostics should include stable codes,
safe IDs, and sanitized filenames when helpful.

## Transaction Boundary

Phase 3 is read-only. It should receive an immutable `RegistrySnapshot`.

Recommended orchestration:

1. caller opens a read transaction if needed;
2. caller reads repository records and detached identity evidence;
3. caller captures snapshot metadata;
4. caller closes the database transaction;
5. caller invokes the planner with the immutable snapshot and observations.

Plan application belongs to a later phase and requires a separate write
transaction design. A plan must not hold a database connection.

## Concurrency And Stale Plans

Phase 2 does not provide a durable registry revision token. Phase 3 should
therefore include metadata that a future apply phase can compare:

- `registry_id`;
- `schema_version`;
- `snapshot_id`;
- optional `repository_revision`;
- `snapshot_created_at`;
- `plan_created_at`;
- `observation_scope_id`;
- scan ID;
- approved-root context or fingerprint;
- desired observation fingerprint.

A later apply phase should add or obtain a reliable registry revision token so
stale plans can be rejected if the registry changes after planning.

## Performance And Weak Candidates

V1 assumes a single-process in-memory planner handling thousands of records and
thousands of observations.

The planner should avoid O(n^2) matching by building deterministic indexes:

- records by Asset ID;
- records by normalized path;
- observations by normalized path;
- observations by trusted claimed Asset ID;
- optional records and observations by comparable full-content hash evidence;
- optional filesystem identity indexes for findings only.

Weak evidence does not perform broad fuzzy matching. Candidate generation may
use only bounded indexed buckets such as normalized filename plus size, or
normalized filename alone when the bucket size is below a configured finite
limit. When a bucket exceeds the limit, the planner must not emit every
candidate. It emits one `weak_candidate_limit_exceeded` finding, requires
review, and continues deterministically. Weak evidence never creates
`path_changed`, never creates a mutation proposal, and must not scan all records
per observation.

Exact numeric defaults for input and candidate limits are implementation
constants, but V1 requires finite limits and deterministic truncation.

## Security

Observation input is untrusted. Phase 3 validation should reject or flag:

- oversized request collections beyond configured limits;
- malformed IDs, hashes, timestamps, and enum values;
- negative sizes;
- strings with leading/trailing whitespace where IDs are expected;
- control characters in diagnostic text;
- log-injection content;
- duplicate-ID attacks;
- path traversal attempts reported by upstream path policy;
- observations outside approved roots;
- pathological inputs that would force quadratic matching.

The planner should log counts and stable IDs rather than full paths. Full
absolute paths should be avoided in public diagnostics unless a future operator
surface explicitly marks them safe.

### Required Finite Limit Categories

Implementation must define finite positive limits for these categories. Exact
numeric values may be implementation constants, but defaults must be documented
in configuration or module documentation. Limits must be deterministic and
checked before expensive indexing or grouping where practical.

| Category |
|---|
| Observations per request |
| Registry records per snapshot |
| Registry identity-evidence rows |
| Observation evidence fields per observation |
| Identifier length |
| Request ID length |
| Observation ID length |
| Asset ID length |
| Source ID length |
| Scope ID length |
| Normalized path length |
| Safe display path length |
| Algorithm identifier length |
| Digest length |
| Metadata field count |
| Metadata key length |
| Metadata value length |
| Total metadata bytes per observation |
| Roots per scope |
| Inaccessible subtrees per root |
| Access failures per root |
| Inclusion filter values |
| Exclusion filter values |
| Explicit Asset IDs |
| Duplicate group size |
| Weak candidates per observation |
| Findings per item |
| Evidence entries per item |
| Actions per item |
| Total plan items |
| Total serialized public plan size |

Exceeding structural request or snapshot limits is a request exception.
Exceeding weak-candidate output limits is a bounded plan finding. Public error
messages must not echo oversized hostile inputs. Truncation is allowed only
where this architecture explicitly permits it. IDs, structural lists, and
authoritative evidence must not be silently truncated.

## Testing Architecture

Phase 3 should be primarily unit-testable without SQLite.

Unit tests:

- request-level trust policy validation;
- claimed Asset ID allowlist and rejection behavior;
- unknown authoritative Asset ID blocking fallback;
- authoritative ID, path, and hash conflict matrix;
- observation validation and isolated partial success;
- duplicate observation ID request rejection;
- duplicate normalized path local conflict;
- machine-evaluable scope coverage;
- complete root, complete subtree, filtered scan, inaccessible subtree,
  mixed-root scan, and explicit Asset ID scope;
- deterministic primary-classification precedence;
- exact path matches;
- strong-hash move with detached registry identity evidence;
- no strong-hash move when registry-side evidence is absent;
- orphaned registry identity evidence snapshot rejection;
- exact duplicate registry evidence deduplication;
- same-record conflicting registry evidence;
- registry-side and observation-side digest collisions;
- bounded weak candidate generation and limit-exceeded findings;
- new observations;
- missing records with complete scope;
- missing records with incomplete scope;
- overlapping root precedence;
- path scope versus explicit-ID scope interaction;
- field-level invalidity tiers;
- lifecycle, availability, size, hash, and verification interactions;
- invalid paths reported by upstream policy;
- unsupported observations;
- tagged subject invariants;
- structured finding ordering;
- action and count invariants;
- no mutation of inputs;
- stable repeated output;
- large-input complexity sanity;
- public error sanitization.

Integration tests:

- repository snapshot loading into immutable inputs;
- optional detached identity evidence supplied beside a snapshot;
- compatibility with `SQLiteAssetRepository` read ordering;
- temporary SQLite databases only;
- no production runtime database access;
- no Resolve interaction;
- future apply-phase stale-plan checks after that phase exists.

## Worked Examples

### 1. Trusted Asset ID And Same-Record Path Match

- Request: `ALLOW_LISTED_SOURCES`, trusted source ID `scan-a`.
- Registry: `RLG-001`, active, path `c:/assets/lower.png`.
- Observation: source `scan-a`, claimed ID `RLG-001`, path
  `c:/assets/lower.png`.
- Evidence: trusted Asset ID and exact normalized path both point to same
  record.
- Classification: `unchanged`.
- Proposed action: `no_action`.

### 2. Trusted Asset ID And Path Conflict

- Request: `ALLOW_LISTED_SOURCES`, trusted source ID `scan-a`.
- Registry: `RLG-001` at `c:/assets/a.mov`; `RLG-002` at
  `c:/assets/b.mov`.
- Observation: source `scan-a`, claimed ID `RLG-001`, path
  `c:/assets/b.mov`.
- Evidence: trusted ID points to `RLG-001`; exact path points to `RLG-002`.
- Classification: `authoritative_identity_conflict`.
- Proposed action: `flag_conflict`.
- Mutation proposal: none.

### 3. Unknown Trusted Asset ID

- Request: `ALLOW_LISTED_SOURCES`, trusted source ID `scan-a`.
- Registry: no record for `RLG-404`.
- Observation: source `scan-a`, claimed ID `RLG-404`, path
  `c:/assets/new.mov`.
- Classification: `unknown_authoritative_asset_id`.
- Proposed action: `flag_conflict`.
- Matching: no fallback to path, hash, or weak evidence for this observation.

### 4. Strong-Hash Move With Detached Registry Evidence

- Registry: `RLG-004`, active, available at `c:/assets/old.mov`.
- Registry snapshot identity evidence: `RLG-004`, `full_content_hash`,
  algorithm `sha256`, value `h1`.
- Observation: available at `c:/assets/new.mov`, `sha256` value `h1`.
- Evidence: unique comparable full-content hash, one record and one
  observation, no ID or path conflict.
- Classification: `path_changed`.
- Proposed action: `propose_path_update`.
- Review: yes by default.

### 5. No Registry Hash Evidence

- Registry: `RLG-005`, active, available at `c:/assets/old.mov`.
- Registry snapshot identity evidence: none.
- Observation: available at `c:/assets/new.mov`, `sha256` value `h1`.
- Evidence: observation hash has no comparable registry-side evidence.
- Classification: `new_unregistered_observation` or `ambiguous_match` if weak
  evidence exists.
- Proposed action: review only.
- Mutation proposal: no path update.

### 6. Path Match Plus Hash Conflict Plus Deprecated State

- Registry: `RLG-006`, deprecated, path `c:/assets/old.png`, detached
  `sha256` value `h1`.
- Observation: inaccessible file at the same path with comparable `sha256`
  value `h2`.
- Primary classification: `content_conflict`.
- Findings: deprecated lifecycle and inaccessible availability facts.
- Proposed action: `flag_conflict` or `require_operator_review`.
- Mutation proposal: no metadata, path, availability, or verification update.

### 7. Complete Root With Inaccessible Subtree

- Scope root: `c:/assets`, `COMPLETE`.
- Inaccessible subtree: `c:/assets/archive`.
- Registry: `RLG-007` under `c:/assets/archive`.
- Observation: absent.
- Classification: `insufficient_scope`.
- Proposed action: `record_diagnostic_only`.
- Missing proposal: none.

### 8. Mixed Complete And Incomplete Roots

- Scope root A: `c:/assets/current`, `COMPLETE`.
- Scope root B: `c:/assets/archive`, `INCOMPLETE`.
- Records absent under root A may be `record_not_observed`.
- Records absent under root B produce `insufficient_scope`.

### 9. Invalid Observation Isolated

- Request: structurally valid with observations `obs-1` and `obs-2`.
- `obs-1`: malformed hash but stable ID and scope.
- `obs-2`: valid exact-path match.
- Result: `obs-1` becomes `invalid_observation`; `obs-2` continues normally.

### 10. Duplicate Observation IDs

- Observations: two entries both use `observation_id=obs-1`.
- Result: request-level validation exception.
- Plan: none.

### 11. Duplicate Observation Paths

- Observations: `obs-1` and `obs-2` share normalized path
  `c:/assets/logo.png`.
- Result: local `duplicate_path_conflict` affecting only those observations.
- Proposed action: `flag_conflict`.

### 12. Weak Candidate Bucket Limit Exceeded

- Observation: filename `logo.png`, no trusted ID, no exact path match, no
  strong hash.
- Candidate bucket: many records share normalized filename `logo.png`.
- Result: emit one `weak_candidate_limit_exceeded` finding.
- Classification: `ambiguous_match` or `new_unregistered_observation`
  depending on implementation policy.
- Mutation proposal: none.

### 13. Orphaned Registry Identity Evidence

- Snapshot records: `RLG-013` only.
- Registry identity evidence: `asset_id=RLG-404`, `full_content_hash`,
  algorithm `sha256`, value `h1`.
- Result: `registry_snapshot_invalid` exception.
- Plan: none.

### 14. Exact Duplicate Registry Evidence Deduplicated

- Registry: `RLG-014`.
- Evidence rows: two semantically identical `sha256` full-content hash claims
  for `RLG-014`, value `h1`, same canonical source and scope.
- Result: one canonical evidence record after deterministic deduplication.
- Conflict: none.
- Strong matching: eligible once if observation-side evidence is also unique.

### 15. Same Asset And Algorithm With Conflicting Digests

- Registry: `RLG-015`.
- Evidence rows: `RLG-015`, `sha256=h1`; `RLG-015`, `sha256=h2`.
- Classification: `registry_identity_evidence_conflict`.
- Subject: `RegistryRecordSubject(RLG-015)`.
- Proposed action: `flag_conflict`.
- Strong matching: unavailable for that Asset ID.

### 16. Same Digest Across Two Registry Records

- Registry evidence: `RLG-016A`, `sha256=h1`; `RLG-016B`, `sha256=h1`.
- Observation: one file has `sha256=h1`.
- Classification: `registry_identity_collision` for registry records plus
  possible `ambiguous_match` for the observation.
- Subject: `RegistryRecordGroupSubject` or compatible `MixedConflictSubject`.
- Mutation proposal: none.

### 17. Same Digest Across Two Observations

- Registry evidence: `RLG-017`, unique `sha256=h1`.
- Observations: `obs-17a` and `obs-17b` both carry `sha256=h1`.
- Classification: `ambiguous_match` or equivalent observation-group conflict.
- Subject: `ObservationGroupSubject` or compatible `MixedConflictSubject`.
- Mutation proposal: no path update.

### 18. Collision On Both Sides

- Registry evidence: `RLG-018A` and `RLG-018B` both carry `sha256=h1`.
- Observations: `obs-18a` and `obs-18b` both carry `sha256=h1`.
- Classification: identity collision or `ambiguous_match` according to
  precedence.
- Subject: `MixedConflictSubject` with safe IDs in canonical order.
- Matching: no arbitrary one-to-one pairing.
- Mutation proposal: none.

### 19. Complete Parent With Incomplete Child

- Scope root: `c:/assets`, `COMPLETE`.
- Child scope root: `c:/assets/archive`, `INCOMPLETE`.
- Registry: `RLG-019` under `c:/assets/archive`.
- Observation: absent.
- Result: most-specific child controls; not proven expected.
- Classification: `insufficient_scope`.

### 20. Incomplete Parent With Complete Child

- Scope root: `c:/assets`, `INCOMPLETE`.
- Child scope root: `c:/assets/current`, `COMPLETE`.
- Registry: `RLG-020` under `c:/assets/current`.
- Observation: absent.
- Result: most-specific child controls; record is expected.
- Classification: `record_not_observed`.
- Proposed action: `mark_missing`.

### 21. Complete Path Scope Plus Explicit Item Failure

- Path scope: complete root includes `RLG-021`.
- Explicit-ID scope: `RLG-021` has an explicit item access failure.
- Result: explicit channel is not complete for that item; path channel is still
  evaluated independently.
- Missing proposal: allowed only if the path channel independently proves
  expected observability and no path-channel failure applies.

### 22. Incomplete Path Scope Plus Complete Explicit-ID Scope

- Path scope: incomplete root includes `RLG-022`.
- Explicit-ID scope: `RLG-022`, `explicit_asset_id_completeness=COMPLETE`.
- Observation: absent.
- Result: explicit-ID channel proves expected observability.
- Classification: `record_not_observed`.

### 23. Malformed Optional Hash With Valid Path

- Observation: exact path matches `RLG-023`; optional hash digest is malformed.
- Result: malformed hash evidence is ignored with a structured finding.
- Classification: path-based `unchanged` or `metadata_drift` according to other
  facts.
- Strong hash: unavailable.

### 24. Malformed Trusted Claimed Asset ID

- Request: `ALLOW_LISTED_SOURCES`, trusted source ID `scan-a`.
- Observation: source `scan-a`, malformed claimed Asset ID, otherwise valid
  path.
- Result: `invalid_observation`.
- Matching: no fallback to path or hash.

### 25. Evidence Public Redaction

- Evidence: normalized path key and full digest support a `content_conflict`.
- Internal plan: stores canonical comparison values.
- Public plan: uses stable evidence IDs and safe summaries with
  `public_visibility=REDACT_VALUE`.
- Result: no raw digest, normalized containment key, or unnecessary absolute
  path appears in public serialization.

### 26. Deterministic Evidence Deduplication And IDs

- Input: identical evidence rows supplied in different orders.
- Deduplication: one canonical evidence record remains.
- Ordering: canonical evidence sort runs before ID assignment.
- Result: both inputs produce the same `evidence-000001` style IDs and same
  plan semantics.

## Extension Points

Future phases may add checksum providers, filesystem scanners, media probes,
duplicate-content analysis, operator approval, plan application, audit history,
MCP tools, Resolve awareness, archive verification, and dashboard views. Those
extensions should feed observations or consume plans; they should not be mixed
into the pure planner.

Use protocols only for real substitution boundaries, such as a future
observation provider or plan serializer. Do not add plugin frameworks in V1.

## Deferred Decisions

Resolved for Phase 3 V1 architecture:

- trusted Asset ID behavior;
- minimum detached checksum evidence representation;
- invalid-observation behavior;
- primary-classification precedence;
- observation scope schema;
- plan subject representation;
- orphaned registry evidence behavior;
- exact duplicate registry evidence behavior;
- conflicting same-record hash evidence behavior;
- digest collision behavior;
- root overlap precedence;
- inclusion and exclusion precedence;
- path scope versus explicit-ID scope interaction;
- plan-local evidence fields;
- evidence deduplication, ordering, and public redaction;
- field-level invalidity tiers.

Deferred to implementation policy:

- exact supported checksum algorithm allowlist and implementation constants;
- exact numeric input and candidate limits.

Deferred to later reconciliation or apply phases:

- filesystem identity portability and reliability for automatic matching;
- durable registry revision-token design;
- operator approval workflow and UX;
- registration execution route;
- automatic-application policy.

## Phase 3 Implementation Boundaries

Phase 3 implementation should add planner domain types and a pure planner only.
It should not alter Phase 1 models unless a senior review approves extending the
domain surface. It should not alter Phase 2 persistence contracts. It should
not add SQLite writes, AssetManager orchestration, MCP handlers, Resolve calls,
configuration loading, runtime scanning, or documentation unrelated to
reconciliation planning.
