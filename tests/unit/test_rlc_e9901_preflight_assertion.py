from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REVIEW_ROOT = Path(__file__).resolve().parents[2]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts import rlc_e9901_preflight_assertion as checker


def _guard(*, project_name="RLC-E9901_MASTER", timeline_name="RLC-E9901_TIMELINE",
           rendering_in_progress=False, queue_count=0):
    return {
        "project_name": project_name,
        "timeline_count": 1,
        "current_timeline_name": timeline_name,
        "target_timeline_name": timeline_name,
        "rendering_in_progress": rendering_in_progress,
        "queue_count": queue_count,
        "queue_fingerprint": [],
    }


def _valid_snapshot(
    *,
    project_name="RLC-E9901_MASTER",
    timeline_name="RLC-E9901_TIMELINE",
    actual_project_name=None,
    actual_timeline_name=None,
    pre_guard_overrides=None,
    post_guard_overrides=None,
    rendering_in_progress=False,
    queue_count=0,
    project_render_queue_override=None,
    preset_names=("Redline Broadcast Master", "YouTube - 720p"),
    video_item_counts=(1,),
    video_track_count_override=None,
    video_count_status="observed",
    video_track_items_override=None,  # list parallel to video_item_counts, each entry a list or None
    drift=False,
    preset_status="observed",
    video_status="observed",
    product_status="observed",
    product_value="DaVinci Resolve",
    version_string="21.0.3.7",
    version_string_status="observed",
    version_list=None,
    version_list_status="observed",
):
    """Flexible fixture builder. Every *_override/status/value parameter lets
    a test reproduce one exact independent-review false-pass shape without
    otherwise disturbing an already-correct baseline snapshot."""

    actual_project_name = project_name if actual_project_name is None else actual_project_name
    actual_timeline_name = timeline_name if actual_timeline_name is None else actual_timeline_name

    pre_guard = _guard(
        project_name=project_name, timeline_name=timeline_name,
        rendering_in_progress=rendering_in_progress, queue_count=queue_count,
    )
    if pre_guard_overrides:
        pre_guard.update(pre_guard_overrides)

    post_guard = dict(pre_guard)
    if drift:
        post_guard = dict(post_guard, queue_count=post_guard["queue_count"] + 1)
    if post_guard_overrides:
        post_guard.update(post_guard_overrides)

    render_presets_value = list(preset_names) if preset_names is not None else None

    resolved_version_list = version_list if version_list is not None else [21, 0, 3, 7, ""]
    session = {
        "product_name": {"source_method": "GetProductName", "status": product_status, "value": product_value, "value_type": "str", "error": None},
        "version_string": {"source_method": "GetVersionString", "status": version_string_status, "value": version_string, "value_type": "str", "error": None},
        "version": {"source_method": "GetVersion", "status": version_list_status, "value": resolved_version_list, "value_type": "list", "error": None},
    }

    project_render_queue = {"count": queue_count, "items": []}
    if project_render_queue_override is not None:
        project_render_queue = project_render_queue_override

    track_count_value = len(video_item_counts) if video_track_count_override is None else video_track_count_override
    tracks = []
    for index, count in enumerate(video_item_counts):
        entry = {"track_index": index + 1, "item_count": count}
        if video_track_items_override is not None and index < len(video_track_items_override) and video_track_items_override[index] is not None:
            entry["items"] = video_track_items_override[index]
        tracks.append(entry)

    video_tracks = {
        "status": video_status,
        "track_type": "video",
        "count": {"source_method": "GetTrackCount", "status": video_count_status, "value": track_count_value},
        "tracks": tracks,
    }

    return {
        "schema_version": "1.0",
        "mission": "test",
        "captured_at": "2026-08-09T00:00:00Z",
        "snapshot_complete": True,
        "expected_context": {"project": project_name, "timeline": timeline_name},
        "session": session,
        "project_manager": {},
        "project": {
            "name": actual_project_name,
            "settings": {"source_method": "GetSetting", "status": "unavailable", "value": None, "value_type": None, "error": None},
            "timeline_count": 1,
            "timeline_inventory": [{"index": 1, "name": actual_timeline_name, "unique_id": {}}],
            "render_presets": {
                "source_method": "GetRenderPresetList",
                "status": preset_status,
                "value_type": "list",
                "value": render_presets_value,
                "error": None,
            },
            "render_queue": project_render_queue,
            "current_render_context": {},
        },
        "target_timeline": {
            "name": actual_timeline_name,
            "tracks": {"video": video_tracks, "audio": {"status": "observed", "tracks": []}, "subtitle": {"status": "unavailable", "tracks": []}},
        },
        "media_pool": {},
        "pre_guard": pre_guard,
        "post_guard": post_guard,
        "ambiguity_policy": {},
    }


