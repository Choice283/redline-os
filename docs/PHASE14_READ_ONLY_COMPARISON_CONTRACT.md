# Phase 14 Read-Only Project/Timeline Comparison Contract

Status: **Construction and static review only**
Mission: **Phase 14 — Dual Project/Timeline Read-Only Snapshot Probe Construction and Static Review**
Founder authorization: Paul Jones, August 4, 2026
Canonical repository checkpoint: `d9ebe5947ba8e5fa77e765f8db3482fee03d7132`
Canonical commit subject: `docs: record Phase 14 isolation evidence`

## 1. Purpose

Phase 14 has established the following project-by-preset isolation matrix:

| Project context | YouTube - 720p | Redline Broadcast Master |
|---|---:|---:|
| `redline-os-test-duplicate` / `RLO-LIVE-ASM-92701_TIMELINE` | Accepted | Accepted |
| `RLC-E9001_MASTER` / `RLC-E9001_TIMELINE` | Rejected | Rejected |

The matrix rules out either tested preset being universally incapable of queue
acceptance. It does not identify a project- or timeline-level cause.

This contract defines the smallest fail-closed system for collecting two
read-only Resolve context snapshots and comparing them offline. It does not
claim corruption, repairability, render eligibility, or causation.

## 2. Current authorization boundary

The authorized construction mission permits only:

- architecture documentation;
- source drafting;
- mocked unit tests;
- static safety review;
- hash generation.

The construction mission prohibits:

- importing or executing `DaVinciResolveScript` against a live environment;
- calling `scriptapp("Resolve")`;
- contacting DaVinci Resolve;
- inspecting live projects, timelines, media pools, render settings, or queues;
- loading or switching projects;
- switching timelines;
- loading presets;
- setting render settings;
- adding, deleting, starting, stopping, or cancelling render jobs;
- accessing or modifying SQLite;
- committing or publishing repository changes.

The source enforces this boundary with:

```python
SNAPSHOT_EXECUTION_ENABLED = False
```

The `snapshot` CLI stops before the connection function while this constant is
false. A future live-capture mission must create a separately reviewed source
revision, generate a new SHA-256, and bind explicit founder authorization to
that revision and the exact repository commit.

## 3. Deliverable layout

The construction review bundle contains:

```text
scripts/phase14_resolve_context_snapshot.py
tests/unit/test_phase14_resolve_context_snapshot.py
docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md
docs/PHASE14_STATIC_REVIEW_REPORT.md
construction_manifest.json
```

No production adapter interface is changed. The probe is intentionally isolated
from `src/redline_core` because it is an evidence-gathering mission artifact,
not an approved production capability.

## 4. Architecture

### 4.1 Two-stage evidence flow

```text
Operator-prepositioned Resolve context
                |
                v
Single-context snapshot collector
                |
       +--------+--------+
       |                 |
       v                 v
control.json       production.json
       |                 |
       +--------+--------+
                |
                v
Pure offline comparator
                |
                v
comparison.json
```

The collector handles one already-open project and one already-current timeline
per invocation. It never loads or switches project/timeline state.

The comparator reads two JSON documents and never imports or contacts Resolve.

### 4.2 Why one snapshot per invocation

The Resolve scripting API exposes full project/timeline detail primarily for
the current project. Automatically loading the second project would mutate the
active Resolve context and violate this mission's read-only boundary.

Therefore, a future authorized operator must manually pre-position Resolve
before each snapshot:

1. Control context:
   - Project: `redline-os-test-duplicate`
   - Timeline: `RLO-LIVE-ASM-92701_TIMELINE`
2. Production-like context:
   - Project: `RLC-E9001_MASTER`
   - Timeline: `RLC-E9001_TIMELINE`

Manual pre-positioning is not authorized by this construction mission. It is a
future execution-contract requirement.

## 5. Snapshot evidence contract

### 5.1 Required root fields

A complete snapshot contains:

```json
{
  "schema_version": "1.0",
  "mission": "Phase 14 — Dual Project/Timeline Read-Only Snapshot Probe",
  "captured_at": "UTC timestamp",
  "snapshot_complete": true,
  "expected_context": {},
  "session": {},
  "project_manager": {},
  "project": {},
  "target_timeline": {},
  "media_pool": {},
  "pre_guard": {},
  "post_guard": {},
  "ambiguity_policy": {}
}
```

Missing required sections or `snapshot_complete != true` make a comparison
invalid.

### 5.2 Optional observation envelope

Optional API values use this envelope:

```json
{
  "source_method": "GetSetting",
  "status": "observed",
  "value_type": "dict",
  "value": {},
  "error": null
}
```

Allowed statuses:

- `observed`
- `unavailable`
- `error`

An arbitrary Resolve bridge object is never converted with `repr()` or `str()`.
Unsupported values become structured errors.

