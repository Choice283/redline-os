"""RLC-E9901 Broadcast Master one-shot queue-attempt harness — execution layer.

Construction status
--------------------
Construction and static-review artifact only, now at Rev7 (six rounds of
independent exact-source review corrections to date; see "Rev2/Rev3/Rev4
corrections" sections below, the Rev5 correction documented directly at
`_parse_production_stdout_occurrences()`/`_evaluate_production_stdout_success_evidence()`,
the Rev6 corrections documented inline at their respective call sites (raw
stderr byte-length gating, `episode.folder_path` resolved-target binding,
and the unconditional stdout `Job ID` comparison), and the Rev7 correction
documented directly at `_verify_no_mutation_boundary_drift()` and in
`classify_queue_attempt_outcome()`'s success requirements (raw
`episode.folder_path` continuity, distinct from resolved-target equality).
Nothing in this module contacts DaVinci Resolve, queues a render, or
mutates repository, database, or workspace state when imported.
`run_authorized_queue_attempt()` is the only function capable of launching
the mutation-bearing production CLI; it is reachable only through this
module's own `run-queue-attempt` CLI subcommand. This
construction/correction mission's own work never invokes that subcommand or
that function. A separate, explicit founder authorization is required
before any future invocation.

What this harness is, and is not
---------------------------------
This harness does NOT reimplement `RenderManager` or `ResolveAdapter`
business logic, and never imports either. The one mutation-bearing
operation remains exactly one real production CLI process:

    python -m cli.main render queue RLC-E9901 broadcast_master

launched with the exact reviewed environment (see
`build_production_environment()`). Everything else this harness does is
infrastructure around that one launch: enforcing the execution contract,
binding exact source/environment/evidence, performing approved read-only
pre/post evidence work, obtaining one fresh getter-only Resolve guard via
the already-published, already-reviewed Rev5 preflight wrapper
(`scripts/rlc_e9901_snapshot_preflight_contract.py`) rather than
introducing a new direct Resolve API surface, and classifying/preserving
what happened afterward.

Subprocess launch sites -- corrected accounting (Rev2, Finding 9)
-----------------------------------------------------------------------
The Rev1 claim "exactly two `subprocess.run(...)` call sites in the whole
module" was false and has been removed. An independent AST review found
four direct `subprocess.run()` call sites in this module:
`_run_git()` (read-only `git` invocations, used throughout every
construction-safe check and the repository checkpoint), and
`verify_python_interpreter()` (a `python -c ...` version probe) are
non-Resolve infrastructure checks, called from many places including
safe, non-live CLI subcommands. The dynamically-loaded, hash-verified
module-provenance checker (`scripts/rlc_e9901_module_provenance_check.py`)
also runs its own harmless, already-reviewed subprocess internally when
`verify_module_provenance()` calls it.

The actual safety invariant -- what this harness structurally guarantees,
proven by `test_exactly_one_production_cli_launch_site` and
`test_exactly_one_fresh_preflight_launch_site` (independent AST tests, not
merely trusted from this docstring) -- is narrower and exact:

* exactly ONE code site can launch the mutation-bearing production CLI
  (`subprocess.run(prepared.production_command, ...)`, inside
  `run_authorized_queue_attempt()`), reached at most once, no loop, no
  retry;
* exactly ONE code site launches the fresh getter-only preflight guard
  (`subprocess.run(prepared.fresh_preflight_command, ...)`, also inside
  `run_authorized_queue_attempt()`), reached at most once, no loop, no
  retry;
* every other `subprocess.run` in this module is one of the non-Resolve
  infrastructure checks named above, never contacts Resolve, and is safe
  to call from any construction-time or preview subcommand.

Source-identity binding: why these files, and not more
---------------------------------------------------------
The primary binding for "the entire mutation-bearing pathway is the exact
reviewed published source" is the repository checkpoint itself
(`verify_repository_checkpoint()`): HEAD exactly equals the authorized
commit, `origin/master` equals the same commit, and the working tree,
index, and stash are all clean. Because git's object model is a Merkle
tree over every tracked file, that checkpoint alone already proves every
tracked file in the repository — not just the files listed below — matches
the published commit's tree exactly.

`_MUTATION_BEARING_SOURCE_SHA256` hashes eight specific files on top of
that as cheap, non-arbitrary, defense-in-depth: exactly the files that
were read, traced, and confirmed to sit on the `render queue` mutation
call graph during the prior read-only preparation mission, and whose bytes
directly determine what Resolve calls are made and in what order:
`cli/main.py` (entry point; also the file that decides real-vs-mock Resolve
routing via `--mock-resolve` — this harness's own production command never
passes that flag, but confirming this file's bytes match review is what
makes that omission meaningful), `cli/render_commands.py` (dispatch and
exception-to-category mapping), `runtime/composition.py` (the
`resolve.connect()` call site -- confirmed, per Rev2 Finding 2, to run
unconditionally before `RenderManager.queue_render()` is ever reached),
`render/manager.py` (the orchestration: collision checks, renderability
preflight, SQLite claim, Resolve queue call, reconciliation, rollback),
`render/plan.py` (output-path construction), `resolve/adapter.py` (the
actual `LoadProject`/`SetCurrentTimeline`/`LoadRenderPreset`/
`SetRenderSettings`/`AddRenderJob`/reconciliation calls), `db/database.py`
(the claim/finalize/release SQL and the episode status transition), and
`config/render_presets.yaml` (data, not code, but just as load-bearing: it
is the source of `resolve_preset_name`, `requires_video_payload`, and the
output filename template).

Deliberately NOT hashed individually: every other transitively-imported
module (exception classes, enums, config loader/schema, episode/media/
timeline managers not on this call path, logging setup, etc.). Those are
already covered by the repository checkpoint, and there is no principled
stopping point once transitive imports are enumerated one at a time — doing
so would produce exactly the "enormous arbitrary hash list" this
construction was told to avoid, while adding no verification strength the
checkpoint doesn't already provide.

Classification model — Rev2 corrections (Findings 2, 3, 6)
-----------------------------------------------------------------------
Rev1's classification "A: failure before Resolve mutation" was imprecise
in two distinct ways, both corrected here:

**Finding 2** — `runtime/composition.py`'s `build_application_services()`
calls `resolve.connect()` unconditionally, before `render_commands.run()`
is ever reached, which is itself before `RenderManager.queue_render()`
performs its very first check (episode lookup). This means EVERY
RenderManager-raised failure -- including "episode not found", which
sounds like it could not possibly have touched Resolve -- occurs after
Resolve has already been connected. `NO_RESOLVE_CONTACT_YET` accordingly
no longer exists as a classification for any outcome where the production
process actually started running Python. It is replaced by
`PRODUCTION_PROCESS_NOT_LAUNCHED` (reserved exclusively for an `OSError`
that prevented the process from starting at all -- the only case this
harness can actually prove made zero Resolve contact) and
`RESOLVE_CONNECTED_EARLY_FAILURE_NO_CLAIM` (for the same set of
known-early RenderManager failures Rev1 mislabeled -- episode/preset/
config errors, a local filesystem/DB collision -- now correctly described
as occurring after Resolve connection, before any SQLite claim).

**Finding 3** — `SQLITE_CLAIM_NO_SETTINGS_MUTATION` claimed "no settings
mutation" for `LoadRenderPreset()`/`SetRenderSettings()` failures, but a
falsy return from either call does not prove no Resolve state changed --
it proves only that Redline did not confirm success. Renamed to
`SQLITE_CLAIM_RENDER_CONFIGURATION_FAILED_BEFORE_ADD_ACCEPTANCE`, with
detail text stating explicitly that these calls may have been attempted
before failing.

**Finding 6** — the success classification (renamed
`PRODUCTION_QUEUE_PATH_ACCEPTED`, see `classify_queue_attempt_outcome()`)
now requires an exact, fully-specified `render_jobs` row match (preset,
project, timeline, status, non-empty `resolve_job_id`, exact output path),
exactly one new row for RLC-E9901, zero new rows for any other episode's
count drift, corroboration against the production CLI's own human-readable
stdout, `archives` still zero, and the expected `.mov` still absent --
rather than the previous loose "some new row plus render_queued" check.
Rev4 strengthens this twice further -- see the "Rev4 corrections" section
below.

None of these classifications is a claim about Resolve's actual queue
state -- see `PRODUCTION_QUEUE_PATH_ACCEPTED`'s own docstring and
`docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md`'s "Classification proof
boundary" section for the exact distinction between "production queue-path
acceptance" (what this harness can prove) and final independent Resolve
queue proof (a separate, not-yet-built, separately authorized
evidence-closure observation this harness deliberately does not add). This
harness does not itself observe Resolve's rendering state at any point --
it never contacts Resolve at all outside the one fresh getter-only
preflight subprocess -- so it cannot detect manual or external rendering
activity it never observed in the first place; see §11's `StartRendering()`
boundary and Rev4 Finding 5 for the precise scope of what is and is not
claimed.

Rev4 corrections (Findings 1-5)
-----------------------------------
**Finding 1** — the success classification did not require the postflight
episode row to retain its expected `project_name`. An independent replay
reproduced a false pass where `episode_status` correctly showed
`render_queued` but `episode_project_name` had drifted to something else
entirely, with every other signal (exact row, exit 0, valid-looking
stdout) still looking correct. `PRODUCTION_QUEUE_PATH_ACCEPTED` now also
requires `db_after.episode_exists` and `db_after.episode_project_name ==
EXPECTED_PROJECT_NAME`, since the queue operation is expected to change
episode *status* only.

**Finding 2** — stdout corroboration required only three of the eight
fields (`resolve_job_id`, `status`, `output_path`) the hash-pinned
production CLI deterministically prints on success, plus the two fixed
confirmation lines. An independent replay reproduced a false pass with
stdout containing only that minimal subset. All eight fields (`Job ID`,
`Episode ID`, `Preset`, `Project`, `Timeline`, `Resolve Job ID`, `Status`,
`Output`) are now required to be present and to agree with the postflight
database row (`Job ID` against the row's own `id`, `Episode ID` against
the fixed `RLC-E9901` constant, everything else against the row's own
fields).

**Finding 3** — the second mutation-boundary recheck reran the repository
checkpoint, source hashes, DB baseline, and filesystem baseline, but not
module provenance -- leaving the exact window the fresh preflight
subprocess spans unguarded against a `python -m` CWD-shadowing scenario.
`_verify_no_mutation_boundary_drift()` now also reruns
`verify_module_provenance()` (the already-published, hash-verified
checker; no new implementation) and preserves its second-pass report in
`mutation_boundary_recheck.json`.

**Finding 4** — the live evidence package did not preserve the reviewed
execution environment or the proven Python interpreter identity for later
independent review. `verify_python_interpreter()` now returns the actual
verified identity (not `None`); `build_execution_environment_evidence()`
writes `execution_environment.json` immediately before the production
launch, containing only a fixed allowlist of reviewed keys copied directly
from the exact environment the production subprocess receives -- never the
full ambient environment, which may contain unrelated credentials.

**Finding 5** — documentation precision: this module's own "Construction
status" no longer claims to be "at Rev2"; the contract's `StartRendering()`
boundary section no longer implies the harness can observe unexpected
rendering activity it never contacts Resolve to see.

Mutation-boundary recheck and snapshot binding — Rev2 additions (Findings 4, 5), extended Rev4 (Finding 3)
------------------------------------------------------------------------------------------------------------
The fresh getter-only preflight subprocess can take a nontrivial, variable
amount of time. `_verify_no_mutation_boundary_drift()` reruns the
repository checkpoint, mutation-bearing source hashes, preflight-wrapper
hash, DB baseline, filesystem baseline, and (Rev4 Finding 3) module
provenance a second time, immediately after the fresh preflight reports
PASS and before the production CLI is ever launched -- closing the window
in which repository, source, database, or module-resolution state could
have drifted while the fresh preflight subprocess was running. The module-
provenance recheck matters specifically because `python -m` inserts the
process's CWD ahead of `PYTHONPATH`; a stray workspace-local `cli/` or
`redline_core/` directory that appeared during that window could otherwise
silently shadow the canonical repository packages the production CLI is
supposed to run. `verify_fresh_preflight_snapshot_binding()` additionally
requires the fresh preflight's own output file to exist, hashes it, and
requires the wrapper's own printed result to include
`snapshot_path`/`snapshot_sha256` -- both fields are mandatory on every
reported PASS (Rev6), not merely compared when present -- with an exact
match against the independently observed bytes, binding the queue
attempt's evidence chain to the exact bytes the fresh preflight actually
captured, not merely to its reported pass/fail verdict.

Rev7 correction (Finding 1) — raw `episode.folder_path` continuity
-----------------------------------------------------------------------
Rev6 bound `episode.folder_path` to the expected RESOLVED episode
directory (via `_resolve_episode_directory()`), but never required the RAW
stored string itself to stay unchanged across the experiment. An
independent replay proved this insufficient: an initial baseline of
`_episodes\RLC-E9901`, followed by a second-pass or postflight raw value
that is a different, syntactically equivalent spelling still resolving to
the exact same directory, passed every existing check -- including a
postflight classification with an otherwise-exact successful row, exit
code, and stdout -- and incorrectly reached `PRODUCTION_QUEUE_PATH_ACCEPTED`.

The hash-pinned production database source proves queue finalization
updates only `episode.status` and `episode.updated_at`; it does not
rewrite `episode.folder_path`. Any raw `folder_path` change during a queue
attempt is therefore unexpected database drift in its own right, even when
the changed value still resolves to the same filesystem target -- this is
about experiment-state continuity, not filesystem-target equivalence, and
the resolved-target check alone cannot detect it.

`_verify_no_mutation_boundary_drift()` now also requires the second-pass
baseline's raw `episode_folder_path` to equal the raw value captured by
the very first pre-mutation baseline, failing closed
(`episode_folder_path_raw_drift`) before the production CLI is ever
launched if it does not; both values are preserved explicitly in
`mutation_boundary_recheck.json`. `classify_queue_attempt_outcome()`'s
`PRODUCTION_QUEUE_PATH_ACCEPTED` requirements now also require the
postflight baseline's raw `episode_folder_path` to equal `db_before`'s raw
value, in addition to (never instead of) the existing resolved-target
equality check -- so the first baseline, the second mutation-boundary
baseline, and the postflight baseline must all agree on the exact raw
stored string, not merely on where it resolves.

Safety design
--------------
* No `DaVinciResolveScript` import or reference anywhere in this module.
* No import of `RenderManager`, `ResolveAdapter`, or any `redline_core.*`
  business-logic module. The only `redline_core`-adjacent contact is the
  production CLI subprocess itself, launched as an opaque external process.
* No import of the preflight wrapper or its checker at module level, or
  under any code path before the repository checkpoint and this harness's
  own source-hash checks have already succeeded.
* Exactly one launch site each for the fresh preflight guard and the
  production CLI (see "Subprocess launch sites" above) -- both inside
  `run_authorized_queue_attempt()`. No loop wraps either. No retry branch
  re-attempts either on any failure path.
* No cleanup, deletion, repair, or second submission is attempted by this
  harness on any failure path. Existing, already-reviewed production
  rollback behavior inside `RenderManager.queue_render()` (SQLite claim
  release; best-effort `DeleteRenderJob()`) may still occur, because it
  runs inside the one production CLI subprocess this harness launches —
  the harness observes and records whether it happened, and never adds to
  it.
* A postflight database read failure can never itself produce a success
  classification (Rev2 Finding 10) -- `read_database_baseline()` is now
  exception-safe end-to-end (connection AND every query wrapped), and
  `classify_queue_attempt_outcome()` explicitly checks for a postflight
  read error before considering any success path.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

MISSION = "RLC-E9901 Broadcast Master One-Shot Queue Attempt — Execution Harness"

# ---------------------------------------------------------------------------
# Canonical bindings.
# ---------------------------------------------------------------------------

CANONICAL_REPOSITORY_ROOT = Path(r"C:\Users\pj198\Documents\redline-os")
CANONICAL_ORIGIN_URL = "git@github.com:Choice283/redline-os.git"
CANONICAL_BRANCH = "master"

EXPECTED_PYTHON_EXECUTABLE = Path(
    r"C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe"
)
EXPECTED_PYTHON_VERSION = (3, 11, 9)

EPISODE_ID = "RLC-E9901"
PRESET_NAME = "broadcast_master"
EXPECTED_PROJECT_NAME = "RLC-E9901_MASTER"
EXPECTED_TIMELINE_NAME = "RLC-E9901_TIMELINE"

# The exact, and only, mutation-bearing production invocation this harness
# may ever construct. A tuple, not a list, and referenced by identity
# everywhere below -- never rebuilt from parts, so there is exactly one
# place a future edit could change what gets queued.
PRODUCTION_CLI_MODULE_ARGS: tuple[str, ...] = ("-m", "cli.main", "render", "queue", EPISODE_ID, PRESET_NAME)
PRODUCTION_CWD = Path(r"C:\Users\pj198\RedlineOSLive\RLC-E9901")

REPOSITORY_SRC_ROOT = CANONICAL_REPOSITORY_ROOT / "src"
REDLINE_CONFIG_DIR = CANONICAL_REPOSITORY_ROOT / "config"
REDLINE_DB_PATH = Path(r"C:\Users\pj198\RedlineOSLive\Runtime\redline.db")

RESOLVE_SCRIPT_API_PATH = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
)
RESOLVE_SCRIPT_LIB_PATH = Path(
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
)
RESOLVE_SCRIPT_MODULES_PATH = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
)

EXPECTED_OUTPUT_PATH = Path(
    r"C:\Users\pj198\RedlineOSLive\RLC-E9901\_episodes\RLC-E9901\exports\RLC-E9901_MASTER.mov"
)

# Rev6 Finding 2: `episode.folder_path` (as stored in the `episodes` table)
# directly controls where `render/plan.py`'s `build_render_output_plan()`
# targets the production render -- `Path(episode.folder_path).expanduser().resolve()`,
# resolved against the production CLI's own CWD (`PRODUCTION_CWD`), not this
# harness process's CWD. `_resolve_episode_directory()` reproduces that exact
# resolution so the harness can prove the DB's raw stored value resolves to
# the one specific expected directory, not merely "some" directory.
EXPECTED_EPISODE_FOLDER_PATH_RELATIVE = r"_episodes\RLC-E9901"
EXPECTED_EPISODE_DIRECTORY = (PRODUCTION_CWD / EXPECTED_EPISODE_FOLDER_PATH_RELATIVE).resolve()


def _resolve_episode_directory(folder_path: str | None) -> Path | None:
    """Reproduce render/plan.py's own resolution of `episode.folder_path`,
    exactly: relative to the production CLI's CWD (`PRODUCTION_CWD`), not
    this process's CWD -- `Path.resolve()` alone would silently resolve
    against the wrong directory. Returns `None` when `folder_path` is
    missing/empty, which can never equal `EXPECTED_EPISODE_DIRECTORY`."""

    if not folder_path:
        return None
    return (PRODUCTION_CWD / folder_path).resolve()


HISTORICAL_PREFLIGHT_PATH = Path(
    r"C:\Users\pj198\RedlineOSPreflightEvidence\RLC-E9901_broadcast_master_readonly_preflight_40f8c7b_20260809.json"
)
_REVIEWED_HISTORICAL_PREFLIGHT_SHA256 = (
    "3728a6af1f13209cfe8cc5972bf46445c7cfa394200511e36728222da0e9d83a"
)

PREFLIGHT_WRAPPER_RELATIVE_PATH = Path("scripts") / "rlc_e9901_snapshot_preflight_contract.py"
CHECKER_RELATIVE_PATH = Path("scripts") / "rlc_e9901_preflight_assertion.py"
MODULE_PROVENANCE_CHECK_RELATIVE_PATH = Path("scripts") / "rlc_e9901_module_provenance_check.py"

_REVIEWED_PREFLIGHT_WRAPPER_SHA256 = (
    "1c57b45c15102d3d73d4b723ba2a1c8734f6e92b9eab5d9e44a6d499f2708e89"
)
_REVIEWED_CHECKER_SHA256 = (
    "aa915a9c567919e545c1f966fe8ab3959ec547b680dc32701338313c5d3302df"
)
_REVIEWED_MODULE_PROVENANCE_CHECK_SHA256 = (
    "29015a44efbd278da14979ba79b10ac765eca7d62e358a18f22ce1a28529dc35"
)

# Recorded independently at construction time, computed directly over each
# file's raw bytes at the authorized commit -- never by importing any of
# them. See the module docstring, "Source-identity binding", for why this
# exact set of eight files was chosen.
_MUTATION_BEARING_SOURCE_SHA256: dict[str, str] = {
    "src/cli/main.py": "4218e88d23253b8788af67dc40207b33bec6d858bc5475922bf726febe3cab08",
    "src/cli/render_commands.py": "72b6b6b31b01739a06617f516cf7151b8753faeb571e1581da3d8d71c08bc0a5",
    "src/redline_core/runtime/composition.py": "5b246c9d9b5c4c6a4bc460a627f69074ae76378765bac52a4745b6983cb94b5d",
    "src/redline_core/render/manager.py": "54c89d5b4e2d9d0944e7241842e347c35be18db138f78564e702e54f8c170039",
    "src/redline_core/render/plan.py": "bf4d6f67cd163f282d4e574d23d777bca694018b7ca361b280204abd7bc048ec",
    "src/redline_core/resolve/adapter.py": "26b800bbb82abddf6dc826e47b12747e541a264184c3275f2d47e269b7379998",
    "src/redline_core/db/database.py": "d26ec783bc6cb4bc4a4df762c2d31a965fdb5ba25b7d35d002a530f3f3307347",
    "config/render_presets.yaml": "f9434b087e504bdfb6858e7fe83cd1e6bc6ccf4caaab56eb4295690502a40524",
}

# Evidence must never land inside any of these. RedlineOSPreflightEvidence
# is included because that directory holds the historical preflight this
# harness only ever reads -- a fresh queue-attempt evidence root must not
# be nested inside it either.
PROTECTED_EVIDENCE_ROOTS: tuple[Path, ...] = (
    CANONICAL_REPOSITORY_ROOT,
    Path(r"C:\Users\pj198\RedlineOSLive\RLC-E9901"),
    Path(r"C:\Users\pj198\RedlineOSLive\Evidence"),
    Path(r"C:\Users\pj198\RedlineOSLive\Runtime"),
    Path(r"C:\Users\pj198\RedlineOSPreflightEvidence"),
)


class QueueAttemptContractError(RuntimeError):
    """Fail-closed harness error with a machine-readable classification."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


