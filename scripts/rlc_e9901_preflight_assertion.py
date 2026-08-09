"""RLC-E9901 Broadcast Master read-only preflight — offline assertion layer.

Construction status
--------------------
Construction and static-review artifact only. This module never imports
`DaVinciResolveScript`, never calls `scriptapp`, and never contacts
DaVinci Resolve in any way -- it consumes only a previously completed
snapshot JSON document (produced by the unmodified rev8 collector at
`scripts/phase14_resolve_context_snapshot.py`, via the execution layer in
`scripts/rlc_e9901_snapshot_preflight_contract.py`) and reasons about it
entirely offline. It does not import that collector or any other
`scripts.*` module -- see `check_snapshot_capture_complete()` below.

Rev5 correction (independent review, Finding 1)
--------------------------------------------------
Rev4 validated that `GetVersion()`'s trailing `suffix` field was
string-typed, but then dropped its value entirely when building the
normalized comparison string -- so `[21, 0, 3, 7, "beta"]` (or any other
non-empty suffix) normalized identically to `[21, 0, 3, 7, ""]` and
silently passed against `version_string == "21.0.3.7"`, even though the
repository's reviewed evidence establishes only the exact empty-suffix
value pair. `_normalized_version_list()` now requires the suffix to be
exactly the empty string `""`, not merely string-typed -- see its own
docstring for the full rationale, including why no generalized non-empty
suffix interpretation is invented.

Rev4 correction (independent review, Finding 1)
--------------------------------------------------
Rev3's `_normalized_version_list()` required every element of
`session.version`'s observed value to be a non-boolean integer, which
rejected `GetVersion()`'s own documented trailing string `suffix`
field -- including the exact, already-reviewed evidence shape
`[21, 0, 3, 7, ""]` the collector's own Phase 14 test double returns (see
`tests/unit/test_phase14_resolve_context_snapshot.py`). An otherwise-valid
snapshot carrying that exact, correct value was misclassified as
malformed and failed the whole preflight. `_normalized_version_list()`
now validates the documented five-field `[major, minor, patch, build,
suffix]` shape directly (see its own docstring for the exact rule) rather
than requiring a uniform-integer list. This does not weaken the Finding-2D
contradictory-accessor protection: two observed accessors that normalize
to different version strings still fail closed exactly as before, and a
malformed suffix, wrong field count, or boolean numeric component are
still treated as "observed but malformed" -- a hard failure, not a silent
pass.

Rev3 correction (independent review, Finding 2)
--------------------------------------------------
Independent review reproduced five concrete false-pass cases against the
exact Rev2 source, all corrected here:

**A. Boolean queue counts.** `pre_guard.queue_count = False` /
`post_guard.queue_count = False` passed rev2's `pre_count == 0` check,
because Python's `bool` is an `int` subclass and `False == 0` is `True`.
`check_queue_empty()` now requires each guard's `queue_count` to be a
non-boolean `int` equal to `0`, checked with an explicit `isinstance`
guard before the equality comparison (the same pattern already used for
`item_count` in `check_video_item_count_positive()`).

**B. Contradictory project-level queue evidence.** Rev2 never inspected
`project.render_queue` at all -- a snapshot could report empty guards
while `project.render_queue.count == 1` and `project.render_queue.items`
held an actual job, and still pass. New `check_render_queue_consistency()`
requires `project.render_queue.count` to be a non-boolean, non-negative
integer equal to `0`, `project.render_queue.items` to be an empty list,
and both guards' `queue_count` to equal that same project-level count --
so guard-level and project-level queue evidence can no longer silently
disagree.

**C. Unobserved product identity.** `session.product_name.status =
unavailable` passed as long as the version check passed. New
`check_resolve_product_identity_observed()` requires `status == "observed"`
and a non-empty string value. Per the independent review's own guidance,
this does NOT pin an exact expected product-name string: the repository's
existing reviewed record (Mission 39E, `docs/ROADMAP.md`) establishes the
exact Resolve *version* used for every live Phase 14 verification
(`21.0.3.7`, already bound as `EXPECTED_RESOLVE_VERSION`), but does not
establish a canonical exact `GetProductName()` string anywhere reviewed --
inventing one here would be exactly the "weaker representation" the
independent review guidance warned against fabricating in the other
direction. The check therefore requires only that a genuine, non-empty
product identity was observed, and the offline result records the exact
observed value as evidence rather than silently discarding it.

**D. Contradictory version accessors.** `session.version_string =
"21.0.3.7"` while `session.version = [99, 99, 99, 99]` passed, because
rev2's `_resolve_version_identity()` preferred `version_string` and never
looked at `version` once `version_string` was usable.
`check_resolve_version_matches_expected()` is rewritten: every accessor
whose `status == "observed"` is independently normalized and validated:
if more than one is observed and they normalize to different version
strings, the check fails closed regardless of whether one of them happens
to match `EXPECTED_RESOLVE_VERSION` -- a contradiction between two
observed accessors is itself disqualifying, not merely "prefer one over
the other."

**E. Optional video track-count observation.** Rev2 only cross-checked
`tracks.video.count` *if* its status happened to be `"observed"`; an
`"unavailable"` count status skipped the cross-check entirely and let the
raw `tracks[]` list alone decide the result.
`check_video_item_count_positive()` now REQUIRES the count observation
itself to be `status == "observed"` with a valid non-negative,
non-boolean integer equal to `len(tracks)` -- an unavailable or malformed
count observation is now itself disqualifying. Each track's `item_count`
is validated the same way, and where a track entry additionally carries
an `items` list, its length must equal `item_count`.

None of this expands into unrelated snapshot validation: every new or
strengthened check maps directly to one of the eight properties the
combined execution-layer contract claims to prove (target project
identity, target/current timeline identity, rendering inactive, render
queue empty, Resolve product/version, Broadcast Master preset observed,
positive video payload, pre/post guard equality) -- see
`scripts/rlc_e9901_snapshot_preflight_contract.py`'s own "overall PASS"
list for the authoritative statement of scope.

Purpose
-------
A completed rev8 snapshot document already proves, live and fail-closed,
that at the moment of capture: the exact expected project and timeline
were current, no other timeline ambiguously matched, rendering was not in
progress, the render queue was empty, and none of those facts drifted
between the pre- and post-capture guard reads. A completed snapshot is
therefore already meaningful evidence -- but it is NOT, by itself, a
passing RLC-E9901 render preflight: it does not by itself prove the
*actual* captured identities were correct (as opposed to merely
self-consistent), that every redundant piece of evidence for a claimed
property actually agrees, that the Resolve version matches what this
review was conducted against, or that `Redline Broadcast Master`/a
positive video item count were actually observed. This module adds
exactly those assertions, offline, against the already-captured JSON.

Snapshot-capture success vs. overall render-preflight success
-----------------------------------------------------------------
These are two different, explicitly distinguished outcomes:

* `snapshot_capture_status` -- was the JSON document itself a complete,
  well-formed rev8 snapshot (required root fields present,
  `snapshot_complete is True`)? This says nothing about renderability.
* `render_preflight_status` -- only evaluated when `snapshot_capture_status
  == "complete"`. Requires every one of the thirteen render-specific
  checks below. A capture failure short-circuits this to
  `"not_evaluated"` -- a broken or incomplete snapshot can never be
  silently treated as a passing preflight.

Interpretation limit (carried on every result, not just documented here)
--------------------------------------------------------------------------
`Redline Broadcast Master` appearing in the preset-name inventory proves
only that Resolve currently lists a preset by that exact name for the
current project. It does NOT prove that a future `LoadRenderPreset()` call
will accept it, that a future `AddRenderJob()` call will succeed, or that
any other render-queue precondition holds. This module never overstates
its own result past that boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MISSION = "RLC-E9901 Broadcast Master Read-Only Preflight — Offline Assertion Layer"

EXPECTED_PROJECT_NAME = "RLC-E9901_MASTER"
EXPECTED_TIMELINE_NAME = "RLC-E9901_TIMELINE"
REQUIRED_PRESET_NAME = "Redline Broadcast Master"

# Bound to the exact DaVinci Resolve Studio version used for every live
# Phase 14 verification recorded in the repository to date (Mission 39E's
# workstation-configuration verification; the 2026-07-29 live queue
# verification in docs/ARCHITECTURE.md §3.5). This is the strongest
# canonical representation the repository's existing reviewed record
# provides -- not a newly invented value. A future Resolve upgrade
# requires this constant to be revisited under its own review, not loosened
# silently.
EXPECTED_RESOLVE_VERSION = "21.0.3.7"

_REQUIRED_SCHEMA_VERSION = "1.0"
_REQUIRED_SNAPSHOT_FIELDS = frozenset(
    {
        "expected_context",
        "session",
        "project_manager",
        "project",
        "target_timeline",
        "media_pool",
        "pre_guard",
        "post_guard",
    }
)

INTERPRETATION_LIMITS: tuple[str, ...] = (
    "Preset-name visibility does not prove LoadRenderPreset() will accept the preset.",
    "Preset-name visibility does not prove a future AddRenderJob() call will succeed.",
    "A positive video item count does not by itself prove Resolve will accept a queue "
    "request; it rules out only the specific zero-video-payload precondition failure "
    "identified by Phase 14 Test D.",
    "A matching Resolve product/version identity does not prove render-queue behavior "
    "is identical to prior verification -- it only rules out evaluating evidence "
    "captured against a different, unreviewed Resolve version or product.",
    "This assertion layer reasons only about the exact snapshot JSON it was given; it "
    "cannot detect state that changed in Resolve after the snapshot was captured.",
)


class OfflinePreflightError(RuntimeError):
    """Fail-closed offline-assertion error with a machine-readable classification."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    observed: Any = None

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail, "observed": self.observed}