# --- load_snapshot ---------------------------------------------------------

def test_load_snapshot_reads_valid_json(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert checker.load_snapshot(path) == {"a": 1}


def test_load_snapshot_missing_file_fails_closed(tmp_path):
    with pytest.raises(checker.OfflinePreflightError) as excinfo:
        checker.load_snapshot(tmp_path / "does-not-exist.json")
    assert excinfo.value.code == "snapshot_load_failed"


def test_load_snapshot_malformed_json_fails_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(checker.OfflinePreflightError) as excinfo:
        checker.load_snapshot(path)
    assert excinfo.value.code == "snapshot_load_failed"


# --- check_snapshot_capture_complete -----------------------------------------

def test_check_snapshot_capture_complete_passes_for_valid_document():
    assert checker.check_snapshot_capture_complete(_valid_snapshot()).passed is True


def test_check_snapshot_capture_complete_fails_when_field_missing():
    snapshot = _valid_snapshot()
    del snapshot["media_pool"]
    assert checker.check_snapshot_capture_complete(snapshot).passed is False


def test_check_snapshot_capture_complete_fails_when_not_snapshot_complete():
    snapshot = _valid_snapshot()
    snapshot["snapshot_complete"] = False
    assert checker.check_snapshot_capture_complete(snapshot).passed is False


def test_check_snapshot_capture_complete_fails_on_wrong_schema_version():
    snapshot = _valid_snapshot()
    snapshot["schema_version"] = "2.0"
    assert checker.check_snapshot_capture_complete(snapshot).passed is False


def test_check_snapshot_capture_complete_fails_on_non_dict():
    assert checker.check_snapshot_capture_complete(["not", "a", "dict"]).passed is False


# --- declared vs actual identity --------------------------------------------

def test_check_expected_context_pass():
    assert checker.check_expected_context(_valid_snapshot()).passed is True


def test_check_actual_project_identity_fails_on_wrong_actual_name():
    snapshot = _valid_snapshot(actual_project_name="RLC-E9001_MASTER")
    assert checker.check_actual_project_identity(snapshot).passed is False


def test_check_actual_timeline_identity_fails_on_wrong_actual_name():
    snapshot = _valid_snapshot(actual_timeline_name="RLC-E9001_TIMELINE")
    assert checker.check_actual_timeline_identity(snapshot).passed is False


def test_check_pre_guard_identity_fails_on_wrong_project_name():
    snapshot = _valid_snapshot(pre_guard_overrides={"project_name": "RLC-E9001_MASTER"})
    assert checker.check_pre_guard_identity(snapshot).passed is False


def test_reproduces_independent_review_false_pass_wrong_actual_identities_now_fails():
    snapshot = _valid_snapshot(
        actual_project_name="RLC-E9001_MASTER",
        actual_timeline_name="RLC-E9001_TIMELINE",
        pre_guard_overrides={"project_name": "RLC-E9001_MASTER", "current_timeline_name": "RLC-E9001_TIMELINE", "target_timeline_name": "RLC-E9001_TIMELINE"},
        post_guard_overrides={"project_name": "RLC-E9001_MASTER", "current_timeline_name": "RLC-E9001_TIMELINE", "target_timeline_name": "RLC-E9001_TIMELINE"},
    )
    result = checker.evaluate_offline_preflight(snapshot)
    assert result.render_preflight_status != "passed"


# --- rendering ---------------------------------------------------------------

def test_check_rendering_inactive_pass():
    assert checker.check_rendering_inactive(_valid_snapshot()).passed is True


def test_check_rendering_inactive_fail():
    snapshot = _valid_snapshot(pre_guard_overrides={"rendering_in_progress": True})
    assert checker.check_rendering_inactive(snapshot).passed is False


# --- Finding 2A: boolean queue counts ----------------------------------------

def test_check_queue_empty_pass_integer_zero():
    assert checker.check_queue_empty(_valid_snapshot(queue_count=0)).passed is True


def test_check_queue_empty_fail_nonzero_integer():
    assert checker.check_queue_empty(_valid_snapshot(queue_count=1)).passed is False


def test_reproduces_independent_review_false_pass_boolean_queue_count_now_fails():
    """Finding 2A exact reproduction: pre_guard.queue_count = False,
    post_guard.queue_count = False. False == 0 in Python; must fail closed."""
    snapshot = _valid_snapshot(
        pre_guard_overrides={"queue_count": False},
        post_guard_overrides={"queue_count": False},
        project_render_queue_override={"count": False, "items": []},
    )
    result = checker.check_queue_empty(snapshot)
    assert result.passed is False

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status != "passed"
    failing = {c.name for c in full.checks if not c.passed}
    assert "queue_empty" in failing


# --- Finding 2B: contradictory project-level queue evidence -----------------

def test_check_render_queue_consistency_pass():
    result = checker.check_render_queue_consistency(_valid_snapshot())
    assert result.passed is True


def test_reproduces_independent_review_false_pass_contradictory_project_queue_now_fails():
    """Finding 2B exact reproduction: guards report zero jobs, while
    project.render_queue.count == 1 and items contains a job."""
    snapshot = _valid_snapshot(
        queue_count=0,
        project_render_queue_override={"count": 1, "items": [{"JobId": "some-job"}]},
    )
    result = checker.check_render_queue_consistency(snapshot)
    assert result.passed is False

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status != "passed"
    failing = {c.name for c in full.checks if not c.passed}
    assert "render_queue_consistency" in failing


def test_check_render_queue_consistency_fails_on_nonempty_items():
    snapshot = _valid_snapshot(project_render_queue_override={"count": 0, "items": [{"JobId": "x"}]})
    assert checker.check_render_queue_consistency(snapshot).passed is False


def test_check_render_queue_consistency_fails_on_mismatched_pre_guard_count():
    snapshot = _valid_snapshot(pre_guard_overrides={"queue_count": 2})
    assert checker.check_render_queue_consistency(snapshot).passed is False


def test_check_render_queue_consistency_fails_on_missing_project_render_queue():
    snapshot = _valid_snapshot()
    del snapshot["project"]["render_queue"]
    assert checker.check_render_queue_consistency(snapshot).passed is False


def test_check_render_queue_consistency_fails_on_nonempty_guard_fingerprint():
    snapshot = _valid_snapshot(pre_guard_overrides={"queue_fingerprint": [{"JobId": "x"}]})
    assert checker.check_render_queue_consistency(snapshot).passed is False


# --- no guard drift ------------------------------------------------------------

def test_check_no_guard_drift_pass():
    assert checker.check_no_guard_drift(_valid_snapshot(drift=False)).passed is True


def test_check_no_guard_drift_fail():
    assert checker.check_no_guard_drift(_valid_snapshot(drift=True)).passed is False


# --- Finding 2C: unobserved product identity ---------------------------------

def test_check_resolve_product_identity_observed_pass():
    result = checker.check_resolve_product_identity_observed(_valid_snapshot())
    assert result.passed is True
    assert result.observed == "DaVinci Resolve"


def test_reproduces_independent_review_false_pass_unobserved_product_identity_now_fails():
    """Finding 2C exact reproduction: session.product_name.status =
    unavailable, value = null; version otherwise correct. Must fail closed
    even though the version check alone would pass."""
    snapshot = _valid_snapshot(product_status="unavailable", product_value=None)
    result = checker.check_resolve_product_identity_observed(snapshot)
    assert result.passed is False

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status != "passed"
    failing = {c.name for c in full.checks if not c.passed}
    assert "resolve_product_identity_observed" in failing
    # the version check itself would have passed in isolation, confirming
    # this specific check -- not a knock-on version failure -- is what fails:
    version_check = next(c for c in full.checks if c.name == "resolve_version_matches_expected")
    assert version_check.passed is True


def test_check_resolve_product_identity_observed_fails_on_empty_string():
    snapshot = _valid_snapshot(product_status="observed", product_value="")
    assert checker.check_resolve_product_identity_observed(snapshot).passed is False


def test_check_resolve_product_identity_observed_does_not_pin_an_exact_string():
    """Per independent review's own guidance: no exact product-name string
    is invented. Any non-empty observed string is accepted."""
    snapshot = _valid_snapshot(product_status="observed", product_value="DaVinci Resolve Studio")
    assert checker.check_resolve_product_identity_observed(snapshot).passed is True


# --- Finding 2D: contradictory version accessors -----------------------------

def test_check_resolve_version_matches_expected_pass_single_accessor():
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list_status="unavailable")
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is True


