"""Mission 39I controlled live Broadcast Master queue-attempt harness.

This script is intentionally fail-closed. Its default mode is dry review:
it creates an evidence package and validates repository/configuration/SQLite
checks that do not require Resolve, then stops before any Resolve access.

A future live attempt requires all of the following:

* this reviewed script hash passed through --expected-script-sha256,
* the separately reviewed repository commit passed through
  --expected-repository-commit,
* --execute,
* the exact founder authorization phrase,
* a manual observation JSON file,
* every preflight gate passing in order.

Mission 39I.1 is authorized to create and statically validate this script
only. Do not run this script with --execute until a separate founder
authorization cites this script's SHA-256.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from redline_core.config.loader import load_config  # noqa: E402
from redline_core.db.models import Episode, EpisodeStatus  # noqa: E402
from redline_core.render.plan import build_render_output_plan  # noqa: E402

MISSION = "39I"
EXPECTED_BRANCH = "master"
EXPECTED_ORIGIN = "git@github.com:Choice283/redline-os.git"
EXPECTED_UNTRACKED_PATH = ".claude/"
EXPECTED_PYTHON_EXE = Path(r"C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe")
EXPECTED_PYTHON_VERSION = "3.11.9"
EPISODE_ID = "RLC-E9001"
PROJECT_NAME = "RLC-E9001_MASTER"
TIMELINE_NAME = "RLC-E9001_TIMELINE"
PRESET_NAME = "broadcast_master"
RESOLVE_PRESET_NAME = "Redline Broadcast Master"
EXPECTED_OUTPUT_NAME = "RLC-E9001_MASTER.mov"
FOUNDER_AUTHORIZATION_PHRASE = (
    "I authorize one controlled Mission 39I live queue attempt under the reviewed contract and "
    "identified script hash. No retry, render start, cancellation, deletion, configuration change, "
    "or additional submission is authorized."
)
QUEUE_JOB_ID_KEYS = ("JobId", "JobID", "jobId", "job_id", "Id", "ID", "id")


class GateFailure(RuntimeError):
    """Raised when any preflight or postflight gate fails closed."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: str
    started_at: str
    ended_at: str
    exit_code: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        started_at = utc_now()
        proc = subprocess.run(
            list(args),
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        ended_at = utc_now()
        return CommandResult(
            args=tuple(str(arg) for arg in args),
            cwd=str(cwd),
            started_at=started_at,
            ended_at=ended_at,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


class EvidencePackage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "commands").mkdir()
        (self.root / "logs").mkdir()
        (self.root / "snapshots").mkdir()
        self._commands: list[dict[str, Any]] = []

    def write_json(self, relative_path: str, value: Any) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")

    def write_text(self, relative_path: str, value: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def record_command(self, label: str, result: CommandResult) -> None:
        index = len(self._commands) + 1
        payload = {
            "label": label,
            "args": list(result.args),
            "cwd": result.cwd,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "exit_code": result.exit_code,
            "stdout_file": f"commands/{index:02d}_{label}_stdout.txt",
            "stderr_file": f"commands/{index:02d}_{label}_stderr.txt",
        }
        self.write_text(payload["stdout_file"], result.stdout)
        self.write_text(payload["stderr_file"], result.stderr)
        self._commands.append(payload)
        self.write_json("commands/commands.json", self._commands)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def script_sha256(path: Path = Path(__file__)) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_full_sha1_hex(value: str | None) -> bool:
    if value is None or len(value) != 40:
        return False
    return all(char in "0123456789abcdef" for char in value)


def render_job_id_from_mapping(job: object) -> str | None:
    if not isinstance(job, dict):
        return None
    for key in QUEUE_JOB_ID_KEYS:
        if key not in job:
            continue
        value = job[key]
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (str, int)):
            job_id = str(value).strip()
            if job_id:
                return job_id
    return None


def queue_inventory(jobs: object) -> dict[str, Any]:
    if jobs is None or jobs is False:
        jobs = []
    if not isinstance(jobs, list):
        return {
            "available": False,
            "container_type": type(jobs).__name__,
            "count": "unavailable",
            "item_types": "unavailable",
            "dict_keys": "unavailable",
            "usable_job_ids": "unavailable",
            "items_missing_ids": "unavailable",
            "non_dict_items": "unavailable",
            "fingerprint": "unavailable",
        }

    item_types: list[str] = []
    dict_keys: list[object] = []
    usable_job_ids: list[str] = []
    fingerprint: list[dict[str, object]] = []
    missing = 0
    non_dict = 0
    for item in jobs:
        item_type = type(item).__name__
        item_types.append(item_type)
        job_id = render_job_id_from_mapping(item)
        if job_id is None:
            missing += 1
        else:
            usable_job_ids.append(job_id)
        if isinstance(item, dict):
            try:
                keys = sorted(str(key) for key in item.keys())
            except Exception:
                keys = ["<unavailable>"]
        else:
            keys = None
            non_dict += 1
        dict_keys.append(keys)
        fingerprint.append({"type": item_type, "keys": keys, "has_usable_job_id": job_id is not None})

    return {
        "available": True,
        "container_type": "list",
        "count": len(jobs),
        "item_types": item_types,
        "dict_keys": dict_keys,
        "usable_job_ids": usable_job_ids,
        "items_missing_ids": missing,
        "non_dict_items": non_dict,
        "fingerprint": fingerprint,
    }


def queue_structural_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_count = before.get("count", "unavailable")
    after_count = after.get("count", "unavailable")
    count_delta: object = "unavailable"
    if isinstance(before_count, int) and isinstance(after_count, int):
        count_delta = after_count - before_count
    return {
        "before_count": before_count,
        "after_count": after_count,
        "count_delta": count_delta,
        "fingerprint_changed": before.get("fingerprint") != after.get("fingerprint"),
        "before_fingerprint": before.get("fingerprint", "unavailable"),
        "after_fingerprint": after.get("fingerprint", "unavailable"),
    }


def compute_new_job_id_candidates(before_ids: Iterable[str], after_ids: Iterable[str]) -> list[str]:
    before_counts: dict[str, int] = {}
    for job_id in before_ids:
        before_counts[job_id] = before_counts.get(job_id, 0) + 1
    candidates: list[str] = []
    for job_id in after_ids:
        remaining = before_counts.get(job_id, 0)
        if remaining:
            before_counts[job_id] = remaining - 1
        else:
            candidates.append(job_id)
    return candidates


def classify_queue_outcome(
    *,
    cli_exit_code: int,
    add_result_type: str | None,
    add_result_repr: str | None,
    before_inventory: dict[str, Any],
    after_inventory: dict[str, Any],
) -> dict[str, Any]:
    before_ids = before_inventory.get("usable_job_ids")
    after_ids = after_inventory.get("usable_job_ids")
    if not isinstance(before_ids, list) or not isinstance(after_ids, list):
        return {"classification": "identity unresolved", "reason": "queue inventory unavailable"}
    candidates = compute_new_job_id_candidates(before_ids, after_ids)
    unidentified_after = after_inventory.get("items_missing_ids")
    if len(candidates) == 1 and cli_exit_code == 0:
        return {"classification": "queue acceptance observed", "resolve_job_id": candidates[0]}
    if (
        add_result_type == "str"
        and add_result_repr == "''"
        and candidates == []
        and sorted(before_ids) == sorted(after_ids)
        and unidentified_after == 0
    ):
        return {"classification": "acceptance not observed", "candidate_job_ids": candidates}
    if cli_exit_code != 0:
        return {"classification": "pre-acceptance failure or adapter-classified failure", "candidate_job_ids": candidates}
    return {"classification": "identity unresolved", "candidate_job_ids": candidates}


def sanitize_log_text(text: str) -> str:
    redacted_lines: list[str] = []
    for line in text.splitlines():
        if "OPENAI_API_KEY" in line or "sk-" in line:
            redacted_lines.append("<redacted sensitive log line>")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines) + ("\n" if text.endswith("\n") else "")


