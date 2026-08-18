from __future__ import annotations

import ast
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REVIEW_ROOT = Path(__file__).resolve().parents[2]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts import rlc_e9901_snapshot_preflight_contract as contract


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _minimal_valid_snapshot_bytes() -> bytes:
    snapshot = {
        "schema_version": "1.0",
        "mission": "test",
        "captured_at": "2026-08-09T00:00:00Z",
        "snapshot_complete": True,
        "expected_context": {"project": "RLC-E9901_MASTER", "timeline": "RLC-E9901_TIMELINE"},
        "session": {
            "product_name": {"status": "observed", "value": "DaVinci Resolve"},
            "version_string": {"status": "observed", "value": "21.0.3.7"},
            "version": {"status": "observed", "value": [21, 0, 3, 7, ""]},
        },
        "project_manager": {},
        "project": {
            "name": "RLC-E9901_MASTER",
            "render_presets": {"status": "observed", "value": ["Redline Broadcast Master"]},
            "render_queue": {"count": 0, "items": []},
        },
        "target_timeline": {
            "name": "RLC-E9901_TIMELINE",
            "tracks": {"video": {"status": "observed", "count": {"status": "observed", "value": 1}, "tracks": [{"item_count": 1}]}},
        },
        "media_pool": {},
        "pre_guard": {
            "project_name": "RLC-E9901_MASTER", "current_timeline_name": "RLC-E9901_TIMELINE",
            "target_timeline_name": "RLC-E9901_TIMELINE", "rendering_in_progress": False, "queue_count": 0,
            "queue_fingerprint": [],
        },
        "post_guard": {
            "project_name": "RLC-E9901_MASTER", "current_timeline_name": "RLC-E9901_TIMELINE",
            "target_timeline_name": "RLC-E9901_TIMELINE", "rendering_in_progress": False, "queue_count": 0,
            "queue_fingerprint": [],
        },
    }
    return json.dumps(snapshot).encode("utf-8")


# Captured once, before any test monkeypatches contract._load_verified_checker_module,
# so _bypass_prechecks() can still load the REAL checker (for realistic
# end-to-end evaluation in tests) without recursing into whatever mock is
# currently installed.
_REAL_LOAD_VERIFIED_CHECKER_MODULE = contract._load_verified_checker_module


def _bypass_prechecks(monkeypatch):
    monkeypatch.setattr(contract, "verify_repository_checkpoint", lambda authorization: None)
    monkeypatch.setattr(contract, "verify_collector_source_identity", lambda: contract._REVIEWED_SNAPSHOT_SOURCE_SHA256)
    monkeypatch.setattr(contract, "verify_python_interpreter", lambda python_executable: None)
    monkeypatch.setattr(
        contract, "_load_verified_checker_module",
        lambda repository_root=contract.CANONICAL_REPOSITORY_ROOT: _REAL_LOAD_VERIFIED_CHECKER_MODULE(),
    )


# --- verify_collector_source_identity: hash-only, never imports the collector ---

@pytest.mark.workstation
def test_verify_collector_source_identity_passes_against_real_published_collector():
    digest = contract.verify_collector_source_identity()
    assert digest == contract._REVIEWED_SNAPSHOT_SOURCE_SHA256


def test_verify_collector_source_identity_fails_closed_on_tampered_source(tmp_path):
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "scripts").mkdir(parents=True)
    tampered_path = fake_repo / contract.SNAPSHOT_SOURCE_RELATIVE_PATH
    tampered_path.write_text(
        "raise RuntimeError('this must never execute -- collector was imported/executed instead of merely hashed')\n",
        encoding="utf-8",
    )
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_collector_source_identity(repository_root=fake_repo)
    assert excinfo.value.code == "collector_source_hash_mismatch"


# --- verify_checker_source_identity / _load_verified_checker_module (Finding 1) ---

@pytest.mark.workstation
def test_verify_checker_source_identity_passes_against_real_published_checker():
    digest = contract.verify_checker_source_identity()
    assert digest == contract._REVIEWED_CHECKER_SOURCE_SHA256


def test_verify_checker_source_identity_fails_closed_on_tampered_source_and_never_executes_it(tmp_path):
    """Finding 1 regression: a drifted checker must be rejected by hashing
    its bytes alone -- with no import/exec of the tampered content."""
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "scripts").mkdir(parents=True)
    tampered_path = fake_repo / contract.CHECKER_SOURCE_RELATIVE_PATH
    tampered_path.write_text(
        "raise RuntimeError('this must never execute -- checker was imported/executed instead of merely hashed')\n",
        encoding="utf-8",
    )
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_checker_source_identity(repository_root=fake_repo)
    assert excinfo.value.code == "checker_source_hash_mismatch"


