"""Redline OS command-line transport.

Mirrors `mcp_server`'s shape: a thin layer over `redline_core`, sharing the
same composition root (`redline_core.runtime.composition`). No business
logic lives here — see docs/ARCHITECTURE.md for the transport boundary.
"""
