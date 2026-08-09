"""Non-Resolve-contacting module-provenance check for the future `render queue` command.

Construction status
--------------------
Construction and static-review artifact only. This module never imports,
references, or dynamically loads `DaVinciResolveScript`, and never calls
`scriptapp`. It exists to answer one narrow question ahead of a future,
separately authorized `python -m cli.main render queue RLC-E9901
broadcast_master` invocation: when that command runs with process CWD
`C:\\Users\\pj198\\RedlineOSLive\\RLC-E9901` (required so
`episode.folder_path` resolves correctly — see
`redline_core/render/plan.py`), does `import cli` / `import redline_core`
actually resolve to the reviewed canonical repository at
`C:\\Users\\pj198\\Documents\\redline-os\\src`, or could it silently
resolve somewhere else (a stray same-named directory under the workspace
CWD, a stale editable install, a wrong PYTHONPATH)?

Why this is necessary
----------------------
`python -m` inserts the process's current working directory at
`sys.path[0]` before anything else is considered (verified empirically:
running `python -c "import sys; print(sys.path)"` from
`C:\\Users\\pj198\\RedlineOSLive\\RLC-E9901` showed `sys.path[0] == ''`,
which Python resolves to the CWD). If that workspace directory ever
contained a subdirectory literally named `cli` or `redline_core`, it would
shadow the real packages silently — no error, just the wrong code running
against the real, non-disposable RLC-E9901 workspace and database. As of
this construction (2026-08-09), the workspace contains only `_assets`,
`_episodes`, `_ingest`, and the episode manifest — no such collision exists
today — but the future execution contract must prove this at invocation
time, not assume it stays true.

PYTHONPATH ordering (verified empirically against the real Python 3.11.9
interpreter and canonical paths on this workstation)
-------------------------------------------------------------------------
With `PYTHONPATH` set to exactly
`C:\\Users\\pj198\\Documents\\redline-os\\src;C:\\ProgramData\\Blackmagic
Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules` and
`python -m cli.main` invoked from
`C:\\Users\\pj198\\RedlineOSLive\\RLC-E9901`, the resulting `sys.path` is:

    [0] ''  (the CWD, per `-m` semantics)
    [1] C:\\Users\\pj198\\Documents\\redline-os\\src
    [2] C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules
    [3..] Python 3.11 standard-library paths
    [N]  ...\\Lib\\site-packages  (also independently contains the same
         `src` path via the pre-existing `__editable__.redline_os-0.1.0.pth`
         install -- redundant with [1], not a conflict, since both name the
         identical directory)

`import cli` resolves at `sys.path[1]` (the repository `src` copy), ahead
of both the CWD entry (empty in this workspace today) and the redundant
site-packages entry. `python -m cli.main --help` was exercised directly
against this exact PYTHONPATH/CWD combination during construction and
exited 0, printing the CLI's own top-level help — a read-only,
non-Resolve-contacting invocation (argparse help text only; no
`ApplicationServices` composition, no Resolve/DB touch occurs before
`--help` short-circuits).

This module treats that empirical finding as a fact to re-verify at every
future invocation, not as a standing guarantee — hence `verify_module_provenance()`
spawning a fresh subprocess with the exact target environment every time,
rather than trusting a cached or documented conclusion.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Iterable, Mapping

CANONICAL_REPOSITORY_SRC = Path(r"C:\Users\pj198\Documents\redline-os\src")
RESOLVE_SCRIPT_MODULES_PATH = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
)
EXPECTED_PYTHON_EXECUTABLE = Path(
    r"C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe"
)
EXPECTED_WORKSPACE_CWD = Path(r"C:\Users\pj198\RedlineOSLive\RLC-E9901")

TARGET_MODULES: tuple[str, ...] = ("cli", "redline_core")

# A short, fixed, reviewable probe program. It imports ONLY the two target
# modules (never `mcp_server`, never anything Resolve-related) and reports
# each module's resolved `__file__` and `__path__` as JSON on stdout. A
# static test asserts this exact string contains neither "Resolve" nor
# "DaVinciResolveScript".
_PROVENANCE_PROBE_SOURCE = """
import importlib
import json

report = {}
for name in ("cli", "redline_core"):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        report[name] = {"imported": False, "error_type": type(exc).__name__}
        continue
    report[name] = {
        "imported": True,
        "file": getattr(module, "__file__", None),
        "path": list(getattr(module, "__path__", []) or []),
    }
print(json.dumps(report))
"""


class ProvenanceCheckError(RuntimeError):
    """Fail-closed module-provenance error with a machine-readable classification."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


