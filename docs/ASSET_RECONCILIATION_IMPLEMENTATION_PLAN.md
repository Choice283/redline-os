# Asset Registry Reconciliation V1 Implementation Plan

This document converts the approved Milestone 10 Phase 3 reconciliation
architecture into a module-by-module implementation map. It is planning only.
It does not add source code, tests, schema changes, configuration, SQLite
changes, Resolve behavior, staging, commits, or pushes.

Approved architecture baseline:

```text
4b703fa447f79b1f49b577f09ee66427192f3068 docs: define Asset Registry reconciliation architecture
```

## 1. Implementation Scope

Phase 3 implementation includes:

- Immutable reconciliation request types.
- Immutable observation types.
- Immutable scope types.
- Detached registry snapshot types.
- Detached registry identity-evidence types.
- Validation for requests, snapshots, observations, scopes, evidence, and
  finite limits.
- Canonicalization of already-normalized facts only.
- Registry indexes.
- Observation indexes.
- Scope indexes.
- Matching.
- Collision detection.
- Conflict analysis.
- Classification.
- Structured findings.
- Plan-local evidence.
- Inert actions.
- Deterministic evidence, action, and item IDs.
- Deterministic ordering.
- Plan summaries.
- Public-safe serialization.
- Unit tests.
- Limited snapshot-loading integration tests.

Phase 3 implementation excludes:

- Filesystem scanning.
- Path resolution.
- Approved-root validation.
- Hashing files.
- Reading metadata from files.
- SQLite mutation.
- Repository mutation.
- Action application.
- Asset registration execution.
- Operator approval workflow.
- Stale-plan enforcement.
- DaVinci Resolve integration.

The planner consumes caller-supplied immutable facts. It must not call
`AssetManager`, `AssetRepository`, `SQLiteAssetRepository`, `path_policy`, MCP
tools, Resolve adapters, or filesystem APIs during planning.

## 2. Proposed Module Structure

Create a new package:

```text
src/redline_core/asset/reconciliation/
    __init__.py
    enums.py
    limits.py
    models.py
    subjects.py
    evidence.py
    actions.py
    findings.py
    scope.py
    validation.py
    canonical.py
    indexes.py
    matching.py
    classification.py
    planner.py
    serialization.py
```

This creates 16 Python files, including package exports. The new package avoids
adding Phase 3 types to `src/redline_core/asset/models.py`, because that module
already contains the Phase 1/2 config reconciliation type
`AssetReconciliationPlan`. The Phase 3 public plan type should be named
`ReconciliationPlan` inside the subpackage and exported from
`redline_core.asset.reconciliation`.

### Dependency Direction

```text
enums / limits
    |
subjects / evidence / actions / findings / models
    |
canonical / validation / scope
    |
indexes
    |
matching
    |
classification
    |
planner
    |
serialization
```

Dependency inversion needed:

- `classification.py` should depend on an internal `ClassificationContext`
  assembled by `planner.py` or `matching.py`, not import planner internals.
- `findings.py` should expose factories and stable codes; matching and
  validation should request findings through those factories instead of
  constructing arbitrary prose.
- `evidence.py` should expose semantic evidence references that remain stable
  before final sequential evidence IDs are assigned.
- `serialization.py` may import public model types but must not be imported by
  domain modules.

### Module Map

| Module | Responsibility | Public classes/functions | Private helpers | Dependencies | Prohibited responsibilities | Expected tests |
|---|---|---|---|---|---|---|
| `__init__.py` | Minimal supported API exports. | `ReconciliationPlanner`, request/plan/snapshot/observation/scope types, public enums, public exceptions, `serialize_public_plan`. | None. | Public modules only. | Exporting internal state, builders, indexes, match state, classifier rules. | `tests/unit/asset/reconciliation/test_package_exports.py` |
| `enums.py` | Stable serialized value sets and rank helpers. | Phase 3 enum classes and rank maps. | `_stable_enum_values`, `_rank`. | Standard library enum only. | Redefining Phase 1 lifecycle, availability, verification enums. | `test_enums.py` |
| `limits.py` | Immutable limit policy and constants. | `ReconciliationLimitPolicy`, `DEFAULT_LIMITS`. | `_require_positive_limit`. | `dataclasses`. | Reading config or environment. | `test_limits.py` |
| `models.py` | Request, observation, snapshot, filters, summaries, plan item, plan. | `ReconciliationRequest`, `AssetObservation`, `ObservationScope`, `ObservationRootScope`, `ObservationFilters`, `ExplicitAssetAccessFailure`, `RegistrySnapshot`, `RegistryIdentityEvidence`, `ReconciliationPlanItem`, `ReconciliationPlan`, `PlanSummary`. | `_tuple`, `_require_utc`. | `enums`, `subjects`, `evidence`, `actions`, existing Phase 1 enums and `AssetRegistryRecord`. | Matching, filesystem work, SQLite work. | `test_models.py` |
| `subjects.py` | Tagged subject variants and subject invariants. | `RegistryRecordSubject`, `ObservationSubject`, `RegistryRecordGroupSubject`, `ObservationGroupSubject`, `MixedConflictSubject`, `PlanSubject`. | `_canonical_subject_key`. | `enums`. | Matching or classification logic. | `test_subjects.py` |
| `evidence.py` | Registry evidence structural validation and deduplication. The current implementation uses the bounded string evidence model for the Phase 3 critical path; no rich `PlanEvidence` extension is required. See architecture doc "Implementation Note: Documentation Reconciliation (Post-Slice 8)". | `validate_registry_identity_evidence`, `is_supported_registry_evidence_algorithm`. | `_validate_registry_identity_evidence_row`, `_require_snapshot_length`. | `enums`, `exceptions`, `limits`, `models`, `canonical`. | Evidence ID assignment, cross-item deduplication, matching/classification retrofits. | `test_evidence.py` (unchanged) |
| `actions.py` | Future / re-evaluate after `planner.py` and `serialization.py` are implemented. `ReconciliationPlanItem.actions` (models.py) is a plain `tuple[str, ...]` today; `planner.py` can populate it directly from `ClassificationDecision` data without a separate action-object system for the current critical path. Not removed from the roadmap. | — | — | — | — | — |
| `findings.py` | Future / re-evaluate after `planner.py` and `serialization.py` are implemented. Same rationale as `actions.py` — `ReconciliationPlanItem.findings` is a plain `tuple[str, ...]` today. Not removed from the roadmap. | — | — | — | — | — |
| `scope.py` | Scope indexes and observability decisions. | `ObservabilityDecision`, `evaluate_record_observability`. | `_containing_roots`, `_most_specific_root`, `_filter_result`. | `enums`, `models`, `canonical`, existing `AssetRegistryRecord`. | Resolving paths or testing containment from raw paths. | `test_scope.py` |
| `validation.py` | Validation coordinator and exceptions. | `validate_reconciliation_inputs`, public Phase 3 exceptions. | `_validate_request`, `_validate_snapshot`, `_validate_observation`, `_validate_scope`, `_validate_evidence`. | `enums`, `limits`, `models`, `canonical`, `findings`. | Planning, matching, filesystem, SQLite. | `test_validation.py` |
| `canonical.py` | Canonical keys for already-normalized facts. | Canonical key functions and safe fingerprint helper. | `_normalize_identifier`, `_normalize_algorithm`, `_hash_sensitive`. | `hashlib`, `enums`, `subjects`, `models`. | Path resolution, containment, symlink logic, raw string prefix checks. | `test_canonical.py` |
| `indexes.py` | Registry, observation, and scope index construction. | `RegistryIndexes`, `ObservationIndexes`, `ScopeIndexes`, `build_indexes`. | `_group_by`, `_detect_index_collisions`. | `models`, `canonical`, `validation`. | Classification or action generation. | `test_indexes.py` |
| `matching.py` | Deterministic association, collision, and match-state production. | `build_matching_state`, internal match-state dataclasses. | `_match_trusted_ids`, `_match_exact_paths`, `_match_identity_evidence`, `_weak_candidates`. | `indexes`, `evidence`, `findings`, `subjects`. | Final classification, public serialization, mutation. | `test_matching.py` |
| `classification.py` | Central ordered classification rules. | `ClassificationContext`, `ClassificationDecision`, `classify_item`. | `_RULES`, `_rule_*`. | `enums`, `matching`, `scope`, `findings`, `actions`. | Index construction or broad matching. | `test_classification.py` |
| `planner.py` | Orchestrate pure planning and invariant checks; assemble `ReconciliationPlanItem`/`ReconciliationPlan` directly from `ClassificationState`. Status: Implemented (Phase 3 Slice 9). | `plan_reconciliation` (module-level import only, `redline_core.asset.reconciliation.planner.plan_reconciliation` -- not re-exported at the package root, matching the Slice 5-8 precedent for `build_indexes`/`build_matching_state`/`classify_reconciliation`; no `ReconciliationPlanner` class exists). | `_assemble_items`, `_assemble_plan_evidence`, `_assemble_summary`, `_limit_policy_fingerprint`, `_verify_plan_invariants`. | `enums`, `exceptions`, `limits`, `models`, `validation` (`ValidatedReconciliationInputs` type only), `classification` (`ClassificationState` type only) for the current critical path; `findings`/`actions` remain future/re-evaluate (section 25 sequencing note) rather than required inputs. | Repository calls, filesystem calls, action execution, prematurely reintroducing a structured evidence/finding/action object system before a real requirement appears, package-root export ahead of the established Slice 5-8 precedent. | `test_planner.py` |
| `serialization.py` | Public-safe DTO/JSON-compatible serialization via an explicit structural allowlist. Status: Implemented (Phase 3 Slice 10). | `serialize_public_plan` (module-level import only, `redline_core.asset.reconciliation.serialization.serialize_public_plan` -- not re-exported at the package root, matching the Slice 5-9 precedent; no `PublicPlanSerializer` class exists). | `_serialize_plan`, `_serialize_item`, `_serialize_subject`, `_serialize_summary`, `_verify_output_invariants`. | `enums`, `exceptions`, `limits`, `models`, `subjects` (types only). | Default dataclass dumps, raw path/digest leakage, per-fact `PublicVisibility` redaction policy (structural allowlist only, per "Phase 3 Slice 10 Implementation Contract -- serialization.py, Revision 3"), re-running `planner.py`'s domain validation, package-root export ahead of the established Slice 5-9 precedent, exposing `RegistryRecordSubject.record_id`. | `test_serialization.py` |

## 3. Enum Map

Python `>=3.10` is required by `pyproject.toml`, so use `class X(str, Enum)`
instead of requiring `StrEnum`. `typing.TypeAlias`, `Literal`, union syntax
with `|`, and `dataclass(frozen=True, slots=True)` are compatible. Avoid
`typing.Self`, which is Python 3.11+.

