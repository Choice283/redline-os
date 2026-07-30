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
_OWNED_HANDLER_ATTR = "_redline_os_owned_handler"
_SUPPORTED_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class LoggingConfigurationError(ValueError):
    """Raised when Redline OS logging cannot be configured safely."""


def configure_logging(
    log_dir: str | Path = "./logs",
    level: str = "INFO",
    log_filename: str = "redline_os.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the root Redline OS logger with console + rotating file output.

    Returns the configured root logger ("redline_os"). Safe to call multiple
    times (e.g. across tests) by replacing only Redline-owned handlers.
    """
    level_value = _normalize_level(level)
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("redline_os")
    root.setLevel(level_value)
    _remove_owned_handlers(root)

    formatter = logging.Formatter(_DEFAULT_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    _mark_owned(console_handler)
    root.addHandler(console_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / log_filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    _mark_owned(file_handler)
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


def _normalize_level(level: str) -> int:
    if not isinstance(level, str):
        raise LoggingConfigurationError("REDLINE_LOG_LEVEL must be one of: DEBUG, INFO, WARNING, ERROR.")

    level_name = level.strip().upper()
    if level_name not in _SUPPORTED_LEVELS:
        raise LoggingConfigurationError("REDLINE_LOG_LEVEL must be one of: DEBUG, INFO, WARNING, ERROR.")
    return _SUPPORTED_LEVELS[level_name]


def _mark_owned(handler: logging.Handler) -> None:
    setattr(handler, _OWNED_HANDLER_ATTR, True)


def _remove_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _OWNED_HANDLER_ATTR, False):
            logger.removeHandler(handler)
            handler.close()
