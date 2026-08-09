from __future__ import annotations

import ast
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import rlc_e9901_project_presence_probe as probe


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProjectManager:
    def __init__(self, project_names, *, raise_on_list=None):
        self._project_names = project_names
        self._raise_on_list = raise_on_list

    def GetProjectListInCurrentFolder(self):
        if self._raise_on_list is not None:
            raise self._raise_on_list
        return self._project_names


class FakeResolve:
    def __init__(
        self,
        *,
        product_name="DaVinci Resolve",
        version="19.0",
        version_string="19.0.0 Build 12",
        project_manager=None,
        raise_on_project_manager=None,
    ):
        self._product_name = product_name
        self._version = version
        self._version_string = version_string
        self._project_manager = project_manager
        self._raise_on_project_manager = raise_on_project_manager

    def GetProjectManager(self):
        if self._raise_on_project_manager is not None:
            raise self._raise_on_project_manager
        return self._project_manager

    def GetProductName(self):
        return self._product_name

    def GetVersion(self):
        return self._version

    def GetVersionString(self):
        return self._version_string


def make_resolve(project_names, **kwargs):
    pm = FakeProjectManager(project_names)
    return FakeResolve(project_manager=pm, **kwargs)


# ---------------------------------------------------------------------------
# Static safety review
# ---------------------------------------------------------------------------


