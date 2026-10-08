"""Convert assembled records into safe error occurrences, without I/O."""

from datetime import UTC, datetime

from app.core.log_records import TERMINAL, LogRecord, split_lead, trace_start
from app.core.runtime import without_metadata

from . import redact
from .fingerprint import digest, fingerprint
from .models import ErrorOccurrence


def normalize(
    record: LogRecord,
    *,
    page: str,
    service: str,
    container_name: str,
    ordinal: int,
    observed_at: datetime,
) -> ErrorOccurrence | None:
    line = record.line
    trace = record.trace
    recognized = bool(
        trace
        and any(
            trace_start(part) or (record.structured_trace and TERMINAL.match(part))
            for part in trace.splitlines()
        )
    )
    if line.level not in {"error", "critical"} and not recognized:
        return None
    # Indented log metadata is folded for Logs compatibility, but is not
    # evidence of an exception in a retained occurrence.
    if not recognized and not record.structured_trace:
        trace = None
    fields = redact.fields(line.fields)
    message = redact.text(
        line.event
        if line.event is not None
        else without_metadata(split_lead(line.text)[1])
    )
    trace = redact.text(trace) if trace else None
    types = [
        match.group(1)
        for part in (trace or "").splitlines()
        if (match := TERMINAL.match(part))
    ]
    exception = types[-1] if types else None
    logger = fields.get("logger")
    timestamp = line.timestamp or observed_at
    timestamp = (
        timestamp.replace(tzinfo=UTC)
        if timestamp.tzinfo is None
        else timestamp.astimezone(UTC)
    )
    identity = [
        record.source,
        line.stream,
        line.source_timestamp or timestamp.isoformat(),
        ordinal,
        record.input_digest,
    ]
    app_service = fields.get("app_service")
    return ErrorOccurrence(
        app_service=app_service,
        id=digest(identity),
        fingerprint=fingerprint(
            service, page, exception, trace, logger, message, app_service
        ),
        timestamp=timestamp,
        source_timestamp=line.source_timestamp,
        ordinal=ordinal,
        page=page,
        service=service,
        container_id=record.source,
        container_name=container_name,
        stream=line.stream,
        level=line.level or "error",
        logger=logger,
        message=message,
        exception_type=exception,
        traceback=trace,
        fields=fields,
        truncated=record.truncated,
        incomplete=record.incomplete,
    )
