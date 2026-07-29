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
from redline_core.runtime.composition import ApplicationServices, build_application_services

# AppContext is exactly ApplicationServices — an alias, not a new type, so
# every existing `ctx.episode_manager`-style attribute access in the tool
# modules keeps working unchanged.
AppContext = ApplicationServices


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