| Enum or stable set | Values and serialized values | Module | Public | Rank requirements | Compatibility rules |
|---|---|---|---:|---|---|
| `AssetIdTrustPolicy` | `REJECT_ALL="reject_all"`, `ALLOW_LISTED_SOURCES="allow_listed_sources"` | `enums.py` | Yes | None. | Unknown values reject the request. |
| `ScopeCompleteness` | `COMPLETE="complete"`, `INCOMPLETE="incomplete"`, `UNKNOWN="unknown"` | `enums.py` | Yes | `complete` outranks only after most-specific-root selection. | Unknown values reject affected scope. |
| `ObservationKind` | `FILESYSTEM_SCAN="filesystem_scan"`, `INGEST="ingest"`, `ARCHIVE="archive"`, `MANUAL="manual"`, `MCP="mcp"`, `RESOLVE="resolve"`, `TEST_FIXTURE="test_fixture"` | `enums.py` | Yes | Stable alphabetical tie-break by value. | Does not imply trust. |
| `ObservationAccessibility` | `ACCESSIBLE="accessible"`, `MISSING="missing"`, `NON_FILE="non_file"`, `INACCESSIBLE="inaccessible"`, `UNSUPPORTED="unsupported"` | `enums.py` | Yes | Accessibility facts sort by severity. | Map to existing `AssetAvailability` where possible; do not replace it. |
| `PrimaryClassification` | `INVALID_OBSERVATION`, `REGISTRY_SNAPSHOT_INVALID`, `REGISTRY_IDENTITY_EVIDENCE_CONFLICT`, `REGISTRY_IDENTITY_COLLISION`, `AUTHORITATIVE_IDENTITY_CONFLICT`, `CONTENT_CONFLICT`, `DUPLICATE_PATH_CONFLICT`, `AMBIGUOUS_MATCH`, `UNKNOWN_AUTHORITATIVE_ASSET_ID`, `PATH_CHANGED`, `METADATA_DRIFT`, `LIFECYCLE_CONFLICT`, `AVAILABILITY_CHANGED`, `RECORD_NOT_OBSERVED`, `NEW_UNREGISTERED_OBSERVATION`, `UNCHANGED`, `INSUFFICIENT_SCOPE`, `UNSUPPORTED_OBSERVATION`, `DIAGNOSTIC_ONLY` with lowercase serialized values. | `enums.py` | Yes | Central precedence order in `classification.py`. | Additive future values only; stable values never renamed. |
| `FindingSeverity` | `INFO="info"`, `WARNING="warning"`, `ERROR="error"` | `enums.py` | Yes | `error`, `warning`, `info`. | Public. |
| `ActionKind` | `NO_ACTION`, `REGISTER_CANDIDATE`, `UPDATE_RESOLVED_PATH`, `UPDATE_AVAILABILITY`, `RESTORE_AVAILABILITY`, `MARK_MISSING`, `UPDATE_VERIFICATION_STATE`, `UPDATE_OBSERVED_METADATA`, `REQUIRE_REVIEW`, `FLAG_CONFLICT`, `DIAGNOSTIC_ONLY` with lowercase serialized values. | `enums.py` | Yes | Conflict/review actions sort before no-op. | Inert only in Phase 3. |
| `EvidenceKind` | `TRUSTED_ASSET_ID`, `NORMALIZED_PATH`, `FULL_CONTENT_HASH`, `FILESYSTEM_IDENTITY`, `PARTIAL_FINGERPRINT`, `FILE_SIZE`, `MODIFIED_TIME`, `METADATA`, `SCOPE`, `DIAGNOSTIC`, `LIFECYCLE`, `AVAILABILITY` with lowercase serialized values. | `enums.py` | Yes | Strong evidence sorts before weak and diagnostic evidence. | Unsupported future evidence becomes finding, not match. |
| `EvidenceAuthority` | `AUTHORITATIVE="authoritative"`, `STRONG="strong"`, `WEAK="weak"`, `DIAGNOSTIC="diagnostic"` | `enums.py` | Yes | Authoritative, strong, weak, diagnostic. | Authority is derived, not caller supplied. |
| `EvidenceSourceKind` | `REGISTRY_RECORD`, `REGISTRY_IDENTITY_EVIDENCE`, `OBSERVATION`, `REQUEST`, `SCOPE`, `DERIVED` with lowercase serialized values. | `enums.py` | Yes | None. | Used for public provenance without raw internals. |
| `ComparisonResult` | `MATCH="match"`, `MISMATCH="mismatch"`, `UNAVAILABLE="unavailable"`, `UNSUPPORTED="unsupported"`, `MALFORMED="malformed"` | `enums.py` | Yes | Mismatch outranks match for conflict checks. | Must be evidence-local. |
| `UniquenessResult` | `UNIQUE="unique"`, `NON_UNIQUE_REGISTRY="non_unique_registry"`, `NON_UNIQUE_OBSERVATION="non_unique_observation"`, `NON_UNIQUE_BOTH="non_unique_both"`, `NOT_APPLICABLE="not_applicable"` | `enums.py` | Yes | Non-unique both, registry, observation, unique, not applicable. | Used to block definitive strong matches. |
| `PublicVisibility` | `PUBLIC_VALUE="public_value"`, `SAFE_SUMMARY="safe_summary"`, `REDACT_VALUE="redact_value"`, `INTERNAL_ONLY="internal_only"` | `enums.py` | Yes | Internal-only evidence omitted from public serialization. | Defaults conservative. |
| `InvalidityTier` | `REQUEST="request"`, `SNAPSHOT="snapshot"`, `OBSERVATION="observation"`, `OPTIONAL_EVIDENCE_FIELD="optional_evidence_field"` | `enums.py` | Yes | Request/snapshot are fatal. | Mirrors architecture tiers. |
| `ConflictKind` | `AUTHORITATIVE_IDENTITY`, `CONTENT`, `DUPLICATE_PATH`, `REGISTRY_IDENTITY_EVIDENCE`, `REGISTRY_IDENTITY_COLLISION`, `OBSERVATION_IDENTITY_COLLISION`, `MIXED_IDENTITY_COLLISION`, `LIFECYCLE`, `SCOPE` with lowercase serialized values. | `enums.py` | Yes | Classification precedence decides primary. | Useful for grouping secondary findings. |

Do not redefine `AssetLifecycle`, `AssetAvailability`, or
`AssetVerificationState`; import them from `redline_core.asset.models`.

## 4. Immutable Domain Type Map

All Phase 3 domain types should be `@dataclass(frozen=True, slots=True)` unless
a standard-library `Protocol` or immutable tuple alias is a better fit. Mutable
input sequences must be converted to tuples in `__post_init__`.

| Type | Module | Fields | Required and defaults | Validation owner | Canonical key | Serialization | Relation to `AssetRegistryRecord` |
|---|---|---|---|---|---|---|---|
| `ReconciliationRequest` | `models.py` | `request_id`, `schema_version`, `created_at`, `observations`, `scopes`, `asset_id_trust_policy`, `trusted_asset_id_source_ids`, `limit_policy`, optional `request_metadata` | Required except metadata; default policy `REJECT_ALL`; default limits `DEFAULT_LIMITS`. | `validation.py` for whole request; constructor only immutability and cheap tuple conversion. | `(schema_version, request_id)` plus fingerprint of sorted observation/scope IDs. | Public safe metadata only. | Supplies facts only; no records. |
| `AssetObservation` | `models.py` | `observation_id`, `source_id`, `source_kind`, `observed_at`, `observation_scope_id`, `normalized_resolved_path`, `resolved_path`, `file_name`, `extension`, `availability`, `verification`, `file_size_bytes`, `file_modified_at`, `file_created_at`, `media_type`, `claimed_asset_id`, `content_hashes`, `partial_fingerprints`, `filesystem_identity`, `diagnostics`, `metadata` | Stable identity fields required; path and evidence optional by availability. | Tier 1 ID uniqueness in `validation.py`; Tier 2 shape validation in `validation.py`; optional evidence Tier 3 in `validation.py`. | Observation ID for identity; semantic keys for path/evidence. | Full paths and raw digests redacted unless visibility permits. | Represents caller-supplied current facts, not registry row state. |
| `ObservationScope` | `models.py` | `scope_id`, `observed_at`, `source_id`, `roots`, `explicit_asset_ids`, `explicit_asset_id_completeness`, `explicit_asset_id_failures`, `inclusion_filters`, `exclusion_filters` | `roots` may be empty only when explicit IDs supplied. | `validation.py`; evaluation in `scope.py`. | `scope_id`. | Safe IDs and redacted root keys. | Determines whether absent records may be considered missing. |
| `ObservationRootScope` | `models.py` | `normalized_root_key`, `completeness`, `inaccessible_subtrees`, `access_failures` | Root key and completeness required; tuples default empty. | `validation.py`; most-specific lookup in `scope.py`. | normalized root component tuple. | Root key fingerprint or safe summary. | Evaluated against `AssetRegistryRecord.normalized_resolved_path`. |
| `ObservationFilters` | `models.py` | `included_media_types`, `included_extensions`, `included_lifecycle_states`, `included_asset_ids`, `excluded_normalized_subtrees` | All default empty tuples. Empty means no filter in that dimension. | `validation.py` and `scope.py`. | Tuple of sorted dimensions. | Safe values only; subtree keys redacted. | Lifecycle filters compare to existing lifecycle enum. |
| `ExplicitAssetAccessFailure` | `models.py` | `asset_id`, `failure_code`, `safe_message` | All required. | `validation.py`. | `(asset_id, failure_code)`. | Safe message only. | Blocks explicit-ID completeness for that record only. |
| `RegistrySnapshot` | `models.py` | `records`, `identity_evidence`, `schema_version`, `snapshot_id`, `snapshot_created_at`, `registry_id`, `approved_root_context`, `repository_revision` | All required except `repository_revision`. | `validation.py`. | `(registry_id, schema_version, snapshot_id)`. | Safe metadata and counts. | Contains detached immutable `AssetRegistryRecord` tuple. |
| `RegistryIdentityEvidence` | `models.py` or `evidence.py` | `asset_id`, `evidence_kind`, `algorithm`, `normalized_value`, `normalization_format`, `scope_id`, `source_id`, `observed_at` | Algorithm required for hash evidence; scope required when kind needs scope. | Snapshot validation and evidence validation. | Architecture key: `(asset_id, kind, algorithm, normalized_value, scope_id, source_id)`. | Raw digest usually redacted. | Supplemental to records; never persisted in Phase 3. |
| `RegistryRecordSubject` | `subjects.py` | `asset_id`, optional `record_id` | Asset ID required. | Constructor plus `validation.py`. | `("registry_record", asset_id)`. | Asset ID safe when externally safe. | Directly references one record. |
| `ObservationSubject` | `subjects.py` | `observation_id` | Required. | Constructor. | `("observation", observation_id)`. | Safe. | Directly references one observation. |
| `RegistryRecordGroupSubject` | `subjects.py` | `asset_ids` | Non-empty unique tuple. | Constructor. | sorted tuple. | Safe IDs in canonical order. | Registry collision groups. |
| `ObservationGroupSubject` | `subjects.py` | `observation_ids` | Non-empty unique tuple. | Constructor. | sorted tuple. | Safe IDs in canonical order. | Observation duplicate/collision groups. |
| `MixedConflictSubject` | `subjects.py` | `asset_ids`, `observation_ids`, `conflict_kind` | At least one ID on each side for mixed collisions. | Constructor. | sorted IDs and kind. | Safe IDs only. | Used when no arbitrary pairings are allowed. |
| `PlanEvidence` | `evidence.py` | `evidence_id`, `kind`, `authority`, `source_kind`, `subject_refs`, `comparison_result`, `uniqueness_result`, `public_visibility`, `safe_summary`, optional `value_fingerprint`, `observed_at` | Final `evidence_id` assigned after canonical sort. | Evidence builder. | Semantic key before IDs; evidence ID after assembly. | Visibility controls value omission/redaction. | May cite registry records and observations without mutating them. |
| `ReconciliationFinding` | `findings.py` | `finding_id`, `code`, `severity`, `review_required`, `proposal_blocking`, `subject`, `evidence_refs`, `safe_message`, `invalidity_tier`, optional `conflict_kind` | Factory supplies templates and flags. | Finding factories and plan invariant checks. | `(subject_key, code, evidence_semantic_refs)`. | Safe message and evidence IDs only. | Explains registry/observation/scope facts. |
| `RegisterCandidateAction` | `actions.py` | `action_id`, `subject`, `observation_id`, `evidence_refs`, safe payload fields | Required only for new observation candidates. | Action factory. | action kind plus subject key. | No raw full path unless allowed. | Future apply may create records, but Phase 3 inert. |
| `UpdateResolvedPathAction` | `actions.py` | `action_id`, `asset_id`, `new_normalized_path_fingerprint`, `evidence_refs`, `requires_review` | Requires path-changed classification and strong evidence. | Action factory. | action kind, asset ID, target path fingerprint. | Redacted target. | Future apply may update record path. |
| `UpdateAvailabilityAction` | `actions.py` | `action_id`, `asset_id`, `availability`, `evidence_refs` | Requires compatible observation. | Action factory. | action kind, asset ID, availability. | Safe enum values. | Future apply may update availability. |
| `RestoreAvailabilityAction` | `actions.py` | `action_id`, `asset_id`, `evidence_refs` | Requires missing/non-file record now available. | Action factory. | action kind, asset ID. | Safe. | Future apply may restore active available state. |
| `MarkMissingAction` | `actions.py` | `action_id`, `asset_id`, `scope_evidence_refs` | Requires complete scope and absent observation. | Action factory. | action kind, asset ID. | Safe. | Future apply may mark missing. |
| `UpdateVerificationStateAction` | `actions.py` | `action_id`, `asset_id`, `verification`, `evidence_refs` | Requires compatible state transition. | Action factory. | action kind, asset ID, verification. | Safe enum values. | Future apply may update verification. |
| `UpdateObservedMetadataAction` | `actions.py` | `action_id`, `asset_id`, `metadata_keys`, `evidence_refs` | Only non-sensitive metadata keys. | Action factory. | action kind, asset ID, metadata key tuple. | Values redacted or summarized. | Future apply may update file facts. |
| `RequireReviewAction` | `actions.py` | `action_id`, `subject`, `reason_codes`, `evidence_refs` | Required for conflicts, ambiguity, unsupported facts. | Action factory. | action kind, subject, reason codes. | Safe. | No mutation. |
| `NoOpAction` | `actions.py` | `action_id`, `subject`, `reason_code` | Default for unchanged or diagnostic-only items. | Action factory. | action kind, subject, reason. | Safe. | No mutation. |
| `ReconciliationPlanItem` | `models.py` | `item_id`, `subject`, `primary_classification`, `findings`, `evidence_refs`, `actions`, `requires_review`, `proposal_blocked` | Final ID assigned after canonical sort. | `planner.py` invariant validation. | subject key plus classification and evidence/action refs. | Public serializer controls nested output. | One item may reference records, observations, or conflict groups. |
| `PlanSummary` | `models.py` | Counts by classification, severity, action kind, review-required, proposal-blocked, invalid-observation, conflict, unmatched | Derived only. | `planner.py`. | Derived from final items. | Public. | No independent authority. |
| `ReconciliationPlan` | `models.py` | `plan_id`, `schema_version`, `request_id`, `snapshot_id`, `registry_id`, `created_at`, `items`, `evidence`, `summary`, `limit_policy_fingerprint`, `approved_root_context`, optional `repository_revision` | Returned only when fatal validation passes. | `planner.py`. | Deterministic content fingerprint excluding `created_at` if caller time is fixed. | Use `serialization.py`; no default dataclass dump. | Contains no mutable records. |

