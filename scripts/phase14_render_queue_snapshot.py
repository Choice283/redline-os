"""Phase 14 render queue read-only snapshot and offline acceptance probe.

Construction status
--------------------
Rev3: correction revision. Independent exact-source review confirmed that
Rev2 successfully corrected all six Rev1 findings, but Rev2 itself did not
pass review: two further evidence-integrity gaps were independently
reproduced (see "Rev2 -> Rev3 findings and corrections" below). This
revision corrects both. **Rev3 has not itself been independently reviewed
or approved as of this revision** — it is submitted for review, not a claim
of passing review. No live execution has occurred against Rev1, Rev2, or
Rev3. Live snapshot collection remains gated by an explicit
execution interlock (see ``enforce_execution_interlock``) — a deliberate
execution control, not authentication and not a security secret. It exists
so an operator cannot reach Resolve by accident, not to resist a determined
adversary. Reaching Resolve requires the CLI caller to pass
``--execution-authorization <revision-id>`` on the ``snapshot`` subcommand,
where ``<revision-id>`` must exactly equal ``EXECUTION_REVISION_ID`` below.
Construction of this probe does not itself authorize live execution; a
future founder authorization for live use must still bind the exact
repository commit, this exact source SHA-256, this exact
``EXECUTION_REVISION_ID``, the exact expected project/timeline, and the
exact evidence output path.

Rev1 -> Rev2 findings and corrections
----------------------------------------
1. BLOCKING (exact queue-closure semantics): Rev1's ``exactly_one_matching_job``
   classification was true even when additional queue entries existed,
   producing a false-pass through ``run_compare_command()``'s exit code.
   Rev2 replaces the classification model with five mutually exclusive,
   explicit outcomes (see ``compare_expected_job_id``); exactly one,
   ``"exact_single_job_match"``, means formal single-job closure, and it is
   the only classification for which ``run_compare_command()`` exits ``0``
   when ``--expected-job-id`` is supplied.
2. BLOCKING (snapshot invariant validation): Rev1's
   ``validate_queue_snapshot_document()`` checked structural shape only,
   not internal consistency — a forged snapshot with mismatched
   expected/observed context, ``rendering_in_progress: true``, or a
   ``render_queue_count`` that disagreed with the actual queue length could
   still reach a successful classification. Rev2's validator checks
   document identity (schema version, mission, collector name/revision
   policy), expected/observed context equality, ``rendering_in_progress is
   False`` exactly, ``render_queue_count == len(render_queue)``, and every
   entry's shape/index/status/job-ID/field validity, including identified
   job-ID uniqueness — before any comparison logic runs.
3. HIGH (conflicting job-ID aliases): Rev1's ``_job_id_key_status()`` used
   Rev8's ``queue_job_id()`` precedence-ordered lookup, which silently
   picked the first matching alias when two recognized aliases held
   different values. Rev2 collects every recognized alias's normalized
   value and fails closed when more than one distinct value is present.
4. HIGH (strict JSON / non-finite floats): Rev8's imported
   ``normalize_json_value``/``write_json_no_overwrite`` permit
   NaN/Infinity/-Infinity through Python's permissive ``json`` defaults
   (RFC 8259 does not define these). Rev2 adds a local, probe-owned strict
   layer (``require_finite_json_value``, ``write_strict_json_no_overwrite``)
   that rejects any non-finite float before a snapshot is returned from
   collection and before either CLI output path publishes evidence. Rev8
   is not modified.
5. HIGH (final rendering/context bracket): Rev1 checked project/timeline
   identity and ``IsRenderingInProgress()`` only immediately before each of
   the two ``GetRenderJobList()`` reads, with no check at all after the
   second read. Rev2 adds a third context/rendering verification, with no
   further queue read, strictly after the second ``GetRenderJobList()``
   call returns, and uses that final verification's observed values in the
   published snapshot.
6. Documentation accuracy: Rev1 described ``connect_resolve_read_only`` as
   a "pure"/"Resolve-contact-free" helper alongside genuinely pure
   functions. Corrected throughout this docstring and
   ``docs/PHASE14_RENDER_QUEUE_SNAPSHOT_CONTRACT.md``: importing it performs
   no Resolve contact, but *calling* it is this probe's own deliberate live
   Resolve connection boundary, gated by the execution interlock exactly as
   before. ``validate_output_path``/``write_json_no_overwrite``/
   ``load_json``/``script_sha256`` are also no longer described as "pure"
   — they inspect or write filesystem state — only as never contacting
   Resolve.

Rev2 -> Rev3 findings and corrections
----------------------------------------
Independent exact-source review confirmed all six Rev1 findings above were
correctly resolved by Rev2, but found two further evidence-integrity gaps,
both corrected here:

1. BLOCKING (cross-validate normalized Job ID against preserved fields):
   Rev2's ``validate_queue_snapshot_document()`` validated ``job_id``/
   ``job_id_status`` and the preserved ``fields`` payload independently of
   each other. A forged entry such as ``{"job_id": "expected",
   "job_id_status": "identified", "fields": {"JobId": "OTHER"}}`` — an
   internally contradictory document no honest collection could produce —
   still reached ``exact_single_job_match``. Rev3 re-derives the canonical
   job-ID classification from each entry's own ``fields`` using the exact
   same ``_job_id_key_status()`` rules live collection uses, and requires
   the derived status/job-ID to agree exactly with the entry's stored
   ``job_id_status``/``job_id`` — failing closed on disagreement, and on
   any malformed or conflicting alias discoverable within ``fields`` itself,
   exactly as live collection would.
2. BLOCKING (evidence envelope must match an actual Rev3 snapshot): Rev2's
   validator tolerated unknown top-level keys and did not validate
   ``captured_at`` at all — a forged document with a missing, null, NaN, or
   malformed ``captured_at``, or an arbitrary extra top-level key, could
   still reach a successful comparison. Rev3 requires the document's
   top-level keys to be exactly the ten keys this collector ever produces
   (no more, no fewer) and requires ``captured_at`` to be a non-empty
   string matching ``utc_now()``'s exact emitted shape
   (``YYYY-MM-DDTHH:MM:SS.ffffffZ``) and to parse as a genuine calendar
   instant, not merely match that shape. The complete accepted document —
   not merely each entry's ``fields`` — is now required to be strict,
   finite-only JSON.

Additional hardening (not itself one of the two findings above):
``compare_expected_job_id()`` now requires a non-``None``
``expected_job_id`` to be a non-empty string; a whitespace-only or
non-string value fails closed rather than being silently treated as an
ordinary zero-match query. This does not change behavior for any
legitimate CLI invocation (argparse always supplies either ``None`` or a
real string).

New execution revision identifier minted: ``phase14.2-render-queue-snapshot-construction-rev3``.
Rev2's identifier is explicitly rejected by both the execution interlock
and ``ACCEPTED_COLLECTOR_REVISIONS``.

Rev3 -> Rev4: target-job status
----------------------------------
Independent RLC-E9901 final-ignition tool-selection review found the one gap
in Rev3's evidence: the final ignition preflight also needs the target
job's own ``JobStatus`` (to prove ``Ready`` before a future, separately
authorized start), and ``GetRenderJobList()`` does not return that field —
confirmed empirically from the real Rev3 RLC-E9901 evidence, whose queue
entry has no ``JobStatus`` key at all. The repository's production adapter
obtains ``JobStatus`` through a different getter, ``Project.GetRenderJobStatus
(job_id)``, which Rev3 did not call.

Rev4 adds exactly that one getter, closed over the same fail-closed
discipline as every other field this probe captures:

* ``GetRenderJobStatus`` is added to ``READ_ONLY_RESOLVE_METHODS`` (six
  methods -> seven). No other method name is added.
* ``snapshot`` (live collection) calls ``GetRenderJobStatus(job_id)`` once
  per **identified** queue entry only — an unidentified entry has no job ID
  to query — using the same current-project handle the final identity/
  rendering guard already confirmed, after the pre/post drift check has
  already proven the queue itself did not change. The response is
  sanitized strictly: anything other than a dict containing a non-empty
  string ``JobStatus`` fails the **entire** snapshot collection closed
  (``render_job_status_missing`` / ``render_job_status_invalid`` /
  ``render_job_status_field_missing`` / ``render_job_status_field_invalid``)
  rather than publishing a placeholder — a completed Rev4 snapshot's
  ``job_status`` is therefore always either a trustworthy non-empty string
  (identified entries) or ``None`` (unidentified entries), never an
  "unavailable" or "malformed" value a later comparison might be tempted to
  treat leniently. This mirrors the existing ``job_id``/``job_id_status``
  precedent exactly.
* ``compare`` (offline evaluation) remains **completely** Resolve-contact-
  free — Rev4 does not add any Resolve call to ``compare``. It gains one new
  optional argument, ``--expected-job-status``, which inspects the
  already-captured ``job_status`` of whatever entry ``--expected-job-id``
  resolves to (only when that resolves unambiguously to
  ``exact_single_job_match``) and fails closed
  (``expected_job_status_invalid`` / ``expected_job_status_requires_expected_job_id``
  / a ``"not_applicable"``-or-``"status_mismatch"`` ``job_status_check``
  classification, both mapped to a nonzero CLI exit code) rather than ever
  treating a missing, ambiguous, or mismatched status as ``Ready``. Omitting
  ``--expected-job-status`` reproduces Rev3's exact existing behavior and
  exit codes — this is a strictly additive, backward-compatible change.

New execution revision identifier minted:
``phase14.2-render-queue-snapshot-construction-rev4``. Rev1/Rev2/Rev3's
identifiers are all explicitly rejected by both the execution interlock and
``ACCEPTED_COLLECTOR_REVISIONS``. ``SCHEMA_VERSION`` is deliberately left at
``"1.0"`` — consistent with Rev1->Rev2->Rev3 precedent: compatibility across
construction revisions is already gated by ``collector.revision`` /
``ACCEPTED_COLLECTOR_REVISIONS``, not by ``schema_version``.

Rev4 construction status: no live Resolve execution occurred while building
or verifying this revision. ``snapshot``'s live path has not been exercised
against a real, running Resolve instance under Rev4; only mocked unit tests
exercise the new ``GetRenderJobStatus`` code path. A separate, explicit
founder authorization — binding this exact source SHA-256, this exact
``EXECUTION_REVISION_ID``, the expected project/timeline, and a fresh
evidence path — is required before any future live invocation, exactly as
for every prior revision.

Rev4 -> Rev5: post-status temporal rebracket
-----------------------------------------------
Independent Rev4 source review found the one publication-blocking gap in
the Rev4 addition: the new ``GetRenderJobStatus()`` calls happen *after*
Rev2/Rev3's own "final" identity/rendering guard, and nothing re-establishes
project identity, timeline identity, ``rendering == false``, or queue
stability *after* those calls, before evidence is published. Classified
``POST_STATUS_REBRACKET_REQUIRED``: a published Rev4 snapshot could
combine a `rendering=false` observation from *before* the status-fetch
window with a `JobStatus=Ready` observation from *during/after* it, without
proving Resolve's surrounding state stayed put across that window — exactly
the class of gap Rev2 Finding 5 closed for the original two-read bracket,
reopened by Rev4 in a new location because Rev4 inserted real, new Resolve
round-trips into what had previously been an immediate finalization step.

Rev5 closes it with the smallest correction that reuses only already-
allowlisted methods — no new Resolve method name is introduced:

* Renamed (conceptually, not renamed in code) Rev2/Rev3/Rev4's own third
  guard from "final" to **pre-status**: it still runs immediately before
  the ``GetRenderJobStatus()`` calls, exactly as in Rev4, and its project
  handle is still what those calls use — Rev5 does not move, remove, or
  weaken ``GetRenderJobStatus()`` itself.
* A new **post-status rebracket** (``_post_status_rebracket()``) runs
  strictly after every ``GetRenderJobStatus()`` call has returned and
  strictly before the snapshot dict is constructed. It re-verifies project
  identity, timeline identity, and ``IsRenderingInProgress() is False``
  (reusing ``_verify_context_and_rendering_inactive()`` unchanged), **and**
  re-reads the render queue a third time (``GetRenderJobList()``, reusing
  the same already-allowlisted method the A/B reads already use) and
  requires it to normalize identically to the already drift-verified B
  queue — fail closed (``post_status_queue_drift``) otherwise. Queue
  stability is explicitly re-proven, not merely assumed: the whole reason
  ``JobStatus`` is worth capturing is to combine it with the queue's own
  identity claims (count, exact job presence, output binding) for a single,
  simultaneous final-ignition proof, so those claims must be shown to still
  hold *after* the status-fetch window, not only as of the read that chose
  which job IDs to query.
* The published snapshot's ``observed_context``/``rendering_in_progress``
  now come from the post-status rebracket's own fresh observation — never
  from the pre-status guard's now-stale one.
* No new Resolve method is added: the allowlist remains the same seven
  methods Rev4 introduced (``GetRenderJobList`` is simply called a third
  time; ``GetProjectManager``/``GetCurrentProject``/``GetName``/
  ``GetCurrentTimeline``/``IsRenderingInProgress`` a fourth).

Full corrected live call sequence::

    verify expected current project/timeline, IsRenderingInProgress -> false   [guard 1]
    GetRenderJobList -> A

    verify expected current project/timeline, IsRenderingInProgress -> false   [guard 2]
    GetRenderJobList -> B

    require normalized A == normalized B

    verify expected current project/timeline, IsRenderingInProgress -> false   [guard 3, pre-status]

    GetRenderJobStatus -> once per identified entry in B

    verify expected current project/timeline, IsRenderingInProgress -> false   [guard 4, post-status]
    GetRenderJobList -> C
    require normalized C == normalized B

    publish evidence using guard 4's observed_context/rendering_in_progress

New execution revision identifier minted:
``phase14.2-render-queue-snapshot-construction-rev5``. Rev1/Rev2/Rev3/Rev4's
identifiers are all explicitly rejected by both the execution interlock and
``ACCEPTED_COLLECTOR_REVISIONS`` — consistent with existing policy, not
broadened; a Rev4 snapshot document (which lacks the post-status rebracket
guarantee entirely) must not be trusted as if it were Rev5 evidence.

Rev5 construction status: no live Resolve execution occurred while building
or verifying this revision — only mocked unit tests exercise the new
post-status rebracket code path. A separate, explicit founder authorization
is required before any future live invocation, exactly as for every prior
revision.

Purpose and distinction from ``phase14_resolve_context_snapshot.py``
----------------------------------------------------------------------
``scripts/phase14_resolve_context_snapshot.py`` (the "Rev8 collector") is a
*pre-mutation comparison* probe: its own safety model
(``enforce_safe_guard_state``) requires the Resolve render queue to be
*empty* before it will complete a snapshot, because its purpose is
capturing two clean, comparable Control/Production baselines.

This probe is the deliberate complement: it exists specifically to inspect
an EXISTING, possibly *non-empty* render queue without mutating Resolve, so
a queue-attempt result (such as the RLC-E9901 Broadcast Master
``PRODUCTION_QUEUE_PATH_ACCEPTED`` queue-attempt outcome) can be
independently corroborated by observing the actual Resolve queue entry and
its Resolve job ID — evidence the Rev8 collector cannot produce because it
refuses to run against a non-empty queue by design. This probe does not
weaken or replace the Rev8 collector's own invariant; the two probes serve
different, non-overlapping moments in the Phase 14 workflow.

This probe is generically parameterized (expected project/timeline are
caller-supplied, not hardcoded) so it is reusable for any future Redline OS
queue-state evidence collection, not only RLC-E9901.

Architecture: reuse without allowlist leakage
------------------------------------------------
Genuinely pure (no I/O, no Resolve, deterministic) helpers and constants
are imported directly from the already multiply-reviewed Rev8 collector,
whose own module docstring states "The module may be imported and its pure
comparison functions may be exercised freely": ``SnapshotError`` (generic
``{code, message, details}`` error contract), ``UnsupportedEvidenceType``,
``normalize_json_value``, ``QUEUE_JOB_ID_KEYS``, ``require_nonempty_string``,
``require_collection``, ``PROHIBITED_RESOLVE_METHODS``.

Two further groups are imported that are **not** claimed to be "pure" —
Rev1 imprecisely lumped them in with the pure group; Rev2 corrects that
(Finding 6):

* ``utc_now`` reads the wall clock — deterministic Resolve/filesystem-free
  behavior, but not a pure function in the referential-transparency sense.
* ``load_json``, ``script_sha256``, ``validate_output_path``, and
  ``write_json_no_overwrite`` inspect or write local filesystem state.
  They never contact Resolve — that is the property this probe actually
  relies on — but "never contacts Resolve" and "pure" are not the same
  claim, and only the former is true of these four.

``connect_resolve_read_only`` is imported and reused unchanged, but is
**not** in either group above: it is Rev8's own deliberate live Resolve
connection boundary function. *Importing* it performs no Resolve contact
(confirmed by the mocked test suite's
``test_module_import_does_not_contact_resolve``). *Calling* it is exactly
the point at which this probe — deliberately, and only after
``enforce_execution_interlock`` has already passed — contacts Resolve.
Describing it as "pure" or "Resolve-contact-free" in the same breath as the
genuinely pure helpers, as Rev1 did, materially understates what calling it
does.

None of the names imported from Rev8 are closed over Rev8's own
``READ_ONLY_RESOLVE_METHODS`` allowlist or Rev8's own
``EXECUTION_REVISION_ID``, so importing them cannot widen this probe's own
Resolve surface or its own execution interlock.

Deliberately NOT imported and instead reimplemented narrowly in this
module: Rev8's ``_resolve_method``/``call_required``/``observe_optional``
dynamic-dispatch helpers, Rev8's ``enforce_execution_interlock``, and (as of
Rev2) Rev8's ``queue_job_id`` precedence-ordered lookup. The first two are
closed over Rev8's own broader allowlist / own revision identifier (see
Rev1's rationale, unchanged). ``queue_job_id`` is no longer imported because
Rev2's conflicting-alias detection (Finding 3) requires collecting every
recognized alias's value, not just the first match Rev8's own function
returns — reusing it would have hidden exactly the conflict this probe must
now detect. ``QUEUE_JOB_ID_KEYS`` (the plain tuple of recognized alias
names) is still imported and reused; only the lookup *function* was
replaced. Rev8 itself is not modified in any way by this construction; its
source bytes and published SHA-256 are unchanged.

Safety design
-------------
* No Resolve module import occurs at module import time.
* The ``snapshot`` CLI path stops at the execution interlock, before output
  validation, before ``DaVinciResolveScript`` import, and before
  connection, unless the caller supplies the exact matching
  ``--execution-authorization``.
* Output paths are validated for pre-existence before Resolve contact and
  are never overwritten (create-only atomic publication).
* Snapshot collection accepts an injected Resolve handle for mocked tests.
* Every dynamically dispatched Resolve method is restricted to a closed,
  getter-only allowlist (``READ_ONLY_RESOLVE_METHODS``) — six methods
  through Rev3, unchanged from Rev1; Rev4 adds exactly one
  (``GetRenderJobStatus``) and no other.
* No project or timeline switch is attempted.
* No render preset is loaded and no render setting is changed.
* No render job is created, deleted, started, stopped, or cancelled.
* An existing non-empty render queue is explicitly permitted and expected
  — this is the one invariant that differs from the Rev8 collector.
* Ambiguous, malformed, conflicting, or duplicate-job-ID queue state fails
  closed.
* Every published snapshot is independently re-verified (project/timeline
  identity, rendering inactive) a third time, with no further queue read,
  strictly after the second ``GetRenderJobList()`` call returns (Rev2,
  Finding 5).
* Every value this probe writes to disk is required to be strict,
  finite-only JSON, independent of Rev8's own more permissive default
  (Rev2, Finding 4).
* Offline acceptance comparison never imports or contacts Resolve, and
  fails closed on any internally inconsistent snapshot document before
  producing a classification (Rev2, Finding 2).
* A snapshot document's stored ``job_id``/``job_id_status`` per entry must
  agree exactly with the classification independently re-derived from that
  same entry's own preserved ``fields``; an internally contradictory
  document fails closed rather than being trusted (Rev3, Finding 1).
* A snapshot document's top-level keys must be exactly the ten keys this
  collector ever produces, and ``captured_at`` must match this collector's
  exact emitted timestamp shape and name a real calendar instant; the
  complete document, not merely each entry's ``fields``, must be strict,
  finite-only JSON (Rev3, Finding 2).
* (Rev4) ``GetRenderJobStatus`` is called only for identified queue entries,
  only after the pre/post drift check and the pre-status identity/rendering
  guard have both already passed; a malformed, missing, or otherwise
  unusable response fails the entire snapshot closed rather than publishing
  a placeholder value. ``compare`` remains completely Resolve-contact-free —
  its optional ``--expected-job-status`` assertion only inspects
  already-captured evidence and never calls Resolve itself.
* (Rev5) A post-status rebracket runs strictly after every
  ``GetRenderJobStatus()`` call and strictly before evidence is published:
  it re-verifies project identity, timeline identity, and
  ``IsRenderingInProgress() is False`` again, and re-reads the render queue
  a third time, requiring it to equal the already drift-verified queue
  exactly (``post_status_queue_drift`` otherwise). The published snapshot's
  ``observed_context``/``rendering_in_progress`` come from this rebracket,
  never from the earlier pre-status guard. No new Resolve method is
  introduced — ``GetRenderJobList`` is simply read a third time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REVIEW_ROOT = Path(__file__).resolve().parents[1]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts.phase14_resolve_context_snapshot import (  # noqa: E402
    PROHIBITED_RESOLVE_METHODS,
    QUEUE_JOB_ID_KEYS,
    SnapshotError,
    UnsupportedEvidenceType,
    connect_resolve_read_only,
    load_json,
    normalize_json_value,
    require_collection,
    require_nonempty_string,
    script_sha256,
    utc_now,
    validate_output_path,
    write_json_no_overwrite,
)

MISSION = "Phase 14 — Render Queue Read-Only Snapshot Probe"
SCHEMA_VERSION = "1.0"
COLLECTOR_NAME = "phase14_render_queue_snapshot"

# Immutable for this exact source revision. See the module docstring's
# "Construction status" section. A future source change requires a new
# identifier minted together with a new SHA-256, both reviewed together and
# bound to founder authorization.
EXECUTION_REVISION_ID = "phase14.2-render-queue-snapshot-construction-rev5"
# Both endpoints must be alphanumeric (a trailing '.', '_', or '-' is
# rejected, not just a leading one); total length 2-80 characters.
EXECUTION_REVISION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}[A-Za-z0-9]$")

# The exact, documented acceptance policy for compare_expected_job_id()'s
# input (Rev2, Finding 2): only a snapshot whose own collector.revision
# equals this exact source revision is accepted. No prior revision's live
# evidence exists (Rev1 and Rev2 were never executed live), and accepting
# an older or different revision's output would mean trusting a document
# collected under different, possibly weaker, validation semantics than
# the ones this exact source now enforces. Remains fail-closed to exactly
# the current revision in Rev3 -- no concrete reason to widen it was
# identified during this correction's architecture review. A future
# revision that legitimately needs to accept additional historical
# revisions must do so by deliberately widening this frozenset, reviewed
# as its own change.
ACCEPTED_COLLECTOR_REVISIONS = frozenset({EXECUTION_REVISION_ID})

# ---------------------------------------------------------------------------
# Getter-only Resolve surface — deliberately the smallest set that satisfies
# the mission's required design properties: verify current project identity,
# verify current timeline identity, verify rendering is not active, read the
# render queue, and (Rev4) read the JobStatus of each identified queue
# entry. See the module docstring for why this is not imported from Rev8's
# own, broader allowlist. Six methods through Rev3; Rev4 adds exactly one
# (``GetRenderJobStatus``) and no other.
# ---------------------------------------------------------------------------
READ_ONLY_RESOLVE_METHODS = frozenset(
    {
        "GetProjectManager",
        "GetCurrentProject",
        "GetName",
        "GetCurrentTimeline",
        "IsRenderingInProgress",
        "GetRenderJobList",
        "GetRenderJobStatus",
    }
)

# Explicitly prohibited for this probe. Reused verbatim from the Rev8
# collector's own reviewed constant: a plain frozenset of method-name
# strings, safe to import because reuse can only ever make this probe's own
# static prohibition scan more inclusive, never grant it access.
_PROHIBITED_RESOLVE_METHODS = PROHIBITED_RESOLVE_METHODS


class QueueSnapshotError(SnapshotError):
    """Fail-closed error for this probe. Reuses Rev8's ``{code, message,
    details}`` contract and its ``normalize_json_value``-backed
    serialization verbatim; only the class name differs, so a caller can
    distinguish this probe's errors from Rev8's own without any behavioral
    difference."""


@dataclass(frozen=True)
class QueueSnapshotContext:
    expected_project: str
    expected_timeline: str


# ---------------------------------------------------------------------------
# Narrow, self-contained getter-only dispatch — closed over this module's
# own READ_ONLY_RESOLVE_METHODS, not Rev8's. Unchanged from Rev1.
# ---------------------------------------------------------------------------


def _resolve_method(obj: Any, method_name: str) -> Callable[..., Any]:
    if method_name not in READ_ONLY_RESOLVE_METHODS:
        raise QueueSnapshotError(
            "accessor_not_allowlisted",
            f"Resolve accessor is not in the approved read-only allowlist: {method_name}",
        )
    try:
        method = getattr(obj, method_name)
    except Exception as exc:
        raise QueueSnapshotError(
            "accessor_lookup_failed",
            f"Resolve accessor lookup raised for {method_name}",
            details={"method": method_name, "error_type": type(exc).__name__},
        ) from exc
    if not callable(method):
        raise QueueSnapshotError(
            "accessor_unavailable",
            f"Resolve accessor is not callable: {method_name}",
            details={"method": method_name},
        )
    return method


def call_required(obj: Any, method_name: str, *args: Any) -> Any:
    method = _resolve_method(obj, method_name)
    try:
        return method(*args)
    except QueueSnapshotError:
        raise
    except Exception as exc:
        raise QueueSnapshotError(
            "accessor_call_failed",
            f"Resolve accessor raised: {method_name}",
            details={"method": method_name, "error_type": type(exc).__name__},
        ) from exc


# ---------------------------------------------------------------------------
# Strict JSON layer (Rev2, Finding 4). Local to this probe; Rev8 unchanged.
# ---------------------------------------------------------------------------


def require_finite_json_value(value: Any, *, _path: str = "$") -> Any:
    """Recursively walk an already-``normalize_json_value``'d JSON-safe value
    and fail closed on any non-finite float (NaN, +Infinity, -Infinity).

    ``normalize_json_value()`` (imported from Rev8) already guarantees the
    value contains only ``None``/``str``/``bool``/``int``/``float``/``list``/
    ``dict`` with string keys — it does not itself reject non-finite
    floats, and neither does Rev8's own ``write_json_no_overwrite()``'s
    ``json.dumps()``/``json.loads()`` calls (both use Python's permissive
    ``allow_nan=True`` default). RFC 8259 does not define NaN/Infinity/
    -Infinity, so Python's default JSON handling of them is a Python-only
    extension, not standard JSON. This function is this probe's own local
    strict-JSON layer, applied to every value before it is returned from
    collection and before either CLI output path publishes evidence, and
    defensively while validating an *input* snapshot document's per-entry
    ``fields`` payloads.
    """

    if isinstance(value, float):
        if not math.isfinite(value):
            raise QueueSnapshotError(
                "non_finite_float_in_evidence",
                "A non-finite float (NaN or +/-Infinity) is not permitted in strict JSON evidence",
                details={"path": _path},
            )
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            require_finite_json_value(item, _path=f"{_path}.{key}")
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            require_finite_json_value(item, _path=f"{_path}[{index}]")
        return value
    return value


def write_strict_json_no_overwrite(path: Path, value: Any) -> None:
    """This probe's local strict-JSON, create-only, no-overwrite evidence writer.

    Wraps Rev8's already-reviewed ``write_json_no_overwrite`` (unchanged)
    with two additional, local guarantees Rev8's own generic writer does
    not provide: (1) every float in ``value`` is required finite via
    ``require_finite_json_value`` before any write is attempted; (2) an
    explicit, redundant ``json.dumps(..., allow_nan=False)`` re-validation
    immediately afterward, so a future change to
    ``require_finite_json_value``'s coverage cannot silently reopen this
    gap. Delegates the actual write to ``write_json_no_overwrite``
    unchanged — this does not weaken or duplicate Rev8's own create-only
    atomic publication guarantee (see its own docstring for the exact
    temp-file-then-``os.link`` mechanism).
    """

    normalized = normalize_json_value(value)
    require_finite_json_value(normalized)
    try:
        json.dumps(normalized, allow_nan=False)
    except ValueError as exc:
        raise QueueSnapshotError(
            "non_finite_float_in_evidence",
            "Evidence failed strict JSON (allow_nan=False) validation",
            details={"error": str(exc)},
        ) from exc
    write_json_no_overwrite(path, normalized)


# ---------------------------------------------------------------------------
# Render queue entry normalization.
# ---------------------------------------------------------------------------


def _job_id_key_status(entry: Mapping[str, Any]) -> tuple[str, str | None]:
    """Classify how a queue entry's job ID could be identified.

    Returns ``(status, job_id)`` where ``status`` is one of:

    * ``"identified"`` — every recognized alias key present with a usable
      value normalizes to the same single value (one alias, or several
      agreeing aliases).
    * ``"unidentified"`` — no known job-ID key was present with a usable
      value. This is an explicit, non-fatal classification: Resolve queue
      entry shape can legitimately vary and this probe does not assume a
      missing ID key is itself malformed.
    * ``"malformed"`` — a known job-ID key was present but mapped to a
      value that is not a bool/None-excluded str/int (e.g. a nested dict or
      list).
    * ``"conflicting"`` (Rev2, Finding 3) — two or more recognized alias
      keys were present with usable values that normalize to *different*
      values. Rev1 used Rev8's ``queue_job_id()``, which scans aliases in a
      fixed precedence order and silently returns the first match,
      discarding a conflicting lower-precedence alias's value without any
      indication a conflict existed. This probe now collects every
      recognized alias's normalized value and fails closed the moment more
      than one distinct value is present, rather than guessing which alias
      is authoritative.

    Both ``"malformed"`` and ``"conflicting"`` are fail-closed conditions:
    neither is ever persisted as a queue entry's status in a completed
    snapshot document — ``normalize_queue_entry`` raises before either can
    reach output.
    """

    malformed_keys: list[str] = []
    values_by_normalized: dict[str, list[str]] = {}
    for key in QUEUE_JOB_ID_KEYS:
        if key not in entry:
            continue
        value = entry[key]
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (str, int)):
            candidate = str(value).strip()
            if candidate:
                values_by_normalized.setdefault(candidate, []).append(key)
            continue
        malformed_keys.append(key)

    if malformed_keys:
        return "malformed", None
    if not values_by_normalized:
        return "unidentified", None
    if len(values_by_normalized) > 1:
        return "conflicting", None
    (job_id,) = values_by_normalized
    return "identified", job_id


def normalize_queue_entry(raw_item: Any, index: int) -> dict[str, Any]:
    """Deterministically normalize one ``GetRenderJobList()`` entry.

    Fails closed (raises ``QueueSnapshotError``) on a non-dict entry, a
    non-string key, a malformed job-ID key value, or conflicting job-ID
    aliases (Rev2, Finding 3). Never stringifies or ``repr()``'s an
    arbitrary bridge object: every preserved value passes through Rev8's
    ``normalize_json_value``, which itself fails closed on any value it
    cannot represent as safe JSON data.
    """

    if not isinstance(raw_item, dict):
        raise QueueSnapshotError(
            "queue_entry_malformed",
            "Render queue entry is not a mapping",
            details={"index": index, "value_type": type(raw_item).__name__},
        )
    for key in raw_item.keys():
        if not isinstance(key, str):
            raise QueueSnapshotError(
                "queue_entry_key_not_string",
                "Render queue entry contains a non-string key",
                details={"index": index, "key_type": type(key).__name__},
            )

    status, job_id = _job_id_key_status(raw_item)
    if status == "malformed":
        raise QueueSnapshotError(
            "queue_entry_job_id_malformed",
            "Render queue entry has a known job-ID key mapped to an unusable value type",
            details={"index": index},
        )
    if status == "conflicting":
        raise QueueSnapshotError(
            "queue_entry_job_id_conflicting",
            "Render queue entry has multiple recognized job-ID aliases with different values",
            details={"index": index},
        )

    try:
        fields = normalize_json_value(raw_item, _path=f"$.render_queue[{index}]")
    except UnsupportedEvidenceType as exc:
        raise QueueSnapshotError(
            "queue_entry_fields_unrepresentable",
            "Render queue entry contains a value that cannot be represented as safe JSON evidence",
            details={"index": index, "error": str(exc)},
        ) from exc

    return {
        "index": index,
        "job_id": job_id,
        "job_id_status": status,
        "fields": fields,
    }


def normalize_render_queue(raw_jobs: Any) -> tuple[list[dict[str, Any]], int]:
    """Normalize a full ``GetRenderJobList()`` return value.

    Fails closed on a malformed top-level type (anything but a list/tuple,
    or Resolve's documented falsy-empty-queue return) and on any duplicate
    ``"identified"`` job ID — a duplicate would make downstream acceptance
    comparison ambiguous by construction, so this probe never guesses which
    duplicate is authoritative.
    """

    raw_list = require_collection(raw_jobs, "render queue", false_means_empty=True)
    entries = [normalize_queue_entry(item, index) for index, item in enumerate(raw_list)]

    seen_ids: dict[str, int] = {}
    for entry in entries:
        job_id = entry["job_id"]
        if job_id is None:
            continue
        if job_id in seen_ids:
            raise QueueSnapshotError(
                "duplicate_render_queue_job_id",
                "Render queue contains more than one entry with the same job ID",
                details={
                    "job_id": job_id,
                    "first_index": seen_ids[job_id],
                    "duplicate_index": entry["index"],
                },
            )
        seen_ids[job_id] = entry["index"]

    return entries, len(entries)


# ---------------------------------------------------------------------------
# Live collection.
# ---------------------------------------------------------------------------


def _fetch_job_status(project: Any, job_id: str) -> str:
    """Fetch and strictly sanitize ``JobStatus`` for one identified queue entry.

    Called only for entries whose ``job_id_status`` is ``"identified"``
    (Rev4) — an unidentified entry has no job ID to query. Any anomaly here
    fails the *entire* snapshot collection closed rather than publishing a
    placeholder: a completed snapshot document's ``job_status`` is always
    either a trustworthy non-empty string (identified entries) or ``None``
    (unidentified entries), never an "unavailable"/"malformed" value a later
    comparison might be tempted to treat leniently. Mirrors the existing
    ``job_id``/``job_id_status`` fail-closed precedent exactly.

    Distinguishes, deliberately, three different anomaly shapes so a future
    reviewer can tell which one actually happened from the error code alone:
    Resolve reporting no status at all for a job this same snapshot just
    observed in the queue (``render_job_status_missing``) is a different,
    more surprising anomaly than a malformed response shape
    (``render_job_status_invalid``) or a present-but-unusable ``JobStatus``
    field (``render_job_status_field_missing`` /
    ``render_job_status_field_invalid``).
    """

    status = call_required(project, "GetRenderJobStatus", job_id)
    if status is None:
        raise QueueSnapshotError(
            "render_job_status_missing",
            "Resolve reported no status for a render queue job this snapshot just observed",
            details={"job_id": job_id},
        )
    if not isinstance(status, dict):
        raise QueueSnapshotError(
            "render_job_status_invalid",
            "Resolve GetRenderJobStatus did not return an object",
            details={"job_id": job_id, "value_type": type(status).__name__},
        )
    if "JobStatus" not in status:
        raise QueueSnapshotError(
            "render_job_status_field_missing",
            "Resolve GetRenderJobStatus response has no JobStatus field",
            details={"job_id": job_id},
        )
    raw_status = status["JobStatus"]
    if not isinstance(raw_status, str) or not raw_status.strip():
        raise QueueSnapshotError(
            "render_job_status_field_invalid",
            "Resolve GetRenderJobStatus JobStatus field is not a non-empty string",
            details={"job_id": job_id, "value_type": type(raw_status).__name__},
        )
    return raw_status


def _post_status_rebracket(
    resolve: Any, context: QueueSnapshotContext, stable_queue: list[dict[str, Any]]
) -> tuple[str, str, bool]:
    """Re-establish project identity, timeline identity, rendering-inactive,
    and render-queue stability strictly AFTER every ``GetRenderJobStatus()``
    call has already returned, and strictly BEFORE evidence is constructed
    or published (Rev5).

    This is the exact correction the independent Rev4 review required
    (``POST_STATUS_REBRACKET_REQUIRED``): Rev4's own "final" guard ran
    *before* the new status getters, not after, so nothing re-confirmed
    context, rendering, or queue stability across the status-fetch window.
    This function is that missing confirmation, not a cosmetic rename of
    the pre-status guard.

    Re-reads the render queue a third time (reusing the already-allowlisted
    ``GetRenderJobList``, not a new method) and requires it to normalize
    identically to ``stable_queue`` (the already drift-verified B queue the
    status getters were run against) — fails closed
    (``post_status_queue_drift``) on any difference, exactly mirroring the
    existing A==B drift-check discipline (Rev1) extended to cover this new
    window. Returns the freshly observed
    ``(project_name, timeline_name, rendering_in_progress)`` — the caller
    must use these, not any earlier guard's values, in the published
    snapshot.
    """

    project, project_name, timeline_name, rendering = _verify_context_and_rendering_inactive(
        resolve, context
    )

    raw_queue = call_required(project, "GetRenderJobList")
    entries, _count = normalize_render_queue(raw_queue)
    if entries != stable_queue:
        raise QueueSnapshotError(
            "post_status_queue_drift",
            "Render queue changed during the post-status rebracket window",
            details={"before_count": len(stable_queue), "after_count": len(entries)},
        )

    return project_name, timeline_name, rendering


def _current_identity(resolve: Any) -> tuple[Any, Any, str, str]:
    project_manager = call_required(resolve, "GetProjectManager")
    if not project_manager:
        raise QueueSnapshotError(
            "project_manager_missing", "Resolve returned no usable project manager"
        )
    project = call_required(project_manager, "GetCurrentProject")
    if not project:
        raise QueueSnapshotError("current_project_missing", "Resolve has no current project")
    project_name = require_nonempty_string(call_required(project, "GetName"), "project name")

    timeline = call_required(project, "GetCurrentTimeline")
    if not timeline:
        raise QueueSnapshotError("current_timeline_missing", "Resolve has no current timeline")
    timeline_name = require_nonempty_string(call_required(timeline, "GetName"), "timeline name")

    return project, timeline, project_name, timeline_name


def _verify_context_and_rendering_inactive(
    resolve: Any, context: QueueSnapshotContext
) -> tuple[Any, str, str, bool]:
    """Verify current project/timeline identity and rendering-inactive.

    Performs no queue read. Called three times per
    ``collect_render_queue_snapshot()`` invocation (Rev2, Finding 5): before
    the first queue read, before the second queue read, and once more,
    strictly after the second queue read returns, with no further queue
    read of its own. Returns the freshly observed
    ``(project, project_name, timeline_name, rendering_in_progress)`` so the
    caller can use the exact values from whichever call is authoritative for
    its purpose.
    """

    project, timeline, project_name, timeline_name = _current_identity(resolve)

    if project_name != context.expected_project:
        raise QueueSnapshotError(
            "project_identity_mismatch",
            "Current Resolve project does not match the expected project",
            details={"expected": context.expected_project, "actual": project_name},
        )
    if timeline_name != context.expected_timeline:
        raise QueueSnapshotError(
            "timeline_identity_mismatch",
            "Current Resolve timeline does not match the expected timeline",
            details={"expected": context.expected_timeline, "actual": timeline_name},
        )

    rendering = call_required(project, "IsRenderingInProgress")
    if not isinstance(rendering, bool):
        raise QueueSnapshotError(
            "invalid_rendering_state",
            "IsRenderingInProgress() did not return a boolean",
            details={"value_type": type(rendering).__name__},
        )
    if rendering is not False:
        raise QueueSnapshotError(
            "rendering_active",
            "Resolve reports rendering in progress; snapshot collection is prohibited",
        )

    return project, project_name, timeline_name, rendering


def _capture_guard(resolve: Any, context: QueueSnapshotContext) -> dict[str, Any]:
    """Verify context/rendering, then read the render queue once."""

    project, project_name, timeline_name, rendering = _verify_context_and_rendering_inactive(
        resolve, context
    )

    raw_queue = call_required(project, "GetRenderJobList")
    entries, count = normalize_render_queue(raw_queue)

    return {
        "project_name": project_name,
        "timeline_name": timeline_name,
        "rendering_in_progress": rendering,
        "render_queue_count": count,
        "render_queue": entries,
    }


def collect_render_queue_snapshot(resolve: Any, context: QueueSnapshotContext) -> dict[str, Any]:
    """Collect one fail-closed render queue snapshot from an injected Resolve handle.

    Does not import the Resolve module. Production use is not authorized by
    this construction mission; mocked unit tests inject fake handles to
    exercise this logic. A non-empty render queue is explicitly permitted —
    this is the property that distinguishes this probe from the Rev8
    collector.

    Live call sequence (Rev2 Finding 5's original bracket, plus the Rev5
    post-status rebracket that closes the Rev4 independent-review finding
    ``POST_STATUS_REBRACKET_REQUIRED``)::

        verify expected current project/timeline
        IsRenderingInProgress -> false
        GetRenderJobList -> A

        verify expected current project/timeline
        IsRenderingInProgress -> false
        GetRenderJobList -> B

        require normalized A == normalized B

        verify expected current project/timeline               [pre-status guard]
        IsRenderingInProgress -> false

        GetRenderJobStatus -> once per identified entry in B (Rev4)

        verify expected current project/timeline               [post-status guard, Rev5]
        IsRenderingInProgress -> false
        GetRenderJobList -> C
        require normalized C == normalized B

    The pre-status guard performs no queue read of its own; it exists only
    to confirm context/rendering immediately before the status getters run,
    using its project handle for those calls (unchanged from Rev4). The
    post-status guard (Rev5) is the one whose observed
    project/timeline/rendering values are published in the returned
    snapshot — Rev4's pre-status guard values are never used for
    publication, since they predate the status-fetch window and would
    misrepresent it as still current. The post-status guard's own fresh
    ``GetRenderJobList()`` read (C) must equal B exactly, proving the queue
    itself — not only context and rendering — stayed stable across the
    status-fetch window; see ``_post_status_rebracket()``.
    """

    if not context.expected_project.strip() or not context.expected_timeline.strip():
        raise QueueSnapshotError(
            "invalid_expected_context",
            "Expected project and timeline names must be non-empty strings",
        )

    # Project identity, timeline identity, and rendering-inactive are each
    # already enforced *inside* every _capture_guard() /
    # _verify_context_and_rendering_inactive() call against the fixed
    # expected context, so pre["project_name"] == post["project_name"] ==
    # context.expected_project (and likewise timeline_name/rendering)
    # always holds by construction once both calls succeed. The render
    # queue itself carries no such external expected value, so it is the
    # one field that can genuinely drift between the two reads; comparing
    # its normalized entries also transitively covers any count change.
    pre = _capture_guard(resolve, context)
    post = _capture_guard(resolve, context)
    if pre["render_queue"] != post["render_queue"]:
        raise QueueSnapshotError(
            "render_queue_drift",
            "Render queue contents changed during snapshot collection",
            details={
                "before_count": pre["render_queue_count"],
                "after_count": post["render_queue_count"],
            },
        )

    # Pre-status guard (Rev2 Finding 5's original "third guard", renamed
    # conceptually in Rev5): confirms context/rendering immediately before
    # the status getters run, and its project handle is what those calls
    # use. Rev5 no longer treats this guard's own observed values as
    # authoritative for publication -- see the post-status guard below.
    pre_status_project, _pre_status_project_name, _pre_status_timeline_name, _pre_status_rendering = (
        _verify_context_and_rendering_inactive(resolve, context)
    )

    # Rev4: fetch JobStatus for every identified entry, using the
    # pre-status guard's project handle, only after the pre/post drift
    # check has already proven the queue itself is stable. One
    # GetRenderJobStatus() call per identified entry; none for unidentified
    # entries (no job ID to query). Any anomaly raises and aborts the whole
    # snapshot -- see _fetch_job_status().
    published_queue = [
        {
            **entry,
            "job_status": (
                _fetch_job_status(pre_status_project, entry["job_id"])
                if entry["job_id_status"] == "identified"
                else None
            ),
        }
        for entry in post["render_queue"]
    ]

    # Post-status guard (Rev5): strictly after every GetRenderJobStatus()
    # call, strictly before evidence construction. Closes
    # POST_STATUS_REBRACKET_REQUIRED -- re-confirms context/rendering AND
    # re-reads the queue, requiring it to still equal B exactly. These are
    # the values actually published below; the pre-status guard's values
    # are discarded once the status getters have run, since they predate
    # a window real Resolve round-trips just occurred in.
    final_project_name, final_timeline_name, final_rendering = _post_status_rebracket(
        resolve, context, post["render_queue"]
    )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "mission": MISSION,
        "captured_at": utc_now(),
        "collector": {
            "name": COLLECTOR_NAME,
            "revision": EXECUTION_REVISION_ID,
        },
        "expected_context": {
            "project": context.expected_project,
            "timeline": context.expected_timeline,
        },
        "observed_context": {
            "project": final_project_name,
            "timeline": final_timeline_name,
        },
        "rendering_in_progress": final_rendering,
        "render_queue_count": post["render_queue_count"],
        "render_queue": published_queue,
        "snapshot_complete": True,
    }
    normalized = normalize_json_value(snapshot)
    require_finite_json_value(normalized)
    return normalized


# ---------------------------------------------------------------------------
# Offline acceptance comparison — never imports or contacts Resolve.
# ---------------------------------------------------------------------------

SUPPORTED_JOB_ID_STATUSES = frozenset({"identified", "unidentified"})
# "malformed" and "conflicting" are never persisted to a completed snapshot
# document — normalize_queue_entry() fails closed on those before an entry
# can ever reach output. A document claiming either status (or anything
# else) is therefore itself invalid evidence, not a third legitimate status
# this validator should tolerate.

# Rev3, Finding 2: the exact and complete top-level key set this collector
# ever produces -- no missing key, no extra key. Supersedes Rev2's
# `_REQUIRED_SNAPSHOT_SECTIONS`, which checked only a 6-key subset for
# presence and never checked for unexpected additional keys.
_REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "mission",
        "captured_at",
        "collector",
        "expected_context",
        "observed_context",
        "rendering_in_progress",
        "render_queue_count",
        "render_queue",
        "snapshot_complete",
    }
)
_REQUIRED_ENTRY_KEYS = frozenset({"index", "job_id", "job_id_status", "fields", "job_status"})
_REQUIRED_CONTEXT_KEYS = frozenset({"project", "timeline"})
_REQUIRED_COLLECTOR_KEYS = frozenset({"name", "revision"})

# Rev3, Finding 2: the exact shape utc_now() emits --
# YYYY-MM-DDTHH:MM:SS.ffffffZ (microsecond-resolution UTC, literal
# trailing "Z", never a numeric offset). A value that merely matches this
# shape but names an impossible calendar instant (e.g. month 13) is
# rejected separately, by attempting to actually parse it.
_CAPTURED_AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _validate_captured_at(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise QueueSnapshotError(
            "snapshot_captured_at_invalid",
            "Snapshot captured_at must be a non-empty string",
            details={"value_type": type(value).__name__},
        )
    if not _CAPTURED_AT_PATTERN.fullmatch(value):
        raise QueueSnapshotError(
            "snapshot_captured_at_malformed",
            "Snapshot captured_at does not match this collector's exact utc_now() shape "
            "(YYYY-MM-DDTHH:MM:SS.ffffffZ)",
        )
    try:
        dt.datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError as exc:
        raise QueueSnapshotError(
            "snapshot_captured_at_not_parseable",
            "Snapshot captured_at matches the expected shape but does not name a real "
            "calendar instant",
            details={"error": str(exc)},
        ) from exc


def validate_queue_snapshot_document(snapshot: Any) -> dict[str, Any]:
    """Fail closed unless ``snapshot`` is internally consistent, structurally
    valid, complete output this exact probe revision could have produced.

    Rev2, Finding 2 (top-level structure) and Rev3, Finding 2 (envelope
    exactness): this validator no longer merely trusts
    ``snapshot_complete: true`` and a shallow key-presence check (Rev1's
    behavior), and no longer tolerates unknown top-level keys or an
    unvalidated ``captured_at`` (Rev2's remaining gap). It independently
    checks: the document's top-level keys are *exactly* the ten keys this
    collector ever produces (Rev3); document identity (schema version,
    mission, collector name and an explicitly documented accepted-revision
    policy — see ``ACCEPTED_COLLECTOR_REVISIONS``); ``captured_at`` matches
    this collector's exact ``utc_now()`` shape and names a real calendar
    instant (Rev3); cross-field consistency between ``expected_context`` and
    ``observed_context`` (a legitimately collected snapshot always has the
    two equal, by construction of ``_verify_context_and_rendering_inactive``'s
    own identity checks — a document where they differ could not have been
    honestly collected by this probe); ``rendering_in_progress is False``
    exactly (not merely falsy); ``render_queue_count == len(render_queue)``;
    every queue entry's shape, positional index, status, job-ID
    validity/uniqueness; and (Rev3, Finding 1) that each entry's stored
    ``job_id``/``job_id_status`` agree exactly with the classification
    independently re-derived from that same entry's own preserved
    ``fields``, using the identical rules live collection uses. The
    complete document, not merely each entry's ``fields``, is required to
    be strict, finite-only JSON (Rev3).
    """

    if not isinstance(snapshot, dict):
        raise QueueSnapshotError("invalid_snapshot_document", "Snapshot must be a JSON object")

    # Rev3: the whole document must be strict, finite-only JSON -- not
    # merely each entry's `fields` sub-object (Rev2's narrower scope).
    # Safe to call before any shape validation below: this walker only
    # ever raises for a non-finite float wherever one appears, and passes
    # every other value through unchanged regardless of overall structure.
    require_finite_json_value(snapshot)

    if set(snapshot) != _REQUIRED_TOP_LEVEL_KEYS:
        raise QueueSnapshotError(
            "snapshot_top_level_keys_invalid",
            "Snapshot does not contain exactly the required top-level keys",
            details={
                "missing": sorted(_REQUIRED_TOP_LEVEL_KEYS - set(snapshot)),
                "unexpected": sorted(set(snapshot) - _REQUIRED_TOP_LEVEL_KEYS),
            },
        )

    if snapshot["schema_version"] != SCHEMA_VERSION:
        raise QueueSnapshotError(
            "snapshot_schema_mismatch",
            "Snapshot schema version does not match",
            details={"expected": SCHEMA_VERSION, "actual": snapshot["schema_version"]},
        )
    if snapshot["mission"] != MISSION:
        raise QueueSnapshotError(
            "snapshot_mission_mismatch",
            "Snapshot mission does not match",
            details={"expected": MISSION, "actual": snapshot["mission"]},
        )
    if snapshot["snapshot_complete"] is not True:
        raise QueueSnapshotError("incomplete_snapshot", "Snapshot is not marked complete")

    _validate_captured_at(snapshot["captured_at"])

    collector = snapshot["collector"]
    if not isinstance(collector, dict) or set(collector) != _REQUIRED_COLLECTOR_KEYS:
        raise QueueSnapshotError(
            "snapshot_collector_invalid",
            "Snapshot collector section must be an object with exactly name/revision",
        )
    if collector.get("name") != COLLECTOR_NAME:
        raise QueueSnapshotError(
            "snapshot_collector_name_mismatch",
            "Snapshot collector name does not match this probe",
            details={"expected": COLLECTOR_NAME, "actual": collector.get("name")},
        )
    if collector.get("revision") not in ACCEPTED_COLLECTOR_REVISIONS:
        raise QueueSnapshotError(
            "snapshot_collector_revision_not_accepted",
            "Snapshot collector revision is not in this probe's accepted-revision policy",
            details={
                "accepted": sorted(ACCEPTED_COLLECTOR_REVISIONS),
                "actual": collector.get("revision"),
            },
        )

    expected_context = snapshot["expected_context"]
    observed_context = snapshot["observed_context"]
    if not isinstance(expected_context, dict) or set(expected_context) != _REQUIRED_CONTEXT_KEYS:
        raise QueueSnapshotError(
            "snapshot_expected_context_invalid",
            "Snapshot expected_context must be an object with exactly project/timeline",
        )
    if not isinstance(observed_context, dict) or set(observed_context) != _REQUIRED_CONTEXT_KEYS:
        raise QueueSnapshotError(
            "snapshot_observed_context_invalid",
            "Snapshot observed_context must be an object with exactly project/timeline",
        )
    for label, ctx in (("expected_context", expected_context), ("observed_context", observed_context)):
        for field in ("project", "timeline"):
            value = ctx[field]
            if not isinstance(value, str) or not value.strip():
                raise QueueSnapshotError(
                    "snapshot_context_field_invalid",
                    f"Snapshot {label}.{field} must be a non-empty string",
                    details={"context": label, "field": field},
                )
    if observed_context["project"] != expected_context["project"]:
        raise QueueSnapshotError(
            "snapshot_observed_project_mismatch",
            "Snapshot observed_context.project does not equal expected_context.project",
            details={
                "expected": expected_context["project"],
                "observed": observed_context["project"],
            },
        )
    if observed_context["timeline"] != expected_context["timeline"]:
        raise QueueSnapshotError(
            "snapshot_observed_timeline_mismatch",
            "Snapshot observed_context.timeline does not equal expected_context.timeline",
            details={
                "expected": expected_context["timeline"],
                "observed": observed_context["timeline"],
            },
        )

    rendering = snapshot["rendering_in_progress"]
    if rendering is not False:
        raise QueueSnapshotError(
            "snapshot_rendering_not_false",
            "Snapshot rendering_in_progress must be exactly False",
            details={"value_type": type(rendering).__name__},
        )

    entries = snapshot["render_queue"]
    if not isinstance(entries, list):
        raise QueueSnapshotError(
            "snapshot_render_queue_not_a_list",
            "Snapshot render_queue must be a list",
            details={"value_type": type(entries).__name__},
        )

    render_queue_count = snapshot["render_queue_count"]
    if isinstance(render_queue_count, bool) or not isinstance(render_queue_count, int) or render_queue_count < 0:
        raise QueueSnapshotError(
            "snapshot_render_queue_count_invalid",
            "Snapshot render_queue_count must be a non-negative integer",
            details={"value_type": type(render_queue_count).__name__},
        )
    if render_queue_count != len(entries):
        raise QueueSnapshotError(
            "snapshot_render_queue_count_mismatch",
            "Snapshot render_queue_count does not equal the actual render_queue length",
            details={"declared": render_queue_count, "actual": len(entries)},
        )

    seen_identified_ids: dict[str, int] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_invalid",
                "Snapshot render_queue entry is not an object",
                details={"position": position},
            )
        if set(entry) != _REQUIRED_ENTRY_KEYS:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_shape_invalid",
                "Snapshot render_queue entry does not have exactly the required keys",
                details={"position": position},
            )

        entry_index = entry["index"]
        if isinstance(entry_index, bool) or not isinstance(entry_index, int) or entry_index < 0:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_index_invalid",
                "Snapshot render_queue entry index must be a non-negative integer",
                details={"position": position},
            )
        if entry_index != position:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_index_out_of_order",
                "Snapshot render_queue entry index does not match its queue position",
                details={"position": position, "declared_index": entry_index},
            )

        status = entry["job_id_status"]
        if status not in SUPPORTED_JOB_ID_STATUSES:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_status_invalid",
                "Snapshot render_queue entry job_id_status is not a supported status",
                details={"position": position, "status": status},
            )

        job_id = entry["job_id"]
        if status == "identified":
            if not isinstance(job_id, str) or not job_id.strip():
                raise QueueSnapshotError(
                    "snapshot_render_queue_entry_identified_job_id_invalid",
                    "Snapshot render_queue entry marked identified must have a non-empty string job_id",
                    details={"position": position},
                )
            if job_id in seen_identified_ids:
                raise QueueSnapshotError(
                    "snapshot_render_queue_duplicate_identified_job_id",
                    "Snapshot render_queue contains more than one identified entry with the same job ID",
                    details={
                        "job_id": job_id,
                        "first_index": seen_identified_ids[job_id],
                        "duplicate_index": entry_index,
                    },
                )
            seen_identified_ids[job_id] = entry_index
        else:
            if job_id is not None:
                raise QueueSnapshotError(
                    "snapshot_render_queue_entry_unidentified_job_id_invalid",
                    "Snapshot render_queue entry marked unidentified must have job_id null",
                    details={"position": position},
                )

        # Rev4: job_status mirrors job_id's own presence/null contract
        # exactly -- an identified entry's job_status must be a trustworthy
        # non-empty string (never null/malformed; _fetch_job_status() fails
        # the whole snapshot closed at collection time rather than letting
        # an unusable value reach a completed document), and an
        # unidentified entry's job_status must be null (no job ID exists to
        # have queried in the first place).
        job_status = entry["job_status"]
        if status == "identified":
            if not isinstance(job_status, str) or not job_status.strip():
                raise QueueSnapshotError(
                    "snapshot_render_queue_entry_job_status_invalid",
                    "Snapshot render_queue entry marked identified must have a non-empty string job_status",
                    details={"position": position},
                )
        else:
            if job_status is not None:
                raise QueueSnapshotError(
                    "snapshot_render_queue_entry_unidentified_job_status_invalid",
                    "Snapshot render_queue entry marked unidentified must have job_status null",
                    details={"position": position},
                )

        fields = entry["fields"]
        if not isinstance(fields, dict):
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_fields_invalid",
                "Snapshot render_queue entry fields must be an object",
                details={"position": position},
            )
        for key in fields:
            if not isinstance(key, str):
                raise QueueSnapshotError(
                    "snapshot_render_queue_entry_fields_key_not_string",
                    "Snapshot render_queue entry fields contains a non-string key",
                    details={"position": position},
                )
        try:
            normalize_json_value(fields)
        except UnsupportedEvidenceType as exc:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_fields_unrepresentable",
                "Snapshot render_queue entry fields cannot be represented as safe JSON evidence",
                details={"position": position, "error": str(exc)},
            ) from exc
        # Non-finite-float check for `fields` is no longer performed here
        # individually -- the whole-document require_finite_json_value(snapshot)
        # call at the top of this function already recurses into every
        # entry's fields, making a second, narrower walk redundant.

        # Rev3, Finding 1: re-derive the canonical job-ID classification
        # from this entry's own preserved `fields`, using the identical
        # rules live collection uses, and require it to agree exactly with
        # the entry's stored job_id/job_id_status. Without this, a forged
        # entry could claim any job_id_status/job_id while carrying
        # completely unrelated (or absent, or self-contradictory)
        # `fields` evidence -- no honest collection could ever produce
        # such a document, since normalize_queue_entry() derives job_id/
        # job_id_status FROM fields in the first place.
        derived_status, derived_job_id = _job_id_key_status(fields)
        if derived_status == "malformed":
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_fields_job_id_malformed",
                "Snapshot render_queue entry fields contain a recognized job-ID alias "
                "mapped to an unusable value type",
                details={"position": position},
            )
        if derived_status == "conflicting":
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_fields_job_id_conflicting",
                "Snapshot render_queue entry fields contain multiple recognized job-ID "
                "aliases with different values",
                details={"position": position},
            )
        if derived_status != status:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_job_id_status_disagrees_with_fields",
                "Snapshot render_queue entry job_id_status does not match the status "
                "derivable from its own preserved fields",
                details={"position": position, "stored_status": status, "derived_status": derived_status},
            )
        if status == "identified" and derived_job_id != job_id:
            raise QueueSnapshotError(
                "snapshot_render_queue_entry_job_id_disagrees_with_fields",
                "Snapshot render_queue entry job_id does not match the job ID derivable "
                "from its own preserved fields",
                details={"position": position, "stored_job_id": job_id, "derived_job_id": derived_job_id},
            )

    return snapshot


def _evaluate_job_status_check(
    validated: Mapping[str, Any],
    classification: str,
    matching_indexes: list[int],
    expected_job_status: str | None,
) -> dict[str, Any]:
    """Offline-only, zero-Resolve-contact evaluation of the Rev4 optional
    ``--expected-job-status`` assertion against an already-validated snapshot.

    ``"not_requested"``: no assertion was asked for -- Rev3's exact existing
    behavior is otherwise unaffected. ``"not_applicable"``: an assertion was
    requested but the target job identity itself is not unambiguously
    resolved (``classification != "exact_single_job_match"``) -- there is no
    single job to check a status against, so this deliberately does not fall
    back to inspecting an arbitrary entry. ``"status_match"`` /
    ``"status_mismatch"``: exact string comparison (case-sensitive, no
    normalization) between ``expected_job_status`` and the matched entry's
    captured ``job_status`` -- by the time ``classification ==
    "exact_single_job_match"`` holds, ``validate_queue_snapshot_document()``
    has already guaranteed that entry's ``job_status`` is a trustworthy
    non-empty string, so no further sanitization is needed here.
    """

    if expected_job_status is None:
        return {"requested": None, "observed": None, "classification": "not_requested"}
    if classification != "exact_single_job_match":
        return {"requested": expected_job_status, "observed": None, "classification": "not_applicable"}
    (index,) = matching_indexes
    observed = validated["render_queue"][index]["job_status"]
    if observed == expected_job_status:
        return {"requested": expected_job_status, "observed": observed, "classification": "status_match"}
    return {"requested": expected_job_status, "observed": observed, "classification": "status_mismatch"}


def compare_expected_job_id(
    snapshot: Mapping[str, Any],
    expected_job_id: str | None,
    expected_job_status: str | None = None,
) -> dict[str, Any]:
    """Offline-only acceptance comparison against one previously collected,
    fully validated snapshot.

    Makes zero Resolve contact — Rev4's optional status assertion does not
    change this: it only inspects a value ``snapshot`` already captured, it
    never calls ``GetRenderJobStatus`` or any other Resolve method itself.
    Rev2, Finding 1: every outcome is one explicit, mutually exclusive
    classification — a caller never has to infer success by combining
    multiple loosely related fields the way Rev1's
    ``has_unexpected_additional_jobs``/``exactly_one_matching_job`` pair
    required. Exactly one classification, ``"exact_single_job_match"``,
    means formal single-job closure: ``render_queue_count == 1 and
    identified_job_id_count == 1 and matching_job_count == 1`` (which
    together already imply zero unidentified entries and zero other
    identified jobs, since the queue has exactly one entry total). Every
    other classification is deliberately not a success.

    Rev3 hardening (not itself one of the two Rev2->Rev3 findings): a
    non-``None`` ``expected_job_id`` must be a non-empty string. A
    whitespace-only or non-string value fails closed
    (``expected_job_id_invalid``) rather than being silently treated as an
    ordinary query that simply never matches.

    Rev4: ``expected_job_status``, if supplied, must likewise be a non-empty
    string (``expected_job_status_invalid``) and may only be supplied
    together with a real ``expected_job_id``
    (``expected_job_status_requires_expected_job_id`` — a status assertion
    with no target job identity to check it against is not a meaningful
    query). The returned dict always carries a ``job_status_check`` key —
    see ``_evaluate_job_status_check()`` — so the output shape is uniform
    regardless of whether the assertion was requested. Omitting
    ``expected_job_status`` (the default) leaves every existing field and
    every existing classification exactly as Rev3 produced them.
    """

    if expected_job_id is not None and (
        not isinstance(expected_job_id, str) or not expected_job_id.strip()
    ):
        raise QueueSnapshotError(
            "expected_job_id_invalid",
            "expected_job_id must be None or a non-empty string",
            details={"value_type": type(expected_job_id).__name__},
        )
    if expected_job_status is not None and (
        not isinstance(expected_job_status, str) or not expected_job_status.strip()
    ):
        raise QueueSnapshotError(
            "expected_job_status_invalid",
            "expected_job_status must be None or a non-empty string",
            details={"value_type": type(expected_job_status).__name__},
        )
    if expected_job_status is not None and expected_job_id is None:
        raise QueueSnapshotError(
            "expected_job_status_requires_expected_job_id",
            "expected_job_status may only be supplied together with expected_job_id",
        )

    validated = validate_queue_snapshot_document(snapshot)
    entries = validated["render_queue"]
    identified = [entry for entry in entries if entry["job_id_status"] == "identified"]
    unidentified = [entry for entry in entries if entry["job_id_status"] == "unidentified"]
    identified_ids = [entry["job_id"] for entry in identified]

    render_queue_count = len(entries)
    identified_job_id_count = len(identified_ids)
    unidentified_entry_count = len(unidentified)

    if expected_job_id is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "mission": MISSION,
            "compared_at": utc_now(),
            "comparison_complete": True,
            "expected_job_id": None,
            "render_queue_count": render_queue_count,
            "identified_job_id_count": identified_job_id_count,
            "unidentified_entry_count": unidentified_entry_count,
            "matching_job_count": None,
            "matching_indexes": [],
            "classification": "no_expected_job_id_supplied",
            "job_status_check": _evaluate_job_status_check(validated, "no_expected_job_id_supplied", [], expected_job_status),
        }

    matching_indexes = [entry["index"] for entry in identified if entry["job_id"] == expected_job_id]
    matching_count = len(matching_indexes)

    if matching_count > 1:
        # validate_queue_snapshot_document() above requires identified job
        # IDs to be unique (Finding 2); reaching more than one match here
        # would mean that invariant was violated despite passing
        # validation, which should be impossible for any snapshot this
        # function actually accepted. Fail closed rather than silently
        # picking one match.
        raise QueueSnapshotError(
            "duplicate_identified_job_id_in_validated_snapshot",
            "More than one identified queue entry matched the expected job ID in an "
            "already-validated snapshot; this should be impossible",
            details={"expected_job_id": expected_job_id, "matching_indexes": matching_indexes},
        )

    if matching_count == 1 and render_queue_count == 1 and identified_job_id_count == 1:
        classification = "exact_single_job_match"
    elif matching_count == 0:
        classification = "zero_matching_jobs"
    elif unidentified_entry_count > 0:
        classification = "ambiguous_due_to_unidentified_entries"
    else:
        classification = "expected_job_present_with_additional_jobs"

    return {
        "schema_version": SCHEMA_VERSION,
        "mission": MISSION,
        "compared_at": utc_now(),
        "comparison_complete": True,
        "expected_job_id": expected_job_id,
        "render_queue_count": render_queue_count,
        "identified_job_id_count": identified_job_id_count,
        "unidentified_entry_count": unidentified_entry_count,
        "matching_job_count": matching_count,
        "matching_indexes": matching_indexes,
        "classification": classification,
        "job_status_check": _evaluate_job_status_check(validated, classification, matching_indexes, expected_job_status),
    }


# ---------------------------------------------------------------------------
# Execution interlock — self-contained; see module docstring for why this is
# not imported from Rev8. Unchanged in behavior from Rev1; bound to Rev2's
# own EXECUTION_REVISION_ID.
# ---------------------------------------------------------------------------


def enforce_execution_interlock(supplied: str | None) -> None:
    """Deliberate execution interlock for live Resolve contact.

    Not authentication and not a secret. Must be called, and must pass,
    before output-path validation, before ``DaVinciResolveScript`` import,
    before Resolve connection, and before any snapshot collection. The
    supplied value is never included in a raised error's message or
    details.
    """

    if supplied is None or supplied == "":
        raise QueueSnapshotError(
            "live_execution_authorization_missing",
            "Live execution requires --execution-authorization naming this exact source revision",
        )
    if not EXECUTION_REVISION_ID_PATTERN.fullmatch(supplied):
        raise QueueSnapshotError(
            "live_execution_authorization_invalid",
            "Execution authorization value is not a well-formed revision identifier",
        )
    if supplied != EXECUTION_REVISION_ID:
        raise QueueSnapshotError(
            "live_execution_revision_mismatch",
            "Execution authorization does not match this source revision's identifier",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_snapshot_command(args: argparse.Namespace) -> int:
    # These two checks must remain, in this order, before any Resolve
    # contact.
    enforce_execution_interlock(args.execution_authorization)
    validate_output_path(args.output)
    resolve = connect_resolve_read_only()
    snapshot = collect_render_queue_snapshot(
        resolve,
        QueueSnapshotContext(
            expected_project=args.expected_project,
            expected_timeline=args.expected_timeline,
        ),
    )
    write_strict_json_no_overwrite(args.output, snapshot)
    return 0


def run_compare_command(args: argparse.Namespace) -> int:
    snapshot = load_json(args.snapshot)
    expected_job_status = getattr(args, "expected_job_status", None)
    comparison = compare_expected_job_id(snapshot, args.expected_job_id, expected_job_status)
    write_strict_json_no_overwrite(args.output, comparison)
    if args.expected_job_id is None:
        return 0
    if comparison["classification"] != "exact_single_job_match":
        return 3
    # Rev4: only reached once job-ID identity is already unambiguous.
    # Omitting --expected-job-status leaves this exit code exactly as Rev3
    # produced it (job_status_check.classification is "not_requested",
    # which is not "status_mismatch"/"not_applicable", so this branch is a
    # no-op for every pre-Rev4 caller).
    if expected_job_status is not None and comparison["job_status_check"]["classification"] != "status_match":
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=MISSION)
    parser.add_argument(
        "--print-sha256",
        action="store_true",
        help="Print the source SHA-256 and exit without Resolve contact.",
    )
    subparsers = parser.add_subparsers(dest="command")

    snapshot = subparsers.add_parser(
        "snapshot",
        help=(
            "Fail-closed by default. Requires --execution-authorization naming "
            "the exact source revision identifier to reach Resolve."
        ),
    )
    snapshot.add_argument("--expected-project", required=True)
    snapshot.add_argument("--expected-timeline", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument(
        "--execution-authorization",
        required=False,
        default=None,
        help=(
            "Deliberate execution interlock, not a credential: must exactly equal "
            "this source revision's EXECUTION_REVISION_ID. Missing, malformed, or "
            "mismatched values stop before any Resolve import or connection."
        ),
    )

    compare = subparsers.add_parser(
        "compare",
        help="Offline acceptance comparison against one completed snapshot JSON file. Never contacts Resolve.",
    )
    compare.add_argument("--snapshot", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument(
        "--expected-job-id",
        required=False,
        default=None,
        help="If supplied, classify how the render queue relates to this exact job ID.",
    )
    compare.add_argument(
        "--expected-job-status",
        required=False,
        default=None,
        help=(
            "Rev4, optional and additive. Requires --expected-job-id. Exact "
            "(case-sensitive) match against the captured JobStatus of "
            "whichever entry --expected-job-id resolves to, only when that "
            "resolves unambiguously to exact_single_job_match; fails closed "
            "(nonzero exit) on a missing, ambiguous, or mismatched status. "
            "Never contacts Resolve -- inspects only what --snapshot already "
            "captured."
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.print_sha256:
        print(script_sha256(Path(__file__)))
        return 0
    if args.command is None:
        parser.error("a command is required unless --print-sha256 is used")
    try:
        if args.command == "snapshot":
            return run_snapshot_command(args)
        if args.command == "compare":
            return run_compare_command(args)
        raise QueueSnapshotError("unsupported_command", f"Unsupported command: {args.command}")
    except SnapshotError as exc:
        # Catches both this module's QueueSnapshotError and the base
        # SnapshotError Rev8's imported validate_output_path/load_json/
        # write_json_no_overwrite helpers raise directly.
        print(json.dumps({"result": "stopped", "error": exc.to_dict()}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
