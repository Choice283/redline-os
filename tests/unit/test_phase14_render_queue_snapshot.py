from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from pathlib import Path

import pytest

REVIEW_ROOT = Path(__file__).resolve().parents[2]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts import phase14_render_queue_snapshot as probe
from scripts.phase14_resolve_context_snapshot import SnapshotError


# ---------------------------------------------------------------------------
# Fakes. Each Resolve-shaped fake accepts a *sequence* of return values, one
# per call; a sequence shorter than the number of calls made repeats its
# final element. This lets tests express the exact three-call bracket
# (before A, before B, final-after-B) collect_render_queue_snapshot()
# performs per call site (Rev2, Finding 5), including cases where a value
# changes only on the 2nd or 3rd call.
# ---------------------------------------------------------------------------


class FakeTimeline:
    def __init__(self, name_sequence):
        self._names = [name_sequence] if isinstance(name_sequence, str) else list(name_sequence)
        self.calls = 0

    def GetName(self):
        idx = min(self.calls, len(self._names) - 1)
        self.calls += 1
        return self._names[idx]


class FakeProject:
    def __init__(self, name_sequence, timeline, *, rendering_sequence=False, queue_sequence=None):
        self._names = [name_sequence] if isinstance(name_sequence, str) else list(name_sequence)
        self.name_calls = 0
        self.timeline = timeline
        self._rendering = (
            [rendering_sequence] if isinstance(rendering_sequence, bool) else list(rendering_sequence)
        )
        self.rendering_calls = 0
        if queue_sequence is None:
            queue_sequence = [[]]
        # queue_sequence: a list of queues (each queue itself a list of dict
        # entries), one per GetRenderJobList() call.
        self._queues = [list(q) for q in queue_sequence]
        self.queue_calls = 0

    def GetName(self):
        idx = min(self.name_calls, len(self._names) - 1)
        self.name_calls += 1
        return self._names[idx]

    def GetCurrentTimeline(self):
        return self.timeline

    def IsRenderingInProgress(self):
        idx = min(self.rendering_calls, len(self._rendering) - 1)
        self.rendering_calls += 1
        return self._rendering[idx]

    def GetRenderJobList(self):
        idx = min(self.queue_calls, len(self._queues) - 1)
        self.queue_calls += 1
        return list(self._queues[idx])


class FakeProjectManager:
    def __init__(self, project: FakeProject | None):
        self.project = project

    def GetCurrentProject(self):
        return self.project


class FakeResolve:
    def __init__(self, project_manager: FakeProjectManager | None):
        self.project_manager = project_manager

    def GetProjectManager(self):
        return self.project_manager


EXPECTED_PROJECT = "RLC-E9901_MASTER"
EXPECTED_TIMELINE = "RLC-E9901_TIMELINE"
EXPECTED_JOB_ID = "3c0af847-bddd-43ee-8b79-a7b64cb915b4"


def make_resolve(
    *,
    project_name_sequence=EXPECTED_PROJECT,
    timeline_name_sequence=EXPECTED_TIMELINE,
    rendering_sequence=False,
    queue_sequence=None,
):
    timeline = FakeTimeline(timeline_name_sequence)
    project = FakeProject(
        project_name_sequence,
        timeline,
        rendering_sequence=rendering_sequence,
        queue_sequence=queue_sequence,
    )
    return FakeResolve(FakeProjectManager(project)), project, timeline


def context():
    return probe.QueueSnapshotContext(expected_project=EXPECTED_PROJECT, expected_timeline=EXPECTED_TIMELINE)


def snapshot_document(entries, *, observed_project=EXPECTED_PROJECT, observed_timeline=EXPECTED_TIMELINE,
                       rendering=False, declared_count=None, collector_revision=None,
                       schema_version=None, mission=None, snapshot_complete=True):
    return {
        "schema_version": probe.SCHEMA_VERSION if schema_version is None else schema_version,
        "mission": probe.MISSION if mission is None else mission,
        "captured_at": "2026-01-01T00:00:00.000000Z",
        "collector": {
            "name": probe.COLLECTOR_NAME,
            "revision": probe.EXECUTION_REVISION_ID if collector_revision is None else collector_revision,
        },
        "expected_context": {"project": EXPECTED_PROJECT, "timeline": EXPECTED_TIMELINE},
        "observed_context": {"project": observed_project, "timeline": observed_timeline},
        "rendering_in_progress": rendering,
        "render_queue_count": len(entries) if declared_count is None else declared_count,
        "render_queue": entries,
        "snapshot_complete": snapshot_complete,
    }


def entry(index, job_id, *, status="identified", fields=None):
    """Builds one render_queue entry. When `fields` is not supplied, it
    defaults to something internally self-consistent with `job_id`/
    `status` (Rev3, Finding 1 requires the two to agree) -- an
    `{"JobId": job_id}` payload for an ordinary identified entry, or an
    empty payload otherwise. Tests that want to construct a deliberately
    self-contradictory entry (Finding 1's own regression tests) pass
    `fields=` explicitly to override this default."""

    if fields is None:
        if status == "identified" and isinstance(job_id, str) and job_id.strip():
            fields = {"JobId": job_id}
        else:
            fields = {}
    return {"index": index, "job_id": job_id, "job_id_status": status, "fields": fields}


def valid_snapshot_with_jobs(job_ids):
    return snapshot_document([entry(i, jid) for i, jid in enumerate(job_ids)])


