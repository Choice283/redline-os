"""Tests for control_room.state_reader.StateReader."""
from __future__ import annotations

import pytest

from control_room.models import ProjectState
from control_room.state_reader import StateReader, StateReadError

_VALID_YAML = """
project_id: redline-os
summary: >
  V1 is frozen; Control Room V0 is the active post-V1 development stage.
current_mission:
  id: control-room-v0-m1
  title: Control Room V0 -- Mission 1
  phase: implementation
latest_checkpoint:
  label: Redline OS V1.0.0
  commit: a41eb57012fbd80ae1be536d8e91ab74f459bc32
  document: docs/REDLINE_OS_V1_RELEASE_CANDIDATE.md
validation:
  status: pass_with_exception
  summary: >
    V1 independent release audit passed. CI remains red from documented
    portability/stale-test debt.
attention:
  required: false
  reason: null
"""


def test_read_valid_state_file(tmp_path):
    path = tmp_path / "PROJECT_STATE.yaml"
    path.write_text(_VALID_YAML, encoding="utf-8")

    state = StateReader().read(path)

    assert isinstance(state, ProjectState)
    assert state.project_id == "redline-os"
    assert state.current_mission.id == "control-room-v0-m1"
    assert state.latest_checkpoint.commit == "a41eb57012fbd80ae1be536d8e91ab74f459bc32"
    assert state.validation.status == "pass_with_exception"
    assert state.attention.required is False
    assert state.attention.reason is None


def test_missing_state_file_raises(tmp_path):
    with pytest.raises(StateReadError):
        StateReader().read(tmp_path / "does_not_exist.yaml")


def test_malformed_yaml_raises(tmp_path):
    path = tmp_path / "PROJECT_STATE.yaml"
    path.write_text("project_id: redline-os\n  bad indent: [oops\n", encoding="utf-8")
    with pytest.raises(StateReadError):
        StateReader().read(path)


def test_schema_invalid_yaml_raises(tmp_path):
    path = tmp_path / "PROJECT_STATE.yaml"
    path.write_text("project_id: redline-os\n", encoding="utf-8")  # missing required fields
    with pytest.raises(StateReadError):
        StateReader().read(path)


def test_non_mapping_yaml_raises(tmp_path):
    path = tmp_path / "PROJECT_STATE.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(StateReadError):
        StateReader().read(path)
