"""Tests for redline_core.restore.verification (Mission 1B-A2-3
extraction): the shared Restore verification authority, and proof that
RestoreManager._verify_restore() is now a thin wrapper around it rather
than a duplicated copy.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from redline_core.backup.package import MANIFEST_FILENAME
from redline_core.restore.exceptions import RestoreVerificationFailedError
from redline_core.restore.models import QuiescenceAttestations
from redline_core.restore.verification import verify_restore

from tests.unit._restore_test_helpers import make_environment, make_target_backup

_ALL_TRUE = QuiescenceAttestations(mcp_stopped=True, control_room_stopped=True, no_other_cli_operation=True)


def _load_manifest_for(env, target_id) -> dict:
    verification = env.backup_manager.verify_backup(target_id)
    return json.loads((verification.backup_path / MANIFEST_FILENAME).read_bytes())


def test_verify_restore_succeeds_after_a_real_restore(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)

    manifest = _load_manifest_for(env, target_id)

    # Calling the shared, module-level function directly, independently of
    # RestoreManager, proves the same behavior is genuinely reusable.
    verify_restore(
        db_path=env.db_path, config_dir=env.config_dir, backup_manager=env.backup_manager,
        manifest=manifest, backup_id=target_id,
    )


def test_verify_restore_raises_on_byte_mismatch(tmp_path: Path):
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)
    env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)
    manifest = _load_manifest_for(env, target_id)

    env.db_path.write_bytes(env.db_path.read_bytes() + b"\x00tamper")

    with pytest.raises(RestoreVerificationFailedError):
        verify_restore(
            db_path=env.db_path, config_dir=env.config_dir, backup_manager=env.backup_manager,
            manifest=manifest, backup_id=target_id,
        )


def test_restore_manager_verify_restore_delegates_to_shared_function(tmp_path: Path, monkeypatch):
    """RestoreManager._verify_restore() is a thin wrapper -- prove it by
    making the shared function raise and confirming that failure
    propagates all the way through RestoreManager.restore(), rather than
    a second, independent verification implementation silently succeeding
    instead."""
    env = make_environment(tmp_path)
    target_id = make_target_backup(tmp_path, env)

    def _boom(**kwargs):
        raise RestoreVerificationFailedError("injected by test: shared verification was actually called")

    monkeypatch.setattr("redline_core.restore.manager.verify_restore", _boom)

    with pytest.raises(RestoreVerificationFailedError, match="injected by test"):
        env.restore_manager.restore(target_id, confirm_backup_id=target_id, attestations=_ALL_TRUE)