def _snapshot_args(output_path: Path, *, execution_authorization):
    return argparse.Namespace(
        expected_project=EXPECTED_PROJECT,
        expected_timeline=EXPECTED_TIMELINE,
        output=output_path,
        execution_authorization=execution_authorization,
    )


# ---------------------------------------------------------------------------
# Import safety / revision identity
# ---------------------------------------------------------------------------


def test_module_import_does_not_contact_resolve():
    assert "DaVinciResolveScript" not in sys.modules


def test_execution_revision_id_is_well_formed_and_distinct_from_rev1_rev2_and_rev8():
    from scripts import phase14_resolve_context_snapshot as rev8

    assert probe.EXECUTION_REVISION_ID_PATTERN.fullmatch(probe.EXECUTION_REVISION_ID)
    assert probe.EXECUTION_REVISION_ID != rev8.EXECUTION_REVISION_ID
    assert probe.EXECUTION_REVISION_ID == "phase14.2-render-queue-snapshot-construction-rev3"
    assert probe.EXECUTION_REVISION_ID != "phase14.2-render-queue-snapshot-construction-rev1"
    assert probe.EXECUTION_REVISION_ID != "phase14.2-render-queue-snapshot-construction-rev2"


def test_accepted_collector_revisions_is_exactly_this_revision():
    assert probe.ACCEPTED_COLLECTOR_REVISIONS == {probe.EXECUTION_REVISION_ID}


# ---------------------------------------------------------------------------
# Execution interlock (unchanged behavior from Rev1, re-verified against Rev2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "supplied,expected_code",
    [
        (None, "live_execution_authorization_missing"),
        ("", "live_execution_authorization_missing"),
        (" ", "live_execution_authorization_invalid"),
        ("not the right id", "live_execution_authorization_invalid"),
        ("wrong-but-well-formed-id", "live_execution_revision_mismatch"),
        ("phase14.2-render-queue-snapshot-construction-rev1", "live_execution_revision_mismatch"),
        ("phase14.2-render-queue-snapshot-construction-rev2", "live_execution_revision_mismatch"),
    ],
)
def test_enforce_execution_interlock_fails_closed(supplied, expected_code):
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.enforce_execution_interlock(supplied)
    assert exc_info.value.code == expected_code


def test_enforce_execution_interlock_accepts_exact_revision():
    probe.enforce_execution_interlock(probe.EXECUTION_REVISION_ID)


def test_missing_interlock_stops_before_resolve_connection(tmp_path, monkeypatch):
    def _blow_up():
        raise AssertionError("connect_resolve_read_only must not be called")

    monkeypatch.setattr(probe, "connect_resolve_read_only", _blow_up)
    args = _snapshot_args(tmp_path / "out.json", execution_authorization=None)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.run_snapshot_command(args)
    assert exc_info.value.code == "live_execution_authorization_missing"


def test_wrong_interlock_stops_before_resolve_connection(tmp_path, monkeypatch):
    def _blow_up():
        raise AssertionError("connect_resolve_read_only must not be called")

    monkeypatch.setattr(probe, "connect_resolve_read_only", _blow_up)
    args = _snapshot_args(tmp_path / "out.json", execution_authorization="not-the-real-revision")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.run_snapshot_command(args)
    assert exc_info.value.code == "live_execution_revision_mismatch"


def test_output_collision_fails_before_resolve_contact(tmp_path, monkeypatch):
    def _blow_up():
        raise AssertionError("connect_resolve_read_only must not be called")

    monkeypatch.setattr(probe, "connect_resolve_read_only", _blow_up)
    existing = tmp_path / "out.json"
    existing.write_text("{}", encoding="utf-8")
    args = _snapshot_args(existing, execution_authorization=probe.EXECUTION_REVISION_ID)
    with pytest.raises(SnapshotError) as exc_info:
        probe.run_snapshot_command(args)
    assert exc_info.value.code == "output_path_already_exists"


def test_run_snapshot_command_end_to_end_with_injected_resolve(tmp_path, monkeypatch):
    resolve, _project, _timeline = make_resolve(queue_sequence=[[{"JobId": "job-1"}]])
    monkeypatch.setattr(probe, "connect_resolve_read_only", lambda: resolve)
    output = tmp_path / "out.json"
    args = _snapshot_args(output, execution_authorization=probe.EXECUTION_REVISION_ID)
    result = probe.run_snapshot_command(args)
    assert result == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["render_queue_count"] == 1
    assert written["render_queue"][0]["job_id"] == "job-1"
    assert written["collector"]["revision"] == probe.EXECUTION_REVISION_ID


# ---------------------------------------------------------------------------
# Finding 5: final rendering/context bracket -- exact call-sequence proof
# ---------------------------------------------------------------------------


def test_call_sequence_is_exactly_three_guards_and_two_queue_reads():
    resolve, project, timeline = make_resolve(queue_sequence=[[{"JobId": "job-1"}]])
    probe.collect_render_queue_snapshot(resolve, context())
    assert project.name_calls == 3
    assert timeline.calls == 3
    assert project.rendering_calls == 3
    assert project.queue_calls == 2