def test_check_resolve_version_matches_expected_pass_both_accessors_agree():
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, ""])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is True


def test_reproduces_independent_review_false_pass_contradictory_version_accessors_now_fails():
    """Finding 2D exact reproduction: version_string = "21.0.3.7" (matches)
    while numeric version = [99, 99, 99, 99, ""] (does not). Rev2 preferred
    version_string and never looked at version once it was usable -- must
    now fail closed on the contradiction itself."""
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[99, 99, 99, 99, ""])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is False
    assert result.observed == {"version_string": "21.0.3.7", "version": "99.99.99.99"}

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status != "passed"
    failing = {c.name for c in full.checks if not c.passed}
    assert "resolve_version_matches_expected" in failing


def test_check_resolve_version_matches_expected_fails_when_both_unobserved():
    snapshot = _valid_snapshot(version_string_status="unavailable", version_list_status="unavailable")
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is False
    assert result.observed is None


def test_check_resolve_version_matches_expected_fails_on_wrong_single_value():
    snapshot = _valid_snapshot(version_string="99.99.99", version_list_status="unavailable")
    assert checker.check_resolve_version_matches_expected(snapshot).passed is False


def test_expected_resolve_version_is_bound_to_the_reviewed_live_verification_value():
    assert checker.EXPECTED_RESOLVE_VERSION == "21.0.3.7"


