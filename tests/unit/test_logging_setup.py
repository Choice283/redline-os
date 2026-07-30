from __future__ import annotations

import io
import logging
import logging.handlers
from pathlib import Path

import pytest

from redline_core.logging.setup import LoggingConfigurationError, configure_logging


def _owned_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in logger.handlers if getattr(handler, "_redline_os_owned_handler", False)]


def _file_handlers(logger: logging.Logger) -> list[logging.handlers.RotatingFileHandler]:
    return [
        handler
        for handler in _owned_handlers(logger)
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]


def _console_handlers(logger: logging.Logger) -> list[logging.StreamHandler]:
    return [
        handler
        for handler in _owned_handlers(logger)
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.handlers.RotatingFileHandler)
    ]


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch):
    logger = logging.getLogger("redline_os")
    original_level = logger.level
    original_handlers = list(logger.handlers)
    original_propagate = logger.propagate
    monkeypatch.delenv("REDLINE_LOG_DIR", raising=False)
    monkeypatch.delenv("REDLINE_LOG_LEVEL", raising=False)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    yield

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        if getattr(handler, "_redline_os_owned_handler", False):
            handler.close()
    for handler in original_handlers:
        logger.addHandler(handler)
    logger.setLevel(original_level)
    logger.propagate = original_propagate


def test_configure_logging_default_configuration_creates_console_and_file(tmp_path):
    logger = configure_logging(log_dir=tmp_path)

    assert logger.name == "redline_os"
    assert logger.level == logging.INFO
    assert logger.propagate is False
    assert len(_owned_handlers(logger)) == 2
    assert len(_console_handlers(logger)) == 1
    assert len(_file_handlers(logger)) == 1
    assert Path(_file_handlers(logger)[0].baseFilename) == tmp_path / "redline_os.log"
    assert (tmp_path / "redline_os.log").exists()


def test_configure_logging_accepts_explicit_valid_log_level(tmp_path):
    logger = configure_logging(log_dir=tmp_path, level="ERROR")

    assert logger.level == logging.ERROR


def test_configure_logging_normalizes_level_case_and_whitespace(tmp_path):
    logger = configure_logging(log_dir=tmp_path, level="  debug ")

    assert logger.level == logging.DEBUG


@pytest.mark.parametrize("level", ["", "TRACE", "CRITICAL", 20])
def test_configure_logging_rejects_invalid_levels_without_creating_log_dir(tmp_path, level):
    log_dir = tmp_path / "logs"

    with pytest.raises(LoggingConfigurationError, match="REDLINE_LOG_LEVEL"):
        configure_logging(log_dir=log_dir, level=level)  # type: ignore[arg-type]

    assert not log_dir.exists()


def test_configure_logging_creates_log_directory_and_respects_filename(tmp_path):
    log_dir = tmp_path / "nested" / "logs"

    logger = configure_logging(log_dir=log_dir, log_filename="operator.log")

    assert log_dir.is_dir()
    assert Path(_file_handlers(logger)[0].baseFilename) == log_dir / "operator.log"
    assert (log_dir / "operator.log").exists()


def test_configure_logging_uses_deterministic_formatter_for_owned_handlers(tmp_path):
    logger = configure_logging(log_dir=tmp_path)

    formats = {handler.formatter._fmt for handler in _owned_handlers(logger)}

    assert formats == {"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"}


def test_repeated_configuration_does_not_duplicate_owned_handlers(tmp_path):
    logger = configure_logging(log_dir=tmp_path)
    first_handlers = list(_owned_handlers(logger))

    logger = configure_logging(log_dir=tmp_path)

    assert len(_owned_handlers(logger)) == 2
    assert not any(handler in _owned_handlers(logger) for handler in first_handlers)


def test_changed_configuration_replaces_owned_handlers_deterministically(tmp_path):
    logger = configure_logging(log_dir=tmp_path / "first", level="INFO", log_filename="first.log")
    first_handlers = list(_owned_handlers(logger))

    logger = configure_logging(log_dir=tmp_path / "second", level="WARNING", log_filename="second.log")

    assert logger.level == logging.WARNING
    assert len(_owned_handlers(logger)) == 2
    assert not any(handler in _owned_handlers(logger) for handler in first_handlers)
    assert Path(_file_handlers(logger)[0].baseFilename) == tmp_path / "second" / "second.log"


def test_unrelated_existing_handlers_remain_untouched(tmp_path):
    logger = logging.getLogger("redline_os")
    stream = io.StringIO()
    unrelated_handler = logging.StreamHandler(stream)
    logger.addHandler(unrelated_handler)

    configure_logging(log_dir=tmp_path)

    assert unrelated_handler in logger.handlers
    assert getattr(unrelated_handler, "_redline_os_owned_handler", False) is False
    assert len(_owned_handlers(logger)) == 2


def test_filesystem_failure_propagates(tmp_path):
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("already a file", encoding="utf-8")

    with pytest.raises(FileExistsError):
        configure_logging(log_dir=file_path)


def test_emitted_message_reaches_file_handler(tmp_path):
    logger = configure_logging(log_dir=tmp_path, level="INFO")

    logger.info("diagnostic message")
    for handler in _file_handlers(logger):
        handler.flush()

    assert "diagnostic message" in (tmp_path / "redline_os.log").read_text(encoding="utf-8")
