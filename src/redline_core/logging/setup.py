"""Structured logging setup for Redline OS.

Every module should do `logger = logging.getLogger(__name__)` and let this
module own handler/formatter configuration. Call `configure_logging()` once,
at process start (MCP server boot, CLI entrypoint, or test session).
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(
    log_dir: str | Path = "./logs",
    level: str = "INFO",
    log_filename: str = "redline_os.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the root Redline OS logger with console + rotating file output.

    Returns the configured root logger ("redline_os"). Safe to call multiple
    times (e.g. across tests) — it clears existing handlers first.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("redline_os")
    root.setLevel(level.upper())
    root.handlers.clear()

    formatter = logging.Formatter(_DEFAULT_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / log_filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    root.propagate = False
    return root


def get_episode_logger(episode_id: str) -> logging.LoggerAdapter:
    """Return a logger adapter that prefixes every message with the episode ID.

    Use this inside managers so every log line from an episode's lifecycle
    can be grepped/filtered by episode_id.
    """
    logger = logging.getLogger("redline_os.episode")
    return logging.LoggerAdapter(logger, {"episode_id": episode_id})