# --- Rev4 Finding 1: GetVersion() five-field [major, minor, patch, build, suffix] normalization ---
#
# Authority: scripts/phase14_resolve_context_snapshot.py's own reviewed
# read-only allowlist includes GetVersion(), and its companion Phase 14
# test double (tests/unit/test_phase14_resolve_context_snapshot.py,
# FakeResolve.GetVersion()) returns exactly [21, 0, 3, 7, ""] -- the
# authoritative, already-preserved schema. No alternative schema is
# invented here.

def test_reproduces_independent_review_false_pass_five_field_version_now_passes():
    """Rev4 Finding 1 exact reproduction: session.version.value =
    [21, 0, 3, 7, ""] (the documented/preserved five-field GetVersion()
    shape) was misclassified as malformed by Rev3 and failed the whole
    preflight. It must now pass, consistently with GetVersionString() ==
    "21.0.3.7"."""
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, ""])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is True
    assert result.observed == {"version_string": "21.0.3.7", "version": "21.0.3.7"}

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status == "passed"


def test_five_field_version_mismatching_expected_fails():
    snapshot = _valid_snapshot(version_string="99.99.99.99", version_string_status="observed", version_list=[99, 99, 99, 99, ""])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is False


def test_five_field_version_malformed_suffix_fails():
    """Suffix must be a string per the documented GetVersion() field type;
    a non-string suffix (e.g. an int, or None) is malformed, not coerced."""
    for malformed_suffix in (5, None, [], {}):
        snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, malformed_suffix])
        result = checker.check_resolve_version_matches_expected(snapshot)
        assert result.passed is False, f"suffix={malformed_suffix!r} must fail closed"


def test_five_field_version_boolean_numeric_component_fails():
    for index in range(4):  # major, minor, patch, build each individually
        version_list = [21, 0, 3, 7, ""]
        version_list[index] = True
        snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=version_list)
        result = checker.check_resolve_version_matches_expected(snapshot)
        assert result.passed is False, f"boolean at index {index} must fail closed"


