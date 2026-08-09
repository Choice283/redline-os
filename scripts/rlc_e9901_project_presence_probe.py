"""RLC-E9901 read-only Resolve project-presence probe.

Construction status
-------------------
This source is Rev3: a minor-corrections revision addressing the two
Minor findings from the completed Rev2 independent source review --
boolean ``True`` was still accepted as meaningful version evidence
alongside the already-hardened ``False``/``0``/``0.0``/``""``/``None``, and
negative integers were accepted unchallenged in a realistic ``GetVersion()``
list/tuple shape. Both are now rejected (see ``_is_unusable_scalar`` and
``_normalize_version_components``). Rev1 (SHA-256
``56f4f325087370a413d9bc56665b3f3ffbb2b33af6c7e3a7b862690146bfc7c8``) and
Rev2 (SHA-256 ``83eab0bb4df456a8aa6344a3c05e998abcc60f52c621ddf1d3882950e317ff6d``)
are both superseded by this revision; do not treat either predecessor's
execution revision identifier as valid for these source bytes. This source
is a construction, documentation, and static-review revision only. It
remains fail-closed by default: reaching Resolve requires the CLI caller to pass
``--execution-authorization <revision-id>`` on the ``check`` subcommand,
where ``<revision-id>`` must exactly equal ``EXECUTION_REVISION_ID`` below.
That value is immutable for this exact source text: any future source
change requires a new identifier and a new SHA-256, reviewed and bound
together by a separate founder authorization. Founder authorization for
live use must still bind: the exact repository commit, this exact source
SHA-256, this exact ``EXECUTION_REVISION_ID``, and the exact evidence
output path. Minting matching source + identifier is a necessary
precondition, not the authorization itself. This construction mission does
not authorize live execution.

Purpose
-------
Narrow, single-question probe: after a future separate live-execution
authorization, determine and report --

1. whether a DaVinci Resolve scripting connection can be established;
2. Resolve's product identity, if safely available;
3. whether ``RLC-E9901_MASTER`` is absent from the Project Manager's current
   folder (the same folder scope ``ResolveScriptAdapter.duplicate_project``
   uses via ``GetProjectListInCurrentFolder()`` -- Redline OS has no separate
   named "applicable folder"; it always operates on whatever folder is
   current when Resolve connects);
4. whether ``RLC_MASTER_TEMPLATE`` is present in that same folder scope.

This module performs zero mutating Resolve calls. It never calls
``LoadProject``, ``SetCurrentFolder``, ``OpenFolder``, ``CreateProject``, or
any other method capable of changing what project or folder is open, so
there is no cleanup or rollback boundary to define: nothing it does can leave
residual Resolve state behind. Every dynamically-relevant Resolve accessor
this module calls is restricted to a closed, read-only allowlist, mirroring
the pattern established by ``scripts/phase14_resolve_context_snapshot.py``,
scaled down to this probe's single narrow question.

Safety design
-------------
* No Resolve module import occurs at module import time.
* The ``check`` CLI path stops at the execution interlock, before output-path
  validation, before ``DaVinciResolveScript`` import, and before connection,
  unless the caller supplies the exact matching ``--execution-authorization``.
* The output path is validated for pre-existence before Resolve contact and
  is never overwritten: the final write is a same-directory temp file
  followed by a create-only atomic link, so a failure never leaves partial or
  replaced evidence. A fresh, not-yet-existing output path is required for
  every invocation -- this is the probe's one-attempt boundary: a second
  invocation against the same evidence path fails closed before Resolve is
  ever contacted a second time.
* Every Resolve accessor call is restricted to a closed, read-only allowlist.
  No dynamic dispatch of an arbitrary method name ever occurs.
* No project or folder switch is attempted. No project is opened, loaded, or
  saved. No render setting is touched. No render job is created, deleted,
  started, stopped, or cancelled.
* Ambiguous, malformed, incomplete, or repeated project-name evidence fails
  closed rather than being silently coerced into a best-effort answer.
* Successful evidence carries a ``captured_at`` UTC ISO-8601 timestamp (same
  convention as ``scripts/phase14_resolve_context_snapshot.py``'s
  ``utc_now()``), so the evidence file can bind itself to a specific point in
  time without relying on filesystem metadata.
* A type-permitted-but-meaningless scalar (``True``, ``False``, ``0``,
  ``0.0``, ``""``) from a version accessor can never satisfy the "usable
  version observed" gate; only a genuinely meaningful value can. A realistic
  Resolve ``GetVersion()``-style list/tuple of version components is
  narrowly normalized -- non-boolean, non-negative integers and non-empty
  strings only -- rather than rejected outright or accepted unvalidated.
* This probe's evidence is scoped to the Project Manager's current-folder
  state at the moment it runs. See
  ``docs/RLC_E9901_PROJECT_PRESENCE_PROBE_CONTRACT.md`` for the operational
  precondition a future live-build authorization must satisfy for that
  evidence to remain valid.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

MISSION = "RLC-E9901 — Read-Only Resolve Project-Presence Probe"
SCHEMA_VERSION = "1.0"

# Immutable for this exact source revision. A future source change requires a
# new identifier minted together with a new SHA-256, both reviewed together
# and bound to a separate founder authorization for live use. This is a
# deliberate execution interlock, not a credential: its purpose is to require
# the operator to name the exact revision they intend to run, not to resist a
# determined attacker.
EXECUTION_REVISION_ID = "rlc-e9901-project-presence-probe-construction-rev3"
EXECUTION_REVISION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}[A-Za-z0-9]$")

DISPOSABLE_PROJECT_NAME = "RLC-E9901_MASTER"
TEMPLATE_PROJECT_NAME = "RLC_MASTER_TEMPLATE"

# Closed allowlist. Every name this module calls on a live Resolve/ProjectManager
# handle must appear here. A future review must re-approve this exact set
# before any name is added.
READ_ONLY_RESOLVE_METHODS = frozenset(
    {
        "GetProductName",
        "GetVersion",
        "GetVersionString",
        "GetProjectManager",
        "GetProjectListInCurrentFolder",
    }
)

# Explicitly forbidden for this probe. Not exhaustive of the Resolve API --
# exhaustive of what this probe must never call. Consumed by the static test
# suite so an added call is caught even if it does not go through the
# allowlist-checked dispatch helper.
PROHIBITED_RESOLVE_METHODS = frozenset(
    {
        "GetCurrentProject",
        "LoadProject",
        "CloseProject",
        "CreateProject",
        "DeleteProject",
        "SaveProject",
        "SetCurrentFolder",
        "OpenFolder",
        "GetProjectAttributesInCurrentFolder",
        "GetCurrentFolder",
        "CreateFolder",
        "DeleteFolder",
        "GotoRootFolder",
        "GotoParentFolder",
        "ImportProject",
        "ExportProject",
        "RestoreProject",
        "GetCurrentTimeline",
        "SetCurrentTimeline",
        "SetSetting",
        "SetRenderSettings",
        "LoadRenderPreset",
        "AddRenderJob",
        "DeleteRenderJob",
        "DeleteAllRenderJobs",
        "StartRendering",
        "StopRendering",
    }
)


class ProbeError(RuntimeError):
    """Fail-closed probe error with a machine-readable classification.

    ``details`` may only ever contain safe scalar diagnostics (exception type
    names, counts, booleans) -- never raw exception text, a local path, or
    the supplied execution-authorization value.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