# ---------------------------------------------------------------------------
# Structured result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueAttemptAuthorization:
    """Per-run values a future founder authorization must bind explicitly."""

    authorized_commit: str
    evidence_output_directory: Path


@dataclass(frozen=True)
class CapturedOutput:
    """JSON-safe, lossless representation of one captured subprocess stream.

    Identical shape and rationale to the already-reviewed
    `rlc_e9901_snapshot_preflight_contract.CapturedOutput` -- duplicated
    here rather than imported, so this harness's own on-disk bytes are the
    complete, self-contained artifact its own source-hash check pins,
    without an import-time coupling to a second module's revision history.
    """

    present: bool
    encoding: str | None
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


def _describe_os_error(exc: OSError) -> dict:
    """Structured launch-error evidence (Rev3, Finding R3-6). Rev2 stored
    only `type(exc).__name__`, discarding the message, `errno`, and
    `filename` an `OSError` (e.g. `FileNotFoundError`, `PermissionError`)
    already carries -- information genuinely useful to a reviewer deciding
    whether a launch failure was transient or structural. Never overclaims:
    only fields the exception object itself provides are included."""

    return {
        "error_type": type(exc).__name__,
        "message": str(exc),
        "errno": exc.errno,
        "filename": exc.filename,
    }


def _normalize_captured_output(value: str | bytes | bytearray | None) -> CapturedOutput:
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
class DatabaseBaseline:
    """One read-only snapshot of the facts this harness cares about.

    `render_jobs_for_episode_rows` (Rev2 Finding 6) captures the exact
    RLC-E9901 render_jobs row(s), not merely their count, so a successful
    classification can verify every expected field rather than inferring
    correctness from a count increase alone.

    `episode_row_count`/`episode_folder_path` (Rev6 Finding 2): the
    hash-pinned `render/plan.py` uses `episode.folder_path` (via
    `Path(episode.folder_path).expanduser().resolve()`, resolved against
    the production CLI's own CWD) to construct the actual render output
    directory -- an unbound or duplicated episode row is therefore itself
    a mutation-bearing input this harness must gate on, not merely
    `status`/`project_name`."""

    integrity_check: str | None
    episode_exists: bool
    episode_row_count: int | None
    episode_status: str | None
    episode_project_name: str | None
    episode_folder_path: str | None
    render_jobs_total_count: int | None
    render_jobs_for_episode_count: int | None
    render_jobs_for_episode_rows: tuple[dict, ...] | None
    archives_total_count: int | None
    error: str | None

    def to_dict(self) -> dict:
        return {
            "integrity_check": self.integrity_check,
            "episode_exists": self.episode_exists,
            "episode_row_count": self.episode_row_count,
            "episode_status": self.episode_status,
            "episode_project_name": self.episode_project_name,
            "episode_folder_path": self.episode_folder_path,
            "render_jobs_total_count": self.render_jobs_total_count,
            "render_jobs_for_episode_count": self.render_jobs_for_episode_count,
            "render_jobs_for_episode_rows": list(self.render_jobs_for_episode_rows) if self.render_jobs_for_episode_rows is not None else None,
            "archives_total_count": self.archives_total_count,
            "error": self.error,
        }


@dataclass(frozen=True)
class ClassificationResult:
    code: str
    detail: str
    evidence: dict

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "evidence": self.evidence}


# ---------------------------------------------------------------------------
# Repository checkpoint (duplicated, self-contained infra -- not
# RenderManager/ResolveAdapter business logic; see module docstring).
# ---------------------------------------------------------------------------


