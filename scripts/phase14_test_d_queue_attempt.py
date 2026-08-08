"""Phase 14 Test D video-payload isolation queue-attempt harness.

Execution-enablement revision r1, built on the published and immutable
construction r4 experiment core. This revision makes the harness live-capable
only through its existing explicit `--execute` path, gated by an exact
founder-authorization value that is textually bound to the invocation's
expected repository commit, expected harness SHA-256, and expected execution
contract SHA-256. A missing, malformed, or non-exact authorization fails
before any evidence-directory creation, `DaVinciResolveScript` import,
`scriptapp("Resolve")` call, or other Resolve contact.

Test D asks one narrow question: when the exact known-working disposable
Control project/timeline is preserved but its single timeline video item is
removed, does Resolve still accept one Redline Broadcast Master queue request?

The harness deliberately does NOT delete the video item. Test D setup is an
explicitly controlled operator action performed in the Resolve UI after a
separate live authorization. The harness then proves the project/timeline/media
state matches the reviewed Control baseline except for the permitted absence of
the timeline video item before making the single queue mutation.

No code path starts rendering, stops rendering, deletes a render job, accesses
SQLite, loads another project, switches timelines, creates timelines, imports
media, or edits timeline content.

Construction of this revision, and its static/native verification, does not
itself authorize live execution. Live execution requires a separately
published commit, a fresh founder authorization bound to that exact commit and
these exact hashes, and the operator's own manual one-item Control video
removal performed outside this harness.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

MISSION = "phase14-test-d-video-payload-isolation"
CONSTRUCTION_REVISION = "phase14-test-d-video-payload-isolation-execution-enablement-r1"
EXECUTION_ENABLED = True

# Mission 39D.3 previously captured these exact active Resolve identifiers
# immediately before a production-like Broadcast Master AddRenderJob() call.
# Test D r2 requires the same active render context so video-payload absence
# remains the only planned experimental discriminator.
EXPECTED_RENDER_FORMAT = "mov"
EXPECTED_RENDER_CODEC = "DNxHRHQX_10"

# After removal of the reviewed trailing 120-frame video item, only two
# timeline-end outcomes are justified without introducing another unexplained
# state change: Resolve may shrink the end to the retained audio-item end
# (86424), or it may retain the reviewed pre-removal timeline end (86544).
# Any other value is drift and fails closed before queue mutation.
#
# Construction r4 adds temporal stability on top of this accepted-value gate:
# whichever of the two values the first Test D snapshot in a run observes
# becomes that run's bound expected end frame, and every later snapshot must
# keep reporting the exact same value. A change from 86424 to 86544 (or the
# reverse) is itself a second, unauthorized experimental variable even though
# both values individually remain in EXPECTED_TEST_D_END_FRAMES.
EXPECTED_TEST_D_END_FRAMES = frozenset({86424, 86544})

EXPECTED_REPOSITORY_ROOT = Path(r"C:\Users\pj198\Documents\redline-os")
EXPECTED_BRANCH = "master"
EXPECTED_ORIGIN = "git@github.com:Choice283/redline-os.git"
EXPECTED_PYTHON_VERSION = "3.11.9"
EXPECTED_PYTHON_EXE = Path(r"C:\Users\pj198\AppData\Local\Programs\Python\Python311\python.exe")
EXPECTED_RESOLVE_VERSION = "21.0.3.7"
EXPECTED_CONTROL_SETTINGS_SHA256 = "71430f17446c1b4d2019f4ff4d73b6a9ab4154124255c31eecfd7cd3f21d355c"

CONTROL_PROJECT = "redline-os-test-duplicate"
CONTROL_TIMELINE = "RLO-LIVE-ASM-92701_TIMELINE"
PRESET_NAME = "Redline Broadcast Master"
TARGET_DIRECTORY = Path(r"C:\Users\pj198\Documents\redline-os\.artifacts\render-tests")
CUSTOM_NAME = "phase14-test-d-no-video"

EXPECTED_TIMELINE_NAMES = (
    "Redline OS Timeline Test",
    "Redline OS Clip Placement Test",
    "Redline OS Clip Placement Test 2",
    CONTROL_TIMELINE,
)

EXPECTED_CONTROL_AUDIO = {
    "name": "Redline OS Assembly Test Audio.wav",
    "media_pool_unique_id": "b88773bf-c80f-4f23-b346-077f09419e23",
    "start": 86400,
    "end": 86424,
    "duration": 24,
    "enabled": True,
}
EXPECTED_CONTROL_VIDEO = {
    "name": "Redline OS Assembly Test Image.png",
    "media_pool_unique_id": "fdded4d6-0e2d-43f0-9007-2cae51bca76a",
    "start": 86424,
    "end": 86544,
    "duration": 120,
    "enabled": True,
}
EXPECTED_CONTROL_MARKERS = [
    {
        "frame": 0,
        "color": "Blue",
        "name": "Assembly Start",
        "note": "Live V1 marker A",
        "duration": 1,
        "customData": "",
    },
    {
        "frame": 48,
        "color": "Yellow",
        "name": "Assembly Beat",
        "note": "Live V1 marker B",
        "duration": 1,
        "customData": "",
    },
]

# Exact name/unique-ID/folder inventory from the independently reviewed Rev8
# Control snapshot. Removing one TimelineItem in the UI must not alter this
# Media Pool inventory.
EXPECTED_MEDIA_POOL_INVENTORY = (
    ("Master/Redline OS Test", "Redline OS Import Test.png", "fa795548-311b-441a-86ca-3dda4b553dff"),
    ("Master/Redline OS Test", "Redline OS Timeline Test", "9baceaac-e972-4f6c-97d1-2053fcff8f8b"),
    ("Master/Redline OS Test", "Redline OS Clip Placement Test", "1cb8ccd0-eade-429d-b1f3-e9743faa3679"),
    ("Master/Redline OS Test", "Redline OS Clip Placement Test 2", "41b954a5-1770-46d0-87a9-0b8a5de4ab38"),
    ("Master/Redline OS Clip Placement Source", "Redline OS Placement Source Tone.wav", "fbbb5d76-2dbf-4b4f-9a2a-a389c70be9a3"),
    ("Master/Redline OS Clip Placement Source", "Redline OS Placement Source B.png", "3f95c208-68c6-4580-b0e8-3d5c4fa961b1"),
    ("Master/Redline OS Clip Placement Source", "Redline OS Placement Source A.png", "e7081b7b-ad11-4907-82cc-5788b7665674"),
    ("Master/Redline OS Episode Assembly Test", "Redline OS Assembly Test Audio.wav", "b88773bf-c80f-4f23-b346-077f09419e23"),
    ("Master/Redline OS Episode Assembly Test", "Redline OS Assembly Test Image.png", "fdded4d6-0e2d-43f0-9007-2cae51bca76a"),
    ("Master/Redline OS Episode Assembly Test", CONTROL_TIMELINE, "3d85daa9-4a29-493f-879a-4816de41a291"),
)

# Execution-enablement r1 replaces the r1-r4 static authorization phrase with
# a value textually derived from, and therefore bound to, this invocation's
# expected repository commit, expected harness SHA-256, and expected
# execution-contract SHA-256 (see build_required_authorization()). A phrase
# copied from a different commit or a different harness/contract revision
# will not match here and fails closed before any Resolve contact.
AUTHORIZATION_ONE_SHOT_SCOPE = (
    "Exactly one Test D queue attempt is authorized. No retry, Production access, "
    "rendering, cleanup, second submission, or additional mutation is authorized."
)

EXIT_ACCEPTED = 0
EXIT_GATE_FAILURE = 10
EXIT_REJECTED = 16
EXIT_INCONCLUSIVE = 17

QUEUE_JOB_ID_KEYS = ("JobId", "JobID", "jobId", "job_id", "Id", "ID", "id")
FULL_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
FULL_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GateFailure(RuntimeError):
    """Fail-closed precondition or evidence-integrity failure."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class QueueOutcome:
    classification: str
    reason: str
    direct_job_id: str | None
    new_job_ids: tuple[str, ...]