def script_sha256(path: Path | None = None) -> str:
    target = path or Path(__file__)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def utc_now() -> str:
    """UTC ISO-8601 timestamp, matching the established Redline OS Phase 14
    read-only probe convention (``scripts/phase14_resolve_context_snapshot.py``'s
    ``utc_now()``), rather than introducing a second timestamp format."""

    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def enforce_execution_interlock(supplied: str | None) -> None:
    """Deliberate execution interlock for live Resolve contact.

    Not authentication and not a secret. Must be called, and must pass,
    before output-path validation, before ``DaVinciResolveScript`` import,
    before Resolve connection, and before output creation. The supplied
    value is never included in a raised error's message or details.
    """

    if supplied is None or supplied == "":
        raise ProbeError(
            "live_execution_authorization_missing",
            "Live execution requires --execution-authorization naming this exact source revision",
        )
    if not EXECUTION_REVISION_ID_PATTERN.fullmatch(supplied):
        raise ProbeError(
            "live_execution_authorization_invalid",
            "Execution authorization value is not a well-formed revision identifier",
        )
    if supplied != EXECUTION_REVISION_ID:
        raise ProbeError(
            "live_execution_revision_mismatch",
            "Execution authorization does not match this source revision's identifier",
        )


def validate_output_path(path: Path) -> None:
    """Fail closed on any pre-existing output path, before Resolve contact.

    This is also the probe's one-attempt boundary: a pre-existing output path
    (from a prior invocation, successful or not) always stops the run before
    Resolve is contacted. The parent directory must already exist; this
    function never creates a directory.
    """

    if path.exists():
        if path.is_dir():
            raise ProbeError(
                "output_path_is_directory",
                f"Output path is an existing directory, not a file: {path}",
            )
        raise ProbeError(
            "output_path_already_exists",
            f"Output path already exists and will not be overwritten: {path}",
        )
    if not path.parent.is_dir():
        raise ProbeError(
            "output_parent_directory_missing",
            f"Output parent directory does not exist: {path.parent}",
        )