def test_rendering_false_before_a_false_before_b_true_after_b_fails():
    resolve, _p, _t = make_resolve(
        rendering_sequence=[False, False, True],
        queue_sequence=[[{"JobId": "job-1"}]],
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "rendering_active"


def test_project_changes_after_b_fails():
    resolve, _p, _t = make_resolve(
        project_name_sequence=[EXPECTED_PROJECT, EXPECTED_PROJECT, "SOME-OTHER-PROJECT"],
        queue_sequence=[[{"JobId": "job-1"}]],
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "project_identity_mismatch"


def test_timeline_changes_after_b_fails():
    resolve, _p, _t = make_resolve(
        timeline_name_sequence=[EXPECTED_TIMELINE, EXPECTED_TIMELINE, "SOME-OTHER-TIMELINE"],
        queue_sequence=[[{"JobId": "job-1"}]],
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "timeline_identity_mismatch"


def test_stable_context_and_rendering_state_passes():
    resolve, _p, _t = make_resolve(
        project_name_sequence=EXPECTED_PROJECT,
        timeline_name_sequence=EXPECTED_TIMELINE,
        rendering_sequence=False,
        queue_sequence=[[{"JobId": "job-1"}]],
    )
    snapshot = probe.collect_render_queue_snapshot(resolve, context())
    assert snapshot["snapshot_complete"] is True
    assert snapshot["rendering_in_progress"] is False
    assert snapshot["observed_context"] == {"project": EXPECTED_PROJECT, "timeline": EXPECTED_TIMELINE}


def test_final_guard_observed_values_are_published_in_snapshot():
    # The final (3rd) guard call happens after both queue reads; its
    # observed project/timeline are what the published snapshot reports.
    resolve, _p, _t = make_resolve(queue_sequence=[[{"JobId": "job-1"}]])
    snapshot = probe.collect_render_queue_snapshot(resolve, context())
    assert snapshot["observed_context"]["project"] == EXPECTED_PROJECT
    assert snapshot["observed_context"]["timeline"] == EXPECTED_TIMELINE


# ---------------------------------------------------------------------------
# Context / identity guards (project/timeline mismatch on first call, etc.)
# ---------------------------------------------------------------------------


def test_project_identity_mismatch_fails():
    resolve, _p, _t = make_resolve(project_name_sequence="SomeOtherProject")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "project_identity_mismatch"


def test_timeline_identity_mismatch_fails():
    resolve, _p, _t = make_resolve(timeline_name_sequence="SomeOtherTimeline")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "timeline_identity_mismatch"


def test_rendering_active_fails():
    resolve, _p, _t = make_resolve(rendering_sequence=True)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "rendering_active"


def test_invalid_expected_context_fails():
    resolve, _p, _t = make_resolve()
    bad_context = probe.QueueSnapshotContext(expected_project="  ", expected_timeline=EXPECTED_TIMELINE)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, bad_context)
    assert exc_info.value.code == "invalid_expected_context"


def test_current_project_missing_fails():
    resolve = FakeResolve(FakeProjectManager(None))
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "current_project_missing"


# ---------------------------------------------------------------------------
# Queue count and permitted-non-empty behavior
# ---------------------------------------------------------------------------


def test_empty_queue_is_valid():
    resolve, _p, _t = make_resolve(queue_sequence=[[]])
    snapshot = probe.collect_render_queue_snapshot(resolve, context())
    assert snapshot["render_queue_count"] == 0
    assert snapshot["render_queue"] == []
    assert snapshot["snapshot_complete"] is True


def test_one_queue_job_is_valid():
    resolve, _p, _t = make_resolve(queue_sequence=[[{"JobId": "job-1", "TargetDir": "C:/out"}]])
    snapshot = probe.collect_render_queue_snapshot(resolve, context())
    assert snapshot["render_queue_count"] == 1
    e = snapshot["render_queue"][0]
    assert e["job_id"] == "job-1"
    assert e["job_id_status"] == "identified"
    assert e["fields"]["TargetDir"] == "C:/out"


def test_multiple_queue_jobs_are_representable():
    resolve, _p, _t = make_resolve(
        queue_sequence=[[{"JobId": "job-1"}, {"JobId": "job-2"}, {"JobId": "job-3"}]]
    )
    snapshot = probe.collect_render_queue_snapshot(resolve, context())
    assert snapshot["render_queue_count"] == 3
    assert [e["job_id"] for e in snapshot["render_queue"]] == ["job-1", "job-2", "job-3"]


def test_render_queue_drift_between_a_and_b_fails_closed():
    resolve, _p, _t = make_resolve(
        queue_sequence=[[{"JobId": "job-1"}], [{"JobId": "job-1"}, {"JobId": "job-2"}]]
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.collect_render_queue_snapshot(resolve, context())
    assert exc_info.value.code == "render_queue_drift"


# ---------------------------------------------------------------------------
# Finding 3: conflicting job-ID aliases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["JobId", "JobID", "jobId", "job_id", "Id", "ID", "id"])
def test_known_job_id_key_spellings_normalize_correctly(key):
    e = probe.normalize_queue_entry({key: "abc-123"}, 0)
    assert e["job_id"] == "abc-123"
    assert e["job_id_status"] == "identified"


def test_missing_job_id_key_classifies_as_unidentified():
    e = probe.normalize_queue_entry({"PresetName": "broadcast_master"}, 0)
    assert e["job_id"] is None
    assert e["job_id_status"] == "unidentified"


def test_ambiguous_job_id_value_type_fails_closed():
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.normalize_queue_entry({"JobId": {"nested": "dict"}}, 0)
    assert exc_info.value.code == "queue_entry_job_id_malformed"


def test_agreeing_aliases_are_identified():
    status, job_id = probe._job_id_key_status({"JobId": "same", "job_id": "same"})
    assert status == "identified"
    assert job_id == "same"
    e = probe.normalize_queue_entry({"JobId": "same", "job_id": "same"}, 0)
    assert e["job_id_status"] == "identified"
    assert e["job_id"] == "same"


def test_conflicting_aliases_fail_closed():
    status, job_id = probe._job_id_key_status({"JobId": "one", "job_id": "two"})
    assert status == "conflicting"
    assert job_id is None
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.normalize_queue_entry({"JobId": "one", "job_id": "two"}, 0)
    assert exc_info.value.code == "queue_entry_job_id_conflicting"


def test_conflicting_aliases_across_three_keys_fail_closed():
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.normalize_queue_entry({"JobId": "one", "job_id": "one", "Id": "two"}, 0)
    assert exc_info.value.code == "queue_entry_job_id_conflicting"


def test_duplicate_identified_job_ids_fail_closed_at_collection():
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.normalize_render_queue([{"JobId": "same"}, {"JobId": "same"}])
    assert exc_info.value.code == "duplicate_render_queue_job_id"


def test_malformed_queue_type_fails():
    with pytest.raises(SnapshotError) as exc_info:
        probe.normalize_render_queue("not-a-list")
    assert exc_info.value.code == "invalid_collection"


def test_malformed_queue_entry_fails():
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.normalize_render_queue(["not-a-dict"])
    assert exc_info.value.code == "queue_entry_malformed"


def test_queue_entry_non_string_key_fails():
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.normalize_queue_entry({1: "value"}, 0)
    assert exc_info.value.code == "queue_entry_key_not_string"


def test_false_render_job_list_normalizes_to_empty_queue():
    entries, count = probe.normalize_render_queue(False)
    assert entries == []
    assert count == 0


# ---------------------------------------------------------------------------
# Finding 4: strict JSON / non-finite floats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_require_finite_json_value_rejects_non_finite_floats(bad_value):
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.require_finite_json_value({"metric": bad_value})
    assert exc_info.value.code == "non_finite_float_in_evidence"


def test_require_finite_json_value_accepts_finite_floats_and_scalars():
    probe.require_finite_json_value({"a": 1.5, "b": [1, "x", None, True], "c": {"d": -3.25}})


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_collection_rejects_non_finite_float_in_queue_field_and_writes_nothing(tmp_path, monkeypatch, bad_value):
    resolve, _p, _t = make_resolve(queue_sequence=[[{"JobId": "job-1", "Metric": bad_value}]])
    monkeypatch.setattr(probe, "connect_resolve_read_only", lambda: resolve)
    output = tmp_path / "out.json"
    args = _snapshot_args(output, execution_authorization=probe.EXECUTION_REVISION_ID)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.run_snapshot_command(args)
    assert exc_info.value.code == "non_finite_float_in_evidence"
    assert not output.exists()


def test_write_strict_json_no_overwrite_rejects_non_finite_float(tmp_path):
    output = tmp_path / "out.json"
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.write_strict_json_no_overwrite(output, {"x": float("nan")})
    assert exc_info.value.code == "non_finite_float_in_evidence"
    assert not output.exists()


def test_compare_output_path_also_enforces_strict_json(tmp_path):
    # The comparison result itself never legitimately contains a float, but
    # this proves the compare CLI path writes through the same strict-JSON
    # writer as the snapshot path (Finding 4's explicit "also test the
    # comparison-output path" requirement), by patching compare_expected_job_id's
    # return value to smuggle a non-finite float through run_compare_command.
    import scripts.phase14_render_queue_snapshot as mod

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(valid_snapshot_with_jobs([EXPECTED_JOB_ID])), encoding="utf-8")
    output_path = tmp_path / "comparison.json"

    original = mod.compare_expected_job_id

    def _forged(snapshot, expected_job_id):
        result = original(snapshot, expected_job_id)
        result["forged_metric"] = float("nan")
        return result

    real_compare = mod.compare_expected_job_id
    mod.compare_expected_job_id = _forged
    try:
        args = argparse.Namespace(snapshot=snapshot_path, output=output_path, expected_job_id=EXPECTED_JOB_ID)
        with pytest.raises(probe.QueueSnapshotError) as exc_info:
            mod.run_compare_command(args)
        assert exc_info.value.code == "non_finite_float_in_evidence"
        assert not output_path.exists()
    finally:
        mod.compare_expected_job_id = real_compare


def test_write_json_no_overwrite_alone_would_have_permitted_nan_demonstration():
    """Documents the exact Rev1 gap this Rev2 layer closes: Rev8's own
    generic writer, called directly (bypassing this probe's strict layer),
    accepts a non-finite float without error."""
    from scripts.phase14_resolve_context_snapshot import normalize_json_value

    normalized = normalize_json_value({"x": float("nan")})
    text = json.dumps(normalized, indent=2, sort_keys=True)
    assert "NaN" in text  # Confirms the underlying gap this layer defends against.


# ---------------------------------------------------------------------------
# Finding 2: validate_queue_snapshot_document invariants
# ---------------------------------------------------------------------------


def test_validate_accepts_a_well_formed_snapshot():
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID])
    validated = probe.validate_queue_snapshot_document(snap)
    assert validated is snap


