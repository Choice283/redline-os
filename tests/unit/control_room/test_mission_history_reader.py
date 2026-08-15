"""Tests for control_room.mission_history_reader.MissionHistoryReader --
discovery of MISSION_*_CLOSURE_*.md documents, deterministic parsing of
title/status/checkpoint SHA/closure date, deterministic ordering, and
graceful degradation of malformed or incomplete records. Never touches
PROJECT_STATE.yaml and never raises."""
from __future__ import annotations

from pathlib import Path

from control_room.mission_history_reader import MissionHistoryReader

_VALID_CLOSURE_TEMPLATE = """# Control Room V0 Mission {number} Closure

## Purpose

Test closure document.

## Published Checkpoint

SHA:
`{sha}`

Subject:
`test: mission {number} checkpoint`

## Closure

Control Room V0 Mission {number} is formally closed.
"""


def _write_closure(directory: Path, number: int, date: str, sha: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"MISSION_{number}_CLOSURE_{date}.md"
    path.write_text(_VALID_CLOSURE_TEMPLATE.format(number=number, sha=sha), encoding="utf-8")
    return path


_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40


def test_no_history_directory_returns_empty_list(tmp_path):
    reader = MissionHistoryReader()
    entries = reader.read(tmp_path / "does-not-exist", tmp_path)
    assert entries == []


def test_reads_valid_closure_documents_in_deterministic_order(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    # Written out of order on purpose -- ordering must come from parsed
    # content/filename, never from filesystem iteration order.
    _write_closure(history_dir, 2, "2026-08-10", _SHA_B)
    _write_closure(history_dir, 1, "2026-08-01", _SHA_A)
    _write_closure(history_dir, 3, "2026-08-15", _SHA_C)

    reader = MissionHistoryReader()
    entries = reader.read(history_dir, tmp_path)

    assert [entry.mission_number for entry in entries] == [1, 2, 3]


def test_orders_double_digit_missions_numerically(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure(history_dir, 10, "2026-08-20", _SHA_C)
    _write_closure(history_dir, 2, "2026-08-10", _SHA_B)
    _write_closure(history_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    entries = reader.read(history_dir, tmp_path)

    assert [entry.mission_number for entry in entries] == [1, 2, 10]


def test_parses_title_status_checkpoint_and_closure_document_reference(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure(history_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.mission_number == 1
    assert entry.title == "Control Room V0 Mission 1"
    assert entry.status == "closed"
    assert entry.checkpoint_commit == _SHA_A
    assert entry.closure_document == "docs/control_room/MISSION_1_CLOSURE_2026-08-01.md"
    assert entry.closure_date == "2026-08-01"
    assert entry.parse_error is None


def test_checkpoint_sha_comes_only_from_published_checkpoint_section(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    unrelated_sha = "d" * 40
    published_sha = _SHA_A
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n"
        "## Evidence\n\n"
        f"SHA:\n`{unrelated_sha}`\n\n"
        "## Published Checkpoint\n\n"
        f"SHA:\n`{published_sha}`\n\n"
        "Subject:\n`test: mission 1 checkpoint`\n\n"
        "## Closure\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.checkpoint_commit == published_sha


def test_document_missing_checkpoint_section_degrades_without_raising(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\nNo checkpoint section here.\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.mission_number == 1
    assert entry.checkpoint_commit is None
    assert entry.status == "closed"
    assert entry.parse_error is not None
    assert "checkpoint" in entry.parse_error.lower()


def test_document_without_closure_statement_status_is_unknown_not_invented(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        f"# Control Room V0 Mission 1 Closure\n\n## Published Checkpoint\n\nSHA:\n`{_SHA_A}`\n\n"
        "This document never states the mission is closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.status == "unknown"
    assert entry.checkpoint_commit == _SHA_A
    assert entry.parse_error is not None
    assert "closure statement" in entry.parse_error.lower()


def test_document_missing_title_heading_degrades_and_falls_back_to_filename_number(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        f"No heading in this document.\n\n## Published Checkpoint\n\nSHA:\n`{_SHA_A}`\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.title is None
    assert entry.mission_number == 1  # recovered from the filename, not invented
    assert entry.parse_error is not None
    assert "title" in entry.parse_error.lower()


def test_malformed_document_does_not_prevent_other_entries_from_parsing(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure(history_dir, 1, "2026-08-01", _SHA_A)
    (history_dir / "MISSION_2_CLOSURE_2026-08-10.md").write_text(
        "garbage content with no recognizable structure\n", encoding="utf-8"
    )
    _write_closure(history_dir, 3, "2026-08-15", _SHA_C)

    reader = MissionHistoryReader()
    entries = reader.read(history_dir, tmp_path)

    assert len(entries) == 3
    by_number = {entry.mission_number: entry for entry in entries}
    assert by_number[1].parse_error is None
    assert by_number[3].parse_error is None
    assert by_number[2].parse_error is not None
    assert by_number[2].checkpoint_commit is None
    assert by_number[2].status == "unknown"


def test_invalid_filename_date_yields_none_closure_date_not_a_guess(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    # Syntactically matches \d{4}-\d{2}-\d{2} but is not a real calendar date.
    (history_dir / "MISSION_1_CLOSURE_2026-13-40.md").write_text(
        _VALID_CLOSURE_TEMPLATE.format(number=1, sha=_SHA_A), encoding="utf-8"
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.closure_date is None
    assert entry.checkpoint_commit == _SHA_A  # unaffected by the bad date


def test_non_matching_filenames_are_not_discovered(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        _VALID_CLOSURE_TEMPLATE.format(number=1, sha=_SHA_A), encoding="utf-8"
    )
    (history_dir / "PROJECT_STATE.yaml").write_text("irrelevant: true\n", encoding="utf-8")
    (history_dir / "README.md").write_text("irrelevant\n", encoding="utf-8")

    reader = MissionHistoryReader()
    entries = reader.read(history_dir, tmp_path)

    assert len(entries) == 1
    assert entries[0].mission_number == 1