Public-safe serialized representations should be DTO dictionaries produced by
`serialization.py`, not separate mutable domain classes unless tests show that
explicit DTO dataclasses reduce risk.

## 5. Exception Map

Phase 3 exceptions should inherit from existing `AssetRegistryError` and use
stable `error_code` plus sanitized context. Add them in
`src/redline_core/asset/reconciliation/validation.py` or a new
`exceptions.py` inside the subpackage if the implementation wants clearer API
exports. Prefer `reconciliation/exceptions.py` if more than three public
classes are needed.

| Exception | Parent | Error code | Sanitized fields | Prohibited raw fields | When raised | Plan returned |
|---|---|---|---|---|---|---:|
| `InvalidReconciliationRequestError` | `AssetRegistryError` | `invalid_reconciliation_request` | `request_id`, `field`, `limit_name`, counts | Full paths, raw digests, raw metadata | Malformed request, duplicate trusted sources, missing request identity, request limits. | No |
| `InvalidRegistrySnapshotError` | `AssetRegistryError` | `registry_snapshot_invalid` | `snapshot_id`, `registry_id`, safe Asset ID, evidence index | SQL, raw database errors, raw digests | Malformed snapshot, orphaned evidence, unsupported snapshot version, snapshot invariants. | No |
| `UnsupportedReconciliationVersionError` | `InvalidReconciliationRequestError` or `InvalidRegistrySnapshotError` | `unsupported_reconciliation_version` | supplied version and expected version | None beyond unsafe metadata | Unsupported request or snapshot schema version. | No |
| `ReconciliationLimitExceededError` | `InvalidReconciliationRequestError` | `reconciliation_limit_exceeded` | `limit_name`, `limit_value`, `actual_count` | Oversized hostile values | Structural finite limit exceeded. | No |
| `DuplicateObservationIdError` | `InvalidReconciliationRequestError` | `duplicate_observation_id` | duplicated observation ID when safe | Observation payloads | Duplicate observation IDs. | No |
| `MissingObservationIdError` | `InvalidReconciliationRequestError` | `missing_observation_id` | observation index | Observation payloads | Observation lacks stable identity. | No |
| `AmbiguousEquivalentRootError` | `InvalidReconciliationRequestError` | `ambiguous_equivalent_root_declarations` | scope ID, root fingerprint | Raw root path/key | Equivalent roots conflict with different completeness or failures. | No |
| `ReconciliationInvariantError` | `AssetRegistryError` | `internal_reconciliation_invariant_violation` | invariant name, safe counts | Internal object dumps | Planner detects impossible internal state, dangling refs, duplicate final IDs, double match. | No |

Observation Tier 2 errors with stable observation identity are not exceptions.
They become `invalid_observation` plan items. Optional Tier 3 evidence-field
invalidity becomes a finding while retaining usable observation facts.

## 6. Validation Pipeline

Validation order:

1. Request version and identity.
2. Top-level finite limits.
3. Observation ID presence and uniqueness.
4. Snapshot structural validation.
5. Registry record uniqueness assumptions.
6. Detached registry evidence structure.
7. Orphaned evidence.
8. Exact registry evidence deduplication.
9. Scope structural validation.
10. Equivalent-root conflict validation.
11. Observation Tier 2 validation.
12. Optional Tier 3 evidence validation.
13. Canonical sorting.
14. Index construction.
15. Planning.

Fatal request errors: stages 1, 2, 3, 9, and 10.

Fatal snapshot errors: stages 4, 5, 6 when required structure is absent, 7,
and canonicalization failures that make deterministic processing impossible.

Item-level invalid observations: stage 11 when observation ID is stable and
scope identity is usable. These produce `invalid_observation` items and do not
block unrelated observations.

Retained findings while continuing: stage 12 malformed optional evidence,
unsupported but structurally valid evidence, non-authoritative claimed IDs,
weak candidate limits, inaccessible scope details, and public serialization
safeguards.

Planning conflict items: duplicate normalized observation paths, registry path
collisions, same-record identity-evidence conflicts, registry digest collisions,
observation digest collisions, mixed collisions, authoritative ID/path
conflicts, and content conflicts.

Validation coordinator pseudocode:

```python
def validate_reconciliation_inputs(request, snapshot):
    request_id = validate_request_version_and_identity(request)
    limits = validate_limit_policy(request.limit_policy)
    enforce_top_level_limits(request, snapshot, limits)
    validate_observation_ids(request.observations)
    validate_snapshot_structure(snapshot)
    validate_registry_record_uniqueness(snapshot.records)
    raw_evidence = validate_registry_evidence_structure(snapshot.identity_evidence)
    require_no_orphaned_registry_evidence(raw_evidence, snapshot.records)
    registry_evidence = deduplicate_registry_evidence(raw_evidence)
    validate_scope_structure(request.scopes)
    validate_no_ambiguous_equivalent_roots(request.scopes)

    observation_results = []
    for observation in canonical_observation_order(request.observations):
        observation_results.append(validate_observation_tier2_and_tier3(observation))

    canonical_inputs = canonicalize_validated_inputs(
        request=request,
        snapshot=replace(snapshot, identity_evidence=registry_evidence),
        observation_results=observation_results,
    )
    indexes = build_indexes(canonical_inputs, limits)
    return ValidatedInputs(canonical_inputs, indexes)
```

## 7. Finite Limit Constants

All limits are positive integers and enforced before expensive work where
practical. Values marked senior-review should be confirmed before coding.

| Constant | Suggested value | Rationale | Enforcement stage | Failure code | Truncation |
|---|---:|---|---|---|---|
| `MAX_OBSERVATIONS_PER_REQUEST` | 10000 | Thousands-scale architecture with headroom. Senior-review. | 2 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_REGISTRY_RECORDS_PER_SNAPSHOT` | 10000 | Matches expected local registry size. Senior-review. | 2 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_REGISTRY_EVIDENCE_ROWS` | 30000 | Allows several detached evidence facts per record. Senior-review. | 2 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_OBSERVATION_EVIDENCE_FIELDS` | 32 | Prevents pathological optional evidence maps. | 11 | `invalid_observation` or Tier 3 finding | Prohibited |
| `MAX_IDENTIFIER_LENGTH` | 128 | Stable IDs should be compact. Senior-review. | 1, 3, 4, 9, 11 | tier-specific | Prohibited |
| `MAX_REQUEST_ID_LENGTH` | 128 | Consistent with identifier limit. | 1 | `invalid_reconciliation_request` | Prohibited |
| `MAX_OBSERVATION_ID_LENGTH` | 128 | Consistent with identifier limit. | 3 | `invalid_reconciliation_request` | Prohibited |
| `MAX_ASSET_ID_LENGTH` | 128 | External IDs are opaque but bounded. Senior-review. | 4, 11 | tier-specific | Prohibited |
| `MAX_SOURCE_ID_LENGTH` | 128 | Source IDs are machine identifiers. | 1, 9, 11 | tier-specific | Prohibited |
| `MAX_SCOPE_ID_LENGTH` | 128 | Scope IDs are machine identifiers. | 9, 11 | tier-specific | Prohibited |
| `MAX_NORMALIZED_PATH_LENGTH` | 4096 | Windows extended paths and POSIX upper bound. Senior-review. | 4, 9, 11 | tier-specific | Prohibited |
| `MAX_SAFE_DISPLAY_PATH_LENGTH` | 512 | Public diagnostics should remain compact. | 11, 18 | `public_serialization_limit` finding | Redaction allowed |
| `MAX_ALGORITHM_IDENTIFIER_LENGTH` | 32 | Algorithm names should be short allowlisted tokens. | 6, 12 | tier-specific | Prohibited |
| `MAX_DIGEST_LENGTH` | 256 | Supports common hex/base encodings with margin. Senior-review. | 6, 12 | tier-specific | Prohibited |
| `MAX_METADATA_FIELD_COUNT` | 64 | Bounded optional metadata. Senior-review. | 11 | Tier 3 finding or invalid observation | Prohibited |
| `MAX_METADATA_KEY_LENGTH` | 64 | Compact public keys. | 11 | Tier 3 finding | Prohibited |
| `MAX_METADATA_VALUE_LENGTH` | 512 | Avoids log/serialization abuse. | 11, 18 | Tier 3 finding | Redaction allowed |
| `MAX_METADATA_BYTES_PER_OBSERVATION` | 8192 | Bounded memory and serialization. Senior-review. | 11 | Tier 3 finding | Prohibited for internal use |
| `MAX_ROOTS_PER_SCOPE` | 128 | Allows mixed roots without quadratic lookup. Senior-review. | 9 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_INACCESSIBLE_SUBTREES_PER_ROOT` | 256 | Bounded access-failure representation. | 9 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_ACCESS_FAILURES_PER_ROOT` | 256 | Mirrors subtree bound. | 9 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_INCLUSION_FILTER_VALUES` | 256 | Bounded OR sets per dimension. | 9 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_EXCLUSION_FILTER_VALUES` | 256 | Bounded exclusion sets. | 9 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_EXPLICIT_ASSET_IDS` | 10000 | Explicit scans may cover full registry. Senior-review. | 9 | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_DUPLICATE_GROUP_SIZE` | 100 | Collision groups remain readable. Senior-review. | 14, matching | `duplicate_group_limit_exceeded` | Deterministic summarization allowed only for weak diagnostics |
| `MAX_WEAK_CANDIDATES_PER_OBSERVATION` | 25 | Prevents broad fuzzy output. Senior-review. | matching | `weak_candidate_limit_exceeded` | Required bounded finding |
| `MAX_FINDINGS_PER_ITEM` | 50 | Keeps items reviewable. Senior-review. | assembly | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_EVIDENCE_PER_ITEM` | 50 | Keeps evidence graph bounded. Senior-review. | assembly | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_ACTIONS_PER_ITEM` | 10 | Actions are narrow and inert. | assembly | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_TOTAL_PLAN_ITEMS` | 20000 | Records plus observations plus conflicts. Senior-review. | assembly | `reconciliation_limit_exceeded` | Prohibited |
| `MAX_SERIALIZED_PUBLIC_PLAN_BYTES` | 10_000_000 | Public output guardrail. Senior-review. | serialization | `public_plan_size_limit_exceeded` | Prohibited |

Checksum algorithm allowlist is an implementation constant. Proposed V1
default is `sha256` only, with `sha512` senior-review optional. Unsupported
algorithms produce findings and are not used for definitive matching.

## 8. Canonicalization Strategy

The planner may canonicalize:

- Enum values.
- Identifiers after validation, preserving exact external Asset ID spelling.
- Algorithm names to lowercase allowlisted tokens.
- Digest casing and format after upstream validation.
- Tuples and deterministic ordering.
- Source IDs.
- Semantic evidence keys.

The planner must not:

- Resolve paths.
- Perform containment.
- Follow symlinks.
- Normalize raw paths.
- Inspect filesystem case behavior.
- Use raw string-prefix containment checks.

Canonical keys:

- Observations: `(observation_id,)` for identity and `(normalized_path_key,)`
  for path matching when supplied.
- Registry records: `(asset_id,)`, plus `(normalized_resolved_path,)` for path
  grouping when supplied.
- Roots: component tuple derived from already-normalized root key; no raw path
  resolution.
- Subjects: tagged tuple with sorted safe IDs.
- Findings: subject key, finding code, semantic evidence refs, severity rank.
- Evidence: kind, authority, source kind, compared safe subjects, comparison
  result, uniqueness result, canonical value fingerprint, scope/source
  qualifiers.
- Actions: kind, subject key, payload-safe canonical tuple.
- Plan items: subject key, primary classification rank, finding keys, action
  keys.

Sensitive values such as full paths, normalized containment keys, and digests
should be fingerprinted with SHA-256 for internal ordering and public-safe
correlation. Public serializers may expose only safe summaries, short
fingerprints, or redacted placeholders according to `PublicVisibility`.

## 9. Index Design

Registry indexes:

- `asset_id_to_record`: key `asset_id`; value one `AssetRegistryRecord`;
  built after snapshot uniqueness validation; O(n); collision is fatal snapshot
  invalidity; deterministic by sorted Asset ID.
- `path_key_to_records`: key `normalized_resolved_path`; value tuple of records;
  O(n); non-unique groups become registry path collisions; values sorted by
  Asset ID.
- `identity_key_to_records`: key comparable evidence tuple
  `(kind, algorithm, normalized_value, normalization_format, scope_id)`; value
  tuple of Asset IDs; O(e); collisions represented as group subjects; sorted by
  Asset ID.
- `record_evidence_by_asset_id`: key Asset ID; value deduplicated evidence
  tuple; O(e); same-record conflicts represented in matching state.
- `record_state_by_asset_id`: key Asset ID; value lifecycle, availability, and
  verification tuple for fast classification; O(n).

Observation indexes:

- `observation_id_to_observation`: key observation ID; value one observation;
  built after duplicate ID validation; O(m).
- `path_key_to_observations`: key `normalized_resolved_path`; value tuple of
  observations; O(m); duplicate path groups become conflicts; values sorted by
  observation ID.
- `identity_key_to_observations`: key comparable evidence tuple; value tuple of
  observations; O(oe); collisions represented deterministically.
- `trusted_claimed_asset_id_to_observations`: key claimed Asset ID for
  allowlisted sources only; value tuple of observations; O(m); unknown IDs
  block fallback.
- `weak_candidate_buckets`: key bounded facts such as
  `(normalized_file_name, file_size_bytes)` then `(normalized_file_name,)`;
  value capped tuple; O(n + m); oversized buckets emit one finding.

Scope indexes:

- `root_component_index`: key component tuple; value root declarations sorted
  by descending component depth; construction O(r log r); equivalent-root
  conflicts are request errors.
- `explicit_asset_id_set`: key Asset ID; value explicit completeness and
  failures; O(k).
- `inaccessible_subtree_index`: root key to sorted inaccessible subtree keys;
  O(s log s).
- `exclusion_index`: sorted normalized excluded subtrees and filter values; O(f
  log f).

Avoid broad record-by-observation comparisons. Matching stages should use
indexes and bounded buckets only.

## 10. Matching Pipeline

Stages:

1. Block structurally invalid observations.
   - Inputs: validated observation results.
   - Outputs: blocked observation subjects and findings.
   - Blocking: invalid stable observation shape.
   - Evidence: validation evidence.
   - Ordering: observation ID.
2. Identify duplicate observation paths.
   - Inputs: observation path index.
   - Outputs: `ObservationGroupSubject` conflicts.
   - Blocking: affected observations cannot be definitive path matches.
   - Findings: `duplicate_observation_path`.
   - Ordering: path fingerprint then observation IDs.
3. Identify registry path collisions.
   - Inputs: registry path index.
   - Outputs: `RegistryRecordGroupSubject` conflicts.
   - Blocking: affected records cannot be definitive path matches.
   - Findings: `registry_path_collision`.
   - Ordering: path fingerprint then Asset IDs.
4. Evaluate trusted claimed Asset IDs.
   - Inputs: request trust policy, observation claimed IDs, record Asset ID
     index.
   - Outputs: authoritative associations, unknown-ID blocks, conflicts.
   - Blocking: unknown trusted ID blocks fallback for observation.
   - Evidence: trusted ID evidence.
   - Ordering: observation ID.
5. Evaluate exact normalized paths.
   - Inputs: path indexes after duplicate/collision exclusions.
   - Outputs: path associations and conflicts with trusted IDs.
   - Blocking: duplicate path groups.
   - Evidence: exact path evidence.
   - Ordering: normalized path fingerprint.
6. Evaluate comparable strong identity evidence.
   - Inputs: deduplicated registry and observation evidence indexes.
   - Outputs: unique hash associations and collision groups.
   - Blocking: unsupported algorithms, malformed digests, non-unique groups.
   - Evidence: full-content hash evidence.
   - Ordering: evidence key fingerprint.
7. Detect registry, observation, and both-side collisions.
   - Inputs: identity indexes.
   - Outputs: registry group, observation group, or mixed conflict subjects.
   - Blocking: no arbitrary one-to-one pairing.
   - Findings: collision codes.
8. Combine evidence.
   - Inputs: claimed ID, path, identity, weak evidence.
   - Outputs: association candidates.
   - Blocking: conflicting authoritative or strong signals.
   - Evidence: accumulated semantic refs.
9. Apply authoritative conflict matrix.
   - Inputs: candidate evidence per subject.
   - Outputs: conflict groups or allowed associations.
   - Blocking: ID/path/hash conflict, content conflict.
10. Create definitive one-to-one matches.
    - Inputs: non-conflicting associations.
    - Outputs: definitive association tuples.
    - Rule: consume exactly one record and one observation.
11. Mark matched records and observations consumed.
    - Inputs: definitive associations.
    - Outputs: consumed ID sets.
    - Invariant: no ID appears twice.
12. Generate bounded weak candidates for remaining observations.
    - Inputs: unmatched observations, unmatched records, weak buckets.
    - Outputs: ambiguous candidates or weak-limit findings.
    - Blocking: weak evidence never creates path update or mutation proposal.
13. Produce unmatched record and observation subjects.
    - Inputs: consumed ID sets and scope decisions.
    - Outputs: missing candidates, new observations, insufficient scope items.
    - Ordering: subject canonical key.

High-level pseudocode:

```python
def build_matching_state(validated, indexes):
    state = MatchingState.empty()
    state += block_invalid_observations(validated.observation_results)
    state += duplicate_observation_path_conflicts(indexes.observations.by_path)
    state += registry_path_collisions(indexes.registry.by_path)
    state += trusted_id_results(validated.request, indexes)
    state += exact_path_results(indexes, state.blocked_ids)
    state += strong_identity_results(indexes, state.blocked_ids)
    state += collision_results(indexes)
    state = apply_conflict_matrix(state)
    state = consume_definitive_one_to_one_matches(state)
    state += weak_candidates_for_unconsumed(indexes, state)
    state += unmatched_subjects(indexes, state)
    return state
```

## 11. Match Result Internal Model

Internal non-public types in `matching.py`:

- `DefinitiveAssociation`: frozen dataclass with `asset_id`,
  `observation_id`, evidence semantic refs, association kind, and consumed flag.
- `BlockedObservation`: frozen dataclass with observation ID, blocking code,
  and evidence refs.
- `BlockedRecord`: frozen dataclass with Asset ID, blocking code, and evidence
  refs.
- `ConflictGroup`: frozen dataclass with subject, conflict kind, affected IDs,
  evidence refs, and proposal-blocking flag.
- `AmbiguousCandidateGroup`: frozen dataclass with observation ID, candidate
  Asset IDs, weak evidence refs, limit flag.
- `UnmatchedObservation`: frozen dataclass with observation ID and weak facts.
- `UnmatchedRecord`: frozen dataclass with Asset ID and scope decision ref.
- `ConsumedIds`: frozen dataclass with asset ID and observation ID frozensets.
- `EvidenceAccumulator`: internal builder input that carries semantic evidence
  refs before final evidence IDs.

These are internal because they expose algorithm state, unredacted comparison
keys, and incomplete evidence references. They prevent double matching by
centralizing consumed ID checks and by requiring `matching.py` to produce one
final `MatchingState` with an invariant that no definitive association shares
an Asset ID or observation ID.

## 12. Scope Evaluation Algorithm

Function-level design:

```python
def evaluate_record_observability(
    record: AssetRegistryRecord,
    scope: ObservationScope,
) -> ObservabilityDecision:
    ...
```

`ObservabilityDecision` fields:

- `asset_id`.
- `applicable_channels`: tuple of `"path"` and/or `"explicit_asset_id"`.
- `complete_channels`: tuple of channels that prove expected observability.
- `blocked_channels`: tuple of channels blocked by incompleteness, access
  failure, exclusion, or invalid record path.
- `exclusion_reasons`: tuple of stable codes.
- `access_failure_reasons`: tuple of stable codes and safe subtree refs.
- `expected_observable`: bool.
- `missing_eligible`: bool.
- `evidence_facts`: tuple of semantic evidence refs.

Pseudocode:

```python
def evaluate_record_observability(record, scope):
    path_channel = evaluate_path_channel(record.normalized_resolved_path, scope)
    explicit_channel = evaluate_explicit_id_channel(record.asset_id, scope)
    complete_channels = tuple(
        channel.name for channel in (path_channel, explicit_channel)
        if channel.applies and channel.complete and not channel.blocked
    )
    return ObservabilityDecision(
        asset_id=record.asset_id,
        applicable_channels=channels_that_apply(path_channel, explicit_channel),
        complete_channels=complete_channels,
        blocked_channels=blocked_channels(path_channel, explicit_channel),
        exclusion_reasons=combined_exclusions(path_channel, explicit_channel),
        access_failure_reasons=combined_access_failures(path_channel, explicit_channel),
        expected_observable=bool(complete_channels),
        missing_eligible=bool(complete_channels) and record_has_usable_path_or_explicit_channel(record),
        evidence_facts=evidence_from_channels(path_channel, explicit_channel),
    )
```

Path channel rules:

- Find containing roots by already-normalized component-aware root keys.
- Select the most-specific root by component depth.
- Reject equivalent roots with conflicting completeness during validation.
- Exclusions win after the applicable most-specific root is selected.
- Inaccessible subtrees block only affected paths.
- Inclusion filters use OR within a dimension and AND across dimensions.
- Records with null or invalid normalized path cannot be proven missing from
  path scope.

Explicit Asset ID channel rules:

- Applies only when the record Asset ID is in `explicit_asset_ids`.
- Complete only when explicit completeness is `COMPLETE`.
- Per-Asset ID access failure blocks only that Asset ID.
- Path and explicit-ID channels are independent; one channel failure does not
  cancel another complete channel.

## 13. Classification Engine

Use a centralized ordered rule table in `classification.py`, not scattered
`if/elif` branches across matching, scope, and planner modules.

`ClassificationContext` inputs:

- Subject.
- Matching facts.
- Scope decision.
- Registry record state.
- Observation state.
- Findings accumulated so far.
- Evidence semantic refs.
- Candidate action eligibility facts.

Rule ordering:

1. Fatal internal invariant violation.
2. Invalid observation.
3. Registry identity evidence conflict.
4. Registry, observation, or mixed identity collision.
5. Authoritative identity conflict.
6. Content conflict.
7. Duplicate path conflict.
8. Unknown authoritative Asset ID.
9. Ambiguous match.
10. Lifecycle conflict.
11. Path changed.
12. Metadata drift.
13. Availability or verification drift.
14. Record not observed.
15. New unregistered observation.
16. Unsupported observation.
17. Insufficient scope.
18. Unchanged.
19. Diagnostic only.

Pseudocode:

```python
def classify_item(context: ClassificationContext) -> ClassificationDecision:
    for rule in CLASSIFICATION_RULES:
        decision = rule(context)
        if decision is not None:
            validate_subject_compatibility(context.subject, decision.primary)
            return decision.with_secondary_findings(context.retained_findings)
    raise ReconciliationInvariantError("No classification rule matched.")
```

The decision includes primary classification, retained secondary finding refs,
proposal-blocking flag, review-required flag, and compatible action kinds.

## 14. Finding Creation

Finding creation should use a factory registry:

- Stable finding codes live in `findings.py`.
- Safe message templates are deterministic and parameterized only with safe
  IDs, counts, enum values, and short fingerprints.
- Severity rank comes from `FindingSeverity`.
- Review flag and proposal-blocking flag are properties of the finding code
  plus context.
- Evidence references are semantic refs during collection and final evidence
  IDs after the evidence builder resolves them.
- Canonical ordering is by severity rank, subject key, finding code, evidence
  keys, and safe message.
- Deduplication uses canonical finding key before final item assembly.

Finding origins:

- Validation: malformed request/snapshot exceptions, invalid observation items,
  optional evidence invalidity, unsupported algorithms.
- Matching: duplicate paths, collisions, trusted ID issues, weak candidate
  limit.
- Scope: inaccessible subtree, exclusion, incomplete scan, explicit item
  failure.
- Classification: primary outcome details and retained secondary facts.
- Action eligibility: proposal blocked, review required, lifecycle invariant.
- Public serialization safeguards: value redacted or omitted.

Matching code must not create arbitrary prose. It should request a finding by
code and safe structured parameters.

## 15. Plan-Local Evidence Implementation

Use a two-pass builder:

```text
collect semantic evidence
-> deduplicate
-> canonical sort
-> assign IDs
-> resolve finding/action references
```

Internal evidence candidate:

- `semantic_ref`: deterministic opaque reference.
- `semantic_key`: kind, authority, source kind, subjects, comparison,
  uniqueness, safe fingerprint, scope/source qualifiers.
- `sensitive_value`: internal only and optional.
- `safe_summary`: public-safe summary.
- `public_visibility`: visibility enum.
- `observed_at`: optional timestamp.

Timestamp merge behavior:

- Exact duplicate semantic claims keep the latest `observed_at`.
- Equal timestamps use canonical tie-breaker.
- Timestamps never make identical identity claims distinct.

Comparison result derivation:

- Path/ID/hash equality yields `MATCH`.
- Comparable but different strong values yield `MISMATCH`.
- Missing comparable value yields `UNAVAILABLE`.
- Unsupported algorithm yields `UNSUPPORTED`.
- Malformed optional value yields `MALFORMED`.

Uniqueness derivation comes from registry and observation evidence indexes.
Authority assignment is derived from trust policy and evidence kind, never
caller-supplied. Public visibility defaults to redaction for normalized paths,
digests, filesystem identities, and uncontrolled metadata.

Evidence IDs should be assigned globally once after all items are drafted.
Use sequential IDs such as `evidence-000001` after canonical sort. Temporary
semantic references are objects or strings stable within the planning run and
resolved to final IDs during assembly.

## 16. Action Generation

Action factories and eligibility predicates:

| Action | Compatible subject | Required classification | Required evidence | Blocking findings | Phase 1 invariant checks | Payload | Ordering | Serialization |
|---|---|---|---|---|---|---|---|---|
| `register_candidate` | `ObservationSubject` | `new_unregistered_observation` | valid observation path or review evidence | invalid observation, unknown trusted ID, conflict | Asset ID not invented; no direct registration execution. | observation ID, safe path summary, optional claimed ID status | by observation ID | Redact path/digest |
| `update_resolved_path` | `RegistryRecordSubject` plus observation ref | `path_changed` | trusted ID or unique full-content hash, target path fact | content conflict, duplicate path, lifecycle conflict, invalid path diagnostic | Asset ID immutable; lifecycle permits proposal. | asset ID, new path fingerprint, observation ID | by Asset ID | Redact path |
| `update_availability` | `RegistryRecordSubject` | `availability_changed` | normal observation availability | content conflict, invalid observation | Existing state combination must be allowed. | asset ID, availability | by Asset ID | Safe enum |
| `restore_availability` | `RegistryRecordSubject` | `availability_changed` or `unchanged` with restored file | exact path or strong match | lifecycle deprecated conflict | Declared/active only. | asset ID, observation ID | by Asset ID | Safe |
| `mark_missing` | `RegistryRecordSubject` | `record_not_observed` | complete scope evidence | incomplete scope, inaccessible subtree, explicit failure | Preserve lifecycle; no delete. | asset ID, scope refs | by Asset ID | Safe |
| `update_verification_state` | `RegistryRecordSubject` | `availability_changed`, `metadata_drift` | observation verification fact | invalid observation | Existing enum combo must be valid. | asset ID, verification | by Asset ID | Safe enum |
| `update_observed_metadata` | `RegistryRecordSubject` | `metadata_drift` | size/time metadata evidence | content conflict, invalid metadata | Metadata facts only for available files. | asset ID, metadata keys | by Asset ID | Values redacted/summarized |
| `require_review` | Any subject | conflicts, ambiguity, unsupported, weak candidate | any relevant evidence | none | No mutation. | reason codes | conflict before diagnostic | Safe |
| `informational/no-op` | Any subject | `unchanged`, `insufficient_scope`, `diagnostic_only` | optional | none | No mutation. | reason code | after proposals | Safe |

No executor, apply function, repository dependency, or SQLite write path should
be created in Phase 3.

## 17. Deterministic Plan Assembly

Assembly sequence:

```text
validated inputs
-> canonical inputs
-> indexes
-> matching state
-> scope decisions
-> classification contexts
-> item drafts
-> evidence collection
-> action drafts
-> canonical sorting
-> final IDs
-> invariant validation
-> immutable plan
```

ID strategy:

- Evidence IDs: sequential `evidence-000001` after global evidence canonical
  sort.
- Action IDs: sequential `action-000001` after global action canonical sort,
  with item membership resolved afterward.
- Plan item IDs: sequential `item-000001` after canonical item sort.
- Plan ID: content-derived public-safe fingerprint from request ID, snapshot ID,
  registry ID, sorted item semantic keys, and limit-policy fingerprint. If the
  plan includes caller-supplied `created_at`, it must not make otherwise equal
  plans nondeterministic unless the caller changes it.

Plan summary fields are derived from final immutable items and evidence only.
They should not be caller supplied.

## 18. Public Serialization

Use `serialization.py` and do not rely on default dataclass serialization.

Requirements:

- Public schema version: `"asset_reconciliation_plan.v1"`.
- Enum serialization uses stable lowercase values.
- Tuples serialize as lists in canonical order.
- Internal model fields marked `INTERNAL_ONLY` are omitted.
- Redacted evidence includes evidence ID, kind, authority, comparison result,
  uniqueness result, public visibility, safe summary, and optional short
  fingerprint.
- Safe subject representations include only type tags and safe IDs.
- Finding messages come from templates, not arbitrary exception strings.
- No dangling references: every finding/action evidence ID must exist in the
  serialized evidence list unless visibility is internal-only and the reference
  is intentionally omitted with a safe note.
- JSON object keys and lists should be deterministic. Prefer constructing
  ordered plain dictionaries and, if stringifying, `json.dumps(...,
  sort_keys=True, separators=(",", ":"))`.
- Enforce `MAX_SERIALIZED_PUBLIC_PLAN_BYTES`.

### Implementation Note: Public Serialization (Slice 10)

The requirements list above describes redacted evidence in terms of
"evidence ID, kind, authority, comparison result, uniqueness result,
public visibility, safe summary" -- the `PlanEvidence` object from the
"Plan-Local Evidence Contract," already confirmed superseded for Slices
6-9. It does not exist. `ReconciliationPlanItem.evidence_refs` and
`ReconciliationPlan.evidence` are `tuple[str, ...]` bounded evidence codes
(models.py, Slice 1), and none of `FindingSeverity`, `ActionKind`,
`EvidenceAuthority`, `EvidenceSourceKind`, `ComparisonResult`,
`UniquenessResult`, `PublicVisibility`, or `InvalidityTier` are used by any
implemented module, including `serialization.py`.

Per the approved "Phase 3 Slice 10 Implementation Contract --
serialization.py, Revision 3," `serialize_public_plan` implements
structural redaction through an explicit public DTO allowlist instead: it
walks the known, fixed set of fields on
`ReconciliationPlan`/`ReconciliationPlanItem`/`PlanSummary`/`PlanSubject`
explicitly, field by field, and emits exactly those fields -- never
`dataclasses.asdict()`, `vars()`, `__dict__`, or any other reflection-based
dump. `ReconciliationPlan` contains no `PublicVisibility` metadata, and
Slice 10 does not invent or infer any; a visibility-driven redaction
engine is deferred until an approved upstream data model supplies explicit
visibility classifications. `RegistryRecordSubject.record_id` is
deliberately never emitted, whether populated or `None` -- `asset_id` is
the stable public business identifier; `record_id` is an optional internal
row reference the approved contract excludes from the public DTO. The
size guard (`max_serialized_public_plan_bytes`, `limits.py`) is measured
against the exact canonical byte sequence
(`json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")`),
not an estimate.

This correction is scoped to this section only, mirroring the disposition
already given to the "Plan-Local Evidence Contract"/"Structured Finding
Contract" sections during the post-Slice-8 documentation reconciliation.
The architecture document's own serialization paragraph and Scenario 25
("Evidence Public Redaction") describe the same superseded design and are
now additionally stale with respect to `record_id`'s exclusion; that
mismatch is recorded as deferred follow-up, not corrected here --
`ASSET_RECONCILIATION_ARCHITECTURE.md` is not modified by Slice 10.

## 19. Package Exports

Export from `redline_core.asset.reconciliation`:

- `ReconciliationPlanner`.
- `plan_reconciliation` convenience function if implemented.
- `ReconciliationRequest`.
- `ReconciliationPlan`.
- `ReconciliationPlanItem`.
- `PlanSummary`.
- `AssetObservation`.
- `ObservationScope`.
- `ObservationRootScope`.
- `ObservationFilters`.
- `ExplicitAssetAccessFailure`.
- `RegistrySnapshot`.
- `RegistryIdentityEvidence`.
- Public subject types.
- Public action and finding types.
- Public enums.
- Public exceptions.

Correction (Slice 10): `serialize_public_plan` is **not** a package-root
export. `test_package_exports.py` (pre-existing, Slices 1-2, unmodified)
already forbids it; `serialize_public_plan` remains importable only via
`redline_core.asset.reconciliation.serialization.serialize_public_plan`,
matching the established Slice 5-9 precedent for
`build_indexes`/`build_matching_state`/`classify_reconciliation`/
`plan_reconciliation`. This correction is scoped to the
`serialize_public_plan` line only; the `ReconciliationPlanner` line above
is separate, unresolved Slice 9 documentation debt and is not corrected as
part of Slice 10.

Do not export:

- Index classes unless senior review decides they are useful test fixtures.
- Internal match-state dataclasses.
- Classifier rule functions.
- Evidence candidate internals.
- Canonical sensitive value helpers.
- Private validators.

## 20. Planner API

Preferred API:

```python
class ReconciliationPlanner:
    def __init__(self, *, limits: ReconciliationLimitPolicy = DEFAULT_LIMITS) -> None:
        ...

    def plan(
        self,
        request: ReconciliationRequest,
        snapshot: RegistrySnapshot,
    ) -> ReconciliationPlan:
        ...
```

Also consider a thin pure function:

```python
def plan_reconciliation(
    request: ReconciliationRequest,
    snapshot: RegistrySnapshot,
    *,
    limits: ReconciliationLimitPolicy = DEFAULT_LIMITS,
) -> ReconciliationPlan:
    return ReconciliationPlanner(limits=limits).plan(request, snapshot)
```

Planner properties:

- Stateless except immutable limit policy.
- No repository dependency.
- No filesystem dependency.
- Thread-safe when the limit policy is immutable.
- Side-effect free.
- Raises public Phase 3 exceptions only for fatal request/snapshot/invariant
  errors.
- Returns an immutable partial-success plan when isolated observations are
  invalid.
