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


def test_a_line_that_carries_a_traceback_is_an_error() -> None:
    """A traceback folds into the line before it; that line, levelled or not
    ("Running in Docker container..." before a crash), is shown as an error."""
    assembly = LogAssembler()
    for text in [
        "Running in Docker container...",
        "Traceback (most recent call last):",
        '  File "/code/app/run.py", line 3, in <module>',
        "ImportError: cannot import name 'x'",
    ]:
        assembly.feed("one", line(text), now=0)
    (record,) = assembly.flush()

    assert record.trace is not None and record.trace.endswith("cannot import name 'x'")
    assert record.line.level == "error"


def test_a_traceback_on_its_own_is_an_error() -> None:
    assembly = LogAssembler()
    assembly.feed("one", line("Traceback (most recent call last):"), now=0)
    assembly.feed("one", line("ValueError: bad"), now=0)
    (record,) = assembly.flush()

    assert record.line.level == "error"


def test_an_error_lines_trace_stays_with_it_and_keeps_its_level() -> None:
    assembly = LogAssembler()
    assembly.feed("one", line("CRITICAL: payment failed"), now=0)
    assembly.feed("one", line("Traceback (most recent call last):"), now=0)
    assembly.feed("one", line("ValueError: bad"), now=0)
    (record,) = assembly.flush()

    assert record.line.level == "critical" and record.trace is not None


def test_indented_lines_folded_in_are_not_a_traceback() -> None:
    """A warning's source line or a pretty-printed dict folds into its line
    for Logs; that is not an exception, so the line keeps its level."""
    assembly = LogAssembler()
    assembly.feed("one", line("/code/app/x.py:12: DeprecationWarning: old"), now=0)
    assembly.feed("one", line("  warnings.warn('old')"), now=0)
    (record,) = assembly.flush()

    assert record.trace is not None and not record.recognized
    assert record.line.level is None