def test_validate_rejects_non_dict_document():
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document("not a dict")
    assert exc_info.value.code == "invalid_snapshot_document"


def test_validate_rejects_wrong_schema_version():
    snap = snapshot_document([], schema_version="9.9")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_schema_mismatch"


def test_validate_rejects_wrong_mission():
    snap = snapshot_document([], mission="Some Other Mission")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_mission_mismatch"


def test_validate_rejects_incomplete_snapshot():
    snap = snapshot_document([], snapshot_complete=False)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "incomplete_snapshot"


def test_validate_rejects_missing_sections():
    snap = snapshot_document([])
    del snap["collector"]
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_top_level_keys_invalid"


def test_validate_rejects_wrong_collector_name():
    snap = snapshot_document([])
    snap["collector"]["name"] = "some-other-collector"
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_collector_name_mismatch"


def test_validate_rejects_unaccepted_collector_revision():
    snap = snapshot_document([], collector_revision="phase14.2-render-queue-snapshot-construction-rev1")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_collector_revision_not_accepted"


def test_validate_rejects_malformed_collector_shape():
    snap = snapshot_document([])
    snap["collector"] = {"name": probe.COLLECTOR_NAME, "revision": probe.EXECUTION_REVISION_ID, "extra": "x"}
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_collector_invalid"


