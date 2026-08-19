"""Tests for Mission 1B-B: the read-only Backup/Restore/Recovery MCP tool
surface (`src/mcp_server/tools/backup_tools.py`,
`src/mcp_server/tools/restore_tools.py`) and its composition wiring
(`mcp_server.context.build_restore_context`).

Reuses `tests/unit/_restore_test_helpers.py`'s `make_environment`/
`make_target_backup` exactly as `tests/unit/test_restore_manager.py` and
`tests/unit/test_recovery_planning.py` already do, and mirrors
`tests/unit/test_mcp_tools.py`'s `_FakeMCP`/`register()` testing pattern so
these tools are exercised without the optional `mcp` extra installed.

Three concerns are tested here:
1. The four new `_*` logic functions behave correctly against real
   `BackupManager`/`RestoreManager` instances (functional coverage).
2. `register()` exposes exactly the four ratified tool names, and only
   those (registration coverage).
3. Neither new module can reach any mutating Restore/Recovery capability —
   proven structurally via AST inspection, not just by what the functional
   tests happen to call (mutation-boundary coverage).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from mcp_server.tools import backup_tools, restore_tools
from redline_core.restore.recovery_models import RecoveryFeasibility, SourceCondition

from tests.unit._restore_test_helpers import make_environment, make_target_backup

_MALFORMED_BACKUP_ID = "not-a-backup-id"
_WELL_FORMED_NONEXISTENT_BACKUP_ID = "b1-20200101T000000Z-000000000000"


# -- backup_tools: functional --------------------------------------------------

def test_backup_list_empty(tmp_path):
    env = make_environment(tmp_path)

    result = backup_tools._backup_list(env.backup_manager)

    assert result == {"success": True, "backups": []}


def test_backup_list_populated(tmp_path):
    env = make_environment(tmp_path)
    backup_id = make_target_backup(tmp_path, env)

    result = backup_tools._backup_list(env.backup_manager)

    assert result["success"] is True
    assert len(result["backups"]) == 1
    record = result["backups"][0]
    assert record["backup_id"] == backup_id
    assert isinstance(record["backup_path"], str)
    assert record["config_file_count"] > 0
    assert record["total_bytes"] > 0


def test_backup_verify_valid_backup(tmp_path):
    env = make_environment(tmp_path)
    backup_id = make_target_backup(tmp_path, env)

    result = backup_tools._backup_verify(env.backup_manager, backup_id)

    assert result["success"] is True
    verification = result["verification"]
    assert verification["backup_id"] == backup_id
    assert verification["verified"] is True
    assert verification["database_integrity_check"] == "ok"


def test_backup_verify_missing_backup(tmp_path):
    env = make_environment(tmp_path)

    result = backup_tools._backup_verify(env.backup_manager, _WELL_FORMED_NONEXISTENT_BACKUP_ID)

    assert result["success"] is False
    assert "error" in result


def test_backup_verify_malformed_backup_id(tmp_path):
    env = make_environment(tmp_path)

    result = backup_tools._backup_verify(env.backup_manager, _MALFORMED_BACKUP_ID)

    assert result["success"] is False
    assert "error" in result


# -- restore_tools: functional --------------------------------------------------

def test_restore_plan_valid_would_proceed(tmp_path):
    env = make_environment(tmp_path)
    backup_id = make_target_backup(tmp_path, env)

    result = restore_tools._restore_plan(env.restore_manager, backup_id)

    assert result["success"] is True
    plan = result["plan"]
    assert plan["backup_id"] == backup_id
    assert plan["target_verified"] is True
    assert plan["would_proceed"] is True
    assert plan["blocking_issues"] == []


def test_restore_plan_blocked_returned_as_data_not_raised(tmp_path):
    env = make_environment(tmp_path)

    result = restore_tools._restore_plan(env.restore_manager, _WELL_FORMED_NONEXISTENT_BACKUP_ID)

    assert result["success"] is True
    plan = result["plan"]
    assert plan["target_verified"] is False
    assert plan["would_proceed"] is False
    assert plan["blocking_issues"] != []


def test_restore_plan_malformed_backup_id(tmp_path):
    env = make_environment(tmp_path)

    result = restore_tools._restore_plan(env.restore_manager, _MALFORMED_BACKUP_ID)

    assert result["success"] is False
    assert "error" in result


def test_restore_recovery_plan_missing_source_recoverable(tmp_path):
    env = make_environment(tmp_path)
    backup_id = make_target_backup(tmp_path, env)
    env.db_path.unlink()

    result = restore_tools._restore_recovery_plan(env.restore_manager, backup_id)

    assert result["success"] is True
    plan = result["plan"]
    assert plan["database"]["condition"] == SourceCondition.MISSING.value
    assert plan["database"]["feasibility"] == RecoveryFeasibility.RECOVERABLE.value
    assert isinstance(plan["sidecar_assessments"], list)
    assert len(plan["sidecar_assessments"]) > 0


def test_restore_recovery_plan_blocked_returned_as_data_not_raised(tmp_path):
    env = make_environment(tmp_path)

    result = restore_tools._restore_recovery_plan(env.restore_manager, _WELL_FORMED_NONEXISTENT_BACKUP_ID)

    assert result["success"] is True
    plan = result["plan"]
    assert plan["target_verified"] is False
    assert plan["would_proceed"] is False
    assert plan["blocking_issues"] != []


def test_restore_recovery_plan_malformed_backup_id(tmp_path):
    env = make_environment(tmp_path)

    result = restore_tools._restore_recovery_plan(env.restore_manager, _MALFORMED_BACKUP_ID)

    assert result["success"] is False
    assert "error" in result


# -- register(): exact tool-name sets -------------------------------------------

class _FakeMCP:
    """Minimal `mcp.server.fastmcp.FastMCP.tool()` stand-in — identical
    pattern to `tests/unit/test_mcp_tools.py`'s `_FakeMCP`, duplicated
    locally (rather than imported cross-file) so this module has no
    dependency on another test file's private helper."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorate(func):
            self.tools[func.__name__] = func
            return func

        return decorate