def _run_git(args: list[str], *, repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise QueueAttemptContractError(
            "git_command_failed", f"git {' '.join(args)} failed",
            details={"args": args, "stderr": result.stderr.strip()},
        )
    return result.stdout.strip()


def verify_repository_checkpoint(
    authorized_commit: str, *, repository_root: Path = CANONICAL_REPOSITORY_ROOT
) -> None:
    """Fail closed unless the live repository matches the complete authorized checkpoint."""

    toplevel = _run_git(["rev-parse", "--show-toplevel"], repository_root=repository_root)
    if Path(toplevel).resolve() != repository_root.resolve():
        raise QueueAttemptContractError(
            "repository_root_mismatch", "git repository root does not match the canonical repository root",
            details={"expected": str(repository_root), "actual": toplevel},
        )

    branch = _run_git(["branch", "--show-current"], repository_root=repository_root)
    if branch != CANONICAL_BRANCH:
        raise QueueAttemptContractError(
            "branch_mismatch", "current branch is not the canonical branch",
            details={"expected": CANONICAL_BRANCH, "actual": branch},
        )

    head = _run_git(["rev-parse", "HEAD"], repository_root=repository_root)
    if head != authorized_commit:
        raise QueueAttemptContractError(
            "head_commit_mismatch", "current HEAD does not match the authorized commit",
            details={"expected": authorized_commit, "actual": head},
        )

    origin_url = _run_git(["remote", "get-url", "origin"], repository_root=repository_root)
    if origin_url != CANONICAL_ORIGIN_URL:
        raise QueueAttemptContractError(
            "origin_url_mismatch", "git remote 'origin' does not match the canonical origin URL",
            details={"expected": CANONICAL_ORIGIN_URL, "actual": origin_url},
        )

    origin_master = _run_git(["rev-parse", "origin/master"], repository_root=repository_root)
    if origin_master != authorized_commit:
        raise QueueAttemptContractError(
            "origin_master_mismatch", "origin/master does not equal the authorized commit",
            details={"expected": authorized_commit, "actual": origin_master},
        )

    status = _run_git(["status", "--short"], repository_root=repository_root)
    if status != "":
        raise QueueAttemptContractError(
            "working_tree_not_clean", "git working tree is not clean",
            details={"git_status_short": status},
        )

    staged = _run_git(["diff", "--cached", "--name-only"], repository_root=repository_root)
    if staged != "":
        raise QueueAttemptContractError(
            "index_not_clean", "git index has staged changes",
            details={"staged_files": staged.splitlines()},
        )

    stash = _run_git(["stash", "list"], repository_root=repository_root)
    if stash != "":
        raise QueueAttemptContractError(
            "stash_not_empty", "git stash is not empty",
            details={"stash_list": stash.splitlines()},
        )


# ---------------------------------------------------------------------------
# Source identity
# ---------------------------------------------------------------------------


def _hash_relative_file(relative_path: str, *, repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> str:
    resolved = repository_root / relative_path
    try:
        raw_bytes = resolved.read_bytes()
    except OSError as exc:
        raise QueueAttemptContractError(
            "source_file_unreadable", f"source file could not be read from disk: {relative_path}",
            details={"path": str(resolved), "error_type": type(exc).__name__},
        ) from exc
    return hashlib.sha256(raw_bytes).hexdigest()


def verify_mutation_bearing_source_identity(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> dict[str, str]:
    """Fail closed unless every mutation-bearing file's on-disk bytes match the reviewed SHA-256."""

    observed: dict[str, str] = {}
    for relative_path, reviewed_sha256 in _MUTATION_BEARING_SOURCE_SHA256.items():
        digest = _hash_relative_file(relative_path, repository_root=repository_root)
        observed[relative_path] = digest
        if digest != reviewed_sha256:
            raise QueueAttemptContractError(
                "mutation_bearing_source_hash_mismatch",
                f"mutation-bearing source file bytes on disk do not match the reviewed SHA-256: {relative_path}",
                details={"path": relative_path, "expected": reviewed_sha256, "actual": digest},
            )
    return observed


def verify_preflight_wrapper_source_identity(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> str:
    """Fail closed unless the preflight wrapper's on-disk bytes match its published, reviewed SHA-256.

    This harness subprocess-launches that exact file; pinning its hash here
    is a direct precondition of the fresh getter-only guard, independent of
    whether it also happens to be covered by the repository checkpoint."""

    digest = _hash_relative_file(str(PREFLIGHT_WRAPPER_RELATIVE_PATH), repository_root=repository_root)
    if digest != _REVIEWED_PREFLIGHT_WRAPPER_SHA256:
        raise QueueAttemptContractError(
            "preflight_wrapper_source_hash_mismatch",
            "preflight wrapper source file bytes on disk do not match the published, reviewed SHA-256",
            details={"expected": _REVIEWED_PREFLIGHT_WRAPPER_SHA256, "actual": digest},
        )
    return digest


# ---------------------------------------------------------------------------
# Python interpreter
# ---------------------------------------------------------------------------


def verify_python_interpreter(
    python_executable: Path = EXPECTED_PYTHON_EXECUTABLE, *, timeout: int = 30
) -> dict:
    """Fail closed unless `python_executable` is exactly Python 3.11.9.

    Rev4 Finding 4: returns the actual verified interpreter identity
    (`{"executable": ..., "version": [3, 11, 9]}`) rather than `None`, so a
    caller can preserve the *proven* result -- not merely the asserted
    constant it was checked against -- as evidence (see
    `execution_environment.json`, built from this return value)."""

    probe_source = (
        "import json, sys; "
        "print(json.dumps({'executable': sys.executable, 'version': list(sys.version_info[:3])}))"
    )
    result = subprocess.run(
        [str(python_executable), "-c", probe_source],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if result.returncode != 0:
        raise QueueAttemptContractError(
            "python_interpreter_probe_failed", "candidate Python interpreter could not be probed",
            details={"executable": str(python_executable), "stderr": result.stderr.strip()},
        )
    try:
        reported = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QueueAttemptContractError(
            "python_interpreter_probe_output_invalid", "candidate Python interpreter probe did not return valid JSON",
        ) from exc

    reported_executable = Path(reported.get("executable", "")).resolve()
    if reported_executable != python_executable.resolve():
        raise QueueAttemptContractError(
            "python_interpreter_path_mismatch", "candidate interpreter's own sys.executable does not match the requested path",
            details={"expected": str(python_executable), "actual": str(reported_executable)},
        )

    reported_version = tuple(reported.get("version", []))
    if reported_version != EXPECTED_PYTHON_VERSION:
        raise QueueAttemptContractError(
            "python_interpreter_version_mismatch", "candidate interpreter is not exactly the expected Python version",
            details={"expected": list(EXPECTED_PYTHON_VERSION), "actual": list(reported_version)},
        )

    return {"executable": str(reported_executable), "version": list(reported_version)}


# ---------------------------------------------------------------------------
# Module provenance (reuses the already-published, hash-verified checker)
# ---------------------------------------------------------------------------


def _load_verified_module(
    *, relative_path: Path, reviewed_sha256: str, module_name: str, repository_root: Path = CANONICAL_REPOSITORY_ROOT
) -> Any:
    resolved_sha = _hash_relative_file(str(relative_path), repository_root=repository_root)
    if resolved_sha != reviewed_sha256:
        raise QueueAttemptContractError(
            "dependency_source_hash_mismatch",
            f"dependency module bytes on disk do not match the reviewed SHA-256: {relative_path}",
            details={"path": str(relative_path), "expected": reviewed_sha256, "actual": resolved_sha},
        )
    canonical_path = (repository_root / relative_path).resolve()
    spec = importlib.util.spec_from_file_location(module_name, canonical_path)
    if spec is None or spec.loader is None:
        raise QueueAttemptContractError(
            "dependency_module_spec_unavailable", "could not build an import spec for the dependency module",
            details={"path": str(canonical_path)},
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del sys.modules[module_name]
        raise QueueAttemptContractError(
            "dependency_module_load_failed", "dependency module raised while being loaded from its canonical path",
            details={"path": str(canonical_path), "error_type": type(exc).__name__},
        ) from exc
    loaded_file = Path(getattr(module, "__file__", "")).resolve() if getattr(module, "__file__", None) else None
    if loaded_file != canonical_path:
        raise QueueAttemptContractError(
            "dependency_module_path_mismatch", "loaded dependency module's own __file__ does not match the canonical path",
            details={"expected": str(canonical_path), "actual": str(loaded_file)},
        )
    return module


def verify_module_provenance(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> dict:
    """Load the already-reviewed module-provenance checker (hash-verified first) and run it.

    Proves `cli`/`redline_core` resolve under the canonical repository `src`
    root for the exact CWD/PYTHONPATH the production CLI will use. Never
    contacts Resolve. (This call, like `_run_git` and
    `verify_python_interpreter`, launches a `subprocess.run` internally --
    see the module docstring's "Subprocess launch sites" section for the
    corrected, complete accounting of every such call site in this file and
    its dependencies.)"""

    module = _load_verified_module(
        relative_path=MODULE_PROVENANCE_CHECK_RELATIVE_PATH,
        reviewed_sha256=_REVIEWED_MODULE_PROVENANCE_CHECK_SHA256,
        module_name="rlc_e9901_module_provenance_check_verified",
        repository_root=repository_root,
    )
    try:
        return module.verify_module_provenance(
            python_executable=EXPECTED_PYTHON_EXECUTABLE,
            cwd=PRODUCTION_CWD,
            expected_src_root=REPOSITORY_SRC_ROOT,
        )
    except module.ProvenanceCheckError as exc:
        raise QueueAttemptContractError(
            "module_provenance_check_failed", str(exc), details=getattr(exc, "details", {}),
        ) from exc


# ---------------------------------------------------------------------------
# Historical preflight binding (read-only; never rewritten)
# ---------------------------------------------------------------------------


def verify_historical_preflight_evidence(repository_root: Path = CANONICAL_REPOSITORY_ROOT) -> dict:
    """Fail closed unless the preserved historical preflight file still hashes to the
    reviewed SHA-256 and still classifies as a passing render preflight.

    Reads the file's bytes; never writes to `HISTORICAL_PREFLIGHT_PATH`."""

    try:
        raw_bytes = HISTORICAL_PREFLIGHT_PATH.read_bytes()
    except OSError as exc:
        raise QueueAttemptContractError(
            "historical_preflight_unreadable", "historical preflight evidence file could not be read",
            details={"path": str(HISTORICAL_PREFLIGHT_PATH), "error_type": type(exc).__name__},
        ) from exc

    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != _REVIEWED_HISTORICAL_PREFLIGHT_SHA256:
        raise QueueAttemptContractError(
            "historical_preflight_hash_mismatch", "historical preflight evidence bytes do not match the reviewed SHA-256",
            details={"expected": _REVIEWED_HISTORICAL_PREFLIGHT_SHA256, "actual": digest},
        )

    try:
        snapshot_obj = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QueueAttemptContractError(
            "historical_preflight_not_valid_json", "historical preflight evidence is not valid JSON despite a matching hash",
        ) from exc

    checker = _load_verified_module(
        relative_path=CHECKER_RELATIVE_PATH,
        reviewed_sha256=_REVIEWED_CHECKER_SHA256,
        module_name="rlc_e9901_preflight_assertion_verified_for_queue_harness",
        repository_root=repository_root,
    )
    offline_result = checker.evaluate_offline_preflight(snapshot_obj)
    if offline_result.render_preflight_status != "passed":
        raise QueueAttemptContractError(
            "historical_preflight_not_passing",
            "historical preflight evidence no longer classifies as a passing render preflight",
            details={"render_preflight_status": offline_result.render_preflight_status},
        )
    return {"sha256": digest, "offline_result": offline_result.to_dict()}


# ---------------------------------------------------------------------------
# Fresh preflight snapshot binding (Rev2, Finding 5)
# ---------------------------------------------------------------------------


def verify_fresh_preflight_snapshot_binding(
    *, fresh_preflight_output_path: Path,
    wrapper_reported_snapshot_path: str | None,
    wrapper_reported_snapshot_sha256: str | None,
) -> dict:
    """Fail closed unless the fresh preflight's own output file exists and
    binds cleanly to whatever the wrapper itself reported.

    Reads the file's bytes and computes SHA-256 independently -- never
    trusts the wrapper's reported `render_preflight_status == "passed"`
    alone. The wrapper's own printed result deterministically includes
    `snapshot_path`/`snapshot_sha256` whenever it reports PASS (per
    `Rlce9901PreflightResult.to_dict()`) -- this function is only ever
    called after that PASS has already been confirmed by the caller, so
    both fields are now REQUIRED to be present and well-formed (Rev6),
    not merely compared when not `None`. A PASS whose JSON is missing
    either field is itself contract-breaking evidence -- the wrapper never
    legitimately omits them -- and must stop before production launch
    exactly like a hash or path mismatch would. Never modifies the
    snapshot bytes."""

    if not fresh_preflight_output_path.exists():
        raise QueueAttemptContractError(
            "fresh_preflight_snapshot_missing",
            "fresh preflight snapshot file does not exist despite a reported PASS",
            details={"path": str(fresh_preflight_output_path)},
        )
    # Rev3 Finding R3-4: `.exists()` returning True does not guarantee
    # `.read_bytes()` will succeed (e.g. a directory at that path, a
    # permissions error, a race). Independent review reproduced an uncaught
    # `IsADirectoryError` here -- after the fresh live preflight has already
    # run, nothing may crash evidence finalization away.
    try:
        raw_bytes = fresh_preflight_output_path.read_bytes()
    except OSError as exc:
        raise QueueAttemptContractError(
            "fresh_preflight_snapshot_unreadable",
            "fresh preflight snapshot file exists but could not be read",
            details=_describe_os_error(exc),
        ) from exc
    observed_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Rev6: mandatory presence and format, not merely "compared when present".
    if not isinstance(wrapper_reported_snapshot_path, str) or wrapper_reported_snapshot_path == "":
        raise QueueAttemptContractError(
            "fresh_preflight_snapshot_path_missing",
            "wrapper reported a passing render_preflight_status but its own snapshot_path field is missing or empty",
            details={"reported_snapshot_path": wrapper_reported_snapshot_path},
        )
    if not isinstance(wrapper_reported_snapshot_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", wrapper_reported_snapshot_sha256):
        raise QueueAttemptContractError(
            "fresh_preflight_snapshot_sha256_missing",
            "wrapper reported a passing render_preflight_status but its own snapshot_sha256 field is missing or not a well-formed SHA-256 value",
            details={"reported_snapshot_sha256": wrapper_reported_snapshot_sha256},
        )

    if observed_sha256 != wrapper_reported_snapshot_sha256:
        raise QueueAttemptContractError(
            "fresh_preflight_snapshot_hash_mismatch",
            "fresh preflight snapshot bytes do not match the wrapper's own reported snapshot_sha256",
            details={"expected": wrapper_reported_snapshot_sha256, "actual": observed_sha256},
        )
    if str(fresh_preflight_output_path) != wrapper_reported_snapshot_path:
        raise QueueAttemptContractError(
            "fresh_preflight_snapshot_path_mismatch",
            "fresh preflight snapshot path does not match the wrapper's own reported snapshot_path",
            details={"expected": str(fresh_preflight_output_path), "actual": wrapper_reported_snapshot_path},
        )

    return {"path": str(fresh_preflight_output_path), "sha256": observed_sha256, "byte_length": len(raw_bytes)}


# ---------------------------------------------------------------------------
# Database / filesystem gates (read-only)
# ---------------------------------------------------------------------------


def read_database_baseline(db_path: Path | None = None, *, episode_id: str = EPISODE_ID) -> DatabaseBaseline:
    """Read-only snapshot. Opens the connection in SQLite URI read-only mode
    (`mode=ro`) so this function cannot mutate the database even by
    accident.

    Rev2 Finding 10: the entire connect-and-query sequence is now wrapped
    in one `try/except sqlite3.Error` block -- previously only the
    `connect()` call itself was guarded, so a query-level failure (e.g. a
    locked file, a schema surprise) after a successful connection would
    have propagated an uncaught exception out of this function, potentially
    crashing `run_authorized_queue_attempt()` after the production
    subprocess had already run and losing evidence-finalization entirely.
    Every failure mode now returns a structured `DatabaseBaseline` with
    `error` set, never raises.

    `db_path` resolves against the current value of the module-level
    `REDLINE_DB_PATH` at call time, not at function-definition time (a
    mutable default bound eagerly would be invisible to tests that patch
    the module constant) -- the same `arg or MODULE_CONSTANT` pattern
    `redline_core.runtime.composition` already uses."""

    resolved_db_path = db_path if db_path is not None else REDLINE_DB_PATH
    uri = f"file:{resolved_db_path}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        try:
            cur = con.cursor()
            integrity = cur.execute("PRAGMA integrity_check").fetchone()
            integrity_check = integrity[0] if integrity else None

            row = cur.execute(
                "SELECT status, project_name, folder_path FROM episodes WHERE episode_id = ?", (episode_id,)
            ).fetchone()
            episode_row_count = cur.execute(
                "SELECT COUNT(*) FROM episodes WHERE episode_id = ?", (episode_id,)
            ).fetchone()[0]
            episode_exists = row is not None
            episode_status = row[0] if row else None
            episode_project_name = row[1] if row else None
            episode_folder_path = row[2] if row else None

            render_jobs_total = cur.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0]
            render_jobs_for_episode = cur.execute(
                "SELECT COUNT(*) FROM render_jobs WHERE episode_id = ?", (episode_id,)
            ).fetchone()[0]
            archives_total = cur.execute("SELECT COUNT(*) FROM archives").fetchone()[0]

            job_rows = cur.execute(
                "SELECT id, episode_id, preset_name, resolve_job_id, project_name, timeline_name, status, output_path "
                "FROM render_jobs WHERE episode_id = ? ORDER BY id",
                (episode_id,),
            ).fetchall()
            render_jobs_for_episode_rows = tuple(
                {
                    "id": r[0], "episode_id": r[1], "preset_name": r[2], "resolve_job_id": r[3],
                    "project_name": r[4], "timeline_name": r[5], "status": r[6], "output_path": r[7],
                }
                for r in job_rows
            )

            return DatabaseBaseline(
                integrity_check=integrity_check, episode_exists=episode_exists, episode_row_count=episode_row_count,
                episode_status=episode_status, episode_project_name=episode_project_name,
                episode_folder_path=episode_folder_path, render_jobs_total_count=render_jobs_total,
                render_jobs_for_episode_count=render_jobs_for_episode,
                render_jobs_for_episode_rows=render_jobs_for_episode_rows,
                archives_total_count=archives_total, error=None,
            )
        finally:
            con.close()
    except sqlite3.Error as exc:
        return DatabaseBaseline(
            integrity_check=None, episode_exists=False, episode_row_count=None, episode_status=None,
            episode_project_name=None, episode_folder_path=None,
            render_jobs_total_count=None, render_jobs_for_episode_count=None,
            render_jobs_for_episode_rows=None, archives_total_count=None,
            error=f"database read failed: {type(exc).__name__}: {exc}",
        )


def verify_pre_mutation_database_baseline(db_path: Path | None = None, *, episode_id: str = EPISODE_ID) -> DatabaseBaseline:
    """Fail closed unless the database is exactly at the expected pre-queue baseline."""

    baseline = read_database_baseline(db_path, episode_id=episode_id)
    if baseline.error is not None:
        raise QueueAttemptContractError("db_baseline_unreadable", baseline.error)
    if baseline.integrity_check != "ok":
        raise QueueAttemptContractError(
            "db_integrity_check_failed", "SQLite integrity_check did not return 'ok'",
            details={"integrity_check": baseline.integrity_check},
        )
    if not baseline.episode_exists:
        raise QueueAttemptContractError("episode_missing", f"No episode row found for episode_id={episode_id!r}")
    # Rev6 Finding 2: a duplicated episode row (episode_exists True, but
    # more than one row) is itself unbound/ambiguous input -- `SELECT ...
    # LIMIT`-style single-row reads elsewhere would silently pick one.
    if baseline.episode_row_count != 1:
        raise QueueAttemptContractError(
            "episode_row_count_unexpected", "expected exactly one episode row for RLC-E9901",
            details={"expected": 1, "actual": baseline.episode_row_count},
        )
    if baseline.episode_status != "assembled":
        raise QueueAttemptContractError(
            "episode_status_unexpected", "episode status is not 'assembled'",
            details={"expected": "assembled", "actual": baseline.episode_status},
        )
    if baseline.episode_project_name != EXPECTED_PROJECT_NAME:
        raise QueueAttemptContractError(
            "episode_project_name_unexpected", "episode project_name does not match the expected RLC-E9901 project",
            details={"expected": EXPECTED_PROJECT_NAME, "actual": baseline.episode_project_name},
        )
    # Rev6 Finding 2: episode.folder_path directly controls where
    # render/plan.py targets the production render -- an unbound
    # mutation-bearing input this harness must gate on. Compares the
    # *resolved* directory (against the production CLI's own CWD), not the
    # raw string, so any folder_path that resolves to a different directory
    # -- even one that happens to also exist -- fails closed.
    resolved_episode_directory = _resolve_episode_directory(baseline.episode_folder_path)
    if resolved_episode_directory != EXPECTED_EPISODE_DIRECTORY:
        raise QueueAttemptContractError(
            "episode_folder_path_unexpected",
            "episode.folder_path does not resolve to the expected RLC-E9901 episode directory",
            details={
                "expected_resolved_directory": str(EXPECTED_EPISODE_DIRECTORY),
                "actual_folder_path": baseline.episode_folder_path,
                "actual_resolved_directory": str(resolved_episode_directory) if resolved_episode_directory else None,
            },
        )
    if baseline.render_jobs_total_count != 0:
        raise QueueAttemptContractError(
            "render_jobs_baseline_nonzero", "render_jobs table is not empty before the queue attempt",
            details={"render_jobs_total_count": baseline.render_jobs_total_count},
        )
    if baseline.archives_total_count != 0:
        raise QueueAttemptContractError(
            "archives_baseline_nonzero", "archives table is not empty before the queue attempt",
            details={"archives_total_count": baseline.archives_total_count},
        )
    return baseline


def verify_pre_mutation_filesystem_baseline(output_path: Path | None = None) -> None:
    """Fail closed if the expected Broadcast Master output already exists."""

    resolved_output_path = output_path if output_path is not None else EXPECTED_OUTPUT_PATH
    if resolved_output_path.exists():
        raise QueueAttemptContractError(
            "expected_output_already_exists", "expected Broadcast Master output already exists",
            details={"path": str(resolved_output_path)},
        )


def _verify_no_mutation_boundary_drift(authorized_commit: str, *, initial_episode_folder_path: str | None) -> dict:
    """Rerun the critical non-Resolve mutation-boundary gates a second time
    (Rev2 Finding 4), immediately after the fresh preflight reports PASS and
    before the production CLI is ever launched -- the fresh preflight
    subprocess can take a variable, nontrivial amount of time, during which
    repository, source, database, or module-resolution state could
    legitimately have drifted. (`_prepare_queue_attempt()` runs the same
    individual checks -- plus a few this function deliberately omits, like
    the historical preflight binding, which cannot drift once already
    verified -- as its own first pass, separately.) Any failure here raises
    before the production CLI is ever constructed or launched.

    Rev4 Finding 3: now also reruns module provenance
    (`verify_module_provenance()`, the already-published, hash-verified
    checker -- no new implementation). `python -m` inserts the process's
    CWD ahead of `PYTHONPATH`, so a stray workspace-local `cli/` or
    `redline_core/` directory that appeared during the fresh-preflight
    window could otherwise silently shadow the canonical repository
    packages the production CLI is supposed to run.

    Rev7 Finding 1: `verify_pre_mutation_database_baseline()` (called
    below) already re-proves the episode's `folder_path` still RESOLVES to
    the exact expected episode directory -- but an independent replay
    proved that check alone insufficient: the raw stored string can drift
    to a different, syntactically equivalent spelling that still resolves
    identically, which the resolved-target check cannot detect.
    `initial_episode_folder_path` is the raw `episode_folder_path` string
    captured by the very first pre-mutation baseline
    (`_prepare_queue_attempt()`'s own call, before the fresh preflight ever
    ran); this function additionally requires the second baseline's raw
    value to equal it EXACTLY, failing closed
    (`episode_folder_path_raw_drift`) even when both values resolve to the
    identical directory. The hash-pinned production database source proves
    queue finalization updates only `episode.status`/`episode.updated_at`
    -- never `episode.folder_path` -- so any raw change here is unexpected
    database drift in its own right, not merely a filesystem-equivalence
    question."""

    mutation_hashes = verify_mutation_bearing_source_identity()
    preflight_wrapper_sha = verify_preflight_wrapper_source_identity()
    verify_repository_checkpoint(authorized_commit)
    db_baseline = verify_pre_mutation_database_baseline()
    if db_baseline.episode_folder_path != initial_episode_folder_path:
        raise QueueAttemptContractError(
            "episode_folder_path_raw_drift",
            "episode.folder_path's raw stored value changed between the initial pre-mutation baseline and this "
            "mutation-boundary recheck, even though it may still resolve to the same expected directory; the "
            "production database source only ever updates episode.status/episode.updated_at during queue "
            "finalization, never folder_path, so any raw change here is unexpected drift in its own right, not "
            "merely a filesystem-equivalence question",
            details={
                "initial_episode_folder_path": initial_episode_folder_path,
                "second_baseline_episode_folder_path": db_baseline.episode_folder_path,
            },
        )
    verify_pre_mutation_filesystem_baseline()
    module_provenance_report = verify_module_provenance()
    # Rev3 Finding R3-5: every value below is preserved and written to
    # `mutation_boundary_recheck.json` by the caller -- Rev2 discarded this
    # return value and wrote only `{"result": "passed"}`, losing the actual
    # second-pass proof.
    return {
        "authorized_commit": authorized_commit,
        "repository_checkpoint_passed": True,
        "mutation_bearing_source_hashes": mutation_hashes,
        "preflight_wrapper_sha256": preflight_wrapper_sha,
        "db_baseline": db_baseline.to_dict(),
        # Rev7 Finding 1: preserved explicitly, alongside (not merely
        # implicitly inside) `db_baseline`, so the raw continuity proof is
        # visible in evidence without cross-referencing `db_preflight.json`.
        "initial_episode_folder_path": initial_episode_folder_path,
        "second_baseline_episode_folder_path": db_baseline.episode_folder_path,
        "module_provenance_report": module_provenance_report,
        "expected_output_path": str(EXPECTED_OUTPUT_PATH),
        "expected_output_exists": False,
        "recheck_completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Evidence directory
# ---------------------------------------------------------------------------


def canonicalize_and_validate_evidence_directory(path: Path) -> Path:
    """Fail closed unless `path` is an absolute, unprotected, fresh evidence directory."""

    if not path.is_absolute():
        raise QueueAttemptContractError("evidence_directory_not_absolute", f"evidence output directory must be absolute: {path}")

    resolved = path.resolve()

    for protected_root in PROTECTED_EVIDENCE_ROOTS:
        protected_resolved = protected_root.resolve()
        if resolved == protected_resolved or resolved.is_relative_to(protected_resolved):
            raise QueueAttemptContractError(
                "evidence_directory_in_protected_location",
                f"evidence output directory must not be inside a protected location: {protected_root}",
                details={"path": str(resolved), "protected_root": str(protected_root)},
            )

    if resolved.exists():
        raise QueueAttemptContractError(
            "evidence_directory_already_exists", f"evidence output directory already exists: {resolved}",
        )
    if not resolved.parent.is_dir():
        raise QueueAttemptContractError(
            "evidence_parent_directory_missing", f"evidence output directory's parent does not exist: {resolved.parent}",
        )

    return resolved


def prepare_fresh_preflight_evidence_subdirectory(evidence_dir: Path) -> Path:
    """Create exactly `<evidence_dir>/fresh_preflight` and nothing else (Rev2, Finding 1).

    The already-published preflight wrapper's own
    `_canonicalize_and_validate_evidence_path()` fails closed with
    `evidence_parent_directory_missing` unless its `--output` file's
    immediate parent directory already exists (it never auto-creates one).
    Rev1 created only `<evidence_dir>` before launching the fresh preflight
    subprocess, whose constructed output path is
    `<evidence_dir>/fresh_preflight/<file>.json` -- one directory level too
    shallow, which would have stopped the live path with exactly that
    error before ever reaching the production queue attempt. This function
    must be called after `evidence_dir` itself exists and before the fresh
    preflight subprocess is launched; it creates only this one directory,
    never the snapshot JSON file itself."""

    fresh_preflight_dir = evidence_dir / "fresh_preflight"
    fresh_preflight_dir.mkdir(parents=True, exist_ok=False)
    return fresh_preflight_dir


# ---------------------------------------------------------------------------
# Environment construction
# ---------------------------------------------------------------------------


def build_production_environment(base_env: Mapping[str, str] | None = None, *, evidence_directory: Path | None = None) -> dict[str, str]:
    """Build the exact environment for the one production CLI subprocess.

    `REDLINE_LOG_DIR` is bound to `<evidence_directory>/logs` when
    `evidence_directory` is given. Independent Rev2 source review confirmed
    this design is valid and genuinely consumed by current production
    source: `src/cli/main.py`'s `_configure_cli_logging()` reads
    `os.environ.get("REDLINE_LOG_DIR", "./logs")`, and
    `src/redline_core/logging/setup.py`'s `configure_logging()` eagerly
    creates that directory (`Path(log_dir).mkdir(parents=True,
    exist_ok=True)`) and writes a rotating file handler into it --
    `runtime/composition.py` owns no logging concern at all. Without this
    override, the production CLI would create `./logs` relative to its CWD
    (`PRODUCTION_CWD`), i.e. inside the protected RLC-E9901 workspace. No
    production logging source modification is required or was made."""

    env = dict(base_env if base_env is not None else os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPOSITORY_SRC_ROOT), str(RESOLVE_SCRIPT_MODULES_PATH)])
    env["REDLINE_CONFIG_DIR"] = str(REDLINE_CONFIG_DIR)
    env["REDLINE_DB_PATH"] = str(REDLINE_DB_PATH)
    env["RESOLVE_SCRIPT_API"] = str(RESOLVE_SCRIPT_API_PATH)
    env["RESOLVE_SCRIPT_LIB"] = str(RESOLVE_SCRIPT_LIB_PATH)
    if evidence_directory is not None:
        env["REDLINE_LOG_DIR"] = str(evidence_directory / "logs")
    return env


# The only environment keys ever written to `execution_environment.json`
# (Rev4 Finding 4). Deliberately a fixed, short allowlist -- `production_env`
# is `dict(os.environ)` plus these overrides, and dumping it wholesale would
# leak arbitrary ambient environment variables (credentials, tokens, etc.)
# into evidence. Every value written is copied from `production_env` itself,
# so it is provably the exact value actually passed to the subprocess, never
# independently re-derived.
_EXECUTION_ENVIRONMENT_EVIDENCE_KEYS: tuple[str, ...] = (
    "PYTHONPATH", "REDLINE_CONFIG_DIR", "REDLINE_DB_PATH",
    "RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB", "REDLINE_LOG_DIR",
)


def build_execution_environment_evidence(
    *, python_interpreter_identity: dict, production_command: list[str], production_env: Mapping[str, str],
) -> dict:
    """Build the reviewed-execution-identity evidence record (Rev4 Finding 4).

    `python_interpreter_identity` is the actual value
    `verify_python_interpreter()` returned (the proven interpreter identity,
    not merely the asserted `EXPECTED_PYTHON_EXECUTABLE`/`EXPECTED_PYTHON_VERSION`
    constants). `production_command[0]` is the exact executable path this
    attempt will invoke. Every other field is read from `production_env` by
    exact key -- see `_EXECUTION_ENVIRONMENT_EVIDENCE_KEYS` -- never the
    full ambient environment."""

    evidence: dict[str, Any] = {
        "python_executable": production_command[0],
        "python_interpreter_verified_executable": python_interpreter_identity.get("executable"),
        "python_version": python_interpreter_identity.get("version"),
        "production_cwd": str(PRODUCTION_CWD),
    }
    for key in _EXECUTION_ENVIRONMENT_EVIDENCE_KEYS:
        evidence[key] = production_env.get(key)
    return evidence


def build_fresh_preflight_command(authorized_commit: str, fresh_preflight_output_path: Path) -> list[str]:
    """Construct (never execute) the fresh getter-only guard's exact invocation."""

    return [
        str(EXPECTED_PYTHON_EXECUTABLE),
        str(CANONICAL_REPOSITORY_ROOT / PREFLIGHT_WRAPPER_RELATIVE_PATH),
        "run-live-preflight",
        "--authorized-commit", authorized_commit,
        "--output", str(fresh_preflight_output_path),
    ]


def build_production_command() -> list[str]:
    """Construct (never execute) the one mutation-bearing production command."""

    return [str(EXPECTED_PYTHON_EXECUTABLE), *PRODUCTION_CLI_MODULE_ARGS]


# ---------------------------------------------------------------------------
# Classification -- Rev2 corrections (Findings 2, 3, 6, 10)
# ---------------------------------------------------------------------------

# Every fragment below is copied verbatim from the exact reviewed source
# strings in render/manager.py, render/plan.py, render/exceptions.py, and
# resolve/adapter.py at the authorized commit (re-verified by
# `verify_mutation_bearing_source_identity()` before every live run) -- none
# is invented. Matching is substring-based against the CLI's captured
# stderr, since the harness never calls RenderManager/ResolveAdapter
# directly and therefore has no other window into which exception fired.
#
# Rev2 Finding 2: `runtime/composition.py`'s `build_application_services()`
# calls `resolve.connect()` unconditionally before `RenderManager` ever
# runs. Every fragment below therefore describes a failure that occurs
# AFTER Resolve connection -- none of these classify as "no Resolve
# contact" any more. Only a production-process launch failure (an OSError
# that meant Python itself never started) can prove that.
_RESOLVE_CONNECTED_EARLY_FAILURE_SUBSTRINGS: tuple[str, ...] = (
    "No episode with episode_id=",
    "No render preset named",
    "does not define an approved filename_template",
    "has no configured workspace",
    "workspace does not exist",
    "resolves outside the episode folder",
    "produced an invalid output filename",
    "Render output already exists",
)
# The DB-collision message from _reject_collisions() includes a numeric
# job id right after "Active render job "; the claim-race message from
# queue_render() itself does not. This distinguishes a local DB collision
# (RESOLVE_CONNECTED_EARLY_FAILURE_NO_CLAIM) from a post-renderability-check
# claim race (RESOLVE_STATE_SELECTION_NO_CLAIM) -- see the module
# docstring's residual-ambiguity note for the one case (live Resolve
# job-list collision) this cannot separate from a local DB/filesystem
# collision by text alone.
_DB_COLLISION_RE = re.compile(r"Active render job \d+ already targets output:")
_CLAIM_RACE_COLLISION_TEXT = "Active render job already targets output:"
_LIVE_RESOLVE_COLLISION_RE = re.compile(r"Resolve render job '.*' already targets output:")

_RESOLVE_STATE_SELECTION_NO_CLAIM_SUBSTRINGS: tuple[str, ...] = (
    "no video TimelineItems were found",  # RenderTimelineNotRenderableError, via get_video_timeline_item_count -> LoadProject
)

# Rev2 Finding 3: renamed from SQLITE_CLAIM_NO_SETTINGS_MUTATION. A falsy
# LoadRenderPreset()/SetRenderSettings() return does not prove no Resolve
# state changed -- only that Redline did not confirm success.
_RENDER_CONFIGURATION_FAILED_SUBSTRINGS: tuple[str, ...] = (
    "Resolve could not load render preset",  # LoadRenderPreset() falsy
    "Resolve rejected render output settings",  # SetRenderSettings() falsy
)

_SETTINGS_MUTATED_ADD_NOT_ACCEPTED_SUBSTRINGS: tuple[str, ...] = (
    "Resolve failed to add a render job",  # AddRenderJob() is False
)

_ADD_CALLED_ACCEPTANCE_UNOBSERVED_SUBSTRINGS: tuple[str, ...] = (
    # RenderQueueAcceptanceNotObservedError / RenderQueueIdentityUnresolvedError
    # both surface under render_commands.py's distinct category strings.
    "render queue acceptance not observed",
    "render queue identity unresolved",
)

_ACCEPTED_ROLLBACK_SUCCEEDED_SUBSTRINGS: tuple[str, ...] = (
    "but database persistence failed; the newly queued Resolve job was removed.",
)

_MANUAL_RECONCILIATION_REQUIRED_SUBSTRINGS: tuple[str, ...] = (
    "Manual reconciliation is required.",
    "Redline could not release database output claim",
    "and the job was removed, but Redline could not release database output claim",
)

_PRODUCTION_STDOUT_LABELS: tuple[tuple[str, str], ...] = (
    ("Job ID:", "job_id"),
    ("Episode ID:", "episode_id"),
    ("Preset:", "preset_name"),
    ("Project:", "project_name"),
    ("Timeline:", "timeline_name"),
    ("Resolve Job ID:", "resolve_job_id"),
    ("Status:", "status"),
    ("Output:", "output_path"),
    # Rev5: tracked as ordinary labelled fields now, not a boolean
    # "was the exact confirmation line ever seen" flag -- see
    # `_parse_production_stdout_occurrences()`.
    ("Rendering started:", "rendering_started"),
    ("Archive performed:", "archive_performed"),
)

# Rev3 Finding R3-2 / Rev4 Finding 2: the pinned production CLI
# (`render_commands.py`'s `_print_job()`/`_print_render_queue_result()`)
# deterministically prints ALL eight of these fields on success, plus both
# fixed confirmation lines. Rev3 required only `resolve_job_id`/`status`/
# `output_path` -- an independent replay proved stdout containing only
# those three plus the two confirmation lines still classified as success,
# which is incomplete evidence relative to the exact pinned CLI (it never
# actually checked that the CLI printed the *entire* deterministic block,
# only a subset). Every field below is now required to be present AND to
# agree with the postflight DB row.
_REQUIRED_SUCCESS_STDOUT_FIELDS: tuple[str, ...] = (
    "job_id", "episode_id", "preset_name", "project_name", "timeline_name",
    "resolve_job_id", "status", "output_path",
)

_CONFIRMATION_STDOUT_FIELDS: tuple[str, ...] = ("rendering_started", "archive_performed")


def _parse_production_stdout_occurrences(stdout_text: str) -> dict[str, list[str]]:
    """Extract EVERY occurrence of each labelled field from production
    stdout -- Rev5 correction: the prior version overwrote an earlier
    match whenever the same label reappeared later (last-value-wins), and
    separately reduced the two confirmation lines to a boolean "was the
    exact '...: no' string ever seen anywhere" flag, which silently
    ignored a contradictory '...: yes' line elsewhere in the same output.
    An independent replay reproduced both as real false-passes. Returning
    the full occurrence list per label -- never collapsed to a single
    value -- lets the evaluator treat duplicate or contradictory evidence
    as itself disqualifying, and keeps that ambiguity visible in
    classification evidence rather than silently resolved one way or the
    other."""

    occurrences: dict[str, list[str]] = {key: [] for _, key in _PRODUCTION_STDOUT_LABELS}
    for line in stdout_text.splitlines():
        for label, key in _PRODUCTION_STDOUT_LABELS:
            if line.startswith(label):
                occurrences[key].append(line[len(label):].strip())
    return occurrences


def _evaluate_production_stdout_success_evidence(occurrences: dict[str, list[str]], row: dict) -> str | None:
    """Rev3 Finding R3-2, strengthened Rev4 Finding 2, strengthened again
    Rev5: stdout corroboration is REQUIRED for every deterministic field
    the hash-pinned production CLI prints on success, AND each field/
    confirmation line must occur EXACTLY ONCE -- no last-value-wins, no
    first-value-wins. A duplicate occurrence is disqualifying by itself,
    even when every occurrence carries an identical value, because
    production source has no legitimate reason to print the same
    deterministic field twice; two occurrences is evidence the parser
    cannot trust to mean what a single, unambiguous occurrence would.
    Returns `None` only when stdout fully and unambiguously corroborates
    the row; otherwise a human-readable reason used directly as the
    classification detail text."""

    for field_name in _REQUIRED_SUCCESS_STDOUT_FIELDS:
        values = occurrences.get(field_name, [])
        if len(values) == 0:
            return f"production stdout is missing the required {field_name!r} success field"
        if len(values) > 1:
            return (
                f"production stdout contains {len(values)} occurrences of the required {field_name!r} field "
                "(duplicate or contradictory evidence -- even identical repeated values -- is itself disqualifying)"
            )

    for field_name in _CONFIRMATION_STDOUT_FIELDS:
        values = occurrences.get(field_name, [])
        if len(values) != 1:
            return (
                f"production stdout contains {len(values)} occurrence(s) of the required {field_name!r} "
                "confirmation line; exactly one is required"
            )
        if values[0] != "no":
            return f"production stdout's {field_name!r} confirmation line value is {values[0]!r}, not the required 'no'"

    job_id = occurrences["job_id"][0]
    episode_id = occurrences["episode_id"][0]
    preset_name = occurrences["preset_name"][0]
    project_name = occurrences["project_name"][0]
    timeline_name = occurrences["timeline_name"][0]
    resolve_job_id = occurrences["resolve_job_id"][0]
    status = occurrences["status"][0]
    output_path = occurrences["output_path"][0]

    # Rev6 Finding 3: no branch may disable this comparison when the DB
    # identity is missing -- classify_queue_attempt_outcome's `row_ok`
    # already requires a genuine positive-integer `id` as a precondition of
    # reaching this function at all, so `row.get("id")` is guaranteed
    # present and valid here; this comparison is unconditional.
    if job_id != str(row.get("id")):
        return "production stdout 'Job ID' does not match the database row id"
    if episode_id != EPISODE_ID:
        return "production stdout 'Episode ID' does not match the expected RLC-E9901 episode"
    if preset_name != row.get("preset_name"):
        return "production stdout 'Preset' does not match the database row"
    if project_name != row.get("project_name"):
        return "production stdout 'Project' does not match the database row"
    if timeline_name != row.get("timeline_name"):
        return "production stdout 'Timeline' does not match the database row"
    if resolve_job_id != (row.get("resolve_job_id") or ""):
        return "production stdout 'Resolve Job ID' does not match the database row"
    if status != row.get("status"):
        return "production stdout 'Status' does not match the database row"
    if output_path != row.get("output_path"):
        return "production stdout 'Output' does not match the database row"

    return None


def classify_queue_attempt_outcome(
    *, exit_code: int | None, stdout_text: str, stderr_text: str,
    db_before: DatabaseBaseline, db_after: DatabaseBaseline,
    launch_error: dict | None, timed_out: bool, expected_output_exists: bool,
    stderr_byte_length: int | None = None,
) -> ClassificationResult:
    """Classify one completed (or failed-to-launch) production CLI attempt.

    Fails closed to `UNCLASSIFIED_REQUIRES_REVIEW` whenever the evidence
    does not match a known, source-quoted pattern -- this function never
    guesses a success or a "safe" outcome from absence of evidence. See the
    module docstring's "Classification model — Rev2/Rev3 corrections"
    sections for the full rationale behind every boundary and rename below.

    `PRODUCTION_QUEUE_PATH_ACCEPTED` is the strongest classification this
    function can produce, and even it proves only production queue-path
    acceptance per the CLI/adapter/SQLite evidence -- not final independent
    proof of Resolve's own actual queue state (see
    `docs/RLC_E9901_QUEUE_ATTEMPT_CONTRACT.md`'s "Classification proof
    boundary" section). `launch_error`, if present, is now the structured
    dict `_describe_os_error()` produces (Rev3 Finding R3-6), not a bare
    class-name string.

    `stderr_byte_length` (Rev6 Finding 1): the RAW captured stderr stream's
    exact byte count -- `run_authorized_queue_attempt()` always passes the
    real `CapturedOutput.byte_length`, since `stderr_text` alone (derived
    from `CapturedOutput.text`, which is `None` whenever the raw bytes
    aren't valid UTF-8) cannot distinguish "truly empty" from "non-empty
    but undecodable" or from whitespace/newline-only bytes an independent
    replay proved `.strip() != ""` on decoded text alone would miss. When
    not supplied (legacy/unit-test callers exercising unrelated behavior),
    falls back to the raw UTF-8-encoded length of `stderr_text` itself --
    equivalent to the real value for any caller passing plain ASCII text,
    but never authoritative for a live run."""

    effective_stderr_byte_length = (
        stderr_byte_length if stderr_byte_length is not None else len(stderr_text.encode("utf-8"))
    )
    combined_text = f"{stdout_text}\n{stderr_text}"
    evidence = {
        "exit_code": exit_code, "launch_error": launch_error, "timed_out": timed_out,
        "db_before": db_before.to_dict(), "db_after": db_after.to_dict(),
        "expected_output_exists": expected_output_exists,
        "stderr_byte_length": effective_stderr_byte_length,
    }

    # Finding 2: only a process that never actually launched can prove zero
    # Resolve contact -- everything that ran, even briefly, ran after
    # composition.py's unconditional resolve.connect().
    if launch_error is not None:
        return ClassificationResult(
            "PRODUCTION_PROCESS_NOT_LAUNCHED",
            "production CLI subprocess could not be launched as an OS process; Python itself never started, so no Resolve contact could have occurred",
            evidence,
        )
    # Rev3 Finding R3-7: a forced timeout is a materially different, more
    # dangerous condition than an ordinary CLI failure -- the production
    # process could have been terminated mid-way between the SQLite claim,
    # Resolve settings mutation, AddRenderJob, DB finalization, or built-in
    # rollback. This check runs BEFORE any DB-state inspection below, so a
    # forced timeout can never classify as success merely because the
    # partial DB state happens to look complete by coincidence.
    if timed_out:
        return ClassificationResult(
            "PRODUCTION_TIMEOUT_RECONCILIATION_REQUIRED",
            "production CLI subprocess was force-terminated after exceeding the timeout while potentially between SQLite claim, Resolve settings "
            "mutation, AddRenderJob, DB finalization, or built-in rollback; Resolve's actual queue state cannot be determined from this evidence "
            "alone and may require a subsequent, separately authorized, read-only getter-only evidence-closure observation before any next action; "
            "not retried",
            evidence,
        )
    # Finding 10: a postflight DB read failure can never itself produce success.
    if db_after.error is not None:
        return ClassificationResult(
            "UNCLASSIFIED_REQUIRES_REVIEW",
            "postflight database read failed; a read failure can never itself prove success or any other specific outcome",
            evidence,
        )

    # Rev3 Finding R3-1: BOTH the per-episode delta and the table-wide
    # total delta must equal exactly 1. Rev2 checked only the per-episode
    # count, so an exact expected RLC-E9901 row alongside one unrelated
    # row elsewhere in the table (total delta 2) still classified as
    # success -- a real false-pass an independent replay reproduced.
    new_row_count = (db_after.render_jobs_for_episode_count or 0) - (db_before.render_jobs_for_episode_count or 0)
    total_new_row_count = (db_after.render_jobs_total_count or 0) - (db_before.render_jobs_total_count or 0)
    rows_after = db_after.render_jobs_for_episode_rows or ()

    if exit_code == 0 and (new_row_count > 1 or total_new_row_count > new_row_count):
        return ClassificationResult(
            "UNCLASSIFIED_REQUIRES_REVIEW",
            f"production CLI reported success but render_jobs deltas do not both equal exactly 1 "
            f"(episode delta={new_row_count}, table-wide total delta={total_new_row_count})",
            evidence,
        )

    # Finding 6 (Rev2) / R3-1, R3-2 (Rev3) / Rev4 Finding 1 / Rev6 Finding 2 /
    # Rev7 Finding 1: strengthened success classification -- exact row match
    # on BOTH deltas, AND the postflight episode row itself must still
    # exist, uniquely, with the expected project identity AND the expected
    # folder_path, not merely "some new row plus render_queued". The queue
    # operation is expected to change episode STATUS only -- an independent
    # replay reproduced a false pass where `episode_project_name` had
    # drifted to something else entirely while every other signal (exact
    # row, exit 0, valid-looking stdout) still looked correct; a second,
    # separate replay reproduced the same false pass via `folder_path`
    # drift (Rev6 Finding 2) -- `episode.folder_path` is what
    # `render/plan.py` actually uses to target the render output, so it is
    # just as mutation-relevant as `project_name`. A third, separate replay
    # (Rev7 Finding 1) proved the resolved-target check alone still
    # insufficient: a postflight `folder_path` that is merely a different,
    # syntactically equivalent spelling of the same resolved directory
    # passed every existing check. The production database source only
    # ever updates `episode.status`/`episode.updated_at` during queue
    # finalization -- it never rewrites `folder_path` -- so `db_after`'s
    # raw `episode_folder_path` must equal `db_before`'s raw value exactly,
    # in addition to (never instead of) the resolved-target equality check.
    if (
        exit_code == 0
        and db_after.integrity_check == "ok"
        and db_after.episode_exists
        and db_after.episode_row_count == 1
        and db_after.episode_status == "render_queued"
        and db_after.episode_project_name == EXPECTED_PROJECT_NAME
        and _resolve_episode_directory(db_after.episode_folder_path) == EXPECTED_EPISODE_DIRECTORY
        and db_after.episode_folder_path == db_before.episode_folder_path
        and new_row_count == 1
        and total_new_row_count == 1
        and len(rows_after) == 1
        and (db_after.archives_total_count or 0) == 0
        and not expected_output_exists
    ):
        row = rows_after[0]
        # Rev6 Finding 3: a successful postflight render_jobs row must have
        # a real database identity -- Rev5 skipped the Job ID comparison
        # entirely whenever `row.id` was None, letting an arbitrary stdout
        # `Job ID` value through unchecked. `row_ok` now requires `id` to be
        # a genuine positive integer as a precondition of success at all,
        # not merely a comparison that silently no-ops when absent.
        row_id = row.get("id")
        row_ok = (
            isinstance(row_id, int) and not isinstance(row_id, bool) and row_id > 0
            and row.get("preset_name") == PRESET_NAME
            and row.get("project_name") == EXPECTED_PROJECT_NAME
            and row.get("timeline_name") == EXPECTED_TIMELINE_NAME
            and row.get("status") == "queued"
            and isinstance(row.get("resolve_job_id"), str) and row.get("resolve_job_id", "").strip() != ""
            and row.get("output_path") == str(EXPECTED_OUTPUT_PATH)
        )
        # Rev5: full occurrence lists per label, not a collapsed single
        # value -- makes duplicate/contradictory stdout evidence visible in
        # classification evidence rather than silently resolved.
        stdout_occurrences = _parse_production_stdout_occurrences(stdout_text)
        evidence["render_job_row"] = row
        evidence["stdout_occurrences"] = stdout_occurrences
        if not row_ok:
            return ClassificationResult(
                "UNCLASSIFIED_REQUIRES_REVIEW",
                "exactly one new render_jobs row exists (matching both delta checks) but its fields do not exactly match the expected episode/preset/project/timeline/status/output_path",
                evidence,
            )
        # Rev3 Finding R3-2, hardened Rev6 Finding 1: non-empty stderr
        # alongside an otherwise apparent success is disqualifying, decided
        # from the RAW byte count, not decoded/stripped text -- Rev5's
        # `stderr_text.strip() != ""` check (a) silently became `False` for
        # non-UTF-8 stderr bytes (`CapturedOutput.text` is `None` there,
        # coerced to `""` before reaching this function) and (b) would also
        # have missed whitespace/newline-only stderr even if it were
        # UTF-8 (`"\n".strip() == ""`). Both were reproduced as real
        # false-passes by an independent replay. Any nonzero raw byte
        # count -- one stray `\xff`, a bare `\n`, anything -- now fails
        # closed.
        if effective_stderr_byte_length != 0:
            return ClassificationResult(
                "UNCLASSIFIED_REQUIRES_REVIEW",
                f"the database row and stdout otherwise look correct, but production CLI stderr contains "
                f"{effective_stderr_byte_length} raw byte(s); failing closed rather than inferring emptiness from decoded text",
                evidence,
            )
        stdout_failure_reason = _evaluate_production_stdout_success_evidence(stdout_occurrences, row)
        if stdout_failure_reason is not None:
            return ClassificationResult("UNCLASSIFIED_REQUIRES_REVIEW", stdout_failure_reason, evidence)
        return ClassificationResult(
            "PRODUCTION_QUEUE_PATH_ACCEPTED",
            "production CLI, adapter, and SQLite evidence all agree on exactly one accepted render job matching every expected field",
            evidence,
        )

    if any(fragment in combined_text for fragment in _MANUAL_RECONCILIATION_REQUIRED_SUBSTRINGS):
        return ClassificationResult("RECONCILIATION_ROLLBACK_FAILED_MANUAL_REQUIRED", "captured output matches a known manual-reconciliation-required message", evidence)

    if any(fragment in combined_text for fragment in _ACCEPTED_ROLLBACK_SUCCEEDED_SUBSTRINGS):
        return ClassificationResult("RECONCILIATION_ROLLBACK_SUCCEEDED", "captured output matches the known full-rollback-succeeded message", evidence)

    if any(fragment in combined_text for fragment in _ADD_CALLED_ACCEPTANCE_UNOBSERVED_SUBSTRINGS):
        return ClassificationResult("ADD_CALLED_ACCEPTANCE_UNOBSERVED", "captured output matches AddRenderJob acceptance-unresolved category text", evidence)

    if any(fragment in combined_text for fragment in _SETTINGS_MUTATED_ADD_NOT_ACCEPTED_SUBSTRINGS):
        return ClassificationResult("SETTINGS_MUTATED_ADD_NOT_ACCEPTED", "captured output matches AddRenderJob() returning False", evidence)

    if any(fragment in combined_text for fragment in _RENDER_CONFIGURATION_FAILED_SUBSTRINGS):
        return ClassificationResult(
            "SQLITE_CLAIM_RENDER_CONFIGURATION_FAILED_BEFORE_ADD_ACCEPTANCE",
            "captured output matches LoadRenderPreset/SetRenderSettings failure; either call may have been attempted against Resolve before failing -- this does not prove no Resolve state changed",
            evidence,
        )

    if any(fragment in combined_text for fragment in _RESOLVE_STATE_SELECTION_NO_CLAIM_SUBSTRINGS):
        return ClassificationResult("RESOLVE_STATE_SELECTION_NO_CLAIM", "captured output matches the renderability preflight's zero-video-payload failure (LoadProject occurred)", evidence)

    if _LIVE_RESOLVE_COLLISION_RE.search(combined_text):
        return ClassificationResult("RESOLVE_STATE_SELECTION_NO_CLAIM", "captured output matches a live Resolve render-queue collision (LoadProject occurred)", evidence)

    if _DB_COLLISION_RE.search(combined_text) or any(fragment in combined_text for fragment in _RESOLVE_CONNECTED_EARLY_FAILURE_SUBSTRINGS):
        return ClassificationResult(
            "RESOLVE_CONNECTED_EARLY_FAILURE_NO_CLAIM",
            "captured output matches a known RenderManager failure that occurs after Resolve connection but before any SQLite claim",
            evidence,
        )

    if _CLAIM_RACE_COLLISION_TEXT in combined_text:
        return ClassificationResult(
            "RESOLVE_STATE_SELECTION_NO_CLAIM",
            "captured output matches the claim-race collision message; a Resolve collision check ran, no successful claim resulted", evidence,
        )

    return ClassificationResult(
        "UNCLASSIFIED_REQUIRES_REVIEW",
        "no known evidence pattern matched exit code, DB diff, or captured output; treat as requiring manual review, not as safe", evidence,
    )


# ---------------------------------------------------------------------------
# Preparation (shared by the safe preview path and the one live path)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PreparedAttempt:
    resolved_evidence_directory: Path
    repository_checkpoint_ok: bool
    mutation_bearing_source_hashes: dict[str, str]
    preflight_wrapper_sha256: str
    python_interpreter_identity: dict
    module_provenance_report: dict
    historical_preflight: dict
    db_baseline_before: DatabaseBaseline
    fresh_preflight_command: list[str]
    fresh_preflight_output_path: Path
    production_command: list[str]
    production_env: dict[str, str]


def _prepare_queue_attempt(authorization: QueueAttemptAuthorization) -> _PreparedAttempt:
    """Run every pre-flight check, in order, before any subprocess is built.

    Order: repository checkpoint -> mutation-bearing source hashes ->
    preflight wrapper hash -> Python interpreter -> module provenance ->
    evidence directory canonicalization -> historical preflight binding ->
    pre-mutation DB baseline -> pre-mutation filesystem baseline. Any
    failure raises `QueueAttemptContractError` before either subprocess
    command is even constructed.

    This is the FIRST mutation-boundary check. A second, identical
    (repository/source/DB/filesystem-only) recheck runs again inside
    `run_authorized_queue_attempt()` immediately after the fresh preflight
    reports PASS -- see `_verify_no_mutation_boundary_drift()` and Rev2
    Finding 4."""

    verify_repository_checkpoint(authorization.authorized_commit)
    mutation_hashes = verify_mutation_bearing_source_identity()
    preflight_wrapper_sha = verify_preflight_wrapper_source_identity()
    python_interpreter_identity = verify_python_interpreter(EXPECTED_PYTHON_EXECUTABLE)
    resolved_evidence_directory = canonicalize_and_validate_evidence_directory(authorization.evidence_output_directory)
    module_provenance_report = verify_module_provenance()
    historical_preflight = verify_historical_preflight_evidence()
    db_baseline_before = verify_pre_mutation_database_baseline()
    verify_pre_mutation_filesystem_baseline()

    fresh_preflight_output_path = resolved_evidence_directory / "fresh_preflight" / (
        f"RLC-E9901_queue_attempt_fresh_preflight_{authorization.authorized_commit[:7]}.json"
    )
    fresh_preflight_command = build_fresh_preflight_command(authorization.authorized_commit, fresh_preflight_output_path)
    production_command = build_production_command()
    production_env = build_production_environment(evidence_directory=resolved_evidence_directory)

    return _PreparedAttempt(
        resolved_evidence_directory=resolved_evidence_directory,
        repository_checkpoint_ok=True,
        mutation_bearing_source_hashes=mutation_hashes,
        preflight_wrapper_sha256=preflight_wrapper_sha,
        python_interpreter_identity=python_interpreter_identity,
        module_provenance_report=module_provenance_report,
        historical_preflight=historical_preflight,
        db_baseline_before=db_baseline_before,
        fresh_preflight_command=fresh_preflight_command,
        fresh_preflight_output_path=fresh_preflight_output_path,
        production_command=production_command,
        production_env=production_env,
    )


def preview_future_queue_attempt(authorization: QueueAttemptAuthorization) -> dict:
    """Run every pre-flight check and return the exact future commands/environment. Never launches anything."""

    prepared = _prepare_queue_attempt(authorization)
    return {
        "fresh_preflight_command": prepared.fresh_preflight_command,
        "production_command": prepared.production_command,
        "production_cwd": str(PRODUCTION_CWD),
        "production_env_overrides": build_production_environment({}, evidence_directory=prepared.resolved_evidence_directory),
        "resolved_evidence_directory": str(prepared.resolved_evidence_directory),
        "mutation_bearing_source_hashes": prepared.mutation_bearing_source_hashes,
        "preflight_wrapper_sha256": prepared.preflight_wrapper_sha256,
        "module_provenance_report": prepared.module_provenance_report,
        "historical_preflight": prepared.historical_preflight,
        "db_baseline_before": prepared.db_baseline_before.to_dict(),
    }


# ---------------------------------------------------------------------------
# The one live-capable orchestration path
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueAttemptResult:
    stop_reason: str | None
    fresh_preflight_render_status: str | None
    fresh_preflight_stdout: CapturedOutput
    fresh_preflight_stderr: CapturedOutput
    fresh_preflight_exit_code: int | None
    fresh_preflight_launch_error: dict | None
    fresh_preflight_snapshot_path: str | None
    fresh_preflight_snapshot_sha256: str | None
    production_launched: bool
    production_exit_code: int | None
    production_stdout: CapturedOutput
    production_stderr: CapturedOutput
    production_launch_error: dict | None
    production_timed_out: bool
    db_baseline_before: DatabaseBaseline
    db_baseline_after: DatabaseBaseline | None
    classification: ClassificationResult | None
    evidence_directory: str

    def to_dict(self) -> dict:
        return {
            "stop_reason": self.stop_reason,
            "fresh_preflight_render_status": self.fresh_preflight_render_status,
            "fresh_preflight_stdout": self.fresh_preflight_stdout.to_dict(),
            "fresh_preflight_stderr": self.fresh_preflight_stderr.to_dict(),
            "fresh_preflight_exit_code": self.fresh_preflight_exit_code,
            "fresh_preflight_launch_error": self.fresh_preflight_launch_error,
            "fresh_preflight_snapshot_path": self.fresh_preflight_snapshot_path,
            "fresh_preflight_snapshot_sha256": self.fresh_preflight_snapshot_sha256,
            "production_launched": self.production_launched,
            "production_exit_code": self.production_exit_code,
            "production_stdout": self.production_stdout.to_dict(),
            "production_stderr": self.production_stderr.to_dict(),
            "production_launch_error": self.production_launch_error,
            "production_timed_out": self.production_timed_out,
            "db_baseline_before": self.db_baseline_before.to_dict(),
            "db_baseline_after": self.db_baseline_after.to_dict() if self.db_baseline_after else None,
            "classification": self.classification.to_dict() if self.classification else None,
            "evidence_directory": self.evidence_directory,
        }


def _write_evidence_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _build_stopped_result(
    *, stop_reason: str, evidence_dir: Path, db_baseline_before: DatabaseBaseline,
    fresh_preflight_render_status: str | None = None,
    fresh_preflight_stdout: CapturedOutput = _ABSENT_CAPTURED_OUTPUT,
    fresh_preflight_stderr: CapturedOutput = _ABSENT_CAPTURED_OUTPUT,
    fresh_preflight_exit_code: int | None = None,
    fresh_preflight_launch_error: dict | None = None,
    fresh_preflight_snapshot_path: str | None = None,
    fresh_preflight_snapshot_sha256: str | None = None,
) -> QueueAttemptResult:
    """Build a `QueueAttemptResult` for any of the several paths that stop
    before the production CLI is ever launched (Rev2: factored out to avoid
    five near-duplicate dataclass constructions across the fresh-preflight
    timeout/launch-failure/not-passing, snapshot-binding-failure, and
    mutation-boundary-drift stop points -- production_launched is always
    False here, by construction, never something a caller can get wrong)."""

    return QueueAttemptResult(
        stop_reason=stop_reason,
        fresh_preflight_render_status=fresh_preflight_render_status,
        fresh_preflight_stdout=fresh_preflight_stdout, fresh_preflight_stderr=fresh_preflight_stderr,
        fresh_preflight_exit_code=fresh_preflight_exit_code,
        fresh_preflight_launch_error=fresh_preflight_launch_error,
        fresh_preflight_snapshot_path=fresh_preflight_snapshot_path,
        fresh_preflight_snapshot_sha256=fresh_preflight_snapshot_sha256,
        production_launched=False, production_exit_code=None,
        production_stdout=_ABSENT_CAPTURED_OUTPUT, production_stderr=_ABSENT_CAPTURED_OUTPUT,
        production_launch_error=None, production_timed_out=False,
        db_baseline_before=db_baseline_before, db_baseline_after=None,
        classification=None, evidence_directory=str(evidence_dir),
    )


def _finalize_stopped_result(evidence_dir: Path, result: QueueAttemptResult) -> QueueAttemptResult:
    """Write final_result.json and the SHA-256 manifest for a stopped
    (production-never-launched) result. Rev2 Finding 7B: every fresh
    preflight stop branch -- timeout, launch failure, or not-passing --
    must reach this, not just the "not passing" branch Rev1 covered."""

    _write_evidence_file(evidence_dir / "final_result.json", result.to_dict())
    _write_sha256_manifest(evidence_dir)
    return result


def run_authorized_queue_attempt(
    authorization: QueueAttemptAuthorization, *, fresh_preflight_timeout: int = 120, production_timeout: int = 120,
) -> QueueAttemptResult:
    """THE ONE live-capable orchestration path.

    Reached only through this module's `run-queue-attempt` CLI subcommand.
    Not invoked by this construction/static-review mission's own work.

    Sequence: `_prepare_queue_attempt()` (repository checkpoint, source
    hashes, Python interpreter, evidence directory, module provenance,
    historical preflight, DB/filesystem baseline -- any failure raises
    before any subprocess exists) -> create `<evidence_dir>/fresh_preflight`
    (Finding 1) -> exactly one `subprocess.run` launching the
    already-reviewed preflight wrapper's `run-live-preflight` subcommand
    (the fresh getter-only guard) -> require its `render_preflight_status
    == "passed"` -> verify the fresh snapshot's exact bytes (Finding 5) ->
    rerun the mutation-boundary gates (Finding 4) -> exactly one
    `subprocess.run` launching the one production CLI command -> read-only
    DB baseline again (exception-safe, Finding 10) -> classify (Findings 2,
    3, 6) -> write the full evidence package -> return one combined
    `QueueAttemptResult`.

    No retry of either subprocess. No branch of this function deletes,
    rewrites, or repairs anything at the evidence directory, the database,
    or the RLC-E9901 workspace. `manifest.json`,
    `fresh_preflight_invocation.json`, and `production_command.json` are
    each written exactly once (Rev2 Finding 8) -- none is ever rewritten
    after being written the first time."""

    prepared = _prepare_queue_attempt(authorization)
    evidence_dir = prepared.resolved_evidence_directory
    evidence_dir.mkdir(parents=True, exist_ok=False)
    prepare_fresh_preflight_evidence_subdirectory(evidence_dir)

    manifest: dict[str, Any] = {
        "mission": MISSION,
        "authorized_commit": authorization.authorized_commit,
        "episode_id": EPISODE_ID,
        "preset_name": PRESET_NAME,
        "expected_project_name": EXPECTED_PROJECT_NAME,
        "expected_timeline_name": EXPECTED_TIMELINE_NAME,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "mutation_bearing_source_hashes": prepared.mutation_bearing_source_hashes,
        "preflight_wrapper_sha256": prepared.preflight_wrapper_sha256,
        "module_provenance_report": prepared.module_provenance_report,
        "historical_preflight": prepared.historical_preflight,
    }
    _write_evidence_file(evidence_dir / "manifest.json", manifest)
    _write_evidence_file(evidence_dir / "db_preflight.json", prepared.db_baseline_before.to_dict())

    # --- Fresh preflight invocation record, written BEFORE launch (Finding 7A/8) ---
    _write_evidence_file(evidence_dir / "fresh_preflight_invocation.json", {
        "attempted": True, "command": prepared.fresh_preflight_command,
        "attempted_at_utc": datetime.now(timezone.utc).isoformat(),
    })

    # --- Launch site 1 of exactly 2 in this function: fresh getter-only guard ---
    # Rev3 Finding R3-3: deliberately NOT `text=True`. With text mode,
    # subprocess.run() decodes the pipe internally using the platform
    # default encoding, and an undecodable byte can raise UnicodeDecodeError
    # from *inside* subprocess.run() itself -- before this harness's own
    # `_normalize_captured_output()` (which already has a lossless
    # base64 fallback for exactly this case) ever sees anything. Binary
    # capture makes `fresh_result.stdout`/`.stderr` (and
    # `TimeoutExpired.stdout`/`.stderr`) raw `bytes` unconditionally, which
    # `_normalize_captured_output()` already handles.
    try:
        fresh_result = subprocess.run(
            prepared.fresh_preflight_command, cwd=str(CANONICAL_REPOSITORY_ROOT),
            capture_output=True, timeout=fresh_preflight_timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result = _build_stopped_result(
            stop_reason="fresh_preflight_timed_out", evidence_dir=evidence_dir, db_baseline_before=prepared.db_baseline_before,
            fresh_preflight_stdout=_normalize_captured_output(exc.stdout), fresh_preflight_stderr=_normalize_captured_output(exc.stderr),
        )
        return _finalize_stopped_result(evidence_dir, result)
    except OSError as exc:
        result = _build_stopped_result(
            stop_reason="fresh_preflight_launch_failed", evidence_dir=evidence_dir, db_baseline_before=prepared.db_baseline_before,
            fresh_preflight_launch_error=_describe_os_error(exc),
        )
        return _finalize_stopped_result(evidence_dir, result)

    fresh_stdout = _normalize_captured_output(fresh_result.stdout)
    fresh_stderr = _normalize_captured_output(fresh_result.stderr)
    _write_evidence_file(evidence_dir / "fresh_preflight_result.json", {
        "exit_code": fresh_result.returncode, "stdout": fresh_stdout.to_dict(), "stderr": fresh_stderr.to_dict(),
    })

    fresh_stdout_obj: dict | None = None
    if fresh_result.returncode == 0 and fresh_stdout.text:
        try:
            fresh_stdout_obj = json.loads(fresh_stdout.text)
        except json.JSONDecodeError:
            fresh_stdout_obj = None
    fresh_render_status = fresh_stdout_obj.get("render_preflight_status") if fresh_stdout_obj else None
    wrapper_snapshot_path = fresh_stdout_obj.get("snapshot_path") if fresh_stdout_obj else None
    wrapper_snapshot_sha256 = fresh_stdout_obj.get("snapshot_sha256") if fresh_stdout_obj else None

    if fresh_render_status != "passed":
        result = _build_stopped_result(
            stop_reason="fresh_preflight_not_passing", evidence_dir=evidence_dir, db_baseline_before=prepared.db_baseline_before,
            fresh_preflight_render_status=fresh_render_status, fresh_preflight_stdout=fresh_stdout, fresh_preflight_stderr=fresh_stderr,
            fresh_preflight_exit_code=fresh_result.returncode,
        )
        return _finalize_stopped_result(evidence_dir, result)

    # Rev6 Finding 1: a fresh preflight result may be treated as PASS only
    # if the WRAPPER PROCESS's own raw stderr stream is exactly zero bytes
    # -- distinct from, and in addition to, exit code 0 and
    # render_preflight_status == "passed" above. This is the wrapper
    # subprocess's own stderr stream, never the `collector_stderr` field
    # embedded inside the wrapper's own JSON stdout result (that field is
    # the wrapper's own preserved evidence of ITS internal collector
    # subprocess, a separate concern already handled by the published,
    # independently-reviewed wrapper itself). Decided from the raw byte
    # count, never from decoded/stripped text, for the identical reason as
    # the production stderr check.
    fresh_stderr_byte_length = fresh_stderr.byte_length if fresh_stderr.byte_length is not None else 0
    if fresh_stderr_byte_length != 0:
        result = _build_stopped_result(
            stop_reason="fresh_preflight_stderr_nonempty", evidence_dir=evidence_dir, db_baseline_before=prepared.db_baseline_before,
            fresh_preflight_render_status=fresh_render_status, fresh_preflight_stdout=fresh_stdout, fresh_preflight_stderr=fresh_stderr,
            fresh_preflight_exit_code=fresh_result.returncode,
        )
        return _finalize_stopped_result(evidence_dir, result)

    # --- Bind the fresh preflight to its exact snapshot bytes (Finding 5) ---
    try:
        snapshot_binding = verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=prepared.fresh_preflight_output_path,
            wrapper_reported_snapshot_path=wrapper_snapshot_path,
            wrapper_reported_snapshot_sha256=wrapper_snapshot_sha256,
        )
        _write_evidence_file(evidence_dir / "fresh_preflight_snapshot_binding.json", {"result": "passed", **snapshot_binding})
    except QueueAttemptContractError as exc:
        _write_evidence_file(evidence_dir / "fresh_preflight_snapshot_binding.json", {"result": "stopped", "error": exc.to_dict()})
        result = _build_stopped_result(
            stop_reason=f"fresh_preflight_snapshot_binding_failed:{exc.code}", evidence_dir=evidence_dir, db_baseline_before=prepared.db_baseline_before,
            fresh_preflight_render_status=fresh_render_status, fresh_preflight_stdout=fresh_stdout, fresh_preflight_stderr=fresh_stderr,
            fresh_preflight_exit_code=fresh_result.returncode,
        )
        return _finalize_stopped_result(evidence_dir, result)

    # --- Mutation-boundary recheck (Finding 4; evidence content per Rev3 Finding R3-5) ---
    try:
        recheck_evidence = _verify_no_mutation_boundary_drift(
            authorization.authorized_commit,
            initial_episode_folder_path=prepared.db_baseline_before.episode_folder_path,
        )
        _write_evidence_file(evidence_dir / "mutation_boundary_recheck.json", {"result": "passed", **recheck_evidence})
    except QueueAttemptContractError as exc:
        _write_evidence_file(evidence_dir / "mutation_boundary_recheck.json", {"result": "stopped", "error": exc.to_dict()})
        result = _build_stopped_result(
            stop_reason=f"mutation_boundary_drift_after_fresh_preflight:{exc.code}", evidence_dir=evidence_dir, db_baseline_before=prepared.db_baseline_before,
            fresh_preflight_render_status=fresh_render_status, fresh_preflight_stdout=fresh_stdout, fresh_preflight_stderr=fresh_stderr,
            fresh_preflight_exit_code=fresh_result.returncode,
            fresh_preflight_snapshot_path=snapshot_binding["path"], fresh_preflight_snapshot_sha256=snapshot_binding["sha256"],
        )
        return _finalize_stopped_result(evidence_dir, result)

    # --- Reviewed execution-environment evidence, written BEFORE launch (Rev4 Finding 4) ---
    _write_evidence_file(evidence_dir / "execution_environment.json", build_execution_environment_evidence(
        python_interpreter_identity=prepared.python_interpreter_identity,
        production_command=prepared.production_command, production_env=prepared.production_env,
    ))

    # --- Production invocation record, written BEFORE launch (Finding 7A/8) ---
    _write_evidence_file(evidence_dir / "production_command.json", {
        "attempted": True, "command": prepared.production_command, "cwd": str(PRODUCTION_CWD),
        "attempted_at_utc": datetime.now(timezone.utc).isoformat(),
    })

    # --- Launch site 2 of exactly 2 in this function: the one production CLI ---
    # Rev3 Finding R3-3: binary capture here too -- see the fresh-preflight
    # launch site's comment above for the full rationale.
    launch_error: dict | None = None
    timed_out = False
    prod_exit_code: int | None = None
    prod_stdout = _ABSENT_CAPTURED_OUTPUT
    prod_stderr = _ABSENT_CAPTURED_OUTPUT
    try:
        prod_result = subprocess.run(
            prepared.production_command, cwd=str(PRODUCTION_CWD), env=prepared.production_env,
            capture_output=True, timeout=production_timeout, check=False,
        )
        prod_exit_code = prod_result.returncode
        prod_stdout = _normalize_captured_output(prod_result.stdout)
        prod_stderr = _normalize_captured_output(prod_result.stderr)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        prod_stdout = _normalize_captured_output(exc.stdout)
        prod_stderr = _normalize_captured_output(exc.stderr)
    except OSError as exc:
        launch_error = _describe_os_error(exc)

    # Finding 7C: a process that failed to launch (OSError) must report
    # production_launched=False -- Rev1 hardcoded True here regardless.
    production_launched = launch_error is None

    # Rev3 Finding R3-7: timeout duration preserved explicitly in evidence,
    # since a forced timeout is a materially different condition from an
    # ordinary CLI failure or exit code (see classify_queue_attempt_outcome).
    _write_evidence_file(evidence_dir / "production_stdio.json", {
        "exit_code": prod_exit_code, "stdout": prod_stdout.to_dict(), "stderr": prod_stderr.to_dict(),
        "launch_error": launch_error, "timed_out": timed_out, "timeout_seconds": production_timeout,
        "production_launched": production_launched,
    })

    # Finding 10: exception-safe even if this raises internally -- it never does now, but the
    # postflight write below still proceeds unconditionally either way.
    db_baseline_after = read_database_baseline()
    _write_evidence_file(evidence_dir / "db_postflight.json", db_baseline_after.to_dict())
    expected_output_exists = EXPECTED_OUTPUT_PATH.exists()
    _write_evidence_file(evidence_dir / "filesystem_postflight.json", {
        "expected_output_path": str(EXPECTED_OUTPUT_PATH), "expected_output_exists": expected_output_exists,
    })

    classification = classify_queue_attempt_outcome(
        exit_code=prod_exit_code, stdout_text=prod_stdout.text or "", stderr_text=prod_stderr.text or "",
        db_before=prepared.db_baseline_before, db_after=db_baseline_after,
        launch_error=launch_error, timed_out=timed_out, expected_output_exists=expected_output_exists,
        # Rev6 Finding 1: the authoritative raw byte count, never re-derived
        # from possibly-`None` decoded text.
        stderr_byte_length=prod_stderr.byte_length if prod_stderr.byte_length is not None else 0,
    )
    _write_evidence_file(evidence_dir / "classification.json", classification.to_dict())

    result = QueueAttemptResult(
        stop_reason=None,
        fresh_preflight_render_status=fresh_render_status,
        fresh_preflight_stdout=fresh_stdout, fresh_preflight_stderr=fresh_stderr,
        fresh_preflight_exit_code=fresh_result.returncode,
        fresh_preflight_launch_error=None,
        fresh_preflight_snapshot_path=snapshot_binding["path"], fresh_preflight_snapshot_sha256=snapshot_binding["sha256"],
        production_launched=production_launched, production_exit_code=prod_exit_code,
        production_stdout=prod_stdout, production_stderr=prod_stderr,
        production_launch_error=launch_error, production_timed_out=timed_out,
        db_baseline_before=prepared.db_baseline_before, db_baseline_after=db_baseline_after,
        classification=classification, evidence_directory=str(evidence_dir),
    )
    _write_evidence_file(evidence_dir / "final_result.json", result.to_dict())
    _write_sha256_manifest(evidence_dir)
    return result


def _write_sha256_manifest(evidence_dir: Path) -> None:
    """Written last, after every other evidence file already exists -- a
    per-file SHA-256 manifest over everything else in the evidence
    directory (recursively, excluding itself). Called from every terminal
    path in `run_authorized_queue_attempt()`, including the fresh-preflight
    timeout/launch-failure paths Rev1 omitted this from (Finding 7B)."""

    manifest_path = evidence_dir / "sha256_manifest.json"
    entries: dict[str, str] = {}
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path != manifest_path:
            entries[str(path.relative_to(evidence_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
    _write_evidence_file(manifest_path, entries)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=MISSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_checkpoint = subparsers.add_parser("verify-checkpoint", help="Verify the repository checkpoint only. No Resolve contact.")
    verify_checkpoint.add_argument("--authorized-commit", required=True)

    subparsers.add_parser("verify-source", help="Verify mutation-bearing source and preflight-wrapper hashes only. No Resolve contact.")
    subparsers.add_parser("verify-python", help="Verify the Python 3.11.9 interpreter. No Resolve contact.")
    subparsers.add_parser("verify-module-provenance", help="Verify cli/redline_core module provenance. No Resolve contact.")
    subparsers.add_parser("verify-historical-preflight", help="Verify the preserved historical preflight evidence. No Resolve contact.")
    subparsers.add_parser("verify-db-baseline", help="Verify the pre-mutation database baseline, read-only. No Resolve contact.")

    preview = subparsers.add_parser("preview-invocation", help="Run every pre-flight check and print the exact future invocation. Never launches anything. No Resolve contact.")
    preview.add_argument("--authorized-commit", required=True)
    preview.add_argument("--evidence-directory", type=Path, required=True)

    live = subparsers.add_parser(
        "run-queue-attempt",
        help=(
            "THE ONLY live-capable subcommand. Launches the fresh getter-only preflight guard, "
            "then, only on PASS and after a mutation-boundary recheck, the one production "
            "render-queue CLI invocation. NOT invoked by the construction/static-review mission "
            "this file was written under."
        ),
    )
    live.add_argument("--authorized-commit", required=True)
    live.add_argument("--evidence-directory", type=Path, required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "verify-checkpoint":
            verify_repository_checkpoint(args.authorized_commit)
            _print_json({"result": "passed", "check": "repository_checkpoint"})
            return 0
        if args.command == "verify-source":
            hashes = verify_mutation_bearing_source_identity()
            preflight_wrapper_sha = verify_preflight_wrapper_source_identity()
            _print_json({"result": "passed", "check": "source_identity", "mutation_bearing_source_hashes": hashes, "preflight_wrapper_sha256": preflight_wrapper_sha})
            return 0
        if args.command == "verify-python":
            identity = verify_python_interpreter()
            _print_json({"result": "passed", "check": "python_interpreter", "identity": identity})
            return 0
        if args.command == "verify-module-provenance":
            report = verify_module_provenance()
            _print_json({"result": "passed", "check": "module_provenance", "report": report})
            return 0
        if args.command == "verify-historical-preflight":
            result = verify_historical_preflight_evidence()
            _print_json({"result": "passed", "check": "historical_preflight", **result})
            return 0
        if args.command == "verify-db-baseline":
            baseline = verify_pre_mutation_database_baseline()
            _print_json({"result": "passed", "check": "db_baseline", "baseline": baseline.to_dict()})
            return 0
        if args.command == "preview-invocation":
            authorization = QueueAttemptAuthorization(
                authorized_commit=args.authorized_commit, evidence_output_directory=args.evidence_directory,
            )
            _print_json(preview_future_queue_attempt(authorization))
            return 0
        if args.command == "run-queue-attempt":
            authorization = QueueAttemptAuthorization(
                authorized_commit=args.authorized_commit, evidence_output_directory=args.evidence_directory,
            )
            result = run_authorized_queue_attempt(authorization)
            _print_json(result.to_dict())
            if result.classification is not None and result.classification.code == "PRODUCTION_QUEUE_PATH_ACCEPTED":
                return 0
            if result.stop_reason is not None:
                return 2
            return 3
    except QueueAttemptContractError as exc:
        _print_json({"result": "stopped", "error": exc.to_dict()})
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
