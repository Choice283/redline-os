"""RLC-E9901 Broadcast Master read-only snapshot preflight — execution layer.

Construction status
--------------------
Construction and static-review artifact only. Nothing in this module
contacts DaVinci Resolve, queues a render, or mutates repository, database,
or workspace state when imported.

Reviewed live boundary (corrected, see Rev3 "Documentation correction"
below): `run_authorized_rlc_e9901_preflight()` is the only function in this
module capable of a live subprocess launch. It IS reachable through this
module's own CLI, via the `run-live-preflight` subcommand -- that
subcommand exists precisely to be that reviewed boundary, by design, not
as an oversight. What is true, and is the actual safety property this
construction/static-review mission relies on, is narrower and exact: this
mission's own work -- writing this source, its tests, and its evidence --
never itself invokes `run-live-preflight`, `run_authorized_rlc_e9901_preflight()`,
or any other path that would launch the collector. A separate, explicit
founder authorization is required before any future invocation of that
subcommand.

Rev3 corrections (independent review, Findings 1/3/4 + documentation)
--------------------------------------------------------------------------

**Finding 1 — checker imported before the repository gate.** Rev2 still
had `from scripts import rlc_e9901_preflight_assertion as checker` at
module import time, meaning checker code executed before
`verify_repository_checkpoint()` could ever run, and did so through
ordinary `sys.path`-based package resolution (ambiguous: some other
same-named `scripts` package earlier on `sys.path` could have been loaded
instead). This revision imports NOTHING from `scripts.*` at module level.
`_load_verified_checker_module()` loads the checker only after the
repository checkpoint and collector-identity checks have already passed,
using `importlib.util.spec_from_file_location()` against the exact
canonical absolute path -- never through `sys.path` package resolution --
and only after independently verifying the checker's own on-disk bytes
against a SHA-256 recorded at review time (`verify_checker_source_identity()`,
the same technique `verify_collector_source_identity()` already uses for
the collector). The loaded module's own `__file__` is re-checked against
the canonical path after loading, as a second confirmation.

**Finding 3 — evidence output path not strongly bound.** Rev2 accepted
relative paths and did not prohibit writing evidence into protected
Redline locations. `_canonicalize_and_validate_evidence_path()` now
requires an absolute path, resolves it, rejects it if it falls inside any
of `CANONICAL_REPOSITORY_ROOT`, the RLC-E9901 workspace
(`C:\\Users\\pj198\\RedlineOSLive\\RLC-E9901`), the runtime directory
(`C:\\Users\\pj198\\RedlineOSLive\\Runtime`), or (Rev4 correction,
independent review Finding 2 -- see below) the separately-located
preserved Redline evidence directory
(`C:\\Users\\pj198\\RedlineOSLive\\Evidence`), and only then applies the
existing freshness rules (must not already exist; parent must already
exist; never auto-created). The one canonicalized `Path` this function
returns is threaded through `_prepare_verified_invocation()` into both
`build_snapshot_command()` and, later, the post-launch existence/read/hash
steps -- the exact same `Path` object is used throughout, so no
substitution between capture and evaluation is structurally possible.

**Finding 4 — collector failure evidence captured then discarded.**
Rev2's `Rlce9901PreflightResult` carried only a bare exit code on failure.
This revision adds `collector_stdout`/`collector_stderr` (preserved
verbatim on every outcome where the collector process actually ran, so a
human reviewer can independently read the collector's own structured
`SnapshotError` JSON from stderr -- this module never reinterprets that
content into a stronger or different claim), plus explicit
`collector_launch_error` (set when the subprocess could not even start)
and `collector_timed_out` (set on a `subprocess.TimeoutExpired`, with
whatever partial stdout/stderr Python captured before the timeout
preserved). A separate, structured outcome exists for: launch failure,
timeout, non-zero exit, missing output after a zero exit, an output file
that exists but cannot be read, and output bytes that are not valid
UTF-8/JSON. None of these ever retries the collector, and none of them
deletes, rewrites, or repairs whatever (if anything) exists at the
evidence path.

Rev4 corrections (independent review)
------------------------------------------

**Finding 1 — Resolve `GetVersion()` normalization was wrong.** Corrected
entirely in the offline checker (`scripts/rlc_e9901_preflight_assertion.py`'s
`_normalized_version_list()`), not in this module -- see that file's own
Rev4 docstring note. Recorded here because it affects what an "overall
PASS" from `run_authorized_rlc_e9901_preflight()` actually proves: the
Resolve product/version identity leg of that claim.

**Finding 2 — preserved evidence root not protected.** Rev3's
`PROTECTED_EVIDENCE_ROOTS` inaccurately claimed the RLC-E9901 workspace
exclusion also covered "the preserved assembly evidence" -- it does not.
The actual preserved Redline evidence directory is a separate location,
`C:\\Users\\pj198\\RedlineOSLive\\Evidence`, outside the RLC-E9901
workspace tree entirely, and was not protected at all until this
revision. It is now a fourth entry in `PROTECTED_EVIDENCE_ROOTS`, and the
inaccurate "one exclusion covers both" claim has been removed from this
module's docstring and from `PROTECTED_EVIDENCE_ROOTS`'s own comment.

Why this replaces reliance on the existing Control/Production runbook
-----------------------------------------------------------------------
`scripts/phase14_live_snapshot_runbook.ps1` and the authorization-manifest
schema documented in `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md` §14
are both hard-bound to a two-context `Control`/`Production` comparison
shape. RLC-E9901's preflight is a single-context inspection, so reusing
that layer as-is is not possible, and editing either would be a source
change to already-published, already-reviewed artifacts. This module
wraps the unmodified collector from the outside instead.

Safety design
--------------
* No `DaVinciResolveScript` import or reference anywhere in this module.
* No import of the collector module (`phase14_resolve_context_snapshot`)
  anywhere in this module, under any code path.
* No import of the checker module (`rlc_e9901_preflight_assertion`) at
  module level, or under any code path before
  `verify_repository_checkpoint()` and `verify_collector_source_identity()`
  have both already succeeded -- see Finding 1 above.
* Exactly one `subprocess.run(...)` call site launches the collector,
  inside `run_authorized_rlc_e9901_preflight()` -- no retry loop, no
  exception-handling branch that re-attempts it.
* Every check in `_prepare_verified_invocation()` runs, in order, before
  that one `subprocess.run` call is ever reached; any failure raises
  `PreflightContractError` and the collector is never launched.
* No cleanup, deletion, or repair is attempted on any failure path.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

MISSION = "RLC-E9901 Broadcast Master Read-Only Snapshot Preflight — Execution Layer"

# ---------------------------------------------------------------------------
# Canonical bindings. These are the values this execution layer was
# constructed and reviewed against. A future authorized invocation supplies
# the mutable per-run values (authorized commit, evidence output path)
# through Rlce9901SnapshotAuthorization; everything below is fixed by this
# source revision.
# ---------------------------------------------------------------------------

CANONICAL_REPOSITORY_ROOT = Path(r"C:\Users\pj198\Documents\redline-os")
CANONICAL_ORIGIN_URL = "git@github.com:Choice283/redline-os.git"
CANONICAL_BRANCH = "master"
SNAPSHOT_SOURCE_RELATIVE_PATH = Path("scripts") / "phase14_resolve_context_snapshot.py"
CHECKER_SOURCE_RELATIVE_PATH = Path("scripts") / "rlc_e9901_preflight_assertion.py"

# Locations evidence must never be written into or under (Finding 3;
# Evidence entry added under Rev4 Finding 2 -- the preserved Redline
# evidence directory is a separate location from the RLC-E9901 workspace,
# not covered by that entry alone).
PROTECTED_EVIDENCE_ROOTS: tuple[Path, ...] = (
    CANONICAL_REPOSITORY_ROOT,
    Path(r"C:\Users\pj198\RedlineOSLive\RLC-E9901"),
    Path(r"C:\Users\pj198\RedlineOSLive\Evidence"),
    Path(r"C:\Users\pj198\RedlineOSLive\Runtime"),
)

EXPECTED_PYTHON_EXECUTABLE = Path(
    r"C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe"
)
EXPECTED_PYTHON_VERSION = (3, 11, 9)

RESOLVE_SCRIPT_API_PATH = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
)
RESOLVE_SCRIPT_LIB_PATH = Path(
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
)
RESOLVE_SCRIPT_MODULES_PATH = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
)

EXPECTED_PROJECT_NAME = "RLC-E9901_MASTER"
EXPECTED_TIMELINE_NAME = "RLC-E9901_TIMELINE"

# Recorded independently at the time this execution layer was constructed
# and reviewed, by computing hashlib.sha256() directly over each file's raw
# bytes -- never by importing either module. verify_collector_source_identity()
# and verify_checker_source_identity() compare live disk bytes against
# these values every time this layer runs, so a future silent edit to
# either file is caught rather than silently trusted.
_REVIEWED_EXECUTION_REVISION_ID = "phase14.1-live-interlock-construction-rev8"
_REVIEWED_SNAPSHOT_SOURCE_SHA256 = (
    "1b600a26dd54fd6625a9100348c32f2ea4decf9cf02407f9a9344a8c1beeb038"
)
_REVIEWED_CHECKER_SOURCE_SHA256 = (
    "aa915a9c567919e545c1f966fe8ab3959ec547b680dc32701338313c5d3302df"
)

_REVIEWED_EXECUTION_REVISION_ID_PATTERN = re.compile(
    re.escape(f'EXECUTION_REVISION_ID = "{_REVIEWED_EXECUTION_REVISION_ID}"')
)


class PreflightContractError(RuntimeError):
    """Fail-closed execution-layer error with a machine-readable classification."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