- Does not mutate input tuples, records, observations, scopes, or evidence.
- Deterministic for equivalent inputs.

## 21. Test Structure

Create new Phase 3 test namespaces:

```text
tests/unit/asset/reconciliation/
tests/integration/asset/reconciliation/
```

Proposed unit test modules, 18 total:

1. `test_package_exports.py`
2. `test_enums.py`
3. `test_models.py`
4. `test_subjects.py`
5. `test_exceptions.py`
6. `test_limits.py`
7. `test_validation_request.py`
8. `test_validation_snapshot.py`
9. `test_registry_evidence.py`
10. `test_canonical.py`
11. `test_scope.py`
12. `test_indexes.py`
13. `test_matching_trusted_ids_and_paths.py`
14. `test_matching_identity_and_collisions.py`
15. `test_classification.py`
16. `test_findings_actions_evidence.py`
17. `test_planner.py`
18. `test_serialization.py`

Proposed integration test modules, 2 total:

1. `test_snapshot_loading_from_sqlite_repository.py`
2. `test_reconciliation_repository_compatibility.py`

Existing Phase 1/2 compatibility tests must keep passing:

- `tests/unit/test_asset_models.py`
- `tests/unit/test_asset_path_policy.py`
- `tests/unit/test_asset_repository_contract.py`
- `tests/unit/test_asset_manager.py`
- `tests/integration/test_asset_sqlite_repository.py`
- `tests/integration/test_asset_database_initialization.py`

## 22. Test Fixture Strategy

Create reusable test builders in
`tests/unit/asset/reconciliation/conftest.py` or
`tests/unit/asset/reconciliation/builders.py`:

- `make_registry_record`.
- `make_observation`.
- `make_scope`.
- `make_root_scope`.
- `make_registry_identity_evidence`.
- `make_request`.
- `make_snapshot`.
- `make_subject`.
- `make_finding`.
- `make_action`.

Fixtures must not depend on local absolute paths. Use safe normalized path facts
such as `c:/approved/assets/logo.png` and `c:/approved/assets/archive/clip.mov`
as already-normalized strings, not real filesystem paths. Integration tests may
use `tmp_path` SQLite databases only.

Use parameterization for matrix rows that differ only by enum or evidence
condition. Use scenario fixtures for worked examples that combine trust policy,
scope, matching, and action expectations.

## 23. Required Test Matrix

Required architecture scenario rows: 59.

Planned focused/parameterized test functions: 28-36. Several rows below should
be implemented as parameterized decision tables, but every row must remain
traceable to at least one test assertion. A row is not considered covered by a
general end-to-end test unless that exact scenario name, expected outcome, and
slice are visible in the test.

| ID | Scenario | Architecture rule | Expected outcome | Test module | Test style | Slice |
|---:|---|---|---|---|---|---:|
| 1 | Trusted ID success | Trusted Asset ID policy | Trusted source ID and exact path identify one record; `unchanged`; `no_action`. | `test_matching_trusted_ids_and_paths.py` | focused unit | 6 |
| 2 | Unknown trusted ID | Trusted Asset ID policy | `unknown_authoritative_asset_id`; no fallback to path/hash/weak evidence; no mutation action. | `test_matching_trusted_ids_and_paths.py` | focused unit | 6 |
| 3 | Trusted ID/path conflict | Trusted Asset ID conflict matrix | `authoritative_identity_conflict`; neither signal wins; review action only. | `test_matching_trusted_ids_and_paths.py` | focused unit | 6 |
| 4 | Trusted ID/hash conflict | Trusted Asset ID and strong evidence conflict matrix | Trusted ID and unique hash disagree; conflict item; no path update. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 5 | Invalid trusted claimed Asset ID has no fallback | Invalidity tiers | Trusted malformed claimed ID creates `invalid_observation`; path/hash fallback is blocked. | `test_validation_request.py` | parameterized decision table | 3 |
| 6 | Invalid untrusted claimed Asset ID allows fallback | Invalidity tiers | Malformed untrusted claim is discarded with finding; valid path/hash evidence may continue. | `test_validation_request.py` | parameterized decision table | 3 |
| 7 | Exact path match | Matching hierarchy | Unique normalized path association produces definitive match. | `test_matching_trusted_ids_and_paths.py` | focused unit | 6 |
| 8 | Path/hash conflict | Conflict matrix | Exact path and comparable hash conflict; `content_conflict`; no mutation proposal. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 9 | Unique hash move | Detached identity evidence | Unique full-content hash on both sides supports `path_changed` with inert path-update proposal. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 10 | Absent registry identity evidence | Registry identity evidence rules | Observation hash has no comparable registry evidence; no strong-hash move. | `test_registry_evidence.py` | focused unit | 3 |
| 11 | Orphaned registry evidence | Registry evidence validation | Detached evidence references absent Asset ID; `registry_snapshot_invalid`; no plan. | `test_validation_snapshot.py` | focused unit | 3 |
| 12 | Orphaned evidence error sanitization | Error diagnostics | Orphaned-evidence exception omits raw digest, raw path, SQL, and uncontrolled metadata. | `test_validation_snapshot.py` | focused unit | 3 |
| 13 | Exact duplicate registry evidence | Registry evidence deduplication | Semantically identical evidence deduped; latest timestamp retained; one claim enters matching. | `test_registry_evidence.py` | focused unit | 3 |
| 14 | Exact duplicate evidence input-reordering determinism | Registry evidence deduplication | Duplicate evidence supplied in different orders yields same retained evidence and IDs. | `test_registry_evidence.py` | parameterized decision table | 3 |
| 15 | Same-record conflicting hashes | Registry evidence validation | Same Asset ID and algorithm with conflicting digests creates conflict item and blocks strong matching. | `test_registry_evidence.py` | focused unit | 3 |
| 16 | Registry digest collision | Collision handling | Same digest on multiple registry records creates registry collision group; no arbitrary match. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 17 | Observation digest collision | Collision handling | Same digest on multiple observations creates observation ambiguity; no path update. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 18 | Both-side collision | Collision handling | Non-unique digest on both sides creates mixed conflict subject. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 19 | Both-side collision cannot create arbitrary pairings | Collision handling | No pairwise record-observation matches are selected from mixed non-unique digest groups. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 20 | Non-unique registry digest cannot create path update | Collision handling | Registry-side non-unique digest blocks `update_resolved_path`. | `test_matching_identity_and_collisions.py` | parameterized decision table | 7 |
| 21 | Non-unique observation digest cannot create path update | Collision handling | Observation-side non-unique digest blocks `update_resolved_path`. | `test_matching_identity_and_collisions.py` | parameterized decision table | 7 |
| 22 | Malformed optional hash | Invalidity tiers | Malformed optional hash is ignored with Tier 3 finding; observation remains usable by path. | `test_validation_request.py` | parameterized decision table | 3 |
| 23 | Unsupported algorithm is not mismatch | Registry evidence rules | Unsupported algorithm creates unsupported-evidence finding; it is not treated as a digest mismatch. | `test_registry_evidence.py` | focused unit | 3 |
| 24 | Malformed weak timestamp | Invalidity tiers | Weak timestamp evidence ignored; Tier 3 finding emitted; other evidence may continue. | `test_validation_request.py` | parameterized decision table | 3 |
| 25 | Malformed filesystem identity | Invalidity tiers | Malformed optional filesystem identity is ignored or flagged without authorizing matching. | `test_validation_request.py` | parameterized decision table | 3 |
| 26 | Oversized optional metadata | Finite limits and public safety | Metadata limit enforced; Tier 3 finding when continuation is allowed; hostile value not echoed. | `test_limits.py` and `test_serialization.py` | parameterized decision table | 3 |
| 27 | Duplicate observation IDs | Request validation | Duplicate observation IDs raise request-level exception; no plan. | `test_validation_request.py` | focused unit | 3 |
| 28 | Duplicate observation paths | Matching hierarchy | Duplicate normalized observation path creates group conflict; affected observations cannot path-match. | `test_matching_trusted_ids_and_paths.py` | focused unit | 6 |
| 29 | Complete/incomplete overlapping roots | Scope precedence | Most-specific matching root controls completeness; branch order does not decide. | `test_scope.py` | parameterized decision table | 4 |
| 30 | Complete parent plus incomplete child | Scope precedence | Record under incomplete child is not proven expected through path channel; no missing proposal. | `test_scope.py` | focused unit | 4 |
| 31 | Incomplete parent plus complete child | Scope precedence | Record under complete child may be missing-eligible; records outside child remain incomplete. | `test_scope.py` | focused unit | 4 |
| 32 | Parent/child root input-reordering determinism | Scope precedence | Reordered root declarations produce same observability decisions and plan IDs. | `test_scope.py` | parameterized decision table | 4 |
| 33 | Equivalent normalized roots with conflicting declarations | Scope validation | Request validation error; no branch-order-dependent selection; no plan. | `test_validation_request.py` | focused unit | 3 |
| 34 | Inaccessible subtree | Scope contract | Record under inaccessible subtree gets access-failure finding/evidence. | `test_scope.py` | focused unit | 4 |
| 35 | Inaccessible subtree does not produce missing | Missing-record safety | No `mark_missing` action and no missing classification requiring complete proof. | `test_scope.py` and `test_planner.py` | planner end-to-end unit | 4 |
| 36 | Exclusion precedence | Scope contract | Exclusion wins for expected-observability; excluded record not missing-eligible. | `test_scope.py` | focused unit | 4 |
| 37 | Excluded record does not produce missing | Missing-record safety | Excluded record receives no missing proposal. | `test_scope.py` and `test_planner.py` | planner end-to-end unit | 4 |
| 38 | Filter AND/OR semantics | Scope filters | OR within a filter dimension and AND across dimensions. | `test_scope.py` | parameterized decision table | 4 |
| 39 | Explicit ID completeness | Explicit Asset ID scope | Complete explicit set can establish expected observability for listed IDs only. | `test_scope.py` | focused unit | 4 |
| 40 | Null or invalid path with complete explicit scope | Explicit Asset ID scope | Path channel unavailable; complete explicit-ID channel may establish missing eligibility; no path normalization. | `test_scope.py` | focused unit | 4 |
| 41 | Incomplete path scope plus complete explicit-ID scope | Independent channels | Incomplete path channel does not cancel complete explicit-ID channel for listed record. | `test_scope.py` | focused unit | 4 |
| 42 | Complete path scope plus explicit-item failure | Independent channels | Explicit channel blocked for item; path channel evaluated independently. | `test_scope.py` | focused unit | 4 |
| 43 | Path/explicit independent channels | Independent channels | Failure in one channel does not cancel a separate complete channel. | `test_scope.py` | parameterized decision table | 4 |
| 44 | Missing eligibility | Scope and action rules | Missing eligibility requires at least one complete unblocked applicable channel. | `test_scope.py` | parameterized decision table | 4 |
| 45 | Incomplete scan does not produce missing | Missing-record safety | Absent registry record under incomplete or unknown scope remains unproven; no `mark_missing`. | `test_scope.py` and `test_planner.py` | planner end-to-end unit | 4 |
| 46 | Moved record not also missing | One-to-one consumption and invariants | Record consumed by move match is skipped by missing pass; invariant suite covers this. | `test_planner.py` | planner end-to-end unit | 11 |
| 47 | Weak candidate output limit | Weak candidates | Oversized weak bucket emits bounded finding, not request failure; no exhaustive candidates. | `test_matching_identity_and_collisions.py` | focused unit | 7 |
| 48 | Metadata drift | Classification table | Definitive match with non-conflicting metadata differences yields `metadata_drift`. | `test_classification.py` | focused unit | 8 |
| 49 | Content conflict | Classification table | Comparable content mismatch outranks metadata/path normal outcomes; no mutation proposal. | `test_classification.py` | focused unit | 8 |
| 50 | Lifecycle conflict | Classification table | Lifecycle restrictions block incompatible proposals. | `test_classification.py` | focused unit | 8 |
| 51 | Availability conflict | Classification table | Availability/verification drift classified deterministically and state invariants checked. | `test_classification.py` | focused unit | 8 |
| 52 | Public evidence redaction | Public serialization | Raw paths, digests, filesystem IDs, and uncontrolled metadata are redacted. | `test_serialization.py` | focused unit | 12 |
| 53 | Public redaction leaves no dangling references | Public serialization | Redacted/internal-only evidence handling leaves no dangling finding/action refs. | `test_serialization.py` | focused unit | 12 |
| 54 | Public serialized plan size at limit | Public serialization limits | Plan at or below `MAX_SERIALIZED_PUBLIC_PLAN_BYTES` serializes successfully. | `test_serialization.py` and `test_limits.py` | focused unit | 12 |
| 55 | Public serialized plan size exceeds limit | Public serialization limits | Documented size-limit failure; no silent truncation or partial invalid payload. | `test_serialization.py` and `test_limits.py` | focused unit | 12 |
| 56 | Deterministic input reorder | Deterministic planning | Equivalent reordered inputs produce same classifications, ordering, and logical plan. | `test_planner.py` | planner end-to-end unit | 11 |
| 57 | Stable plan/evidence/action/item IDs | Deterministic IDs | Equivalent reordered inputs produce same plan ID and sequential evidence/action/item IDs. | `test_planner.py` | planner end-to-end unit | 11 |
| 58 | No input object mutation | Immutability and side effects | Request, snapshot, records, observations, scopes, and evidence remain unchanged after planning. | `test_planner.py` | planner end-to-end unit | 11 |
| 59 | Final invariant failure | Plan invariants | Injected invalid final draft raises sanitized invariant exception and returns no plan. | `test_planner.py` | invariant injection | 11 |