def test_five_field_version_wrong_field_count_fails():
    for wrong_length_list in ([21, 0, 3, 7], [21, 0, 3, 7, "", "extra"], [21, 0, 3], []):
        snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=wrong_length_list)
        result = checker.check_resolve_version_matches_expected(snapshot)
        assert result.passed is False, f"field count {len(wrong_length_list)} must fail closed"


def test_five_field_version_does_not_weaken_contradictory_accessor_protection():
    """Both accessors observed, both individually well-formed, but they
    disagree -- must still fail closed exactly as Finding 2D established,
    even though both are now valid five-field-aware normalizations."""
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 8, ""])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is False
    assert result.observed == {"version_string": "21.0.3.7", "version": "21.0.3.8"}


# --- Rev5 Finding 1: non-empty GetVersion() suffix must not be silently discarded ---

def test_reproduces_independent_review_false_pass_nonempty_suffix_beta_now_fails():
    """Rev5 Finding 1 exact reproduction: session.version.value =
    [21, 0, 3, 7, "beta"] alongside version_string == "21.0.3.7" was
    misclassified as PASSED by Rev4, because Rev4 validated only the
    suffix's type (str) and then dropped its value when normalizing. The
    repository's reviewed evidence establishes only the exact empty-suffix
    pairing; a non-empty suffix must fail closed and require renewed
    review, not silently pass."""
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, "beta"])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is False

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status != "passed"
    failing = {c.name for c in full.checks if not c.passed}
    assert "resolve_version_matches_expected" in failing


def test_five_field_version_nonempty_suffix_studio_fails():
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, "Studio"])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is False


def test_five_field_version_arbitrary_nonempty_suffix_values_cannot_pass():
    for suffix in ("beta", "Studio", "b3", "rc1", "-", " ", "0", "21.0.3.7", "\x00"):
        snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, suffix])
        result = checker.check_resolve_version_matches_expected(snapshot)
        assert result.passed is False, f"suffix={suffix!r} must fail closed, not silently pass"


def test_five_field_version_exact_empty_suffix_still_passes():
    """Regression pin: the fix for Finding 1 must not turn the one reviewed,
    evidenced value pair into a false negative."""
    snapshot = _valid_snapshot(version_string="21.0.3.7", version_list=[21, 0, 3, 7, ""])
    result = checker.check_resolve_version_matches_expected(snapshot)
    assert result.passed is True


# --- preset presence -----------------------------------------------------------

def test_check_broadcast_master_preset_observed_fail_absent():
    snapshot = _valid_snapshot(preset_names=("YouTube - 720p",))
    assert checker.check_broadcast_master_preset_observed(snapshot).passed is False


def test_check_broadcast_master_preset_observed_pass_dict_list_fallback():
    snapshot = _valid_snapshot(preset_names=None)
    snapshot["project"]["render_presets"]["value"] = [{"PresetName": "Redline Broadcast Master"}]
    assert checker.check_broadcast_master_preset_observed(snapshot).passed is True


# --- Finding 2E: video track-count observation must itself be observed ------

def test_check_video_item_count_positive_pass():
    assert checker.check_video_item_count_positive(_valid_snapshot(video_item_counts=(1,))).passed is True


def test_check_video_item_count_positive_fail_zero():
    assert checker.check_video_item_count_positive(_valid_snapshot(video_item_counts=(0,))).passed is False


def test_reproduces_independent_review_false_pass_unobserved_video_count_now_fails():
    """Finding 2E exact reproduction: tracks[] has a positive entry, but the
    track group's own count observation is unavailable/null. Rev2 skipped
    the cross-check entirely when count.status wasn't observed and let the
    raw tracks[] decide alone."""
    snapshot = _valid_snapshot(video_item_counts=(1,), video_count_status="unavailable", video_track_count_override=None)
    result = checker.check_video_item_count_positive(snapshot)
    assert result.passed is False

    full = checker.evaluate_offline_preflight(snapshot)
    assert full.render_preflight_status != "passed"
    failing = {c.name for c in full.checks if not c.passed}
    assert "video_item_count_positive" in failing


def test_check_video_item_count_positive_rejects_boolean_declared_count():
    snapshot = _valid_snapshot(video_item_counts=(1,), video_track_count_override=True)
    assert checker.check_video_item_count_positive(snapshot).passed is False