def test_backup_tools_register_exposes_exactly_backup_list_and_verify(tmp_path):
    env = make_environment(tmp_path)

    class FakeRestoreContext:
        backup_manager = env.backup_manager

    mcp = _FakeMCP()
    backup_tools.register(mcp, FakeRestoreContext())

    assert set(mcp.tools.keys()) == {"backup_list", "backup_verify"}


def test_restore_tools_register_exposes_exactly_restore_plan_and_recovery_plan(tmp_path):
    env = make_environment(tmp_path)

    class FakeRestoreContext:
        restore_manager = env.restore_manager

    mcp = _FakeMCP()
    restore_tools.register(mcp, FakeRestoreContext())

    assert set(mcp.tools.keys()) == {"restore_plan", "restore_recovery_plan"}


def test_registered_backup_list_tool_calls_manager(tmp_path):
    env = make_environment(tmp_path)
    make_target_backup(tmp_path, env)

    class FakeRestoreContext:
        backup_manager = env.backup_manager

    mcp = _FakeMCP()
    backup_tools.register(mcp, FakeRestoreContext())

    result = mcp.tools["backup_list"]()

    assert result["success"] is True
    assert len(result["backups"]) == 1


def test_registered_restore_plan_tool_calls_manager(tmp_path):
    env = make_environment(tmp_path)
    backup_id = make_target_backup(tmp_path, env)

    class FakeRestoreContext:
        restore_manager = env.restore_manager

    mcp = _FakeMCP()
    restore_tools.register(mcp, FakeRestoreContext())

    result = mcp.tools["restore_plan"](backup_id)

    assert result["success"] is True
    assert result["plan"]["would_proceed"] is True


# -- mutation-boundary: structural / AST proofs ----------------------------------

_FORBIDDEN_NAMES = {
    "create_backup",
    "restore",
    "execute_recovery",
    "build_degraded_source_capture",
    "RecoveryAuthorization",
    "QuiescenceAttestations",
    "mcp_stopped",
    "attest_mcp_stopped",
}


def _module_source_path(module) -> Path:
    return Path(inspect.getsourcefile(module))


def _collect_imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _collect_attribute_and_name_identifiers(tree: ast.AST) -> set[str]:
    """Every bare Name identifier and every Attribute's trailing `.attr`
    referenced anywhere in the module — catches `manager.restore(...)`-style
    calls that a pure import-name check would miss."""
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
    return identifiers


@pytest.mark.parametrize("module", [backup_tools, restore_tools])
def test_module_never_imports_a_forbidden_mutation_symbol(module):
    tree = ast.parse(_module_source_path(module).read_text(encoding="utf-8"))
    imported = _collect_imported_names(tree)
    assert not (imported & _FORBIDDEN_NAMES), f"{module.__name__} imports forbidden symbol(s): {imported & _FORBIDDEN_NAMES}"


