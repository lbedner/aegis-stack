"""A run's log lines, kept under its id for whoever started it to read.

Bound once where a run starts, every line logged inside it, by structlog
or the standard library, lands in the sink under that id; nothing the
work does differs.
"""

from collections.abc import Callable
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core import run_log
from app.core.config import settings
from app.core.log import logger


def test_lines_logged_inside_a_run_land_under_its_id(
    run_log_sink: run_log.MemorySink, setup_logging: Callable[..., None]
) -> None:
    setup_logging()
    with run_log.bind_run("r1"):
        logger.info("fetched", url="http://a.test", status=200)
        logging.getLogger("third.party").warning("throttled")
    logger.info("outside any run")

    lines = run_log_sink.read("r1")

    assert len(lines) == 2
    assert lines[0].endswith(" info fetched status=200 url=http://a.test")
    assert lines[1].endswith(" warning throttled")
    assert run_log_sink.read("r1", start=1) == lines[1:]
    assert run_log_sink.count("r1") == 2
    assert run_log_sink.read("never") == []


def test_a_line_under_the_level_reaches_no_sink(
    run_log_sink: run_log.MemorySink,
    setup_logging: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run log shows what the console shows: a debug line on an INFO
    stack is dropped before it is rendered, not kept on the side."""
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    setup_logging()
    with run_log.bind_run("r1"):
        logger.debug("noisy")
        logger.info("kept")

    assert [line.split(" ", 2)[1] for line in run_log_sink.read("r1")] == ["info"]


def test_a_failure_keeps_its_traceback(
    run_log_sink: run_log.MemorySink, setup_logging: Callable[..., None]
) -> None:
    setup_logging()
    with run_log.bind_run("r2"):
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("page failed")

    (line,) = run_log_sink.read("r2")

    assert " error page failed" in line
    assert "ValueError: boom" in line.splitlines()[-1]


def test_the_memory_sink_keeps_the_newest_lines_of_the_newest_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_log, "MAX_LINES", 3)
    monkeypatch.setattr(run_log, "MAX_RUNS", 2)
    sink = run_log.MemorySink()
    for n in range(5):
        sink.append("r", f"line {n}")
    sink.append("s", "a")
    sink.append("t", "b")

    assert sink.read("r") == [], "the oldest run made room"
    assert sink.read("s") == ["a"] and sink.read("t") == ["b"]
    sink.append("u", "c")
    for n in range(5):
        sink.append("u", f"line {n}")
    assert sink.read("u") == ["line 2", "line 3", "line 4"]


def test_the_redis_sink_appends_capped_and_expiring() -> None:
    pytest.importorskip("redis")  # a stack without Redis has no sink to test
    redis = MagicMock()
    redis.lrange.return_value = ["a", "b"]
    redis.llen.return_value = 2
    sink = run_log.RedisSink(redis, keep_seconds=60)

    sink.append("r", "a")
    pipe: Any = redis.pipeline.return_value
    pipe.rpush.assert_called_once_with("aegis:run:r:log", "a")
    pipe.ltrim.assert_called_once_with("aegis:run:r:log", -run_log.MAX_LINES, -1)
    pipe.expire.assert_called_once_with("aegis:run:r:log", 60)
    pipe.execute.assert_called_once()
    assert sink.count("r") == 2
    assert sink.read("r", start=1) == ["a", "b"]
    redis.lrange.assert_called_once_with("aegis:run:r:log", 1, -1)


def test_the_redis_sink_reports_an_unreachable_store_as_an_oserror() -> None:
    """A reader (an Overseer partial) answers 503 on it without knowing
    the client."""
    redis_client = pytest.importorskip("redis")

    client = MagicMock()
    client.lrange.side_effect = redis_client.ConnectionError("refused")
    with pytest.raises(OSError):
        run_log.RedisSink(client).read("r1")
