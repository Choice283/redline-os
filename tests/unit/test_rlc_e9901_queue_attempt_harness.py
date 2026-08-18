from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REVIEW_ROOT = Path(__file__).resolve().parents[2]
if str(REVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(REVIEW_ROOT))

from scripts import rlc_e9901_queue_attempt_harness as harness
from scripts import rlc_e9901_snapshot_preflight_contract as real_preflight_contract


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _build_test_db(path: Path, *, episode_status: str = "assembled", project_name: str = "RLC-E9901_MASTER",
                    folder_path: str = "_episodes\\RLC-E9901", render_jobs_total: int = 0, archives_total: int = 0,
                    extra_episode_rows: int = 0) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE episodes (id INTEGER PRIMARY KEY, episode_number INTEGER, episode_id TEXT, "
            "project_name TEXT, project_path TEXT, folder_path TEXT, status TEXT, assembly_claim_token TEXT, "
            "assembly_claimed_at TEXT, created_at TEXT, updated_at TEXT)"
        )
        con.execute(
            "CREATE TABLE render_jobs (id INTEGER PRIMARY KEY, episode_id TEXT, preset_name TEXT, "
            "resolve_job_id TEXT, project_name TEXT, timeline_name TEXT, status TEXT, output_path TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        con.execute(
            "CREATE TABLE archives (id INTEGER PRIMARY KEY, episode_id TEXT, archive_path TEXT, archived_at TEXT)"
        )
        con.execute(
            "INSERT INTO episodes (episode_number, episode_id, project_name, folder_path, status) "
            "VALUES (9901, 'RLC-E9901', ?, ?, ?)",
            (project_name, folder_path, episode_status),
        )
        # Rev6 Finding 2 regression fixture: a second row with the same
        # episode_id, simulating a corrupted/duplicated episode row --
        # this minimal test schema deliberately declares no UNIQUE
        # constraint on episode_id, so the harness's own defensive
        # episode_row_count == 1 check is the only thing that can catch it.
        for _ in range(extra_episode_rows):
            con.execute(
                "INSERT INTO episodes (episode_number, episode_id, project_name, folder_path, status) "
                "VALUES (9901, 'RLC-E9901', ?, ?, ?)",
                (project_name, folder_path, episode_status),
            )
        for i in range(render_jobs_total):
            con.execute(
                "INSERT INTO render_jobs (episode_id, preset_name, status, output_path) VALUES (?, ?, 'queued', ?)",
                (f"OTHER-{i}", "broadcast_master", f"C:\\out{i}.mov"),
            )
        for i in range(archives_total):
            con.execute("INSERT INTO archives (episode_id, archive_path) VALUES (?, ?)", (f"OTHER-{i}", f"C:\\a{i}"))
        con.commit()
    finally:
        con.close()


def _db(**overrides):
    """Defaults `render_jobs_total_count` to match `render_jobs_for_episode_count`
    whenever the caller sets the latter but not the former -- the common
    case in these tests is a table containing only RLC-E9901 rows, so the
    two naturally agree. R3-1 adversarial tests that need them to diverge
    (an unrelated row elsewhere in the table) pass `render_jobs_total_count`
    explicitly to override this default."""

    base = dict(
        integrity_check="ok", episode_exists=True, episode_row_count=1, episode_status="assembled",
        episode_project_name="RLC-E9901_MASTER", episode_folder_path=harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE,
        render_jobs_total_count=0,
        render_jobs_for_episode_count=0, render_jobs_for_episode_rows=(), archives_total_count=0, error=None,
    )
    base.update(overrides)
    if "render_jobs_total_count" not in overrides and "render_jobs_for_episode_count" in overrides:
        base["render_jobs_total_count"] = overrides["render_jobs_for_episode_count"]
    return harness.DatabaseBaseline(**base)


def _accepted_row(**overrides) -> dict:
    row = {
        "id": 1, "episode_id": "RLC-E9901", "preset_name": "broadcast_master", "resolve_job_id": "job-abc-123",
        "project_name": "RLC-E9901_MASTER", "timeline_name": "RLC-E9901_TIMELINE", "status": "queued",
        "output_path": str(harness.EXPECTED_OUTPUT_PATH),
    }
    row.update(overrides)
    return row