@pytest.mark.parametrize("module", [backup_tools, restore_tools])
def test_module_never_references_a_forbidden_mutation_identifier(module):
    """Stronger than the import-only check above: also catches an
    attribute reference like `manager.restore(...)` or a bare name used
    without ever being imported (e.g. a typo'd local variable named after
    a forbidden symbol)."""
    tree = ast.parse(_module_source_path(module).read_text(encoding="utf-8"))
    identifiers = _collect_attribute_and_name_identifiers(tree)
    assert not (identifiers & _FORBIDDEN_NAMES), (
        f"{module.__name__} references forbidden identifier(s): {identifiers & _FORBIDDEN_NAMES}"
    )


def test_no_backup_create_restore_execute_or_recovery_execute_tool_registered():
    """Union of every tool this module pair registers must never contain
    backup_create, restore/restore_execute, or restore_recovery/
    restore_recovery_execute under any name."""
    mcp = _FakeMCP()

    class Ctx:
        backup_manager = None
        restore_manager = None

    # register() only needs ctx to build closures; the manager attributes
    # are never called during registration itself, only when a tool is
    # invoked -- safe to pass None here since this test never invokes one.
    backup_tools.register(mcp, Ctx())
    restore_tools.register(mcp, Ctx())

    registered = set(mcp.tools.keys())
    assert registered == {"backup_list", "backup_verify", "restore_plan", "restore_recovery_plan"}
    forbidden_tool_names = {
        "backup_create",
        "restore",
        "restore_execute",
        "restore_recovery",
        "restore_recovery_execute",
    }
    assert not (registered & forbidden_tool_names)


# -- registration parity: original 20 + new 4 == 24, no overlap -----------------

def test_full_server_tool_set_is_original_20_plus_exactly_4_new(tmp_path):
    """Registration-regression proof (Mission 1B-B): builds every one of
    the six pre-existing tool modules' real registered tool names (via
    tests/unit/test_mcp_tools.py's own make_managers()/register() pattern)
    plus the two new modules', and proves: the two sets are disjoint, the
    original set is unchanged from its known-20-name baseline (statically
    enumerated from source, since the optional `mcp` extra is not assumed
    installed in every environment this suite runs in), and the new set is
    exactly the four ratified names."""
    from tests.unit.test_mcp_tools import make_managers
    from mcp_server.tools import archive_tools, asset_tools, episode_tools, media_tools, render_tools, timeline_tools

    m = make_managers(tmp_path)

    class FullAppContext:
        episode_manager = m["episode"]
        asset_manager = m["asset"]
        media_manager = m["media"]
        timeline_builder = m["timeline"]
        render_manager = m["render"]
        archive_manager = m["archive"]

    original_mcp = _FakeMCP()
    episode_tools.register(original_mcp, FullAppContext())
    asset_tools.register(original_mcp, FullAppContext())
    media_tools.register(original_mcp, FullAppContext())
    timeline_tools.register(original_mcp, FullAppContext())
    render_tools.register(original_mcp, FullAppContext())
    archive_tools.register(original_mcp, FullAppContext())

    known_original_20 = {
        "create_episode", "get_episode_status", "list_episodes", "validate_manifest", "assemble_episode",
        "list_available_assets", "verify_assets_for_episode",
        "scan_ingest_for_episode", "organize_bins",
        "build_timeline", "add_markers", "place_clips",
        "queue_render", "get_render_status", "cancel_render", "list_render_jobs_for_episode",
        "archive_create", "archive_verify", "list_archives", "archive_recover",
    }
    assert set(original_mcp.tools.keys()) == known_original_20

    env = make_environment(tmp_path)

    class RestoreCtx:
        backup_manager = env.backup_manager
        restore_manager = env.restore_manager

    new_mcp = _FakeMCP()
    backup_tools.register(new_mcp, RestoreCtx())
    restore_tools.register(new_mcp, RestoreCtx())
    new_names = set(new_mcp.tools.keys())

    assert new_names == {"backup_list", "backup_verify", "restore_plan", "restore_recovery_plan"}
    assert known_original_20.isdisjoint(new_names)

    full_set = known_original_20 | new_names
    assert len(full_set) == 24
