from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "phase14_test_d_queue_attempt.py"
spec = importlib.util.spec_from_file_location("phase14_test_d_queue_attempt", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def make_test_d_snapshot():
    return {
        "name": mod.CONTROL_TIMELINE,
        "settings": {"timelineFrameRate": 24.0},
        "settings_sha256": mod.EXPECTED_CONTROL_SETTINGS_SHA256,
        "start_frame": 86400,
        "end_frame": 86424,
        "markers": list(mod.EXPECTED_CONTROL_MARKERS),
        "tracks": {
            "audio": {"count": 1, "tracks": [[dict(mod.EXPECTED_CONTROL_AUDIO)]]},
            "video": {"count": 1, "tracks": [[]]},
            "subtitle": {"count": 1, "tracks": [[]]},
        },
    }


def test_enablement_revision_reports_execution_enabled_true():
    assert mod.EXECUTION_ENABLED is True
    assert mod.CONSTRUCTION_REVISION == (
        "phase14-test-d-video-payload-isolation-execution-enablement-r1"
    )


def test_test_d_exact_video_removal_passes():
    mod.validate_test_d_snapshot(make_test_d_snapshot())


def test_test_d_video_still_present_fails_closed():
    snap = make_test_d_snapshot()
    snap["tracks"]["video"]["tracks"][0].append(dict(mod.EXPECTED_CONTROL_VIDEO))
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_audio_change_fails_closed():
    snap = make_test_d_snapshot()
    snap["tracks"]["audio"]["tracks"][0][0]["duration"] = 23
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_marker_change_fails_closed():
    snap = make_test_d_snapshot()
    snap["markers"][0] = dict(snap["markers"][0])
    snap["markers"][0]["name"] = "changed"
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_settings_hash_change_fails_closed():
    snap = make_test_d_snapshot()
    snap["settings_sha256"] = "0" * 64
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_start_frame_change_fails_closed():
    snap = make_test_d_snapshot()
    snap["start_frame"] = 0
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_end_frame_shrunk_to_audio_end_passes():
    snap = make_test_d_snapshot()
    snap["end_frame"] = 86424
    mod.validate_test_d_snapshot(snap)


def test_test_d_end_frame_retained_baseline_passes():
    snap = make_test_d_snapshot()
    snap["end_frame"] = 86544
    mod.validate_test_d_snapshot(snap)


def test_test_d_unjustified_end_frame_drift_fails_closed():
    snap = make_test_d_snapshot()
    snap["end_frame"] = 99999
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_non_integer_end_frame_fails_closed():
    snap = make_test_d_snapshot()
    snap["end_frame"] = "86424"
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_boolean_end_frame_fails_closed():
    snap = make_test_d_snapshot()
    snap["end_frame"] = True
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap)


def test_test_d_end_frame_matching_run_bound_value_passes():
    snap = make_test_d_snapshot()
    snap["end_frame"] = 86424
    mod.validate_test_d_snapshot(snap, expected_end_frame=86424)


def test_test_d_end_frame_drift_from_run_bound_value_fails_closed():
    snap = make_test_d_snapshot()
    snap["end_frame"] = 86544
    with pytest.raises(mod.GateFailure):
        mod.validate_test_d_snapshot(snap, expected_end_frame=86424)


def test_empty_string_and_unchanged_empty_queue_is_rejected():
    outcome = mod.classify_queue_outcome("", [], [])
    assert outcome.classification == "rejected"


def test_false_and_unchanged_empty_queue_is_rejected():
    outcome = mod.classify_queue_outcome(False, [], [])
    assert outcome.classification == "rejected"


def test_empty_string_plus_one_identifiable_job_is_accepted():
    outcome = mod.classify_queue_outcome("", [], [{"JobId": "job-1"}])
    assert outcome.classification == "accepted"
    assert outcome.new_job_ids == ("job-1",)


def test_direct_id_plus_matching_queue_job_is_accepted():
    outcome = mod.classify_queue_outcome("job-1", [], [{"JobId": "job-1"}])
    assert outcome.classification == "accepted"


def test_direct_id_without_queue_observation_is_inconclusive():
    outcome = mod.classify_queue_outcome("job-1", [], [])
    assert outcome.classification == "inconclusive"


def test_conflicting_direct_and_observed_ids_is_inconclusive():
    outcome = mod.classify_queue_outcome("job-A", [], [{"JobId": "job-B"}])
    assert outcome.classification == "inconclusive"