def _source_tree() -> ast.Module:
    source = Path(probe.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def test_no_module_level_resolve_import():
    tree = _source_tree()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "DaVinciResolveScript"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "DaVinciResolveScript"


def test_allowlist_and_prohibited_lists_are_disjoint():
    assert probe.READ_ONLY_RESOLVE_METHODS.isdisjoint(probe.PROHIBITED_RESOLVE_METHODS)


def test_no_prohibited_method_called_anywhere_in_source():
    tree = _source_tree()
    called_attribute_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attribute_names.add(node.func.attr)
    overlap = called_attribute_names & probe.PROHIBITED_RESOLVE_METHODS
    assert overlap == set(), f"prohibited Resolve methods referenced as calls: {overlap}"


def test_no_prohibited_method_referenced_as_string_literal_outside_the_list_itself():
    """A prohibited name may appear once, inside PROHIBITED_RESOLVE_METHODS's
    own definition (that's how the list documents what it forbids). It must
    never appear as a string literal anywhere else -- e.g. passed to
    getattr() for dynamic dispatch."""

    tree = _source_tree()
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_assign_target_name(node: ast.AST) -> str | None:
        current = node
        while current in parents:
            current = parents[current]
            if isinstance(current, ast.Assign) and len(current.targets) == 1:
                target = current.targets[0]
                if isinstance(target, ast.Name):
                    return target.id
        return None

    offenders: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if node.value not in probe.PROHIBITED_RESOLVE_METHODS:
            continue
        if enclosing_assign_target_name(node) == "PROHIBITED_RESOLVE_METHODS":
            continue
        offenders.add(node.value)

    assert offenders == set(), f"prohibited Resolve methods referenced outside their own list: {offenders}"


def test_script_sha256_is_deterministic_and_stable_length():
    digest = probe.script_sha256()
    assert len(digest) == 64
    assert digest == probe.script_sha256()


# ---------------------------------------------------------------------------
# Execution interlock
# ---------------------------------------------------------------------------


def test_interlock_missing_none():
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.enforce_execution_interlock(None)
    assert excinfo.value.code == "live_execution_authorization_missing"


def test_interlock_missing_empty_string():
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.enforce_execution_interlock("")
    assert excinfo.value.code == "live_execution_authorization_missing"


@pytest.mark.parametrize(
    "malformed",
    ["", " ", "-leading-dash", "trailing-dash-", " padded ", "a" * 100, "!@#$"],
)
def test_interlock_malformed_values(malformed):
    if malformed == "":
        return  # covered by missing-empty-string case
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.enforce_execution_interlock(malformed)
    assert excinfo.value.code in (
        "live_execution_authorization_invalid",
        "live_execution_revision_mismatch",
    )


def test_interlock_mismatched_well_formed_value():
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.enforce_execution_interlock("some-other-well-formed-revision-id")
    assert excinfo.value.code == "live_execution_revision_mismatch"


def test_interlock_exact_match_passes():
    probe.enforce_execution_interlock(probe.EXECUTION_REVISION_ID)  # must not raise


def test_interlock_error_never_leaks_supplied_value():
    secret = "SHOULD-NEVER-APPEAR-IN-ERROR-abc123"
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.enforce_execution_interlock(secret)
    dumped = json.dumps(excinfo.value.to_dict())
    assert secret not in dumped


# ---------------------------------------------------------------------------
# Output path validation / no-overwrite write
# ---------------------------------------------------------------------------


def test_validate_output_path_rejects_existing_file(tmp_path):
    existing = tmp_path / "evidence.json"
    existing.write_text("{}")
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.validate_output_path(existing)
    assert excinfo.value.code == "output_path_already_exists"


def test_validate_output_path_rejects_existing_directory(tmp_path):
    existing_dir = tmp_path / "evidence_dir"
    existing_dir.mkdir()
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.validate_output_path(existing_dir)
    assert excinfo.value.code == "output_path_is_directory"


def test_validate_output_path_rejects_missing_parent(tmp_path):
    target = tmp_path / "does_not_exist" / "evidence.json"
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.validate_output_path(target)
    assert excinfo.value.code == "output_parent_directory_missing"


def test_validate_output_path_accepts_fresh_path_without_creating_it(tmp_path):
    target = tmp_path / "evidence.json"
    probe.validate_output_path(target)  # must not raise
    assert not target.exists()


def test_write_json_no_overwrite_writes_exact_content(tmp_path):
    target = tmp_path / "evidence.json"
    payload = {"b": 2, "a": 1}
    probe.write_json_no_overwrite(target, payload)
    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == payload
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    # sort_keys=True in the writer
    assert text.index('"a"') < text.index('"b"')


def test_write_json_no_overwrite_refuses_existing_path(tmp_path):
    target = tmp_path / "evidence.json"
    target.write_text("{}")
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.write_json_no_overwrite(target, {"x": 1})
    assert excinfo.value.code == "output_path_already_exists"


def test_write_json_no_overwrite_leaves_no_temp_file_behind(tmp_path):
    target = tmp_path / "evidence.json"
    probe.write_json_no_overwrite(target, {"x": 1})
    remaining = list(tmp_path.iterdir())
    assert remaining == [target]


# ---------------------------------------------------------------------------
# connect_resolve_read_only
# ---------------------------------------------------------------------------


def test_connect_import_failure():
    def failing_importer(name):
        raise ImportError("no module")

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.connect_resolve_read_only(importer=failing_importer)
    assert excinfo.value.code == "resolve_module_import_failed"


def test_connect_scriptapp_missing():
    class ModuleWithoutScriptapp:
        pass

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.connect_resolve_read_only(importer=lambda name: ModuleWithoutScriptapp())
    assert excinfo.value.code == "resolve_scriptapp_unavailable"


def test_connect_scriptapp_raises():
    class Module:
        def scriptapp(self, name):
            raise RuntimeError("boom")

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.connect_resolve_read_only(importer=lambda name: Module())
    assert excinfo.value.code == "resolve_scriptapp_call_failed"


def test_connect_scriptapp_returns_falsy():
    class Module:
        def scriptapp(self, name):
            return None

    with pytest.raises(probe.ProbeError) as excinfo:
        probe.connect_resolve_read_only(importer=lambda name: Module())
    assert excinfo.value.code == "resolve_connection_failed"


def test_connect_success():
    sentinel = object()

    class Module:
        def scriptapp(self, name):
            assert name == "Resolve"
            return sentinel

    assert probe.connect_resolve_read_only(importer=lambda name: Module()) is sentinel


# ---------------------------------------------------------------------------
# classify_membership
# ---------------------------------------------------------------------------


def test_classify_membership_absent():
    assert probe.classify_membership(["A", "B"], "RLC-E9901_MASTER") == ("absent", 0)


def test_classify_membership_present():
    assert probe.classify_membership(["A", "RLC-E9901_MASTER"], "RLC-E9901_MASTER") == ("present", 1)


def test_classify_membership_ambiguous():
    names = ["RLC-E9901_MASTER", "RLC-E9901_MASTER"]
    assert probe.classify_membership(names, "RLC-E9901_MASTER") == ("ambiguous", 2)


def test_classify_membership_is_case_sensitive():
    assert probe.classify_membership(["rlc-e9901_master"], "RLC-E9901_MASTER") == ("absent", 0)


# ---------------------------------------------------------------------------
# collect_project_presence
# ---------------------------------------------------------------------------


def test_collect_ready_gate():
    resolve = make_resolve(["Other Project", "RLC_MASTER_TEMPLATE"])
    result = probe.collect_project_presence(resolve)
    assert result["disposable_project"]["status"] == "absent"
    assert result["template_project"]["status"] == "present"
    assert result["overall_gate"] == "ready_for_live_build_authorization_review"
    assert result["probe_complete"] is True
    assert result["project_list_count"] == 2


def test_collect_blocked_disposable_present():
    resolve = make_resolve(["RLC-E9901_MASTER", "RLC_MASTER_TEMPLATE"])
    result = probe.collect_project_presence(resolve)
    assert result["overall_gate"] == "blocked_disposable_project_present"


def test_collect_blocked_template_absent():
    resolve = make_resolve(["SomeOtherProject"])
    result = probe.collect_project_presence(resolve)
    assert result["overall_gate"] == "blocked_template_absent"


def test_collect_blocked_both():
    resolve = make_resolve(["RLC-E9901_MASTER"])
    result = probe.collect_project_presence(resolve)
    assert result["overall_gate"] == "blocked_disposable_present_and_template_absent"


def test_collect_version_unavailable_fails_closed():
    resolve = make_resolve(["RLC_MASTER_TEMPLATE"], version=None, version_string=None)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "resolve_version_unavailable"


def test_collect_project_manager_missing():
    resolve = FakeResolve(project_manager=None)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "project_manager_missing"


def test_collect_project_manager_accessor_raises_fails_closed():
    """Important Finding 1: GetProjectManager() raising must surface as a
    structured ProbeError via _call_allowlisted's accessor_call_failed
    classification -- never an uncontrolled traceback, never a silent
    fallback to some other outcome."""

    boom = RuntimeError("bridge disconnected")
    resolve = FakeResolve(project_manager=FakeProjectManager(["RLC_MASTER_TEMPLATE"]))
    resolve._raise_on_project_manager = boom
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "accessor_call_failed"
    assert excinfo.value.details["method"] == "GetProjectManager"
    assert excinfo.value.details["error_type"] == "RuntimeError"
    # The raw exception text/object must never leak into the structured error.
    dumped = json.dumps(excinfo.value.to_dict())
    assert "bridge disconnected" not in dumped


def test_collect_project_list_accessor_raises_fails_closed():
    """Important Finding 1: GetProjectListInCurrentFolder() raising must
    surface the same way. Exercises the existing raise_on_list scaffolding
    that was previously built but never wired into a test."""

    boom = RuntimeError("timeout talking to Resolve")
    pm = FakeProjectManager(["RLC_MASTER_TEMPLATE"], raise_on_list=boom)
    resolve = FakeResolve(project_manager=pm)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "accessor_call_failed"
    assert excinfo.value.details["method"] == "GetProjectListInCurrentFolder"
    assert excinfo.value.details["error_type"] == "RuntimeError"
    dumped = json.dumps(excinfo.value.to_dict())
    assert "timeout talking to Resolve" not in dumped


def test_collect_non_list_project_list():
    pm = FakeProjectManager("not-a-list")
    resolve = FakeResolve(project_manager=pm)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "invalid_project_list"


def test_collect_non_string_entry():
    pm = FakeProjectManager(["Valid", 42])
    resolve = FakeResolve(project_manager=pm)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "invalid_project_list_entry"


def test_collect_empty_string_entry():
    pm = FakeProjectManager(["Valid", "   "])
    resolve = FakeResolve(project_manager=pm)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "invalid_project_list_entry"


def test_collect_disposable_ambiguous():
    resolve = make_resolve(["RLC-E9901_MASTER", "RLC-E9901_MASTER", "RLC_MASTER_TEMPLATE"])
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "disposable_project_ambiguous"


def test_collect_template_ambiguous():
    resolve = make_resolve(["RLC_MASTER_TEMPLATE", "RLC_MASTER_TEMPLATE"])
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "template_project_ambiguous"


def test_collect_project_list_returns_falsy_none():
    pm = FakeProjectManager(None)
    resolve = FakeResolve(project_manager=pm)
    result = probe.collect_project_presence(resolve)
    assert result["project_list_count"] == 0
    assert result["overall_gate"] == "blocked_template_absent"


def test_collect_result_is_json_serializable():
    resolve = make_resolve(["RLC_MASTER_TEMPLATE"])
    result = probe.collect_project_presence(resolve)
    json.dumps(result)  # must not raise


# ---------------------------------------------------------------------------
# Important Finding 3: captured_at evidence timestamp
# ---------------------------------------------------------------------------


def test_collect_includes_captured_at_field():
    resolve = make_resolve(["RLC_MASTER_TEMPLATE"])
    result = probe.collect_project_presence(resolve)
    assert "captured_at" in result
    assert isinstance(result["captured_at"], str) and result["captured_at"]


def test_utc_now_matches_established_redline_os_convention():
    """Same convention as scripts/phase14_resolve_context_snapshot.py's
    utc_now(): timezone-aware UTC, microsecond precision, 'Z' suffix instead
    of '+00:00', and round-trips through datetime.fromisoformat once 'Z' is
    substituted back."""

    timestamp = probe.utc_now()
    assert timestamp.endswith("Z")
    assert "+00:00" not in timestamp
    parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == dt.timedelta(0)


def test_collect_captured_at_uses_utc_now(monkeypatch):
    fixed = "2026-01-01T00:00:00.000000Z"
    monkeypatch.setattr(probe, "utc_now", lambda: fixed)
    resolve = make_resolve(["RLC_MASTER_TEMPLATE"])
    result = probe.collect_project_presence(resolve)
    assert result["captured_at"] == fixed


def test_main_check_full_success_evidence_includes_captured_at(tmp_path, monkeypatch):
    resolve = make_resolve(["RLC_MASTER_TEMPLATE"])
    monkeypatch.setattr(probe, "connect_resolve_read_only", lambda: resolve)
    target = tmp_path / "evidence.json"
    exit_code = probe.main(
        ["check", "--output", str(target), "--execution-authorization", probe.EXECUTION_REVISION_ID]
    )
    assert exit_code == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert "captured_at" in written and written["captured_at"]


# ---------------------------------------------------------------------------
# Minor Finding 5: unusable falsy scalars must never satisfy the
# usable-version observation gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unusable", [None, "", False, 0, 0.0, True])
def test_is_unusable_scalar_true_for_exact_findings_list(unusable):
    """Rev3: both booleans are unusable, alongside None/""/0/0.0 (Rev2)."""
    assert probe._is_unusable_scalar(unusable) is True


@pytest.mark.parametrize("usable", ["19.0", "0.0.1", 1, 1.5, "False", "True", "0 "])
def test_is_unusable_scalar_false_for_meaningful_values(usable):
    assert probe._is_unusable_scalar(usable) is False


class _ScalarFakeObject:
    """Minimal object exposing exactly one allowlisted-shaped accessor
    returning a caller-supplied scalar, for direct _observe_identity tests."""

    def __init__(self, value):
        self._value = value

    def GetVersionString(self):
        return self._value


@pytest.mark.parametrize("unusable", [None, "", False, 0, 0.0, True])
def test_observe_identity_treats_unusable_scalars_as_unavailable(unusable):
    """Rev3: True is included alongside the Rev2 set -- both booleans are
    unusable version evidence, not just False."""
    observation = probe._observe_identity(_ScalarFakeObject(unusable), "GetVersionString")
    assert observation["status"] == "unavailable"
    assert observation["value"] is None


@pytest.mark.parametrize("value", [None, "", False, 0, 0.0, True])
def test_collect_version_and_version_string_both_unusable_fails_closed(value):
    """Integration-level proof for Rev2/Rev3 Minor Finding 5: even though
    these are permitted Python scalar types, neither GetVersion() nor
    GetVersionString() returning one can satisfy has_usable_version."""

    resolve = make_resolve(["RLC_MASTER_TEMPLATE"], version=value, version_string=value)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "resolve_version_unavailable"


def test_collect_version_true_boolean_is_rejected():
    """Rev3 correction: True must not satisfy has_usable_version, closing the
    gap the Rev2 independent review identified (Rev2 deliberately -- and, on
    review, indefensibly -- scoped its hardening to exactly
    None/""/False/0/0.0, leaving True accepted). With both GetVersion() and
    GetVersionString() returning True, no usable version is observed at all,
    so the probe fails closed rather than reaching the project-list read."""

    resolve = make_resolve(["RLC_MASTER_TEMPLATE"], version=True, version_string=True)
    with pytest.raises(probe.ProbeError) as excinfo:
        probe.collect_project_presence(resolve)
    assert excinfo.value.code == "resolve_version_unavailable"


# ---------------------------------------------------------------------------
# Minor Finding 6: realistic GetVersion() list/tuple shape
# ---------------------------------------------------------------------------


def test_normalize_version_components_realistic_list():
    assert probe._normalize_version_components([19, 0, 3, 7]) == "19.0.3.7"


def test_normalize_version_components_tuple_with_string_suffix():
    assert probe._normalize_version_components((19, 0, 4, 3, "b1")) == "19.0.4.3.b1"


def test_normalize_version_components_empty_sequence_is_none():
    assert probe._normalize_version_components([]) is None


def test_normalize_version_components_rejects_bool_element():
    assert probe._normalize_version_components([19, True, 3]) is None


def test_normalize_version_components_rejects_empty_string_element():
    assert probe._normalize_version_components([19, "", 3]) is None


def test_normalize_version_components_rejects_non_int_non_str_element():
    assert probe._normalize_version_components([19, 0, None]) is None
    assert probe._normalize_version_components([19, 0, 3.5]) is None


def test_normalize_version_components_rejects_negative_integer_element():
    """Rev3 correction: a negative integer anywhere in the sequence rejects
    the whole sequence, closing the gap the Rev2 independent review
    identified (genuine Resolve version components are never negative)."""

    assert probe._normalize_version_components([-1, 0, 3]) is None
    assert probe._normalize_version_components([19, -1, 3, 7]) is None


def test_normalize_version_components_rejects_negative_integer_as_first_and_last_element():
    assert probe._normalize_version_components([-1]) is None
    assert probe._normalize_version_components([19, 0, 3, -7]) is None


def test_normalize_version_components_zero_is_still_accepted():
    """Zero is a valid, non-negative version component -- only strictly
    negative integers are rejected by the Rev3 correction."""

    assert probe._normalize_version_components([0, 0, 0]) == "0.0.0"


def test_observe_identity_rejects_realistic_looking_negative_version_list():
    observation = probe._observe_identity(_ScalarFakeObject([19, -1, 3, 7]), "GetVersionString")
    assert observation["status"] == "error"
    assert observation["value"] is None


def test_observe_identity_normalizes_realistic_resolve_version_list():
    observation = probe._observe_identity(_ScalarFakeObject([19, 0, 3, 7]), "GetVersionString")
    assert observation["status"] == "observed"
    assert observation["value"] == "19.0.3.7"


def test_observe_identity_rejects_malformed_version_list():
    observation = probe._observe_identity(_ScalarFakeObject([19, None, 3]), "GetVersionString")
    assert observation["status"] == "error"
    assert observation["value"] is None


def test_collect_accepts_realistic_list_shaped_get_version():
    """Deliberate behavior, not accidental: a realistic Resolve-shaped
    GetVersion() list satisfies has_usable_version via normalization, even
    when GetVersionString() itself is unavailable."""

    resolve = make_resolve(["RLC_MASTER_TEMPLATE"], version=[19, 0, 3, 7], version_string=None)
    result = probe.collect_project_presence(resolve)
    assert result["session"]["version"]["status"] == "observed"
    assert result["session"]["version"]["value"] == "19.0.3.7"
    assert result["overall_gate"] == "ready_for_live_build_authorization_review"


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_main_print_sha256_never_touches_resolve(monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("connect_resolve_read_only must not be called")

    monkeypatch.setattr(probe, "connect_resolve_read_only", explode)
    exit_code = probe.main(["--print-sha256"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == probe.script_sha256()


def test_main_check_requires_command():
    with pytest.raises(SystemExit):
        probe.main([])


def test_main_check_missing_authorization_stops_before_output_validation(tmp_path, monkeypatch, capsys):
    target = tmp_path / "nested" / "evidence.json"  # parent does not exist

    def explode(*args, **kwargs):
        raise AssertionError("must not validate output path before interlock passes")

    monkeypatch.setattr(probe, "validate_output_path", explode)
    exit_code = probe.main(["check", "--output", str(target)])
    assert exit_code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "live_execution_authorization_missing"


def test_main_check_wrong_authorization_never_contacts_resolve(tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("connect_resolve_read_only must not be called")

    monkeypatch.setattr(probe, "connect_resolve_read_only", explode)
    target = tmp_path / "evidence.json"
    exit_code = probe.main(
        ["check", "--output", str(target), "--execution-authorization", "wrong-revision"]
    )
    assert exit_code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "live_execution_revision_mismatch"
    assert not target.exists()


def test_main_check_output_collision_with_valid_auth_never_contacts_resolve(tmp_path, monkeypatch, capsys):
    """Important Finding 2: mechanically protects the required ordering

        execution interlock -> output-path validation -> Resolve connection

    with a *valid* execution authorization, so this test can only pass if
    validate_output_path genuinely runs, and genuinely stops the run, before
    connect_resolve_read_only is ever reached. A future accidental reordering
    of those two calls in run_check_command would make this test fail: with
    a real (non-exploding) connect_resolve_read_only, a reordering that
    connects first would attempt a real Resolve import/connection during a
    unit test run and error out in an environment-dependent way rather than
    cleanly asserting the intended output_path_already_exists outcome.
    """

    def explode(*args, **kwargs):
        raise AssertionError(
            "connect_resolve_read_only must not be called when the output path already exists"
        )

    monkeypatch.setattr(probe, "connect_resolve_read_only", explode)
    target = tmp_path / "evidence.json"
    target.write_text("{}")  # pre-existing destination -- the collision
    exit_code = probe.main(
        [
            "check",
            "--output",
            str(target),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,  # deliberately valid
        ]
    )
    assert exit_code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "output_path_already_exists"
    # The pre-existing file must remain exactly as it was -- never overwritten.
    assert target.read_text(encoding="utf-8") == "{}"


def test_main_check_full_success_path(tmp_path, monkeypatch):
    resolve = make_resolve(["RLC_MASTER_TEMPLATE"])
    monkeypatch.setattr(probe, "connect_resolve_read_only", lambda: resolve)
    target = tmp_path / "evidence.json"
    exit_code = probe.main(
        [
            "check",
            "--output",
            str(target),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )
    assert exit_code == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["overall_gate"] == "ready_for_live_build_authorization_review"


def test_main_check_probe_error_writes_no_evidence(tmp_path, monkeypatch, capsys):
    def raise_probe_error():
        raise probe.ProbeError("resolve_connection_failed", "no handle")

    monkeypatch.setattr(probe, "connect_resolve_read_only", raise_probe_error)
    target = tmp_path / "evidence.json"
    exit_code = probe.main(
        [
            "check",
            "--output",
            str(target),
            "--execution-authorization",
            probe.EXECUTION_REVISION_ID,
        ]
    )
    assert exit_code == 2
    assert not target.exists()
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "resolve_connection_failed"