@dataclass(frozen=True)
class Rlce9901SnapshotAuthorization:
    """Per-run values a future founder authorization must bind explicitly.

    `evidence_output_path` need not be pre-canonicalized by the caller --
    `_canonicalize_and_validate_evidence_path()` resolves and validates it;
    every downstream step uses that one returned canonical Path, never this
    field directly.
    """

    authorized_commit: str
    evidence_output_path: Path


@dataclass(frozen=True)
class CapturedOutput:
    """JSON-safe, lossless representation of one captured subprocess stream.

    Rev5 correction (independent review, Finding 2): on Python 3.11,
    `subprocess.TimeoutExpired.stdout`/`.stderr` can carry raw `bytes` even
    when `subprocess.run(..., text=True)` was used -- `text=True` reliably
    governs a *completed* `CompletedProcess`'s `stdout`/`stderr`, but not
    necessarily the partial output attached to a timeout exception. Rev4
    stored whatever value it received directly in a `str | None` field and
    relied on `json.dumps(..., default=str)` to paper over a `bytes` value
    by falling back to Python's `repr()` (`"b'hello\\xff'"`) -- lossy,
    non-deterministic-looking, and not the explicit, verbatim evidence
    representation this contract claims to provide.

    `present` distinguishes "this stream was never captured at all" (e.g.
    a launch failure that never reached a subprocess) from "captured, and
    happened to be empty" (`present=True`, `byte_length=0`). When the
    captured value decodes as valid UTF-8 -- true for every ordinary text
    stream, and the overwhelmingly common case -- `encoding` is `"utf-8"`
    and `text` holds the exact decoded string. When it does not (or when
    non-UTF-8 `bytes` are received directly, as `TimeoutExpired` can
    produce), the raw bytes are preserved losslessly as `encoding="base64"`
    plus `base64_data`, never coerced through `str(bytes)`. `sha256` and
    `byte_length` are always populated when `present` is `True`, computed
    over the exact original bytes, so a reviewer can independently verify
    integrity regardless of which encoding branch was used.
    """

    present: bool
    encoding: str | None  # "utf-8" | "base64" | None (None only when present is False)
    text: str | None
    base64_data: str | None
    sha256: str | None
    byte_length: int | None

    def to_dict(self) -> dict:
        return {
            "present": self.present,
            "encoding": self.encoding,
            "text": self.text,
            "base64_data": self.base64_data,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
        }