class CommandRunner:
    """Injectable subprocess boundary for repository checks only."""

    def run(self, args: Sequence[str], *, cwd: Path) -> CommandResult:
        proc = subprocess.run(
            list(args),
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        return CommandResult(
            args=tuple(str(arg) for arg in args),
            cwd=str(cwd),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


class EvidencePackage:
    """Write evidence outside the repository with a durable file checkpoint."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=False)

    def write_json(self, name: str, value: Any) -> Path:
        """Atomically persist one UTF-8/LF JSON record and fsync its bytes.

        The file is written to a unique sibling temporary path, flushed and
        fsynced, then atomically replaced into its final name. Directory fsync
        is attempted where the host supports opening directories; Windows may
        reject that final best-effort step, but the file itself is always
        flushed, fsynced, closed, and atomically renamed before this method
        returns. A failure raises and therefore prevents a later queue call.
        """
        final_path = self.root / name
        temporary_path = self.root / f".{name}.{uuid.uuid4().hex}.tmp"
        payload = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
        try:
            with temporary_path.open(
                "x", encoding="utf-8", newline="\n"
            ) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, final_path)
            try:
                directory_fd = os.open(self.root, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
            return final_path
        finally:
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _safe_repr(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


def _normalized_path_text(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _run_git(runner: CommandRunner, repo_root: Path, *args: str) -> str:
    result = runner.run(("git", "--no-optional-locks", *args), cwd=repo_root)
    if result.exit_code != 0:
        raise GateFailure(
            f"git {' '.join(args)} failed with exit code {result.exit_code}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def repository_gate(
    *, runner: CommandRunner, repo_root: Path, expected_commit: str
) -> dict[str, Any]:
    _require(
        FULL_SHA1_RE.fullmatch(expected_commit) is not None,
        "expected repository commit is not full lowercase SHA-1",
    )
    root = _run_git(runner, repo_root, "rev-parse", "--show-toplevel")
    branch = _run_git(runner, repo_root, "branch", "--show-current")
    head = _run_git(runner, repo_root, "rev-parse", "HEAD")
    origin = _run_git(runner, repo_root, "remote", "get-url", "origin")
    status = _run_git(runner, repo_root, "status", "--porcelain=v1")

    _require(
        _normalized_path_text(Path(root)) == _normalized_path_text(EXPECTED_REPOSITORY_ROOT),
        f"repository root mismatch: {root}",
    )
    _require(branch == EXPECTED_BRANCH, f"branch mismatch: {branch}")
    _require(head == expected_commit, f"HEAD mismatch: {head}")
    _require(origin == EXPECTED_ORIGIN, f"origin mismatch: {origin}")
    _require(status == "", "working tree is not clean")
    return {
        "root": root,
        "branch": branch,
        "head": head,
        "origin": origin,
        "clean": True,
    }


def validate_host_python() -> dict[str, str]:
    version = platform.python_version()
    executable = Path(sys.executable)
    _require(version == EXPECTED_PYTHON_VERSION, f"Python version mismatch: {version}")
    _require(
        _normalized_path_text(executable) == _normalized_path_text(EXPECTED_PYTHON_EXE),
        f"Python executable mismatch: {executable}",
    )
    return {"version": version, "executable": str(executable)}


def validate_bound_files(
    *,
    script_path: Path,
    expected_script_sha256: str,
    contract_path: Path,
    expected_contract_sha256: str,
) -> dict[str, str]:
    _require(
        FULL_SHA256_RE.fullmatch(expected_script_sha256) is not None,
        "expected script SHA-256 is invalid",
    )
    _require(
        FULL_SHA256_RE.fullmatch(expected_contract_sha256) is not None,
        "expected contract SHA-256 is invalid",
    )
    _require(script_path.is_file(), f"script path is not a file: {script_path}")
    _require(contract_path.is_file(), f"contract path is not a file: {contract_path}")
    script_hash = sha256_file(script_path)
    contract_hash = sha256_file(contract_path)
    _require(script_hash == expected_script_sha256, "script SHA-256 mismatch")
    _require(contract_hash == expected_contract_sha256, "contract SHA-256 mismatch")
    return {"script_sha256": script_hash, "contract_sha256": contract_hash}


def build_required_authorization(
    *,
    expected_repository_commit: str,
    expected_script_sha256: str,
    expected_contract_sha256: str,
) -> str:
    """Derive the exact one-shot founder authorization value for this invocation.

    The required text textually incorporates the exact expected repository
    commit, expected enabled-harness SHA-256, and expected r4 execution
    contract SHA-256 supplied to this invocation, together with the fixed
    Control project/timeline identity and the fixed one-shot scope clauses.
    Binding those three invocation-supplied values into the required text —
    rather than accepting any authorization phrase regardless of which
    commit/bytes are in play — means an authorization phrase derived for a
    different commit, a different harness revision, or a different contract
    revision does not match here and is rejected before any Resolve contact.

    Callers must supply values already proven well-formed and, for the
    commit, already proven to equal the real repository HEAD (both are
    established earlier in `main()` via `repository_gate()` and
    `validate_bound_files()` before this function is ever called).
    """
    return (
        "I authorize one Phase 14 Test D video-payload isolation queue attempt "
        f"against project {CONTROL_PROJECT} and timeline {CONTROL_TIMELINE}, "
        f"bound to repository commit {expected_repository_commit}, harness "
        f"SHA-256 {expected_script_sha256}, and execution contract SHA-256 "
        f"{expected_contract_sha256}, immediately after exactly one manual "
        "removal of the reviewed Control video timeline item. "
        + AUTHORIZATION_ONE_SHOT_SCOPE
    )


def normalize_markers(raw: object) -> list[dict[str, Any]]:
    if raw is None or raw is False:
        return []
    if not isinstance(raw, dict):
        raise GateFailure(f"GetMarkers returned {type(raw).__name__}, expected dict")
    normalized: list[dict[str, Any]] = []
    for frame, value in raw.items():
        if isinstance(frame, bool) or not isinstance(frame, (int, float)):
            raise GateFailure("marker frame key is not numeric")
        if not isinstance(value, dict):
            raise GateFailure("marker value is not a dict")
        normalized.append(
            {
                "frame": int(frame),
                "color": value.get("color"),
                "name": value.get("name"),
                "note": value.get("note"),
                "duration": value.get("duration"),
                "customData": value.get("customData", ""),
            }
        )
    return sorted(normalized, key=lambda item: item["frame"])


def item_fingerprint(item: object) -> dict[str, Any]:
    for method_name in (
        "GetStart",
        "GetEnd",
        "GetDuration",
        "GetClipEnabled",
        "GetMediaPoolItem",
    ):
        _require(callable(getattr(item, method_name, None)), f"timeline item lacks {method_name}")
    media_pool_item = item.GetMediaPoolItem()
    _require(media_pool_item is not None, "timeline item has no MediaPoolItem")
    _require(callable(getattr(media_pool_item, "GetName", None)), "MediaPoolItem lacks GetName")
    _require(
        callable(getattr(media_pool_item, "GetUniqueId", None)),
        "MediaPoolItem lacks GetUniqueId",
    )
    return {
        "name": media_pool_item.GetName(),
        "media_pool_unique_id": media_pool_item.GetUniqueId(),
        "start": item.GetStart(),
        "end": item.GetEnd(),
        "duration": item.GetDuration(),
        "enabled": item.GetClipEnabled(),
    }


def snapshot_timeline(timeline: object) -> dict[str, Any]:
    for method_name in (
        "GetName",
        "GetSetting",
        "GetMarkers",
        "GetStartFrame",
        "GetEndFrame",
        "GetTrackCount",
        "GetItemListInTrack",
    ):
        _require(callable(getattr(timeline, method_name, None)), f"timeline lacks {method_name}")

    settings = timeline.GetSetting()
    _require(
        isinstance(settings, dict),
        f"GetSetting returned {type(settings).__name__}, expected dict",
    )
    tracks: dict[str, Any] = {}
    for track_type in ("audio", "video", "subtitle"):
        count = timeline.GetTrackCount(track_type)
        _require(
            isinstance(count, int) and not isinstance(count, bool) and count >= 0,
            f"invalid {track_type} track count",
        )
        track_items: list[list[dict[str, Any]]] = []
        for index in range(1, count + 1):
            raw_items = timeline.GetItemListInTrack(track_type, index)
            if raw_items is None or raw_items is False:
                raw_items = []
            _require(
                isinstance(raw_items, list),
                f"{track_type} track {index} item list is not a list",
            )
            track_items.append([item_fingerprint(item) for item in raw_items])
        tracks[track_type] = {"count": count, "tracks": track_items}

    return {
        "name": timeline.GetName(),
        "start_frame": timeline.GetStartFrame(),
        "end_frame": timeline.GetEndFrame(),
        "settings": settings,
        "settings_sha256": _canonical_sha256(settings),
        "markers": normalize_markers(timeline.GetMarkers()),
        "tracks": tracks,
    }


def _flatten_items(snapshot: Mapping[str, Any], track_type: str) -> list[dict[str, Any]]:
    return [
        item
        for track in snapshot["tracks"][track_type]["tracks"]
        for item in track
    ]


def expected_control_baseline_reference() -> dict[str, Any]:
    """Immutable reference facts from the reviewed Rev8 Control evidence."""
    return {
        "project": CONTROL_PROJECT,
        "timeline": CONTROL_TIMELINE,
        "settings_sha256": EXPECTED_CONTROL_SETTINGS_SHA256,
        "start_frame": 86400,
        "end_frame_before_test_d": 86544,
        "track_counts": {"audio": 1, "video": 1, "subtitle": 1},
        "audio_items": [dict(EXPECTED_CONTROL_AUDIO)],
        "video_items_before_test_d": [dict(EXPECTED_CONTROL_VIDEO)],
        "subtitle_items": [],
        "markers": list(EXPECTED_CONTROL_MARKERS),
        "timeline_names": list(EXPECTED_TIMELINE_NAMES),
        "media_pool_inventory": [list(item) for item in EXPECTED_MEDIA_POOL_INVENTORY],
    }


def validate_test_d_snapshot(
    snapshot: Mapping[str, Any], *, expected_end_frame: int | None = None
) -> None:
    """Prove the exact Control timeline differs only by video-item absence.

    The end frame may either shrink to the retained audio end (86424) or
    remain at the reviewed pre-removal end (86544). Any other value is
    unexplained drift and invalidates the one-variable experiment.

    When `expected_end_frame` is given, the observed end frame must
    additionally equal that run-bound value. The first successfully
    validated Test D snapshot in a run binds the accepted end frame for the
    rest of that run; a later snapshot reporting the *other* otherwise-valid
    value is temporal drift, not a stable one-variable experiment, and fails
    closed the same as an unrecognized value.
    """
    _require(snapshot.get("name") == CONTROL_TIMELINE, "Control timeline name mismatch")
    _require(snapshot.get("start_frame") == 86400, "Control timeline start frame drifted")
    end_frame = snapshot.get("end_frame")
    _require(
        isinstance(end_frame, int) and not isinstance(end_frame, bool),
        f"Control timeline end frame is invalid: {end_frame!r}",
    )
    _require(
        end_frame in EXPECTED_TEST_D_END_FRAMES,
        f"Control timeline end frame drifted unexpectedly: {end_frame!r}",
    )
    if expected_end_frame is not None:
        _require(
            end_frame == expected_end_frame,
            "Control timeline end frame "
            f"{end_frame!r} no longer matches the run-bound value "
            f"{expected_end_frame!r} established by the first Test D snapshot",
        )
    _require(
        snapshot.get("settings_sha256") == EXPECTED_CONTROL_SETTINGS_SHA256,
        "Control timeline settings drifted from reviewed baseline",
    )
    _require(snapshot.get("markers") == EXPECTED_CONTROL_MARKERS, "Control markers drifted")
    _require(snapshot["tracks"]["audio"]["count"] == 1, "Control must have one audio track")
    _require(snapshot["tracks"]["video"]["count"] == 1, "Control must have one video track")
    _require(
        snapshot["tracks"]["subtitle"]["count"] == 1,
        "Control must have one subtitle track",
    )
    _require(
        _flatten_items(snapshot, "audio") == [EXPECTED_CONTROL_AUDIO],
        "Control audio payload drifted",
    )
    _require(
        _flatten_items(snapshot, "video") == [],
        "Test D requires zero video timeline items",
    )
    _require(
        _flatten_items(snapshot, "subtitle") == [],
        "Control subtitle track must remain empty",
    )


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
            text = str(value).strip()
            if text:
                return text
    return None


def normalize_queue(raw: object) -> list[dict[str, Any]]:
    if raw is None or raw is False:
        return []
    _require(
        isinstance(raw, list),
        f"GetRenderJobList returned {type(raw).__name__}, expected list",
    )
    return raw


def queue_inventory(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    fingerprint: list[dict[str, Any]] = []
    ids: list[str] = []
    for job in jobs:
        job_id = render_job_id_from_mapping(job)
        if job_id is not None:
            ids.append(job_id)
        fingerprint.append(
            {
                "type": type(job).__name__,
                "keys": sorted(str(key) for key in job.keys())
                if isinstance(job, dict)
                else None,
                "has_usable_job_id": job_id is not None,
            }
        )
    return {
        "count": len(jobs),
        "usable_job_ids": ids,
        "unidentified_items": sum(
            1 for item in fingerprint if not item["has_usable_job_id"]
        ),
        "fingerprint": fingerprint,
    }


def coerce_direct_job_id(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return text or None
    return render_job_id_from_mapping(value)


def classify_queue_outcome(
    add_result: object,
    before_jobs: list[dict[str, Any]],
    after_jobs: list[dict[str, Any]],
) -> QueueOutcome:
    direct_job_id = coerce_direct_job_id(add_result)
    if before_jobs:
        return QueueOutcome(
            "inconclusive",
            "precondition violation: queue was not empty",
            direct_job_id,
            (),
        )

    after_ids = [
        job_id
        for job_id in (render_job_id_from_mapping(job) for job in after_jobs)
        if job_id
    ]
    unidentified_after = [
        job for job in after_jobs if render_job_id_from_mapping(job) is None
    ]
    if unidentified_after:
        return QueueOutcome(
            "inconclusive",
            "after-queue contains an unidentifiable item",
            direct_job_id,
            (),
        )

    new_job_ids = tuple(after_ids)
    if len(after_jobs) == 1 and len(new_job_ids) == 1:
        if direct_job_id is not None and direct_job_id != new_job_ids[0]:
            return QueueOutcome(
                "inconclusive",
                "direct AddRenderJob ID conflicts with the single observed queue job ID",
                direct_job_id,
                new_job_ids,
            )
        return QueueOutcome(
            "accepted",
            "exactly one identifiable render job is present after the single AddRenderJob call",
            direct_job_id,
            new_job_ids,
        )

    if not after_jobs and (
        (isinstance(add_result, str) and add_result == "") or add_result is False
    ):
        return QueueOutcome(
            "rejected",
            "AddRenderJob returned an explicit empty/false result and the queue remained empty",
            direct_job_id,
            (),
        )

    if not after_jobs and direct_job_id is not None:
        return QueueOutcome(
            "inconclusive",
            "AddRenderJob returned an ID but no queue acceptance was observed",
            direct_job_id,
            (),
        )

    return QueueOutcome(
        "inconclusive",
        "queue state did not satisfy the exact accepted or rejected predicate",
        direct_job_id,
        new_job_ids,
    )


def _timeline_inventory(project: object) -> list[str]:
    _require(callable(getattr(project, "GetTimelineCount", None)), "project lacks GetTimelineCount")
    _require(callable(getattr(project, "GetTimelineByIndex", None)), "project lacks GetTimelineByIndex")
    count = project.GetTimelineCount()
    _require(
        isinstance(count, int) and not isinstance(count, bool) and count >= 0,
        "invalid timeline count",
    )
    names: list[str] = []
    for index in range(1, count + 1):
        timeline = project.GetTimelineByIndex(index)
        _require(timeline is not None, f"timeline {index} is unavailable")
        _require(callable(getattr(timeline, "GetName", None)), f"timeline {index} lacks GetName")
        name = timeline.GetName()
        _require(isinstance(name, str) and name.strip(), f"timeline {index} name is invalid")
        names.append(name)
    return names


def validate_timeline_inventory(project: object) -> list[str]:
    names = _timeline_inventory(project)
    _require(
        tuple(names) == EXPECTED_TIMELINE_NAMES,
        f"timeline inventory drifted: {names!r}",
    )
    return names


def find_timeline(project: object, timeline_name: str) -> object:
    count = project.GetTimelineCount()
    matches: list[object] = []
    for index in range(1, count + 1):
        timeline = project.GetTimelineByIndex(index)
        _require(timeline is not None, f"timeline {index} is unavailable")
        if timeline.GetName() == timeline_name:
            matches.append(timeline)
    _require(
        len(matches) == 1,
        f"expected exactly one timeline named {timeline_name!r}, found {len(matches)}",
    )
    return matches[0]


def _walk_media_pool_folder(
    folder: object,
    path: tuple[str, ...],
    visited: set[int],
    out: list[tuple[str, str, str]],
) -> None:
    identity = id(folder)
    _require(identity not in visited, f"cyclic/repeated Media Pool folder at {'/'.join(path)}")
    visited.add(identity)

    _require(callable(getattr(folder, "GetClipList", None)), "Media Pool folder lacks GetClipList")
    _require(
        callable(getattr(folder, "GetSubFolderList", None)),
        "Media Pool folder lacks GetSubFolderList",
    )
    clips = folder.GetClipList()
    if clips is None or clips is False:
        clips = []
    _require(isinstance(clips, list), "Media Pool GetClipList did not return a list")
    for clip in clips:
        _require(callable(getattr(clip, "GetName", None)), "Media Pool item lacks GetName")
        _require(callable(getattr(clip, "GetUniqueId", None)), "Media Pool item lacks GetUniqueId")
        name = clip.GetName()
        unique_id = clip.GetUniqueId()
        _require(isinstance(name, str) and name.strip(), "Media Pool item name is invalid")
        _require(
            isinstance(unique_id, str) and unique_id.strip(),
            "Media Pool item unique ID is invalid",
        )
        out.append(("/".join(path), name, unique_id))

    subfolders = folder.GetSubFolderList()
    if subfolders is None or subfolders is False:
        subfolders = []
    _require(
        isinstance(subfolders, list),
        "Media Pool GetSubFolderList did not return a list",
    )
    for child in subfolders:
        _require(callable(getattr(child, "GetName", None)), "Media Pool subfolder lacks GetName")
        child_name = child.GetName()
        _require(
            isinstance(child_name, str) and child_name.strip(),
            "Media Pool subfolder name is invalid",
        )
        _walk_media_pool_folder(child, path + (child_name,), visited, out)


def media_pool_inventory(project: object) -> list[tuple[str, str, str]]:
    _require(callable(getattr(project, "GetMediaPool", None)), "project lacks GetMediaPool")
    media_pool = project.GetMediaPool()
    _require(media_pool is not None, "project Media Pool is unavailable")
    _require(callable(getattr(media_pool, "GetRootFolder", None)), "Media Pool lacks GetRootFolder")
    root = media_pool.GetRootFolder()
    _require(root is not None, "Media Pool root folder is unavailable")
    _require(callable(getattr(root, "GetName", None)), "Media Pool root folder lacks GetName")
    root_name = root.GetName()
    _require(isinstance(root_name, str) and root_name.strip(), "Media Pool root folder name is invalid")
    result: list[tuple[str, str, str]] = []
    _walk_media_pool_folder(root, (root_name,), set(), result)
    return result


def validate_media_pool_inventory(project: object) -> list[tuple[str, str, str]]:
    inventory = media_pool_inventory(project)
    _require(
        sorted(inventory) == sorted(EXPECTED_MEDIA_POOL_INVENTORY),
        "Media Pool inventory drifted from reviewed Control baseline",
    )
    return inventory


def current_identity(resolve: object) -> tuple[object, object, object]:
    _require(callable(getattr(resolve, "GetProjectManager", None)), "Resolve lacks GetProjectManager")
    manager = resolve.GetProjectManager()
    _require(manager is not None, "Resolve project manager is unavailable")
    _require(
        callable(getattr(manager, "GetCurrentProject", None)),
        "project manager lacks GetCurrentProject",
    )
    project = manager.GetCurrentProject()
    _require(project is not None, "no current Resolve project")
    _require(callable(getattr(project, "GetName", None)), "current project lacks GetName")
    _require(
        project.GetName() == CONTROL_PROJECT,
        f"current project is not {CONTROL_PROJECT!r}",
    )
    _require(
        callable(getattr(project, "GetCurrentTimeline", None)),
        "project lacks GetCurrentTimeline",
    )
    timeline = project.GetCurrentTimeline()
    _require(timeline is not None, "no current Resolve timeline")
    _require(callable(getattr(timeline, "GetName", None)), "current timeline lacks GetName")
    _require(
        timeline.GetName() == CONTROL_TIMELINE,
        f"current timeline is not {CONTROL_TIMELINE!r}",
    )
    return manager, project, timeline


def validate_resolve_identity(resolve: object) -> dict[str, str]:
    product_getter = getattr(resolve, "GetProductName", None)
    _require(callable(product_getter), "Resolve cannot report product name")
    product_name = product_getter()
    _require(product_name == "DaVinci Resolve Studio", f"Resolve product mismatch: {product_name!r}")

    value: object = None
    getter = getattr(resolve, "GetVersionString", None)
    if callable(getter):
        value = getter()
    if not isinstance(value, str) or not value.strip():
        getter = getattr(resolve, "GetVersion", None)
        _require(callable(getter), "Resolve cannot report version")
        raw = getter()
        if isinstance(raw, (list, tuple)):
            value = ".".join(str(part) for part in raw if str(part) != "")
        else:
            value = str(raw)
    version = str(value).strip()
    _require(version == EXPECTED_RESOLVE_VERSION, f"Resolve version mismatch: {version}")
    return {"product_name": product_name, "version": version}


def validate_project_settings(project: object) -> dict[str, Any]:
    _require(callable(getattr(project, "GetSetting", None)), "project lacks GetSetting")
    settings = project.GetSetting()
    _require(
        isinstance(settings, dict),
        f"project GetSetting returned {type(settings).__name__}, expected dict",
    )
    digest = _canonical_sha256(settings)
    _require(
        digest == EXPECTED_CONTROL_SETTINGS_SHA256,
        "project settings drifted from reviewed Control baseline",
    )
    return {"settings_sha256": digest, "field_count": len(settings)}


def validate_queue_and_render_state(
    project: object,
) -> tuple[list[dict[str, Any]], bool]:
    _require(
        callable(getattr(project, "GetRenderJobList", None)),
        "project lacks GetRenderJobList",
    )
    _require(
        callable(getattr(project, "IsRenderingInProgress", None)),
        "project lacks IsRenderingInProgress",
    )
    jobs = normalize_queue(project.GetRenderJobList())
    rendering = project.IsRenderingInProgress()
    _require(
        rendering is False,
        f"IsRenderingInProgress must be literally False, got {rendering!r}",
    )
    return jobs, False


def validate_preset(project: object) -> None:
    _require(
        callable(getattr(project, "GetRenderPresetList", None)),
        "project lacks GetRenderPresetList",
    )
    presets = project.GetRenderPresetList()
    _require(
        isinstance(presets, list),
        f"GetRenderPresetList returned {type(presets).__name__}, expected list",
    )
    _require(
        presets.count(PRESET_NAME) == 1,
        f"preset {PRESET_NAME!r} must exist exactly once",
    )


def validate_target_directory() -> dict[str, Any]:
    _require(
        TARGET_DIRECTORY.exists(),
        f"target directory does not exist: {TARGET_DIRECTORY}",
    )
    _require(
        TARGET_DIRECTORY.is_dir(),
        f"target path is not a directory: {TARGET_DIRECTORY}",
    )
    collisions = sorted(
        str(path)
        for path in TARGET_DIRECTORY.glob(f"{CUSTOM_NAME}.*")
        if path.is_file()
    )
    _require(not collisions, f"target output stem collision exists: {collisions}")
    return {"path": str(TARGET_DIRECTORY), "collisions": []}


def validate_render_context(project: object) -> dict[str, str]:
    """Require the exact reviewed Broadcast Master format/codec identifiers."""
    getter = getattr(project, "GetCurrentRenderFormatAndCodec", None)
    _require(callable(getter), "project lacks GetCurrentRenderFormatAndCodec")
    raw_context = getter()
    _require(
        isinstance(raw_context, dict),
        "GetCurrentRenderFormatAndCodec did not return a dict",
    )
    render_format = raw_context.get("format")
    render_codec = raw_context.get("codec")
    _require(
        render_format == EXPECTED_RENDER_FORMAT,
        f"Broadcast Master render format mismatch: {render_format!r}",
    )
    _require(
        render_codec == EXPECTED_RENDER_CODEC,
        f"Broadcast Master render codec mismatch: {render_codec!r}",
    )
    return {"format": render_format, "codec": render_codec}


def connect_live_resolve() -> object:
    """Only live Resolve import/connection boundary.

    Reachable only via `--execute` with the exact founder authorization
    derived by `build_required_authorization()` for this invocation's
    commit/harness/contract triple; see `main()`.
    """
    try:
        import DaVinciResolveScript as dvr_script  # type: ignore
    except ImportError as exc:
        raise GateFailure("Could not import DaVinciResolveScript") from exc
    resolve = dvr_script.scriptapp("Resolve")
    _require(
        resolve is not None,
        "DaVinciResolveScript.scriptapp('Resolve') returned None",
    )
    return resolve


def _pre_add_snapshot(
    resolve: object, *, expected_end_frame: int | None = None
) -> dict[str, Any]:
    _, project, current_timeline = current_identity(resolve)
    resolve_identity = validate_resolve_identity(resolve)
    project_settings = validate_project_settings(project)
    timeline_names = validate_timeline_inventory(project)
    media_inventory = validate_media_pool_inventory(project)
    timeline = find_timeline(project, CONTROL_TIMELINE)
    _require(
        timeline is current_timeline or timeline.GetName() == current_timeline.GetName(),
        "current timeline identity drift",
    )
    timeline_snapshot = snapshot_timeline(timeline)
    validate_test_d_snapshot(timeline_snapshot, expected_end_frame=expected_end_frame)
    jobs, _ = validate_queue_and_render_state(project)
    _require(jobs == [], "render queue must be empty before Test D")
    return {
        "resolve_identity": resolve_identity,
        "project_settings": project_settings,
        "timeline_names": timeline_names,
        "media_pool_inventory": [list(item) for item in media_inventory],
        "timeline": timeline_snapshot,
        "queue": queue_inventory(jobs),
        "rendering_in_progress": False,
    }


def execute_test_d(resolve: object, evidence: EvidencePackage) -> dict[str, Any]:
    """Run the single Test D queue attempt with durable one-shot evidence."""
    _, project, _ = current_identity(resolve)
    baseline_reference = expected_control_baseline_reference()

    initial = _pre_add_snapshot(resolve)
    initial_end_frame = initial["timeline"]["end_frame"]
    validate_preset(project)
    target_dir = validate_target_directory()

    # Full repeat immediately before any render-context mutation. The end
    # frame bound by the very first Test D snapshot above must still hold;
    # a drift to the other otherwise-valid value fails closed here.
    pre_render_context = _pre_add_snapshot(resolve, expected_end_frame=initial_end_frame)

    _require(
        callable(getattr(project, "LoadRenderPreset", None)),
        "project lacks LoadRenderPreset",
    )
    _require(
        callable(getattr(project, "SetRenderSettings", None)),
        "project lacks SetRenderSettings",
    )
    _require(callable(getattr(project, "AddRenderJob", None)), "project lacks AddRenderJob")

    preset_loaded = project.LoadRenderPreset(PRESET_NAME)
    _require(preset_loaded is True, f"LoadRenderPreset returned {preset_loaded!r}")
    render_settings = {
        "TargetDir": str(TARGET_DIRECTORY),
        "CustomName": CUSTOM_NAME,
    }
    settings_applied = project.SetRenderSettings(render_settings)
    _require(
        settings_applied is True,
        f"SetRenderSettings returned {settings_applied!r}",
    )

    # r2 isolation gate: the accessor is mandatory and both identifiers must
    # match the exact reviewed Broadcast Master context before queue mutation.
    render_context = validate_render_context(project)

    # Final fail-closed gate immediately before the ONE queue mutation. Still
    # bound to the end frame the first Test D snapshot established.
    final_guard = _pre_add_snapshot(resolve, expected_end_frame=initial_end_frame)
    final_jobs: list[dict[str, Any]] = []

    pre_add_checkpoint = {
        "mission": MISSION,
        "construction_revision": CONSTRUCTION_REVISION,
        "checkpoint": "pre_add",
        "captured_at": utc_now(),
        "queue_mutation_started": False,
        "baseline_reference": baseline_reference,
        "project": CONTROL_PROJECT,
        "timeline": CONTROL_TIMELINE,
        "initial_end_frame": initial_end_frame,
        "initial_test_d_state": initial,
        "pre_render_context_state": pre_render_context,
        "final_pre_add_guard": final_guard,
        "target_directory": target_dir,
        "preset": PRESET_NAME,
        "render_settings": render_settings,
        "render_context": render_context,
        "before_queue": queue_inventory(final_jobs),
    }
    pre_add_path = evidence.write_json("pre_add_evidence.json", pre_add_checkpoint)
    pre_add_sha256 = sha256_file(pre_add_path)

    mutation_started_at = utc_now()
    add_result = project.AddRenderJob()  # THE ONLY AddRenderJob CALL IN THIS FILE.
    mutation_finished_at = utc_now()
    add_result_record = {
        "mission": MISSION,
        "construction_revision": CONSTRUCTION_REVISION,
        "mutation_started_at": mutation_started_at,
        "mutation_finished_at": mutation_finished_at,
        "add_result_type": type(add_result).__name__,
        "add_result_repr": _safe_repr(add_result),
        "pre_add_evidence_sha256": pre_add_sha256,
    }
    evidence_errors: list[dict[str, str]] = []
    add_result_sha256: str | None = None
    try:
        add_result_path = evidence.write_json("add_render_job_result.json", add_result_record)
        add_result_sha256 = sha256_file(add_result_path)
    except Exception as exc:
        # Post-mutation evidence persistence must never suppress the read-only
        # queue/render/project observations needed to understand what happened.
        # Record the failure in-memory, continue observation, and force the
        # final classification to inconclusive. No retry is authorized.
        evidence_errors.append(
            {
                "phase": "add_render_job_result_write",
                "type": type(exc).__name__,
                "repr": _safe_repr(exc),
            }
        )

    post_errors: list[dict[str, str]] = []
    after_jobs: list[dict[str, Any]] | None = None
    rendering_after: object = "unavailable"
    post_identity: object = "unavailable"
    post_timeline_snapshot: object = "unavailable"
    post_media_inventory: object = "unavailable"

    try:
        after_jobs = normalize_queue(project.GetRenderJobList())
    except Exception as exc:
        post_errors.append(
            {"phase": "after_queue", "type": type(exc).__name__, "repr": _safe_repr(exc)}
        )

    try:
        rendering_after = project.IsRenderingInProgress()
    except Exception as exc:
        post_errors.append(
            {
                "phase": "rendering_after",
                "type": type(exc).__name__,
                "repr": _safe_repr(exc),
            }
        )

    try:
        _, project_after, timeline_after = current_identity(resolve)
        post_identity = {
            "same_project_handle": project_after is project,
            "project_name": project_after.GetName(),
            "timeline_name": timeline_after.GetName(),
        }
    except Exception as exc:
        post_errors.append(
            {"phase": "post_identity", "type": type(exc).__name__, "repr": _safe_repr(exc)}
        )

    try:
        post_timeline_snapshot = snapshot_timeline(find_timeline(project, CONTROL_TIMELINE))
        # Observational only: a post-call end-frame drift from the run-bound
        # value is recorded as a post_error (which forces `inconclusive`
        # below) rather than repaired, retried, or otherwise mutated.
        validate_test_d_snapshot(post_timeline_snapshot, expected_end_frame=initial_end_frame)
    except Exception as exc:
        post_errors.append(
            {"phase": "post_timeline", "type": type(exc).__name__, "repr": _safe_repr(exc)}
        )

    try:
        post_media_inventory = [list(item) for item in validate_media_pool_inventory(project)]
        validate_timeline_inventory(project)
        validate_project_settings(project)
    except Exception as exc:
        post_errors.append(
            {"phase": "post_project_state", "type": type(exc).__name__, "repr": _safe_repr(exc)}
        )

    if after_jobs is None:
        outcome = QueueOutcome(
            "inconclusive",
            "after-queue snapshot unavailable",
            coerce_direct_job_id(add_result),
            (),
        )
    else:
        outcome = classify_queue_outcome(add_result, final_jobs, after_jobs)

    if rendering_after is not False:
        outcome = QueueOutcome(
            "inconclusive",
            f"rendering state became {rendering_after!r}; no StopRendering action is authorized",
            outcome.direct_job_id,
            outcome.new_job_ids,
        )
    if post_errors:
        outcome = QueueOutcome(
            "inconclusive",
            f"post-call observation had {len(post_errors)} error(s)",
            outcome.direct_job_id,
            outcome.new_job_ids,
        )
    if evidence_errors:
        outcome = QueueOutcome(
            "inconclusive",
            f"post-call evidence persistence had {len(evidence_errors)} error(s)",
            outcome.direct_job_id,
            outcome.new_job_ids,
        )

    post_add_checkpoint = {
        "mission": MISSION,
        "construction_revision": CONSTRUCTION_REVISION,
        "checkpoint": "post_add",
        "captured_at": utc_now(),
        "pre_add_evidence_sha256": pre_add_sha256,
        "add_render_job_result_sha256": add_result_sha256,
        "add_render_job_result": add_result_record,
        "evidence_errors": evidence_errors,
        "before_queue": queue_inventory(final_jobs),
        "after_queue": queue_inventory(after_jobs)
        if after_jobs is not None
        else {"available": False},
        "rendering_after": rendering_after,
        "post_identity": post_identity,
        "post_timeline_snapshot": post_timeline_snapshot,
        "post_media_pool_inventory": post_media_inventory,
        "post_errors": post_errors,
        "outcome": asdict(outcome),
    }
    post_add_sha256: str | None = None
    try:
        post_add_path = evidence.write_json("post_add_evidence.json", post_add_checkpoint)
        post_add_sha256 = sha256_file(post_add_path)
    except Exception as exc:
        evidence_errors.append(
            {
                "phase": "post_add_evidence_write",
                "type": type(exc).__name__,
                "repr": _safe_repr(exc),
            }
        )
        outcome = QueueOutcome(
            "inconclusive",
            f"post-call evidence persistence had {len(evidence_errors)} error(s)",
            outcome.direct_job_id,
            outcome.new_job_ids,
        )

    return {
        "mission": MISSION,
        "construction_revision": CONSTRUCTION_REVISION,
        "baseline_reference": baseline_reference,
        "project": CONTROL_PROJECT,
        "timeline": CONTROL_TIMELINE,
        "initial_end_frame": initial_end_frame,
        "initial_test_d_state": initial,
        "pre_render_context_state": pre_render_context,
        "final_pre_add_guard": final_guard,
        "target_directory": target_dir,
        "preset": PRESET_NAME,
        "render_settings": render_settings,
        "render_context": render_context,
        "pre_add_evidence_sha256": pre_add_sha256,
        "add_render_job_result_sha256": add_result_sha256,
        "post_add_evidence_sha256": post_add_sha256,
        "mutation_started_at": mutation_started_at,
        "mutation_finished_at": mutation_finished_at,
        "add_result_type": type(add_result).__name__,
        "add_result_repr": _safe_repr(add_result),
        "before_queue": queue_inventory(final_jobs),
        "after_queue": queue_inventory(after_jobs)
        if after_jobs is not None
        else {"available": False},
        "rendering_after": rendering_after,
        "post_identity": post_identity,
        "post_timeline_snapshot": post_timeline_snapshot,
        "post_media_pool_inventory": post_media_inventory,
        "post_errors": post_errors,
        "evidence_errors": evidence_errors,
        "outcome": asdict(outcome),
    }


def default_evidence_root() -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        Path.home()
        / "Documents"
        / f"phase14-test-d-evidence-{stamp}-{uuid.uuid4().hex}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="request the one live Test D attempt",
    )
    parser.add_argument("--expected-script-sha256", required=True)
    parser.add_argument("--contract-path", required=True, type=Path)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--expected-repository-commit", required=True)
    parser.add_argument("--authorization", default="")
    parser.add_argument("--evidence-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_path = Path(__file__).resolve()
    repo_root = EXPECTED_REPOSITORY_ROOT
    runner = CommandRunner()
    evidence: EvidencePackage | None = None

    try:
        host_python = validate_host_python()
        bound_files = validate_bound_files(
            script_path=script_path,
            expected_script_sha256=args.expected_script_sha256,
            contract_path=args.contract_path.resolve(),
            expected_contract_sha256=args.expected_contract_sha256,
        )
        repo_before = repository_gate(
            runner=runner,
            repo_root=repo_root,
            expected_commit=args.expected_repository_commit,
        )

        if not args.execute:
            print(
                json.dumps(
                    {
                        "mission": MISSION,
                        "construction_revision": CONSTRUCTION_REVISION,
                        "dry_review_complete": True,
                        "execution_enabled": EXECUTION_ENABLED,
                        "resolve_contact": False,
                        "queue_mutation": False,
                        "host_python": host_python,
                        "bound_files": bound_files,
                        "repository": repo_before,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        _require(
            EXECUTION_ENABLED is True,
            "live Test D execution requires EXECUTION_ENABLED = True in this revision",
        )
        required_authorization = build_required_authorization(
            expected_repository_commit=args.expected_repository_commit,
            expected_script_sha256=args.expected_script_sha256,
            expected_contract_sha256=args.expected_contract_sha256,
        )
        _require(
            args.authorization == required_authorization,
            "founder authorization does not match the exact value bound to "
            "this invocation's repository commit, harness SHA-256, and "
            "contract SHA-256",
        )

        evidence_root = (args.evidence_root or default_evidence_root()).resolve()
        _require(
            not _normalized_path_text(evidence_root).startswith(
                _normalized_path_text(repo_root) + os.sep
            ),
            "evidence root must be outside the repository",
        )
        evidence = EvidencePackage(evidence_root)
        evidence.write_json(
            "execution_binding.json",
            {
                "mission": MISSION,
                "construction_revision": CONSTRUCTION_REVISION,
                "started_at": utc_now(),
                "host_python": host_python,
                "bound_files": bound_files,
                "repository_before": repo_before,
                "expected_repository_commit": args.expected_repository_commit,
            },
        )

        resolve = connect_live_resolve()
        result = execute_test_d(resolve, evidence)
        evidence.write_json("test_d_result_pre_repo_postflight.json", result)

        try:
            repo_after = repository_gate(
                runner=runner,
                repo_root=repo_root,
                expected_commit=args.expected_repository_commit,
            )
            result["repository_after"] = repo_after
        except Exception as exc:
            result["repository_after"] = {
                "available": False,
                "error_type": type(exc).__name__,
                "error_repr": _safe_repr(exc),
            }
            prior = result.get("outcome", {})
            result["outcome"] = asdict(
                QueueOutcome(
                    "inconclusive",
                    "repository postflight failed after the queue attempt",
                    prior.get("direct_job_id"),
                    tuple(prior.get("new_job_ids", ())),
                )
            )

        result["completed_at"] = utc_now()
        evidence.write_json("test_d_result.json", result)

        classification = result["outcome"]["classification"]
        print(f"Test D outcome: {classification}")
        print(f"Evidence directory: {evidence_root}")
        if classification == "accepted":
            print(
                "STOP: accepted job is intentionally retained for independent review; "
                "do not render or delete it."
            )
            return EXIT_ACCEPTED
        if classification == "rejected":
            print("STOP: queue rejection observed; do not retry.")
            return EXIT_REJECTED
        print("STOP: inconclusive outcome; do not retry or repair.")
        return EXIT_INCONCLUSIVE

    except GateFailure as exc:
        if evidence is not None:
            try:
                evidence.write_json(
                    "run_failure.json",
                    {
                        "failed_at": utc_now(),
                        "type": type(exc).__name__,
                        "repr": _safe_repr(exc),
                    },
                )
            except Exception:
                pass
        print(f"STOP: {exc}", file=sys.stderr)
        return EXIT_GATE_FAILURE
    except Exception as exc:
        if evidence is not None:
            try:
                evidence.write_json(
                    "run_failure.json",
                    {
                        "failed_at": utc_now(),
                        "type": type(exc).__name__,
                        "repr": _safe_repr(exc),
                    },
                )
            except Exception:
                pass
        print(
            f"STOP: unexpected {type(exc).__name__}: {_safe_repr(exc)}",
            file=sys.stderr,
        )
        return EXIT_GATE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