def test_validate_rejects_observed_project_mismatch():
    snap = snapshot_document([], observed_project="WRONG")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_observed_project_mismatch"


def test_validate_rejects_observed_timeline_mismatch():
    snap = snapshot_document([], observed_timeline="WRONG")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_observed_timeline_mismatch"


def test_validate_rejects_empty_string_context_field():
    snap = snapshot_document([], observed_project="   ")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_context_field_invalid"


@pytest.mark.parametrize("bad_rendering", [True, None, 0, 1, "false", "False"])
def test_validate_rejects_any_non_false_rendering_value(bad_rendering):
    snap = snapshot_document([], rendering=bad_rendering)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_rendering_not_false"


def test_validate_rejects_render_queue_count_mismatch():
    snap = snapshot_document([entry(0, EXPECTED_JOB_ID)], declared_count=999)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_count_mismatch"


@pytest.mark.parametrize("bad_count", [-1, 1.5, "1", True])
def test_validate_rejects_malformed_render_queue_count(bad_count):
    snap = snapshot_document([], declared_count=bad_count)
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_count_invalid"


def test_validate_rejects_render_queue_not_a_list():
    snap = snapshot_document([])
    snap["render_queue"] = "not-a-list"
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_not_a_list"


def test_validate_rejects_non_dict_entry():
    snap = snapshot_document(["not-a-dict"])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_invalid"


def test_validate_rejects_entry_with_extra_or_missing_keys():
    snap = snapshot_document([{"index": 0, "job_id": None, "job_id_status": "unidentified"}])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_shape_invalid"


def test_validate_rejects_out_of_order_index():
    snap = snapshot_document([entry(37, EXPECTED_JOB_ID)])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_index_out_of_order"


@pytest.mark.parametrize("bad_index", [-1, 1.5, "0", True])
def test_validate_rejects_malformed_entry_index(bad_index):
    snap = snapshot_document([{"index": bad_index, "job_id": None, "job_id_status": "unidentified", "fields": {}}])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_index_invalid"


def test_validate_rejects_unsupported_job_id_status():
    snap = snapshot_document([entry(0, None, status="malformed")])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_status_invalid"


def test_validate_rejects_identified_entry_with_null_job_id():
    snap = snapshot_document([entry(0, None, status="identified")])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_identified_job_id_invalid"


def test_validate_rejects_unidentified_entry_with_non_null_job_id():
    snap = snapshot_document([entry(0, "should-be-null", status="unidentified")])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_unidentified_job_id_invalid"


def test_validate_rejects_duplicate_identified_job_ids():
    snap = snapshot_document([entry(0, "same"), entry(1, "same")])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_duplicate_identified_job_id"


def test_validate_rejects_non_dict_fields():
    snap = snapshot_document([{"index": 0, "job_id": "x", "job_id_status": "identified", "fields": "not-a-dict"}])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_fields_invalid"


def test_validate_rejects_non_finite_float_in_entry_fields():
    snap = snapshot_document([entry(0, EXPECTED_JOB_ID, fields={"metric": float("nan")})])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "non_finite_float_in_evidence"


def test_full_forged_evidence_scenario_from_independent_review_fails_closed():
    """Exact regression matching the independent review reproduction: a
    snapshot with correct schema/mission/completeness but mismatched
    observed project/timeline, rendering_in_progress true, an incorrect
    declared render_queue_count, and one entry whose index does not match
    its queue position, containing the expected job ID. Proves
    compare_expected_job_id() fails closed rather than returning a
    successful classification. No Resolve contact occurs anywhere in this
    test."""

    forged = {
        "schema_version": probe.SCHEMA_VERSION,
        "mission": probe.MISSION,
        "captured_at": "2026-01-01T00:00:00.000000Z",
        "collector": {"name": probe.COLLECTOR_NAME, "revision": probe.EXECUTION_REVISION_ID},
        "expected_context": {"project": "RLC-E9901_MASTER", "timeline": "RLC-E9901_TIMELINE"},
        "observed_context": {"project": "WRONG", "timeline": "WRONG"},
        "rendering_in_progress": True,
        "render_queue_count": 999,
        "render_queue": [
            {"index": 37, "job_id": EXPECTED_JOB_ID, "job_id_status": "identified", "fields": {}}
        ],
        "snapshot_complete": True,
    }
    with pytest.raises(probe.QueueSnapshotError):
        probe.compare_expected_job_id(forged, EXPECTED_JOB_ID)


# ---------------------------------------------------------------------------
# Rev3 Finding 1: cross-validate normalized Job ID against preserved fields
# ---------------------------------------------------------------------------


def test_rev3_finding1_valid_entry_passes():
    snap = snapshot_document([entry(0, "expected", fields={"JobId": "expected"})])
    validated = probe.validate_queue_snapshot_document(snap)
    assert validated is snap