def create_evidence_package(base_dir: Path | None = None) -> EvidencePackage:
    base = base_dir or Path(tempfile.gettempdir())
    stamp = dt.datetime.now(dt.timezone.utc).strftime("redline-mission39i-%Y%m%dT%H%M%S%fZ")
    return EvidencePackage(base / stamp)


def require_command_success(evidence: EvidencePackage, label: str, result: CommandResult) -> str:
    evidence.record_command(label, result)
    if result.exit_code != 0:
        raise GateFailure(f"{label} failed with exit code {result.exit_code}: {result.stderr.strip()}")
    return result.stdout.strip()


def parse_status_porcelain(status_output: str) -> tuple[list[str], list[str]]:
    tracked: list[str] = []
    untracked: list[str] = []
    for line in status_output.splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            untracked.append(line)
        else:
            tracked.append(line)
    return tracked, untracked


def row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        episode_number=row["episode_number"],
        episode_id=row["episode_id"],
        project_name=row["project_name"],
        project_path=row["project_path"],
        folder_path=row["folder_path"],
        status=EpisodeStatus(row["status"]),
        assembly_claim_token=row["assembly_claim_token"],
        assembly_claimed_at=row["assembly_claimed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class Mission39IAttempt:
    def __init__(
        self,
        *,
        repo_root: Path = REPO_ROOT,
        python_exe: Path = EXPECTED_PYTHON_EXE,
        runner: CommandRunner | None = None,
        resolve_probe: Callable[[], Any] | None = None,
    ):
        self.repo_root = repo_root.resolve()
        self.python_exe = python_exe
        self.runner = runner or CommandRunner()
        self.resolve_probe = resolve_probe or self._probe_resolve_read_only
        self.queue_invocation_count = 0
        self.baseline_queue_inventory: dict[str, Any] | None = None
        self.output_path: Path | None = None
        self.output_directory: Path | None = None
        self.db_path: Path | None = None

    def run(
        self,
        *,
        execute: bool,
        expected_script_hash: str | None,
        expected_repository_commit: str | None,
        founder_authorization: str | None,
        manual_observation_json: Path | None,
        evidence_base_dir: Path | None = None,
    ) -> int:
        evidence = create_evidence_package(evidence_base_dir)
        evidence.write_json(
            "manifest.json",
            {
                "mission": MISSION,
                "created_at": utc_now(),
                "repo_root": str(self.repo_root),
                "script_path": str(Path(__file__).resolve()),
                "script_sha256": script_sha256(),
                "expected_repository_commit": expected_repository_commit,
                "mode": "execute" if execute else "dry-review",
            },
        )
        try:
            self._validate_script_authorization(
                execute=execute,
                expected_script_hash=expected_script_hash,
                expected_repository_commit=expected_repository_commit,
                founder_authorization=founder_authorization,
            )
            baseline = self._gate_1_repository_identity(
                evidence,
                require_live_remote=execute,
                expected_repository_commit=expected_repository_commit,
            )
            interpreter = self._gate_2_interpreter(evidence)
            config_payload = self._gate_3_configuration(evidence)
            sqlite_payload = self._gate_4_sqlite(evidence, config_payload["config"])
            if not execute:
                evidence.write_json(
                    "dry_review_result.json",
                    {
                        "result": "stopped before Resolve access by design",
                        "completed_gates": [1, 2, 3, 4],
                        "exact_live_command": self.exact_queue_command(),
                    },
                )
                print(f"DRY REVIEW COMPLETE: evidence={evidence.root}")
                return 0

            resolve_payload = self._gate_5_resolve_read_only(evidence)
            self._gate_6_manual_observation(evidence, manual_observation_json)
            self._gate_7_immediate_revalidation(evidence, baseline, sqlite_payload, resolve_payload)
            cli_result = self._execute_single_queue_command(evidence)
            self._postflight(evidence, cli_result)
            evidence.write_json(
                "result.json",
                {
                    "result": "completed",
                    "queue_invocation_count": self.queue_invocation_count,
                    "python": interpreter,
                },
            )
            print(f"LIVE ATTEMPT COMPLETE: evidence={evidence.root}")
            return cli_result.exit_code
        except GateFailure as exc:
            evidence.write_json(
                "result.json",
                {
                    "result": "stopped",
                    "reason": str(exc),
                    "queue_invocation_count": self.queue_invocation_count,
                },
            )
            print(f"MISSION 39I STOPPED: {exc}", file=sys.stderr)
            print(f"EVIDENCE: {evidence.root}", file=sys.stderr)
            return 2

    def _validate_script_authorization(
        self,
        *,
        execute: bool,
        expected_script_hash: str | None,
        expected_repository_commit: str | None,
        founder_authorization: str | None,
    ) -> None:
        current_hash = script_sha256()
        if execute:
            if expected_script_hash != current_hash:
                raise GateFailure("script SHA-256 does not match --expected-script-sha256")
            if not is_full_sha1_hex(expected_repository_commit):
                raise GateFailure("--expected-repository-commit must be a full 40-character lowercase SHA-1")
            if founder_authorization != FOUNDER_AUTHORIZATION_PHRASE:
                raise GateFailure("founder authorization phrase missing or not exact")

    def _gate_1_repository_identity(
        self,
        evidence: EvidencePackage,
        *,
        require_live_remote: bool,
        expected_repository_commit: str | None,
    ) -> dict[str, Any]:
        branch = require_command_success(
            evidence,
            "git_branch",
            self.runner.run(("git", "branch", "--show-current"), cwd=self.repo_root),
        )
        head = require_command_success(
            evidence,
            "git_head",
            self.runner.run(("git", "rev-parse", "HEAD"), cwd=self.repo_root),
        )
        origin_master = require_command_success(
            evidence,
            "git_origin_master",
            self.runner.run(("git", "rev-parse", "origin/master"), cwd=self.repo_root),
        )
        origin = require_command_success(
            evidence,
            "git_origin_url",
            self.runner.run(("git", "remote", "get-url", "origin"), cwd=self.repo_root),
        )
        tracked_status = require_command_success(
            evidence,
            "git_status_tracked",
            self.runner.run(("git", "status", "--porcelain", "--untracked-files=no"), cwd=self.repo_root),
        )
        default_status = require_command_success(
            evidence,
            "git_status_porcelain",
            self.runner.run(("git", "status", "--porcelain"), cwd=self.repo_root),
        )
        other_paths = require_command_success(
            evidence,
            "git_untracked_paths",
            self.runner.run(("git", "ls-files", "--others", "--exclude-standard", "--directory"), cwd=self.repo_root),
        )
        claude_paths = require_command_success(
            evidence,
            "git_claude_untracked_metadata",
            self.runner.run(
                ("git", "ls-files", "--others", "--exclude-standard", "--directory", "--", ".claude/"),
                cwd=self.repo_root,
            ),
        )
        claude_tracked = require_command_success(
            evidence,
            "git_claude_tracked_metadata",
            self.runner.run(("git", "ls-files", "--stage", "--", ".claude/"), cwd=self.repo_root),
        )
        tracked, _default_untracked = parse_status_porcelain(default_status)
        tracked_only_status = [line for line in tracked_status.splitlines() if line]
        untracked_paths = [line for line in other_paths.splitlines() if line]
        claude_untracked_paths = [line for line in claude_paths.splitlines() if line]
        claude_tracked_paths = [line for line in claude_tracked.splitlines() if line]
        live_remote = origin_master
        if require_live_remote:
            live_remote_output = require_command_success(
                evidence,
                "git_ls_remote_master",
                self.runner.run(("git", "ls-remote", "origin", "refs/heads/master"), cwd=self.repo_root, timeout=120),
            )
            live_remote = live_remote_output.split()[0] if live_remote_output.split() else ""

        payload = {
            "expected_repository_commit": expected_repository_commit,
            "branch": branch,
            "head": head,
            "origin_master": origin_master,
            "live_remote_master": live_remote,
            "origin": origin,
            "tracked_status": tracked,
            "tracked_only_status": tracked_only_status,
            "default_status_raw": default_status,
            "untracked_paths": untracked_paths,
            "claude_untracked_metadata": claude_untracked_paths,
            "claude_tracked_metadata": claude_tracked_paths,
        }
        evidence.write_json("snapshots/gate_1_repository.json", payload)
        if branch != EXPECTED_BRANCH:
            raise GateFailure(f"unexpected branch: {branch}")
        if require_live_remote and not is_full_sha1_hex(expected_repository_commit):
            raise GateFailure("--expected-repository-commit is required for live repository validation")
        if expected_repository_commit is not None:
            if head != expected_repository_commit:
                raise GateFailure("local HEAD does not match expected repository commit")
            if origin_master != expected_repository_commit:
                raise GateFailure("origin/master does not match expected repository commit")
            if require_live_remote and live_remote != expected_repository_commit:
                raise GateFailure("live remote master does not match expected repository commit")
        if origin != EXPECTED_ORIGIN:
            raise GateFailure(f"unexpected origin URL: {origin}")
        if tracked or tracked_only_status:
            raise GateFailure(f"tracked working tree is not clean: {tracked or tracked_only_status}")
        if untracked_paths != [EXPECTED_UNTRACKED_PATH]:
            raise GateFailure(f"unexpected untracked paths: {untracked_paths}")
        if claude_untracked_paths != [EXPECTED_UNTRACKED_PATH]:
            raise GateFailure(f".claude/ metadata check failed: {claude_untracked_paths}")
        if claude_tracked_paths:
            raise GateFailure(".claude/ is tracked, but it must remain untracked")
        return payload

    def _gate_2_interpreter(self, evidence: EvidencePackage) -> dict[str, str]:
        version_result = self.runner.run((str(self.python_exe), "--version"), cwd=self.repo_root)
        version = require_command_success(evidence, "python_version", version_result)
        current_payload = {
            "approved_executable": str(self.python_exe),
            "approved_version_output": version,
            "script_executable": sys.executable,
            "script_version": platform.python_version(),
            "pythonpath": os.environ.get("PYTHONPATH", ""),
            "resolve_script_api": os.environ.get("RESOLVE_SCRIPT_API", ""),
            "resolve_script_lib": os.environ.get("RESOLVE_SCRIPT_LIB", ""),
        }
        evidence.write_json("snapshots/gate_2_interpreter.json", current_payload)
        if self.python_exe != EXPECTED_PYTHON_EXE:
            raise GateFailure(f"unexpected Python executable: {self.python_exe}")
        if version != f"Python {EXPECTED_PYTHON_VERSION}":
            raise GateFailure(f"unexpected Python version: {version}")
        return current_payload

    def _gate_3_configuration(self, evidence: EvidencePackage) -> dict[str, Any]:
        config = load_config(self.repo_root / "config")
        preset = config.render_presets.get(PRESET_NAME)
        if preset is None:
            raise GateFailure("broadcast_master preset is missing")
        payload = {
            "preset": {
                "name": preset.name,
                "resolve_preset_name": preset.resolve_preset_name,
                "output_subfolder": preset.output_subfolder,
                "filename_template": preset.filename_template,
                "file_extension": preset.file_extension,
                "collision_policy": preset.collision_policy,
            },
            "expected_relative_output": f"{preset.output_subfolder}/{EXPECTED_OUTPUT_NAME}",
        }
        evidence.write_json("snapshots/gate_3_configuration.json", payload)
        if preset.resolve_preset_name != RESOLVE_PRESET_NAME:
            raise GateFailure("broadcast_master Resolve preset mapping changed")
        if preset.output_subfolder != "exports":
            raise GateFailure("broadcast_master output_subfolder changed")
        if preset.filename_template != "{project_name}" or preset.file_extension != ".mov":
            raise GateFailure("broadcast_master output naming changed")
        if preset.collision_policy != "reject":
            raise GateFailure("broadcast_master collision policy changed")
        return {"config": config, "preset": preset, "payload": payload}

    def _gate_4_sqlite(self, evidence: EvidencePackage, config) -> dict[str, Any]:
        self.db_path = Path(os.environ.get("REDLINE_DB_PATH", self.repo_root / "redline.db")).resolve()
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise GateFailure(f"could not open SQLite database read-only: {exc}") from exc
        conn.row_factory = sqlite3.Row
        try:
            episode_row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (EPISODE_ID,)).fetchone()
            if episode_row is None:
                raise GateFailure(f"episode {EPISODE_ID} not found")
            episode = row_to_episode(episode_row)
            if episode.project_name != PROJECT_NAME:
                raise GateFailure(f"unexpected project name: {episode.project_name}")
            if episode.status not in {
                EpisodeStatus.TIMELINE_BUILT,
                EpisodeStatus.ASSEMBLED,
            }:
                raise GateFailure(f"episode status is not valid for queue submission: {episode.status.value}")
            plan = build_render_output_plan(episode, config.render_presets.get(PRESET_NAME), TIMELINE_NAME)
            self.output_directory = plan.output_directory
            self.output_path = plan.output_path
            if plan.project_name != PROJECT_NAME or plan.timeline_name != TIMELINE_NAME:
                raise GateFailure("render plan project/timeline mismatch")
            if plan.output_stem != PROJECT_NAME or plan.file_extension != ".mov":
                raise GateFailure("render plan output naming mismatch")
            target_access = self._target_directory_diagnostics(plan.output_directory)
            if not target_access["exists"] or not target_access["is_dir"] or not target_access["read_accessible"]:
                raise GateFailure(f"target directory is not usable: {target_access}")
            if plan.output_path.exists():
                raise GateFailure(f"expected output already exists: {plan.output_path}")
            conflicts = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, episode_id, preset_name, status, output_path FROM render_jobs "
                    "WHERE output_path = ? AND status IN ('claiming', 'queued', 'rendering')",
                    (str(plan.output_path),),
                ).fetchall()
            ]
            if conflicts:
                raise GateFailure(f"active render output conflict exists: {conflicts}")
            render_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, episode_id, preset_name, resolve_job_id, project_name, timeline_name, status, output_path "
                    "FROM render_jobs WHERE episode_id = ? ORDER BY id",
                    (EPISODE_ID,),
                ).fetchall()
            ]
        finally:
            conn.close()

        payload = {
            "db_path": str(self.db_path),
            "episode": {
                "episode_id": episode.episode_id,
                "project_name": episode.project_name,
                "folder_path": episode.folder_path,
                "status": episode.status.value,
            },
            "planned_output_directory": str(plan.output_directory),
            "planned_output_path": str(plan.output_path),
            "target_directory_diagnostics": target_access,
            "render_rows_for_episode": render_rows,
            "active_output_conflicts": conflicts,
        }
        evidence.write_json("snapshots/gate_4_sqlite.json", payload)
        return payload

    def _target_directory_diagnostics(self, path: Path) -> dict[str, Any]:
        try:
            return {
                "path": str(path),
                "exists": path.exists(),
                "is_dir": path.is_dir(),
                "read_accessible": os.access(path, os.R_OK),
                "write_probe_performed": False,
            }
        except OSError as exc:
            return {
                "path": str(path),
                "exists": "unavailable",
                "is_dir": "unavailable",
                "read_accessible": False,
                "error_type": type(exc).__name__,
                "write_probe_performed": False,
            }

    def _gate_5_resolve_read_only(self, evidence: EvidencePackage) -> dict[str, Any]:
        payload = self.resolve_probe()
        evidence.write_json("snapshots/gate_5_resolve_read_only.json", payload)
        if payload.get("project_name") != PROJECT_NAME:
            raise GateFailure(f"Resolve current project mismatch: {payload.get('project_name')}")
        if TIMELINE_NAME not in payload.get("timeline_names", []):
            raise GateFailure(f"Resolve timeline {TIMELINE_NAME} not found")
        if payload.get("rendering_in_progress") is not False:
            raise GateFailure("Resolve reports active rendering")
        if RESOLVE_PRESET_NAME not in payload.get("render_presets", []):
            raise GateFailure(f"Resolve preset {RESOLVE_PRESET_NAME!r} not visible")
        inventory = payload.get("queue_inventory")
        if not isinstance(inventory, dict) or not inventory.get("available"):
            raise GateFailure("Resolve queue inventory unavailable")
        self.baseline_queue_inventory = inventory
        conflicts = []
        expected_output = str(self.output_path) if self.output_path else ""
        for item in payload.get("raw_queue_safe_items", []):
            if isinstance(item, dict) and item.get("output_path") == expected_output:
                conflicts.append(item)
        if conflicts:
            raise GateFailure(f"Resolve queue already contains expected output: {conflicts}")
        return payload

    def _probe_resolve_read_only(self) -> dict[str, Any]:
        import DaVinciResolveScript as bmd  # type: ignore[import-not-found]

        resolve = bmd.scriptapp("Resolve")
        if not resolve:
            raise GateFailure("Resolve Studio is not reachable")
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject()
        if not project:
            raise GateFailure("Resolve has no current project")
        project_name = project.GetName()
        timelines: list[str] = []
        for index in range(1, int(project.GetTimelineCount()) + 1):
            timeline = project.GetTimelineByIndex(index)
            if timeline:
                timelines.append(str(timeline.GetName()))
        jobs = project.GetRenderJobList()
        inventory = queue_inventory(jobs)
        render_presets = self._read_resolve_presets(project)
        safe_items = self._safe_queue_items(jobs)
        return {
            "project_name": project_name,
            "timeline_names": timelines,
            "rendering_in_progress": bool(project.IsRenderingInProgress()),
            "render_presets": render_presets,
            "queue_inventory": inventory,
            "raw_queue_safe_items": safe_items,
        }

    def _read_resolve_presets(self, project) -> list[str]:
        for method_name in ("GetRenderPresetList", "GetRenderPresetNames"):
            method = getattr(project, method_name, None)
            if callable(method):
                raw = method()
                if isinstance(raw, list):
                    return [str(item) for item in raw]
        raise GateFailure("Resolve project cannot report render presets read-only")

    def _safe_queue_items(self, jobs: object) -> list[dict[str, Any]]:
        if not isinstance(jobs, list):
            return []
        safe_items: list[dict[str, Any]] = []
        for job in jobs:
            if not isinstance(job, dict):
                safe_items.append({"type": type(job).__name__, "job_id": None, "keys": None})
                continue
            safe_items.append(
                {
                    "type": "dict",
                    "job_id": render_job_id_from_mapping(job),
                    "keys": sorted(str(key) for key in job.keys()),
                    "output_path": self._extract_queue_output_path(job),
                }
            )
        return safe_items

    def _extract_queue_output_path(self, job: dict[str, Any]) -> str | None:
        for directory_key in ("TargetDir", "targetDir", "target_dir", "OutputDir"):
            for name_key in ("CustomName", "customName", "custom_name", "RenderJobName"):
                if directory_key in job and name_key in job:
                    return str(Path(str(job[directory_key])) / f"{job[name_key]}.mov")
        return None

    def _gate_6_manual_observation(self, evidence: EvidencePackage, manual_observation_json: Path | None) -> None:
        if manual_observation_json is None:
            raise GateFailure("manual observation JSON is required for live execution")
        observation = json.loads(manual_observation_json.read_text(encoding="utf-8"))
        required_keys = {
            "resolve_page",
            "render_mode_observed",
            "visible_preset",
            "visible_filename",
            "visible_destination",
            "warnings_or_disabled_controls",
        }
        missing = sorted(required_keys - set(observation))
        if missing:
            raise GateFailure(f"manual observation JSON missing keys: {missing}")
        evidence.write_json("snapshots/gate_6_manual_observation.json", observation)

    def _gate_7_immediate_revalidation(
        self,
        evidence: EvidencePackage,
        baseline: dict[str, str],
        sqlite_payload: dict[str, Any],
        resolve_payload: dict[str, Any],
    ) -> None:
        current = self._gate_1_repository_identity(
            evidence,
            require_live_remote=True,
            expected_repository_commit=baseline.get("expected_repository_commit"),
        )
        if current != baseline:
            raise GateFailure("repository baseline changed between Gate 1 and Gate 7")
        if self.output_path is None or self.output_path.exists():
            raise GateFailure("output file appeared before submission")
        refreshed_sqlite = self._gate_4_sqlite(evidence, load_config(self.repo_root / "config"))
        if refreshed_sqlite["planned_output_path"] != sqlite_payload["planned_output_path"]:
            raise GateFailure("planned output changed before submission")
        refreshed_resolve = self._gate_5_resolve_read_only(evidence)
        if refreshed_resolve.get("queue_inventory") != resolve_payload.get("queue_inventory"):
            raise GateFailure("Resolve queue inventory changed before submission")
        evidence.write_json("snapshots/gate_7_immediate_revalidation.json", {"status": "passed"})

    def exact_queue_command(self) -> list[str]:
        return [str(self.python_exe), "-m", "cli.main", "render", "queue", EPISODE_ID, PRESET_NAME]

    def _execute_single_queue_command(self, evidence: EvidencePackage) -> CommandResult:
        if self.queue_invocation_count != 0:
            raise GateFailure("queue command was already invoked")
        self.queue_invocation_count += 1
        evidence.write_json(
            "attempt_counter.json",
            {
                "queue_command_invocations": self.queue_invocation_count,
                "max_authorized_invocations": 1,
                "recorded_at": utc_now(),
            },
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_ROOT)
        env["REDLINE_LOG_DIR"] = str(evidence.root / "logs" / "redline_app")
        result = self.runner.run(self.exact_queue_command(), cwd=self.repo_root, env=env, timeout=300)
        evidence.record_command("redline_render_queue_once", result)
        return result

    def _postflight(self, evidence: EvidencePackage, cli_result: CommandResult) -> None:
        before = self.baseline_queue_inventory or queue_inventory([])
        after_payload = self._gate_5_resolve_read_only(evidence)
        after = after_payload.get("queue_inventory", queue_inventory(None))
        app_log_dir = evidence.root / "logs" / "redline_app"
        sanitized_logs: dict[str, str] = {}
        if app_log_dir.exists():
            for log_file in app_log_dir.glob("*.log"):
                sanitized = sanitize_log_text(log_file.read_text(encoding="utf-8", errors="replace"))
                target = evidence.root / "logs" / f"sanitized_{log_file.name}"
                target.write_text(sanitized, encoding="utf-8")
                sanitized_logs[log_file.name] = str(target)
        classification = classify_queue_outcome(
            cli_exit_code=cli_result.exit_code,
            add_result_type=None,
            add_result_repr=None,
            before_inventory=before,
            after_inventory=after,
        )
        evidence.write_json(
            "postflight.json",
            {
                "cli_exit_code": cli_result.exit_code,
                "before_queue_inventory": before,
                "after_queue_inventory": after,
                "queue_structural_delta": queue_structural_delta(before, after),
                "classification": classification,
                "rendering_in_progress": after_payload.get("rendering_in_progress"),
                "output_file_exists": self.output_path.exists() if self.output_path else "unavailable",
                "sanitized_logs": sanitized_logs,
            },
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mission 39I controlled live queue attempt harness.")
    parser.add_argument("--execute", action="store_true", help="Run the live attempt after all gates pass.")
    parser.add_argument("--expected-script-sha256", help="Reviewed SHA-256 of this script.")
    parser.add_argument("--expected-repository-commit", help="Reviewed full commit that local/origin/live master must equal.")
    parser.add_argument("--founder-authorization", help="Exact founder authorization phrase.")
    parser.add_argument("--manual-observation-json", type=Path, help="Manual Resolve UI observation JSON.")
    parser.add_argument("--evidence-base-dir", type=Path, help="Parent directory for the evidence package.")
    parser.add_argument("--print-sha256", action="store_true", help="Print this script's SHA-256 and exit.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.print_sha256:
        print(script_sha256())
        return 0
    attempt = Mission39IAttempt()
    return attempt.run(
        execute=args.execute,
        expected_script_hash=args.expected_script_sha256,
        expected_repository_commit=args.expected_repository_commit,
        founder_authorization=args.founder_authorization,
        manual_observation_json=args.manual_observation_json,
        evidence_base_dir=args.evidence_base_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