def write_json_no_overwrite(path: Path, value: Any) -> None:
    """Write ``value`` as JSON to ``path`` without ever overwriting it.

    Same create-only, fsync-then-atomic-link discipline as
    ``phase14_resolve_context_snapshot.write_json_no_overwrite``: serialize
    fully in memory first, write to a same-directory temp file, fsync, then
    publish via ``os.link`` (raises on an existing destination on both
    Windows and POSIX, unlike a plain rename). Cleanup of the temp file is
    always attempted and never swallowed on failure.
    """

    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    json.loads(text)  # Validate completeness before any disk write.

    validate_output_path(path)

    try:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", suffix="", dir=str(path.parent))
    except OSError as exc:
        raise ProbeError(
            "output_temp_create_failed",
            "Could not create an exclusive temporary output file",
            details={"error_type": type(exc).__name__},
        ) from exc

    tmp_path = Path(tmp_name)
    published = False
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ProbeError(
                "output_write_failed",
                "Could not write and fsync the temporary output file",
                details={"error_type": type(exc).__name__, "published": False},
            ) from exc

        try:
            os.link(tmp_path, path)
            published = True
        except FileExistsError as exc:
            raise ProbeError(
                "output_path_already_exists",
                f"Output path already exists and will not be overwritten: {path}",
                details={"published": False},
            ) from exc
        except OSError as exc:
            raise ProbeError(
                "output_publish_failed",
                "Could not publish the temporary output file to its final path",
                details={"error_type": type(exc).__name__, "published": False},
            ) from exc
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as exc:
            raise ProbeError(
                "output_temp_cleanup_failed",
                (
                    "Output was published but its temporary file could not be removed"
                    if published
                    else "Temporary output file could not be removed after a failed write"
                ),
                details={"error_type": type(exc).__name__, "published": published},
            ) from exc


def connect_resolve_read_only(
    importer: Callable[[str], Any] = importlib.import_module,
) -> Any:
    """Import and connect to Resolve only after a future live contract enables it.

    Every exception this function can raise is a structured ``ProbeError``
    with only a safe exception-type name in its details -- never raw
    exception text or a local path -- so a controlled import or connection
    failure cannot escape ``main()`` as an uncaught traceback.
    """

    try:
        module = importer("DaVinciResolveScript")
    except Exception as exc:
        raise ProbeError(
            "resolve_module_import_failed",
            "Importing DaVinciResolveScript raised",
            details={"error_type": type(exc).__name__},
        ) from exc

    scriptapp = getattr(module, "scriptapp", None)
    if not callable(scriptapp):
        raise ProbeError(
            "resolve_scriptapp_unavailable",
            "DaVinciResolveScript.scriptapp is unavailable",
        )

    try:
        resolve = scriptapp("Resolve")
    except Exception as exc:
        raise ProbeError(
            "resolve_scriptapp_call_failed",
            "DaVinciResolveScript.scriptapp('Resolve') raised",
            details={"error_type": type(exc).__name__},
        ) from exc

    if not resolve:
        raise ProbeError(
            "resolve_connection_failed",
            "DaVinciResolveScript.scriptapp('Resolve') returned no usable handle",
        )
    return resolve


def _call_allowlisted(obj: Any, method_name: str) -> Any:
    if method_name not in READ_ONLY_RESOLVE_METHODS:
        raise ProbeError(
            "accessor_not_allowlisted",
            f"Resolve accessor is not in the approved read-only allowlist: {method_name}",
        )
    try:
        method = getattr(obj, method_name)
    except Exception as exc:
        raise ProbeError(
            "accessor_lookup_failed",
            f"Resolve accessor lookup raised for {method_name}",
            details={"method": method_name, "error_type": type(exc).__name__},
        ) from exc
    if not callable(method):
        raise ProbeError(
            "accessor_unavailable",
            f"Resolve accessor is not callable: {method_name}",
            details={"method": method_name},
        )
    try:
        return method()
    except Exception as exc:
        raise ProbeError(
            "accessor_call_failed",
            f"Resolve accessor raised: {method_name}",
            details={"method": method_name, "error_type": type(exc).__name__},
        ) from exc


