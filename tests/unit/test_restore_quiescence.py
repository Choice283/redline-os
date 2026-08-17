"""Tests for the Mission 1B-A1 quiescence probe and attestations
(redline_core.restore.quiescence).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from redline_core.restore.exceptions import RestoreAttestationMissingError, RestoreQuiescenceFailedError
from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.quiescence import probe_quiescence, require_attestations


def test_probe_quiescence_passes_on_an_untouched_database(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    probe_quiescence(db_path)  # must not raise


def test_probe_quiescence_passes_when_database_does_not_exist_yet(tmp_path: Path):
    """The exact "database missing" scenario Restore exists to recover
    from: probing must not create a new file as a side effect."""
    db_path = tmp_path / "redline.db"
    assert not db_path.exists()

    probe_quiescence(db_path)

    assert not db_path.exists(), "probing a missing database must never create one"


def test_probe_quiescence_detects_an_open_writer(tmp_path: Path):
    db_path = tmp_path / "redline.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()

    writer = sqlite3.connect(str(db_path), timeout=0)
    try:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(RestoreQuiescenceFailedError):
            probe_quiescence(db_path)
    finally:
        writer.rollback()
        writer.close()
        conn.close()


def test_probe_quiescence_closes_its_own_connection_before_returning(tmp_path: Path):
    """After a successful probe, nothing Restore itself opened should hold
    a lock -- a second, independent writer must be able to acquire one
    immediately afterward."""
    db_path = tmp_path / "redline.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    probe_quiescence(db_path)

    second = sqlite3.connect(str(db_path), timeout=0)
    try:
        second.execute("BEGIN IMMEDIATE")
        second.rollback()
    finally:
        second.close()


# -- attestations -----------------------------------------------------------------


def test_require_attestations_passes_when_all_true():
    require_attestations(
        QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True)
    )


@pytest.mark.parametrize(
    "kwargs,missing_name",
    [
        ({"mcp_stopped": False, "control_room_stopped": True, "no_other_cli_operation": True}, "mcp_stopped"),
        ({"mcp_stopped": True, "control_room_stopped": False, "no_other_cli_operation": True}, "control_room_stopped"),
        ({"mcp_stopped": True, "control_room_stopped": True, "no_other_cli_operation": False}, "no_other_cli_operation"),
    ],
)
def test_require_attestations_rejects_any_single_missing_attestation(kwargs, missing_name):
    with pytest.raises(RestoreAttestationMissingError, match=missing_name):
        require_attestations(QuiescenceAttestations(**kwargs))


def test_require_attestations_rejects_when_all_missing():
    with pytest.raises(RestoreAttestationMissingError) as excinfo:
        require_attestations(
            QuiescenceAttestations(mcp_stopped=False, control_room_stopped=False, no_other_cli_operation=False)
        )
    message = str(excinfo.value)
    assert "mcp_stopped" in message
    assert "control_room_stopped" in message
    assert "no_other_cli_operation" in message
