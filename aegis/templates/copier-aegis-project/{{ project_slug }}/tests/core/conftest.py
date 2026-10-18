"""Fixtures for the core tests."""

from collections.abc import Callable, Iterator
import logging
import sys
from typing import TextIO

import pytest
import structlog

from app.core import log


@pytest.fixture
def setup_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """``log.setup_logging`` for one test, with everything it changed put back.

    It swaps structlog's processor list and caches each logger on first use.
    A logger cached on the session's list keeps it; left swapped, a later
    ``structlog.testing.capture_logs`` empties a list that logger no longer
    reads, and captures nothing.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_config = structlog.get_config()
    monkeypatch.setattr(log, "_logging_configured", False)

    def setup(stream: TextIO = sys.stdout) -> None:
        log.setup_logging(stream)
        # No logger caches this test's processors for the rest of the session.
        structlog.configure(cache_logger_on_first_use=False)

    try:
        yield setup
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.configure(**saved_config)