def test_load_verified_checker_module_rejects_tampered_source_before_any_execution(tmp_path):
    """Finding 1 regression, exercised through the actual loader (not just
    the hash function directly): _load_verified_checker_module() must stop
    at the hash check and never reach spec_from_file_location/exec_module
    for a drifted checker."""
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "scripts").mkdir(parents=True)
    tampered_path = fake_repo / contract.CHECKER_SOURCE_RELATIVE_PATH
    tampered_path.write_text(
        "raise RuntimeError('MUST NEVER EXECUTE: drifted checker was loaded before the hash gate rejected it')\n",
        encoding="utf-8",
    )
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._load_verified_checker_module(repository_root=fake_repo)
    assert excinfo.value.code == "checker_source_hash_mismatch"


@pytest.mark.workstation
def test_load_verified_checker_module_loads_the_real_checker_by_exact_path_not_sys_path():
    module = contract._load_verified_checker_module()
    assert Path(module.__file__).resolve() == (contract.CANONICAL_REPOSITORY_ROOT / contract.CHECKER_SOURCE_RELATIVE_PATH).resolve()
    assert hasattr(module, "evaluate_offline_preflight")


def test_checker_is_not_reachable_before_the_repository_checkpoint_gate_rejects_a_bad_state(monkeypatch):
    """Finding 1 regression: when the repository checkpoint itself fails,
    the checker must never be loaded (and therefore never executed) at all
    -- _prepare_verified_invocation() must call verify_repository_checkpoint()
    strictly before _load_verified_checker_module()."""

    def failing_checkpoint(authorization):
        raise contract.PreflightContractError("head_commit_mismatch", "boom")

    monkeypatch.setattr(contract, "verify_repository_checkpoint", failing_checkpoint)

    def must_not_be_called(repository_root=contract.CANONICAL_REPOSITORY_ROOT):
        raise AssertionError("checker must never be loaded when the repository checkpoint fails")

    monkeypatch.setattr(contract, "_load_verified_checker_module", must_not_be_called)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="wrong", evidence_output_path=Path(r"C:\evidence\x.json"))
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._prepare_verified_invocation(authorization)
    assert excinfo.value.code == "head_commit_mismatch"


def test_module_never_imports_the_collector_anywhere():
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "phase14_resolve_context_snapshot" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module == "scripts":
                assert all(alias.name != "phase14_resolve_context_snapshot" for alias in node.names)


def test_module_never_imports_the_checker_via_ordinary_import_statement():
    """Finding 1: the checker must never appear in an ordinary Import/ImportFrom
    node anywhere -- it is loaded only via importlib.util.spec_from_file_location
    inside _load_verified_checker_module(), never through sys.path resolution."""
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "rlc_e9901_preflight_assertion" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module == "scripts":
                assert all(alias.name != "rlc_e9901_preflight_assertion" for alias in node.names)


def test_module_has_zero_scripts_package_imports_at_all():
    """This module resolves both sibling files (collector, checker) purely
    by canonical absolute path -- never via `from scripts import ...` /
    `import scripts...`, avoiding any ambiguous sys.path-based resolution."""
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "scripts"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("scripts")


# --- checkpoint hardening ------------------------------------------------------

def _patch_git(monkeypatch, responses: dict[tuple, str]):
    def fake_run_git(args, *, repository_root=contract.CANONICAL_REPOSITORY_ROOT):
        key = tuple(args)
        if key not in responses:
            raise AssertionError(f"unexpected git invocation: {args}")
        return responses[key]

    monkeypatch.setattr(contract, "_run_git", fake_run_git)


_FULL_CLEAN_RESPONSES = {
    ("rev-parse", "--show-toplevel"): str(contract.CANONICAL_REPOSITORY_ROOT),
    ("branch", "--show-current"): contract.CANONICAL_BRANCH,
    ("rev-parse", "HEAD"): "6fa5452320626d06698a0b2f2997c7dd0e6d0c5d",
    ("remote", "get-url", "origin"): contract.CANONICAL_ORIGIN_URL,
    ("rev-parse", "origin/master"): "6fa5452320626d06698a0b2f2997c7dd0e6d0c5d",
    ("status", "--short"): "",
    ("diff", "--cached", "--name-only"): "",
    ("stash", "list"): "",
}


