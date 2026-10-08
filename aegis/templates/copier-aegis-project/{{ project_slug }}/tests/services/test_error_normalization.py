"""Grouping is independent of replay identity and retention is redacted."""

from dataclasses import replace
from datetime import UTC, datetime
import json
from typing import Any

import pytest

from app.core.log_records import LogAssembler, LogRecord
from app.core.runtime import parse_log_line
from app.services.system.errors.models import ErrorOccurrence
from app.services.system.errors.normalize import normalize


def event(message: str, trace: str | None = None, **fields: Any) -> LogRecord:
    assembly = LogAssembler()
    assembly.feed(
        "container-id",
        parse_log_line(
            json.dumps({"event": message, "exception": trace, **fields}), "stderr"
        ),
        now=0,
    )
    return assembly.flush()[0]


def normalized(record: LogRecord, ordinal: int = 0) -> ErrorOccurrence | None:
    return normalize(
        record,
        page="worker",
        service="worker-system",
        container_name="worker-1",
        ordinal=ordinal,
        observed_at=datetime(2026, 10, 7, tzinfo=UTC),
    )


@pytest.mark.parametrize("fields", [{}, {"level": "warning"}, {"level": "info"}])
def test_plain_stderr_and_error_words_are_not_errors(fields: dict[str, str]) -> None:
    assert normalized(event("error rate is zero", **fields)) is None


def test_message_only_error_has_no_invented_trace() -> None:
    result = normalized(event("failed", level="error"))
    assert (
        result is not None
        and result.traceback is None
        and result.exception_type is None
    )


def test_grouping_ignores_deployment_root_line_number_and_request_id() -> None:
    first = event(
        "failed request 123",
        'Traceback (most recent call last):\n  File "/code/app/pay.py", line 3, in charge\nValueError: bad',
        level="warning",
        request_id="123",
    )
    other = event(
        "failed request 456",
        'Traceback (most recent call last):\n  File "/srv/release/app/pay.py", line 99, in charge\nValueError: different',
        level="warning",
        request_id="456",
    )
    a, b = normalized(first), normalized(other)
    assert a is not None and b is not None
    assert a.fingerprint == b.fingerprint
    repeated, replayed = normalized(first, 1), normalized(first)
    assert repeated is not None and replayed is not None
    assert a.id != repeated.id
    assert a.id == replayed.id
    assert first.trace is not None
    different = normalized(
        event("failed", first.trace.replace("charge", "refund"), level="error")
    )
    assert different is not None and different.fingerprint != a.fingerprint
    permission = normalized(event("permission denied", level="error"))
    connection = normalized(event("connection refused", level="error"))
    assert permission is not None and connection is not None
    assert permission.fingerprint != connection.fingerprint


def test_retained_payload_removes_credentials_and_locals() -> None:
    record = event(
        "Authorization: Bearer test-token-abc",
        'Traceback (most recent call last):\n  File "app/a.py", line 1, in run\nValueError: token=secret123',
        level="error",
        password="password123",
        context={"api_key": "key123", "safe": "ok"},
        locals={"secret": "local123"},
    )
    result = normalized(record)
    assert result is not None
    serialized = result.model_dump_json()
    for secret in ("test-token-abc", "secret123", "password123", "key123", "local123"):
        assert secret not in serialized
    assert "ok" in serialized


def test_nanosecond_source_identity_is_not_rounded() -> None:
    first = event("failed", level="error")
    a = replace(
        first,
        line=replace(first.line, source_timestamp="2026-10-07T12:00:00.123456001Z"),
    )
    b = replace(
        first,
        line=replace(first.line, source_timestamp="2026-10-07T12:00:00.123456002Z"),
    )
    left, right = normalized(a), normalized(b)
    assert left is not None and right is not None
    assert left.id != right.id


def test_structured_exception_without_header_is_captured() -> None:
    result = normalized(event("retrying", "ValueError: invalid", level="warning"))
    assert result is not None
    assert result.exception_type == "ValueError"