def test_rev3_finding1_valid_agreeing_aliases_pass():
    snap = snapshot_document(
        [entry(0, "expected", fields={"JobId": "expected", "job_id": "expected"})]
    )
    probe.validate_queue_snapshot_document(snap)


def test_rev3_finding1_top_level_id_contradicts_fields_fails_closed():
    snap = snapshot_document([entry(0, "expected", fields={"JobId": "OTHER"})])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_job_id_disagrees_with_fields"


def test_rev3_finding1_identified_claim_with_no_usable_id_in_fields_fails_closed():
    snap = snapshot_document([entry(0, "expected", fields={})])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_job_id_status_disagrees_with_fields"


def test_rev3_finding1_unidentified_claim_with_hidden_id_in_fields_fails_closed():
    snap = snapshot_document(
        [entry(0, None, status="unidentified", fields={"JobId": "expected"})]
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_job_id_status_disagrees_with_fields"


def test_rev3_finding1_conflicting_aliases_in_fields_fail_closed():
    snap = snapshot_document(
        [entry(0, "expected", fields={"JobId": "expected", "job_id": "OTHER"})]
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_fields_job_id_conflicting"


def test_rev3_finding1_malformed_alias_in_fields_fails_closed():
    snap = snapshot_document(
        [entry(0, "expected", fields={"JobId": {"nested": "invalid"}})]
    )
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_render_queue_entry_fields_job_id_malformed"


def test_rev3_finding1_compare_expected_job_id_also_fails_closed_on_contradiction():
    """Proves the cross-validation is reached through the public
    compare_expected_job_id() entry point actually used by the CLI, not
    only through validate_queue_snapshot_document() called directly."""
    snap = snapshot_document([entry(0, "expected", fields={"JobId": "OTHER"})])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.compare_expected_job_id(snap, "expected")
    assert exc_info.value.code == "snapshot_render_queue_entry_job_id_disagrees_with_fields"


# ---------------------------------------------------------------------------
# Rev3 Finding 2: evidence envelope must match an actual Rev3 snapshot
# ---------------------------------------------------------------------------


def test_rev3_finding2_valid_captured_at_passes():
    snap = snapshot_document([])
    snap["captured_at"] = probe.utc_now()
    probe.validate_queue_snapshot_document(snap)


def test_rev3_finding2_missing_captured_at_rejected():
    snap = snapshot_document([])
    del snap["captured_at"]
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_top_level_keys_invalid"


def test_rev3_finding2_none_captured_at_rejected():
    snap = snapshot_document([])
    snap["captured_at"] = None
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_captured_at_invalid"


def test_rev3_finding2_nan_captured_at_rejected():
    snap = snapshot_document([])
    snap["captured_at"] = float("nan")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "non_finite_float_in_evidence"


def test_rev3_finding2_empty_string_captured_at_rejected():
    snap = snapshot_document([])
    snap["captured_at"] = ""
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_captured_at_invalid"


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "not-a-timestamp",
        "2026-08-10",
        "2026-08-10T21:39:02Z",  # missing fractional seconds
        "2026-08-10 21:39:02.349088Z",  # missing 'T'
        "08-10-2026T21:39:02.349088Z",  # wrong date order
    ],
)
def test_rev3_finding2_malformed_captured_at_rejected(bad_timestamp):
    snap = snapshot_document([])
    snap["captured_at"] = bad_timestamp
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_captured_at_malformed"


@pytest.mark.parametrize(
    "non_utc_timestamp",
    [
        "2026-08-10T21:39:02.349088+05:00",
        "2026-08-10T21:39:02.349088+00:00",
        "2026-08-10T21:39:02.349088",  # no zone designator at all
    ],
)
def test_rev3_finding2_non_utc_captured_at_rejected(non_utc_timestamp):
    snap = snapshot_document([])
    snap["captured_at"] = non_utc_timestamp
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_captured_at_malformed"


def test_rev3_finding2_impossible_calendar_instant_rejected():
    snap = snapshot_document([])
    snap["captured_at"] = "2026-13-40T99:99:99.999999Z"
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_captured_at_not_parseable"


def test_rev3_finding2_extra_top_level_key_rejected():
    snap = snapshot_document([])
    snap["unexpected_extra_field"] = "surprise"
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_top_level_keys_invalid"


@pytest.mark.parametrize(
    "key",
    [
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
    ],
)
def test_rev3_finding2_missing_any_required_top_level_key_rejected(key):
    snap = snapshot_document([])
    del snap[key]
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "snapshot_top_level_keys_invalid"


def test_rev3_finding2_top_level_key_set_is_exactly_ten_keys():
    assert probe._REQUIRED_TOP_LEVEL_KEYS == {
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


def test_rev3_finding2_whole_document_must_be_finite_json_not_only_entry_fields():
    """A non-finite float placed OUTSIDE any entry's fields (here, smuggled
    into expected_context.project) must still be rejected -- proving the
    finiteness check covers the complete document, not merely each entry's
    fields sub-object the way Rev2's did."""
    snap = snapshot_document([])
    snap["expected_context"]["project"] = float("nan")
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.validate_queue_snapshot_document(snap)
    assert exc_info.value.code == "non_finite_float_in_evidence"


def test_rev3_finding2_collected_snapshot_captured_at_validates_successfully():
    """Round-trip proof: a snapshot actually produced by
    collect_render_queue_snapshot() (via a fake Resolve handle) has a
    captured_at value that this validator's own captured_at check accepts."""
    resolve, _project, _timeline = make_resolve(queue_sequence=[[]])
    snapshot = probe.collect_render_queue_snapshot(resolve, context())
    probe.validate_queue_snapshot_document(snapshot)


# ---------------------------------------------------------------------------
# Rev3 additional hardening: compare_expected_job_id() input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["", "   ", 123, 1.5, [], {}, ("t",)])
def test_rev3_expected_job_id_must_be_non_empty_string_when_supplied(bad_value):
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.compare_expected_job_id({}, bad_value)
    assert exc_info.value.code == "expected_job_id_invalid"


def test_rev3_expected_job_id_none_is_still_a_valid_observational_query():
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID])
    result = probe.compare_expected_job_id(snap, None)
    assert result["classification"] == "no_expected_job_id_supplied"


