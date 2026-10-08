"""Bounded per-source assembly, ordinals, and conservative resume positions.

The proxy refuses container inspect, so restart incarnation is unavailable.
Container ID plus original log timestamp/stream/ordinal identify retained input;
restarts keeping that ID are disambiguated by their source timestamps. Docker
rotation or a writer without timestamps makes recovery uncertain, not durable.
"""

from datetime import UTC, datetime

from app.core.log_records import LogAssembler, LogRecord, clip
from app.core.runtime import Instance, LogLine
from app.services.system.errors.models import MAX_PAYLOAD, ErrorOccurrence
from app.services.system.errors.normalize import normalize


def fit(event: ErrorOccurrence) -> ErrorOccurrence:
    """Halve the trace and message until the serialized record, JSON
    escaping and metadata included, fits ``MAX_PAYLOAD``."""
    if event.logger and len(event.logger.encode()) > 512:
        event = event.model_copy(
            update={"logger": clip(event.logger, 512), "truncated": True}
        )
    while len(event.model_dump_json().encode()) > MAX_PAYLOAD:
        trace = event.traceback or ""
        message = event.message
        event = event.model_copy(
            update={
                "traceback": clip(trace, len(trace.encode()) // 2) if trace else None,
                "message": clip(message, len(message.encode()) // 2),
                "fields": {},
                "truncated": True,
            }
        )
    return event


class SourceReader:
    def __init__(self, instance: Instance, page: str) -> None:
        self.instance, self.page = instance, page
        self.assembly = LogAssembler(max_bytes=48 * 1024)
        self.ordinals: dict[str, tuple[str | None, int]] = {}
        self.latest: datetime | None = None
        self.uncertain = False
        # The cursor last saved, and when (``Collector.commit``).
        self.saved: datetime | None = None
        self.saved_at = float("-inf")

    def feed(self, line: LogLine, *, now: float) -> list[ErrorOccurrence]:
        stamp, ordinal = self.ordinals.get(line.stream, (None, -1))
        ordinal = ordinal + 1 if stamp == line.source_timestamp else 0
        self.ordinals[line.stream] = (line.source_timestamp, ordinal)
        self.uncertain |= line.source_timestamp is None
        if line.timestamp is not None:
            self.latest = line.timestamp.replace(tzinfo=UTC)
        records = self.assembly.feed(self.instance.id, line, now=now, ordinal=ordinal)
        return self._events(records)

    def flush(self, *, now: float | None = None) -> list[ErrorOccurrence]:
        return self._events(self.assembly.flush(now=now))

    def resume_at(self) -> datetime | None:
        times = [
            record.line.timestamp.replace(tzinfo=UTC)
            for record in self.assembly.pending.values()
            if record.line.timestamp
        ]
        return min(times + [self.latest]) if self.latest else None

    def _events(self, records: list[LogRecord]) -> list[ErrorOccurrence]:
        events = []
        for record in records:
            event = normalize(
                record,
                page=self.page,
                service=self.instance.service,
                container_name=self.instance.name,
                ordinal=record.ordinal,
                observed_at=datetime.now(UTC),
            )
            if event is not None:
                events.append(fit(event))
        return events