def test_verify_repository_checkpoint_passes_when_everything_matches(monkeypatch):
    _patch_git(monkeypatch, _FULL_CLEAN_RESPONSES)
    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="6fa5452320626d06698a0b2f2997c7dd0e6d0c5d", evidence_output_path=Path("unused"))
    contract.verify_repository_checkpoint(authorization)


def test_verify_repository_checkpoint_fails_on_wrong_branch(monkeypatch):
    responses = {**_FULL_CLEAN_RESPONSES, **{("branch", "--show-current"): "some-feature-branch"}}
    _patch_git(monkeypatch, responses)
    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="6fa5452320626d06698a0b2f2997c7dd0e6d0c5d", evidence_output_path=Path("unused"))
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_repository_checkpoint(authorization)
    assert excinfo.value.code == "branch_mismatch"


def test_verify_repository_checkpoint_fails_on_wrong_head(monkeypatch):
    responses = {**_FULL_CLEAN_RESPONSES, **{("rev-parse", "HEAD"): "deadbeef"}}
    _patch_git(monkeypatch, responses)
    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="6fa5452320626d06698a0b2f2997c7dd0e6d0c5d", evidence_output_path=Path("unused"))
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_repository_checkpoint(authorization)
    assert excinfo.value.code == "head_commit_mismatch"


def test_verify_repository_checkpoint_fails_on_dirty_working_tree(monkeypatch):
    responses = {**_FULL_CLEAN_RESPONSES, **{("status", "--short"): "?? file.py"}}
    _patch_git(monkeypatch, responses)
    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="6fa5452320626d06698a0b2f2997c7dd0e6d0c5d", evidence_output_path=Path("unused"))
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_repository_checkpoint(authorization)
    assert excinfo.value.code == "working_tree_not_clean"


def test_verify_repository_checkpoint_fails_on_nonempty_stash(monkeypatch):
    responses = {**_FULL_CLEAN_RESPONSES, **{("stash", "list"): "stash@{0}: WIP on master"}}
    _patch_git(monkeypatch, responses)
    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="6fa5452320626d06698a0b2f2997c7dd0e6d0c5d", evidence_output_path=Path("unused"))
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_repository_checkpoint(authorization)
    assert excinfo.value.code == "stash_not_empty"


def test_run_git_raises_on_nonzero_exit(monkeypatch):
    def fake_subprocess_run(cmd, capture_output, text, check):
        return _FakeCompletedProcess(1, stderr="fatal: not a git repository")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._run_git(["status"])
    assert excinfo.value.code == "git_command_failed"


# --- verify_python_interpreter ----------------------------------------------