def test_check_video_item_count_positive_rejects_boolean_item_count():
    snapshot = _valid_snapshot(video_item_counts=(1,))
    snapshot["target_timeline"]["tracks"]["video"]["tracks"][0]["item_count"] = True
    assert checker.check_video_item_count_positive(snapshot).passed is False


def test_check_video_item_count_positive_rejects_negative_count():
    snapshot = _valid_snapshot(video_item_counts=(1,))
    snapshot["target_timeline"]["tracks"]["video"]["tracks"][0]["item_count"] = -1
    assert checker.check_video_item_count_positive(snapshot).passed is False


def test_check_video_item_count_positive_rejects_inconsistent_declared_count():
    snapshot = _valid_snapshot(video_item_counts=(1,), video_track_count_override=5)
    assert checker.check_video_item_count_positive(snapshot).passed is False


def test_check_video_item_count_positive_pass_with_matching_items_list_length():
    snapshot = _valid_snapshot(video_item_counts=(2,), video_track_items_override=[["a", "b"]])
    assert checker.check_video_item_count_positive(snapshot).passed is True


def test_check_video_item_count_positive_fails_when_items_list_length_mismatches_item_count():
    snapshot = _valid_snapshot(video_item_counts=(2,), video_track_items_override=[["a"]])
    assert checker.check_video_item_count_positive(snapshot).passed is False


# --- evaluate_offline_preflight: capture-vs-preflight distinction, full pass ---

def test_evaluate_offline_preflight_incomplete_capture_short_circuits():
    snapshot = _valid_snapshot()
    del snapshot["media_pool"]
    result = checker.evaluate_offline_preflight(snapshot)
    assert result.snapshot_capture_status == "incomplete"
    assert result.render_preflight_status == "not_evaluated"
    assert len(result.checks) == 1


def test_evaluate_offline_preflight_complete_capture_all_checks_pass():
    result = checker.evaluate_offline_preflight(_valid_snapshot())
    assert result.snapshot_capture_status == "complete"
    assert result.render_preflight_status == "passed"
    # 1 capture + 13 render-specific checks (Rev3 adds render_queue_consistency
    # and resolve_product_identity_observed over Rev2's 11).
    assert len(result.checks) == 14
    assert all(check.passed for check in result.checks)


def test_evaluate_offline_preflight_result_always_carries_interpretation_limits():
    result = checker.evaluate_offline_preflight(_valid_snapshot())
    assert result.interpretation_limits == checker.INTERPRETATION_LIMITS


def test_snapshot_capture_success_is_not_render_preflight_success():
    snapshot = _valid_snapshot(preset_names=("YouTube - 720p",))
    result = checker.evaluate_offline_preflight(snapshot)
    assert result.snapshot_capture_status == "complete"
    assert result.render_preflight_status != "passed"


# --- CLI ---------------------------------------------------------------------

def test_main_exits_0_when_preflight_passes(tmp_path, capsys):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_valid_snapshot()), encoding="utf-8")
    exit_code = checker.main(["--snapshot", str(path)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["render_preflight_status"] == "passed"


def test_main_exits_3_when_capture_complete_but_preflight_fails(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_valid_snapshot(video_item_counts=(0,))), encoding="utf-8")
    assert checker.main(["--snapshot", str(path)]) == 3


def test_main_exits_2_when_capture_incomplete(tmp_path):
    snapshot = _valid_snapshot()
    del snapshot["media_pool"]
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert checker.main(["--snapshot", str(path)]) == 2


def test_main_exits_2_when_snapshot_file_missing(tmp_path):
    assert checker.main(["--snapshot", str(tmp_path / "missing.json")]) == 2


# --- static safety: never imports collector or references Resolve ----------

def test_module_source_has_no_resolve_import_statements():
    source = Path(checker.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "resolve" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "resolve" not in node.module.lower()


def test_module_source_never_calls_import_module_or_scriptapp():
    source = Path(checker.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"import_module", "scriptapp"}
        if isinstance(node, ast.Name):
            assert node.id not in {"scriptapp"}


def test_module_never_imports_any_scripts_sibling():
    """This module never imports the collector or any other scripts.* module."""
    source = Path(checker.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("scripts")
        if isinstance(node, ast.ImportFrom):
            assert node.module != "scripts"