_ABSENT_CAPTURED_OUTPUT = CapturedOutput(
    present=False, encoding=None, text=None, base64_data=None, sha256=None, byte_length=None
)


def _normalize_captured_output(value: str | bytes | bytearray | None) -> CapturedOutput:
    """Normalize one raw subprocess-captured stream into a JSON-safe `CapturedOutput`.

    Applied uniformly to every `collector_stdout`/`collector_stderr`
    construction site in `run_authorized_rlc_e9901_preflight()` -- both the
    `TimeoutExpired`-sourced values (the only ones actually at risk of
    being `bytes`) and the ordinary `CompletedProcess.stdout`/`.stderr`
    values (always `str`, guaranteed by `text=True`, and unaffected by
    this normalization: a `str` input always normalizes to
    `encoding="utf-8"` with the identical text preserved verbatim). This
    keeps one single, uniformly JSON-safe representation across every
    outcome path rather than a str-shaped field for most paths and a
    differently-shaped value only for timeouts.
    """

    if value is None:
        return _ABSENT_CAPTURED_OUTPUT
    if isinstance(value, str):
        raw_bytes = value.encode("utf-8")
        return CapturedOutput(
            present=True, encoding="utf-8", text=value, base64_data=None,
            sha256=hashlib.sha256(raw_bytes).hexdigest(), byte_length=len(raw_bytes),
        )
    if isinstance(value, (bytes, bytearray)):
        raw_bytes = bytes(value)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return CapturedOutput(
                present=True, encoding="base64", text=None,
                base64_data=base64.b64encode(raw_bytes).decode("ascii"),
                sha256=hashlib.sha256(raw_bytes).hexdigest(), byte_length=len(raw_bytes),
            )
        return CapturedOutput(
            present=True, encoding="utf-8", text=text, base64_data=None,
            sha256=hashlib.sha256(raw_bytes).hexdigest(), byte_length=len(raw_bytes),
        )
    raise TypeError(f"unsupported captured subprocess output type: {type(value).__name__}")