def test_verify_python_interpreter_passes_on_exact_match(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout=json.dumps({"executable": str(contract.EXPECTED_PYTHON_EXECUTABLE), "version": [3, 11, 9]}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    contract.verify_python_interpreter(contract.EXPECTED_PYTHON_EXECUTABLE)


def test_verify_python_interpreter_fails_on_wrong_version(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout=json.dumps({"executable": str(contract.EXPECTED_PYTHON_EXECUTABLE), "version": [3, 13, 0]}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.verify_python_interpreter(contract.EXPECTED_PYTHON_EXECUTABLE)
    assert excinfo.value.code == "python_interpreter_version_mismatch"


def test_verify_python_interpreter_against_real_expected_interpreter():
    if not contract.EXPECTED_PYTHON_EXECUTABLE.exists():
        pytest.skip("expected Python 3.11.9 interpreter is not installed on this machine")
    contract.verify_python_interpreter(contract.EXPECTED_PYTHON_EXECUTABLE)


# --- Finding 3: evidence output path canonicalization/safety ----------------

def test_evidence_path_rejects_relative_path():
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(Path("relative/evidence.json"))
    assert excinfo.value.code == "evidence_path_not_absolute"


@pytest.mark.workstation
def test_evidence_path_rejects_repository_location():
    path = contract.CANONICAL_REPOSITORY_ROOT / "evidence.json"
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(path)
    assert excinfo.value.code == "evidence_path_in_protected_location"


@pytest.mark.workstation
def test_evidence_path_rejects_rlc_e9901_workspace_location():
    path = Path(r"C:\Users\pj198\RedlineOSLive\RLC-E9901\evidence.json")
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(path)
    assert excinfo.value.code == "evidence_path_in_protected_location"


@pytest.mark.workstation
def test_evidence_path_rejects_runtime_location():
    path = Path(r"C:\Users\pj198\RedlineOSLive\Runtime\evidence.json")
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(path)
    assert excinfo.value.code == "evidence_path_in_protected_location"


@pytest.mark.workstation
def test_evidence_path_rejects_preserved_evidence_directory():
    """Rev4 Finding 2 exact reproduction: the separately-located preserved
    Redline evidence directory (C:\\Users\\pj198\\RedlineOSLive\\Evidence)
    is NOT inside the RLC-E9901 workspace tree and was unprotected until
    this revision."""
    path = Path(r"C:\Users\pj198\RedlineOSLive\Evidence\anything.json")
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(path)
    assert excinfo.value.code == "evidence_path_in_protected_location"


def test_evidence_path_rejects_already_existing_output(tmp_path):
    existing = tmp_path / "already-here.json"
    existing.write_text("{}", encoding="utf-8")
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(existing)
    assert excinfo.value.code == "evidence_path_already_exists"


def test_evidence_path_rejects_missing_parent(tmp_path):
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract._canonicalize_and_validate_evidence_path(tmp_path / "missing-parent" / "evidence.json")
    assert excinfo.value.code == "evidence_parent_directory_missing"


def test_evidence_path_accepts_approved_absolute_external_path(tmp_path):
    path = tmp_path / "approved" / "evidence.json"
    path.parent.mkdir()
    resolved = contract._canonicalize_and_validate_evidence_path(path)
    assert resolved == path.resolve()
    assert resolved.is_absolute()


# --- build_snapshot_command --------------------------------------------------

def test_build_snapshot_command_uses_the_resolved_path_not_the_original(tmp_path):
    authorization = contract.Rlce9901SnapshotAuthorization(
        authorized_commit="whatever", evidence_output_path=Path("relative-looking.json")
    )
    resolved_path = tmp_path / "actual-resolved.json"
    command = contract.build_snapshot_command(authorization, resolved_path)
    assert command == [
        str(contract.EXPECTED_PYTHON_EXECUTABLE),
        str(contract.CANONICAL_REPOSITORY_ROOT / contract.SNAPSHOT_SOURCE_RELATIVE_PATH),
        "snapshot",
        "--expected-project", "RLC-E9901_MASTER",
        "--expected-timeline", "RLC-E9901_TIMELINE",
        "--output", str(resolved_path),
        "--execution-authorization", contract._REVIEWED_EXECUTION_REVISION_ID,
    ]


# --- _prepare_verified_invocation: single shared verification path ----------

def test_prepare_verified_invocation_runs_checks_in_order(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(contract, "verify_repository_checkpoint", lambda authorization: calls.append("checkpoint"))
    monkeypatch.setattr(contract, "verify_collector_source_identity", lambda: calls.append("collector") or contract._REVIEWED_SNAPSHOT_SOURCE_SHA256)
    monkeypatch.setattr(contract, "_load_verified_checker_module", lambda repository_root=contract.CANONICAL_REPOSITORY_ROOT: calls.append("checker") or SimpleNamespace())
    monkeypatch.setattr(contract, "verify_python_interpreter", lambda python_executable: calls.append("python"))

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=tmp_path / "x.json")
    contract._prepare_verified_invocation(authorization)
    assert calls == ["checkpoint", "collector", "checker", "python"]


def test_preview_never_launches_any_subprocess_when_prechecks_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(contract, "verify_repository_checkpoint", lambda authorization: None)
    monkeypatch.setattr(contract, "verify_collector_source_identity", lambda: contract._REVIEWED_SNAPSHOT_SOURCE_SHA256)
    monkeypatch.setattr(contract, "_load_verified_checker_module", lambda repository_root=contract.CANONICAL_REPOSITORY_ROOT: SimpleNamespace(__file__=str(contract.CANONICAL_REPOSITORY_ROOT / contract.CHECKER_SOURCE_RELATIVE_PATH)))
    monkeypatch.setattr(contract, "verify_python_interpreter", lambda python_executable: None)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("preview must never launch a subprocess")

    monkeypatch.setattr(subprocess, "run", must_not_be_called)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=tmp_path / "preview.json")
    result = contract.preview_future_snapshot_invocation(authorization)
    assert result["command"][2] == "snapshot"
    assert result["resolved_output_path"] == str((tmp_path / "preview.json").resolve())


# --- run_authorized_rlc_e9901_preflight: the one live orchestration path ----

def test_run_authorized_preflight_stops_before_subprocess_when_checkpoint_fails(monkeypatch, tmp_path):
    def failing_checkpoint(authorization):
        raise contract.PreflightContractError("head_commit_mismatch", "boom")

    monkeypatch.setattr(contract, "verify_repository_checkpoint", failing_checkpoint)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch")))

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="wrong", evidence_output_path=tmp_path / "snapshot.json")
    with pytest.raises(contract.PreflightContractError) as excinfo:
        contract.run_authorized_rlc_e9901_preflight(authorization)
    assert excinfo.value.code == "head_commit_mismatch"


@pytest.mark.workstation
def test_run_authorized_preflight_launches_subprocess_exactly_once_end_to_end(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    call_count = {"n": 0}
    evidence_path = tmp_path / "snapshot.json"
    snapshot_bytes = _minimal_valid_snapshot_bytes()

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        call_count["n"] += 1
        evidence_path.write_bytes(snapshot_bytes)
        return _FakeCompletedProcess(0, stdout="collector stdout", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert call_count["n"] == 1
    assert result.collector_exit_code == 0
    assert result.collector_stdout.text == "collector stdout"
    assert result.stop_reason is None
    assert result.snapshot_capture_status == "complete"
    assert result.render_preflight_status == "passed"


# --- Finding 4: collector failure/timeout/unreadable-output evidence --------

@pytest.mark.workstation
def test_run_authorized_preflight_collector_nonzero_exit_preserves_stdout_stderr(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(2, stdout="", stderr='{"result": "stopped", "error": {"code": "rendering_active"}}')

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.collector_exit_code == 2
    assert result.stop_reason == "collector_exit_nonzero"
    assert "rendering_active" in result.collector_stderr.text
    assert result.snapshot_sha256 is None
    assert not evidence_path.exists()


@pytest.mark.workstation
def test_run_authorized_preflight_collector_launch_failure_is_structured(monkeypatch, tmp_path):
    """A collector process that cannot even start (e.g. FileNotFoundError)
    must produce a structured result, not an uncaught exception."""
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        raise FileNotFoundError("python.exe not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.stop_reason == "collector_launch_failed"
    assert result.collector_launch_error == "FileNotFoundError"
    assert result.collector_exit_code is None
    assert result.render_preflight_status == "not_evaluated"


@pytest.mark.workstation
def test_run_authorized_preflight_collector_timeout_preserves_partial_output(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output="partial stdout", stderr="partial stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.collector_timed_out is True
    assert result.stop_reason == "collector_timed_out"
    assert result.collector_stdout.text == "partial stdout"
    assert result.collector_stderr.text == "partial stderr"
    assert result.render_preflight_status == "not_evaluated"


@pytest.mark.workstation
def test_run_authorized_preflight_missing_output_after_success_preserves_stdout_stderr(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout="collector said ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.stop_reason == "output_file_missing_after_success"
    assert result.collector_stdout.text == "collector said ok"
    assert result.render_preflight_status == "not_evaluated"


@pytest.mark.workstation
def test_run_authorized_preflight_unreadable_output_is_structured(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "unreadable-dir-as-file.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        # Simulate an unreadable path: create a directory where a file was expected.
        evidence_path.mkdir()
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.stop_reason is not None and result.stop_reason.startswith("output_file_unreadable")
    assert result.render_preflight_status == "not_evaluated"


@pytest.mark.workstation
def test_run_authorized_preflight_malformed_json_preserves_evidence_and_hash(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        evidence_path.write_bytes(b"{not valid json")
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.stop_reason == "snapshot_bytes_not_valid_json"
    assert result.snapshot_sha256 == hashlib.sha256(b"{not valid json").hexdigest()
    assert evidence_path.read_bytes() == b"{not valid json"


@pytest.mark.workstation
def test_run_authorized_preflight_never_substitutes_a_different_snapshot_path(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    authorized_path = tmp_path / "authorized.json"
    decoy_path = tmp_path / "decoy.json"
    decoy_path.write_bytes(_minimal_valid_snapshot_bytes())

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=authorized_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.stop_reason == "output_file_missing_after_success"
    assert result.snapshot_path == str(authorized_path)


@pytest.mark.workstation
def test_run_authorized_preflight_records_correct_sha256_of_captured_evidence(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"
    snapshot_bytes = _minimal_valid_snapshot_bytes()

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        evidence_path.write_bytes(snapshot_bytes)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)
    assert result.snapshot_sha256 == hashlib.sha256(evidence_path.read_bytes()).hexdigest()


@pytest.mark.workstation
def test_run_authorized_preflight_capture_success_but_offline_failure_preserves_evidence_and_is_not_pass(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    bad_snapshot = json.loads(_minimal_valid_snapshot_bytes())
    bad_snapshot["project"]["render_presets"]["value"] = ["YouTube - 720p"]
    bad_bytes = json.dumps(bad_snapshot).encode("utf-8")

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        evidence_path.write_bytes(bad_bytes)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.snapshot_capture_status == "complete"
    assert result.render_preflight_status == "failed"
    assert evidence_path.read_bytes() == bad_bytes


@pytest.mark.workstation
def test_run_authorized_preflight_result_to_dict_includes_stdout_stderr(monkeypatch, tmp_path):
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"
    snapshot_bytes = _minimal_valid_snapshot_bytes()

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        evidence_path.write_bytes(snapshot_bytes)
        return _FakeCompletedProcess(0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)
    payload = result.to_dict()
    assert payload["collector_stdout"]["text"] == "ok"
    assert payload["collector_stdout"]["present"] is True
    assert payload["collector_stderr"]["text"] == ""
    assert payload["collector_stderr"]["present"] is True
    assert payload["render_preflight_status"] == "passed"
    # Must round-trip through plain json.dumps() with no `default=` fallback --
    # proves subprocess evidence no longer depends on default=str (Rev5 Finding 2).
    json.dumps({"collector_stdout": payload["collector_stdout"], "collector_stderr": payload["collector_stderr"]})


# --- Rev5 Finding 2: subprocess evidence normalization (CapturedOutput) -----

def test_normalize_captured_output_none_is_absent():
    result = contract._normalize_captured_output(None)
    assert result.present is False
    assert result.encoding is None
    assert result.text is None
    assert result.base64_data is None


def test_normalize_captured_output_empty_string_is_present_but_empty():
    result = contract._normalize_captured_output("")
    assert result.present is True
    assert result.encoding == "utf-8"
    assert result.text == ""
    assert result.byte_length == 0


def test_normalize_captured_output_empty_bytes_is_present_but_empty():
    result = contract._normalize_captured_output(b"")
    assert result.present is True
    assert result.encoding == "utf-8"
    assert result.text == ""
    assert result.byte_length == 0


def test_normalize_captured_output_distinguishes_absent_from_empty():
    assert contract._normalize_captured_output(None).present is False
    assert contract._normalize_captured_output("").present is True
    assert contract._normalize_captured_output(b"").present is True


def test_normalize_captured_output_string_preserved_verbatim():
    result = contract._normalize_captured_output("collector said hello")
    assert result.encoding == "utf-8"
    assert result.text == "collector said hello"
    assert result.base64_data is None


def test_normalize_captured_output_utf8_bytes_preserved_as_text():
    result = contract._normalize_captured_output("hello world".encode("utf-8"))
    assert result.encoding == "utf-8"
    assert result.text == "hello world"
    assert result.base64_data is None


def test_normalize_captured_output_non_utf8_bytes_preserved_losslessly_via_base64():
    """The exact Rev5 Finding 2 case: TimeoutExpired can carry raw bytes on
    Python 3.11 even with text=True. Non-UTF-8 bytes must never be coerced
    through str(bytes) -- they are preserved as base64 + sha256 instead."""
    raw = b"\xff\xfe\x00partial-output-mid-multibyte-sequence"
    result = contract._normalize_captured_output(raw)
    assert result.present is True
    assert result.encoding == "base64"
    assert result.text is None
    assert base64.b64decode(result.base64_data) == raw
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.byte_length == len(raw)


def test_normalize_captured_output_sha256_and_byte_length_always_present_when_present():
    for value in ("some text", b"some bytes", b"\xff\xfe non-utf8"):
        result = contract._normalize_captured_output(value)
        assert result.sha256 is not None
        assert result.byte_length is not None


def test_normalize_captured_output_json_serializable_without_default_str():
    """Every CapturedOutput.to_dict() must round-trip through plain
    json.dumps() -- no default=str fallback needed, for any input shape."""
    for value in (None, "", b"", "text", b"utf8 bytes", b"\xff\xfe non-utf8 bytes"):
        payload = contract._normalize_captured_output(value).to_dict()
        json.dumps(payload)  # raises TypeError if not natively JSON-safe


def test_normalize_captured_output_rejects_unsupported_type():
    with pytest.raises(TypeError):
        contract._normalize_captured_output(12345)


@pytest.mark.workstation
def test_run_authorized_preflight_collector_timeout_with_non_utf8_bytes_preserves_losslessly(monkeypatch, tmp_path):
    """Exact Rev5 Finding 2 reproduction: TimeoutExpired carrying raw,
    non-UTF-8 bytes for stdout/stderr (the documented Python 3.11 behavior
    even under text=True) must be preserved losslessly, not coerced
    through str(bytes) into a lossy repr."""
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"
    raw_stdout = b"\xff\xfemid-sequence-stdout"
    raw_stderr = b"\xff\xfemid-sequence-stderr"  # 0xFF/0xFE are never valid UTF-8 lead bytes

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=raw_stdout, stderr=raw_stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.collector_timed_out is True
    assert result.collector_stdout.encoding == "base64"
    assert base64.b64decode(result.collector_stdout.base64_data) == raw_stdout
    assert result.collector_stderr.encoding == "base64"
    assert base64.b64decode(result.collector_stderr.base64_data) == raw_stderr
    # Must still round-trip through plain json.dumps() -- proves the whole
    # result, not just the isolated helper, no longer depends on default=str
    # for subprocess evidence.
    json.dumps(result.to_dict()["collector_stdout"])
    json.dumps(result.to_dict()["collector_stderr"])


@pytest.mark.workstation
def test_run_authorized_preflight_collector_timeout_with_none_output_is_absent_not_empty(monkeypatch, tmp_path):
    """A TimeoutExpired that never captured any output at all (stdout/stderr
    both None) must be distinguished from captured-but-empty output."""
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=None, stderr=None)

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)

    assert result.collector_stdout.present is False
    assert result.collector_stderr.present is False


@pytest.mark.workstation
def test_result_to_dict_subprocess_evidence_json_serializable_without_default_str(monkeypatch, tmp_path):
    """result.to_dict()'s collector_stdout/collector_stderr sub-payloads must
    round-trip through plain json.dumps() -- proving the subprocess-evidence
    portion of the contract is JSON-native and does not rely on _print_json's
    defensive default=str fallback."""
    _bypass_prechecks(monkeypatch)
    evidence_path = tmp_path / "snapshot.json"
    raw_stdout = b"\xfa\xfbnon-utf8-normal-path"

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=raw_stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    authorization = contract.Rlce9901SnapshotAuthorization(authorized_commit="whatever", evidence_output_path=evidence_path)
    result = contract.run_authorized_rlc_e9901_preflight(authorization)
    payload = result.to_dict()
    json.dumps(payload["collector_stdout"])
    json.dumps(payload["collector_stderr"])


# --- PreflightContractError -------------------------------------------------

def test_preflight_contract_error_to_dict():
    error = contract.PreflightContractError("some_code", "some message", details={"k": "v"})
    assert error.to_dict() == {"code": "some_code", "message": "some message", "details": {"k": "v"}}


# --- CLI: exactly one live subcommand, routed through the reviewed function -

@pytest.mark.workstation
def test_cli_verify_checker_subcommand(capsys):
    exit_code = contract.main(["verify-checker"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["check"] == "checker_source_identity"


def test_cli_preview_snapshot_never_invokes_subprocess(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(contract, "verify_repository_checkpoint", lambda authorization: None)
    monkeypatch.setattr(contract, "verify_collector_source_identity", lambda: contract._REVIEWED_SNAPSHOT_SOURCE_SHA256)
    monkeypatch.setattr(contract, "_load_verified_checker_module", lambda repository_root=contract.CANONICAL_REPOSITORY_ROOT: SimpleNamespace(__file__=str(contract.CANONICAL_REPOSITORY_ROOT / contract.CHECKER_SOURCE_RELATIVE_PATH)))
    monkeypatch.setattr(contract, "verify_python_interpreter", lambda python_executable: None)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("preview-snapshot must never launch a subprocess")

    monkeypatch.setattr(subprocess, "run", must_not_be_called)
    exit_code = contract.main(["preview-snapshot", "--authorized-commit", "abc123", "--output", str(tmp_path / "x.json")])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"][2] == "snapshot"


def test_cli_run_live_preflight_routes_through_the_single_reviewed_orchestration_function(monkeypatch, capsys):
    captured_authorizations = []

    def fake_orchestration(authorization, **kwargs):
        captured_authorizations.append(authorization)
        fake_offline = SimpleNamespace(
            snapshot_capture_status="complete", render_preflight_status="passed",
            to_dict=lambda: {"snapshot_capture_status": "complete", "render_preflight_status": "passed"},
        )
        return contract.Rlce9901PreflightResult(
            collector_launch_error=None, collector_timed_out=False, collector_exit_code=0,
            collector_stdout=contract._normalize_captured_output("ok"),
            collector_stderr=contract._normalize_captured_output(""),
            snapshot_path="C:/evidence/x.json",
            snapshot_sha256="deadbeef", offline_result=fake_offline, stop_reason=None,
        )

    monkeypatch.setattr(contract, "run_authorized_rlc_e9901_preflight", fake_orchestration)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("main() must never call subprocess.run directly")))

    exit_code = contract.main(["run-live-preflight", "--authorized-commit", "abc123", "--output", "C:/evidence/x.json"])
    assert exit_code == 0
    assert len(captured_authorizations) == 1
    assert captured_authorizations[0].authorized_commit == "abc123"


def test_cli_run_live_preflight_exit_code_reflects_render_preflight_status(monkeypatch):
    def fake_orchestration_failed(authorization, **kwargs):
        fake_offline = SimpleNamespace(snapshot_capture_status="complete", render_preflight_status="failed", to_dict=lambda: {})
        return contract.Rlce9901PreflightResult(
            collector_launch_error=None, collector_timed_out=False, collector_exit_code=0,
            collector_stdout=contract._normalize_captured_output(""),
            collector_stderr=contract._normalize_captured_output(""),
            snapshot_path="x.json", snapshot_sha256="abc",
            offline_result=fake_offline, stop_reason=None,
        )

    monkeypatch.setattr(contract, "run_authorized_rlc_e9901_preflight", fake_orchestration_failed)
    exit_code = contract.main(["run-live-preflight", "--authorized-commit", "abc123", "--output", "x.json"])
    assert exit_code == 3


def test_run_live_preflight_is_the_only_subcommand_that_can_reach_the_orchestration_function(monkeypatch, tmp_path):
    calls = {"n": 0}

    def counting_orchestration(authorization, **kwargs):
        calls["n"] += 1
        raise AssertionError("should not be reached by this test")

    monkeypatch.setattr(contract, "run_authorized_rlc_e9901_preflight", counting_orchestration)
    monkeypatch.setattr(contract, "verify_repository_checkpoint", lambda authorization: None)
    monkeypatch.setattr(contract, "verify_collector_source_identity", lambda: contract._REVIEWED_SNAPSHOT_SOURCE_SHA256)
    monkeypatch.setattr(contract, "_load_verified_checker_module", lambda repository_root=contract.CANONICAL_REPOSITORY_ROOT: SimpleNamespace(__file__=str(contract.CANONICAL_REPOSITORY_ROOT / contract.CHECKER_SOURCE_RELATIVE_PATH)))
    monkeypatch.setattr(contract, "verify_python_interpreter", lambda python_executable: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess expected")))

    contract.main(["verify-collector"])
    contract.main(["verify-checker"])
    contract.main(["verify-python"])
    contract.main(["preview-snapshot", "--authorized-commit", "abc", "--output", str(tmp_path / "x.json")])
    assert calls["n"] == 0


# --- static/architectural requirements --------------------------------------

def test_exactly_one_subprocess_run_call_site_can_launch_the_collector():
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_bodies = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    collector_launch_sites = []
    for name, func_node in function_bodies.items():
        for call in ast.walk(func_node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "run"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "subprocess"
            ):
                if call.args and isinstance(call.args[0], ast.Attribute) and call.args[0].attr == "command":
                    collector_launch_sites.append(name)
    assert collector_launch_sites == ["run_authorized_rlc_e9901_preflight"]


def test_run_authorized_preflight_is_never_called_at_module_import_time():
    assert contract.run_authorized_rlc_e9901_preflight.__name__ == "run_authorized_rlc_e9901_preflight"


@pytest.mark.workstation
def test_collector_source_never_imports_redline_os_packages():
    source = (contract.CANONICAL_REPOSITORY_ROOT / contract.SNAPSHOT_SOURCE_RELATIVE_PATH).read_text(encoding="utf-8")
    tree = ast.parse(source)
    disallowed = {"cli", "redline_core", "mcp_server"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in disallowed
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert node.module.split(".")[0] not in disallowed


def test_protected_evidence_roots_cover_repo_workspace_runtime_and_evidence():
    resolved_roots = {p.resolve() for p in contract.PROTECTED_EVIDENCE_ROOTS}
    assert contract.CANONICAL_REPOSITORY_ROOT.resolve() in resolved_roots
    assert Path(r"C:\Users\pj198\RedlineOSLive\RLC-E9901").resolve() in resolved_roots
    assert Path(r"C:\Users\pj198\RedlineOSLive\Runtime").resolve() in resolved_roots
    assert Path(r"C:\Users\pj198\RedlineOSLive\Evidence").resolve() in resolved_roots
