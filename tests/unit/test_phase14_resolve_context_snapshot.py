from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

REVIEW_ROOT = Path(__file__).resolve().parents[2]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts import phase14_resolve_context_snapshot as probe


class ExplodingRepr:
    def __repr__(self) -> str:
        raise AssertionError("repr must not be called")


class FakeMediaPoolItem:
    def __init__(self, name: str = "clip.mov", media_id: str = "media-1", unique_id: str = "unique-media-1"):
        self.name = name
        self.media_id = media_id
        self.unique_id = unique_id

    def GetName(self):
        return self.name

    def GetMediaId(self):
        return self.media_id

    def GetUniqueId(self):
        return self.unique_id

    def GetClipProperty(self):
        return {
            "Clip Name": self.name,
            "Type": "Video",
            "File Path": f"C:/media/{self.name}",
            "Duration": "120",
            "FPS": "24",
            "Resolution": "1920x1080",
            "Video Codec": "H.264",
        }


class FakeTimelineItem:
    def __init__(self, source: FakeMediaPoolItem | None = None, unique_id: str = "timeline-item-1"):
        self.source = source or FakeMediaPoolItem()
        self.unique_id = unique_id

    def GetName(self):
        return self.source.name

    def GetUniqueId(self):
        return self.unique_id

    def GetStart(self):
        return 0

    def GetEnd(self):
        return 120

    def GetDuration(self):
        return 120

    def GetLeftOffset(self):
        return 0

    def GetRightOffset(self):
        return 0

    def GetSourceStartFrame(self):
        return 0

    def GetSourceEndFrame(self):
        return 119

    def GetClipEnabled(self):
        return True

    def GetMediaPoolItem(self):
        return self.source


class FakeFolder:
    def __init__(self, name: str, clips=None, subfolders=None):
        self.name = name
        self.clips = list(clips or [])
        self.subfolders = list(subfolders or [])

    def GetName(self):
        return self.name

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return list(self.subfolders)


class FakeMediaPool:
    def __init__(self, root: FakeFolder):
        self.root = root

    def GetRootFolder(self):
        return self.root


class FakeTimeline:
    def __init__(self, name: str, unique_id: str, *, item: FakeTimelineItem | None = None):
        self.name = name
        self.unique_id = unique_id
        self.item = item or FakeTimelineItem(unique_id=f"{unique_id}-item")

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.unique_id

    def GetStartFrame(self):
        return 0

    def GetEndFrame(self):
        return 120

    def GetStartTimecode(self):
        return "01:00:00:00"

    def GetSetting(self):
        return {
            "timelineFrameRate": "24",
            "timelineResolutionWidth": "1920",
            "timelineResolutionHeight": "1080",
        }

    def GetMarkers(self):
        return {}

    def GetTrackCount(self, track_type: str):
        if track_type == "video":
            return 1
        if track_type in {"audio", "subtitle"}:
            return 0
        raise AssertionError(track_type)

    def GetItemListInTrack(self, track_type: str, track_index: int):
        assert track_type == "video"
        assert track_index == 1
        return [self.item]


class FakeProject:
    def __init__(
        self,
        name: str,
        timelines: list[FakeTimeline],
        *,
        current: FakeTimeline | None = None,
        rendering=False,
        queue=None,
        timeline_counts: list[int] | None = None,
        root: FakeFolder | None = None,
    ):
        self.name = name
        self.timelines = timelines
        self.current = current or timelines[0]
        self.rendering = rendering
        self.queue = [] if queue is None else queue
        self.timeline_counts = list(timeline_counts or [])
        self.timeline_count_calls = 0
        self.media_pool = FakeMediaPool(root or FakeFolder("Root", clips=[FakeMediaPoolItem()]))

    def GetName(self):
        return self.name

    def GetTimelineCount(self):
        self.timeline_count_calls += 1
        if self.timeline_counts:
            index = min(self.timeline_count_calls - 1, len(self.timeline_counts) - 1)
            return self.timeline_counts[index]
        return len(self.timelines)

    def GetTimelineByIndex(self, index: int):
        return self.timelines[index - 1]

    def GetCurrentTimeline(self):
        return self.current

    def GetMediaPool(self):
        return self.media_pool

    def GetSetting(self):
        return {
            "timelineFrameRate": "24",
            "timelineResolutionWidth": "1920",
            "timelineResolutionHeight": "1080",
            "colorScienceMode": "davinciYRGBColorManagedv2",
        }

    def IsRenderingInProgress(self):
        return self.rendering

    def GetRenderJobList(self):
        return self.queue

    def GetRenderPresetList(self):
        return ["YouTube - 720p", "Redline Broadcast Master"]

    def GetCurrentRenderFormatAndCodec(self):
        return {"format": "mov", "codec": "DNxHRHQX_10"}

    def GetCurrentRenderMode(self):
        return 0

    def GetRenderSettings(self):
        return {"TargetDir": "C:/output", "CustomName": "example"}


