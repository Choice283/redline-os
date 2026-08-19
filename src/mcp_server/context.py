"""Shared application context for the MCP server.

This is now a thin, MCP-specific alias over the transport-neutral
composition root in `redline_core.runtime.composition` — see that module
for the actual construction logic and rationale. Kept here (rather than
having every tool module import from `redline_core.runtime` directly) so
existing imports (`from mcp_server.context import build_context, AppContext`)
keep working unchanged for the MCP transport and its tests.
"""
from __future__ import annotations

from pathlib import Path

from redline_core.resolve.adapter import ResolveAdapter
from redline_core.runtime.composition import (
    ApplicationServices,
    RestoreServices,
    build_application_services,
    build_restore_services,
)

# AppContext is exactly ApplicationServices — an alias, not a new type, so
# every existing `ctx.episode_manager`-style attribute access in the tool
# modules keeps working unchanged.
AppContext = ApplicationServices

# RestoreContext is exactly RestoreServices (Mission 1B-B) — a second,
# independent context object, deliberately never merged into AppContext.
# RestoreServices holds neither a live Database connection nor a Resolve
# adapter, and per redline_core.runtime.composition's own module docstring
# must never share a tier with a builder that opens either.
RestoreContext = RestoreServices


def build_context(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    resolve_adapter: ResolveAdapter | None = None,
) -> AppContext:
    """Build the shared AppContext for the MCP server.

    Same signature and behavior as before this refactor — delegates to the
    transport-neutral `build_application_services()`.
    """
    return build_application_services(
        config_dir=config_dir,
        db_path=db_path,
        resolve_adapter=resolve_adapter,
    )


def build_restore_context(
    config_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> RestoreContext:
    """Build the shared, independent read-only Backup/Restore/Recovery
    context for the MCP server (Mission 1B-B).

    Mirrors `build_context()` exactly, delegating to the existing,
    transport-neutral `build_restore_services()` — never calls
    `Database.connect()`/`init_schema()` and never constructs or connects a
    `ResolveAdapter`, the same guarantee `build_context()`'s underlying
    `build_application_services()` does not make. Kept as a second, separate
    context object rather than folded into `AppContext` so that a caller
    routed through `RestoreContext` genuinely cannot reach `ctx.db` or
    `ctx.resolve`, by construction, not by convention.
    """
    return build_restore_services(config_dir=config_dir, db_path=db_path)