def test_rev3_expected_job_id_real_string_is_unaffected():
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID])
    result = probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert result["classification"] == "exact_single_job_match"


def test_rev3_expected_job_id_hardening_checked_before_snapshot_validation():
    """The expected_job_id shape check must fail closed even against a
    completely invalid/empty snapshot document -- proving it is checked
    independently, not merely as a side effect of validation succeeding."""
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.compare_expected_job_id("not even a dict", "   ")
    assert exc_info.value.code == "expected_job_id_invalid"


# ---------------------------------------------------------------------------
# Finding 1 (Rev2): exact queue-closure semantics
# ---------------------------------------------------------------------------


def test_sole_expected_job_is_exact_single_job_match():
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID])
    result = probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert result["classification"] == "exact_single_job_match"


def test_expected_plus_unrelated_identified_job_is_not_exact_match():
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID, "UNRELATED-JOB"])
    result = probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert result["classification"] != "exact_single_job_match"
    assert result["classification"] == "expected_job_present_with_additional_jobs"


def test_expected_plus_unidentified_entry_is_not_exact_match():
    snap = snapshot_document([entry(0, EXPECTED_JOB_ID), entry(1, None, status="unidentified")])
    result = probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert result["classification"] != "exact_single_job_match"
    assert result["classification"] == "ambiguous_due_to_unidentified_entries"


def test_unrelated_only_queue_is_not_exact_match():
    snap = valid_snapshot_with_jobs(["UNRELATED-JOB"])
    result = probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert result["classification"] != "exact_single_job_match"
    assert result["classification"] == "zero_matching_jobs"


def test_empty_queue_is_not_exact_match():
    snap = valid_snapshot_with_jobs([])
    result = probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert result["classification"] != "exact_single_job_match"
    assert result["classification"] == "zero_matching_jobs"


def test_theoretically_ambiguous_multiple_match_fails_closed_not_exact_match():
    # A snapshot with two identified entries sharing the expected job ID can
    # never legitimately pass validate_queue_snapshot_document() (Finding 2
    # requires identified-ID uniqueness), so this scenario is exercised at
    # its actual reachable boundary: validation rejects it before
    # classification, and compare_expected_job_id() therefore raises rather
    # than returning any classification, let alone a successful one.
    snap = snapshot_document([entry(0, EXPECTED_JOB_ID), entry(1, EXPECTED_JOB_ID)])
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)
    assert exc_info.value.code == "snapshot_render_queue_duplicate_identified_job_id"


def test_no_expected_job_id_supplied_is_observational_only():
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID])
    result = probe.compare_expected_job_id(snap, None)
    assert result["classification"] == "no_expected_job_id_supplied"


def test_classifications_are_five_distinct_values_plus_observational():
    """There must be exactly one classification meaning formal single-job
    closure, and it must be textually distinct from every other outcome."""
    outcomes = set()

    outcomes.add(probe.compare_expected_job_id(valid_snapshot_with_jobs([EXPECTED_JOB_ID]), EXPECTED_JOB_ID)["classification"])
    outcomes.add(probe.compare_expected_job_id(valid_snapshot_with_jobs([EXPECTED_JOB_ID, "X"]), EXPECTED_JOB_ID)["classification"])
    outcomes.add(
        probe.compare_expected_job_id(
            snapshot_document([entry(0, EXPECTED_JOB_ID), entry(1, None, status="unidentified")]),
            EXPECTED_JOB_ID,
        )["classification"]
    )
    outcomes.add(probe.compare_expected_job_id(valid_snapshot_with_jobs(["X"]), EXPECTED_JOB_ID)["classification"])
    outcomes.add(probe.compare_expected_job_id(valid_snapshot_with_jobs([]), None)["classification"])

    assert outcomes == {
        "exact_single_job_match",
        "expected_job_present_with_additional_jobs",
        "ambiguous_due_to_unidentified_entries",
        "zero_matching_jobs",
        "no_expected_job_id_supplied",
    }
    assert sum(1 for o in outcomes if o == "exact_single_job_match") == 1


# ---------------------------------------------------------------------------
# run_compare_command exit codes -- CLI surface for Finding 1
# ---------------------------------------------------------------------------


def _run_compare(tmp_path, snapshot_obj, expected_job_id):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot_obj), encoding="utf-8")
    output_path = tmp_path / "comparison.json"
    args = argparse.Namespace(snapshot=snapshot_path, output=output_path, expected_job_id=expected_job_id)
    rc = probe.run_compare_command(args)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    return rc, written


def test_cli_exit_zero_only_for_exact_single_job_match(tmp_path):
    rc, written = _run_compare(tmp_path, valid_snapshot_with_jobs([EXPECTED_JOB_ID]), EXPECTED_JOB_ID)
    assert rc == 0
    assert written["classification"] == "exact_single_job_match"