class FakeProjectManager:
    def __init__(self, project: FakeProject):
        self.project = project

    def GetCurrentProject(self):
        return self.project

    def GetProjectListInCurrentFolder(self):
        return ["redline-os-test-duplicate", "RLC-E9001_MASTER"]

    def GetProjectAttributesInCurrentFolder(self):
        return {
            "redline-os-test-duplicate": {"LastModified": "2026-08-04"},
            "RLC-E9001_MASTER": {"LastModified": "2026-08-04"},
        }


class FakeResolve:
    def __init__(self, project: FakeProject):
        self.manager = FakeProjectManager(project)

    def GetProductName(self):
        return "DaVinci Resolve Studio"

    def GetVersion(self):
        return [21, 0, 3, 7, ""]

    def GetVersionString(self):
        return "21.0.3.7"

    def GetProjectManager(self):
        return self.manager


def valid_resolve(project_name: str = "RLC-E9001_MASTER", timeline_name: str = "RLC-E9001_TIMELINE"):
    timeline = FakeTimeline(timeline_name, "timeline-1")
    project = FakeProject(project_name, [timeline])
    return FakeResolve(project)


def valid_snapshot(project: str, timeline: str, *, setting_value="24", render_codec="DNxHRHQX_10"):
    observed_version = {
        "source_method": "GetVersionString",
        "status": "observed",
        "value_type": "str",
        "value": "21.0.3.7",
        "error": None,
    }
    observed_setting = {
        "source_method": "GetSetting",
        "status": "observed",
        "value_type": "dict",
        "value": {"timelineFrameRate": setting_value},
        "error": None,
    }
    observed_render = {
        "source_method": "GetCurrentRenderFormatAndCodec",
        "status": "observed",
        "value_type": "dict",
        "value": {"format": "mov", "codec": render_codec},
        "error": None,
    }
    return {
        "schema_version": probe.SCHEMA_VERSION,
        "mission": probe.MISSION,
        "captured_at": "2026-08-04T00:00:00Z",
        "snapshot_complete": True,
        "expected_context": {"project": project, "timeline": timeline},
        "session": {
            "product_name": {**observed_version, "source_method": "GetProductName", "value": "DaVinci Resolve Studio"},
            "version": {
                **observed_version,
                "source_method": "GetVersion",
                "value_type": "list",
                "value": [21, 0, 3, 7, ""],
            },
            "version_string": observed_version,
        },
        "project_manager": {},
        "project": {
            "name": project,
            "settings": observed_setting,
            "current_render_context": {"format_and_codec": observed_render},
            "render_presets": {
                "source_method": "GetRenderPresetList",
                "status": "observed",
                "value_type": "list",
                "value": ["Redline Broadcast Master"],
                "error": None,
            },
            "render_queue": {"count": 0, "items": []},
        },
        "target_timeline": {"name": timeline},
        "media_pool": {"name": "Root", "clips": [], "subfolders": []},
        "pre_guard": {"project_name": project, "current_timeline_name": timeline},
        "post_guard": {"project_name": project, "current_timeline_name": timeline},
    }


def test_module_import_does_not_import_resolve_module():
    assert "DaVinciResolveScript" not in sys.modules
    assert probe.SNAPSHOT_EXECUTION_ENABLED is False