### 5.3 Session controls

The collector records:

- product name;
- version tuple/list, when available;
- version string, when available.

At least one usable version representation is required. Session identity is
captured again after collection; any change fails closed.

The offline comparator refuses comparison when the two snapshots do not expose
the same Resolve version identity.

### 5.4 Project-manager metadata

Optional read-only observations:

- project list in the current project-manager folder;
- project attributes in the current project-manager folder.

These fields may expose project record dates, notes, collaboration flags, or
other version-dependent attributes. They are evidence only and cannot prove a
cause.

### 5.5 Project evidence

The collector records:

- exact current project name;
- project settings dictionary, when available;
- complete timeline count and timeline inventory;
- exact-name duplicate detection;
- render preset name inventory, when available;
- sanitized render queue inventory;
- current render format/codec, mode, and settings, when available.

Current render context is marked context-sensitive. It may reflect prior Deliver
page or preset activity and is not treated as intrinsic project identity.

### 5.6 Timeline evidence

The target timeline records:

- exact name;
- unique ID, when available;
- start and end frame, when available;
- start timecode, when available;
- timeline settings, when available;
- marker dictionary, when available;
- complete required video/audio track counts;
- optional subtitle track count;
- complete item inventory for every observed track.

A required track count or item collection that is malformed or incomplete stops
the snapshot.

### 5.7 Timeline-item evidence

Each timeline item records:

- track type and one-based track index;
- zero-based item index in the returned collection;
- item name;
- unique ID;
- start, end, and duration;
- left/right offsets;
- source start/end frame;
- enabled state;
- associated media-pool item metadata.

Optional accessors may be unavailable on a specific Resolve version or item
type. Unavailability is recorded without inventing a value.

### 5.8 Media-pool evidence

The media-pool hierarchy records:

- folder name and full hierarchy path;
- clips in each folder;
- complete subfolder traversal;
- clip name;
- media ID and unique ID, when available;
- complete clip property dictionary, when available.

If a folder name is missing or non-string, the deterministic sentinel is used:

```text
<folder-name-unavailable>
```

Repeated or cyclic folder handles fail closed and report both the first and
repeated hierarchy paths.

### 5.9 Guard evidence

The pre- and post-collection guards contain:

- project name;
- timeline count;
- current timeline name;
- target timeline name;
- literal rendering-in-progress boolean;
- queue count;
- sanitized queue fingerprint.

Collection is allowed only when:

- project name exactly matches the expected value;
- current and target timeline names exactly match the expected value;
- rendering is literally `False`;
- render queue count is zero.

Any pre/post difference fails as snapshot identity drift.

## 6. Closed read-only API surface

Every dynamically dispatched Resolve method must appear in the source's
`READ_ONLY_RESOLVE_METHODS` allowlist.

The allowlist covers only getters used for:

- Resolve product/version identity;
- project-manager/current-project inspection;
- project/timeline enumeration and settings;
- media-pool hierarchy and clip metadata;
- render queue/preset/context inspection;
- timeline track/item metadata.

The source separately defines `PROHIBITED_RESOLVE_METHODS`. Static tests verify
that:

- the allowlist and prohibited set do not overlap;
- no prohibited method is directly called;
- no direct `DaVinciResolveScript` import statement exists.

The connection function contains the module name only as a future dynamic import
target. It is unreachable from the construction `snapshot` CLI because the
hard-disable check executes first.

## 7. Fail-closed error classes

Representative snapshot stop codes:

| Code | Meaning |
|---|---|
| `live_execution_disabled` | Construction artifact cannot contact Resolve. |
| `project_identity_mismatch` | Current project is not the exact expected project. |
| `expected_timeline_missing` | Expected timeline was not found. |
| `duplicate_expected_timeline` | More than one exact-name timeline matched. |
| `current_timeline_mismatch` | Current timeline differs from the expected target. |
| `invalid_count` | Required count is boolean, negative, or non-integer. |
| `invalid_collection` | Required collection has an invalid outer type. |
| `rendering_active` | Resolve reports an active render. |
| `render_queue_not_empty` | Render queue is not empty. |
| `repeated_media_pool_folder_handle` | Repeated/cyclic hierarchy handle detected. |
| `snapshot_identity_drift` | Guarded state changed during collection. |
| `resolve_session_drift` | Product/version identity changed during collection. |
| `unsupported evidence type` | A bridge handle or unsupported value reached JSON normalization. |

No failure triggers cleanup because the collector performs no authorized live
mutation.

## 8. Offline comparison contract

### 8.1 Comparison classifications

Each compared leaf is classified as one of:

- `equal`
- `different`
- `unavailable_on_control`
- `unavailable_on_production`
- `unavailable_on_both`
- `structurally_invalid`
- `context_sensitive`