def test_cli_exit_nonzero_for_expected_plus_additional_job(tmp_path):
    rc, written = _run_compare(tmp_path, valid_snapshot_with_jobs([EXPECTED_JOB_ID, "OTHER"]), EXPECTED_JOB_ID)
    assert rc == 3
    assert written["classification"] != "exact_single_job_match"


def test_cli_exit_nonzero_for_zero_matching_jobs(tmp_path):
    rc, written = _run_compare(tmp_path, valid_snapshot_with_jobs(["OTHER"]), EXPECTED_JOB_ID)
    assert rc == 3


def test_cli_exit_zero_when_no_expected_job_id_supplied(tmp_path):
    rc, written = _run_compare(tmp_path, valid_snapshot_with_jobs([EXPECTED_JOB_ID]), None)
    assert rc == 0
    assert written["classification"] == "no_expected_job_id_supplied"


def test_offline_comparison_makes_zero_resolve_contact(monkeypatch):
    def _blow_up():
        raise AssertionError("connect_resolve_read_only must not be called")

    monkeypatch.setattr(probe, "connect_resolve_read_only", _blow_up)
    snap = valid_snapshot_with_jobs([EXPECTED_JOB_ID])
    probe.compare_expected_job_id(snap, EXPECTED_JOB_ID)


# ---------------------------------------------------------------------------
# Evidence output determinism / atomicity
# ---------------------------------------------------------------------------


def test_evidence_output_never_overwrites(tmp_path, monkeypatch):
    resolve, _p, _t = make_resolve(queue_sequence=[[]])
    monkeypatch.setattr(probe, "connect_resolve_read_only", lambda: resolve)
    output = tmp_path / "out.json"
    args = _snapshot_args(output, execution_authorization=probe.EXECUTION_REVISION_ID)
    assert probe.run_snapshot_command(args) == 0
    with pytest.raises(SnapshotError) as exc_info:
        probe.run_snapshot_command(args)
    assert exc_info.value.code == "output_path_already_exists"


def test_evidence_output_is_deterministic_json(tmp_path, monkeypatch):
    resolve, _p, _t = make_resolve(queue_sequence=[[{"JobId": "job-1"}]])
    monkeypatch.setattr(probe, "connect_resolve_read_only", lambda: resolve)
    output = tmp_path / "out.json"
    args = _snapshot_args(output, execution_authorization=probe.EXECUTION_REVISION_ID)
    probe.run_snapshot_command(args)
    text = output.read_text(encoding="utf-8")
    reparsed = json.loads(text)
    assert json.dumps(reparsed, indent=2, sort_keys=True) + "\n" == text


# ---------------------------------------------------------------------------
# Static safety: prohibited Resolve methods unreachable (unchanged from Rev1)
# ---------------------------------------------------------------------------


def _source_identifiers_and_string_literals() -> set[str]:
    source = Path(probe.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def test_prohibited_resolve_methods_absent_from_source():
    used = _source_identifiers_and_string_literals()
    overlap = used & probe._PROHIBITED_RESOLVE_METHODS
    assert overlap == set(), f"prohibited methods reachable in source: {overlap}"


@pytest.mark.parametrize("method_name", ["AddRenderJob", "DeleteRenderJob", "StartRendering"])
def test_specific_mutating_methods_absent_from_source(method_name):
    used = _source_identifiers_and_string_literals()
    assert method_name not in used


def test_read_only_allowlist_and_prohibited_list_are_disjoint():
    assert probe.READ_ONLY_RESOLVE_METHODS & probe._PROHIBITED_RESOLVE_METHODS == set()


def test_read_only_allowlist_is_exactly_six_getter_methods():
    assert probe.READ_ONLY_RESOLVE_METHODS == {
        "GetProjectManager",
        "GetCurrentProject",
        "GetName",
        "GetCurrentTimeline",
        "IsRenderingInProgress",
        "GetRenderJobList",
    }


def test_dynamic_dispatch_rejects_method_outside_allowlist():
    resolve, _p, _t = make_resolve()
    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.call_required(resolve, "AddRenderJob")
    assert exc_info.value.code == "accessor_not_allowlisted"


def test_dynamic_dispatch_does_not_reuse_rev8_broader_allowlist():
    """Rev8 permits e.g. GetMediaPool via its own 30-method allowlist; this
    probe's dispatch must reject it, proving the two allowlists are not
    accidentally shared by import."""

    class _HasMediaPool:
        def GetMediaPool(self):
            raise AssertionError("must never be called")

    with pytest.raises(probe.QueueSnapshotError) as exc_info:
        probe.call_required(_HasMediaPool(), "GetMediaPool")
    assert exc_info.value.code == "accessor_not_allowlisted"


def test_no_new_resolve_method_name_introduced_relative_to_rev1():
    """Finding 5 explicitly forbids adding any new Resolve method name while
    fixing the temporal bracket. The allowlist itself is the authoritative
    proof: it must remain exactly the Rev1 six methods."""
    assert probe.READ_ONLY_RESOLVE_METHODS == frozenset(
        {
            "GetProjectManager",
            "GetCurrentProject",
            "GetName",
            "GetCurrentTimeline",
            "IsRenderingInProgress",
            "GetRenderJobList",
        }
    )


def test_queue_job_id_no_longer_imported_from_rev8():
    """Finding 3: Rev8's precedence-ordered queue_job_id() is no longer
    imported (this probe now needs to see every alias, not just the first
    match)."""
    assert "queue_job_id" not in vars(probe)