def _is_unusable_scalar(value: Any) -> bool:
    """True for exactly the type-permitted scalars that must never satisfy a
    "usable value observed" gate: ``None``, ``""``, ``0``, ``0.0``, and both
    boolean values ``True``/``False``. Rev3 (correcting a gap identified in
    the Rev2 independent review) rejects both booleans: no Resolve version
    accessor has any documented or plausible scenario that legitimately
    returns a bare boolean, for either truth value -- a boolean return from
    ``GetVersion()``/``GetVersionString()`` only ever indicates an anomalous
    or broken bridge, not real version data.

    Type-dispatched rather than a membership/equality check against a tuple,
    so cross-type equality quirks (``0 == False`` is ``True`` in Python) can
    never cause one sentinel's check to accidentally swallow a different,
    legitimately meaningful value.
    """

    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (int, float)):
        return value == 0
    return False


def _normalize_version_components(value: Sequence[Any]) -> str | None:
    """Narrowly normalize a realistic Resolve ``GetVersion()`` list/tuple
    return (documented shape, e.g. ``[19, 0, 3, 7]``) into a stable
    dot-joined string.

    Returns ``None`` (never raises) for an empty sequence, or one containing
    any element that is not a non-boolean, non-negative ``int`` or a
    non-empty ``str`` -- this recognizes exactly the one documented
    realistic shape; it does not broaden accepted element types. Rev3
    (correcting a gap identified in the Rev2 independent review) also
    rejects negative integers: genuine Resolve version components are never
    negative, so a negative value indicates malformed or untrustworthy
    input, not a real version component, and normalizing it anyway would
    produce a version string that only looks legitimate.
    """

    if not value:
        return None
    parts: list[str] = []
    for item in value:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            if item < 0:
                return None
            parts.append(str(item))
        elif isinstance(item, str) and item.strip():
            parts.append(item)
        else:
            return None
    return ".".join(parts)


def _observe_identity(obj: Any, method_name: str) -> dict[str, Any]:
    """Best-effort identity accessor: absence/failure is evidence, not fatal.

    A scalar is only ever classified ``"observed"`` if it is a meaningful,
    non-empty value -- ``True``, ``False``, ``0``, ``0.0``, ``""``, and
    ``None`` are always ``"unavailable"``, never a usable observation, even
    though some are technically permitted Python scalar types (see
    ``_is_unusable_scalar``). A realistic Resolve ``GetVersion()``-style
    list/tuple of version components is narrowly normalized into a
    dot-joined string via ``_normalize_version_components`` rather than
    rejected outright or accepted unvalidated.
    """

    if method_name not in READ_ONLY_RESOLVE_METHODS:
        return {"status": "error", "value": None, "error_type": "AccessorNotAllowlisted"}
    try:
        method = getattr(obj, method_name)
    except Exception as exc:
        return {"status": "error", "value": None, "error_type": type(exc).__name__}
    if not callable(method):
        return {"status": "unavailable", "value": None, "error_type": None}
    try:
        value = method()
    except Exception as exc:
        return {"status": "error", "value": None, "error_type": type(exc).__name__}

    if isinstance(value, (list, tuple)):
        normalized = _normalize_version_components(value)
        if normalized is None:
            return {"status": "error", "value": None, "error_type": type(value).__name__}
        return {"status": "observed", "value": normalized, "error_type": None}

    if _is_unusable_scalar(value):
        return {"status": "unavailable", "value": None, "error_type": None}
    if not isinstance(value, (str, int, float, bool)):
        return {"status": "error", "value": None, "error_type": type(value).__name__}
    return {"status": "observed", "value": value, "error_type": None}


def classify_membership(project_names: Sequence[str], target: str) -> tuple[str, int]:
    """Classify one exact-name lookup against a validated project-name list.

    Returns ``(status, match_count)`` where ``status`` is one of
    ``"present"`` (exactly one exact match), ``"absent"`` (zero matches), or
    ``"ambiguous"`` (more than one exact match -- Resolve project names are
    expected unique within one folder, so this fails closed rather than
    picking one).
    """

    match_count = sum(1 for name in project_names if name == target)
    if match_count == 0:
        return "absent", 0
    if match_count == 1:
        return "present", 1
    return "ambiguous", match_count


