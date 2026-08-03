from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import mission39i_live_queue_attempt as mission39i


class FakeRunner:
    def __init__(
        self,
        *,
        head: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        origin_master: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        live_remote: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ):
        self.calls: list[tuple[str, ...]] = []
        self.head = head
        self.origin_master = origin_master
        self.live_remote = live_remote

    def run(self, args, *, cwd: Path, env=None, timeout: int = 60):
        command = tuple(str(arg) for arg in args)
        self.calls.append(command)
        stdout = self._stdout_for(command)
        return mission39i.CommandResult(
            args=command,
            cwd=str(cwd),
            started_at="2026-08-02T00:00:00.000000Z",
            ended_at="2026-08-02T00:00:00.000001Z",
            exit_code=0,
            stdout=stdout,
            stderr="",
        )

    def _stdout_for(self, command: tuple[str, ...]) -> str:
        if command == ("git", "branch", "--show-current"):
            return "master\n"
        if command == ("git", "rev-parse", "HEAD"):
            return f"{self.head}\n"
        if command == ("git", "rev-parse", "origin/master"):
            return f"{self.origin_master}\n"
        if command == ("git", "remote", "get-url", "origin"):
            return f"{mission39i.EXPECTED_ORIGIN}\n"
        if command == ("git", "status", "--porcelain"):
            return "?? .claude/\n"
        if command == ("git", "ls-remote", "origin", "refs/heads/master"):
            return f"{self.live_remote}\trefs/heads/master\n"
        if command == (str(mission39i.EXPECTED_PYTHON_EXE), "--version"):
            return "Python 3.11.9\n"
        raise AssertionError(f"unexpected command: {command}")


def write_config(root: Path) -> None:
    config = root / "config"
    config.mkdir()
    (config / "naming.yaml").write_text(
        "episode_id_pattern: 'RLC-E{episode_number:03d}'\n"
        "project_name_pattern: '{episode_id}_MASTER'\n",
        encoding="utf-8",
    )
    (config / "folder_structure.yaml").write_text("root_path: './_episodes'\n", encoding="utf-8")
    (config / "render_presets.yaml").write_text(
        "presets:\n"
        "  - name: 'broadcast_master'\n"
        "    resolve_preset_name: 'Redline Broadcast Master'\n"
        "    output_subfolder: 'exports'\n"
        "    filename_template: '{project_name}'\n"
        "    file_extension: '.mov'\n"
        "    collision_policy: 'reject'\n",
        encoding="utf-8",
    )
    (config / "paths.yaml").write_text(
        "ingest_path: './_ingest'\n"
        "archive_path: './_archive'\n"
        "assets_path: './_assets'\n"
        "master_project_template: 'RLC_MASTER_TEMPLATE'\n",
        encoding="utf-8",
    )
    (config / "assets.yaml").write_text("assets: []\nrequired_for_episode: []\n", encoding="utf-8")
    (config / "timeline_template.yaml").write_text(
        "timeline_name_pattern: '{episode_id}_TIMELINE'\nmarkers: []\n",
        encoding="utf-8",
    )


def write_database(path: Path, episode_folder: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_number INTEGER NOT NULL UNIQUE,
                episode_id TEXT NOT NULL UNIQUE,
                project_name TEXT NOT NULL,
                project_path TEXT,
                folder_path TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                assembly_claim_token TEXT,
                assembly_claimed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE render_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                preset_name TEXT NOT NULL,
                resolve_job_id TEXT,
                project_name TEXT,
                timeline_name TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                output_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name, folder_path, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                9001,
                mission39i.EPISODE_ID,
                mission39i.PROJECT_NAME,
                str(episode_folder),
                "assembled",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_exact_queue_command_uses_reviewed_python_module_form():
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner())

    assert attempt.exact_queue_command() == [
        str(mission39i.EXPECTED_PYTHON_EXE),
        "-m",
        "cli.main",
        "render",
        "queue",
        "RLC-E9001",
        "broadcast_master",
    ]


def test_queue_inventory_sanitizes_queue_values():
    inventory = mission39i.queue_inventory(
        [
            {
                "JobId": "job-1",
                "TargetDir": "C:/private/output",
                "CustomName": "sensitive-name",
            },
            object(),
        ]
    )

    assert inventory["count"] == 2
    assert inventory["usable_job_ids"] == ["job-1"]
    assert inventory["items_missing_ids"] == 1
    assert inventory["non_dict_items"] == 1
    assert "TargetDir" in inventory["dict_keys"][0]
    assert "C:/private/output" not in repr(inventory)
    assert "sensitive-name" not in repr(inventory)


