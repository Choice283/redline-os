"""Read-only discovery and parsing of Control Room mission closure
records under a project's docs/control_room/ directory -- the durable
historical record the Project Detail screen's Mission & Checkpoint
History section is derived from. Never touches PROJECT_STATE.yaml
(which remains a current-state record only, never an event log) and
never treats conversation history or agent reports as source-of-truth.

Discovery uses the established `MISSION_<n>_CLOSURE_<date>.md` naming
convention only to enumerate candidate files -- it is not itself trusted
as data. Every field value is parsed from each document's own content
(the H1 title, the `## Published Checkpoint` SHA line, and the literal
"is formally closed." closure statement each closure document so far
has used) rather than from the filename. `closure_date` is the one
narrow, documented exception: no closure document currently encodes its
own date as a content field, so it is read from the filename's trailing
`_YYYY-MM-DD` segment; if that segment is absent or not a valid
calendar date, `closure_date` is simply None -- never a guessed date.

This module never raises. A file that cannot be read, or whose content
does not match the expected structure, yields a MissionHistoryEntry with
`parse_error` set describing exactly what could not be determined,
rather than being silently dropped or given an invented value.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from control_room.models import MissionHistoryEntry

logger = logging.getLogger("redline_os.control_room.mission_history_reader")

_FILENAME_PATTERN = re.compile(r"^MISSION_(\d+)_CLOSURE_(\d{4}-\d{2}-\d{2})\.md$")
_TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s+Closure\s*$", re.MULTILINE)
_MISSION_NUMBER_IN_TITLE_PATTERN = re.compile(r"Mission\s+(\d+)")
_PUBLISHED_CHECKPOINT_SECTION_PATTERN = re.compile(
    r"^##\s+Published Checkpoint\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
_SHA_PATTERN = re.compile(r"SHA:\s*\n\s*`([0-9a-f]{40})`")
_CLOSED_STATEMENT_PATTERN = re.compile(r"is formally closed\.")


class MissionHistoryReader:
    """Reads every `MISSION_*_CLOSURE_*.md` file directly inside a given
    docs/control_room/ directory and parses it into a MissionHistoryEntry,
    sorted deterministically by mission number."""

    def read(self, history_dir: str | Path, repository_path: str | Path) -> list[MissionHistoryEntry]:
        directory = Path(history_dir)
        repository_path = Path(repository_path)
        if not directory.is_dir():
            return []

        candidates = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and _FILENAME_PATTERN.match(path.name)
        )

        entries = [self._parse(path, repository_path) for path in candidates]
        entries.sort(key=self._sort_key)
        return entries

    def _parse(self, path: Path, repository_path: Path) -> MissionHistoryEntry:
        filename_match = _FILENAME_PATTERN.match(path.name)
        filename_number = int(filename_match.group(1)) if filename_match else None
        filename_date = filename_match.group(2) if filename_match else None
        closure_document = self._relative_document_path(path, repository_path)

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            message = f"unable to read mission closure document {path}: {exc}"
            logger.error("control room mission history read failed: %s", message)
            return MissionHistoryEntry(
                mission_number=filename_number,
                closure_document=closure_document,
                closure_date=self._valid_iso_date(filename_date),
                parse_error=message,
            )

        parse_errors: list[str] = []

        title_match = _TITLE_PATTERN.search(text)
        title = title_match.group(1).strip() if title_match else None
        if title is None:
            parse_errors.append("could not parse mission title from document heading")

        mission_number = self._extract_mission_number(title)
        if mission_number is None:
            mission_number = filename_number
        if mission_number is None:
            parse_errors.append("could not determine mission number from title or filename")

        checkpoint_commit = self._extract_published_checkpoint_sha(text)
        if checkpoint_commit is None:
            parse_errors.append("could not parse published checkpoint SHA from document")

        status = "closed" if _CLOSED_STATEMENT_PATTERN.search(text) else "unknown"
        if status == "unknown":
            parse_errors.append("document does not contain an explicit closure statement")

        return MissionHistoryEntry(
            mission_number=mission_number,
            title=title,
            status=status,
            checkpoint_commit=checkpoint_commit,
            closure_document=closure_document,
            closure_date=self._valid_iso_date(filename_date),
            parse_error="; ".join(parse_errors) if parse_errors else None,
        )

    @staticmethod
    def _extract_mission_number(title: str | None) -> int | None:
        if title is None:
            return None
        match = _MISSION_NUMBER_IN_TITLE_PATTERN.search(title)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_published_checkpoint_sha(text: str) -> str | None:
        section_match = _PUBLISHED_CHECKPOINT_SECTION_PATTERN.search(text)
        if section_match is None:
            return None
        sha_match = _SHA_PATTERN.search(section_match.group("body"))
        return sha_match.group(1) if sha_match else None

    @staticmethod
    def _valid_iso_date(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value

    @staticmethod
    def _relative_document_path(path: Path, repository_path: Path) -> str:
        try:
            relative = path.relative_to(repository_path)
        except ValueError:
            # Should not happen for a real registry entry (history_dir is
            # always resolved under repository_path), but degrade to the
            # bare filename rather than raising if it ever does.
            return path.name
        return relative.as_posix()

    @staticmethod
    def _sort_key(entry: MissionHistoryEntry):
        return (entry.mission_number is None, entry.mission_number or 0, entry.closure_document)