def collect_project_presence(resolve: Any) -> dict[str, Any]:
    """Collect one fail-closed project-presence observation from an injected
    Resolve handle.

    This function does not import the Resolve module. Production use is not
    authorized by this construction mission; mocked unit tests may inject
    fake handles to exercise the logic.
    """

    session = {
        "product_name": _observe_identity(resolve, "GetProductName"),
        "version": _observe_identity(resolve, "GetVersion"),
        "version_string": _observe_identity(resolve, "GetVersionString"),
    }
    has_usable_version = any(
        session[key]["status"] == "observed" for key in ("version_string", "version")
    )
    if not has_usable_version:
        raise ProbeError(
            "resolve_version_unavailable",
            "Resolve did not expose a usable version through the approved accessors",
        )

    project_manager = _call_allowlisted(resolve, "GetProjectManager")
    if not project_manager:
        raise ProbeError(
            "project_manager_missing", "Resolve returned no usable project manager"
        )

    raw_project_list = _call_allowlisted(project_manager, "GetProjectListInCurrentFolder")
    if raw_project_list is None or raw_project_list is False:
        raw_project_list = []
    if not isinstance(raw_project_list, (list, tuple)):
        raise ProbeError(
            "invalid_project_list",
            "GetProjectListInCurrentFolder() did not return a list",
            details={"value_type": type(raw_project_list).__name__},
        )
    project_names: list[str] = []
    for index, name in enumerate(raw_project_list):
        if not isinstance(name, str) or not name.strip():
            raise ProbeError(
                "invalid_project_list_entry",
                "GetProjectListInCurrentFolder() returned a non-string or empty entry",
                details={"index": index, "value_type": type(name).__name__},
            )
        project_names.append(name)

    disposable_status, disposable_count = classify_membership(project_names, DISPOSABLE_PROJECT_NAME)
    template_status, template_count = classify_membership(project_names, TEMPLATE_PROJECT_NAME)

    if disposable_status == "ambiguous":
        raise ProbeError(
            "disposable_project_ambiguous",
            f"More than one project named '{DISPOSABLE_PROJECT_NAME}' was found",
            details={"match_count": disposable_count},
        )
    if template_status == "ambiguous":
        raise ProbeError(
            "template_project_ambiguous",
            f"More than one project named '{TEMPLATE_PROJECT_NAME}' was found",
            details={"match_count": template_count},
        )

    if disposable_status == "absent" and template_status == "present":
        overall_gate = "ready_for_live_build_authorization_review"
    elif disposable_status == "present" and template_status == "present":
        overall_gate = "blocked_disposable_project_present"
    elif disposable_status == "absent" and template_status == "absent":
        overall_gate = "blocked_template_absent"
    else:
        overall_gate = "blocked_disposable_present_and_template_absent"

    return {
        "schema_version": SCHEMA_VERSION,
        "mission": MISSION,
        "execution_revision_id": EXECUTION_REVISION_ID,
        "captured_at": utc_now(),
        "session": session,
        "project_list_count": len(project_names),
        "project_names": sorted(project_names),
        "disposable_project": {
            "name": DISPOSABLE_PROJECT_NAME,
            "status": disposable_status,
            "match_count": disposable_count,
        },
        "template_project": {
            "name": TEMPLATE_PROJECT_NAME,
            "status": template_status,
            "match_count": template_count,
        },
        "overall_gate": overall_gate,
        "probe_complete": True,
        "interpretation_limits": [
            "This probe never opens, loads, or duplicates any project.",
            "Presence/absence is scoped to the Project Manager's current folder only, "
            "matching the same scope ResolveScriptAdapter.duplicate_project() uses.",
            "A completed 'blocked' classification is not a probe failure; it is evidence.",
            "This result does not authorize redline build or any Resolve mutation.",
        ],
    }


def run_check_command(args: argparse.Namespace) -> int:
    # These two checks must remain, in this order, before connect_resolve_read_only().
    enforce_execution_interlock(args.execution_authorization)
    validate_output_path(args.output)
    resolve = connect_resolve_read_only()
    result = collect_project_presence(resolve)
    write_json_no_overwrite(args.output, result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=MISSION)
    parser.add_argument(
        "--print-sha256",
        action="store_true",
        help="Print the source SHA-256 and exit without Resolve contact.",
    )
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser(
        "check",
        help=(
            "Fail-closed by default. Requires --execution-authorization naming "
            "the exact source revision identifier to reach Resolve."
        ),
    )
    check.add_argument("--output", type=Path, required=True)
    check.add_argument(
        "--execution-authorization",
        required=False,
        default=None,
        help=(
            "Deliberate execution interlock, not a credential: must exactly equal "
            "this source revision's EXECUTION_REVISION_ID. Missing, malformed, or "
            "mismatched values stop before any Resolve import or connection."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.print_sha256:
        print(script_sha256())
        return 0
    if args.command is None:
        parser.error("a command is required unless --print-sha256 is used")
    try:
        if args.command == "check":
            return run_check_command(args)
        raise ProbeError("unsupported_command", f"Unsupported command: {args.command}")
    except ProbeError as exc:
        print(json.dumps({"result": "stopped", "error": exc.to_dict()}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