## 24. Implementation Phases

Use small reviewable slices. Prefer one commit per slice after tests pass.

Revision note: implementation has progressed beyond the original validation
planning milestone. The validation subsystem has already been implemented and
approved at repository HEAD
`c06d05badf697adf1395ea48d5f8175853fb2ef4`; remaining slice numbers are
realigned so future prompts point to the next unimplemented work. This is a
documentation-only schedule update. Architecture and behavior are unchanged.

| Slice | Files created | Files modified | Tests added | Dependencies | Acceptance criteria | Review risks | Documentation updates | One commit |
|---|---|---|---|---|---|---|---|---:|
| 1. Foundational enums and immutable models | `reconciliation/__init__.py`, `enums.py`, `limits.py`, `models.py` | package data only if needed, no schema | `test_enums.py`, `test_models.py`, `test_limits.py` | Existing Phase 1 enums and `AssetRegistryRecord` | Frozen types, tuple conversion, Python 3.10-compatible typing | Over-large model constructors | None yet | Yes |
| 2. Subjects, findings, actions, exceptions | `subjects.py`, `findings.py`, `actions.py`, optional `exceptions.py` | `__init__.py` exports | `test_subjects.py`, `test_findings_actions_evidence.py`, `test_exceptions.py` | Slice 1 | Tagged subjects, inert action payloads, safe exceptions | Subject ambiguity, public API sprawl | None yet | Yes |
| Historical Slice 3. Limits and structural validation | `validation.py` | `models.py` only if constructor gaps found | `test_validation_request.py`, `test_validation_snapshot.py` | Slices 1-2 | Fatal vs item-level validation split | Too many exception classes | Status: COMPLETE (Implemented and Approved). Approved repository HEAD: `c06d05badf697adf1395ea48d5f8175853fb2ef4` | Yes |
| 3. Canonical keys and evidence validation | `canonical.py`, `evidence.py` | `validation.py` | `test_canonical.py`, `test_registry_evidence.py`, `test_evidence.py` | Completed validation subsystem | Dedup, same-record conflict, unsupported evidence findings | Digest leakage | None yet | Yes |
| 4. Scope evaluation | `scope.py` | None expected | `test_scope.py` | Slice 3 | Most-specific roots, filters, explicit channel independence | Accidentally doing path policy | None yet | Yes |
| 5. Indexes and collision analysis | `indexes.py` | `matching.py` skeleton optional | `test_indexes.py`, collision cases | Slice 4 | O(n) grouping, deterministic collision groups | Nondeterministic dict iteration | None yet | Yes |
| 6. Trusted ID and exact-path matching | `matching.py` | None expected | `test_matching_trusted_ids_and_paths.py` | Slice 5 | Trust policy and path matrix implemented | Trusted ID fallback mistakes | None yet | Yes |
| 7. Strong identity matching | `matching.py` (extended) | None (`indexes.py` unchanged; the registry/observation identity-key bridge lives entirely in `matching.py` — see architecture doc "Implementation Note: Registry/Observation Identity-Key Bridge") | `test_matching_strong_identity.py` | Slice 6 | Unique hash move, collision blocking, absent evidence behavior | Conflicting hashes becoming definitive | Status: Implemented and committed; independent implementation review pending (not yet approved). Architecture doc updated with the identity-key bridge note; CHANGELOG updated. | Yes |
| 8. Classification engine | `classification.py` | None (imports `indexes.py` directly, in addition to `enums`, `matching`, `scope`; advisory list corrected -- see "Slice 8 Implementation Contract -- Revision 3", Decision 7) | `test_classification.py` | Slice 7 | Ordered rule table and precedence | Scattered logic | Status: Implemented and unit tested (32 new tests; full existing suite of 468 prior tests remains passing, 500 total); independent implementation review pending (not yet approved). Architecture-level contract ("Slice 8 Implementation Contract -- Revision 3") approved prior to implementation; `SIZE_CONFLICT` enum addition deferred to a future dedicated slice (Decision 5a); CHANGELOG updated. | Yes |
| 9. Evidence builder and deterministic IDs | `evidence.py` (no extension currently required — see Documentation updates) | None | `test_evidence.py` (existing coverage; no new tests required for the current critical path) | Slice 8 | No rich `PlanEvidence` extension is required for the current Phase 3 critical path | Reintroducing a structured evidence-ID system before a real requirement appears | Status: Scope corrected. Rich `PlanEvidence`/`EvidenceCandidate`/`EvidenceBuilder` design reclassified as future / re-evaluate after planner and serialization are implemented — not removed. The current implementation uses the bounded string evidence model; the original design remains documented as an earlier architectural proposal and is not part of the current Phase 3 implementation path. `planner.py` work tracked entirely at row 11, not partially here. See "Phase 3 Documentation Reconciliation Contract, Revision 2" and architecture doc "Implementation Note: Documentation Reconciliation (Post-Slice 8)". | Yes |
| 10. Action generation | `actions.py` (future / re-evaluate after planner and serialization are implemented) | None | `test_findings_actions_evidence.py` (future, if re-evaluated) | Slice 9 | Future / re-evaluate after planner and serialization are implemented; not currently required for row 11's implementation | Prematurely designing a structured action system before a real requirement appears | Status: Scope corrected. `actions.py` reclassified as future / re-evaluate, not removed. Row 11 does not depend on this row for its current implementation — see row 11's Sequencing Note. | Yes |
| 11. Plan assembly and invariants | `planner.py` | None (`__init__.py` is not modified -- `plan_reconciliation` is a module-level import only, `redline_core.asset.reconciliation.planner.plan_reconciliation`, matching the established Slice 5-8 precedent that `build_indexes`/`build_matching_state`/`classify_reconciliation` are also not package-root exports; see `test_package_exports.py`, unchanged) | `test_planner.py` | **Corrected: Slice 8 (`classification.py`) directly, for the current critical path.** Original dependency ("Slice 10") assumed `findings.py`/`actions.py` (rows 9-10) would already exist; both are future/re-evaluate (see rows 9-10), so this row's real, buildable dependency today is Slice 8's output directly. | Immutable full plan, summaries, one-to-one consumption; `ReconciliationPlanItem`/`ReconciliationPlan` assembled directly from `ClassificationState` with plain string findings/evidence_refs/actions | Double matching, moved also missing, prematurely reintroducing a deferred object system | Status: Implemented and unit tested (57 new tests -- see CHANGELOG for the full-suite total; independent implementation review pending, not yet approved). Architecture-level contract ("Phase 3 Slice 9 Implementation Contract -- planner.py, Revision 4") approved prior to implementation. No `ReconciliationPlanner` class exists (contract Decision 4); `_limit_policy_fingerprint` is private and local to `planner.py`, not added to `canonical.py` (contract Decision 6); `findings`/`actions` are always `()` and `PlanSummary.severities`/`action_kinds` are always empty for every item (contract Decisions 2, 3, 5) -- no action, finding, or severity policy is introduced by this slice. **Sequencing Note:** this row's original dependency chain (rows 9 → 10 → 11) was circular as written (row 10 also referenced a partial `planner.py` from row 9). This correction removes the circularity by depending on row 8 directly. Roadmap row numbers identify planning entries only; implementation slice numbers identify chronological implementation order; the two are independent and are not required to match -- `planner.py` is **Phase 3 Slice 9**, while remaining **roadmap row 11**. | Yes |
| 12. Public serialization and redaction | `serialization.py` | None (`__init__.py` is not modified -- `serialize_public_plan` is a module-level import only, `redline_core.asset.reconciliation.serialization.serialize_public_plan`, matching the established Slice 5-9 precedent; see `test_package_exports.py`, unchanged) | `test_serialization.py` | **Corrected: Slice 9 (`planner.py`) directly.** Original dependency ("Slice 11") assumed an implementation-slice-number track that does not exist; roadmap row numbers and implementation slice numbers are independent tracks, as already recorded on row 11 -- this row's real, buildable dependency is Slice 9's `ReconciliationPlan` output directly. | Stable safe DTOs via an explicit structural allowlist, size guard, no raw leakage | Dataclass dump leakage | Status: Implemented and unit tested (26 new test cases across 20 numbered tests -- see CHANGELOG for the full-suite total; independent implementation review pending, not yet approved). Architecture-level contract ("Phase 3 Slice 10 Implementation Contract -- serialization.py, Revision 3") approved prior to implementation. No `PublicPlanSerializer` class exists; redaction is a structural allowlist, not a `PublicVisibility`-driven per-fact policy (no upstream data model changes); `RegistryRecordSubject.record_id` is never exposed. `serialize_public_plan` is not exported from the package root (`__init__.py` unchanged, `test_package_exports.py` unchanged). Documentation corrections for this row are scoped to this row, the `serialization.py` module-map row, this section, and Section 18/19 below; the architecture document and the unrelated Slice 9 `ReconciliationPlanner` export-line documentation debt are explicitly out of scope for this slice and are not touched here. | Yes |
| 13. Integration compatibility | None expected | Integration tests only; possible helper in tests | `test_snapshot_loading_from_sqlite_repository.py`, `test_reconciliation_repository_compatibility.py` | Slice 12 | SQLite read ordering compatible, no writes, no schema change | Test accidentally mutating production DB | Documentation, changelog, milestone only after approval | Yes |

## 25. Documentation Obligations

Do not make these updates during this planning task. During implementation:

- Slice 12: add package usage example to `README.md` or a reconciliation usage
  section if repository convention prefers README.
- Slice 12: document default limit policy in
  `docs/ASSET_RECONCILIATION_ARCHITECTURE.md` or a concise companion note if
  senior review requests it.
- Slice 12: document public serialization schema and redaction behavior.
- Slice 13: document snapshot-loading integration expectations with
  `SQLiteAssetRepository`.
- After full implementation and senior approval: update `docs/CHANGELOG.md`.
- After full implementation and senior approval: update `MILESTONES.md` only
  if requested by milestone process.
- No configuration documentation changes should imply a new runtime flag,
  because Phase 3 has no scanner, apply phase, or network-path option.

## 26. Review Gates

Every gate is run from the repository root. Replace no command with a tool that
is not supported by `pyproject.toml` or existing repository tooling. A failed
required command blocks gate approval. Known informational Git warnings do not
block approval unless they prevent accurate inspection. Approval at one gate
does not authorize a future push.

### Gate 1. Implementation Plan Review

- Purpose: verify architecture traceability and implementation readiness.
- Artifacts reviewed: implementation plan, approved reconciliation
  architecture, repository conventions.
- Required commands:
  - `git rev-parse HEAD`
  - `git status --short`
  - `git diff --check`
  - `git diff --cached --name-status`
- Required tests/checks: documentation-only scope, complete test
  traceability, complete module ownership, no architecture contradiction, no
  source or test changes.
- Approval criteria: no critical or important findings; minor findings are
  absent or explicitly accepted.
- Prohibited work: source implementation, test implementation, staging,
  committing, and pushing during review.
- Allowed next action after approval: commit the implementation plan.
- Required next action after rejection: perform focused implementation-plan
  corrections.

### Gate 2. Foundational Model Review