@dataclass(frozen=True)
class Rlce9901PreflightResult:
    """The one combined result of a live preflight attempt (Defect 4 / Finding 4).

    `collector_stdout`/`collector_stderr` preserve the collector's own raw
    output verbatim (via `CapturedOutput`, see Rev5 Finding 2 above)
    whenever the process actually ran, so a human reviewer can
    independently read its structured `SnapshotError` classification --
    this module never reinterprets that content into a stronger claim.
    """

    collector_launch_error: str | None
    collector_timed_out: bool
    collector_exit_code: int | None
    collector_stdout: CapturedOutput
    collector_stderr: CapturedOutput
    snapshot_path: str
    snapshot_sha256: str | None
    offline_result: Any  # rlc_e9901_preflight_assertion.OfflinePreflightResult, or None
    stop_reason: str | None

    @property
    def snapshot_capture_status(self) -> str:
        if self.stop_reason is not None:
            return self.stop_reason
        assert self.offline_result is not None
        return self.offline_result.snapshot_capture_status

    @property
    def render_preflight_status(self) -> str:
        if self.stop_reason is not None:
            return "not_evaluated"
        assert self.offline_result is not None
        return self.offline_result.render_preflight_status

    def to_dict(self) -> dict:
        return {
            "collector_launch_error": self.collector_launch_error,
            "collector_timed_out": self.collector_timed_out,
            "collector_exit_code": self.collector_exit_code,
            "collector_stdout": self.collector_stdout.to_dict(),
            "collector_stderr": self.collector_stderr.to_dict(),
            "snapshot_path": self.snapshot_path,
            "snapshot_sha256": self.snapshot_sha256,
            "snapshot_capture_status": self.snapshot_capture_status,
            "render_preflight_status": self.render_preflight_status,
            "stop_reason": self.stop_reason,
            "offline_result": self.offline_result.to_dict() if self.offline_result is not None else None,
        }


def verify_repository_checkpoint(
    authorization: Rlce9901SnapshotAuthorization, *, repository_root: Path = CANONICAL_REPOSITORY_ROOT
) -> None:
    """Fail closed unless the live repository matches the complete authorized checkpoint.

    Checks, in order: repository root, branch name, HEAD commit, origin
    URL, `origin/master` (must equal the same authorized commit as HEAD),
    working-tree cleanliness, index cleanliness, and stash emptiness.
    Read-only `git` subprocess calls only.
    """

    toplevel = _run_git(["rev-parse", "--show-toplevel"], repository_root=repository_root)
    if Path(toplevel).resolve() != repository_root.resolve():
        raise PreflightContractError(
            "repository_root_mismatch",
            "git repository root does not match the canonical repository root",
            details={"expected": str(repository_root), "actual": toplevel},
        )

    branch = _run_git(["branch", "--show-current"], repository_root=repository_root)
    if branch != CANONICAL_BRANCH:
        raise PreflightContractError(
            "branch_mismatch",
            "current branch is not the canonical branch",
            details={"expected": CANONICAL_BRANCH, "actual": branch},
        )

    head = _run_git(["rev-parse", "HEAD"], repository_root=repository_root)
    if head != authorization.authorized_commit:
        raise PreflightContractError(
            "head_commit_mismatch",
            "current HEAD does not match the authorized commit",
            details={"expected": authorization.authorized_commit, "actual": head},
        )

    origin_url = _run_git(["remote", "get-url", "origin"], repository_root=repository_root)
    if origin_url != CANONICAL_ORIGIN_URL:
        raise PreflightContractError(
            "origin_url_mismatch",
            "git remote 'origin' does not match the canonical origin URL",
            details={"expected": CANONICAL_ORIGIN_URL, "actual": origin_url},
        )

    origin_master = _run_git(["rev-parse", "origin/master"], repository_root=repository_root)
    if origin_master != authorization.authorized_commit:
        raise PreflightContractError(
            "origin_master_mismatch",
            "origin/master does not equal the authorized commit",
            details={"expected": authorization.authorized_commit, "actual": origin_master},
        )

    status = _run_git(["status", "--short"], repository_root=repository_root)
    if status != "":
        raise PreflightContractError(
            "working_tree_not_clean",
            "git working tree is not clean",
            details={"git_status_short": status},
        )

    staged = _run_git(["diff", "--cached", "--name-only"], repository_root=repository_root)
    if staged != "":
        raise PreflightContractError(
            "index_not_clean",
            "git index has staged changes",
            details={"staged_files": staged.splitlines()},
        )

    stash = _run_git(["stash", "list"], repository_root=repository_root)
    if stash != "":
        raise PreflightContractError(
            "stash_not_empty",
            "git stash is not empty",
            details={"stash_list": stash.splitlines()},
        )


def _verify_source_identity(
    *, relative_path: Path, reviewed_sha256: str, code_prefix: str, repository_root: Path
) -> bytes:
    resolved_path = repository_root / relative_path
    try:
        raw_bytes = resolved_path.read_bytes()
    except OSError as exc:
        raise PreflightContractError(
            f"{code_prefix}_source_unreadable",
            f"{code_prefix} source file could not be read from disk",
            details={"path": str(resolved_path), "error_type": type(exc).__name__},
        ) from exc

    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != reviewed_sha256:
        raise PreflightContractError(
            f"{code_prefix}_source_hash_mismatch",
            f"{code_prefix} source file bytes on disk do not match the reviewed SHA-256",
            details={"path": str(resolved_path), "expected": reviewed_sha256, "actual": digest},
        )
    return raw_bytes


