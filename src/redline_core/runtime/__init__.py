"""Transport-neutral application runtime.

This package owns the one thing every Redline OS transport (MCP server, CLI,
future transports) needs and must not duplicate: wiring Config, the SQLite
Database, the Resolve connection, and every manager into a single set of
shared instances. See composition.py.
"""
