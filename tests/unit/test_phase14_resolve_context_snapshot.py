from __future__ import annotations

import ast
import base64
import copy
import io
import json
import os
import re
import shutil
import subprocess
import textwrap
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
    assert isinstance(probe.EXECUTION_REVISION_ID, str) and probe.EXECUTION_REVISION_ID
    assert probe.EXECUTION_REVISION_ID_PATTERN.fullmatch(probe.EXECUTION_REVISION_ID)


def test_snapshot_cli_stops_before_connection_when_authorization_missing(monkeypatch, capsys, tmp_path):
    """Formerly test_snapshot_cli_stops_before_connection.

    Updated for Phase 14.1: the flat SNAPSHOT_EXECUTION_ENABLED disable was
    replaced by the execution interlock, so the stop code is now
    live_execution_authorization_missing rather than live_execution_disabled.
    Coverage (CLI stops before connection with no output written) is preserved.
    """

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
    assert "live_execution_authorization_missing" in capsys.readouterr().err
    assert not (tmp_path / "snapshot.json").exists()


def test_incorrect_authorization_format_stops_before_connection(monkeypatch, capsys, tmp_path):
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
            "--execution-authorization",
            "not a well formed revision id!!",
        ]
    )

    assert result == 2
    assert "live_execution_authorization_invalid" in capsys.readouterr().err
    assert not (tmp_path / "snapshot.json").exists()


def test_authorization_revision_mismatch_stops_before_connection(monkeypatch, capsys, tmp_path):
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
            "--execution-authorization",
            "phase14.1-a-well-formed-but-wrong-revision-id",
        ]
    )

    assert result == 2
    assert "live_execution_revision_mismatch" in capsys.readouterr().err
    assert not (tmp_path / "snapshot.json").exists()


def test_correct_authorization_reaches_connection_boundary(monkeypatch, tmp_path):
    connect_calls = []

    def stub_connect(*args, **kwargs):
        connect_calls.append(True)
        return valid_resolve()

    monkeypatch.setattr(probe, "connect_resolve_read_only", stub_connect)
    output_path = tmp_path / "snapshot.json"
    result = probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(output_path),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )

    assert connect_calls == [True]
    assert result == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["snapshot_complete"] is True


def test_existing_snapshot_output_stops_before_connection(monkeypatch, capsys, tmp_path):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(probe, "connect_resolve_read_only", forbidden_connect)
    output_path = tmp_path / "snapshot.json"
    output_path.write_text('{"already": "here"}', encoding="utf-8")

    result = probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(output_path),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )

    assert result == 2
    assert "output_path_already_exists" in capsys.readouterr().err
    assert output_path.read_text(encoding="utf-8") == '{"already": "here"}'


def test_output_path_is_existing_directory_is_rejected(monkeypatch, capsys, tmp_path):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(probe, "connect_resolve_read_only", forbidden_connect)
    output_path = tmp_path / "snapshot.json"
    output_path.mkdir()

    result = probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(output_path),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )

    assert result == 2
    assert "output_path_is_directory" in capsys.readouterr().err


def test_failed_snapshot_leaves_no_final_output_and_no_temp_file(monkeypatch, tmp_path):
    def stub_connect(*args, **kwargs):
        return valid_resolve(project_name="wrong-project")

    monkeypatch.setattr(probe, "connect_resolve_read_only", stub_connect)
    output_path = tmp_path / "snapshot.json"

    result = probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(output_path),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )

    assert result == 2
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_serialization_failure_occurs_before_any_disk_write(monkeypatch, tmp_path):
    """Formerly misnamed test_temp_file_removed_after_controlled_write_failure.

    This does not prove post-creation temp-file cleanup: json.dumps() is
    called before validate_output_path() or tempfile.mkstemp(), so no temp
    file is ever created in this scenario -- there is nothing to clean up.
    Real post-creation cleanup is proven by
    test_write_failure_is_structured_and_leaves_no_final_output,
    test_publish_failure_is_structured_and_removes_temp, and
    test_temp_cleanup_failure_is_surfaced_not_swallowed below.
    """
    output_path = tmp_path / "snapshot.json"

    def exploding_dumps(*args, **kwargs):
        raise ValueError("simulated serialization failure")

    monkeypatch.setattr(probe.json, "dumps", exploding_dumps)

    with pytest.raises(ValueError):
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_authorization_leading_whitespace_is_rejected():
    with pytest.raises(probe.SnapshotError) as error:
        probe.enforce_execution_interlock(" " + probe.EXECUTION_REVISION_ID)
    assert error.value.code == "live_execution_authorization_invalid"