def build_pythonpath(
    *,
    repository_src: Path = CANONICAL_REPOSITORY_SRC,
    resolve_modules: Path = RESOLVE_SCRIPT_MODULES_PATH,
) -> str:
    """Return the exact two-entry PYTHONPATH the future `render queue` command needs.

    Repository `src` is listed first (so Redline OS's own code takes
    precedence in the hypothetical case of any future name collision with
    something under the Resolve Modules directory); the Resolve scripting
    Modules directory is second, required for `ResolveScriptAdapter.connect()`'s
    own local `import DaVinciResolveScript` to succeed. This function never
    imports or contacts Resolve itself -- it only builds a path string.
    """

    return os.pathsep.join([str(repository_src), str(resolve_modules)])


def build_provenance_check_environment(
    base_env: Mapping[str, str] | None = None,
    *,
    repository_src: Path = CANONICAL_REPOSITORY_SRC,
    resolve_modules: Path = RESOLVE_SCRIPT_MODULES_PATH,
) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    env["PYTHONPATH"] = build_pythonpath(repository_src=repository_src, resolve_modules=resolve_modules)
    return env


def verify_module_provenance(
    *,
    python_executable: Path = EXPECTED_PYTHON_EXECUTABLE,
    cwd: Path = EXPECTED_WORKSPACE_CWD,
    env: Mapping[str, str] | None = None,
    expected_src_root: Path = CANONICAL_REPOSITORY_SRC,
    target_modules: Iterable[str] = TARGET_MODULES,
    timeout: int = 30,
) -> dict:
    """Spawn a fresh subprocess and prove `cli`/`redline_core` resolve under `expected_src_root`.

    Fails closed (raises ProvenanceCheckError) on: a non-zero probe exit, a
    malformed probe response, an import failure for either target module, a
    missing `__file__`, or a resolved path that is not under
    `expected_src_root`. Never imports or contacts Resolve: the probe
    program imports only `cli` and `redline_core`.

    Returns the full per-module provenance report on success.
    """

    effective_env = dict(env) if env is not None else build_provenance_check_environment()

    result = subprocess.run(
        [str(python_executable), "-c", _PROVENANCE_PROBE_SOURCE],
        cwd=str(cwd),
        env=effective_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise ProvenanceCheckError(
            "provenance_probe_failed",
            "module-provenance probe subprocess exited non-zero",
            details={
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
                "cwd": str(cwd),
            },
        )

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProvenanceCheckError(
            "provenance_probe_output_invalid",
            "module-provenance probe did not return valid JSON",
            details={"stdout": result.stdout.strip()},
        ) from exc

    resolved_root = expected_src_root.resolve()
    for module_name in target_modules:
        entry = report.get(module_name)
        if not isinstance(entry, dict):
            raise ProvenanceCheckError(
                "module_provenance_missing",
                f"probe report is missing an entry for module: {module_name}",
                details={"module": module_name},
            )
        if entry.get("imported") is not True:
            raise ProvenanceCheckError(
                "module_import_failed",
                f"probe could not import module: {module_name}",
                details={"module": module_name, "error_type": entry.get("error_type")},
            )
        file_value = entry.get("file")
        if not isinstance(file_value, str) or not file_value:
            raise ProvenanceCheckError(
                "module_file_unavailable",
                f"probe reported no usable __file__ for module: {module_name}",
                details={"module": module_name},
            )
        resolved_file = Path(file_value).resolve()
        if not _is_relative_to(resolved_file, resolved_root):
            raise ProvenanceCheckError(
                "module_provenance_mismatch",
                f"module {module_name!r} did not resolve under the canonical repository src root",
                details={
                    "module": module_name,
                    "resolved_file": str(resolved_file),
                    "expected_root": str(resolved_root),
                },
            )

    return report


def _is_relative_to(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Non-Resolve-contacting module-provenance check for cli/redline_core."
    )
    parser.add_argument("--python-executable", type=Path, default=EXPECTED_PYTHON_EXECUTABLE)
    parser.add_argument("--cwd", type=Path, default=EXPECTED_WORKSPACE_CWD)
    parser.add_argument("--expected-src-root", type=Path, default=CANONICAL_REPOSITORY_SRC)
    args = parser.parse_args(argv)

    try:
        report = verify_module_provenance(
            python_executable=args.python_executable,
            cwd=args.cwd,
            expected_src_root=args.expected_src_root,
        )
    except ProvenanceCheckError as exc:
        _print_json({"result": "stopped", "error": exc.to_dict()})
        return 2

    _print_json({"result": "passed", "report": report})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
