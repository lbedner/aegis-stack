"""The dev console logger prints an exception's traceback, not its locals.

Rich tracebacks with locals rendered pydantic-ai's agent and tool objects
in full: some 4,000 lines per failed chat turn, formatted synchronously
while the request waited. The traceback is what a reader needs; a frame's
locals are one breakpoint away.
"""

from collections.abc import Callable
import logging
import sys

import pytest

from app.core import log
from app.core.config import settings


def _formatted_failure() -> str:
    def fails() -> None:
        # Built at runtime so only a locals dump, never the source
        # excerpt, can contain the joined value.
        sentinel = "-".join(("LOCAL", "VALUE", "SENTINEL"))  # noqa: F841
        raise RuntimeError("boom")

    try:
        fails()
    except RuntimeError:
        record = logging.LogRecord(
            "app", logging.ERROR, __file__, 0, "failed", None, sys.exc_info()
        )
    return logging.getLogger().handlers[0].format(record)


def test_dev_tracebacks_leave_the_locals_out(
    monkeypatch: pytest.MonkeyPatch, setup_logging: Callable[..., None]
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    setup_logging()
    out = _formatted_failure()

    assert "RuntimeError" in out and "boom" in out
    assert "LOCAL-VALUE-SENTINEL" not in out