def test_authorization_trailing_whitespace_is_rejected():
    with pytest.raises(probe.SnapshotError) as error:
        probe.enforce_execution_interlock(probe.EXECUTION_REVISION_ID + " ")
    assert error.value.code == "live_execution_authorization_invalid"


def test_authorization_whitespace_only_is_rejected():
    with pytest.raises(probe.SnapshotError) as error:
        probe.enforce_execution_interlock("   ")
    assert error.value.code == "live_execution_authorization_invalid"


def test_forced_temp_name_collision_cannot_overwrite_existing_file(monkeypatch, tmp_path):
    output_path = tmp_path / "snapshot.json"

    def colliding_mkstemp(*args, **kwargs):
        raise FileExistsError("simulated exhausted temp-name retries")

    monkeypatch.setattr(probe.tempfile, "mkstemp", colliding_mkstemp)

    with pytest.raises(probe.SnapshotError) as error:
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert error.value.code == "output_temp_create_failed"
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_generic_temp_creation_failure_is_structured(monkeypatch, tmp_path):
    output_path = tmp_path / "snapshot.json"

    def failing_mkstemp(*args, **kwargs):
        raise PermissionError("simulated permission failure")

    monkeypatch.setattr(probe.tempfile, "mkstemp", failing_mkstemp)

    with pytest.raises(probe.SnapshotError) as error:
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert error.value.code == "output_temp_create_failed"
    assert error.value.details["error_type"] == "PermissionError"
    assert not output_path.exists()


def test_write_failure_is_structured_and_leaves_no_final_output(monkeypatch, tmp_path):
    output_path = tmp_path / "snapshot.json"

    def failing_fsync(*args, **kwargs):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(probe.os, "fsync", failing_fsync)

    with pytest.raises(probe.SnapshotError) as error:
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert error.value.code == "output_write_failed"
    assert error.value.details["published"] is False
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_publish_failure_is_structured_and_removes_temp(monkeypatch, tmp_path):
    output_path = tmp_path / "snapshot.json"

    def failing_link(*args, **kwargs):
        raise OSError("simulated cross-device link failure")

    monkeypatch.setattr(probe.os, "link", failing_link)

    with pytest.raises(probe.SnapshotError) as error:
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert error.value.code == "output_publish_failed"
    assert error.value.details["published"] is False
    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_destination_created_during_publication_race_preserves_destination(monkeypatch, tmp_path):
    output_path = tmp_path / "snapshot.json"
    raced_content = "raced-in-content"

    def racing_link(src, dst, *args, **kwargs):
        Path(dst).write_text(raced_content, encoding="utf-8")
        raise FileExistsError("simulated race: destination created after pre-flight check")

    monkeypatch.setattr(probe.os, "link", racing_link)

    with pytest.raises(probe.SnapshotError) as error:
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert error.value.code == "output_path_already_exists"
    assert output_path.read_text(encoding="utf-8") == raced_content


def test_temp_cleanup_failure_is_surfaced_not_swallowed(monkeypatch, tmp_path):
    output_path = tmp_path / "snapshot.json"

    def failing_unlink(self, *args, **kwargs):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(probe.Path, "unlink", failing_unlink)

    with pytest.raises(probe.SnapshotError) as error:
        probe.write_json_no_overwrite(output_path, {"ok": True})

    assert error.value.code == "output_temp_cleanup_failed"
    # Publication had already succeeded when cleanup failed: the completed
    # final output must be preserved, and success must not be reported.
    assert error.value.details["published"] is True
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == {"ok": True}


def test_main_returns_documented_exit_code_for_output_write_failure(monkeypatch, capsys, tmp_path):
    def stub_connect(*args, **kwargs):
        return valid_resolve()

    monkeypatch.setattr(probe, "connect_resolve_read_only", stub_connect)

    def failing_fsync(*args, **kwargs):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(probe.os, "fsync", failing_fsync)
    output_path = tmp_path / "snapshot.json"

    result = probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(output_path),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )

    assert result == 2
    assert "output_write_failed" in capsys.readouterr().err
    assert not output_path.exists()


