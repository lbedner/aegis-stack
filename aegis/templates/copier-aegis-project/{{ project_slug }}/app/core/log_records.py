"""Bounded log records shared by Logs and continuous error collection.

Call feed per line, flush(now=monotonic_time) on idle ticks, and flush(source)
on EOF. Source must identify a container incarnation; stdout/stderr remain
separate. A flush does not promise a complete traceback: incomplete records
are marked. Console parsing is best effort; structured traces are preferred.
"""

from dataclasses import dataclass, replace
import hashlib
import re

from app.core.runtime import LogLine

# A plain line's lead that the time cell and level tag already show: a date
# and time (an optional zone after it), a bare time, or a level tag, then
# any bracketed groups (logger, process) up to the message.
_LEAD = re.compile(
    r"^(?:\[?\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?(?-i:Z| ?[A-Z]{2,4}\b)?\]?"
    r"|\[\d\d:\d\d:\d\d\]"
    r"|(?:debug|info|warn|warning|error|critical)\s*:)"
    r"\s*(?:\[[^\]]*\]\s*)*",
    re.IGNORECASE,
)


def split_lead(text: str) -> tuple[str, str]:
    """Parse a console log header into its metadata prefix and message."""
    lead = _LEAD.match(text)
    if lead is None or not text[lead.end() :].strip():
        return "", text
    return lead.group(), text[lead.end() :]


HEADERS = (
    "Traceback (most recent call last)",
    "Exception Group Traceback",
    "During handling of the above exception",
    "The above exception was the direct cause",
)
TERMINAL = re.compile(r"^(?:\s*[|+]\s*)?([A-Za-z_][\w.]*)(?::(?: |$)|$)")


def trace_start(text: str) -> bool:
    return text.lstrip(" |+").startswith(HEADERS)


def clip(text: str, size: int) -> str:
    return text.encode()[: max(0, size)].decode(errors="ignore")


@dataclass
class LogRecord:
    source: str
    line: LogLine
    trace: str | None = None
    truncated: bool = False
    incomplete: bool = False
    input_digest: str = ""
    touched: float = 0.0
    structured_trace: bool = False
    ordinal: int = 0

    @property
    def recognized(self) -> bool:
        """Whether its trace is an exception's, not indented lines folded in
        for Logs (a warning's source line, a pretty-printed dict)."""
        return bool(
            self.trace
            and any(
                trace_start(part) or (self.structured_trace and TERMINAL.match(part))
                for part in self.trace.splitlines()
            )
        )

    def continues(self, line: LogLine) -> bool:
        if line.level is not None or line.event is not None:
            return False
        text = line.text
        if (
            self.trace
            and not self.incomplete
            and text.lstrip(" |+").startswith(
                ("Traceback (", "Exception Group Traceback")
            )
        ):
            return False
        return bool(
            (not text.strip() and self.trace)
            or (text and text[0].isspace())
            or trace_start(text)
            or (self.trace and self.incomplete and TERMINAL.match(text))
        )


class LogAssembler:
    """One bounded pending record per source/stream; caller bounds source count."""

    def __init__(
        self, max_bytes: int | None = 65536, idle_seconds: float = 0.5
    ) -> None:
        if (max_bytes is not None and max_bytes < 1) or idle_seconds < 0:
            raise ValueError(
                "Positive payload size and nonnegative idle interval required"
            )
        self.max_bytes = max_bytes
        self.idle_seconds = idle_seconds
        self.pending: dict[tuple[str, str], LogRecord] = {}

    def feed(
        self, source: str, line: LogLine, *, now: float, ordinal: int = 0
    ) -> list[LogRecord]:
        key = source, line.stream
        last = self.pending.get(key)
        if last is not None and last.continues(line):
            self._append(last, line.text)
            last.touched = now
            return []
        ready = [self.pending.pop(key)] if last else []
        if line.text.strip():
            self.pending[key] = self._new(source, line, now)
            self.pending[key].ordinal = ordinal
        return ready

    def _new(self, source: str, line: LogLine, now: float) -> LogRecord:
        if self.max_bytes is None:
            record = LogRecord(
                source, line, line.trace, touched=now, structured_trace=bool(line.trace)
            )
            if record.trace is None and trace_start(line.text):
                record.trace = line.text
            self._complete(record)
            return record
        remaining = self.max_bytes
        truncated = False

        def take(text: str) -> str:
            nonlocal remaining, truncated
            kept = clip(text, remaining)
            remaining -= len(kept.encode())
            truncated |= kept != text
            return kept

        # Keep the semantic message and trace first, then auxiliary fields.
        event = take(line.event) if line.event is not None else None
        text = take(line.text) if event is None else event
        trace = take(line.trace) if line.trace else None
        fields = tuple((take(k), take(v)) for k, v in line.fields if remaining > 0)
        truncated |= len(fields) != len(line.fields)
        bounded = replace(line, text=text, event=event, trace=None, fields=fields)
        record = LogRecord(
            source,
            bounded,
            trace,
            truncated,
            input_digest=hashlib.sha256(line.text.encode()).hexdigest(),
            touched=now,
            structured_trace=bool(line.trace),
        )
        if trace is None and trace_start(line.text):
            record.trace = text
            record.line = replace(bounded, text="", event="Traceback")
        self._complete(record)
        return record

    def _append(self, record: LogRecord, text: str) -> None:
        used = len(record.line.text.encode()) + len((record.trace or "").encode())
        used += sum(len(k.encode()) + len(v.encode()) for k, v in record.line.fields)
        addition = ("\n" if record.trace else "") + text
        kept = (
            addition
            if self.max_bytes is None
            else clip(addition, self.max_bytes - used)
        )
        record.trace = (record.trace or "") + kept
        record.truncated |= kept != addition
        self._complete(record)

    @staticmethod
    def _complete(record: LogRecord) -> None:
        if record.line.level is None and record.recognized:
            # A record that carries a traceback failed, whatever its line
            # printed ("Running in Docker container..." before a crash).
            record.line = replace(record.line, level="error")
        text = (record.trace or "").rstrip()
        last = text.splitlines()[-1] if text else ""
        closed_group = last.strip().startswith("+") and set(last.strip()) <= {"+", "-"}
        record.incomplete = bool(text) and (
            record.truncated or not (TERMINAL.match(last) or closed_group)
        )

    def flush(
        self, source: str | None = None, *, now: float | None = None
    ) -> list[LogRecord]:
        keys = [
            key
            for key, record in self.pending.items()
            if (source is None or key[0] == source)
            and (now is None or now - record.touched >= self.idle_seconds)
        ]
        return [self.pending.pop(key) for key in keys]
