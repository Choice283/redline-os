from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REVIEW_ROOT = Path(__file__).resolve().parents[2]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts import rlc_e9901_module_provenance_check as prov


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _good_report(src_root: Path) -> str:
    return json.dumps(
        {
            "cli": {"imported": True, "file": str(src_root / "cli" / "__init__.py"), "path": [str(src_root / "cli")]},
            "redline_core": {
                "imported": True,
                "file": str(src_root / "redline_core" / "__init__.py"),
                "path": [str(src_root / "redline_core")],
            },
        }
    )


# --- build_pythonpath / build_provenance_check_environment ------------------

def test_build_pythonpath_has_src_first_then_resolve_modules():
    """`build_pythonpath()` itself joins with `os.pathsep` (portable by
    design -- see the function's own docstring). Verify by direct equality
    against that same join, not by splitting the result back apart: the
    fixture values below are Windows-drive-style strings (`C:/repo/src`),
    which themselves contain a `:` -- on a host where `os.pathsep` is also
    `:` (e.g. Linux), `result.split(os.pathsep)` incorrectly splits the
    drive-letter prefixes apart too, not just the intended join point. A
    literal hardcoded `;` has the same problem in the opposite direction:
    it silently fails to split the joined value at all on such a host.
    Neither is a defect in `build_pythonpath()` itself, which never splits
    anything -- only this test's own verification strategy needed to
    avoid reversing a join with split()."""
    src = Path("C:/repo/src")
    modules = Path("C:/resolve/modules")
    result = prov.build_pythonpath(repository_src=src, resolve_modules=modules)
    assert result == os.pathsep.join([str(src), str(modules)])


def test_build_provenance_check_environment_overrides_pythonpath_only():
    base = {"PYTHONPATH": "stale-value", "OTHER_VAR": "kept"}
    env = prov.build_provenance_check_environment(base)
    assert env["OTHER_VAR"] == "kept"
    assert env["PYTHONPATH"] == prov.build_pythonpath()


# --- verify_module_provenance: success -----------------------------------

def test_verify_module_provenance_passes_when_both_modules_under_expected_root(monkeypatch):
    src_root = Path("C:/Users/pj198/Documents/redline-os/src")

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout=_good_report(src_root))

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = prov.verify_module_provenance(expected_src_root=src_root, env={})
    assert report["cli"]["imported"] is True
    assert report["redline_core"]["imported"] is True


# --- verify_module_provenance: fail-closed paths -----------------------------

def test_verify_module_provenance_fails_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(prov.ProvenanceCheckError) as excinfo:
        prov.verify_module_provenance(env={})
    assert excinfo.value.code == "provenance_probe_failed"


def test_verify_module_provenance_fails_on_malformed_json(monkeypatch):
    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout="not json")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(prov.ProvenanceCheckError) as excinfo:
        prov.verify_module_provenance(env={})
    assert excinfo.value.code == "provenance_probe_output_invalid"


def test_verify_module_provenance_fails_when_module_entry_missing(monkeypatch):
    src_root = Path("C:/Users/pj198/Documents/redline-os/src")

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        # `cli` (checked first) resolves correctly; `redline_core` is
        # entirely absent from the probe report.
        return _FakeCompletedProcess(
            0,
            stdout=json.dumps(
                {"cli": {"imported": True, "file": str(src_root / "cli" / "__init__.py"), "path": [str(src_root / "cli")]}}
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(prov.ProvenanceCheckError) as excinfo:
        prov.verify_module_provenance(expected_src_root=src_root, env={})
    assert excinfo.value.code == "module_provenance_missing"


def test_verify_module_provenance_fails_when_import_failed(monkeypatch):
    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(
            0,
            stdout=json.dumps(
                {
                    "cli": {"imported": False, "error_type": "ModuleNotFoundError"},
                    "redline_core": {"imported": True, "file": "x", "path": []},
                }
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(prov.ProvenanceCheckError) as excinfo:
        prov.verify_module_provenance(env={})
    assert excinfo.value.code == "module_import_failed"


def test_verify_module_provenance_fails_when_file_missing(monkeypatch):
    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(
            0,
            stdout=json.dumps(
                {
                    "cli": {"imported": True, "file": None, "path": []},
                    "redline_core": {"imported": True, "file": "x", "path": []},
                }
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(prov.ProvenanceCheckError) as excinfo:
        prov.verify_module_provenance(env={})
    assert excinfo.value.code == "module_file_unavailable"


def test_verify_module_provenance_fails_closed_on_shadowing_directory(monkeypatch, tmp_path):
    """The exact CWD-shadowing risk this check exists to catch."""

    shadow_root = tmp_path / "workspace_shadow"
    shadow_cli_file = shadow_root / "cli" / "__init__.py"

    def fake_run_shadowed(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(
            0,
            stdout=json.dumps(
                {
                    "cli": {"imported": True, "file": str(shadow_cli_file), "path": [str(shadow_root / "cli")]},
                    "redline_core": {
                        "imported": True,
                        "file": str(prov.CANONICAL_REPOSITORY_SRC / "redline_core" / "__init__.py"),
                        "path": [str(prov.CANONICAL_REPOSITORY_SRC / "redline_core")],
                    },
                }
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run_shadowed)
    with pytest.raises(prov.ProvenanceCheckError) as excinfo:
        prov.verify_module_provenance(env={})
    assert excinfo.value.code == "module_provenance_mismatch"
    assert excinfo.value.details["module"] == "cli"


# --- CLI ---------------------------------------------------------------------

def test_main_exits_0_on_success(monkeypatch, capsys):
    src_root = prov.CANONICAL_REPOSITORY_SRC

    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout=_good_report(src_root))

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = prov.main([])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "passed"


def test_main_exits_2_on_failure(monkeypatch, capsys):
    def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
        return _FakeCompletedProcess(1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    exit_code = prov.main([])
    assert exit_code == 2


# --- static safety: probe program and module never reference Resolve -------

def test_probe_source_never_references_resolve():
    assert "Resolve" not in prov._PROVENANCE_PROBE_SOURCE
    assert "DaVinciResolveScript" not in prov._PROVENANCE_PROBE_SOURCE
    assert "scriptapp" not in prov._PROVENANCE_PROBE_SOURCE


def test_probe_source_imports_only_target_modules():
    assert '"cli"' in prov._PROVENANCE_PROBE_SOURCE
    assert '"redline_core"' in prov._PROVENANCE_PROBE_SOURCE
    assert "mcp_server" not in prov._PROVENANCE_PROBE_SOURCE


def test_module_source_has_no_resolve_import_statements():
    # String-substring checks would false-positive here: the module's own
    # docstring names `DaVinciResolveScript`/`scriptapp` in prose to
    # document that it never touches them. AST parsing checks only actual
    # Import/ImportFrom/Call nodes, ignoring docstrings and comments.
    source = Path(prov.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "resolve" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "resolve" not in node.module.lower()
        elif isinstance(node, (ast.Attribute, ast.Name)):
            identifier = getattr(node, "attr", None) or getattr(node, "id", None)
            assert identifier != "scriptapp"