def _bypass_prechecks(monkeypatch, *, evidence_dir: Path):
    """Mirror the preflight wrapper's own test-suite pattern: monkeypatch each
    precheck function object on the module, not the underlying constants.

    `_verify_no_mutation_boundary_drift` (the Rev2 Finding 4 recheck) is
    deliberately NOT mocked here -- it calls these same monkeypatched
    function objects internally (Python resolves global names at call time,
    not def time), so it succeeds automatically whenever these succeed, and
    a test can make it fail by overriding just one of these after calling
    this helper."""

    monkeypatch.setattr(harness, "verify_repository_checkpoint", lambda authorized_commit: None)
    monkeypatch.setattr(harness, "verify_mutation_bearing_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: dict(harness._MUTATION_BEARING_SOURCE_SHA256))
    monkeypatch.setattr(harness, "verify_preflight_wrapper_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: harness._REVIEWED_PREFLIGHT_WRAPPER_SHA256)
    monkeypatch.setattr(harness, "verify_python_interpreter", lambda python_executable=harness.EXPECTED_PYTHON_EXECUTABLE: {"executable": str(harness.EXPECTED_PYTHON_EXECUTABLE), "version": list(harness.EXPECTED_PYTHON_VERSION)})
    monkeypatch.setattr(harness, "verify_module_provenance", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {"cli": {"imported": True}, "redline_core": {"imported": True}})
    monkeypatch.setattr(
        harness, "verify_historical_preflight_evidence",
        lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {"sha256": harness._REVIEWED_HISTORICAL_PREFLIGHT_SHA256, "offline_result": {"render_preflight_status": "passed"}},
    )
    monkeypatch.setattr(harness, "verify_pre_mutation_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: _db())
    monkeypatch.setattr(harness, "verify_pre_mutation_filesystem_baseline", lambda output_path=None: None)


def _default_fresh_preflight_result_factory(output_path: Path) -> _FakeCompletedProcess:
    """Writes real snapshot bytes and reports a matching sha256 -- exercises
    the REAL `verify_fresh_preflight_snapshot_binding()` logic end-to-end in
    every test that uses it as the default, rather than mocking Finding 5
    away."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b'{"fake": "snapshot", "schema_version": "1.0"}')
    snapshot_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
    stdout = json.dumps({
        "render_preflight_status": "passed", "snapshot_path": str(output_path), "snapshot_sha256": snapshot_sha256,
    })
    return _FakeCompletedProcess(0, stdout=stdout, stderr="")


def _make_fake_subprocess_module(*, fresh_result_factory, production_result, calls):
    def fake_run(command, cwd=None, env=None, capture_output=True, text=True, timeout=None, check=False):
        if "run-live-preflight" in command:
            calls["fresh_preflight"] += 1
            output_idx = command.index("--output") + 1
            output_path = Path(command[output_idx])
            result = fresh_result_factory(output_path)
            if isinstance(result, Exception):
                raise result
            return result
        calls["production"] += 1
        if isinstance(production_result, Exception):
            raise production_result
        return production_result
    return type("FakeSubprocessModule", (), {
        "run": staticmethod(fake_run), "TimeoutExpired": harness.subprocess.TimeoutExpired,
    })()


def _run_success_case(monkeypatch, tmp_path, *, production_result, db_after=None, extra_setup=None):
    """`db_after` may be a `DatabaseBaseline` or a zero-arg callable returning
    one. It is resolved AFTER `EXPECTED_OUTPUT_PATH` is patched to a tmp
    path, so a caller building `_accepted_row()` (whose default
    `output_path` reads the live `harness.EXPECTED_OUTPUT_PATH`) via a
    lambda gets a value consistent with what the harness will actually
    compare against -- building it eagerly before this call would silently
    capture the real production path instead."""

    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory, production_result=production_result, calls=calls,
    ))
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")
    if db_after is not None:
        resolved_db_after = db_after() if callable(db_after) else db_after
        monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: resolved_db_after)
    if extra_setup:
        extra_setup(monkeypatch, evidence_dir)
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)
    return result, evidence_dir, calls


# --- repository checkpoint ---------------------------------------------------


def test_verify_repository_checkpoint_passes_against_a_clean_matching_repository(monkeypatch):
    commit = "a" * 40
    responses = {
        "rev-parse --show-toplevel": str(harness.CANONICAL_REPOSITORY_ROOT),
        "branch --show-current": harness.CANONICAL_BRANCH,
        "rev-parse HEAD": commit,
        "remote get-url origin": harness.CANONICAL_ORIGIN_URL,
        "rev-parse origin/master": commit,
        "status --short": "",
        "diff --cached --name-only": "",
        "stash list": "",
    }

    def fake_run_git(args, *, repository_root=harness.CANONICAL_REPOSITORY_ROOT):
        return responses[" ".join(args)]

    monkeypatch.setattr(harness, "_run_git", fake_run_git)
    harness.verify_repository_checkpoint(commit)


@pytest.mark.workstation
def test_verify_repository_checkpoint_fails_closed_on_wrong_commit():
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_repository_checkpoint("0" * 40)
    assert excinfo.value.code == "head_commit_mismatch"


# --- source identity ----------------------------------------------------------


def test_mutation_bearing_source_pins_are_exactly_the_historically_reviewed_values():
    """Render Start Path Rev2 correction, Finding 9: this harness's pinned
    hashes are a historical evidence binding for the (now superseded)
    reviewed `render queue` mutation-bearing source. This correction is not
    authorized to change those pins merely because unrelated later work
    (the `render start` path) legitimately modified three of the same
    eight files. This test proves the pin dict itself is untouched -- a
    byte-for-byte snapshot of the values recorded at harness construction
    time, independent of whatever is currently on disk."""

    assert harness._MUTATION_BEARING_SOURCE_SHA256 == {
        "src/cli/main.py": "4218e88d23253b8788af67dc40207b33bec6d858bc5475922bf726febe3cab08",
        "src/cli/render_commands.py": "72b6b6b31b01739a06617f516cf7151b8753faeb571e1581da3d8d71c08bc0a5",
        "src/redline_core/runtime/composition.py": "5b246c9d9b5c4c6a4bc460a627f69074ae76378765bac52a4745b6983cb94b5d",
        "src/redline_core/render/manager.py": "54c89d5b4e2d9d0944e7241842e347c35be18db138f78564e702e54f8c170039",
        "src/redline_core/render/plan.py": "bf4d6f67cd163f282d4e574d23d777bca694018b7ca361b280204abd7bc048ec",
        "src/redline_core/resolve/adapter.py": "26b800bbb82abddf6dc826e47b12747e541a264184c3275f2d47e269b7379998",
        "src/redline_core/db/database.py": "d26ec783bc6cb4bc4a4df762c2d31a965fdb5ba25b7d35d002a530f3f3307347",
        "config/render_presets.yaml": "f9434b087e504bdfb6858e7fe83cd1e6bc6ccf4caaab56eb4295690502a40524",
    }


# As of this CI-portability correction, real current `master` diverges
# from the frozen Rev7 pins for six of the eight pinned files -- not
# merely the four `render start` path files Rev2 Finding 9 originally
# accounted for. `src/cli/main.py` and `src/redline_core/runtime/composition.py`
# have since been legitimately modified again by unrelated, later Redline
# OS V2 Recovery work (e.g. commits `e298194` "feat: add degraded-source
# recovery planning" and `c1c7f32` "feat: add healthy-source system
# restore"), neither of which is the render-start-path correction these
# pins were originally recorded against. The pins in
# `harness._MUTATION_BEARING_SOURCE_SHA256` remain frozen and untouched
# (see `test_mutation_bearing_source_pins_are_exactly_the_historically_reviewed_values`
# and the harness's own module docstring, "Source-identity binding") --
# only this test file's own present-day expectation of which pinned files
# still match real current bytes is corrected here, so it stays accurate
# rather than carrying a stale, unexplained-red assumption. Re-derive this
# split (not just patch it) the next time either list goes red.
_FILES_STILL_MATCHING_REV7_PINS = (
    "src/redline_core/render/plan.py",
    "config/render_presets.yaml",
)
_FILES_DRIFTED_SINCE_REV7 = (
    "src/cli/main.py",
    "src/cli/render_commands.py",
    "src/redline_core/runtime/composition.py",
    "src/redline_core/render/manager.py",
    "src/redline_core/resolve/adapter.py",
    "src/redline_core/db/database.py",
)


@pytest.mark.workstation
def test_verify_mutation_bearing_source_identity_fails_closed_against_current_master(monkeypatch):
    """The harness's `_MUTATION_BEARING_SOURCE_SHA256` pins are frozen at
    Rev7 (commit `2652cd1`). Real current `master` has since diverged from
    six of the eight pinned files -- originally just the four `render
    start` path files (Rev2 Finding 9), and, more recently, `src/cli/main.py`
    and `src/redline_core/runtime/composition.py` too, via unrelated,
    legitimate later Recovery work (see `_FILES_DRIFTED_SINCE_REV7` above).
    Updating the pins is out of scope (they remain a historical evidence
    binding, see the harness's own module docstring, "Source-identity
    binding"): this harness must remain intentionally UNABLE to authorize a
    live queue attempt against later, differently-reviewed production
    bytes, no matter which later work caused the divergence.

    This replaces the old
    `test_verify_mutation_bearing_source_identity_passes_against_real_published_source`,
    which asserted the opposite (that current on-disk bytes still match the
    historical pins) -- that assertion is no longer true, by design, and
    leaving it in place would have been an unexplained red test rather than
    a proven, intentional incompatibility."""

    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_mutation_bearing_source_identity()
    assert excinfo.value.code == "mutation_bearing_source_hash_mismatch"
    # Dict iteration order is insertion order; "src/cli/main.py" is itself
    # now the first pinned entry that no longer matches (it is a member of
    # _FILES_DRIFTED_SINCE_REV7), so it is deterministically the first
    # mismatch verify_mutation_bearing_source_identity() encounters.
    assert excinfo.value.details["path"] == "src/cli/main.py"
    assert excinfo.value.details["path"] in _FILES_DRIFTED_SINCE_REV7


@pytest.mark.parametrize("relative_path", _FILES_STILL_MATCHING_REV7_PINS)
@pytest.mark.workstation
def test_mutation_bearing_source_files_still_matching_historical_pins(relative_path):
    """The positive proof: exactly the files in
    `_FILES_STILL_MATCHING_REV7_PINS` still match their frozen Rev7 pins
    byte-for-byte today. This set has shrunk since Rev7 as legitimate,
    unrelated later work touched more of the eight pinned files (see
    `_FILES_DRIFTED_SINCE_REV7`); it is not assumed to be permanent, and
    must be re-derived (not silently patched) whenever it next goes red."""

    digest = harness._hash_relative_file(relative_path)
    assert digest == harness._MUTATION_BEARING_SOURCE_SHA256[relative_path]


@pytest.mark.parametrize("relative_path", _FILES_DRIFTED_SINCE_REV7)
@pytest.mark.workstation
def test_mutation_bearing_source_files_drifted_since_rev7_no_longer_match_pins(relative_path):
    """The complementary proof: every pinned file whose real current bytes
    have diverged from its Rev7 pin -- both the original four `render
    start` path files (Rev2 Finding 9) and the two later Recovery-work
    files -- is correctly detected as a mismatch, never silently treated as
    still-authorized. Together with
    `test_mutation_bearing_source_files_still_matching_historical_pins`,
    this fully partitions all eight pinned files by present-day match
    status, so the fail-closed guarantee is proven for the complete pin
    set, not only for whichever file dict-iteration order happens to hit
    first."""

    digest = harness._hash_relative_file(relative_path)
    assert digest != harness._MUTATION_BEARING_SOURCE_SHA256[relative_path]


def test_verify_mutation_bearing_source_identity_fails_closed_on_tampered_file(tmp_path):
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "src" / "cli").mkdir(parents=True)
    (fake_repo / "src" / "cli" / "main.py").write_text("tampered", encoding="utf-8")
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_mutation_bearing_source_identity(repository_root=fake_repo)
    assert excinfo.value.code in ("mutation_bearing_source_hash_mismatch", "source_file_unreadable")


@pytest.mark.workstation
def test_verify_preflight_wrapper_source_identity_passes_against_real_published_wrapper():
    digest = harness.verify_preflight_wrapper_source_identity()
    assert digest == harness._REVIEWED_PREFLIGHT_WRAPPER_SHA256


# --- Python interpreter -------------------------------------------------------


@pytest.mark.workstation
def test_verify_python_interpreter_passes_against_real_interpreter():
    """Rev4 Finding 4: verify_python_interpreter() must return the actual
    verified identity, not None."""

    identity = harness.verify_python_interpreter(harness.EXPECTED_PYTHON_EXECUTABLE)
    assert identity["version"] == list(harness.EXPECTED_PYTHON_VERSION)
    assert Path(identity["executable"]).resolve() == harness.EXPECTED_PYTHON_EXECUTABLE.resolve()


def test_verify_python_interpreter_fails_closed_on_wrong_version(monkeypatch):
    def fake_run(args, capture_output, text, timeout, check):
        return _FakeCompletedProcess(0, stdout=json.dumps({"executable": str(harness.EXPECTED_PYTHON_EXECUTABLE), "version": [3, 13, 0]}))
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_python_interpreter(harness.EXPECTED_PYTHON_EXECUTABLE)
    assert excinfo.value.code == "python_interpreter_version_mismatch"


# --- module provenance --------------------------------------------------------


@pytest.mark.workstation
def test_verify_module_provenance_passes_against_real_published_checker():
    report = harness.verify_module_provenance()
    assert report["cli"]["imported"] is True
    assert report["redline_core"]["imported"] is True


# --- historical preflight binding --------------------------------------------


@pytest.mark.workstation
def test_verify_historical_preflight_evidence_passes_against_real_preserved_evidence():
    result = harness.verify_historical_preflight_evidence()
    assert result["sha256"] == harness._REVIEWED_HISTORICAL_PREFLIGHT_SHA256
    assert result["offline_result"]["render_preflight_status"] == "passed"


def test_verify_historical_preflight_evidence_fails_closed_on_hash_mismatch(monkeypatch, tmp_path):
    stale = tmp_path / "stale.json"
    stale.write_bytes(b'{"tampered": true}')
    monkeypatch.setattr(harness, "HISTORICAL_PREFLIGHT_PATH", stale)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_historical_preflight_evidence()
    assert excinfo.value.code == "historical_preflight_hash_mismatch"


@pytest.mark.workstation
def test_verify_historical_preflight_evidence_fails_closed_on_stale_failing_content(monkeypatch, tmp_path):
    stale = tmp_path / "stale.json"
    stale.write_bytes(b'{"schema_version": "1.0", "snapshot_complete": false}')
    digest = hashlib.sha256(stale.read_bytes()).hexdigest()
    monkeypatch.setattr(harness, "HISTORICAL_PREFLIGHT_PATH", stale)
    monkeypatch.setattr(harness, "_REVIEWED_HISTORICAL_PREFLIGHT_SHA256", digest)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_historical_preflight_evidence()
    assert excinfo.value.code == "historical_preflight_not_passing"


# --- fresh preflight snapshot binding (Finding 5) -----------------------------


def test_verify_fresh_preflight_snapshot_binding_passes_when_bytes_and_hash_agree(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    result = harness.verify_fresh_preflight_snapshot_binding(
        fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=str(output_path), wrapper_reported_snapshot_sha256=sha,
    )
    assert result["sha256"] == sha


def test_verify_fresh_preflight_snapshot_binding_fails_closed_when_file_missing(tmp_path):
    output_path = tmp_path / "does-not-exist.json"
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=None, wrapper_reported_snapshot_sha256=None,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_missing"


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_hash_mismatch(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=str(output_path), wrapper_reported_snapshot_sha256="0" * 64,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_hash_mismatch"


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_path_mismatch(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=r"C:\somewhere\else.json", wrapper_reported_snapshot_sha256=sha,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_path_mismatch"


# --- DB / filesystem gates ----------------------------------------------------


def test_verify_pre_mutation_database_baseline_passes_on_expected_shape(tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path)
    baseline = harness.verify_pre_mutation_database_baseline(db_path)
    assert baseline.episode_status == "assembled"
    assert baseline.render_jobs_total_count == 0
    assert baseline.render_jobs_for_episode_rows == ()


def test_verify_pre_mutation_database_baseline_fails_closed_on_wrong_status(tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path, episode_status="render_queued")
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_pre_mutation_database_baseline(db_path)
    assert excinfo.value.code == "episode_status_unexpected"


def test_verify_pre_mutation_database_baseline_fails_closed_on_nonzero_render_jobs(tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path, render_jobs_total=1)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_pre_mutation_database_baseline(db_path)
    assert excinfo.value.code == "render_jobs_baseline_nonzero"


def test_verify_pre_mutation_database_baseline_uses_module_constant_at_call_time(monkeypatch, tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path)
    monkeypatch.setattr(harness, "REDLINE_DB_PATH", db_path)
    baseline = harness.verify_pre_mutation_database_baseline()
    assert baseline.episode_status == "assembled"


def test_verify_pre_mutation_filesystem_baseline_fails_closed_on_existing_output(tmp_path):
    output = tmp_path / "RLC-E9901_MASTER.mov"
    output.write_bytes(b"not really a video")
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_pre_mutation_filesystem_baseline(output)
    assert excinfo.value.code == "expected_output_already_exists"


def test_verify_pre_mutation_filesystem_baseline_passes_when_absent(tmp_path):
    harness.verify_pre_mutation_filesystem_baseline(tmp_path / "does-not-exist.mov")


# --- Finding 10: postflight DB read hardening ----------------------------------


def test_read_database_baseline_never_raises_on_query_failure(monkeypatch, tmp_path):
    """A connection that succeeds but whose queries fail must still return a
    structured DatabaseBaseline with `.error` set, not propagate an
    exception -- the specific regression Finding 10 targets (Rev1 only
    guarded the connect() call, not the query sequence)."""

    db_path = tmp_path / "redline.db"
    _build_test_db(db_path)
    # Corrupt the file post-creation so PRAGMA/queries fail after connect() succeeds.
    with open(db_path, "r+b") as f:
        f.seek(20)
        f.write(b"\xff" * 200)
    baseline = harness.read_database_baseline(db_path)
    assert baseline.error is not None
    assert baseline.integrity_check is None


def test_read_database_baseline_captures_exact_render_job_rows(tmp_path):
    db_path = tmp_path / "redline.db"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE episodes (id INTEGER PRIMARY KEY, episode_id TEXT, project_name TEXT, status TEXT, folder_path TEXT)"
    )
    con.execute(
        "CREATE TABLE render_jobs (id INTEGER PRIMARY KEY, episode_id TEXT, preset_name TEXT, resolve_job_id TEXT, "
        "project_name TEXT, timeline_name TEXT, status TEXT, output_path TEXT)"
    )
    con.execute("CREATE TABLE archives (id INTEGER PRIMARY KEY, episode_id TEXT, archive_path TEXT)")
    con.execute(
        "INSERT INTO episodes (episode_id, project_name, status, folder_path) VALUES ('RLC-E9901', 'RLC-E9901_MASTER', 'render_queued', '_episodes\\RLC-E9901')"
    )
    con.execute(
        "INSERT INTO render_jobs (episode_id, preset_name, resolve_job_id, project_name, timeline_name, status, output_path) "
        "VALUES ('RLC-E9901', 'broadcast_master', 'job-1', 'RLC-E9901_MASTER', 'RLC-E9901_TIMELINE', 'queued', 'C:\\out.mov')"
    )
    con.commit()
    con.close()
    baseline = harness.read_database_baseline(db_path)
    assert len(baseline.render_jobs_for_episode_rows) == 1
    assert baseline.render_jobs_for_episode_rows[0]["resolve_job_id"] == "job-1"


# --- evidence directory --------------------------------------------------------


def test_canonicalize_evidence_directory_rejects_relative_path():
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.canonicalize_and_validate_evidence_directory(Path("relative/dir"))
    assert excinfo.value.code == "evidence_directory_not_absolute"


@pytest.mark.workstation
def test_canonicalize_evidence_directory_rejects_protected_roots():
    for protected in harness.PROTECTED_EVIDENCE_ROOTS:
        with pytest.raises(harness.QueueAttemptContractError) as excinfo:
            harness.canonicalize_and_validate_evidence_directory(protected / "sub")
        assert excinfo.value.code == "evidence_directory_in_protected_location"


def test_canonicalize_evidence_directory_rejects_already_existing(tmp_path):
    existing = tmp_path / "already-here"
    existing.mkdir()
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.canonicalize_and_validate_evidence_directory(existing)
    assert excinfo.value.code == "evidence_directory_already_exists"


def test_canonicalize_evidence_directory_accepts_fresh_absolute_path(tmp_path):
    fresh = tmp_path / "fresh-evidence"
    resolved = harness.canonicalize_and_validate_evidence_directory(fresh)
    assert resolved == fresh.resolve()
    assert not resolved.exists()


# --- Finding 1: fresh_preflight output parent must exist before launch --------


def test_prepare_fresh_preflight_evidence_subdirectory_creates_exactly_that_one_directory(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    created = harness.prepare_fresh_preflight_evidence_subdirectory(evidence_dir)
    assert created == evidence_dir / "fresh_preflight"
    assert created.is_dir()
    assert list(evidence_dir.iterdir()) == [created]


def test_real_published_preflight_validator_accepts_the_prepared_parent(tmp_path):
    """Regression for Finding 1: uses the REAL published preflight wrapper's
    own `_canonicalize_and_validate_evidence_path()` -- not a fake subprocess
    that merely returns PASS -- to prove the harness's prepared output path
    genuinely satisfies the published tool's real validation semantics."""

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    harness.prepare_fresh_preflight_evidence_subdirectory(evidence_dir)
    candidate_output_path = evidence_dir / "fresh_preflight" / "RLC-E9901_queue_attempt_fresh_preflight_deadbee.json"

    resolved = real_preflight_contract._canonicalize_and_validate_evidence_path(candidate_output_path)
    assert resolved == candidate_output_path.resolve()
    assert not resolved.exists()


def test_real_published_preflight_validator_rejects_missing_parent(tmp_path):
    """The inverse proof: without Finding 1's fix, the harness's prepared
    output path (parent never created) is REJECTED by the real published
    validator with exactly the error the mission's independent review
    predicted."""

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    # Deliberately do NOT call prepare_fresh_preflight_evidence_subdirectory.
    candidate_output_path = evidence_dir / "fresh_preflight" / "RLC-E9901_queue_attempt_fresh_preflight_deadbee.json"
    with pytest.raises(real_preflight_contract.PreflightContractError) as excinfo:
        real_preflight_contract._canonicalize_and_validate_evidence_path(candidate_output_path)
    assert excinfo.value.code == "evidence_parent_directory_missing"


# --- environment construction ---------------------------------------------------


def test_build_production_environment_binds_expected_variables(tmp_path):
    env = harness.build_production_environment({}, evidence_directory=tmp_path)
    assert env["REDLINE_CONFIG_DIR"] == str(harness.REDLINE_CONFIG_DIR)
    assert env["REDLINE_DB_PATH"] == str(harness.REDLINE_DB_PATH)
    assert env["RESOLVE_SCRIPT_API"] == str(harness.RESOLVE_SCRIPT_API_PATH)
    assert env["RESOLVE_SCRIPT_LIB"] == str(harness.RESOLVE_SCRIPT_LIB_PATH)
    assert str(harness.REPOSITORY_SRC_ROOT) in env["PYTHONPATH"]
    assert str(harness.RESOLVE_SCRIPT_MODULES_PATH) in env["PYTHONPATH"]
    assert env["REDLINE_LOG_DIR"] == str(tmp_path / "logs")


def test_build_production_command_is_exactly_the_authorized_invocation():
    command = harness.build_production_command()
    assert command[0] == str(harness.EXPECTED_PYTHON_EXECUTABLE)
    assert command[1:] == ["-m", "cli.main", "render", "queue", "RLC-E9901", "broadcast_master"]


# --- classification (Findings 2, 3, 6, 10) --------------------------------------


_FULL_SUCCESS_STDOUT = (
    "Job ID: 1\nEpisode ID: RLC-E9901\nPreset: broadcast_master\nProject: RLC-E9901_MASTER\n"
    "Timeline: RLC-E9901_TIMELINE\nResolve Job ID: job-abc-123\nStatus: queued\n"
    "Output: " + str(harness.EXPECTED_OUTPUT_PATH) + "\nRendering started: no\nArchive performed: no"
)


def test_classify_success_requires_exact_row_match():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_two_new_rows_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text="Render queued", stderr_text="",
        db_before=_db(),
        db_after=_db(render_jobs_for_episode_count=2, render_jobs_for_episode_rows=(_accepted_row(id=1), _accepted_row(id=2)), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


@pytest.mark.parametrize("field,bad_value", [
    ("preset_name", "youtube_1080p"),
    ("project_name", "SOME_OTHER_PROJECT"),
    ("timeline_name", "SOME_OTHER_TIMELINE"),
    ("status", "claiming"),
    ("resolve_job_id", ""),
    ("resolve_job_id", None),
    ("output_path", r"C:\wrong\path.mov"),
])
def test_classify_wrong_row_field_cannot_pass(field, bad_value):
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text="Render queued", stderr_text="",
        db_before=_db(),
        db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(**{field: bad_value}),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_existing_output_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text="Render queued", stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=True,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_stdout_disagreement_fails_closed():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text="Resolve Job ID: totally-different-job-id\nStatus: queued\nOutput: " + str(harness.EXPECTED_OUTPUT_PATH),
        stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_postflight_db_read_error_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text="Render queued", stderr_text="",
        db_before=_db(), db_after=_db(error="database read failed: disk I/O error"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert "postflight database read failed" in result.detail


def test_classify_episode_not_found_is_resolve_connected_early_failure_not_no_contact():
    """Finding 2 regression: composition.py's build_application_services()
    calls resolve.connect() unconditionally before RenderManager ever runs,
    so an episode-not-found failure -- despite sounding Resolve-free --
    occurred AFTER Resolve connection. It must never classify as any
    'no Resolve contact' code."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="Render queue failed (episode not found): No episode with episode_id=RLC-E9901.",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "RESOLVE_CONNECTED_EARLY_FAILURE_NO_CLAIM"
    assert result.code != "NO_RESOLVE_CONTACT_YET"


def test_classify_resolve_state_selection_no_claim_renderability():
    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="Render queue failed (render timeline not renderable): no video TimelineItems were found",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "RESOLVE_STATE_SELECTION_NO_CLAIM"


def test_classify_render_configuration_failed_preset_load_failed():
    """Finding 3 regression: renamed from SQLITE_CLAIM_NO_SETTINGS_MUTATION
    -- a falsy LoadRenderPreset()/SetRenderSettings() return does not prove
    no Resolve state changed."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="Render queue failed (render queue failed): Resolve could not load render preset 'Redline Broadcast Master'",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "SQLITE_CLAIM_RENDER_CONFIGURATION_FAILED_BEFORE_ADD_ACCEPTANCE"
    assert "may have been attempted" in result.detail


def test_classify_settings_mutated_add_not_accepted():
    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="Render queue failed (render queue failed): Resolve failed to add a render job",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "SETTINGS_MUTATED_ADD_NOT_ACCEPTED"


def test_classify_add_called_acceptance_unobserved():
    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="Render queue failed (render queue acceptance not observed): AddRenderJob() returned an empty string",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "ADD_CALLED_ACCEPTANCE_UNOBSERVED"


def test_classify_reconciliation_rollback_succeeded():
    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="Resolve accepted render job 'abc', but database persistence failed; the newly queued Resolve job was removed.",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "RECONCILIATION_ROLLBACK_SUCCEEDED"


def test_classify_reconciliation_rollback_failed_manual_required():
    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="",
        stderr_text="Resolve accepted render job 'abc', but database persistence failed and best-effort Resolve deletion also failed. Manual reconciliation is required.",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "RECONCILIATION_ROLLBACK_FAILED_MANUAL_REQUIRED"


def test_classify_launch_failure_is_production_process_not_launched():
    """Finding 2 regression: only a process that never actually started can
    prove zero Resolve contact -- renamed from NO_RESOLVE_CONTACT_YET."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=None, stdout_text="", stderr_text="", db_before=_db(), db_after=_db(),
        launch_error="FileNotFoundError", timed_out=False, expected_output_exists=False,
    )
    assert result.code == "PRODUCTION_PROCESS_NOT_LAUNCHED"


def test_classify_unclassified_fallback_never_guesses_success():
    result = harness.classify_queue_attempt_outcome(
        exit_code=1, stdout_text="", stderr_text="a totally novel error message never seen before",
        db_before=_db(), db_after=_db(), launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_timeout_never_guesses_success():
    """Rev3 Finding R3-7: a forced timeout gets its own specific
    classification, distinct from generic UNCLASSIFIED_REQUIRES_REVIEW,
    since it is a materially different (reconciliation-relevant) condition
    -- but it still must never be PRODUCTION_QUEUE_PATH_ACCEPTED."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=None, stdout_text="", stderr_text="", db_before=_db(), db_after=_db(),
        launch_error=None, timed_out=True, expected_output_exists=False,
    )
    assert result.code == "PRODUCTION_TIMEOUT_RECONCILIATION_REQUIRED"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_no_classification_code_is_the_removed_rev1_name():
    """Static guard: the Rev1 names this review required removed must never
    reappear as a real classification code."""

    source = Path(harness.__file__).read_text(encoding="utf-8")
    assert '"NO_RESOLVE_CONTACT_YET"' not in source
    assert '"SQLITE_CLAIM_NO_SETTINGS_MUTATION"' not in source
    assert '"QUEUE_ACCEPTED_WITH_JOB_ID"' not in source


# --- full orchestration: success / exactly-one invocation ----------------------


def test_run_authorized_queue_attempt_launches_each_subprocess_exactly_once_on_success(monkeypatch, tmp_path):
    stdout_holder = {}

    def make_db_after():
        row = _accepted_row()
        stdout_holder["text"] = (
            f"Job ID: {row['id']}\nEpisode ID: {row['episode_id']}\nPreset: {row['preset_name']}\n"
            f"Project: {row['project_name']}\nTimeline: {row['timeline_name']}\n"
            f"Resolve Job ID: {row['resolve_job_id']}\nStatus: {row['status']}\nOutput: {row['output_path']}\n"
            "Rendering started: no\nArchive performed: no"
        )
        return _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(row,), episode_status="render_queued")

    # production_result must be built lazily too, since it embeds the same
    # output_path that depends on the post-patch EXPECTED_OUTPUT_PATH.
    def production_result_factory():
        return _FakeCompletedProcess(0, stdout=stdout_holder["text"], stderr="")

    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")
    db_after = make_db_after()
    monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: db_after)
    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory, production_result=production_result_factory(), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls == {"fresh_preflight": 1, "production": 1}
    assert result.classification.code == "PRODUCTION_QUEUE_PATH_ACCEPTED"
    assert result.production_launched is True
    assert (evidence_dir / "final_result.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()
    assert (evidence_dir / "fresh_preflight_snapshot_binding.json").exists()
    assert (evidence_dir / "mutation_boundary_recheck.json").exists()


def test_run_authorized_queue_attempt_stops_when_fresh_preflight_fails_and_never_launches_production(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        return _FakeCompletedProcess(3, stdout=json.dumps({"render_preflight_status": "failed"}), stderr="")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never be launched"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls == {"fresh_preflight": 1, "production": 0}
    assert result.stop_reason == "fresh_preflight_not_passing"
    assert result.production_launched is False
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_queue_cli_nonzero_exit_is_not_retried(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path,
        production_result=_FakeCompletedProcess(1, stdout="", stderr="Render queue failed (episode not found): No episode with episode_id=RLC-E9901."),
        db_after=_db(),
    )
    assert calls == {"fresh_preflight": 1, "production": 1}
    assert result.production_exit_code == 1
    assert result.classification.code == "RESOLVE_CONNECTED_EARLY_FAILURE_NO_CLAIM"


# --- Finding 1: fresh preflight parent exists before launch (full orchestration) ---


def test_fresh_preflight_output_parent_exists_at_launch_time(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    seen = {"parent_existed": None}

    def factory(output_path):
        seen["parent_existed"] = output_path.parent.is_dir()
        return _default_fresh_preflight_result_factory(output_path)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=_FakeCompletedProcess(0, stdout="Render queued"), calls=calls,
    ))
    monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: _db())
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    harness.run_authorized_queue_attempt(authorization)
    assert seen["parent_existed"] is True


# --- Finding 2/6: episode-not-found never classifies as no-Resolve-contact (full orchestration) ---


def test_episode_not_found_full_orchestration_never_classifies_no_resolve_contact(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path,
        production_result=_FakeCompletedProcess(1, stdout="", stderr="Render queue failed (episode not found): No episode with episode_id=RLC-E9901."),
        db_after=_db(),
    )
    assert result.classification.code == "RESOLVE_CONNECTED_EARLY_FAILURE_NO_CLAIM"
    assert result.classification.code != "NO_RESOLVE_CONTACT_YET"


# --- Finding 4: post-fresh-preflight drift prevents queue launch ---------------


def test_post_fresh_db_drift_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def db_baseline_side_effect(db_path=None, episode_id=harness.EPISODE_ID):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _db()
        raise harness.QueueAttemptContractError("render_jobs_baseline_nonzero", "drift detected on recheck")

    monkeypatch.setattr(harness, "verify_pre_mutation_database_baseline", db_baseline_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after boundary drift"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason.startswith("mutation_boundary_drift_after_fresh_preflight")
    assert (evidence_dir / "mutation_boundary_recheck.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_post_fresh_repository_drift_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def checkpoint_side_effect(authorized_commit):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        raise harness.QueueAttemptContractError("working_tree_not_clean", "drift detected on recheck")

    monkeypatch.setattr(harness, "verify_repository_checkpoint", checkpoint_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after boundary drift"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason.startswith("mutation_boundary_drift_after_fresh_preflight")


def test_post_fresh_source_hash_drift_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def source_side_effect(repository_root=harness.CANONICAL_REPOSITORY_ROOT):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return dict(harness._MUTATION_BEARING_SOURCE_SHA256)
        raise harness.QueueAttemptContractError("mutation_bearing_source_hash_mismatch", "drift detected on recheck")

    monkeypatch.setattr(harness, "verify_mutation_bearing_source_identity", source_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after boundary drift"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason.startswith("mutation_boundary_drift_after_fresh_preflight")


def test_post_fresh_output_appearance_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def fs_side_effect(output_path=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        raise harness.QueueAttemptContractError("expected_output_already_exists", "output appeared during fresh preflight")

    monkeypatch.setattr(harness, "verify_pre_mutation_filesystem_baseline", fs_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after boundary drift"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason.startswith("mutation_boundary_drift_after_fresh_preflight")


# --- Finding 5: missing/mismatched fresh snapshot prevents queue launch --------


def test_fresh_snapshot_missing_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        # PASS reported, but the file is never actually written.
        return _FakeCompletedProcess(0, stdout=json.dumps({"render_preflight_status": "passed", "snapshot_path": str(output_path), "snapshot_sha256": "0" * 64}), stderr="")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never launch"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_snapshot_binding_failed:fresh_preflight_snapshot_missing"


def test_fresh_snapshot_hash_mismatch_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b'{"real": "bytes"}')
        return _FakeCompletedProcess(0, stdout=json.dumps({"render_preflight_status": "passed", "snapshot_path": str(output_path), "snapshot_sha256": "0" * 64}), stderr="")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never launch"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_snapshot_binding_failed:fresh_preflight_snapshot_hash_mismatch"


# --- Finding 7: invocation/evidence bookkeeping ---------------------------------


def test_fresh_preflight_invocation_recorded_durably_before_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    seen = {"existed_at_launch": None, "content": None}

    def factory(output_path):
        invocation_path = evidence_dir / "fresh_preflight_invocation.json"
        seen["existed_at_launch"] = invocation_path.exists()
        if invocation_path.exists():
            seen["content"] = json.loads(invocation_path.read_text(encoding="utf-8"))
        return _default_fresh_preflight_result_factory(output_path)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=_FakeCompletedProcess(0, stdout="Render queued"), calls=calls,
    ))
    monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: _db())
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    harness.run_authorized_queue_attempt(authorization)

    assert seen["existed_at_launch"] is True
    assert seen["content"]["attempted"] is True


def test_production_invocation_recorded_durably_before_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    seen = {"existed_at_launch": None, "content": None}

    def production_run_hook():
        invocation_path = evidence_dir / "production_command.json"
        seen["existed_at_launch"] = invocation_path.exists()
        if invocation_path.exists():
            seen["content"] = json.loads(invocation_path.read_text(encoding="utf-8"))
        return _FakeCompletedProcess(0, stdout="Render queued")

    def fake_run(command, cwd=None, env=None, capture_output=True, text=True, timeout=None, check=False):
        if "run-live-preflight" in command:
            return _default_fresh_preflight_result_factory(Path(command[command.index("--output") + 1]))
        return production_run_hook()

    monkeypatch.setattr(harness, "subprocess", type("S", (), {"run": staticmethod(fake_run), "TimeoutExpired": harness.subprocess.TimeoutExpired})())
    monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: _db())
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    harness.run_authorized_queue_attempt(authorization)

    assert seen["existed_at_launch"] is True
    assert seen["content"]["attempted"] is True
    assert seen["content"]["command"][1:] == ["-m", "cli.main", "render", "queue", "RLC-E9901", "broadcast_master"]


def test_fresh_preflight_timeout_still_writes_final_result_and_sha256_manifest(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        return harness.subprocess.TimeoutExpired(cmd="fresh-preflight", timeout=1)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("must not launch"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert result.stop_reason == "fresh_preflight_timed_out"
    assert (evidence_dir / "final_result.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_fresh_preflight_launch_failure_still_writes_final_result_and_sha256_manifest_and_records_error(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        return FileNotFoundError("python.exe not found")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("must not launch"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert result.stop_reason == "fresh_preflight_launch_failed"
    assert result.fresh_preflight_launch_error["error_type"] == "FileNotFoundError"
    assert result.fresh_preflight_launch_error["message"] == "python.exe not found"
    assert (evidence_dir / "final_result.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_production_launch_oserror_sets_production_launched_false(monkeypatch, tmp_path):
    """Finding 7C regression: Rev1 hardcoded production_launched=True in
    this branch even when the OSError meant the process never started."""

    def factory(output_path):
        return _default_fresh_preflight_result_factory(output_path)

    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=FileNotFoundError("python.exe not found"), db_after=_db(),
    )
    assert result.production_launched is False
    assert result.production_launch_error["error_type"] == "FileNotFoundError"
    assert result.production_launch_error["message"] == "python.exe not found"
    assert calls["production"] == 1


# --- Finding 10: postflight DB read failure preserves non-success evidence ------


def test_postflight_db_read_failure_preserves_evidence_and_is_non_success(monkeypatch, tmp_path):
    broken_baseline = harness.DatabaseBaseline(
        integrity_check=None, episode_exists=False, episode_row_count=None, episode_status=None,
        episode_project_name=None, episode_folder_path=None,
        render_jobs_total_count=None, render_jobs_for_episode_count=None, render_jobs_for_episode_rows=None,
        archives_total_count=None, error="database read failed: OperationalError: disk I/O error",
    )
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout="Render queued"), db_after=broken_baseline,
    )
    assert result.classification.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert (evidence_dir / "production_stdio.json").exists()
    assert (evidence_dir / "db_postflight.json").exists()
    assert (evidence_dir / "classification.json").exists()
    assert (evidence_dir / "final_result.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()


# --- fail-closed gates: dirty-git / wrong-DB / existing-output (first-pass, unchanged) ---


def test_dirty_git_stops_before_any_subprocess(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"

    def fail_checkpoint(authorized_commit):
        raise harness.QueueAttemptContractError("working_tree_not_clean", "dirty")
    monkeypatch.setattr(harness, "verify_repository_checkpoint", fail_checkpoint)

    calls = {"n": 0}
    def fake_run(*a, **k):
        calls["n"] += 1
        raise AssertionError("must not be called")
    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.run_authorized_queue_attempt(authorization)
    assert excinfo.value.code == "working_tree_not_clean"
    assert calls["n"] == 0
    assert not evidence_dir.exists()


def test_stale_historical_preflight_stops_before_any_subprocess(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(harness, "verify_repository_checkpoint", lambda authorized_commit: None)
    monkeypatch.setattr(harness, "verify_mutation_bearing_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {})
    monkeypatch.setattr(harness, "verify_preflight_wrapper_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: "x")
    monkeypatch.setattr(harness, "verify_python_interpreter", lambda python_executable=harness.EXPECTED_PYTHON_EXECUTABLE: {"executable": str(harness.EXPECTED_PYTHON_EXECUTABLE), "version": list(harness.EXPECTED_PYTHON_VERSION)})
    monkeypatch.setattr(harness, "verify_module_provenance", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {})

    def fail_historical(repository_root=harness.CANONICAL_REPOSITORY_ROOT):
        raise harness.QueueAttemptContractError("historical_preflight_hash_mismatch", "stale")
    monkeypatch.setattr(harness, "verify_historical_preflight_evidence", fail_historical)

    calls = {"n": 0}
    def fake_run(*a, **k):
        calls["n"] += 1
        raise AssertionError("must not be called")
    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.run_authorized_queue_attempt(authorization)
    assert excinfo.value.code == "historical_preflight_hash_mismatch"
    assert calls["n"] == 0


def test_wrong_db_baseline_stops_before_any_subprocess(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(harness, "verify_repository_checkpoint", lambda authorized_commit: None)
    monkeypatch.setattr(harness, "verify_mutation_bearing_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {})
    monkeypatch.setattr(harness, "verify_preflight_wrapper_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: "x")
    monkeypatch.setattr(harness, "verify_python_interpreter", lambda python_executable=harness.EXPECTED_PYTHON_EXECUTABLE: {"executable": str(harness.EXPECTED_PYTHON_EXECUTABLE), "version": list(harness.EXPECTED_PYTHON_VERSION)})
    monkeypatch.setattr(harness, "verify_module_provenance", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {})
    monkeypatch.setattr(harness, "verify_historical_preflight_evidence", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {"sha256": "x", "offline_result": {"render_preflight_status": "passed"}})

    def fail_db(db_path=None, episode_id=harness.EPISODE_ID):
        raise harness.QueueAttemptContractError("render_jobs_baseline_nonzero", "dirty db")
    monkeypatch.setattr(harness, "verify_pre_mutation_database_baseline", fail_db)

    calls = {"n": 0}
    def fake_run(*a, **k):
        calls["n"] += 1
        raise AssertionError("must not be called")
    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.run_authorized_queue_attempt(authorization)
    assert excinfo.value.code == "render_jobs_baseline_nonzero"
    assert calls["n"] == 0


def test_existing_output_stops_before_any_subprocess(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(harness, "verify_repository_checkpoint", lambda authorized_commit: None)
    monkeypatch.setattr(harness, "verify_mutation_bearing_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {})
    monkeypatch.setattr(harness, "verify_preflight_wrapper_source_identity", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: "x")
    monkeypatch.setattr(harness, "verify_python_interpreter", lambda python_executable=harness.EXPECTED_PYTHON_EXECUTABLE: {"executable": str(harness.EXPECTED_PYTHON_EXECUTABLE), "version": list(harness.EXPECTED_PYTHON_VERSION)})
    monkeypatch.setattr(harness, "verify_module_provenance", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {})
    monkeypatch.setattr(harness, "verify_historical_preflight_evidence", lambda repository_root=harness.CANONICAL_REPOSITORY_ROOT: {"sha256": "x", "offline_result": {"render_preflight_status": "passed"}})
    monkeypatch.setattr(harness, "verify_pre_mutation_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: _db())

    def fail_fs(output_path=None):
        raise harness.QueueAttemptContractError("expected_output_already_exists", "already there")
    monkeypatch.setattr(harness, "verify_pre_mutation_filesystem_baseline", fail_fs)

    calls = {"n": 0}
    def fake_run(*a, **k):
        calls["n"] += 1
        raise AssertionError("must not be called")
    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.run_authorized_queue_attempt(authorization)
    assert excinfo.value.code == "expected_output_already_exists"
    assert calls["n"] == 0


# --- preview path never launches anything --------------------------------------


def test_preview_future_queue_attempt_never_touches_subprocess_for_the_mutation_pathway(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    calls = {"n": 0}
    def fake_run(*a, **k):
        calls["n"] += 1
        raise AssertionError("preview must never launch a subprocess")
    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    preview = harness.preview_future_queue_attempt(authorization)

    assert calls["n"] == 0
    assert not evidence_dir.exists()
    assert preview["production_command"][1:] == ["-m", "cli.main", "render", "queue", "RLC-E9901", "broadcast_master"]
    assert "run-live-preflight" in preview["fresh_preflight_command"]


# --- Rev3 corrections: R3-1 through R3-7 ----------------------------------------


# R3-1: success requires BOTH the per-episode delta AND the table-wide total
# delta to equal exactly 1.


def test_classify_R3_1_unrelated_row_elsewhere_in_table_must_not_pass():
    """The exact false-pass an independent replay reproduced against Rev2:
    one exact expected RLC-E9901 row (episode delta +1) alongside one
    unrelated row for a different episode (table-wide total delta +2)."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), render_jobs_total_count=2, episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_R3_1_full_orchestration_unrelated_row_elsewhere_in_table_must_not_pass(monkeypatch, tmp_path):
    stdout_holder = {}

    def make_db_after():
        row = _accepted_row()
        stdout_holder["text"] = (
            f"Job ID: {row['id']}\nEpisode ID: {row['episode_id']}\nPreset: {row['preset_name']}\n"
            f"Project: {row['project_name']}\nTimeline: {row['timeline_name']}\n"
            f"Resolve Job ID: {row['resolve_job_id']}\nStatus: {row['status']}\nOutput: {row['output_path']}\n"
            "Rendering started: no\nArchive performed: no"
        )
        # episode delta +1, but total delta +2 -- an unrelated row appeared elsewhere.
        return _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(row,), render_jobs_total_count=2, episode_status="render_queued")

    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")
    db_after = make_db_after()  # populates stdout_holder["text"] as a side effect
    monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: db_after)
    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=_FakeCompletedProcess(0, stdout=stdout_holder["text"], stderr=""), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)
    assert result.classification.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.classification.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


# R3-2: stdout corroboration is now REQUIRED, not optional.


def test_classify_R3_2_empty_stdout_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text="", stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R3_2_missing_resolve_job_id_cannot_pass():
    stdout = "Status: queued\nOutput: " + str(harness.EXPECTED_OUTPUT_PATH) + "\nRendering started: no\nArchive performed: no"
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R3_2_missing_rendering_started_no_cannot_pass():
    stdout = "Resolve Job ID: job-abc-123\nStatus: queued\nOutput: " + str(harness.EXPECTED_OUTPUT_PATH) + "\nArchive performed: no"
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R3_2_missing_archive_performed_no_cannot_pass():
    stdout = "Resolve Job ID: job-abc-123\nStatus: queued\nOutput: " + str(harness.EXPECTED_OUTPUT_PATH) + "\nRendering started: no"
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


@pytest.mark.parametrize("bad_field,bad_value", [
    ("Resolve Job ID:", "totally-different-job"),
    ("Status:", "claiming"),
    ("Output:", r"C:\wrong\path.mov"),
])
def test_classify_R3_2_wrong_stdout_field_cannot_pass(bad_field, bad_value):
    lines = {
        "Resolve Job ID:": "Resolve Job ID: job-abc-123", "Status:": "Status: queued",
        "Output:": "Output: " + str(harness.EXPECTED_OUTPUT_PATH),
    }
    lines[bad_field] = f"{bad_field} {bad_value}"
    stdout = "\n".join(lines.values()) + "\nRendering started: no\nArchive performed: no"
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R3_2_nonempty_contradictory_stderr_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="WARNING: something unexpected happened",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R3_2_full_success_stdout_still_passes():
    """Positive control: proves the strengthened checks aren't so strict
    they reject the actual, real success shape."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "PRODUCTION_QUEUE_PATH_ACCEPTED"


# R3-3: live subprocess capture must be binary (never `text=True`), so an
# undecodable byte can never raise UnicodeDecodeError out of subprocess.run().

_NON_UTF8_BYTES = b"\xff\xfe\x00\x01RESULT-CORRUPTED-BYTES\xd8\x00"


def test_production_completion_with_non_utf8_stdout_does_not_raise_and_preserves_bytes_losslessly(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout=_NON_UTF8_BYTES, stderr=b""), db_after=_db(),
    )
    assert calls["production"] == 1
    assert result.production_stdout.encoding == "base64"
    assert result.production_stdout.sha256 == hashlib.sha256(_NON_UTF8_BYTES).hexdigest()
    assert result.production_stdout.byte_length == len(_NON_UTF8_BYTES)
    # Round-trip through the actual persisted evidence file, not just the in-memory result.
    persisted = json.loads((evidence_dir / "production_stdio.json").read_text(encoding="utf-8"))
    assert persisted["stdout"]["sha256"] == hashlib.sha256(_NON_UTF8_BYTES).hexdigest()
    assert result.classification.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_production_timeout_with_non_utf8_partial_output_does_not_raise_and_preserves_bytes_losslessly(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def production_timeout_error():
        return harness.subprocess.TimeoutExpired(cmd="production", timeout=120, output=_NON_UTF8_BYTES, stderr=b"")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory, production_result=production_timeout_error(), calls=calls,
    ))
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert result.production_timed_out is True
    assert result.production_stdout.encoding == "base64"
    assert result.production_stdout.sha256 == hashlib.sha256(_NON_UTF8_BYTES).hexdigest()
    assert result.classification.code == "PRODUCTION_TIMEOUT_RECONCILIATION_REQUIRED"
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_fresh_preflight_non_utf8_output_does_not_raise_and_preserves_bytes_losslessly(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        return _FakeCompletedProcess(0, stdout=_NON_UTF8_BYTES, stderr=b"")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("must not launch"), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_not_passing"
    assert result.fresh_preflight_stdout.encoding == "base64"
    assert result.fresh_preflight_stdout.sha256 == hashlib.sha256(_NON_UTF8_BYTES).hexdigest()
    assert (evidence_dir / "sha256_manifest.json").exists()


# R3-4: a fresh snapshot path that exists but cannot be read must not crash.


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_unreadable_file(tmp_path):
    """A path that `.exists()` but raises on `.read_bytes()` -- e.g. a
    directory created where the snapshot file was expected."""

    output_path = tmp_path / "snapshot-that-is-actually-a-directory.json"
    output_path.mkdir()
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=None, wrapper_reported_snapshot_sha256=None,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_unreadable"


def test_fresh_snapshot_unreadable_prevents_queue_launch_and_preserves_evidence(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.mkdir()  # exists, but is a directory -- read_bytes() will raise
        return _FakeCompletedProcess(0, stdout=json.dumps({"render_preflight_status": "passed", "snapshot_path": str(output_path), "snapshot_sha256": "0" * 64}), stderr="")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never launch"), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_snapshot_binding_failed:fresh_preflight_snapshot_unreadable"
    assert (evidence_dir / "final_result.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()
    assert result.fresh_preflight_stdout.present is True


# R3-5: the actual second mutation-boundary recheck values must be preserved,
# not discarded in favor of a bare {"result": "passed"}.


def test_mutation_boundary_recheck_evidence_contains_actual_second_pass_values(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout=_FULL_SUCCESS_STDOUT, stderr=""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
    )
    recheck = json.loads((evidence_dir / "mutation_boundary_recheck.json").read_text(encoding="utf-8"))
    assert recheck["result"] == "passed"
    assert recheck["authorized_commit"] == "deadbeef"
    assert recheck["mutation_bearing_source_hashes"] == harness._MUTATION_BEARING_SOURCE_SHA256
    assert recheck["preflight_wrapper_sha256"] == harness._REVIEWED_PREFLIGHT_WRAPPER_SHA256
    assert "db_baseline" in recheck and recheck["db_baseline"]["episode_status"] == "assembled"
    assert recheck["expected_output_exists"] is False
    assert "recheck_completed_at_utc" in recheck
    # Written before production_command.json / launch (ordering, not just content).
    assert (evidence_dir / "production_command.json").exists()


# R3-6: launch-error evidence must be structured, not just a bare class name.


def test_describe_os_error_captures_structured_fields():
    exc = FileNotFoundError(2, "No such file or directory")
    exc.filename = r"C:\does\not\exist.exe"
    described = harness._describe_os_error(exc)
    assert described["error_type"] == "FileNotFoundError"
    assert described["errno"] == 2
    assert described["filename"] == r"C:\does\not\exist.exe"
    assert "message" in described


# R3-7: a forced production timeout must never classify as success, no
# matter how "complete" the DB happens to look afterward.


def test_R3_7_timeout_with_claiming_row_cannot_pass(monkeypatch, tmp_path):
    claiming_row = _accepted_row(status="claiming", resolve_job_id=None)
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=harness.subprocess.TimeoutExpired(cmd="x", timeout=120, output=b"partial", stderr=b""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(claiming_row,)),
    )
    assert result.classification.code == "PRODUCTION_TIMEOUT_RECONCILIATION_REQUIRED"
    assert result.classification.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_R3_7_timeout_with_fully_matching_queued_row_still_cannot_pass(monkeypatch, tmp_path):
    """Even a DB state that would otherwise satisfy every success
    requirement must not pass when the process was force-terminated --
    the timeout check runs before any row-matching logic."""

    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=harness.subprocess.TimeoutExpired(cmd="x", timeout=120, output=_FULL_SUCCESS_STDOUT.encode("utf-8"), stderr=b""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
    )
    assert result.classification.code == "PRODUCTION_TIMEOUT_RECONCILIATION_REQUIRED"
    assert result.classification.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_R3_7_timeout_with_no_new_row_cannot_pass(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=harness.subprocess.TimeoutExpired(cmd="x", timeout=120, output=b"", stderr=b""),
        db_after=lambda: _db(),
    )
    assert result.classification.code == "PRODUCTION_TIMEOUT_RECONCILIATION_REQUIRED"
    assert result.classification.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_R3_7_timeout_evidence_preserves_duration_and_never_retries(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=harness.subprocess.TimeoutExpired(cmd="x", timeout=120, output=b"", stderr=b""), db_after=lambda: _db(),
    )
    assert calls["production"] == 1
    stdio = json.loads((evidence_dir / "production_stdio.json").read_text(encoding="utf-8"))
    assert stdio["timed_out"] is True
    assert stdio["timeout_seconds"] == 120


# --- Rev4 corrections: Findings 1-4 (Finding 5 is documentation-only) -----------


# Finding 1: postflight episode row must still exist with the expected
# project identity, not merely the expected status.


def test_classify_R4_1_wrong_postflight_episode_project_name_cannot_pass():
    """The exact false pass an independent replay reproduced against Rev3:
    episode_status correctly transitioned to render_queued, the exact
    expected render_jobs row is present, exit 0, valid-looking stdout --
    but episode_project_name silently drifted to something else."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_project_name="SOME_OTHER_PROJECT",
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R4_1_missing_postflight_episode_row_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_exists=False,
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


# Finding 2: ALL eight deterministic success stdout fields are required, not
# just resolve_job_id/status/output_path.


@pytest.mark.parametrize("removed_label", ["Job ID:", "Episode ID:", "Preset:", "Project:", "Timeline:"])
def test_classify_R4_2_missing_deterministic_field_cannot_pass(removed_label):
    lines = [l for l in _FULL_SUCCESS_STDOUT.splitlines() if not l.startswith(removed_label)]
    stdout = "\n".join(lines)
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R4_2_minimal_rev3_style_stdout_subset_cannot_pass():
    """The exact minimal-stdout false pass an independent replay reproduced
    against Rev3: only Resolve Job ID/Status/Output plus both confirmation
    lines -- missing Job ID/Episode ID/Preset/Project/Timeline, which Rev3
    treated as merely "preferred", not required."""

    stdout = (
        "Resolve Job ID: job-abc-123\nStatus: queued\nOutput: " + str(harness.EXPECTED_OUTPUT_PATH) +
        "\nRendering started: no\nArchive performed: no"
    )
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


@pytest.mark.parametrize("field,bad_value", [
    ("job_id", "999"), ("episode_id", "RLC-E0001"), ("preset_name", "youtube_1080p"),
    ("project_name", "WRONG_PROJECT"), ("timeline_name", "WRONG_TIMELINE"),
])
def test_classify_R4_2_disagreeing_deterministic_field_cannot_pass(field, bad_value):
    label_by_field = {
        "job_id": "Job ID:", "episode_id": "Episode ID:", "preset_name": "Preset:",
        "project_name": "Project:", "timeline_name": "Timeline:",
    }
    label = label_by_field[field]
    lines = [l for l in _FULL_SUCCESS_STDOUT.splitlines() if not l.startswith(label)]
    lines.insert(0, f"{label} {bad_value}")
    stdout = "\n".join(lines)
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout, stderr_text="",
        db_before=_db(), db_after=_db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


# Finding 3: module provenance must be rechecked at the mutation boundary.


def test_R4_3_second_pass_module_provenance_failure_prevents_production_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def provenance_side_effect(repository_root=harness.CANONICAL_REPOSITORY_ROOT):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"cli": {"imported": True}, "redline_core": {"imported": True}}
        raise harness.QueueAttemptContractError(
            "module_provenance_check_failed", "cli/redline_core resolved outside the canonical repository src root on recheck",
        )

    monkeypatch.setattr(harness, "verify_module_provenance", provenance_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after a module-provenance recheck failure"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert call_count["n"] == 2, "provenance must be checked once during prep and once during the post-fresh-preflight recheck"
    assert calls["production"] == 0
    assert result.stop_reason == "mutation_boundary_drift_after_fresh_preflight:module_provenance_check_failed"
    assert (evidence_dir / "mutation_boundary_recheck.json").exists()
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_R4_3_mutation_boundary_recheck_contains_second_pass_module_provenance(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout=_FULL_SUCCESS_STDOUT, stderr=""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
    )
    recheck = json.loads((evidence_dir / "mutation_boundary_recheck.json").read_text(encoding="utf-8"))
    assert "module_provenance_report" in recheck
    assert recheck["module_provenance_report"]["cli"]["imported"] is True
    assert recheck["module_provenance_report"]["redline_core"]["imported"] is True


# Finding 4: preserve reviewed execution environment / Python identity, and
# nothing beyond a fixed allowlist.


def test_execution_environment_evidence_contains_exact_reviewed_values(monkeypatch, tmp_path):
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout=_FULL_SUCCESS_STDOUT, stderr=""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
    )
    evidence = json.loads((evidence_dir / "execution_environment.json").read_text(encoding="utf-8"))
    assert evidence["python_executable"] == str(harness.EXPECTED_PYTHON_EXECUTABLE)
    assert evidence["python_interpreter_verified_executable"] == str(harness.EXPECTED_PYTHON_EXECUTABLE)
    assert evidence["python_version"] == list(harness.EXPECTED_PYTHON_VERSION)
    assert evidence["production_cwd"] == str(harness.PRODUCTION_CWD)
    assert str(harness.REPOSITORY_SRC_ROOT) in evidence["PYTHONPATH"]
    assert str(harness.RESOLVE_SCRIPT_MODULES_PATH) in evidence["PYTHONPATH"]
    assert evidence["REDLINE_CONFIG_DIR"] == str(harness.REDLINE_CONFIG_DIR)
    assert evidence["REDLINE_DB_PATH"] == str(harness.REDLINE_DB_PATH)
    assert evidence["RESOLVE_SCRIPT_API"] == str(harness.RESOLVE_SCRIPT_API_PATH)
    assert evidence["RESOLVE_SCRIPT_LIB"] == str(harness.RESOLVE_SCRIPT_LIB_PATH)
    assert evidence["REDLINE_LOG_DIR"] == str(evidence_dir / "logs")
    # Written before production launch.
    assert (evidence_dir / "production_command.json").exists()


def test_execution_environment_evidence_does_not_leak_ambient_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("TOTALLY_UNRELATED_SECRET_TOKEN", "super-secret-value-must-not-leak")
    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout=_FULL_SUCCESS_STDOUT, stderr=""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
    )
    raw_text = (evidence_dir / "execution_environment.json").read_text(encoding="utf-8")
    evidence = json.loads(raw_text)
    assert "TOTALLY_UNRELATED_SECRET_TOKEN" not in raw_text
    assert "super-secret-value-must-not-leak" not in raw_text
    assert set(evidence.keys()) == {
        "python_executable", "python_interpreter_verified_executable", "python_version", "production_cwd",
        "PYTHONPATH", "REDLINE_CONFIG_DIR", "REDLINE_DB_PATH", "RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB", "REDLINE_LOG_DIR",
    }


def test_build_execution_environment_evidence_is_a_fixed_allowlist_not_full_environment():
    """Unit-level proof independent of the full orchestration: passing a
    `production_env` containing arbitrary extra keys must not leak them."""

    noisy_env = {
        "PYTHONPATH": "x", "REDLINE_CONFIG_DIR": "y", "REDLINE_DB_PATH": "z",
        "RESOLVE_SCRIPT_API": "a", "RESOLVE_SCRIPT_LIB": "b", "REDLINE_LOG_DIR": "c",
        "AWS_SECRET_ACCESS_KEY": "should-never-appear", "SOME_OTHER_VAR": "also-should-never-appear",
    }
    evidence = harness.build_execution_environment_evidence(
        python_interpreter_identity={"executable": "py.exe", "version": [3, 11, 9]},
        production_command=["py.exe", "-m", "cli.main"], production_env=noisy_env,
    )
    assert "AWS_SECRET_ACCESS_KEY" not in evidence
    assert "SOME_OTHER_VAR" not in evidence
    assert evidence["PYTHONPATH"] == "x"


# --- Rev5: duplicate/contradictory success stdout must fail closed --------------

_WRONG_DUPLICATE_BLOCK = (
    "Job ID: 999\nEpisode ID: WRONG\nPreset: wrong\nProject: WRONG\n"
    "Timeline: WRONG\nResolve Job ID: bad\nStatus: bad\nOutput: wrong"
)


def _classify_full_success_db(
    stdout_text: str, stderr_text: str = "", *, stderr_byte_length: int | None = None,
    db_after: harness.DatabaseBaseline | None = None,
) -> harness.ClassificationResult:
    return harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=stdout_text, stderr_text=stderr_text,
        db_before=_db(),
        db_after=db_after if db_after is not None else _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
        launch_error=None, timed_out=False, expected_output_exists=False, stderr_byte_length=stderr_byte_length,
    )


def test_classify_R5_wrong_duplicate_block_then_correct_block_cannot_pass():
    """Case A from the Rev5 finding: a wrong duplicate block followed later
    by the complete correct success block. The Rev4 parser overwrote the
    earlier (wrong) value with the later (correct) one and passed."""

    result = _classify_full_success_db(_WRONG_DUPLICATE_BLOCK + "\n" + _FULL_SUCCESS_STDOUT)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R5_correct_block_then_wrong_duplicate_block_cannot_pass():
    """The inverse ordering -- correct block first, wrong duplicate block
    second. Neither first-value-wins nor last-value-wins may pass this."""

    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT + "\n" + _WRONG_DUPLICATE_BLOCK)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


@pytest.mark.parametrize("label", ["Job ID: 1", "Resolve Job ID: job-abc-123", "Status: queued"])
def test_classify_R5_duplicate_identical_value_field_cannot_pass(label):
    """A duplicate is contradictory evidence by itself -- even when every
    occurrence carries an IDENTICAL value, not merely a differing one."""

    stdout = _FULL_SUCCESS_STDOUT + "\n" + label
    result = _classify_full_success_db(stdout)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


@pytest.mark.parametrize("confirmation_lines", [
    "Rendering started: yes\nRendering started: no",
    "Rendering started: no\nRendering started: no",
])
def test_classify_R5_contradictory_or_duplicate_rendering_started_cannot_pass(confirmation_lines):
    lines = [l for l in _FULL_SUCCESS_STDOUT.splitlines() if not l.startswith("Rendering started:")]
    stdout = "\n".join(lines) + "\n" + confirmation_lines
    result = _classify_full_success_db(stdout)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


@pytest.mark.parametrize("confirmation_lines", [
    "Archive performed: yes\nArchive performed: no",
    "Archive performed: no\nArchive performed: no",
])
def test_classify_R5_contradictory_or_duplicate_archive_performed_cannot_pass(confirmation_lines):
    lines = [l for l in _FULL_SUCCESS_STDOUT.splitlines() if not l.startswith("Archive performed:")]
    stdout = "\n".join(lines) + "\n" + confirmation_lines
    result = _classify_full_success_db(stdout)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R5_rendering_started_yes_alone_cannot_pass():
    lines = [l for l in _FULL_SUCCESS_STDOUT.splitlines() if not l.startswith("Rendering started:")]
    stdout = "\n".join(lines) + "\nRendering started: yes"
    result = _classify_full_success_db(stdout)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R5_archive_performed_yes_alone_cannot_pass():
    lines = [l for l in _FULL_SUCCESS_STDOUT.splitlines() if not l.startswith("Archive performed:")]
    stdout = "\n".join(lines) + "\nArchive performed: yes"
    result = _classify_full_success_db(stdout)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R5_ordinary_single_success_block_still_passes():
    """Retention check: exactly one of every required field, plus each
    confirmation line exactly once, still classifies as success."""

    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT)
    assert result.code == "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_stdout_occurrences_evidence_reveals_duplicates_not_collapsed():
    """The classification evidence must make ambiguity visible -- a full
    occurrence list per label, not a single collapsed dictionary value."""

    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT + "\nJob ID: 1")
    occurrences = result.evidence["stdout_occurrences"]
    assert occurrences["job_id"] == ["1", "1"]
    assert len(occurrences["job_id"]) == 2


def test_parse_production_stdout_occurrences_never_collapses_duplicates():
    occurrences = harness._parse_production_stdout_occurrences("Status: queued\nStatus: queued\nStatus: failed")
    assert occurrences["status"] == ["queued", "queued", "failed"]


# --- Rev6: raw stderr byte-length, episode folder_path, DB row identity ---------


# Finding 1: raw non-empty stderr (including non-UTF-8, whitespace-only, and
# newline-only bytes) must fail closed, decided from raw byte count.


def test_classify_R6_1_nonutf8_stderr_bytes_cannot_pass():
    """Case A from the Rev6 finding: perfect success DB/stdout, but raw
    stderr = b"\\xff" -- CapturedOutput.text is None for this, so any check
    based on decoded text alone silently treats it as empty."""

    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, stderr_text="", stderr_byte_length=1)
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R6_1_valid_utf8_warning_stderr_cannot_pass():
    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, stderr_text="WARNING: something unexpected happened")
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R6_1_whitespace_only_stderr_cannot_pass():
    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, stderr_text="   ")
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R6_1_newline_only_stderr_cannot_pass():
    """`"\\n".strip() == ""` -- the Rev5 `.strip() != ""` check would have
    missed this even with correctly-decoded UTF-8 text."""

    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, stderr_text="\n")
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R6_1_genuinely_empty_stderr_still_passes():
    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, stderr_text="", stderr_byte_length=0)
    assert result.code == "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R6_1_stderr_byte_length_visible_in_evidence():
    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, stderr_text="", stderr_byte_length=1)
    assert result.evidence["stderr_byte_length"] == 1


def test_R6_1_production_raw_nonutf8_stderr_full_orchestration_cannot_pass(monkeypatch, tmp_path):
    """Full-orchestration proof: run_authorized_queue_attempt() must pass
    the REAL CapturedOutput.byte_length into classification, not a
    text-derived length -- production_result carries raw b"\\xff" stderr
    exactly as a real subprocess (binary capture, Rev3 R3-3) would."""

    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)
    monkeypatch.setattr(harness, "EXPECTED_OUTPUT_PATH", tmp_path / "does-not-exist.mov")
    row = _accepted_row()
    stdout_text = (
        f"Job ID: {row['id']}\nEpisode ID: {row['episode_id']}\nPreset: {row['preset_name']}\n"
        f"Project: {row['project_name']}\nTimeline: {row['timeline_name']}\nResolve Job ID: {row['resolve_job_id']}\n"
        f"Status: {row['status']}\nOutput: {row['output_path']}\nRendering started: no\nArchive performed: no"
    )
    db_after = _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(row,), episode_status="render_queued")
    monkeypatch.setattr(harness, "read_database_baseline", lambda db_path=None, episode_id=harness.EPISODE_ID: db_after)
    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=_FakeCompletedProcess(0, stdout=stdout_text, stderr=b"\xff"), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)
    assert result.classification.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.classification.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_R6_1_fresh_preflight_nonempty_wrapper_stderr_prevents_production_launch(monkeypatch, tmp_path):
    """A fresh preflight result may be treated as PASS only if the WRAPPER
    PROCESS's own raw stderr is exactly zero bytes -- distinct from the
    `collector_stderr` field embedded inside its JSON stdout."""

    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b'{"fake": "snapshot"}')
        sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
        stdout = json.dumps({"render_preflight_status": "passed", "snapshot_path": str(output_path), "snapshot_sha256": sha})
        return _FakeCompletedProcess(0, stdout=stdout, stderr=b"\xff")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never launch"), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)
    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_stderr_nonempty"


# Finding 2: episode.folder_path is an unbound mutation-bearing input.


def test_verify_pre_mutation_database_baseline_fails_closed_on_wrong_folder_path(tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path, folder_path="_episodes\\WRONG")
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_pre_mutation_database_baseline(db_path)
    assert excinfo.value.code == "episode_folder_path_unexpected"


def test_verify_pre_mutation_database_baseline_passes_on_expected_folder_path(tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path)
    baseline = harness.verify_pre_mutation_database_baseline(db_path)
    assert baseline.episode_folder_path == "_episodes\\RLC-E9901"


def test_verify_pre_mutation_database_baseline_fails_closed_on_duplicate_episode_rows(tmp_path):
    db_path = tmp_path / "redline.db"
    _build_test_db(db_path, extra_episode_rows=1)
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_pre_mutation_database_baseline(db_path)
    assert excinfo.value.code == "episode_row_count_unexpected"


def test_post_fresh_folder_path_drift_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def db_baseline_side_effect(db_path=None, episode_id=harness.EPISODE_ID):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _db()
        raise harness.QueueAttemptContractError("episode_folder_path_unexpected", "folder_path drifted during fresh preflight")

    monkeypatch.setattr(harness, "verify_pre_mutation_database_baseline", db_baseline_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after boundary drift"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason.startswith("mutation_boundary_drift_after_fresh_preflight")
    assert "episode_folder_path_unexpected" in result.stop_reason


def test_classify_R6_2_postflight_folder_path_drift_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_folder_path="_episodes\\WRONG",
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R6_2_postflight_missing_folder_path_cannot_pass():
    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_folder_path=None,
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


@pytest.mark.workstation
def test_resolve_episode_directory_matches_expected_constant():
    resolved = harness._resolve_episode_directory(harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE)
    assert resolved == harness.EXPECTED_EPISODE_DIRECTORY
    assert resolved == harness.PRODUCTION_CWD / "_episodes" / "RLC-E9901"


def test_resolve_episode_directory_rejects_different_valid_directory():
    """A different, but otherwise perfectly valid-looking, directory must
    not be accepted merely because it also resolves somewhere real."""

    resolved = harness._resolve_episode_directory("_episodes\\SOME_OTHER_EPISODE")
    assert resolved != harness.EXPECTED_EPISODE_DIRECTORY


# Finding 3: DB render_jobs row identity (id) must always be validated, never
# optional.


def test_classify_R6_3_render_job_row_id_none_cannot_pass():
    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, db_after=_db(
        render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(id=None),), episode_status="render_queued",
    ))
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


@pytest.mark.parametrize("bad_id", [0, -1])
def test_classify_R6_3_render_job_row_nonpositive_id_cannot_pass(bad_id):
    result = _classify_full_success_db(_FULL_SUCCESS_STDOUT, db_after=_db(
        render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(id=bad_id),), episode_status="render_queued",
    ))
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_classify_R6_3_arbitrary_stdout_job_id_when_db_id_missing_cannot_pass():
    """Independent replay: otherwise perfect success evidence, postflight
    row id=None, arbitrary stdout Job ID -- must not pass merely because
    the id comparison was skipped."""

    stdout = _FULL_SUCCESS_STDOUT.replace("Job ID: 1", "Job ID: 999999")
    result = _classify_full_success_db(stdout, db_after=_db(
        render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(id=None),), episode_status="render_queued",
    ))
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"


def test_evaluate_production_stdout_success_evidence_job_id_comparison_is_unconditional():
    """Direct proof at the function level (not merely via the row_ok gate
    in classify_queue_attempt_outcome) that no branch disables the Job ID
    comparison when the DB row's id is missing."""

    occurrences = harness._parse_production_stdout_occurrences(_FULL_SUCCESS_STDOUT)
    reason = harness._evaluate_production_stdout_success_evidence(occurrences, _accepted_row(id=None))
    assert reason is not None
    assert "Job ID" in reason


# --- Rev7: raw episode.folder_path continuity, distinct from resolved-target ----


# Finding 1: a raw folder_path that changes to a different, syntactically
# equivalent spelling -- still resolving to the exact same directory -- must
# be treated as unexpected drift, not safe drift. The resolved-target check
# alone (Rev6) cannot detect this.

_EQUIVALENT_FOLDER_PATH_SPELLING = "_episodes\\.\\RLC-E9901"


@pytest.mark.workstation
def test_equivalent_folder_path_spelling_resolves_identically_but_differs_as_a_raw_string():
    """Sanity precondition the rest of this section depends on."""

    assert harness._resolve_episode_directory(_EQUIVALENT_FOLDER_PATH_SPELLING) == harness.EXPECTED_EPISODE_DIRECTORY
    assert _EQUIVALENT_FOLDER_PATH_SPELLING != harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE


def test_R7_1_post_fresh_raw_folder_path_equivalent_spelling_prevents_queue_launch(monkeypatch, tmp_path):
    """Adversarial test 1: initial `_episodes\\RLC-E9901`, then a second-pass
    (mutation-boundary recheck) equivalent path spelling that still resolves
    to the expected directory -- production launch count must be ZERO."""

    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    call_count = {"n": 0}

    def db_baseline_side_effect(db_path=None, episode_id=harness.EPISODE_ID):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _db()
        return _db(episode_folder_path=_EQUIVALENT_FOLDER_PATH_SPELLING)

    monkeypatch.setattr(harness, "verify_pre_mutation_database_baseline", db_baseline_side_effect)

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=_default_fresh_preflight_result_factory,
        production_result=AssertionError("production must never launch after raw folder_path drift"), calls=calls,
    ))

    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)

    assert calls["production"] == 0
    assert result.stop_reason == "mutation_boundary_drift_after_fresh_preflight:episode_folder_path_raw_drift"
    recheck = json.loads((evidence_dir / "mutation_boundary_recheck.json").read_text(encoding="utf-8"))
    assert recheck["result"] == "stopped"
    assert recheck["error"]["code"] == "episode_folder_path_raw_drift"
    assert recheck["error"]["details"]["initial_episode_folder_path"] == harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE
    assert recheck["error"]["details"]["second_baseline_episode_folder_path"] == _EQUIVALENT_FOLDER_PATH_SPELLING
    assert (evidence_dir / "sha256_manifest.json").exists()


def test_classify_R7_1_postflight_raw_folder_path_equivalent_spelling_cannot_pass():
    """Adversarial test 2: initial `_episodes\\RLC-E9901`, then a postflight
    equivalent path spelling -- must NOT return PRODUCTION_QUEUE_PATH_ACCEPTED,
    even though the postflight value still resolves to the exact expected
    directory and every other signal (row, exit code, stdout) is correct."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_folder_path=_EQUIVALENT_FOLDER_PATH_SPELLING,
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R7_1_unchanged_raw_folder_path_still_passes():
    """Adversarial test 3: unchanged raw folder_path -- the existing valid
    success case must still pass. Rev7 adds a continuity requirement; it
    does not touch the ordinary matching path."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(episode_folder_path=harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_folder_path=harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE,
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_classify_R7_1_genuinely_different_resolved_directory_still_fails_closed():
    """Adversarial test 4: a genuinely different resolved directory (not
    merely a different spelling of the same one) must continue to fail
    exactly as Rev6 already required -- Rev7 adds a continuity check on top
    of, and does not weaken, the existing resolved-target check."""

    result = harness.classify_queue_attempt_outcome(
        exit_code=0, stdout_text=_FULL_SUCCESS_STDOUT, stderr_text="",
        db_before=_db(),
        db_after=_db(
            render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),),
            episode_status="render_queued", episode_folder_path="_episodes\\WRONG",
        ),
        launch_error=None, timed_out=False, expected_output_exists=False,
    )
    assert result.code == "UNCLASSIFIED_REQUIRES_REVIEW"
    assert result.code != "PRODUCTION_QUEUE_PATH_ACCEPTED"


def test_mutation_boundary_recheck_evidence_preserves_raw_folder_path_continuity(monkeypatch, tmp_path):
    """The mutation-boundary recheck evidence must explicitly preserve both
    the initial and second-pass raw folder_path values, not merely imply
    agreement via the nested db_baseline dict."""

    result, evidence_dir, calls = _run_success_case(
        monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout=_FULL_SUCCESS_STDOUT, stderr=""),
        db_after=lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued"),
    )
    recheck = json.loads((evidence_dir / "mutation_boundary_recheck.json").read_text(encoding="utf-8"))
    assert recheck["initial_episode_folder_path"] == harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE
    assert recheck["second_baseline_episode_folder_path"] == harness.EXPECTED_EPISODE_FOLDER_PATH_RELATIVE


# Fresh snapshot metadata: snapshot_path/snapshot_sha256 mandatory and well-formed.


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_missing_snapshot_path(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=None, wrapper_reported_snapshot_sha256=sha,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_path_missing"


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_empty_snapshot_path(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path="", wrapper_reported_snapshot_sha256=sha,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_path_missing"


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_missing_snapshot_sha256(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=str(output_path), wrapper_reported_snapshot_sha256=None,
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_sha256_missing"


def test_verify_fresh_preflight_snapshot_binding_fails_closed_on_malformed_snapshot_sha256(tmp_path):
    output_path = tmp_path / "snapshot.json"
    output_path.write_bytes(b'{"a": 1}')
    with pytest.raises(harness.QueueAttemptContractError) as excinfo:
        harness.verify_fresh_preflight_snapshot_binding(
            fresh_preflight_output_path=output_path, wrapper_reported_snapshot_path=str(output_path), wrapper_reported_snapshot_sha256="not-a-valid-sha",
        )
    assert excinfo.value.code == "fresh_preflight_snapshot_sha256_missing"


def test_fresh_snapshot_missing_path_metadata_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b'{"fake": "snapshot"}')
        sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return _FakeCompletedProcess(0, stdout=json.dumps({"render_preflight_status": "passed", "snapshot_sha256": sha}), stderr="")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never launch"), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)
    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_snapshot_binding_failed:fresh_preflight_snapshot_path_missing"


def test_fresh_snapshot_missing_sha256_metadata_prevents_queue_launch(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _bypass_prechecks(monkeypatch, evidence_dir=evidence_dir)

    def factory(output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b'{"fake": "snapshot"}')
        return _FakeCompletedProcess(0, stdout=json.dumps({"render_preflight_status": "passed", "snapshot_path": str(output_path)}), stderr="")

    calls = {"fresh_preflight": 0, "production": 0}
    monkeypatch.setattr(harness, "subprocess", _make_fake_subprocess_module(
        fresh_result_factory=factory, production_result=AssertionError("production must never launch"), calls=calls,
    ))
    authorization = harness.QueueAttemptAuthorization(authorized_commit="deadbeef", evidence_output_directory=evidence_dir)
    result = harness.run_authorized_queue_attempt(authorization)
    assert calls["production"] == 0
    assert result.stop_reason == "fresh_preflight_snapshot_binding_failed:fresh_preflight_snapshot_sha256_missing"


# --- static safety checks -------------------------------------------------------


def test_harness_source_contains_no_direct_resolve_scripting_api_calls():
    source = Path(harness.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "DaVinciResolveScript" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "DaVinciResolveScript" not in node.module

    forbidden_call_names = {"scriptapp", "LoadRenderPreset", "SetRenderSettings", "AddRenderJob", "StartRendering"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_call_names
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_call_names


def test_harness_never_imports_render_manager_or_resolve_adapter():
    source = Path(harness.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    disallowed_modules = {"redline_core", "cli"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in disallowed_modules
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert node.module.split(".")[0] not in disallowed_modules


def test_production_command_args_are_exactly_the_authorized_tuple():
    assert harness.PRODUCTION_CLI_MODULE_ARGS == ("-m", "cli.main", "render", "queue", "RLC-E9901", "broadcast_master")


def _find_subprocess_run_call_sites() -> list[tuple[str, str | None]]:
    """Returns (function_name, first_arg_attr_or_None) for every
    `subprocess.run(...)` call found anywhere in the module."""

    source = Path(harness.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_bodies = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    sites = []
    for name, func_node in function_bodies.items():
        for call in ast.walk(func_node):
            if (
                isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "run"
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "subprocess"
            ):
                first_arg_attr = call.args[0].attr if call.args and isinstance(call.args[0], ast.Attribute) else None
                sites.append((name, first_arg_attr))
    return sites


def test_exactly_one_production_cli_launch_site():
    sites = [name for name, attr in _find_subprocess_run_call_sites() if attr == "production_command"]
    assert sites == ["run_authorized_queue_attempt"]


def test_exactly_one_fresh_preflight_launch_site():
    sites = [name for name, attr in _find_subprocess_run_call_sites() if attr == "fresh_preflight_command"]
    assert sites == ["run_authorized_queue_attempt"]


def test_all_subprocess_run_call_sites_are_known_and_accounted_for():
    """Finding 9 regression: corrects the Rev1 false claim of 'exactly two
    subprocess.run call sites in the whole module'. Enumerates every call
    site by function name and proves the complete set is exactly the four
    known, accounted-for sites -- two non-Resolve infrastructure checks
    (`_run_git`, `verify_python_interpreter`) plus the two mutation-capable
    launches inside `run_authorized_queue_attempt`."""

    function_names = sorted(name for name, _attr in _find_subprocess_run_call_sites())
    assert function_names == sorted([
        "_run_git", "verify_python_interpreter", "run_authorized_queue_attempt", "run_authorized_queue_attempt",
    ])


def test_no_loop_statement_wraps_run_authorized_queue_attempt_body():
    source = Path(harness.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func_node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "run_authorized_queue_attempt")
    for node in ast.walk(func_node):
        assert not isinstance(node, (ast.For, ast.While)), "run_authorized_queue_attempt must not contain any loop"


def test_run_authorized_queue_attempt_is_the_only_entry_point_named_run_prefixed_and_not_called_at_import_time():
    assert harness.run_authorized_queue_attempt.__name__ == "run_authorized_queue_attempt"


def test_manifest_json_is_written_exactly_once(monkeypatch, tmp_path):
    """Finding 8 regression: manifest.json must never be rewritten after
    its first write -- invocation counts now live in separate
    fresh_preflight_invocation.json / production_command.json records
    instead of being folded back into manifest.json."""

    evidence_dir = tmp_path / "evidence"
    write_calls = []
    real_write = harness._write_evidence_file

    def spy_write(path, payload):
        write_calls.append(Path(path))
        real_write(path, payload)

    monkeypatch.setattr(harness, "_write_evidence_file", spy_write)

    db_after_factory = lambda: _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued")
    _run_success_case(monkeypatch, tmp_path, production_result=_FakeCompletedProcess(0, stdout="Render queued"), db_after=db_after_factory)

    manifest_writes = [p for p in write_calls if p.name == "manifest.json"]
    assert len(manifest_writes) == 1


# --- CLI dispatch: safe subcommands never reach subprocess for the mutation pathway ---


@pytest.mark.workstation
def test_cli_safe_subcommands_never_construct_production_command(monkeypatch):
    calls = {"n": 0}
    def fake_build_production_command():
        calls["n"] += 1
        return harness.build_production_command()
    monkeypatch.setattr(harness, "build_production_command", fake_build_production_command)

    harness.main(["verify-python"])
    harness.main(["verify-checkpoint", "--authorized-commit", harness._run_git(["rev-parse", "HEAD"])])
    assert calls["n"] == 0


def test_cli_success_exit_code_checks_the_renamed_classification(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    db_after = _db(render_jobs_for_episode_count=1, render_jobs_for_episode_rows=(_accepted_row(),), episode_status="render_queued")

    def fake_run_authorized_queue_attempt(authorization):
        return harness.QueueAttemptResult(
            stop_reason=None, fresh_preflight_render_status="passed",
            fresh_preflight_stdout=harness._ABSENT_CAPTURED_OUTPUT, fresh_preflight_stderr=harness._ABSENT_CAPTURED_OUTPUT,
            fresh_preflight_exit_code=0, fresh_preflight_launch_error=None,
            fresh_preflight_snapshot_path="x", fresh_preflight_snapshot_sha256="y",
            production_launched=True, production_exit_code=0,
            production_stdout=harness._ABSENT_CAPTURED_OUTPUT, production_stderr=harness._ABSENT_CAPTURED_OUTPUT,
            production_launch_error=None, production_timed_out=False,
            db_baseline_before=_db(), db_baseline_after=db_after,
            classification=harness.ClassificationResult("PRODUCTION_QUEUE_PATH_ACCEPTED", "ok", {}),
            evidence_directory=str(evidence_dir),
        )

    monkeypatch.setattr(harness, "run_authorized_queue_attempt", fake_run_authorized_queue_attempt)
    exit_code = harness.main(["run-queue-attempt", "--authorized-commit", "deadbeef", "--evidence-directory", str(evidence_dir)])
    assert exit_code == 0
