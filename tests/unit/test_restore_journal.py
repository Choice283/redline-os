"""Tests for the Mission 1B-A1 restore transaction journal
(redline_core.restore.journal): immutable numbered transitions, canonical
JSON + SHA-256 sidecars, collision-refusing publication, and read-only
gap-free chain discovery.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from redline_core.restore.exceptions import RestorePathCollisionError
from redline_core.restore.journal import (
    RestoreJournal,
    RestoreState,
    build_restore_id,
    discover_journal_chain,
    validate_restore_id,
)


def _clock(start: datetime = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)):
    state = {"now": start}

    def tick() -> datetime:
        moment = state["now"]
        state["now"] = moment + timedelta(seconds=1)
        return moment

    return tick


def test_build_restore_id_matches_schema():
    restore_id = build_restore_id(datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc))
    assert validate_restore_id(restore_id) == restore_id
    assert restore_id.startswith("r1-20260817T120000Z-")


def test_two_restore_ids_built_at_the_same_moment_do_not_collide():
    moment = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)
    a = build_restore_id(moment)
    b = build_restore_id(moment)
    assert a != b


def test_record_writes_numbered_transitions_with_intent_and_completion(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-20260817T120000Z-000000000000", "b1-x", clock=_clock())
    journal.record(RestoreState.DB_REPLACE_INTENT, {})
    journal.record(RestoreState.DB_REPLACED, {})

    files = sorted(p.name for p in journal.journal_dir.glob("*.json"))
    assert files == ["0001_DB_REPLACE_INTENT.json", "0002_DB_REPLACED.json"]
    for name in files:
        assert (journal.journal_dir / f"{name}.sha256").is_file()


def test_record_payload_is_canonical_json_with_matching_sha256_sidecar(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-20260817T120000Z-000000000000", "b1-x", clock=_clock())
    path = journal.record(RestoreState.RESTORE_INITIATED, {"reason": "unit test"})

    body = path.read_bytes()
    sidecar = (path.parent / f"{path.name}.sha256").read_text(encoding="ascii").strip()
    assert hashlib.sha256(body).hexdigest() == sidecar

    # canonical: sort_keys, compact separators, ascii-only
    reparsed = json.loads(body)
    assert json.dumps(reparsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8") == body
    assert reparsed["sequence"] == 1
    assert reparsed["state"] == "RESTORE_INITIATED"
    assert reparsed["detail"] == {"reason": "unit test"}


def test_journal_create_fails_closed_on_directory_collision(tmp_path: Path):
    root = tmp_path / "restore_journal"
    RestoreJournal.create(root, "r1-dup", "b1-x", clock=_clock())
    with pytest.raises(RestorePathCollisionError):
        RestoreJournal.create(root, "r1-dup", "b1-x", clock=_clock())


def test_record_never_overwrites_an_existing_transition_pathname(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})

    original_bytes = (journal.journal_dir / "0001_RESTORE_INITIATED.json").read_bytes()

    # Force the same sequence/state to collide by resetting the internal
    # counter (simulating a bug that tried to re-record sequence 1) --
    # the collision-refusing rename/pre-check must still stop it.
    journal._next_sequence = 1
    with pytest.raises(RestorePathCollisionError):
        journal.record(RestoreState.RESTORE_INITIATED, {"different": "payload"})

    assert (journal.journal_dir / "0001_RESTORE_INITIATED.json").read_bytes() == original_bytes


def test_record_never_overwrites_an_existing_sidecar_pathname(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    original_sidecar = (journal.journal_dir / "0001_RESTORE_INITIATED.json.sha256").read_text(encoding="ascii")

    journal._next_sequence = 1
    with pytest.raises(RestorePathCollisionError):
        journal.record(RestoreState.RESTORE_INITIATED, {})

    assert (journal.journal_dir / "0001_RESTORE_INITIATED.json.sha256").read_text(encoding="ascii") == original_sidecar


def test_record_leaves_no_temp_files_behind(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    journal.record(RestoreState.TARGET_VERIFIED, {})

    leftover_tmp = list(journal.journal_dir.glob(".*"))
    assert leftover_tmp == []


# -- discovery: read-only, gap-free ---------------------------------------------


def test_discover_journal_chain_returns_full_valid_chain(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    journal.record(RestoreState.TARGET_VERIFIED, {})
    journal.record(RestoreState.SCHEMA_COMPATIBLE, {})

    chain = discover_journal_chain(journal.journal_dir)
    assert [t.state for t in chain] == ["RESTORE_INITIATED", "TARGET_VERIFIED", "SCHEMA_COMPATIBLE"]
    assert [t.sequence for t in chain] == [1, 2, 3]


def test_discover_journal_chain_stops_at_a_gap(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    journal.record(RestoreState.TARGET_VERIFIED, {})
    journal.record(RestoreState.SCHEMA_COMPATIBLE, {})

    # Remove the middle transition (and its sidecar) to create a gap.
    (journal.journal_dir / "0002_TARGET_VERIFIED.json").unlink()
    (journal.journal_dir / "0002_TARGET_VERIFIED.json.sha256").unlink()

    chain = discover_journal_chain(journal.journal_dir)
    assert [t.state for t in chain] == ["RESTORE_INITIATED"]


def test_discover_journal_chain_does_not_let_a_higher_invalid_transition_hide_the_true_latest_state(tmp_path: Path):
    """A corrupted sequence-2 entry must not let a structurally-present
    sequence-3 file be mistaken for proof of a more-advanced state --
    discovery must stop at the first gap/corruption, not skip past it."""
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    journal.record(RestoreState.TARGET_VERIFIED, {})
    journal.record(RestoreState.SCHEMA_COMPATIBLE, {})

    # Corrupt sequence 2's sidecar so its hash no longer matches.
    sidecar_path = journal.journal_dir / "0002_TARGET_VERIFIED.json.sha256"
    sidecar_path.write_text("0" * 64, encoding="ascii")

    chain = discover_journal_chain(journal.journal_dir)
    assert [t.state for t in chain] == ["RESTORE_INITIATED"]
    # Sequence 3 is present on disk but must never appear in the trusted chain.
    assert not any(t.sequence == 3 for t in chain)


def test_discover_journal_chain_detects_tampered_json_body(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    journal.record(RestoreState.TARGET_VERIFIED, {})

    json_path = journal.journal_dir / "0001_RESTORE_INITIATED.json"
    payload = json.loads(json_path.read_bytes())
    payload["detail"] = {"tampered": True}
    tampered_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    json_path.write_bytes(tampered_bytes)  # sidecar hash no longer matches

    chain = discover_journal_chain(journal.journal_dir)
    assert chain == []


def test_discover_journal_chain_performs_zero_writes(tmp_path: Path):
    journal = RestoreJournal.create(tmp_path / "restore_journal", "r1-x", "b1-x", clock=_clock())
    journal.record(RestoreState.RESTORE_INITIATED, {})
    journal.record(RestoreState.TARGET_VERIFIED, {})

    before = {p.name: p.stat().st_mtime_ns for p in journal.journal_dir.iterdir()}
    discover_journal_chain(journal.journal_dir)
    discover_journal_chain(journal.journal_dir)
    after = {p.name: p.stat().st_mtime_ns for p in journal.journal_dir.iterdir()}
    assert before == after


def test_discover_journal_chain_on_missing_directory_returns_empty(tmp_path: Path):
    assert discover_journal_chain(tmp_path / "does_not_exist") == []


def test_discover_journal_chain_on_empty_directory_returns_empty(tmp_path: Path):
    empty_dir = tmp_path / "empty_journal"
    empty_dir.mkdir()
    assert discover_journal_chain(empty_dir) == []
