"""Restore transaction journal (Mission 1B-A1).

An immutable, restore-ID-scoped, monotonically-numbered sequence of
transition records under ``<backup_root>/restore_journal/<restore_id>/``.
Each transition is written once, as canonical JSON with a separate SHA-256
sidecar -- exactly Mission 1A's manifest/sidecar precedent
(``redline_core.backup.package``) -- via a unique temp filename, flushed and
fsync'd, then published with a collision-refusing ``os.rename()``. No
transition pathname is ever overwritten, edited, deleted, or reused.

``RestoreJournal`` only ever appends. Discovery (``discover_journal_chain()``)
is a completely separate, read-only function: it performs zero writes, does
not resume or repair anything, and stops at the first gap or corrupt entry
rather than trusting a higher-numbered-but-invalid file to represent the
true latest state. Mission 1B-A1 implements no automatic continuation,
repair, or rollback built on top of this journal -- it exists purely as a
durable, inspectable record of what actually happened, for a human to read
after a crash.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from redline_core.restore.exceptions import RestoreJournalError, RestorePathCollisionError

Clock = Callable[[], datetime]

JOURNAL_DIRNAME = "restore_journal"
RESTORE_ID_SCHEMA_TAG = "r1"
_RESTORE_ID_RE = re.compile(r"^r1-\d{8}T\d{6}Z-[0-9a-f]{12}$")
_TRANSITION_NAME_RE = re.compile(r"^(?P<sequence>\d{4})_(?P<state>[A-Z0-9_]+)\.json$")


class RestoreState(str, Enum):
    """Intent/completion states around every live mutation (Mission 1B-A1,
    locked scope item 11) plus the surrounding read-only/fail-closed states
    needed to make the journal a complete record of one restore attempt."""

    RESTORE_INITIATED = "RESTORE_INITIATED"
    TARGET_VERIFIED = "TARGET_VERIFIED"
    TARGET_VERIFICATION_FAILED = "TARGET_VERIFICATION_FAILED"
    SCHEMA_COMPATIBLE = "SCHEMA_COMPATIBLE"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    PRE_RESTORE_SNAPSHOT_COMPLETE = "PRE_RESTORE_SNAPSHOT_COMPLETE"
    PRE_RESTORE_SNAPSHOT_FAILED = "PRE_RESTORE_SNAPSHOT_FAILED"
    QUIESCENCE_CONFIRMED = "QUIESCENCE_CONFIRMED"
    QUIESCENCE_FAILED = "QUIESCENCE_FAILED"
    SIDECAR_CHECK_PASSED_PRE = "SIDECAR_CHECK_PASSED_PRE"
    SIDECAR_PRESENT_PRE = "SIDECAR_PRESENT_PRE"
    STAGING_INTENT = "STAGING_INTENT"
    STAGING_COMPLETE = "STAGING_COMPLETE"
    STAGING_FAILED = "STAGING_FAILED"
    DB_REPLACE_INTENT = "DB_REPLACE_INTENT"
    DB_REPLACED = "DB_REPLACED"
    DB_REPLACE_FAILED = "DB_REPLACE_FAILED"
    CONFIG_RENAME_ASIDE_INTENT = "CONFIG_RENAME_ASIDE_INTENT"
    CONFIG_RENAMED_ASIDE = "CONFIG_RENAMED_ASIDE"
    CONFIG_INSTALL_INTENT = "CONFIG_INSTALL_INTENT"
    CONFIG_REPLACED = "CONFIG_REPLACED"
    CONFIG_REPLACE_FAILED = "CONFIG_REPLACE_FAILED"
    SIDECAR_CHECK_PASSED_POST = "SIDECAR_CHECK_PASSED_POST"
    SIDECAR_PRESENT_POST = "SIDECAR_PRESENT_POST"
    VERIFICATION_INTENT = "VERIFICATION_INTENT"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_utc_compact(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def validate_restore_id(restore_id: object) -> str:
    if not isinstance(restore_id, str) or not _RESTORE_ID_RE.fullmatch(restore_id):
        raise ValueError(f"restore_id must match {_RESTORE_ID_RE.pattern!r}, got {restore_id!r}")
    return restore_id


def build_restore_id(moment: datetime) -> str:
    """``r1-<UTC timestamp>-<12 random hex>``. Random, not content-derived
    (unlike ``backup_id``): a restore attempt has no stable content digest
    of its own before it begins, and randomness is sufficient to keep
    concurrent restores at the same wall-clock second from colliding --
    the journal directory creation itself is still the authoritative,
    collision-refusing check (``RestoreJournal.create()``)."""
    restore_id = f"{RESTORE_ID_SCHEMA_TAG}-{_format_utc_compact(moment)}-{uuid.uuid4().hex[:12]}"
    return validate_restore_id(restore_id)


def _canonical_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _fsync_write(path: Path, data: bytes) -> None:
    with path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


class RestoreJournal:
    """An open, append-only journal for exactly one restore attempt
    (``restore_id``). Each ``record()`` call durably publishes exactly one
    new, immutable transition file plus its SHA-256 sidecar before
    returning -- there is no in-memory-only transition state a crash could
    lose."""

    def __init__(self, journal_dir: Path, restore_id: str, backup_id: str, *, clock: Clock = _default_clock):
        self.journal_dir = journal_dir
        self.restore_id = restore_id
        self.backup_id = backup_id
        self._clock = clock
        self._next_sequence = 1

    @classmethod
    def create(cls, journal_root: Path, restore_id: str, backup_id: str, *, clock: Clock = _default_clock) -> "RestoreJournal":
        """Create a fresh, restore-ID-scoped journal directory. Fails
        closed (``RestorePathCollisionError``) if a journal directory for
        this ``restore_id`` already exists -- a restore never resumes or
        appends to a prior attempt's journal."""
        journal_dir = journal_root / restore_id
        try:
            journal_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RestorePathCollisionError(
                f"a restore journal directory already exists at {journal_dir}; refusing to reuse or resume "
                "a prior restore_id."
            ) from exc
        except OSError as exc:
            raise RestoreJournalError(f"could not create restore journal directory {journal_dir}: {exc}") from exc
        return cls(journal_dir, restore_id, backup_id, clock=clock)

    def record(self, state: RestoreState, detail: dict | None = None) -> Path:
        """Durably publish the next numbered transition. Returns the
        published transition's path. Raises ``RestorePathCollisionError``
        if the computed final pathname (or its sidecar) already exists --
        this should never happen in normal operation (sequence numbers are
        assigned by this single, in-process counter), but the check is the
        actual collision authority, not merely a sanity assertion."""
        sequence = self._next_sequence
        payload = {
            "restore_id": self.restore_id,
            "backup_id": self.backup_id,
            "sequence": sequence,
            "state": state.value,
            "timestamp": _format_utc_iso(self._clock()),
            "detail": detail or {},
        }
        body = _canonical_json_bytes(payload)
        digest_hex = hashlib.sha256(body).hexdigest()

        final_name = f"{sequence:04d}_{state.value}.json"
        final_path = self.journal_dir / final_name
        sidecar_path = self.journal_dir / f"{final_name}.sha256"
        if final_path.exists() or sidecar_path.exists():
            raise RestorePathCollisionError(
                f"restore journal transition {final_name!r} already exists at {self.journal_dir}; refusing "
                "to overwrite an existing transition."
            )

        tmp_json = self.journal_dir / f".{uuid.uuid4().hex}.json.tmp"
        tmp_sidecar = self.journal_dir / f".{uuid.uuid4().hex}.sha256.tmp"
        try:
            _fsync_write(tmp_json, body)
            _fsync_write(tmp_sidecar, digest_hex.encode("ascii"))
            try:
                os.rename(tmp_json, final_path)
            except FileExistsError as exc:
                raise RestorePathCollisionError(
                    f"restore journal transition {final_name!r} was published concurrently; refusing to "
                    "overwrite it."
                ) from exc
            try:
                os.rename(tmp_sidecar, sidecar_path)
            except FileExistsError as exc:
                raise RestorePathCollisionError(
                    f"restore journal sidecar for {final_name!r} was published concurrently; refusing to "
                    "overwrite it."
                ) from exc
        except OSError as exc:
            if isinstance(exc, RestorePathCollisionError):
                raise
            raise RestoreJournalError(f"could not durably record restore journal transition {final_name!r}: {exc}") from exc
        finally:
            for tmp in (tmp_json, tmp_sidecar):
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

        self._next_sequence += 1
        return final_path