def verify_collector_source_identity(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> str:
    """Fail closed unless the collector's on-disk bytes match the reviewed SHA-256.

    Reads the collector's raw bytes directly from disk by its canonical
    path. NEVER imports, executes, or otherwise runs any collector code.
    As a secondary, purely textual defense-in-depth signal (redundant with
    the hash once it already matches), also confirms the expected
    `EXECUTION_REVISION_ID` assignment literally appears in the source
    bytes.
    """

    raw_bytes = _verify_source_identity(
        relative_path=SNAPSHOT_SOURCE_RELATIVE_PATH,
        reviewed_sha256=_REVIEWED_SNAPSHOT_SOURCE_SHA256,
        code_prefix="collector",
        repository_root=repository_root,
    )
    try:
        source_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreflightContractError(
            "collector_source_not_utf8",
            "collector source file is not valid UTF-8 despite a matching SHA-256",
            details={"error_type": type(exc).__name__},
        ) from exc
    if not _REVIEWED_EXECUTION_REVISION_ID_PATTERN.search(source_text):
        raise PreflightContractError(
            "collector_execution_revision_id_not_found",
            "reviewed EXECUTION_REVISION_ID assignment was not found verbatim in collector source",
            details={"expected_revision_id": _REVIEWED_EXECUTION_REVISION_ID},
        )
    return hashlib.sha256(raw_bytes).hexdigest()


def verify_checker_source_identity(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> str:
    """Fail closed unless the offline checker's on-disk bytes match the reviewed SHA-256.

    Reads the checker's raw bytes directly from disk by its canonical
    path. Called BEFORE `_load_verified_checker_module()` ever loads or
    executes the checker (Finding 1) -- this function itself never
    executes the checker either, it only hashes its bytes.
    """

    return hashlib.sha256(
        _verify_source_identity(
            relative_path=CHECKER_SOURCE_RELATIVE_PATH,
            reviewed_sha256=_REVIEWED_CHECKER_SOURCE_SHA256,
            code_prefix="checker",
            repository_root=repository_root,
        )
    ).hexdigest()


def _load_verified_checker_module(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> Any:
    """Load the offline checker module, but ONLY after its source identity is verified.

    Loaded by its exact canonical absolute path via `importlib.util`, never
    through `sys.path`-based package resolution (Finding 1: ambiguous
    resolution could otherwise load a same-named module from somewhere
    else on `sys.path`). This function must only ever be called after
    `verify_repository_checkpoint()` has already succeeded -- see
    `_prepare_verified_invocation()`, the single caller.
    """

    verify_checker_source_identity(repository_root)
    canonical_path = (repository_root / CHECKER_SOURCE_RELATIVE_PATH).resolve()

    module_name = "rlc_e9901_preflight_assertion_verified"
    spec = importlib.util.spec_from_file_location(module_name, canonical_path)
    if spec is None or spec.loader is None:
        raise PreflightContractError(
            "checker_module_spec_unavailable",
            "could not build an import spec for the checker module from its canonical path",
            details={"path": str(canonical_path)},
        )

    module = importlib.util.module_from_spec(spec)
    # Registration under this exact, distinct module name is required for
    # the checker's own `@dataclass` decorators to resolve their owning
    # module via `sys.modules[cls.__module__]` during class creation -- a
    # standard requirement of `importlib.util`'s manual-load pattern, not a
    # relaxation of "avoid ambiguous sys.path resolution": this name is
    # never looked up via `sys.path`, only ever set and read back by us.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del sys.modules[module_name]
        raise PreflightContractError(
            "checker_module_load_failed",
            "checker module raised while being loaded from its canonical path",
            details={"path": str(canonical_path), "error_type": type(exc).__name__},
        ) from exc

    loaded_file = Path(getattr(module, "__file__", "")).resolve() if getattr(module, "__file__", None) else None
    if loaded_file != canonical_path:
        raise PreflightContractError(
            "checker_module_path_mismatch",
            "loaded checker module's own __file__ does not match the canonical path it was loaded from",
            details={"expected": str(canonical_path), "actual": str(loaded_file)},
        )

    return module


def verify_python_interpreter(
    python_executable: Path = EXPECTED_PYTHON_EXECUTABLE, *, timeout: int = 30
) -> None:
    """Fail closed unless `python_executable` is exactly Python 3.11.9."""

    probe_source = (
        "import json, sys; "
        "print(json.dumps({'executable': sys.executable, "
        "'version': list(sys.version_info[:3])}))"
    )
    result = subprocess.run(
        [str(python_executable), "-c", probe_source],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise PreflightContractError(
            "python_interpreter_probe_failed",
            "candidate Python interpreter could not be probed",
            details={"executable": str(python_executable), "stderr": result.stderr.strip()},
        )
    try:
        reported = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightContractError(
            "python_interpreter_probe_output_invalid",
            "candidate Python interpreter probe did not return valid JSON",
        ) from exc

    reported_executable = Path(reported.get("executable", "")).resolve()
    if reported_executable != python_executable.resolve():
        raise PreflightContractError(
            "python_interpreter_path_mismatch",
            "candidate interpreter's own sys.executable does not match the requested path",
            details={"expected": str(python_executable), "actual": str(reported_executable)},
        )

    reported_version = tuple(reported.get("version", []))
    if reported_version != EXPECTED_PYTHON_VERSION:
        raise PreflightContractError(
            "python_interpreter_version_mismatch",
            "candidate interpreter is not exactly the expected Python version",
            details={"expected": list(EXPECTED_PYTHON_VERSION), "actual": list(reported_version)},
        )


def _canonicalize_and_validate_evidence_path(path: Path) -> Path:
    """Fail closed unless `path` is an absolute, unprotected, fresh evidence path.

    Rules, in order (Finding 3): must be absolute; once resolved, must not
    fall inside any `PROTECTED_EVIDENCE_ROOTS` entry; must not already
    exist (file or directory); its parent directory must already exist
    (never auto-created). Returns the resolved, canonical `Path` -- callers
    must use this return value everywhere downstream, never the original
    argument, so the exact path passed to the collector is the exact path
    later read and hashed.
    """

    if not path.is_absolute():
        raise PreflightContractError(
            "evidence_path_not_absolute",
            f"evidence output path must be absolute: {path}",
        )

    resolved = path.resolve()

    for protected_root in PROTECTED_EVIDENCE_ROOTS:
        protected_resolved = protected_root.resolve()
        if resolved == protected_resolved or resolved.is_relative_to(protected_resolved):
            raise PreflightContractError(
                "evidence_path_in_protected_location",
                f"evidence output path must not be inside a protected location: {protected_root}",
                details={"path": str(resolved), "protected_root": str(protected_root)},
            )

    if resolved.exists():
        if resolved.is_dir():
            raise PreflightContractError(
                "evidence_path_is_directory",
                f"evidence output path is an existing directory, not a file: {resolved}",
            )
        raise PreflightContractError(
            "evidence_path_already_exists",
            f"evidence output path already exists and will not be overwritten: {resolved}",
        )
    if not resolved.parent.is_dir():
        raise PreflightContractError(
            "evidence_parent_directory_missing",
            f"evidence output parent directory does not exist: {resolved.parent}",
        )

    return resolved


def build_snapshot_command(
    authorization: Rlce9901SnapshotAuthorization, resolved_output_path: Path
) -> list[str]:
    """Construct (never execute) the exact one-shot collector invocation.

    `resolved_output_path` must be the value `_canonicalize_and_validate_evidence_path()`
    returned -- never `authorization.evidence_output_path` directly (Finding 3).
    """

    return [
        str(EXPECTED_PYTHON_EXECUTABLE),
        str(CANONICAL_REPOSITORY_ROOT / SNAPSHOT_SOURCE_RELATIVE_PATH),
        "snapshot",
        "--expected-project",
        EXPECTED_PROJECT_NAME,
        "--expected-timeline",
        EXPECTED_TIMELINE_NAME,
        "--output",
        str(resolved_output_path),
        "--execution-authorization",
        _REVIEWED_EXECUTION_REVISION_ID,
    ]


def build_snapshot_subprocess_environment(
    base_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Build the exact environment for the future collector subprocess.

    Deliberately does NOT put the repository `src` directory on PYTHONPATH:
    the collector imports only the Python standard library plus,
    dynamically, `DaVinciResolveScript` -- it never imports `cli`,
    `redline_core`, or `mcp_server`. Only the Resolve scripting Modules
    directory is required on PYTHONPATH. Explicitly overrides PYTHONPATH
    rather than appending to it.
    """

    env = dict(base_env if base_env is not None else os.environ)
    env["PYTHONPATH"] = str(RESOLVE_SCRIPT_MODULES_PATH)
    env["RESOLVE_SCRIPT_API"] = str(RESOLVE_SCRIPT_API_PATH)
    env["RESOLVE_SCRIPT_LIB"] = str(RESOLVE_SCRIPT_LIB_PATH)
    return env


@dataclass(frozen=True)
class _PreparedInvocation:
    command: list[str]
    env: dict[str, str]
    checker_module: Any
    resolved_output_path: Path


def _prepare_verified_invocation(
    authorization: Rlce9901SnapshotAuthorization,
) -> _PreparedInvocation:
    """Run every pre-flight check, then build the collector command/environment.

    This is the ONE place in this module where verification happens before
    any collector contact: both `preview_future_snapshot_invocation()`
    (safe, never launches anything) and `run_authorized_rlc_e9901_preflight()`
    (the one live path) call this function and only this function.

    Verification order: repository checkpoint -> collector source identity
    (hash-only, no import) -> checker source identity + load (hash-only
    verification first, then loaded by exact canonical path -- only after
    the checkpoint above has already passed, per Finding 1) -> Python
    interpreter identity -> evidence output path canonicalization/safety
    (Finding 3). Every check raises PreflightContractError before any
    subprocess is built if it fails.
    """

    verify_repository_checkpoint(authorization)
    verify_collector_source_identity()
    checker_module = _load_verified_checker_module()
    verify_python_interpreter(EXPECTED_PYTHON_EXECUTABLE)
    resolved_output_path = _canonicalize_and_validate_evidence_path(authorization.evidence_output_path)

    command = build_snapshot_command(authorization, resolved_output_path)
    env = build_snapshot_subprocess_environment()
    return _PreparedInvocation(
        command=command, env=env, checker_module=checker_module, resolved_output_path=resolved_output_path
    )


def preview_future_snapshot_invocation(authorization: Rlce9901SnapshotAuthorization) -> dict:
    """Run every pre-flight check and return the exact command/environment -- never launches it."""

    prepared = _prepare_verified_invocation(authorization)
    return {
        "command": prepared.command,
        "cwd": str(CANONICAL_REPOSITORY_ROOT),
        "resolved_output_path": str(prepared.resolved_output_path),
        "env_overrides": build_snapshot_subprocess_environment({}),
        "checker_loaded_from": str(Path(prepared.checker_module.__file__).resolve()),
    }


def run_authorized_rlc_e9901_preflight(
    authorization: Rlce9901SnapshotAuthorization, *, timeout: int = 120
) -> Rlce9901PreflightResult:
    """The ONE live-capable orchestration path.

    This function IS the reviewed live boundary this module's
    `run-live-preflight` CLI subcommand reaches -- see this module's
    docstring. It is not invoked by this construction/static-review
    mission's own work.

    Sequence: `_prepare_verified_invocation()` (repository checkpoint,
    collector hash, checker hash+load, Python interpreter, evidence-path
    canonicalization/safety -- any failure raises before any subprocess
    exists) -> exactly one `subprocess.run` launching the unchanged
    collector -> require exit code `0` -> require the resolved evidence
    path (the exact same path just passed to the collector) to exist ->
    read and SHA-256 those exact bytes -> parse them as JSON -> pass them
    to the verified checker module's `evaluate_offline_preflight()` ->
    return one combined `Rlce9901PreflightResult`.

    No retry: exactly one subprocess launch attempt, whether it succeeds,
    fails, or times out. No cleanup: every failure path returns a
    structured result without deleting, rewriting, or repairing whatever
    (if anything) exists at the evidence path. A snapshot-capture success
    alone can never produce `render_preflight_status == "passed"`.
    """

    prepared = _prepare_verified_invocation(authorization)
    resolved_output_path = prepared.resolved_output_path

    try:
        result = subprocess.run(
            prepared.command,
            cwd=str(CANONICAL_REPOSITORY_ROOT),
            env=prepared.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return Rlce9901PreflightResult(
            collector_launch_error=None,
            collector_timed_out=True,
            collector_exit_code=None,
            collector_stdout=_normalize_captured_output(exc.stdout),
            collector_stderr=_normalize_captured_output(exc.stderr),
            snapshot_path=str(resolved_output_path),
            snapshot_sha256=None,
            offline_result=None,
            stop_reason="collector_timed_out",
        )
    except OSError as exc:
        return Rlce9901PreflightResult(
            collector_launch_error=type(exc).__name__,
            collector_timed_out=False,
            collector_exit_code=None,
            collector_stdout=_ABSENT_CAPTURED_OUTPUT,
            collector_stderr=_ABSENT_CAPTURED_OUTPUT,
            snapshot_path=str(resolved_output_path),
            snapshot_sha256=None,
            offline_result=None,
            stop_reason="collector_launch_failed",
        )

    if result.returncode != 0:
        return Rlce9901PreflightResult(
            collector_launch_error=None,
            collector_timed_out=False,
            collector_exit_code=result.returncode,
            collector_stdout=_normalize_captured_output(result.stdout),
            collector_stderr=_normalize_captured_output(result.stderr),
            snapshot_path=str(resolved_output_path),
            snapshot_sha256=None,
            offline_result=None,
            stop_reason="collector_exit_nonzero",
        )

    if not resolved_output_path.exists():
        return Rlce9901PreflightResult(
            collector_launch_error=None,
            collector_timed_out=False,
            collector_exit_code=0,
            collector_stdout=_normalize_captured_output(result.stdout),
            collector_stderr=_normalize_captured_output(result.stderr),
            snapshot_path=str(resolved_output_path),
            snapshot_sha256=None,
            offline_result=None,
            stop_reason="output_file_missing_after_success",
        )

    try:
        raw_bytes = resolved_output_path.read_bytes()
    except OSError as exc:
        return Rlce9901PreflightResult(
            collector_launch_error=None,
            collector_timed_out=False,
            collector_exit_code=0,
            collector_stdout=_normalize_captured_output(result.stdout),
            collector_stderr=_normalize_captured_output(result.stderr),
            snapshot_path=str(resolved_output_path),
            snapshot_sha256=None,
            offline_result=None,
            stop_reason=f"output_file_unreadable:{type(exc).__name__}",
        )

    snapshot_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    try:
        snapshot_obj = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Rlce9901PreflightResult(
            collector_launch_error=None,
            collector_timed_out=False,
            collector_exit_code=0,
            collector_stdout=_normalize_captured_output(result.stdout),
            collector_stderr=_normalize_captured_output(result.stderr),
            snapshot_path=str(resolved_output_path),
            snapshot_sha256=snapshot_sha256,
            offline_result=None,
            stop_reason="snapshot_bytes_not_valid_json",
        )

    offline_result = prepared.checker_module.evaluate_offline_preflight(snapshot_obj)
    return Rlce9901PreflightResult(
        collector_launch_error=None,
        collector_timed_out=False,
        collector_exit_code=0,
        collector_stdout=_normalize_captured_output(result.stdout),
        collector_stderr=_normalize_captured_output(result.stderr),
        snapshot_path=str(resolved_output_path),
        snapshot_sha256=snapshot_sha256,
        offline_result=offline_result,
        stop_reason=None,
    )


def _run_git(args: list[str], *, repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PreflightContractError(
            "git_command_failed",
            f"git {' '.join(args)} failed",
            details={"args": args, "stderr": result.stderr.strip()},
        )
    return result.stdout.strip()


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=MISSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_checkpoint = subparsers.add_parser(
        "verify-checkpoint", help="Verify the repository checkpoint only. No Resolve contact."
    )
    verify_checkpoint.add_argument("--authorized-commit", required=True)

    subparsers.add_parser(
        "verify-collector",
        help="Verify collector source identity by disk-bytes SHA-256 only, without importing it. No Resolve contact.",
    )

    subparsers.add_parser(
        "verify-checker",
        help="Verify offline checker source identity by disk-bytes SHA-256 only. No Resolve contact.",
    )

    verify_python = subparsers.add_parser(
        "verify-python", help="Verify the Python 3.11.9 interpreter. No Resolve contact."
    )
    verify_python.add_argument("--python-executable", type=Path, default=EXPECTED_PYTHON_EXECUTABLE)

    preview = subparsers.add_parser(
        "preview-snapshot",
        help="Run every pre-flight check and print the exact future invocation. Never launches it. No Resolve contact.",
    )
    preview.add_argument("--authorized-commit", required=True)
    preview.add_argument("--output", type=Path, required=True)

    live = subparsers.add_parser(
        "run-live-preflight",
        help=(
            "THE ONLY live-capable subcommand. Launches the unchanged collector exactly "
            "once and evaluates the result. Requires --authorized-commit and --output. "
            "NOT invoked by the construction/static-review mission this file was written under."
        ),
    )
    live.add_argument("--authorized-commit", required=True)
    live.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "verify-checkpoint":
            verify_repository_checkpoint(
                Rlce9901SnapshotAuthorization(
                    authorized_commit=args.authorized_commit, evidence_output_path=Path(".")
                )
            )
            _print_json({"result": "passed", "check": "repository_checkpoint"})
            return 0
        if args.command == "verify-collector":
            verify_collector_source_identity()
            _print_json({"result": "passed", "check": "collector_source_identity"})
            return 0
        if args.command == "verify-checker":
            verify_checker_source_identity()
            _print_json({"result": "passed", "check": "checker_source_identity"})
            return 0
        if args.command == "verify-python":
            verify_python_interpreter(args.python_executable)
            _print_json({"result": "passed", "check": "python_interpreter"})
            return 0
        if args.command == "preview-snapshot":
            authorization = Rlce9901SnapshotAuthorization(
                authorized_commit=args.authorized_commit, evidence_output_path=args.output
            )
            _print_json(preview_future_snapshot_invocation(authorization))
            return 0
        if args.command == "run-live-preflight":
            authorization = Rlce9901SnapshotAuthorization(
                authorized_commit=args.authorized_commit, evidence_output_path=args.output
            )
            result = run_authorized_rlc_e9901_preflight(authorization)
            _print_json(result.to_dict())
            if result.render_preflight_status == "passed":
                return 0
            if result.stop_reason is not None:
                return 2
            return 3
    except PreflightContractError as exc:
        _print_json({"result": "stopped", "error": exc.to_dict()})
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
