"""Shared assembly keeps source boundaries and honest completeness."""

from app.core.log_records import LogAssembler
from app.core.runtime import LogLine, parse_log_line


def line(text: str, stream: str = "stdout") -> LogLine:
    return parse_log_line("2026-10-07T12:00:00.123456789Z " + text, stream)


def test_streams_do_not_steal_each_others_trace() -> None:
    assembly = LogAssembler()
    assembly.feed("one", line("ERROR: failed"), now=0)
    assembly.feed("one", line("INFO: stderr", "stderr"), now=0)
    assembly.feed("two", line("ERROR: other"), now=0)
    assembly.feed("one", line("Traceback (most recent call last):"), now=0)
    assembly.feed("one", line('  File "/code/app/pay.py", line 3, in charge'), now=0)
    assembly.feed("one", line("ValueError: invalid"), now=0)
    records = assembly.flush()
    failed = next(r for r in records if r.line.text == "ERROR: failed")
    assert failed.trace is not None and "ValueError: invalid" in failed.trace
    assert not failed.incomplete
    assert all(r.trace is None for r in records if r is not failed)
    assert failed.line.source_timestamp == "2026-10-07T12:00:00.123456789Z"


def test_idle_flush_and_eof_mark_unfinished_trace() -> None:
    assembly = LogAssembler()
    assembly.feed("one", line("Traceback (most recent call last):"), now=0)
    assert assembly.flush(now=0.1) == []
    (record,) = assembly.flush(now=1)
    assert record.incomplete
    assembly.feed("two", line("Traceback (most recent call last):"), now=2)
    assert assembly.flush("two")[0].incomplete


def test_chain_and_exception_group_stay_together() -> None:
    assembly = LogAssembler()
    lines = [
        "ERROR: failed",
        "Traceback (most recent call last):",
        "ValueError: bad",
        "",
        "During handling of the above exception, another exception occurred:",
        "  + Exception Group Traceback (most recent call last):",
        "  | ExceptionGroup: failures (1 sub-exception)",
        "  +-+---------------- 1 ----------------",
        "    | TypeError: bad",
        "    +------------------------------------",
    ]
    for text in lines:
        assert assembly.feed("one", line(text), now=0) == []
    (record,) = assembly.flush()
    assert record.trace is not None
    assert "ValueError" in record.trace and "TypeError" in record.trace
    assert not record.incomplete


def test_payload_is_bounded_and_labeled() -> None:
    assembly = LogAssembler(max_bytes=128)
    assembly.feed("one", line("ERROR: " + "x" * 1000), now=0)
    for _ in range(20):
        assembly.feed("one", line("    " + "y" * 100), now=0)
    (record,) = assembly.flush()
    assert record.truncated
    assert len(record.line.text.encode()) + len((record.trace or "").encode()) <= 128


def test_exception_without_message_is_folded_and_complete() -> None:
    assembly = LogAssembler()
    assembly.feed("one", line("ERROR: failed"), now=0)
    assembly.feed("one", line("Traceback (most recent call last):"), now=0)
    assembly.feed("one", line("ValueError"), now=0)
    (record,) = assembly.flush()
    assert record.trace is not None and record.trace.endswith("ValueError")
    assert not record.incomplete


def test_completed_trace_does_not_steal_a_plain_log_message() -> None:
    assembly = LogAssembler()
    assembly.feed("one", line("ERROR: failed"), now=0)
    assembly.feed("one", line("Traceback (most recent call last):"), now=0)
    assembly.feed("one", line("ValueError: bad"), now=0)
    (record,) = assembly.feed("one", line("Started: worker"), now=0)
    assert record.trace is not None and record.trace.endswith("ValueError: bad")
    assert assembly.flush()[0].line.text == "Started: worker"