@dataclass(frozen=True)
class OfflinePreflightResult:
    snapshot_capture_status: str  # "complete" | "incomplete"
    render_preflight_status: str  # "passed" | "failed" | "not_evaluated"
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)
    interpretation_limits: tuple[str, ...] = INTERPRETATION_LIMITS

    def to_dict(self) -> dict:
        return {
            "mission": MISSION,
            "snapshot_capture_status": self.snapshot_capture_status,
            "render_preflight_status": self.render_preflight_status,
            "checks": [check.to_dict() for check in self.checks],
            "interpretation_limits": list(self.interpretation_limits),
        }


def load_snapshot(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfflinePreflightError(
            "snapshot_load_failed", f"could not load snapshot JSON: {path}",
            details={"error_type": type(exc).__name__},
        ) from exc


def _is_nonbool_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_snapshot_capture_complete(snapshot: Any) -> CheckResult:
    """Local reimplementation of the collector's own validate_snapshot_document() rule.

    Not imported -- this module never imports the collector or any other
    `scripts.*` module, so it carries no import-ordering obligation at all.
    """

    if not isinstance(snapshot, dict):
        return CheckResult("snapshot_capture_complete", False, "snapshot document is not a JSON object", observed=type(snapshot).__name__)
    if snapshot.get("schema_version") != _REQUIRED_SCHEMA_VERSION:
        return CheckResult(
            "snapshot_capture_complete", False,
            "snapshot schema_version does not match the expected value",
            observed=snapshot.get("schema_version"),
        )
    if snapshot.get("snapshot_complete") is not True:
        return CheckResult(
            "snapshot_capture_complete", False,
            "snapshot_complete is not True", observed=snapshot.get("snapshot_complete"),
        )
    missing = sorted(_REQUIRED_SNAPSHOT_FIELDS - set(snapshot))
    if missing:
        return CheckResult(
            "snapshot_capture_complete", False,
            "snapshot is missing required sections", observed=missing,
        )
    return CheckResult("snapshot_capture_complete", True, "snapshot document is complete and well-formed")


def check_expected_context(snapshot: dict) -> CheckResult:
    expected = {"project": EXPECTED_PROJECT_NAME, "timeline": EXPECTED_TIMELINE_NAME}
    actual = snapshot.get("expected_context")
    if actual == expected:
        return CheckResult("expected_context", True, "snapshot declared the exact expected RLC-E9901 context", observed=actual)
    return CheckResult(
        "expected_context", False,
        "snapshot's expected_context does not match RLC-E9901_MASTER/RLC-E9901_TIMELINE",
        observed=actual,
    )


def check_actual_project_identity(snapshot: dict) -> CheckResult:
    project = snapshot.get("project")
    actual = project.get("name") if isinstance(project, dict) else None
    if actual == EXPECTED_PROJECT_NAME:
        return CheckResult("actual_project_identity", True, "project.name matches the expected RLC-E9901 project", observed=actual)
    return CheckResult(
        "actual_project_identity", False,
        "project.name does not match the expected RLC-E9901 project", observed=actual,
    )


def check_actual_timeline_identity(snapshot: dict) -> CheckResult:
    target_timeline = snapshot.get("target_timeline")
    actual = target_timeline.get("name") if isinstance(target_timeline, dict) else None
    if actual == EXPECTED_TIMELINE_NAME:
        return CheckResult("actual_timeline_identity", True, "target_timeline.name matches the expected RLC-E9901 timeline", observed=actual)
    return CheckResult(
        "actual_timeline_identity", False,
        "target_timeline.name does not match the expected RLC-E9901 timeline", observed=actual,
    )


def _guard_identity_observed(guard: dict) -> dict:
    return {key: guard.get(key) for key in ("project_name", "current_timeline_name", "target_timeline_name")}


def _guard_identity_ok(guard: dict) -> bool:
    return (
        guard.get("project_name") == EXPECTED_PROJECT_NAME
        and guard.get("current_timeline_name") == EXPECTED_TIMELINE_NAME
        and guard.get("target_timeline_name") == EXPECTED_TIMELINE_NAME
    )


def check_pre_guard_identity(snapshot: dict) -> CheckResult:
    guard = _guard(snapshot, "pre_guard")
    observed = _guard_identity_observed(guard)
    if _guard_identity_ok(guard):
        return CheckResult("pre_guard_identity", True, "pre_guard project/timeline identities match the expected RLC-E9901 values", observed=observed)
    return CheckResult(
        "pre_guard_identity", False,
        "pre_guard project/timeline identities do not match the expected RLC-E9901 values", observed=observed,
    )


def check_post_guard_identity(snapshot: dict) -> CheckResult:
    guard = _guard(snapshot, "post_guard")
    observed = _guard_identity_observed(guard)
    if _guard_identity_ok(guard):
        return CheckResult("post_guard_identity", True, "post_guard project/timeline identities match the expected RLC-E9901 values", observed=observed)
    return CheckResult(
        "post_guard_identity", False,
        "post_guard project/timeline identities do not match the expected RLC-E9901 values", observed=observed,
    )


def check_rendering_inactive(snapshot: dict) -> CheckResult:
    pre = _guard(snapshot, "pre_guard")
    post = _guard(snapshot, "post_guard")
    pre_value = pre.get("rendering_in_progress")
    post_value = post.get("rendering_in_progress")
    # `is False` (identity), not `== False`/`== 0` -- already immune to the
    # bool/int confusion the queue-count checks below must guard against
    # explicitly, since only the literal singleton `False` satisfies `is False`.
    if pre_value is False and post_value is False:
        return CheckResult("rendering_inactive", True, "rendering was not in progress before or after capture")
    return CheckResult(
        "rendering_inactive", False, "rendering was reported active (or non-boolean) at some point during capture",
        observed={"pre_guard": pre_value, "post_guard": post_value},
    )


def check_queue_empty(snapshot: dict) -> CheckResult:
    """Rev3 (Finding 2A): requires non-boolean integer zero, not merely `== 0`
    (which `False` would also satisfy)."""

    pre = _guard(snapshot, "pre_guard")
    post = _guard(snapshot, "post_guard")
    pre_count = pre.get("queue_count")
    post_count = post.get("queue_count")
    pre_ok = _is_nonbool_int(pre_count) and pre_count == 0
    post_ok = _is_nonbool_int(post_count) and post_count == 0
    if pre_ok and post_ok:
        return CheckResult("queue_empty", True, "Resolve render queue was empty (integer zero) before and after capture")
    return CheckResult(
        "queue_empty", False,
        "Resolve render queue was not a valid non-boolean zero at some point during capture",
        observed={"pre_guard": pre_count, "post_guard": post_count},
    )


def check_render_queue_consistency(snapshot: dict) -> CheckResult:
    """Rev3 (Finding 2B): the project-level captured queue inventory must be
    valid, empty, and consistent with both guards -- not merely the guards'
    own queue_count field in isolation."""

    pre = _guard(snapshot, "pre_guard")
    post = _guard(snapshot, "post_guard")
    project_queue = _project_field(snapshot, "render_queue")

    if not isinstance(project_queue, dict):
        return CheckResult(
            "render_queue_consistency", False,
            "project.render_queue is missing or malformed", observed=project_queue,
        )

    project_count = project_queue.get("count")
    project_items = project_queue.get("items")
    pre_count = pre.get("queue_count")
    post_count = post.get("queue_count")
    pre_fingerprint = pre.get("queue_fingerprint")
    post_fingerprint = post.get("queue_fingerprint")

    observed = {
        "project_count": project_count,
        "project_items": project_items,
        "pre_guard_queue_count": pre_count,
        "post_guard_queue_count": post_count,
        "pre_guard_queue_fingerprint": pre_fingerprint,
        "post_guard_queue_fingerprint": post_fingerprint,
    }

    if not (_is_nonbool_int(project_count) and project_count == 0):
        return CheckResult("render_queue_consistency", False, "project.render_queue.count is not a valid non-boolean zero", observed=observed)
    if not (isinstance(project_items, list) and len(project_items) == 0):
        return CheckResult("render_queue_consistency", False, "project.render_queue.items is not an empty list", observed=observed)
    if not (_is_nonbool_int(pre_count) and pre_count == project_count):
        return CheckResult("render_queue_consistency", False, "pre_guard.queue_count does not match project.render_queue.count", observed=observed)
    if not (_is_nonbool_int(post_count) and post_count == project_count):
        return CheckResult("render_queue_consistency", False, "post_guard.queue_count does not match project.render_queue.count", observed=observed)
    if not (isinstance(pre_fingerprint, list) and len(pre_fingerprint) == 0):
        return CheckResult("render_queue_consistency", False, "pre_guard.queue_fingerprint is not a valid empty list", observed=observed)
    if not (isinstance(post_fingerprint, list) and len(post_fingerprint) == 0):
        return CheckResult("render_queue_consistency", False, "post_guard.queue_fingerprint is not a valid empty list", observed=observed)

    return CheckResult("render_queue_consistency", True, "render queue observations are valid, empty, and mutually consistent", observed=observed)


def check_no_guard_drift(snapshot: dict) -> CheckResult:
    pre = _guard(snapshot, "pre_guard")
    post = _guard(snapshot, "post_guard")
    if pre == post:
        return CheckResult("no_guard_drift", True, "pre- and post-capture guard state are identical")
    return CheckResult(
        "no_guard_drift", False, "pre- and post-capture guard state differ",
        observed={"pre_guard": pre, "post_guard": post},
    )


def check_resolve_product_identity_observed(snapshot: dict) -> CheckResult:
    """Rev3 (Finding 2C): requires a genuinely observed, non-empty product
    identity. Deliberately does NOT pin an exact expected product-name
    string -- the repository's reviewed record establishes the exact
    Resolve *version* used for prior live verification, but no exact
    `GetProductName()` string; inventing one would fabricate evidence in
    the opposite direction from the false-pass this corrects. The observed
    value is still recorded as evidence."""

    session = snapshot.get("session")
    product = session.get("product_name") if isinstance(session, dict) else None
    if not isinstance(product, dict) or product.get("status") != "observed":
        return CheckResult("resolve_product_identity_observed", False, "Resolve product identity was not observed", observed=product)
    value = product.get("value")
    if not isinstance(value, str) or not value.strip():
        return CheckResult("resolve_product_identity_observed", False, "Resolve product identity observed value is not a non-empty string", observed=value)
    return CheckResult("resolve_product_identity_observed", True, "Resolve product identity was observed", observed=value)


def _normalized_version_string(observation: Any) -> tuple[bool, str | None]:
    """Returns (was_observed_and_well_formed, normalized_value_or_None)."""
    if not isinstance(observation, dict) or observation.get("status") != "observed":
        return False, None
    value = observation.get("value")
    if isinstance(value, str) and value.strip():
        return True, value.strip()
    return True, None  # observed but malformed -- caller must treat as a failure, not "unobserved"


def _normalized_version_list(observation: Any) -> tuple[bool, str | None]:
    """Normalizes GetVersion()'s documented `[major, minor, patch, build, suffix]`
    representation to a comparable "major.minor.patch.build" string.

    Rev4 correction (independent review, Finding 1): rev3 required every
    element of the list to be a non-boolean integer, which rejected
    GetVersion()'s own documented trailing string `suffix` field --
    including the exact, already-reviewed evidence shape
    `[21, 0, 3, 7, ""]` returned by the collector's own Phase 14 test
    double (`FakeResolve.GetVersion()` in
    `tests/unit/test_phase14_resolve_context_snapshot.py`). That is the
    authoritative schema used here; no alternative representation is
    invented.

    Rev5 correction (independent review, Finding 1): Rev4 validated the
    suffix field's *type* (must be a string) but then dropped its *value*
    entirely when building the normalized comparison string -- so any
    non-empty suffix (`"beta"`, `"Studio"`, anything) silently normalized
    identically to an empty one, and a snapshot carrying, say,
    `[21, 0, 3, 7, "beta"]` alongside `version_string == "21.0.3.7"` passed
    as if the two accessors agreed, when they do not represent a reviewed,
    verified build. The repository's reviewed evidence establishes only
    one exact value pair: `GetVersion() == [21, 0, 3, 7, ""]` alongside
    `GetVersionString() == "21.0.3.7"` -- an EMPTY suffix. No repository
    evidence establishes what a non-empty suffix would mean or how it
    should be reconciled with `GetVersionString()`'s plain-dotted form, so
    none is invented: the suffix must now be exactly the empty string
    `""`, not merely string-typed. A future Resolve build that legitimately
    carries a non-empty suffix (a beta, an RC, a Studio-tier marker, or
    anything else) must fail closed here and require its own renewed
    review and constant update, not a silent pass under the current
    binding.

    Exactly five elements are required: four non-boolean, non-negative
    integer fields (major, minor, patch, build) followed by a suffix field
    that must be the literal empty string. Any other field count, a
    non-string or non-empty suffix, a boolean, or a negative numeric field
    is treated as malformed (fails closed), not silently coerced.
    """

    if not isinstance(observation, dict) or observation.get("status") != "observed":
        return False, None
    value = observation.get("value")
    if not isinstance(value, list) or len(value) != 5:
        return True, None
    major, minor, patch, build, suffix = value
    numeric_fields = (major, minor, patch, build)
    if not all(_is_nonbool_int(part) and part >= 0 for part in numeric_fields):
        return True, None
    if not isinstance(suffix, str) or suffix != "":
        return True, None
    return True, ".".join(str(part) for part in numeric_fields)


def check_resolve_version_matches_expected(snapshot: dict) -> CheckResult:
    """Rev3 (Finding 2D): every accessor with status == "observed" is
    independently validated; if more than one is observed, they must
    normalize to the SAME version string, or the check fails closed even
    if one of them happens to match EXPECTED_RESOLVE_VERSION."""

    session = snapshot.get("session")
    if not isinstance(session, dict):
        return CheckResult("resolve_version_matches_expected", False, "session is missing or malformed", observed=session)

    was_observed_str, normalized_str = _normalized_version_string(session.get("version_string"))
    was_observed_list, normalized_list = _normalized_version_list(session.get("version"))

    if was_observed_str and normalized_str is None:
        return CheckResult("resolve_version_matches_expected", False, "session.version_string is observed but malformed", observed=session.get("version_string"))
    if was_observed_list and normalized_list is None:
        return CheckResult("resolve_version_matches_expected", False, "session.version is observed but malformed", observed=session.get("version"))

    observed_values: dict[str, str] = {}
    if was_observed_str:
        observed_values["version_string"] = normalized_str  # type: ignore[assignment]
    if was_observed_list:
        observed_values["version"] = normalized_list  # type: ignore[assignment]

    if not observed_values:
        return CheckResult("resolve_version_matches_expected", False, "no Resolve version accessor was observed", observed=None)

    distinct = set(observed_values.values())
    if len(distinct) > 1:
        return CheckResult(
            "resolve_version_matches_expected", False,
            "observed Resolve version accessors disagree with each other", observed=observed_values,
        )

    (observed_version,) = distinct
    if observed_version != EXPECTED_RESOLVE_VERSION:
        return CheckResult(
            "resolve_version_matches_expected", False,
            f"observed Resolve version does not match the authorization-bound version "
            f"{EXPECTED_RESOLVE_VERSION!r}; a version mismatch requires renewed review, not a silent pass",
            observed=observed_values,
        )
    return CheckResult(
        "resolve_version_matches_expected", True,
        f"observed Resolve version {observed_version!r} matches the authorization-bound version",
        observed=observed_values,
    )


def check_broadcast_master_preset_observed(snapshot: dict) -> CheckResult:
    observation = _project_field(snapshot, "render_presets")
    if not isinstance(observation, dict) or observation.get("status") != "observed":
        return CheckResult(
            "broadcast_master_preset_observed", False,
            "render-preset inventory was not observed (unavailable or errored)",
            observed=observation,
        )

    value = observation.get("value")
    names = _extract_preset_names(value)
    if names is None:
        return CheckResult(
            "broadcast_master_preset_observed", False,
            "render-preset inventory has an unrecognized shape; cannot confirm preset presence",
            observed=value,
        )
    if REQUIRED_PRESET_NAME in names:
        return CheckResult(
            "broadcast_master_preset_observed", True,
            f"{REQUIRED_PRESET_NAME!r} is present in the observed render-preset inventory",
            observed=names,
        )
    return CheckResult(
        "broadcast_master_preset_observed", False,
        f"{REQUIRED_PRESET_NAME!r} was not found in the observed render-preset inventory",
        observed=names,
    )


def check_video_item_count_positive(snapshot: dict) -> CheckResult:
    """Rev3 (Finding 2E): the required video track group's own `count`
    observation must itself be status == "observed" with a valid
    non-negative, non-boolean integer equal to len(tracks) -- an
    unavailable count observation is now itself disqualifying, not merely
    skipped. Each track's item_count is validated the same way, and where
    a track additionally carries an `items` list, its length must equal
    item_count."""

    tracks_group = _timeline_field(snapshot, ["tracks", "video"])
    if not isinstance(tracks_group, dict) or tracks_group.get("status") != "observed":
        return CheckResult(
            "video_item_count_positive", False,
            "target timeline's video track group was not observed (unavailable or errored)",
            observed=tracks_group,
        )

    track_list = tracks_group.get("tracks")
    if not isinstance(track_list, list):
        return CheckResult(
            "video_item_count_positive", False,
            "target timeline's video track list has an unrecognized shape",
            observed=track_list,
        )

    count_observation = tracks_group.get("count")
    if not isinstance(count_observation, dict) or count_observation.get("status") != "observed":
        return CheckResult(
            "video_item_count_positive", False,
            "required video track count observation was not made (status must be observed)",
            observed=count_observation,
        )
    declared = count_observation.get("value")
    if not _is_nonbool_int(declared) or declared < 0:
        return CheckResult(
            "video_item_count_positive", False,
            "declared video track count is malformed (must be a non-negative, non-boolean integer)",
            observed=declared,
        )
    if declared != len(track_list):
        return CheckResult(
            "video_item_count_positive", False,
            "declared video track count does not match the observed track list length",
            observed={"declared_count": declared, "track_list_length": len(track_list)},
        )

    total = 0
    for track in track_list:
        if not isinstance(track, dict):
            return CheckResult(
                "video_item_count_positive", False,
                "a video track entry is not an object", observed=track_list,
            )
        item_count = track.get("item_count")
        if not _is_nonbool_int(item_count) or item_count < 0:
            return CheckResult(
                "video_item_count_positive", False,
                "a video track entry has a malformed item_count (must be a non-negative, non-boolean integer)",
                observed=track_list,
            )
        items_list = track.get("items")
        if items_list is not None:
            if not isinstance(items_list, list):
                return CheckResult(
                    "video_item_count_positive", False,
                    "a video track entry's items field is present but is not a list",
                    observed=track_list,
                )
            if len(items_list) != item_count:
                return CheckResult(
                    "video_item_count_positive", False,
                    "a video track entry's item_count does not match its items list length",
                    observed=track_list,
                )
        total += item_count

    if total > 0:
        return CheckResult(
            "video_item_count_positive", True,
            f"total video TimelineItem count is {total}", observed=total,
        )
    return CheckResult(
        "video_item_count_positive", False,
        "total video TimelineItem count is zero", observed=total,
    )


_RENDER_PREFLIGHT_CHECKS = (
    check_expected_context,
    check_actual_project_identity,
    check_actual_timeline_identity,
    check_pre_guard_identity,
    check_post_guard_identity,
    check_rendering_inactive,
    check_queue_empty,
    check_render_queue_consistency,
    check_no_guard_drift,
    check_resolve_product_identity_observed,
    check_resolve_version_matches_expected,
    check_broadcast_master_preset_observed,
    check_video_item_count_positive,
)


def evaluate_offline_preflight(snapshot: Any) -> OfflinePreflightResult:
    """Evaluate a completed rev8 snapshot document against the RLC-E9901 render preflight.

    A snapshot-capture failure short-circuits with
    `render_preflight_status == "not_evaluated"` -- the render-specific
    checks are never run against an incomplete/malformed document. A
    passing `render_preflight_status` independently requires every one of
    the thirteen render-specific checks -- including the actual (not
    merely declared) project/timeline identity, guard-identity, render-
    queue cross-consistency, and Resolve product/version checks -- per the
    Rev2/Rev3 corrections above.
    """

    capture_check = check_snapshot_capture_complete(snapshot)
    if not capture_check.passed:
        return OfflinePreflightResult(
            snapshot_capture_status="incomplete",
            render_preflight_status="not_evaluated",
            checks=(capture_check,),
        )

    checks = [capture_check] + [check_fn(snapshot) for check_fn in _RENDER_PREFLIGHT_CHECKS]
    overall_passed = all(check.passed for check in checks)
    return OfflinePreflightResult(
        snapshot_capture_status="complete",
        render_preflight_status="passed" if overall_passed else "failed",
        checks=tuple(checks),
    )


def _guard(snapshot: dict, key: str) -> dict:
    value = snapshot.get(key)
    return value if isinstance(value, dict) else {}


def _project_field(snapshot: dict, key: str) -> Any:
    project = snapshot.get("project")
    if not isinstance(project, dict):
        return None
    return project.get(key)


def _timeline_field(snapshot: dict, path: list[str]) -> Any:
    node: Any = snapshot.get("target_timeline")
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _extract_preset_names(value: Any) -> list[str] | None:
    """Normalize GetRenderPresetList()/GetRenderPresetNames() observed values to a name list.

    The reviewed Resolve scripting API returns a flat list of preset name
    strings for both accessors (confirmed for GetRenderPresetList() by the
    Mission 39C live finding recorded in docs/ROADMAP.md: "GetRenderPresetList()
    found 'Redline Broadcast Master'"). A defensive fallback also accepts a
    list of dicts exposing a 'PresetName' or 'Name' string field. Any other
    shape returns None (fail closed -- the caller must not assume presence).
    """

    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return value
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("PresetName") or item.get("Name")
                if isinstance(name, str):
                    names.append(name)
                    continue
            return None
        return names
    return None


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=MISSION)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        snapshot = load_snapshot(args.snapshot)
    except OfflinePreflightError as exc:
        _print_json({"result": "stopped", "error": exc.to_dict()})
        return 2

    result = evaluate_offline_preflight(snapshot)
    _print_json(result.to_dict())

    if result.snapshot_capture_status != "complete":
        return 2
    return 0 if result.render_preflight_status == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