def test_unidentified_after_item_is_inconclusive():
    outcome = mod.classify_queue_outcome("", [], [{"TimelineName": "test"}])
    assert outcome.classification == "inconclusive"


def test_nonempty_before_queue_is_inconclusive():
    outcome = mod.classify_queue_outcome("", [{"JobId": "old"}], [])
    assert outcome.classification == "inconclusive"


def test_static_exactly_one_add_render_job_call():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "AddRenderJob"
    ]
    assert len(calls) == 1


def test_static_no_prohibited_render_navigation_or_content_mutations():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    prohibited = {
        "StartRendering",
        "StopRendering",
        "DeleteRenderJob",
        "DeleteAllRenderJobs",
        "LoadProject",
        "SetCurrentTimeline",
        "ImportMedia",
        "AppendToTimeline",
        "CreateEmptyTimeline",
        "DeleteTimelines",
        "DeleteClips",
    }
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (attrs & prohibited)


def test_static_no_sqlite_import():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "sqlite3" not in imported


def test_davinci_import_is_confined_to_live_connection_function():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    import_parents = []
    for fn in [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        for child in ast.walk(fn):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name == "DaVinciResolveScript":
                        import_parents.append(fn.name)
    assert import_parents == ["connect_live_resolve"]


def test_authorization_carries_one_shot_boundaries_and_binds_commit_and_hashes():
    commit = "a" * 40
    script_sha = "b" * 64
    contract_sha = "c" * 64
    phrase = mod.build_required_authorization(
        expected_repository_commit=commit,
        expected_script_sha256=script_sha,
        expected_contract_sha256=contract_sha,
    )
    assert "one Phase 14 Test D" in phrase
    assert "No retry" in phrase
    assert "Production access" in phrase
    assert "rendering" in phrase
    assert "second submission" in phrase
    assert mod.CONTROL_PROJECT in phrase
    assert mod.CONTROL_TIMELINE in phrase
    assert commit in phrase
    assert script_sha in phrase
    assert contract_sha in phrase


def test_authorization_differs_when_any_bound_value_differs():
    base = mod.build_required_authorization(
        expected_repository_commit="a" * 40,
        expected_script_sha256="b" * 64,
        expected_contract_sha256="c" * 64,
    )
    different_commit = mod.build_required_authorization(
        expected_repository_commit="d" * 40,
        expected_script_sha256="b" * 64,
        expected_contract_sha256="c" * 64,
    )
    different_script = mod.build_required_authorization(
        expected_repository_commit="a" * 40,
        expected_script_sha256="e" * 64,
        expected_contract_sha256="c" * 64,
    )
    different_contract = mod.build_required_authorization(
        expected_repository_commit="a" * 40,
        expected_script_sha256="b" * 64,
        expected_contract_sha256="f" * 64,
    )
    assert base != different_commit
    assert base != different_script
    assert base != different_contract


def _enablement_gate_args(tmp_path, *, commit, script_sha, contract_sha, authorization):
    return [
        "--execute",
        "--expected-script-sha256",
        script_sha,
        "--contract-path",
        str(tmp_path / "contract.md"),
        "--expected-contract-sha256",
        contract_sha,
        "--expected-repository-commit",
        commit,
        "--authorization",
        authorization,
    ]


def _patch_non_contact_gates(monkeypatch):
    monkeypatch.setattr(mod, "validate_host_python", lambda: {"version": "3.11.9"})
    monkeypatch.setattr(mod, "validate_bound_files", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(mod, "repository_gate", lambda **kwargs: {"clean": True})


def test_non_execute_invocation_remains_strictly_non_contact(monkeypatch, tmp_path, capsys):
    _patch_non_contact_gates(monkeypatch)

    def forbidden_connect():
        raise AssertionError("non---execute invocations must never contact Resolve")

    monkeypatch.setattr(mod, "connect_live_resolve", forbidden_connect)
    monkeypatch.setattr(
        mod, "execute_test_d", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run"))
    )
    rc = mod.main(
        [
            "--expected-script-sha256",
            "0" * 64,
            "--contract-path",
            str(tmp_path / "contract.md"),
            "--expected-contract-sha256",
            "1" * 64,
            "--expected-repository-commit",
            "2" * 40,
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_enabled"] is True
    assert payload["resolve_contact"] is False
    assert payload["queue_mutation"] is False
    assert payload["dry_review_complete"] is True


def test_execute_missing_authorization_stops_before_resolve_connection(monkeypatch, tmp_path):
    _patch_non_contact_gates(monkeypatch)
    connect_calls: list[bool] = []
    monkeypatch.setattr(mod, "connect_live_resolve", lambda: connect_calls.append(True))
    rc = mod.main(
        _enablement_gate_args(
            tmp_path,
            commit="2" * 40,
            script_sha="0" * 64,
            contract_sha="1" * 64,
            authorization="",
        )
    )
    assert rc == mod.EXIT_GATE_FAILURE
    assert connect_calls == []


def test_execute_incorrect_authorization_stops_before_resolve_connection(monkeypatch, tmp_path):
    _patch_non_contact_gates(monkeypatch)
    connect_calls: list[bool] = []
    monkeypatch.setattr(mod, "connect_live_resolve", lambda: connect_calls.append(True))
    rc = mod.main(
        _enablement_gate_args(
            tmp_path,
            commit="2" * 40,
            script_sha="0" * 64,
            contract_sha="1" * 64,
            authorization="this is not the derived authorization text",
        )
    )
    assert rc == mod.EXIT_GATE_FAILURE
    assert connect_calls == []


def test_execute_authorization_bound_to_wrong_commit_fails_before_resolve_connection(
    monkeypatch, tmp_path
):
    _patch_non_contact_gates(monkeypatch)
    connect_calls: list[bool] = []
    monkeypatch.setattr(mod, "connect_live_resolve", lambda: connect_calls.append(True))
    script_sha = "0" * 64
    contract_sha = "1" * 64
    stale_authorization = mod.build_required_authorization(
        expected_repository_commit="9" * 40,  # not the invocation's commit below
        expected_script_sha256=script_sha,
        expected_contract_sha256=contract_sha,
    )
    rc = mod.main(
        _enablement_gate_args(
            tmp_path,
            commit="2" * 40,
            script_sha=script_sha,
            contract_sha=contract_sha,
            authorization=stale_authorization,
        )
    )
    assert rc == mod.EXIT_GATE_FAILURE
    assert connect_calls == []


def test_execute_authorization_bound_to_wrong_harness_hash_fails_before_resolve_connection(
    monkeypatch, tmp_path
):
    _patch_non_contact_gates(monkeypatch)
    connect_calls: list[bool] = []
    monkeypatch.setattr(mod, "connect_live_resolve", lambda: connect_calls.append(True))
    commit = "2" * 40
    contract_sha = "1" * 64
    stale_authorization = mod.build_required_authorization(
        expected_repository_commit=commit,
        expected_script_sha256="9" * 64,  # not the invocation's harness hash below
        expected_contract_sha256=contract_sha,
    )
    rc = mod.main(
        _enablement_gate_args(
            tmp_path,
            commit=commit,
            script_sha="0" * 64,
            contract_sha=contract_sha,
            authorization=stale_authorization,
        )
    )
    assert rc == mod.EXIT_GATE_FAILURE
    assert connect_calls == []


def test_execute_authorization_bound_to_wrong_contract_hash_fails_before_resolve_connection(
    monkeypatch, tmp_path
):
    _patch_non_contact_gates(monkeypatch)
    connect_calls: list[bool] = []
    monkeypatch.setattr(mod, "connect_live_resolve", lambda: connect_calls.append(True))
    commit = "2" * 40
    script_sha = "0" * 64
    stale_authorization = mod.build_required_authorization(
        expected_repository_commit=commit,
        expected_script_sha256=script_sha,
        expected_contract_sha256="9" * 64,  # not the invocation's contract hash below
    )
    rc = mod.main(
        _enablement_gate_args(
            tmp_path,
            commit=commit,
            script_sha=script_sha,
            contract_sha="1" * 64,
            authorization=stale_authorization,
        )
    )
    assert rc == mod.EXIT_GATE_FAILURE
    assert connect_calls == []


def test_execute_with_exact_correct_authorization_reaches_resolve_connection_and_executes_once(
    monkeypatch, tmp_path
):
    _patch_non_contact_gates(monkeypatch)
    commit = "2" * 40
    script_sha = "0" * 64
    contract_sha = "1" * 64

    connect_calls: list[bool] = []

    def fake_connect():
        connect_calls.append(True)
        return object()

    execute_calls: list[tuple[object, object]] = []

    def fake_execute_test_d(resolve, evidence):
        execute_calls.append((resolve, evidence))
        return {
            "outcome": {
                "classification": "accepted",
                "reason": "mocked",
                "direct_job_id": None,
                "new_job_ids": (),
            }
        }

    monkeypatch.setattr(mod, "connect_live_resolve", fake_connect)
    monkeypatch.setattr(mod, "execute_test_d", fake_execute_test_d)

    authorization = mod.build_required_authorization(
        expected_repository_commit=commit,
        expected_script_sha256=script_sha,
        expected_contract_sha256=contract_sha,
    )
    rc = mod.main(
        _enablement_gate_args(
            tmp_path,
            commit=commit,
            script_sha=script_sha,
            contract_sha=contract_sha,
            authorization=authorization,
        )
        + ["--evidence-root", str(tmp_path / "evidence")]
    )
    assert connect_calls == [True]
    assert len(execute_calls) == 1
    assert rc == mod.EXIT_ACCEPTED


class FakeMediaPoolItem:
    def __init__(self, name, unique_id):
        self.name = name
        self.unique_id = unique_id

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.unique_id


class FakeTimelineItem:
    def __init__(self, fingerprint):
        self.fp = fingerprint
        self.mpi = FakeMediaPoolItem(
            fingerprint["name"], fingerprint["media_pool_unique_id"]
        )

    def GetStart(self):
        return self.fp["start"]

    def GetEnd(self):
        return self.fp["end"]

    def GetDuration(self):
        return self.fp["duration"]

    def GetClipEnabled(self):
        return self.fp["enabled"]

    def GetMediaPoolItem(self):
        return self.mpi


class FakeTimeline:
    def __init__(self, name, settings, *, test_d=False, end_frame_values=None):
        self.name = name
        self.settings = settings
        self.test_d = test_d
        self.audio_item = FakeTimelineItem(mod.EXPECTED_CONTROL_AUDIO)
        # end_frame_values lets a test script a different GetEndFrame() result
        # on each successive call (one call per Test D snapshot), to exercise
        # r4 temporal end-frame stability. The last value repeats once the
        # list is exhausted. None preserves the original fixed-86424 behavior.
        self._end_frame_values = list(end_frame_values) if end_frame_values is not None else None
        self._end_frame_calls = 0

    def GetName(self):
        return self.name

    def GetSetting(self):
        return dict(self.settings)

    def GetMarkers(self):
        if self.name != mod.CONTROL_TIMELINE:
            return {}
        return {
            0: {
                "color": "Blue",
                "name": "Assembly Start",
                "note": "Live V1 marker A",
                "duration": 1,
                "customData": "",
            },
            48: {
                "color": "Yellow",
                "name": "Assembly Beat",
                "note": "Live V1 marker B",
                "duration": 1,
                "customData": "",
            },
        }

    def GetStartFrame(self):
        return 86400

    def GetEndFrame(self):
        if self.name != mod.CONTROL_TIMELINE:
            return 86400
        if self._end_frame_values is None:
            return 86424
        index = min(self._end_frame_calls, len(self._end_frame_values) - 1)
        self._end_frame_calls += 1
        return self._end_frame_values[index]

    def GetTrackCount(self, track_type):
        return 1 if self.name == mod.CONTROL_TIMELINE else 0

    def GetItemListInTrack(self, track_type, index):
        if self.name != mod.CONTROL_TIMELINE:
            return []
        assert index == 1
        if track_type == "audio":
            return [self.audio_item]
        return []


class FakeFolder:
    def __init__(self, name, clips=None, children=None):
        self.name = name
        self.clips = clips or []
        self.children = children or []

    def GetName(self):
        return self.name

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return list(self.children)


class FakeMediaPool:
    def __init__(self):
        by_folder = {}
        for folder_path, name, uid in mod.EXPECTED_MEDIA_POOL_INVENTORY:
            by_folder.setdefault(folder_path, []).append(FakeMediaPoolItem(name, uid))
        children = []
        for folder_path in [
            "Master/Redline OS Test",
            "Master/Redline OS Clip Placement Source",
            "Master/Redline OS Episode Assembly Test",
        ]:
            children.append(FakeFolder(folder_path.split("/")[-1], by_folder[folder_path]))
        self.root = FakeFolder("Master", [], children)

    def GetRootFolder(self):
        return self.root


class FakeProject:
    def __init__(
        self,
        settings,
        add_result="job-1",
        accept=True,
        *,
        render_format=None,
        render_codec=None,
        raise_on_add=False,
        end_frame_values=None,
    ):
        self.settings = settings
        self.timelines = [
            FakeTimeline("Redline OS Timeline Test", settings),
            FakeTimeline("Redline OS Clip Placement Test", settings),
            FakeTimeline("Redline OS Clip Placement Test 2", settings),
            FakeTimeline(
                mod.CONTROL_TIMELINE,
                settings,
                test_d=True,
                end_frame_values=end_frame_values,
            ),
        ]
        self.current = self.timelines[-1]
        self.media_pool = FakeMediaPool()
        self.add_result = add_result
        self.accept = accept
        self.add_calls = 0
        self.render_job_list_calls = 0
        self.after_add = False
        self.render_format = render_format or mod.EXPECTED_RENDER_FORMAT
        self.render_codec = render_codec or mod.EXPECTED_RENDER_CODEC
        self.raise_on_add = raise_on_add

    def GetName(self):
        return mod.CONTROL_PROJECT

    def GetCurrentTimeline(self):
        return self.current

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1]

    def GetSetting(self):
        return dict(self.settings)

    def GetMediaPool(self):
        return self.media_pool

    def GetRenderJobList(self):
        self.render_job_list_calls += 1
        if self.after_add and self.accept:
            return [{"JobId": "job-1", "TimelineName": mod.CONTROL_TIMELINE}]
        return []

    def IsRenderingInProgress(self):
        return False

    def GetRenderPresetList(self):
        return [mod.PRESET_NAME]

    def LoadRenderPreset(self, name):
        return name == mod.PRESET_NAME

    def SetRenderSettings(self, settings):
        return settings == {
            "TargetDir": str(mod.TARGET_DIRECTORY),
            "CustomName": mod.CUSTOM_NAME,
        }

    def GetCurrentRenderFormatAndCodec(self):
        return {"format": self.render_format, "codec": self.render_codec}

    def AddRenderJob(self):
        self.add_calls += 1
        if self.raise_on_add:
            raise RuntimeError("synthetic AddRenderJob failure")
        self.after_add = True
        return self.add_result


class FakeProjectManager:
    def __init__(self, project):
        self.project = project

    def GetCurrentProject(self):
        return self.project


class FakeResolve:
    def __init__(self, project):
        self.manager = FakeProjectManager(project)

    def GetProjectManager(self):
        return self.manager

    def GetProductName(self):
        return "DaVinci Resolve Studio"

    def GetVersionString(self):
        return mod.EXPECTED_RESOLVE_VERSION


def test_execute_test_d_mock_acceptance_calls_add_once(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    project = FakeProject(settings)
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    assert result["outcome"]["classification"] == "accepted"
    assert result["after_queue"]["count"] == 1
    assert result["rendering_after"] is False
    assert result["post_errors"] == []


def test_render_context_exact_expected_values_pass():
    project = type(
        "P",
        (),
        {
            "GetCurrentRenderFormatAndCodec": lambda self: {
                "format": mod.EXPECTED_RENDER_FORMAT,
                "codec": mod.EXPECTED_RENDER_CODEC,
            }
        },
    )()
    assert mod.validate_render_context(project) == {
        "format": mod.EXPECTED_RENDER_FORMAT,
        "codec": mod.EXPECTED_RENDER_CODEC,
    }


def test_render_context_wrong_format_fails_closed():
    project = type(
        "P",
        (),
        {
            "GetCurrentRenderFormatAndCodec": lambda self: {
                "format": "mp4",
                "codec": mod.EXPECTED_RENDER_CODEC,
            }
        },
    )()
    with pytest.raises(mod.GateFailure):
        mod.validate_render_context(project)


def test_render_context_wrong_codec_fails_closed():
    project = type(
        "P",
        (),
        {
            "GetCurrentRenderFormatAndCodec": lambda self: {
                "format": mod.EXPECTED_RENDER_FORMAT,
                "codec": "unexpected",
            }
        },
    )()
    with pytest.raises(mod.GateFailure):
        mod.validate_render_context(project)


def test_render_context_unavailable_fails_closed():
    with pytest.raises(mod.GateFailure):
        mod.validate_render_context(object())


def test_render_context_non_dict_fails_closed():
    project = type(
        "P",
        (),
        {"GetCurrentRenderFormatAndCodec": lambda self: ("mov", "DNxHRHQX_10")},
    )()
    with pytest.raises(mod.GateFailure):
        mod.validate_render_context(project)


def test_render_context_accessor_exception_stops_before_queue_logic():
    def boom(self):
        raise RuntimeError("synthetic render-context failure")

    project = type("P", (), {"GetCurrentRenderFormatAndCodec": boom})()
    with pytest.raises(RuntimeError, match="synthetic render-context failure"):
        mod.validate_render_context(project)


def test_execute_render_context_mismatch_prevents_add(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    project = FakeProject(settings, render_codec="unexpected")
    with pytest.raises(mod.GateFailure):
        mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 0
    assert not (evidence.root / "pre_add_evidence.json").exists()


def test_pre_add_evidence_exists_before_single_add(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    project = FakeProject(settings)
    original_add = project.AddRenderJob

    def checked_add():
        assert (evidence.root / "pre_add_evidence.json").is_file()
        payload = (evidence.root / "pre_add_evidence.json").read_text(encoding="utf-8")
        assert '"queue_mutation_started": false' in payload
        return original_add()

    project.AddRenderJob = checked_add
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert result["outcome"]["classification"] == "accepted"
    assert (evidence.root / "add_render_job_result.json").is_file()
    assert (evidence.root / "post_add_evidence.json").is_file()


def test_pre_add_evidence_write_failure_prevents_add(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    real_write = evidence.write_json

    def fail_pre_add(name, value):
        if name == "pre_add_evidence.json":
            raise OSError("synthetic evidence failure")
        return real_write(name, value)

    evidence.write_json = fail_pre_add
    project = FakeProject(settings)
    with pytest.raises(OSError):
        mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 0


def test_add_exception_preserves_pre_add_evidence(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    project = FakeProject(settings, raise_on_add=True)
    with pytest.raises(RuntimeError, match="synthetic AddRenderJob failure"):
        mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    assert (evidence.root / "pre_add_evidence.json").is_file()
    assert not (evidence.root / "add_render_job_result.json").exists()


def test_add_result_evidence_write_failure_still_observes_queue(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    real_write = evidence.write_json

    def fail_direct_result(name, value):
        if name == "add_render_job_result.json":
            raise OSError("synthetic direct-result evidence failure")
        return real_write(name, value)

    evidence.write_json = fail_direct_result
    project = FakeProject(settings)
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    # Three pre-add queue reads plus at least one post-add read prove the
    # persistence failure did not suppress post-call observation.
    assert project.render_job_list_calls >= 4
    assert result["after_queue"]["count"] == 1
    assert result["rendering_after"] is False
    assert isinstance(result["post_identity"], dict)
    assert isinstance(result["post_timeline_snapshot"], dict)
    assert isinstance(result["post_media_pool_inventory"], list)
    assert result["outcome"]["classification"] == "inconclusive"
    assert result["evidence_errors"][0]["phase"] == "add_render_job_result_write"
    assert result["add_render_job_result_sha256"] is None
    assert (evidence.root / "pre_add_evidence.json").is_file()
    assert not (evidence.root / "add_render_job_result.json").exists()
    assert (evidence.root / "post_add_evidence.json").is_file()


def test_post_add_evidence_write_failure_returns_observed_inconclusive_result(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    real_write = evidence.write_json

    def fail_post_add(name, value):
        if name == "post_add_evidence.json":
            raise OSError("synthetic post-add evidence failure")
        return real_write(name, value)

    evidence.write_json = fail_post_add
    project = FakeProject(settings)
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    assert project.render_job_list_calls >= 4
    assert result["after_queue"]["count"] == 1
    assert result["rendering_after"] is False
    assert isinstance(result["post_identity"], dict)
    assert isinstance(result["post_timeline_snapshot"], dict)
    assert isinstance(result["post_media_pool_inventory"], list)
    assert result["outcome"]["classification"] == "inconclusive"
    assert result["evidence_errors"][-1]["phase"] == "post_add_evidence_write"
    assert result["post_add_evidence_sha256"] is None
    assert (evidence.root / "add_render_job_result.json").is_file()
    assert not (evidence.root / "post_add_evidence.json").exists()


def _end_frame_stability_project(settings, end_frame_values, **kwargs):
    return FakeProject(settings, end_frame_values=end_frame_values, **kwargs)


def test_end_frame_drift_at_pre_render_context_fails_closed_with_no_add(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    # initial snapshot binds 86424; the very next (pre-render-context)
    # snapshot reports 86544, an otherwise-valid but temporally unstable value.
    project = _end_frame_stability_project(settings, [86424, 86544])
    with pytest.raises(mod.GateFailure):
        mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 0
    assert not (evidence.root / "pre_add_evidence.json").exists()


def test_end_frame_drift_at_final_guard_fails_closed_with_no_add(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    # initial and pre-render-context snapshots both report 86424; the final
    # pre-add guard (immediately before AddRenderJob()) reports 86544.
    project = _end_frame_stability_project(settings, [86424, 86424, 86544])
    with pytest.raises(mod.GateFailure):
        mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 0
    assert not (evidence.root / "pre_add_evidence.json").exists()


def test_post_add_end_frame_drift_forces_inconclusive_without_retry(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    # All three pre-add snapshots stay stable at 86424; only the post-call
    # observation (after the sole AddRenderJob() call) reports the drift.
    project = _end_frame_stability_project(settings, [86424, 86424, 86424, 86544])
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    assert result["outcome"]["classification"] == "inconclusive"
    assert isinstance(result["post_timeline_snapshot"], dict)
    assert result["post_timeline_snapshot"]["end_frame"] == 86544
    assert any(err["phase"] == "post_timeline" for err in result["post_errors"])
    assert (evidence.root / "pre_add_evidence.json").is_file()
    assert (evidence.root / "post_add_evidence.json").is_file()


def test_stable_86424_end_frame_remains_valid_through_experiment(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    project = _end_frame_stability_project(settings, [86424, 86424, 86424, 86424])
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    assert result["outcome"]["classification"] == "accepted"
    assert result["initial_end_frame"] == 86424


def test_stable_86544_end_frame_remains_valid_through_experiment(monkeypatch, tmp_path):
    settings = {"timelineFrameRate": 24.0}
    digest = mod._canonical_sha256(settings)
    monkeypatch.setattr(mod, "EXPECTED_CONTROL_SETTINGS_SHA256", digest)
    monkeypatch.setattr(
        mod,
        "validate_target_directory",
        lambda: {"path": str(mod.TARGET_DIRECTORY), "collisions": []},
    )
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    project = _end_frame_stability_project(settings, [86544, 86544, 86544, 86544])
    result = mod.execute_test_d(FakeResolve(project), evidence)
    assert project.add_calls == 1
    assert result["outcome"]["classification"] == "accepted"
    assert result["initial_end_frame"] == 86544


def test_durable_evidence_writer_uses_fsync_and_atomic_replace(monkeypatch, tmp_path):
    evidence = mod.EvidencePackage(tmp_path / "evidence")
    fsync_calls = []
    replace_calls = []
    real_fsync = mod.os.fsync
    real_replace = mod.os.replace

    def recording_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    def recording_replace(src, dst):
        replace_calls.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "fsync", recording_fsync)
    monkeypatch.setattr(mod.os, "replace", recording_replace)
    path = evidence.write_json("checkpoint.json", {"ok": True})
    assert path.is_file()
    assert fsync_calls
    assert len(replace_calls) == 1
    assert replace_calls[0][1] == path


def test_dynamic_getattr_method_names_are_read_only_or_reviewed_mutations():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    method_names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
            continue
        value = node.args[1].value
        if isinstance(value, str) and value[:1].isupper():
            method_names.add(value)
    assert method_names <= {
        "GetName",
        "GetUniqueId",
        "GetProjectManager",
        "GetCurrentProject",
        "GetCurrentTimeline",
        "GetProductName",
        "GetVersionString",
        "GetVersion",
        "GetRenderJobList",
        "IsRenderingInProgress",
        "GetRenderPresetList",
        "GetMediaPool",
        "GetRootFolder",
        "GetClipList",
        "GetSubFolderList",
        "GetSetting",
        "GetTimelineCount",
        "GetTimelineByIndex",
        "GetCurrentRenderFormatAndCodec",
        "LoadRenderPreset",
        "SetRenderSettings",
        "AddRenderJob",
    }