- Purpose: approve enums, exceptions, immutable models, subjects, limits, and
  package boundaries.
- Artifacts reviewed: foundational source modules, foundational unit tests,
  package exports, relevant documentation updates.
- Required commands:
  - `python -m pytest tests/unit/asset/reconciliation/test_package_exports.py tests/unit/asset/reconciliation/test_enums.py tests/unit/asset/reconciliation/test_models.py tests/unit/asset/reconciliation/test_subjects.py tests/unit/asset/reconciliation/test_exceptions.py tests/unit/asset/reconciliation/test_limits.py`
  - `python -m pytest tests/unit/test_asset_models.py tests/unit/test_asset_path_policy.py tests/unit/test_asset_repository_contract.py tests/unit/test_asset_manager.py`
  - `python -m compileall src/redline_core/asset/reconciliation`
  - `git diff --check`
  - `git status --short`
- Required tests: enums, immutable model validation, subject invariants,
  exception sanitization, finite limit policy, package import/export smoke
  test.
- Approval criteria: all required tests pass; no circular imports; no Phase 1
  enum redefinition; no mutable public domain state; public API remains
  minimal.
- Prohibited work: matching implementation beyond compile-safe interfaces,
  serialization implementation, repository integration, filesystem
  integration.
- Allowed next action after approval: proceed to structural validation and
  scope implementation slices.
- Required next action after rejection: correct foundational models before
  dependent slices continue.

### Gate 3. Matching And Scope Review

- Purpose: approve validation, scope evaluation, indexes, collision handling,
  and matching hierarchy.
- Artifacts reviewed: validation, scope, canonical keys, indexes, matching
  modules, related unit tests.
- Required commands:
  - `python -m pytest tests/unit/asset/reconciliation/test_validation_request.py tests/unit/asset/reconciliation/test_validation_snapshot.py`
  - `python -m pytest tests/unit/asset/reconciliation/test_registry_evidence.py tests/unit/asset/reconciliation/test_canonical.py tests/unit/asset/reconciliation/test_scope.py`
  - `python -m pytest tests/unit/asset/reconciliation/test_indexes.py tests/unit/asset/reconciliation/test_matching_trusted_ids_and_paths.py tests/unit/asset/reconciliation/test_matching_identity_and_collisions.py`
  - `python -m pytest tests/unit/test_asset_models.py tests/unit/test_asset_path_policy.py tests/unit/test_asset_repository_contract.py tests/unit/test_asset_manager.py`
  - `git diff --check`
  - `git status --short`
- Required tests: validation tiers, orphaned evidence, duplicate evidence, root
  precedence, inaccessible/exclusion behavior, explicit-ID scope, incomplete
  scan not missing, trusted ID behavior, exact path, strong identity, all
  collision classes, one-to-one consumption, matching input-reorder
  determinism.
- Approval criteria: no arbitrary pairing; no double consumption; no missing
  from incomplete scope; no trusted malformed-ID fallback; collision behavior
  matches architecture; weak candidates and collision groups are bounded.
- Prohibited work: final public serialization, action execution, repository
  writes, filesystem access.
- Allowed next action after approval: proceed to classification, evidence, and
  action slices.
- Required next action after rejection: correct matching/scope implementation
  before plan assembly proceeds.

### Gate 4. Deterministic Plan Review

- Purpose: approve classification, findings, evidence builder, inert actions,
  plan assembly, IDs, and final invariants.
- Artifacts reviewed: classification, findings, evidence, actions, planner,
  invariant validator, associated tests.
- Required commands:
  - `python -m pytest tests/unit/asset/reconciliation/test_classification.py`
  - `python -m pytest tests/unit/asset/reconciliation/test_findings_actions_evidence.py tests/unit/asset/reconciliation/test_registry_evidence.py`
  - `python -m pytest tests/unit/asset/reconciliation/test_planner.py`
  - `python -m pytest tests/unit/asset/reconciliation/test_planner.py -k "deterministic or stable or mutation or invariant"`
  - `git diff --check`
  - `git status --short`
- Required tests: classification precedence, secondary finding retention,
  evidence deduplication, uniqueness states, stable sequential IDs, stable
  content-derived plan ID, action eligibility, moved record not missing,
  conflict item has no mutation action, dangling-reference invariant, final
  invariant failure, no input mutation.
- Approval criteria: equivalent reordered inputs produce identical logical
  plans and IDs; all references resolve; all actions remain inert; all final
  invariants pass; classification logic is not duplicated outside the central
  engine.
- Prohibited work: action executor, database writes, filesystem writes,
  operator workflow.
- Allowed next action after approval: proceed to public serialization and
  read-only integration compatibility.
- Required next action after rejection: correct deterministic plan behavior
  before serializer work is approved.

### Gate 5. Serialization And Security Review

- Purpose: approve public-safe serialization, redaction, stable encoding, and
  output limits.
- Artifacts reviewed: serializer, public DTOs or public output schema,
  redaction policy, serialization tests, size-limit tests, usage documentation.
- Required commands:
  - `python -m pytest tests/unit/asset/reconciliation/test_serialization.py`
  - `python -m pytest tests/unit/asset/reconciliation/test_limits.py -k "serialized or size or metadata"`
  - `python -m pytest tests/unit/asset/reconciliation/test_planner.py`
  - `git diff --check`
  - `git status --short`
- Required tests: raw path redaction, digest redaction, filesystem identity
  redaction, internal-only evidence handling, no dangling public references,
  deterministic key/list ordering, byte-stable or logically stable output
  according to the selected contract, at-limit serialization, over-limit
  serialization failure, hostile oversized content not echoed.
- Approval criteria: no sensitive internal values leak; public output is
  structurally valid; size limit is deterministic; equivalent plans serialize
  consistently; default dataclass dumping is not used.
- Prohibited work: weakening redaction to satisfy tests, silent truncation of
  structural data, repository-dependent serialization.
- Allowed next action after approval: proceed to full implementation review.
- Required next action after rejection: correct serializer/security defects
  before integration approval.

### Gate 6. Full Implementation Review

- Purpose: approve the complete Phase 3 implementation.
- Artifacts reviewed: all Phase 3 source, all unit and integration tests,
  package documentation, usage examples, limit documentation, changelog draft,
  milestone completion draft if appropriate.
- Required commands:
  - `python -m pytest`
  - `python -m compileall src/redline_core/asset/reconciliation`
  - `git diff --check`
  - `git status --short`
- Required tests: complete architecture test matrix, all existing Phase 1
  tests, all existing Phase 2 tests, read-only snapshot-loading integration,
  public serialization tests, determinism tests, limits and complexity tests.
- Approval criteria: no critical, important, or unresolved minor findings; all
  tests pass; no Phase 1 or Phase 2 regressions; no schema change; no write
  behavior; documentation complete; definition of done satisfied.
- Prohibited work: push, action execution, repository mutation, filesystem
  mutation, Resolve integration.
- Allowed next action after approval: commit the complete approved
  implementation sequence or final implementation commit according to the
  approved commit strategy.
- Required next action after rejection: perform focused implementation
  corrections.
- Repository-standard optional commands: add a type checker, linter,
  formatting check, or coverage command only if the repository adds supported
  tooling for that command.

### Gate 7. Implementation Commit Review

- Purpose: verify approved source, tests, and documentation are committed with
  correct boundaries.
- Artifacts reviewed: staged diffs, commit sequence, commit messages, final
  repository status.
- Required commands:
  - `git status --short`
  - `git diff --cached --name-status`
  - `git diff --cached --check`
  - `git diff --cached`
  - `git log --oneline --decorate -n 8`
- Required tests/checks: only approved files staged; tests and implementation
  committed together by slice; no credentials or generated artifacts; no schema
  change; no unapproved milestone/changelog edits; no push.
- Approval criteria: commit boundaries match approved strategy; every commit is
  reviewable; working tree ends clean; implementation commit hashes are
  recorded.
- Prohibited work: automatic push, force push, amend or rebase unless
  explicitly approved.
- Allowed next action after approval: implementation is ready for optional push
  only after explicit user instruction.
- Required next action after rejection: repair staging or commit history
  without pushing.

### Gate 8. Optional Push Authorization

- Purpose: verify whether approved local commits may be pushed.
- Artifacts reviewed: local commit hashes, branch name, remote target, clean
  working tree.
- Required commands:
  - `git status --short`
  - `git branch --show-current`
  - `git log --oneline --decorate -n 8`
  - `git remote -v`
- Required tests/checks: explicit user instruction to push, correct branch and
  remote, clean working tree, approved commit sequence only.
- Approval criteria: push target and branch are explicit; working tree is
  clean; only approved commits are present.
- Prohibited work: push without explicit instruction, force push unless
  explicitly authorized, silently changing branch or remote.
- Allowed next action after approval: push the approved branch to the approved
  remote.
- Required next action without authorization: keep commits local.

## 27. Risks

| Risk | Mitigation |
|---|---|
| Circular imports | Keep layered dependency direction; use small DTO/context objects. |
| Duplicated architecture logic | Centralize precedence in `classification.py` and finding templates in `findings.py`. |
| Nondeterministic iteration | Sort all dict/group outputs by canonical keys before IDs and serialization. |
| Evidence-reference resolution | Use semantic refs until global evidence IDs are assigned. |
| Accidental raw-path/digest leakage | Default sensitive evidence to `REDACT_VALUE` or `INTERNAL_ONLY`; test serialization. |
| Double matching | Central `ConsumedIds` invariant and planner invariant checks. |
| Moved record also marked missing | Scope missing pass must skip consumed records. |
| Conflicting hashes becoming definitive | Same-record and cross-record collisions block strong matching. |
| Scope-channel cancellation | Model path and explicit channels independently. |
| Unbounded collision groups | Enforce duplicate-group and weak-candidate limits. |
| Excessive dataclass complexity | Keep model types explicit, use builders in tests, avoid nested mutable maps. |
| Public API overexposure | Minimal `__init__.py` exports; keep indexes and match state private. |
| Performance regressions | Indexed matching only; complexity sanity tests. |
| Tests encoding implementation details | Prefer behavior scenarios and public API assertions, except focused internal unit tests for canonical/index modules. |

## 28. Open Implementation Constants

Architecture-permitted implementation choices:

- Supported checksum algorithms: default `sha256`; consider `sha512` only with
  senior approval. Rationale: SHA-256 is common, fixed-length, and sufficient
  for V1 strong evidence.
- Exact numeric limits: use the table in section 7; all values marked
  senior-review should be explicitly approved before coding or adjusted during
  implementation review.
- Deterministic serialization encoding: default compact UTF-8 JSON-compatible
  dictionaries with sorted keys for byte-size measurement. Senior approval not
  required unless an external schema artifact is added.
- Internal sequential ID width: default six digits,
  `evidence-000001`/`action-000001`/`item-000001`. Senior approval not
  required unless expected plan size exceeds 999999.
- Internal helper organization: use private helpers inside modules first;
  extract only when test or complexity pressure justifies it. Senior approval
  not required.

Do not reopen these approved architecture decisions: read-only planner,
repository independence, no path resolution, no filesystem scanning, detached
registry identity evidence, trust policy behavior, invalidity tiers, scope
precedence, collision behavior, evidence redaction, and inert actions.

## 29. Definition Of Done

Phase 3 implementation is complete when:

- Planner is read-only and repository-independent.
- All approved domain types exist.
- Validation tiers are implemented.
- Matching matrix is implemented.
- Scope precedence is implemented.
- Collisions are deterministic.
- One-to-one consumption is enforced.
- Classifications are deterministic.
- Findings are structured.
- Evidence is deduplicated and redacted.
- Actions are inert.
- IDs are stable across reordered inputs.
- Required unit and integration tests pass.
- No schema change is made.
- No Phase 1 or Phase 2 regression occurs.
- Documentation is complete.
- Changelog is updated.
- Senior implementation review approves the result.

## Self-Review

- Every architecture concept maps to one module, type, or function in this
  plan.
- No behavior is left to implementation intuition; where architecture leaves
  constants open, defaults and review needs are listed.
- No module owns both I/O and domain planning.
- No source code is written by this planning document.
- No test is written by this planning document.
- No schema change is proposed.
- The dependency graph is acyclic by design.
- All required tests map to an implementation slice.
- Documentation obligations are listed.
- Deferred future features remain deferred.