def test_classification_requires_authoritative_job_id_not_structural_change():
    before = mission39i.queue_inventory([{"JobId": "existing"}])
    after = mission39i.queue_inventory([{"JobId": "existing", "RenderJobName": "renamed"}])

    result = mission39i.classify_queue_outcome(
        cli_exit_code=0,
        add_result_type="bool",
        add_result_repr="True",
        before_inventory=before,
        after_inventory=after,
    )

    assert result["classification"] == "identity unresolved"


def test_classification_acceptance_not_observed_for_empty_result_unchanged_queue():
    before = mission39i.queue_inventory([{"JobId": "existing"}])
    after = mission39i.queue_inventory([{"JobId": "existing"}])

    result = mission39i.classify_queue_outcome(
        cli_exit_code=1,
        add_result_type="str",
        add_result_repr="''",
        before_inventory=before,
        after_inventory=after,
    )

    assert result["classification"] == "acceptance not observed"


def test_dry_review_stops_before_resolve_access_and_queue_invocation(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    write_config(repo)
    episode_folder = repo / "_episodes" / "RLC-E9001"
    (episode_folder / "exports").mkdir(parents=True)
    db_path = tmp_path / "redline.db"
    write_database(db_path, episode_folder)
    monkeypatch.setenv("REDLINE_DB_PATH", str(db_path))
    resolve_called = False

    def resolve_probe():
        nonlocal resolve_called
        resolve_called = True
        raise AssertionError("dry review must not inspect Resolve")

    attempt = mission39i.Mission39IAttempt(
        repo_root=repo,
        runner=FakeRunner(),
        resolve_probe=resolve_probe,
    )

    exit_code = attempt.run(
        execute=False,
        expected_script_hash=None,
        expected_repository_commit=None,
        founder_authorization=None,
        manual_observation_json=None,
        evidence_base_dir=tmp_path,
    )

    assert exit_code == 0
    assert resolve_called is False
    assert attempt.queue_invocation_count == 0


def test_live_execution_requires_matching_script_hash():
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner())

    with pytest.raises(mission39i.GateFailure, match="script SHA-256"):
        attempt._validate_script_authorization(
            execute=True,
            expected_script_hash="not-the-current-hash",
            expected_repository_commit="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            founder_authorization=mission39i.FOUNDER_AUTHORIZATION_PHRASE,
        )


def test_live_execution_requires_repository_commit_argument():
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner())

    with pytest.raises(mission39i.GateFailure, match="expected-repository-commit"):
        attempt._validate_script_authorization(
            execute=True,
            expected_script_hash=mission39i.script_sha256(),
            expected_repository_commit=None,
            founder_authorization=mission39i.FOUNDER_AUTHORIZATION_PHRASE,
        )


def test_live_execution_rejects_malformed_repository_commit_argument():
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner())

    with pytest.raises(mission39i.GateFailure, match="full 40-character"):
        attempt._validate_script_authorization(
            execute=True,
            expected_script_hash=mission39i.script_sha256(),
            expected_repository_commit="20b7e38",
            founder_authorization=mission39i.FOUNDER_AUTHORIZATION_PHRASE,
        )


def test_repository_gate_rejects_local_head_mismatch(tmp_path):
    evidence = mission39i.EvidencePackage(tmp_path / "evidence")
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner(head="b" * 40))

    with pytest.raises(mission39i.GateFailure, match="local HEAD"):
        attempt._gate_1_repository_identity(
            evidence,
            require_live_remote=True,
            expected_repository_commit="a" * 40,
        )


def test_repository_gate_rejects_origin_master_mismatch(tmp_path):
    evidence = mission39i.EvidencePackage(tmp_path / "evidence")
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner(origin_master="b" * 40))

    with pytest.raises(mission39i.GateFailure, match="origin/master"):
        attempt._gate_1_repository_identity(
            evidence,
            require_live_remote=True,
            expected_repository_commit="a" * 40,
        )


def test_repository_gate_rejects_live_remote_mismatch(tmp_path):
    evidence = mission39i.EvidencePackage(tmp_path / "evidence")
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner(live_remote="b" * 40))

    with pytest.raises(mission39i.GateFailure, match="live remote master"):
        attempt._gate_1_repository_identity(
            evidence,
            require_live_remote=True,
            expected_repository_commit="a" * 40,
        )


def test_repository_gate_accepts_explicit_matching_commit_pin(tmp_path):
    evidence = mission39i.EvidencePackage(tmp_path / "evidence")
    attempt = mission39i.Mission39IAttempt(runner=FakeRunner())

    result = attempt._gate_1_repository_identity(
        evidence,
        require_live_remote=True,
        expected_repository_commit="a" * 40,
    )

    assert result["head"] == "a" * 40
    assert result["origin_master"] == "a" * 40
    assert result["live_remote_master"] == "a" * 40
    assert result["expected_repository_commit"] == "a" * 40
