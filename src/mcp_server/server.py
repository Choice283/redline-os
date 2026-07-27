"""Redline OS MCP server entrypoint.

Exposes the Episode/Asset/Media/Timeline/Render/Archive managers (Phases
2-7) as MCP tools. See docs/MCP_TOOLS.md for the full tool reference and
docs/ARCHITECTURE.md §5 for the design rationale (thin tool layer, single
persistent Resolve connection, async-by-design for anything long-running).

Run it with:
    python -m mcp_server.server                 # real Resolve Studio connection
    python -m mcp_server.server --mock-resolve  # MockResolveAdapter, no Studio needed

Requires the optional 'mcp' extra: pip install -e ".[mcp]"
"""
from __future__ import annotations

import argparse
import logging
import os

from redline_core.logging.setup import configure_logging
from redline_core.resolve.mock import MockResolveAdapter

from mcp_server.context import build_context
from mcp_server.tools import archive_tools, asset_tools, episode_tools, media_tools, render_tools, timeline_tools

logger = logging.getLogger(__name__)


def create_server(use_mock_resolve: bool = False):
    """Build and return the configured FastMCP server instance.

    Import of `mcp` is deferred to here (rather than module top-level) so
    that everything else in this package stays importable — and unit
    testable — without the optional [mcp] extra installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "The 'mcp' package is required to run the MCP server. Install it with: pip install -e '.[mcp]'"
        ) from exc

    resolve_adapter = MockResolveAdapter() if use_mock_resolve else None
    ctx = build_context(resolve_adapter=resolve_adapter)

    mcp = FastMCP("redline-mcp")
    episode_tools.register(mcp, ctx)
    asset_tools.register(mcp, ctx)
    media_tools.register(mcp, ctx)
    timeline_tools.register(mcp, ctx)
    render_tools.register(mcp, ctx)
    archive_tools.register(mcp, ctx)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Redline OS MCP server.")
    parser.add_argument(
        "--mock-resolve",
        action="store_true",
        help="Use MockResolveAdapter instead of a real Resolve Studio connection "
        "(for trying the MCP tools out before you have Studio installed).",
    )
    args = parser.parse_args()

    configure_logging(
        log_dir=os.environ.get("REDLINE_LOG_DIR", "./logs"),
        level=os.environ.get("REDLINE_LOG_LEVEL", "INFO"),
    )
    logger.info("Starting Redline OS MCP server (mock_resolve=%s)", args.mock_resolve)

    mcp = create_server(use_mock_resolve=args.mock_resolve)
    mcp.run()


if __name__ == "__main__":
    main()