A version mismatch produces an overall `incomparable` result with no property
records.

### 8.2 Expected identity normalization

The two contexts intentionally have different project and target timeline
names. Before property comparison, these expected names are normalized to:

```text
<expected-project>
<expected-timeline>
```

This prevents known identity labels from being misreported as candidate
root-cause differences. Other timeline names remain unchanged so unexpected
inventory differences stay visible.

### 8.3 Overall outcomes

Possible overall outcomes:

- `incomparable`
- `ambiguous_due_to_structural_errors`
- `differences_observed`
- `no_exposed_intrinsic_difference_observed_with_gaps`
- `no_exposed_intrinsic_difference_observed`

These outcomes describe exposed API evidence only.

### 8.4 Mandatory interpretation limits

Every comparison report states:

1. A difference is a candidate discriminator, not a proven cause.
2. Equality does not rule out hidden Resolve state.
3. Current render context is context-sensitive, not intrinsic identity.
4. A comparison does not authorize repair or a mutating experiment.

## 9. API limitations

This design cannot reliably obtain:

- an explicit read-only answer to whether `AddRenderJob()` would succeed;
- the hidden rejection reason used by Resolve queue acceptance;
- a corruption or project-health flag;
- a repair recommendation;
- a complete settings dictionary for a named preset without loading it;
- a reliable project dirty/unsaved-state flag;
- inactive-project timeline/media details without switching projects;
- UI-only warnings or disabled-control state;
- proof that Resolve can create an output file without a write or queue action;
- internal project/timeline state not exposed through the scripting API.

The probe must not convert these limitations into assumptions.

## 10. Mocked validation matrix

The unit suite covers:

- module import without Resolve import;
- hard-disabled snapshot CLI stopping before connection;
- valid complete mocked snapshot;
- wrong project;
- duplicate exact timeline;
- current timeline mismatch;
- active rendering;
- nonempty queue with sanitized evidence;
- boolean timeline count rejection;
- repeated/cyclic media-pool folder detection;
- pre/post identity drift;
- unsupported bridge object rejection without `repr()`;
- cyclic JSON container rejection;
- optional absent accessor classification;
- queue value sanitization;
- intrinsic vs context-sensitive comparison;
- unavailable-value comparison;
- Resolve version mismatch;
- incomplete snapshot rejection;
- offline compare without Resolve import;
- static absence of direct Resolve import and prohibited calls;
- allowlist/prohibited-set disjointness;
- hash printing without connection.

## 11. Safe construction-time commands

The following commands do not contact Resolve:

```powershell
python -m py_compile `
  scripts\phase14_resolve_context_snapshot.py `
  tests\unit\test_phase14_resolve_context_snapshot.py

pytest -q tests\unit\test_phase14_resolve_context_snapshot.py

python scripts\phase14_resolve_context_snapshot.py --print-sha256
```

Offline comparison is safe only when it reads previously reviewed JSON files:

```powershell
python scripts\phase14_resolve_context_snapshot.py compare `
  --control .\control.json `
  --production .\production.json `
  --output .\comparison.json
```

The following command is intentionally blocked in this construction artifact:

```powershell
python scripts\phase14_resolve_context_snapshot.py snapshot `
  --expected-project RLC-E9001_MASTER `
  --expected-timeline RLC-E9001_TIMELINE `
  --output .\production.json
```

It must return `live_execution_disabled` before any Resolve import or contact.

## 12. Future live-capture authorization requirements

Before enabling snapshot execution, a separately numbered mission must specify:

- exact repository commit;
- exact source path and SHA-256;
- exact Resolve version;
- exact project and timeline for each capture;
- exact allowed getter set;
- exact prohibited calls;
- empty queue and inactive-render preconditions;
- one invocation per context;
- output evidence paths;
- abort conditions;
- expected exit classifications;
- evidence preservation requirements;
- confirmation that no mutation or cleanup is authorized.

Enabling execution requires a source change and therefore a new hash. The
construction hash must never be treated as an execution authorization hash.

## 13. Repository integration and publication

This bundle was created outside the canonical repository. No repository file,
Git reference, runtime database, Resolve state, or remote state was changed.

A future founder decision is required before:

- copying these files into the repository;
- updating `docs/ROADMAP.md`;
- updating `docs/CHANGELOG.md`;
- staging or committing;
- pushing or opening a pull request.

Suggested future commit subject, only after separate publication authorization:

```text
feat: add Phase 14 read-only context comparison probe
```

## 14. Stop condition

The construction mission stops after:

- source completion;
- mocked test completion;
- static safety review;
- architecture contract completion;
- SHA-256 generation;
- delivery for founder review.

No live execution follows from construction approval.

**Agents advise. Paul decides.**