def test_bounded_record_keeps_normal_log_text() -> None:
    from app.core.log_records import LogAssembler

    assembly = LogAssembler(max_bytes=128)
    raw = json.dumps({"event": "failed", "level": "error", "exception": "x" * 500})
    assembly.feed("one", parse_log_line(raw, "stdout"), now=0)
    result = normalized(assembly.flush()[0])
    assert result is not None and result.truncated and result.incomplete


def test_indented_message_fields_do_not_make_a_warning_an_exception() -> None:
    assembly = LogAssembler()
    assembly.feed("one", parse_log_line("WARNING: Slow query", "stderr"), now=0)
    assembly.feed("one", parse_log_line("    Duration: 50ms", "stderr"), now=0)
    assert normalized(assembly.flush()[0]) is None


def test_redaction_of_a_truncated_nested_field() -> None:
    from app.services.system.errors.redact import fields

    payload = fields(
        (("context", '{"api_key": "sensitive-value", "large": "unfinished'),)
    )
    assert "sensitive-value" not in json.dumps(payload)


def test_indented_fields_on_error_do_not_invent_a_traceback() -> None:
    assembly = LogAssembler()
    assembly.feed("one", parse_log_line("ERROR: failed", "stderr"), now=0)
    assembly.feed("one", parse_log_line("    Duration: 50ms", "stderr"), now=0)
    occurrence = normalized(assembly.flush()[0])
    assert occurrence is not None
    assert occurrence.exception_type is None and occurrence.traceback is None


def test_exception_without_frames_keeps_meaningful_cause_text() -> None:
    first = normalized(
        event("operation failed", "ValueError: invalid invoice", level="error")
    )
    second = normalized(
        event("operation failed", "ValueError: invalid address", level="error")
    )
    assert first is not None and second is not None
    assert first.fingerprint != second.fingerprint


def test_console_timestamp_and_level_prefix_do_not_split_message_only_errors() -> None:
    results = []
    for stamp in ("2026-10-07 12:00:01", "2026-10-07 12:00:02"):
        assembly = LogAssembler()
        assembly.feed(
            "one",
            parse_log_line(stamp + " [error    ] connection refused", "stdout"),
            now=0,
        )
        result = normalized(assembly.flush()[0])
        assert result is not None
        results.append(result)
    assert results[0].fingerprint == results[1].fingerprint
    assert results[0].message == "connection refused"


def test_service_attribution_changes_grouping_without_changing_replay_identity() -> (
    None
):
    record = event("shared helper failed", level="error", app_service="ai")
    first = normalized(record)
    other = normalized(event("shared helper failed", level="error", app_service="auth"))
    legacy = normalized(event("shared helper failed", level="error"))
    assert first is not None and other is not None and legacy is not None
    assert first.app_service == "ai"
    assert first.fingerprint != other.fingerprint
    assert normalized(record).id == first.id
    assert legacy.app_service is None


def test_a_console_errors_message_leaves_its_attribution_out() -> None:
    """The development console prints ``app_service=… pathname=…`` after the
    message: fields, not words to group or search by."""
    assembly = LogAssembler()
    line = "2026-10-03 20:45:01 [error    ] Charge failed [app.core.log] app_service=payment pathname=/code/app/services/payment/charge.py"
    assembly.feed("container-id", parse_log_line(line, "stderr"), now=0)
    result = normalized(assembly.flush()[0])
    assert result is not None
    assert "pathname" not in result.message and "app_service" not in result.message
    assert result.fields["pathname"] == "/code/app/services/payment/charge.py"


@pytest.mark.parametrize(
    ("raw", "kept", "gone"),
    [
        # Every named credential is masked when assigned in prose too.
        (
            "refresh failed credential=abc123 retrying",
            "credential=[redacted]",
            "abc123",
        ),
        # A connection URL's password, by the app's one rule (``hide_password``).
        (
            "cannot reach postgresql://app:hunter2@db:5432/app",
            "postgresql://app:***@db:5432/app",
            "hunter2",
        ),
    ],
)
def test_free_text_hides_credentials(raw: str, kept: str, gone: str) -> None:
    from app.services.system.errors.redact import text

    assert kept in text(raw) and gone not in text(raw)