def test_successful_write_produces_exactly_one_final_json_file(tmp_path):
    output_path = tmp_path / "snapshot.json"
    probe.write_json_no_overwrite(output_path, {"ok": True})

    entries = list(tmp_path.iterdir())
    assert entries == [output_path]
    assert json.loads(output_path.read_text(encoding="utf-8")) == {"ok": True}


def test_existing_comparison_output_is_not_overwritten(tmp_path):
    control_path = tmp_path / "control.json"
    production_path = tmp_path / "production.json"
    output_path = tmp_path / "comparison.json"
    control_path.write_text(json.dumps(valid_snapshot("control", "control-timeline")), encoding="utf-8")
    production_path.write_text(json.dumps(valid_snapshot("production", "production-timeline")), encoding="utf-8")
    output_path.write_text('{"already": "here"}', encoding="utf-8")

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

    assert result == 2
    assert output_path.read_text(encoding="utf-8") == '{"already": "here"}'


def test_offline_compare_does_not_require_execution_authorization(tmp_path):
    control_path = tmp_path / "control.json"
    production_path = tmp_path / "production.json"
    output_path = tmp_path / "comparison.json"
    control_path.write_text(json.dumps(valid_snapshot("control", "control-timeline")), encoding="utf-8")
    production_path.write_text(json.dumps(valid_snapshot("production", "production-timeline")), encoding="utf-8")

    parser = probe.build_parser()
    parsed = parser.parse_args(
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
    assert not hasattr(parsed, "execution_authorization")

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


def test_authorization_value_not_present_in_snapshot_evidence(monkeypatch, tmp_path):
    def stub_connect(*args, **kwargs):
        return valid_resolve()

    monkeypatch.setattr(probe, "connect_resolve_read_only", stub_connect)
    output_path = tmp_path / "snapshot.json"

    probe.main(
        [
            "snapshot",
            "--expected-project",
            "RLC-E9001_MASTER",
            "--expected-timeline",
            "RLC-E9001_TIMELINE",
            "--output",
            str(output_path),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )

    assert probe.EXECUTION_REVISION_ID not in output_path.read_text(encoding="utf-8")


def test_structured_error_does_not_expose_authorization_value():
    secret_looking_value = "sk-not-actually-a-secret-but-should-not-leak"
    with pytest.raises(probe.SnapshotError) as error:
        probe.enforce_execution_interlock(secret_looking_value)
    dump = json.dumps(error.value.to_dict())
    assert secret_looking_value not in dump


def test_no_sqlite_reference_in_source():
    source_path = Path(probe.__file__)
    text = source_path.read_text(encoding="utf-8")
    assert "sqlite3" not in text
    assert "REDLINE_DB_PATH" not in text


def test_revision_id_pattern_rejects_trailing_dot():
    assert not probe.EXECUTION_REVISION_ID_PATTERN.fullmatch("phase14.1-rev3.")


def test_revision_id_pattern_rejects_trailing_underscore():
    assert not probe.EXECUTION_REVISION_ID_PATTERN.fullmatch("phase14.1-rev3_")


def test_revision_id_pattern_rejects_trailing_hyphen():
    assert not probe.EXECUTION_REVISION_ID_PATTERN.fullmatch("phase14.1-rev3-")


def test_revision_id_pattern_accepts_minimum_two_characters():
    assert probe.EXECUTION_REVISION_ID_PATTERN.fullmatch("a1")


def test_revision_id_pattern_rejects_single_character():
    assert not probe.EXECUTION_REVISION_ID_PATTERN.fullmatch("a")


def test_resolve_module_import_failure_is_structured(monkeypatch):
    def failing_importer(name):
        raise ImportError("simulated: no module named DaVinciResolveScript")

    with pytest.raises(probe.SnapshotError) as error:
        probe.connect_resolve_read_only(importer=failing_importer)

    assert error.value.code == "resolve_module_import_failed"
    assert error.value.details["error_type"] == "ImportError"
    dump = json.dumps(error.value.to_dict())
    assert "DaVinciResolveScript" not in dump or "no module named" not in dump


def test_resolve_scriptapp_call_failure_is_structured():
    class FakeModule:
        def scriptapp(self, name):
            raise RuntimeError("simulated: scriptapp internal failure")

    def stub_importer(name):
        return FakeModule()

    with pytest.raises(probe.SnapshotError) as error:
        probe.connect_resolve_read_only(importer=stub_importer)

    assert error.value.code == "resolve_scriptapp_call_failed"
    assert error.value.details["error_type"] == "RuntimeError"


def _valid_manifest_document():
    return {
        "schema_version": 1,
        "mission": "phase14.1-live-snapshot",
        "repository_root": "C:/Users/pj198/Documents/redline-os",
        "origin_url": "git@github.com:Choice283/redline-os.git",
        "authorized_commit": "0" * 40,
        "execution_revision_id": probe.EXECUTION_REVISION_ID,
        "probe_sha256": "0" * 64,
        "test_sha256": "1" * 64,
        "contract_sha256": "2" * 64,
        "runbook_sha256": "3" * 64,
        "resolve_product_version": "21.0.3.7",
        "contexts": {
            "Control": {"project": "redline-os-test-duplicate", "timeline": "RLO-LIVE-ASM-92701_TIMELINE"},
            "Production": {"project": "RLC-E9001_MASTER", "timeline": "RLC-E9001_TIMELINE"},
        },
    }


def test_execution_revision_id_is_rev7():
    assert probe.EXECUTION_REVISION_ID == "phase14.1-live-interlock-construction-rev7"
    assert probe.EXECUTION_REVISION_ID_PATTERN.fullmatch(probe.EXECUTION_REVISION_ID)


def test_valid_manifest_bytes_are_accepted():
    raw = json.dumps(_valid_manifest_document()).encode("utf-8")
    document = probe.validate_authorization_manifest_bytes(raw)
    assert document["schema_version"] == 1
    assert document["execution_revision_id"] == probe.EXECUTION_REVISION_ID


def test_manifest_duplicate_top_level_key_is_rejected():
    raw = b'{"schema_version": 1, "schema_version": 1, "mission": "x"}'
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_duplicate_key"


def test_manifest_duplicate_nested_context_key_is_rejected():
    doc_text = json.dumps(_valid_manifest_document())
    # Inject a duplicate key inside the nested Control context object.
    injected = doc_text.replace(
        '"Control": {"project": "redline-os-test-duplicate"',
        '"Control": {"project": "redline-os-test-duplicate", "project": "duplicate"',
    )
    assert injected != doc_text
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(injected.encode("utf-8"))
    assert error.value.code == "manifest_duplicate_key"


def test_manifest_unexpected_top_level_field_is_rejected():
    doc = _valid_manifest_document()
    doc["unexpected_field"] = "surprise"
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_unexpected_top_level_fields"


def test_manifest_missing_top_level_field_is_rejected():
    doc = _valid_manifest_document()
    del doc["origin_url"]
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_unexpected_top_level_fields"


def test_manifest_unexpected_context_field_is_rejected():
    doc = _valid_manifest_document()
    doc["contexts"]["Control"]["extra"] = "surprise"
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_context_fields_invalid"


def test_manifest_unexpected_context_name_is_rejected():
    doc = _valid_manifest_document()
    doc["contexts"]["Staging"] = doc["contexts"].pop("Production")
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_contexts_invalid"


def test_manifest_string_schema_version_is_rejected():
    doc = _valid_manifest_document()
    doc["schema_version"] = "1"
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_schema_version_invalid"


def test_manifest_boolean_schema_version_is_rejected():
    doc = _valid_manifest_document()
    raw_text = json.dumps(doc).replace('"schema_version": 1', '"schema_version": true')
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw_text.encode("utf-8"))
    assert error.value.code == "manifest_schema_version_invalid"


def test_manifest_non_string_field_is_rejected():
    doc = _valid_manifest_document()
    doc["mission"] = 12345
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_field_not_string:mission"


def test_manifest_invalid_utf8_is_rejected():
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(b"\xff\xfe\x00\x01not utf-8")
    assert error.value.code == "manifest_not_utf8"


def test_manifest_root_not_object_is_rejected():
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(b"[1, 2, 3]")
    assert error.value.code == "manifest_root_not_object"


def test_manifest_error_code_never_contains_field_values():
    doc = _valid_manifest_document()
    doc["authorized_commit"] = "a-secret-looking-commit-value"
    doc["schema_version"] = 2  # unrelated failure; commit value is never validated for format here
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(probe.ManifestValidationError) as error:
        probe.validate_authorization_manifest_bytes(raw)
    assert error.value.code == "manifest_schema_version_invalid"
    assert "a-secret-looking-commit-value" not in error.value.code


def test_validate_manifest_cli_accepts_valid_manifest_without_resolve_import(monkeypatch, capsys):
    def forbidden_import(name):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(probe.importlib, "import_module", forbidden_import)
    raw = json.dumps(_valid_manifest_document()).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    result = probe.main(["validate-manifest"])
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True


def test_validate_manifest_cli_rejects_duplicate_key_without_resolve_import(monkeypatch, capsys):
    def forbidden_import(name):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(probe.importlib, "import_module", forbidden_import)
    raw = b'{"schema_version": 1, "schema_version": 1}'
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    result = probe.main(["validate-manifest"])
    assert result == 2
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "manifest_duplicate_key"


def test_validate_manifest_base64_cli_preserves_exact_bytes_without_resolve_import(
    monkeypatch, capsys
):
    def forbidden_import(name):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(probe.importlib, "import_module", forbidden_import)
    document = _valid_manifest_document()
    document["contexts"]["Control"]["project"] = "redline-café-control"
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")

    observed = []
    original_validator = probe.validate_authorization_manifest_bytes

    def capturing_validator(candidate):
        observed.append(candidate)
        return original_validator(candidate)

    monkeypatch.setattr(probe, "validate_authorization_manifest_bytes", capturing_validator)
    result = probe.main(["validate-manifest-base64", encoded])

    assert result == 0
    assert observed == [raw]
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True


def test_validate_manifest_base64_cli_rejects_invalid_payload_without_resolve_import(
    monkeypatch, capsys
):
    def forbidden_import(name):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(probe.importlib, "import_module", forbidden_import)
    result = probe.main(["validate-manifest-base64", "not+canonical=base64??"])

    assert result == 2
    output = json.loads(capsys.readouterr().err)
    assert output["code"] == "manifest_base64_invalid"


def test_resolve_falsy_handle_still_reports_connection_failed():
    class FakeModule:
        def scriptapp(self, name):
            return None

    def stub_importer(name):
        return FakeModule()

    with pytest.raises(probe.SnapshotError) as error:
        probe.connect_resolve_read_only(importer=stub_importer)

    assert error.value.code == "resolve_connection_failed"


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


RUNBOOK_PATH = REVIEW_ROOT / "scripts" / "phase14_live_snapshot_runbook.ps1"
REVISION_ID_FOR_TESTS = "phase14.1-live-interlock-construction-rev7"


def _runbook_source() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _native_helper_block(source: str) -> str:
    start_marker = "# BEGIN PHASE14_NATIVE_PROCESS_HELPERS"
    end_marker = "# END PHASE14_NATIVE_PROCESS_HELPERS"
    start = source.index(start_marker)
    end = source.index(end_marker, start) + len(end_marker)
    return source[start:end]


def test_rev7_runbook_uses_one_windows_compatible_native_process_boundary():
    source = _runbook_source()

    assert REVISION_ID_FOR_TESTS in source
    assert "# BEGIN PHASE14_NATIVE_PROCESS_HELPERS" in source
    assert "# END PHASE14_NATIVE_PROCESS_HELPERS" in source
    assert "$psi.ArgumentList" not in source
    assert ".ArgumentList.Add" not in source
    assert "Start-Process -FilePath $pyPath" not in source
    assert source.count("Invoke-NativeProcessCapture") >= 5


def test_rev7_runbook_python_identity_program_is_quote_free():
    source = _runbook_source()
    helper_block = _native_helper_block(source)
    match = re.search(
        r"\$versionProbeScript = '([^']+)'",
        helper_block,
    )

    assert match is not None
    program = match.group(1)
    assert '"' not in program
    assert "chr(31)" in program


def test_rev7_runbook_manifest_transport_is_base64_and_single_read():
    source = _runbook_source()

    assert source.count("[System.IO.File]::ReadAllBytes($AuthorizationManifest)") == 1
    assert "[Convert]::ToBase64String($manifestBytes)" in source
    assert '"validate-manifest-base64"' in source
    assert "StandardInput.BaseStream" not in source
    assert "$processInfo.RedirectStandardInput = $true" not in source


def test_rev7_runbook_preflight_returns_before_live_contact_boundary():
    source = _runbook_source()
    preflight_start = source.index("if ($PreflightOnly) {")
    preflight_return = source.index("\n    return\n", preflight_start)
    read_host = source.index("Read-Host", preflight_return)
    live_launch = source.index(
        "$processResult = Invoke-NativeProcessCapture",
        preflight_return,
    )

    assert preflight_start < preflight_return < read_host < live_launch


def test_rev7_runbook_retains_sqlite_fail_closed_source_guard_only():
    source = _runbook_source()

    assert source.count('if ($probeSourceText -match "sqlite3|REDLINE_DB_PATH")') == 1
    assert "sqlite3.connect" not in source
    assert "System.Data.SQLite" not in source


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell.exe") is None,
    reason="requires native Windows PowerShell",
)
def test_rev7_native_process_helpers_round_trip_on_windows(tmp_path):
    source = _runbook_source()
    helpers = _native_helper_block(source)

    echo_path = tmp_path / "argv echo helper.py"
    echo_path.write_text(
        "import json, sys\nprint(json.dumps({'argv': sys.argv[1:]}, sort_keys=True))\n",
        encoding="utf-8",
    )

    document = _valid_manifest_document()
    document["execution_revision_id"] = probe.EXECUTION_REVISION_ID
    manifest_raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    manifest_base64 = base64.b64encode(manifest_raw).decode("ascii")

    harness_path = tmp_path / "native helper harness.ps1"
    harness = textwrap.dedent(
        f"""
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$PythonPath,
            [Parameter(Mandatory = $true)][string]$EchoPath,
            [Parameter(Mandatory = $true)][string]$ProbePath,
            [Parameter(Mandatory = $true)][string]$ManifestBase64
        )
        $ErrorActionPreference = "Stop"
        Set-StrictMode -Version Latest

        function Assert-OrdinaryFile {{
            param(
                [Parameter(Mandatory = $true)][string]$Path,
                [Parameter(Mandatory = $true)][string]$Label
            )
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{
                throw "missing file"
            }}
            $item = Get-Item -LiteralPath $Path -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {{
                throw "reparse point"
            }}
        }}

        {helpers}

        $identity = Get-PythonRuntimeIdentity -PythonPath $PythonPath
        if ($identity.Major -ne 3 -or $identity.Minor -ne 11) {{
            throw "identity mismatch"
        }}

        $expected = @(
            "simple",
            "with space",
            'quote"value',
            "trailing\\",
            "C:\\path with space\\tail\\",
            "",
            "a&b",
            "semi;colon"
        )
        $roundTrip = Invoke-NativeProcessCapture `
            -FilePath $PythonPath `
            -Arguments (@($EchoPath) + $expected)
        if ($roundTrip.ExitCode -ne 0) {{
            throw "round-trip process failed"
        }}
        $roundTripDocument = $roundTrip.Stdout | ConvertFrom-Json -ErrorAction Stop
        $actual = @($roundTripDocument.argv)
        if ($actual.Count -ne $expected.Count) {{
            throw "argument count mismatch"
        }}
        for ($index = 0; $index -lt $expected.Count; $index += 1) {{
            if ([string]$actual[$index] -cne [string]$expected[$index]) {{
                throw "argument mismatch at $index"
            }}
        }}

        $validation = Invoke-NativeProcessCapture `
            -FilePath $PythonPath `
            -Arguments @(
                $ProbePath,
                "validate-manifest-base64",
                $ManifestBase64
            )
        if ($validation.ExitCode -ne 0) {{
            throw "manifest validation process failed"
        }}
        $validationDocument = $validation.Stdout | ConvertFrom-Json -ErrorAction Stop
        if ($validationDocument.valid -ne $true) {{
            throw "manifest validation did not return valid=true"
        }}

        Write-Output "REV7_NATIVE_PROCESS_TEST_PASS"
        """
    ).strip() + "\n"
    harness_path.write_text(harness, encoding="utf-8")

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness_path),
            "-PythonPath",
            sys.executable,
            "-EchoPath",
            str(echo_path),
            "-ProbePath",
            str(Path(probe.__file__).resolve()),
            "-ManifestBase64",
            manifest_base64,
        ],
        cwd=REVIEW_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, (
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "REV7_NATIVE_PROCESS_TEST_PASS" in result.stdout