def test_snapshot_cli_stops_before_connection(monkeypatch, capsys, tmp_path):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(probe, "connect_resolve_read_only", forbidden_connect)
    result = probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(tmp_path / "snapshot.json"),
        ]
    )

    assert result == 2
    assert "live_execution_disabled" in capsys.readouterr().err
    assert not (tmp_path / "snapshot.json").exists()


def test_valid_mock_snapshot_is_complete():
    snapshot = probe.collect_snapshot(
        valid_resolve(),
        probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
    )

    assert snapshot["snapshot_complete"] is True
    assert snapshot["project"]["name"] == "RLC-E9001_MASTER"
    assert snapshot["target_timeline"]["name"] == "RLC-E9001_TIMELINE"
    assert snapshot["project"]["render_queue"]["count"] == 0
    assert snapshot["pre_guard"] == snapshot["post_guard"]
    assert snapshot["media_pool"]["clips"][0]["media_id"]["value"] == "media-1"


def test_wrong_project_fails_closed():
    with pytest.raises(probe.SnapshotError, match="does not match") as error:
        probe.collect_snapshot(
            valid_resolve(project_name="wrong-project"),
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "project_identity_mismatch"


def test_duplicate_exact_timeline_fails_closed():
    one = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    two = FakeTimeline("RLC-E9001_TIMELINE", "timeline-2")
    resolve = FakeResolve(FakeProject("RLC-E9001_MASTER", [one, two], current=one))

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            resolve,
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "duplicate_expected_timeline"


def test_current_timeline_mismatch_fails_closed():
    expected = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    other = FakeTimeline("OTHER", "timeline-2")
    resolve = FakeResolve(FakeProject("RLC-E9001_MASTER", [expected, other], current=other))

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            resolve,
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "current_timeline_mismatch"


def test_active_rendering_fails_closed():
    timeline = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    resolve = FakeResolve(FakeProject("RLC-E9001_MASTER", [timeline], rendering=True))

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            resolve,
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "rendering_active"


def test_nonempty_queue_fails_closed_without_logging_values():
    timeline = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    queue = [{"JobId": "job-1", "TargetDir": "C:/private", "CustomName": "secret"}]
    resolve = FakeResolve(FakeProject("RLC-E9001_MASTER", [timeline], queue=queue))

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            resolve,
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "render_queue_not_empty"
    assert "C:/private" not in repr(error.value.details)
    assert "secret" not in repr(error.value.details)


def test_boolean_timeline_count_fails_closed():
    timeline = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    resolve = FakeResolve(
        FakeProject("RLC-E9001_MASTER", [timeline], timeline_counts=[True])
    )

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            resolve,
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "invalid_count"


def test_repeated_media_pool_folder_handle_fails_closed():
    root = FakeFolder("Root")
    root.subfolders.append(root)
    timeline = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    resolve = FakeResolve(FakeProject("RLC-E9001_MASTER", [timeline], root=root))

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            resolve,
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "repeated_media_pool_folder_handle"
    assert error.value.details["first_path"] == ["Root"]
    assert error.value.details["repeated_path"] == ["Root", "Root"]


def test_identity_drift_fails_closed():
    timeline = FakeTimeline("RLC-E9001_TIMELINE", "timeline-1")
    # Calls: timeline enumeration, pre-guard, post-guard.
    project = FakeProject(
        "RLC-E9001_MASTER",
        [timeline],
        timeline_counts=[1, 1, 2],
    )

    with pytest.raises(probe.SnapshotError) as error:
        probe.collect_snapshot(
            FakeResolve(project),
            probe.SnapshotContext("RLC-E9001_MASTER", "RLC-E9001_TIMELINE"),
        )
    assert error.value.code == "snapshot_identity_drift"


def test_unknown_bridge_value_is_rejected_without_repr():
    with pytest.raises(probe.UnsupportedEvidenceType, match="unsupported evidence type"):
        probe.normalize_json_value(ExplodingRepr())


def test_cyclic_evidence_container_is_rejected():
    value = []
    value.append(value)
    with pytest.raises(probe.UnsupportedEvidenceType, match="cyclic evidence"):
        probe.normalize_json_value(value)


def test_optional_missing_accessor_is_unavailable_not_error():
    observation = probe.observe_optional(object(), "GetVersionString")
    assert observation["status"] == "unavailable"
    assert observation["error"]["type"] == "AccessorUnavailable"


def test_queue_inventory_sanitizes_values():
    inventory = probe.queue_inventory(
        [{"JobId": "job-1", "TargetDir": "C:/private", "CustomName": "secret"}]
    )
    assert inventory["count"] == 1
    assert inventory["items"][0]["job_id"] == "job-1"
    assert "TargetDir" in inventory["items"][0]["keys"]
    assert "C:/private" not in repr(inventory)
    assert "secret" not in repr(inventory)


def test_comparison_classifies_intrinsic_and_context_sensitive_differences():
    control = valid_snapshot("redline-os-test-duplicate", "RLO-LIVE-ASM-92701_TIMELINE")
    production = valid_snapshot(
        "RLC-E9001_MASTER",
        "RLC-E9001_TIMELINE",
        setting_value="23.976",
        render_codec="H264",
    )

    comparison = probe.compare_snapshots(control, production)
    by_path = {record["path"]: record["classification"] for record in comparison["records"]}

    assert comparison["comparison_complete"] is True
    assert by_path["/project/settings"] == "different"
    assert by_path["/project/current_render_context/format_and_codec"] == "context_sensitive"
    assert comparison["overall_classification"] == "differences_observed"


def test_comparison_classifies_unavailable_values():
    control = valid_snapshot("control", "control-timeline")
    production = valid_snapshot("production", "production-timeline")
    control["project"]["settings"] = {
        "source_method": "GetSetting",
        "status": "unavailable",
        "value_type": None,
        "value": None,
        "error": {"type": "AccessorUnavailable"},
    }

    comparison = probe.compare_snapshots(control, production)
    by_path = {record["path"]: record["classification"] for record in comparison["records"]}
    assert by_path["/project/settings"] == "unavailable_on_control"


def test_version_mismatch_makes_comparison_incomparable():
    control = valid_snapshot("control", "control-timeline")
    production = valid_snapshot("production", "production-timeline")
    production["session"]["version_string"]["value"] = "21.1.0"

    comparison = probe.compare_snapshots(control, production)
    assert comparison["comparison_complete"] is False
    assert comparison["overall_classification"] == "incomparable"


def test_incomplete_snapshot_is_rejected():
    control = valid_snapshot("control", "control-timeline")
    production = valid_snapshot("production", "production-timeline")
    production["snapshot_complete"] = False

    with pytest.raises(probe.SnapshotError) as error:
        probe.compare_snapshots(control, production)
    assert error.value.code == "incomplete_snapshot"


def test_offline_compare_command_writes_json_without_resolve_import(monkeypatch, tmp_path):
    def forbidden_import(name: str):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(probe.importlib, "import_module", forbidden_import)
    control_path = tmp_path / "control.json"
    production_path = tmp_path / "production.json"
    output_path = tmp_path / "comparison.json"
    control_path.write_text(json.dumps(valid_snapshot("control", "control-timeline")), encoding="utf-8")
    production_path.write_text(json.dumps(valid_snapshot("production", "production-timeline")), encoding="utf-8")

    result = probe.main(
        [
            "compare",
            "--control",
            str(control_path),
            "--production",
            str(production_path),
            "--output",
            str(output_path),
        ]
    )

    assert result == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["comparison_complete"] is True


def test_source_has_no_direct_resolve_import_or_prohibited_method_calls():
    source_path = Path(probe.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_names = set()
    called_attributes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)

    assert "DaVinciResolveScript" not in imported_names
    assert called_attributes.isdisjoint(probe.PROHIBITED_RESOLVE_METHODS)


def test_allowlist_contains_no_prohibited_method():
    assert probe.READ_ONLY_RESOLVE_METHODS.isdisjoint(probe.PROHIBITED_RESOLVE_METHODS)


def test_print_sha256_does_not_connect(monkeypatch, capsys):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(probe, "connect_resolve_read_only", forbidden_connect)
    assert probe.main(["--print-sha256"]) == 0
    output = capsys.readouterr().out.strip()
    assert len(output) == 64
    assert all(character in "0123456789abcdef" for character in output)
