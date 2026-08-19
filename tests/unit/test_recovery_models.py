"""Tests for redline_core.restore.recovery_models.RecoveryAuthorization
(Mission 1B-A2-3)."""
from __future__ import annotations

from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.recovery_models import RecoveryAuthorization

_ALL_TRUE_QUIESCENCE = QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True)


def test_missing_recovery_attestations_empty_when_all_true():
    auth = RecoveryAuthorization(
        confirm_backup_id="b1-x", quiescence=_ALL_TRUE_QUIESCENCE,
        disposition_understood=True, no_automatic_rollback_understood=True,
    )
    assert auth.missing_recovery_attestations() == ()


def test_missing_recovery_attestations_names_disposition_understood():
    auth = RecoveryAuthorization(
        confirm_backup_id="b1-x", quiescence=_ALL_TRUE_QUIESCENCE,
        disposition_understood=False, no_automatic_rollback_understood=True,
    )
    assert auth.missing_recovery_attestations() == ("disposition_understood",)


def test_missing_recovery_attestations_names_no_automatic_rollback():
    auth = RecoveryAuthorization(
        confirm_backup_id="b1-x", quiescence=_ALL_TRUE_QUIESCENCE,
        disposition_understood=True, no_automatic_rollback_understood=False,
    )
    assert auth.missing_recovery_attestations() == ("no_automatic_rollback_understood",)


def test_missing_recovery_attestations_names_both_in_order():
    auth = RecoveryAuthorization(
        confirm_backup_id="b1-x", quiescence=_ALL_TRUE_QUIESCENCE,
        disposition_understood=False, no_automatic_rollback_understood=False,
    )
    assert auth.missing_recovery_attestations() == ("disposition_understood", "no_automatic_rollback_understood")


def test_recovery_authorization_is_frozen():
    auth = RecoveryAuthorization(
        confirm_backup_id="b1-x", quiescence=_ALL_TRUE_QUIESCENCE,
        disposition_understood=True, no_automatic_rollback_understood=True,
    )
    try:
        auth.confirm_backup_id = "b1-y"
        assert False, "expected FrozenInstanceError"
    except AttributeError:
        pass