class JournalTransition:
    """One successfully discovered, verified transition record."""

    __slots__ = ("sequence", "state", "path", "payload")

    def __init__(self, sequence: int, state: str, path: Path, payload: dict):
        self.sequence = sequence
        self.state = state
        self.path = path
        self.payload = payload


def discover_journal_chain(journal_dir: Path) -> list[JournalTransition]:
    """Read-only discovery of the gap-free, verified transition chain under
    ``journal_dir``, starting at sequence 1. Performs zero writes.

    Stops at (and excludes) the first sequence number that is missing,
    whose JSON does not parse, whose recorded sequence/state does not match
    its own filename, or whose sidecar hash does not match its bytes --
    a higher-numbered file existing beyond that point is never treated as
    proof of a more-advanced state; only the gap-free prefix is trusted.
    This function does not resume, repair, or continue anything -- it is
    read-only reporting only, for a human (or ``restore-plan``) to inspect
    after an interruption.
    """
    if not journal_dir.is_dir():
        return []

    entries_by_sequence: dict[int, Path] = {}
    for entry in journal_dir.iterdir():
        if not entry.is_file():
            continue
        match = _TRANSITION_NAME_RE.fullmatch(entry.name)
        if not match:
            continue
        entries_by_sequence[int(match.group("sequence"))] = entry

    chain: list[JournalTransition] = []
    sequence = 1
    while sequence in entries_by_sequence:
        json_path = entries_by_sequence[sequence]
        sidecar_path = json_path.with_name(json_path.name + ".sha256")
        transition = _try_read_transition(json_path, sidecar_path, expected_sequence=sequence)
        if transition is None:
            break
        chain.append(transition)
        sequence += 1

    return chain


def _try_read_transition(json_path: Path, sidecar_path: Path, *, expected_sequence: int) -> JournalTransition | None:
    if not sidecar_path.is_file():
        return None
    try:
        body = json_path.read_bytes()
        expected_digest = sidecar_path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    if hashlib.sha256(body).hexdigest() != expected_digest:
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("sequence") != expected_sequence:
        return None
    state = payload.get("state")
    if not isinstance(state, str):
        return None
    expected_name = f"{expected_sequence:04d}_{state}.json"
    if json_path.name != expected_name:
        return None
    return JournalTransition(sequence=expected_sequence, state=state, path=json_path, payload=payload)
