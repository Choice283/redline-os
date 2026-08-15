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


# -- Validation & Evidence Detail (Mission 5) -------------------------------

_CLOSURE_WITH_EVIDENCE_TEMPLATE = """# Control Room V0 Mission {number} Closure

## Published Checkpoint

SHA:
`{sha}`

## Validation

- **Focused suite**: 10 passed.
- **Broad regression**: 100 passed, 2 skipped.

## Independent Review

Final verdict: **PASS**.

## CI

Observed failure, classified pre-existing.

## Closure

Control Room V0 Mission {number} is formally closed.
"""


def _write_closure_with_evidence(directory: Path, number: int, date: str, sha: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"MISSION_{number}_CLOSURE_{date}.md"
    path.write_text(_CLOSURE_WITH_EVIDENCE_TEMPLATE.format(number=number, sha=sha), encoding="utf-8")
    return path


def test_extracts_validation_independent_review_and_ci_sections_verbatim(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure_with_evidence(history_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert "Focused suite" in entry.validation_section
    assert "10 passed" in entry.validation_section
    assert "Broad regression" in entry.validation_section
    assert "PASS" in entry.independent_review_section
    assert "pre-existing" in entry.ci_section


def test_evidence_sections_do_not_bleed_into_each_other(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure_with_evidence(history_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    # Validation text must not contain the Independent Review or CI content,
    # and vice versa -- each section is bounded strictly by the next "## ".
    assert "Final verdict" not in entry.validation_section
    assert "Observed failure" not in entry.validation_section
    assert "Focused suite" not in entry.independent_review_section
    assert "Focused suite" not in entry.ci_section


def test_tilde_fenced_headings_do_not_truncate_validation_evidence(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n"
        "## Published Checkpoint\n\n"
        f"SHA:\n`{_SHA_A}`\n\n"
        "## Validation\n\n"
        "before\n\n"
        "~~~text\n"
        "## CI\n"
        "fake heading inside evidence\n"
        "~~~\n\n"
        "after\n\n"
        "## Independent Review\n\n"
        "Final verdict: PASS.\n\n"
        "## Closure\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.validation_section == (
        "before\n\n"
        "~~~text\n"
        "## CI\n"
        "fake heading inside evidence\n"
        "~~~\n\n"
        "after"
    )
    assert entry.independent_review_section == "Final verdict: PASS."


def test_fenced_fake_validation_heading_is_not_selected_before_real_heading(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n"
        "## Published Checkpoint\n\n"
        f"SHA:\n`{_SHA_A}`\n\n"
        "~~~text\n"
        "## Validation\n"
        "fake evidence\n"
        "~~~\n\n"
        "## Validation\n\n"
        "real evidence\n\n"
        "## Closure\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.validation_section == "real evidence"
    assert "fake evidence" not in entry.validation_section


def test_backtick_fenced_headings_do_not_end_validation_evidence(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n"
        "## Published Checkpoint\n\n"
        f"SHA:\n`{_SHA_A}`\n\n"
        "## Validation\n\n"
        "before backtick fence\n\n"
        "````markdown\n"
        "## Independent Review\n"
        "not a real section boundary\n"
        "````\n\n"
        "after backtick fence\n\n"
        "## Closure\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.validation_section == (
        "before backtick fence\n\n"
        "````markdown\n"
        "## Independent Review\n"
        "not a real section boundary\n"
        "````\n\n"
        "after backtick fence"
    )
    assert entry.independent_review_section is None


def test_missing_validation_section_is_none_not_invented(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n## Published Checkpoint\n\nSHA:\n"
        f"`{_SHA_A}`\n\n## Closure\n\nControl Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.validation_section is None
    assert entry.independent_review_section is None
    assert entry.ci_section is None
    # Absence of these optional sections is not itself a parse error --
    # only title/checkpoint/closure-statement problems are.
    assert entry.parse_error is None


def test_evidence_extraction_unaffected_by_title_and_checkpoint_parse_errors(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "No heading and no checkpoint section in this document.\n\n"
        "## Validation\n\nEvidence text survives even when other fields fail to parse.\n\n"
        "## Closure\n\n(no explicit closure statement)\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.title is None
    assert entry.checkpoint_commit is None
    assert entry.parse_error is not None
    assert "Evidence text survives" in entry.validation_section


def test_history_discovery_does_not_recurse_into_subdirectories(tmp_path):
    """Discovery must only ever consider direct children of the configured
    history directory -- never an arbitrary, deeper, or user-influenced
    path. A validly-named closure file nested one level deeper must not be
    discovered."""
    history_dir = tmp_path / "docs" / "control_room"
    nested_dir = history_dir / "nested"
    _write_closure(nested_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    entries = reader.read(history_dir, tmp_path)

    assert entries == []


# -- Mission Scope & Outcome Detail (Mission 6) -----------------------------

_CLOSURE_WITH_SCOPE_OUTCOME_TEMPLATE = """# Control Room V0 Mission {number} Closure

## Purpose

This mission exists to prove scope extraction works.

## Published Checkpoint

SHA:
`{sha}`

## Delivered Capability

- Delivered thing one.
- Delivered thing two.

## Deferred Work

- Deferred thing one.
- Deferred thing two.

## Closure

Control Room V0 Mission {number} is formally closed.
"""


def _write_closure_with_scope_outcome(directory: Path, number: int, date: str, sha: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"MISSION_{number}_CLOSURE_{date}.md"
    path.write_text(_CLOSURE_WITH_SCOPE_OUTCOME_TEMPLATE.format(number=number, sha=sha), encoding="utf-8")
    return path


def test_extracts_purpose_delivered_capability_and_deferred_work_verbatim(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure_with_scope_outcome(history_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert "prove scope extraction" in entry.purpose_section
    assert "Delivered thing one" in entry.delivered_capability_section
    assert "Delivered thing two" in entry.delivered_capability_section
    assert "Deferred thing one" in entry.deferred_work_section
    assert "Deferred thing two" in entry.deferred_work_section


def test_scope_outcome_sections_do_not_bleed_into_each_other_or_evidence(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    _write_closure_with_scope_outcome(history_dir, 1, "2026-08-01", _SHA_A)

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert "Delivered thing" not in entry.purpose_section
    assert "Deferred thing" not in entry.purpose_section
    assert "prove scope extraction" not in entry.delivered_capability_section
    assert "Deferred thing" not in entry.delivered_capability_section
    assert "Delivered thing" not in entry.deferred_work_section
    # Scope/outcome sections must not be confused with evidence sections.
    assert entry.validation_section is None
    assert entry.independent_review_section is None


def test_missing_scope_outcome_sections_are_none_not_invented(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n## Published Checkpoint\n\nSHA:\n"
        f"`{_SHA_A}`\n\n## Closure\n\nControl Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.purpose_section is None
    assert entry.delivered_capability_section is None
    assert entry.deferred_work_section is None
    # Absence of these optional sections is not itself a parse error.
    assert entry.parse_error is None


def test_fenced_fake_purpose_heading_does_not_alter_extraction_boundary(tmp_path):
    history_dir = tmp_path / "docs" / "control_room"
    history_dir.mkdir(parents=True)
    (history_dir / "MISSION_1_CLOSURE_2026-08-01.md").write_text(
        "# Control Room V0 Mission 1 Closure\n\n"
        "## Purpose\n\n"
        "real purpose text\n\n"
        "```markdown\n"
        "## Delivered Capability\n"
        "fake heading inside a fenced example\n"
        "```\n\n"
        "still purpose text after the fence\n\n"
        "## Published Checkpoint\n\n"
        f"SHA:\n`{_SHA_A}`\n\n"
        "## Delivered Capability\n\n"
        "real delivered capability text\n\n"
        "## Closure\n\n"
        "Control Room V0 Mission 1 is formally closed.\n",
        encoding="utf-8",
    )

    reader = MissionHistoryReader()
    [entry] = reader.read(history_dir, tmp_path)

    assert entry.purpose_section == (
        "real purpose text\n\n"
        "```markdown\n"
        "## Delivered Capability\n"
        "fake heading inside a fenced example\n"
        "```\n\n"
        "still purpose text after the fence"
    )
    assert entry.delivered_capability_section == "real delivered capability text"
    assert "fake heading" not in entry.delivered_capability_section


def test_real_mission_1_through_5_closure_documents_parse_scope_outcome_cleanly():
    """Missions 1-5 are proven compatible against their real committed
    closure records -- not a synthetic fixture."""
    repo_root = Path(__file__).resolve().parents[3]
    history_dir = repo_root / "docs" / "control_room"

    reader = MissionHistoryReader()
    entries = reader.read(history_dir, repo_root)
    by_number = {entry.mission_number: entry for entry in entries}

    for mission_number in (1, 2, 3, 4, 5):
        assert mission_number in by_number, f"Mission {mission_number} closure document not discovered"
        entry = by_number[mission_number]
        assert entry.parse_error is None, f"Mission {mission_number}: {entry.parse_error}"
        assert entry.purpose_section, f"Mission {mission_number} missing Purpose"
        assert entry.delivered_capability_section, f"Mission {mission_number} missing Delivered Capability"
        assert entry.deferred_work_section, f"Mission {mission_number} missing Deferred Work"
