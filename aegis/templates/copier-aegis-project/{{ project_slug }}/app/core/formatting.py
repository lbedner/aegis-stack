"""Shared formatting utilities for display across CLI and frontend."""

from collections.abc import Iterable
from datetime import UTC, datetime
import re


def format_number(num: int) -> str:
    """Format large numbers with commas (e.g., 1234567 -> '1,234,567')."""
    return f"{num:,}"


def counted(count: int, noun: str, plural: str | None = None) -> str:
    """``count`` and its noun, singular for exactly one: ``1 draft``,
    ``2 drafts``; ``plural`` where it is not the noun and an s
    (``watches``)."""
    return f"{count} {noun if count == 1 else plural or noun + 's'}"


def format_cost(cost: float) -> str:
    """Format cost with dollar sign and appropriate decimal places.

    Uses 6 decimal places for tiny amounts (< $0.01) to show token-level
    pricing accurately, 4 decimal places otherwise for readability.
    """
    if cost < 0.01:
        return f"${cost:.6f}"
    return f"${cost:.4f}"


def format_percentage(pct: float) -> str:
    """Format percentage with one decimal place (e.g., 90.5%)."""
    return f"{pct:.1f}%"


def format_bytes(size: int | float) -> str:
    """A byte count in the unit that reads: "512 B", "9.0 MB", "3.0 GB"."""
    if size < 1024:
        return f"{int(size)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


def format_value(value: float, fmt: str | None) -> str:
    """A charted value as its chart reads it (``"percent"``, ``"bytes"``,
    ``"bytes_per_second"``, ``"money"``, plain otherwise): the twin of formatValue in charts.js,
    for the Flet charts drawing the same data."""
    if fmt == "percent":
        return format_percentage(value)
    if fmt == "bytes":
        return format_bytes(value)
    if fmt == "bytes_per_second":
        return f"{format_bytes(value)}/s"
    if fmt == "seconds":
        return f"{value:.1f} s" if value < 10 else f"{value:.0f} s"
    if fmt == "money":
        return f"{'-' if value < 0 else ''}${abs(value):,.2f}"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,}"


def format_date(value: object) -> str:
    """An ISO date (or ``date``) as "Aug 19, 2026". Blank stays blank.

    Anything unparseable is returned as-is rather than swallowed: a
    surprising string on screen is a better failure than a silently empty
    cell, and it points at the real bug instead of hiding it.
    """
    from datetime import date as _date
    from datetime import datetime as _datetime

    if value is None or value == "":
        return ""
    if isinstance(value, _datetime):
        value = value.date()
    if not isinstance(value, _date):
        try:
            value = _date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def _coarse_age(seconds: float) -> str:
    """Days / months / years for durations past the sub-day branches.

    Rounds to the NEAREST unit rather than truncating: six calendar
    months is 181 days, and ``int(181 / 30.44)`` is 5, so truncation
    reports a gap a whole month shorter than the one a calendar shows.
    Each unit still floors at 1, so a duration that reached this branch
    never reports as zero of anything.
    """
    days = int(seconds / 86400)
    if days < 30:
        return f"{counted(days, 'day')} ago"
    if days < 365:
        months = max(1, round(days / 30.44))
        return f"{counted(months, 'month')} ago"
    years = max(1, round(days / 365.25))
    return f"{counted(years, 'year')} ago"


# A moment by the clock (``Oct 06 14:05``): past a day, or wherever relative
# times would blur a burst of them into one.
CLOCK = "%b %d %H:%M"


def format_relative_time(
    iso_str: str | datetime | None,
    *,
    now: datetime | None = None,
    coarse: bool = False,
) -> str:
    """Format an ISO timestamp (or a datetime) as a relative duration
    ("3 minutes ago").

    Returns ``"—"`` for empty input. Sub-minute durations render as
    ``"just now"``. Anything a day or older falls back to a short
    absolute format (``"%b %d %H:%M"``). On parse failure the raw input
    is returned so the value stays debuggable in the UI rather than
    silently disappearing.

    ``coarse`` keeps counting in days, months and years past that point
    instead, for ages that are naturally measured in months (when a model
    was pulled, say) where an absolute timestamp answers a question
    nobody asked. Off by default, so existing callers are unaffected.

    Tolerates missing timezone (assumed UTC) and a trailing ``Z`` (which
    Python's ``fromisoformat`` rejects pre-3.11).

    ``now`` is exposed for testability; production callers pass it as
    ``None`` so we default to ``datetime.now(timezone.utc)``.
    """
    if not iso_str:
        return "—"
    try:
        if isinstance(iso_str, datetime):
            dt = iso_str
        else:
            ts = iso_str.replace("Z", "+00:00") if "Z" in iso_str else iso_str
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        now_dt = now if now is not None else datetime.now(UTC)
        seconds = (now_dt - dt).total_seconds()
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            mins = int(seconds / 60)
            return f"{counted(mins, 'minute')} ago"
        if seconds < 86400:
            hours = int(seconds / 3600)
            return f"{counted(hours, 'hour')} ago"
        if coarse:
            return _coarse_age(seconds)
        return dt.strftime(CLOCK)
    except (ValueError, TypeError, IndexError):
        return str(iso_str)


def slugify(value: str) -> str:
    """Lowercase, hyphen-separated, ASCII; empty when nothing survives."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


# When a scheduled thing next runs, and how long a run took: shared by the
# Flet dashboard and the web Overseer.
def format_next_run_time(iso_time_str: str) -> str:
    """
    Format ISO datetime string to human readable relative time.

    Generic utility that can be used by any component card/modal to display
    upcoming execution times in a user-friendly format.

    Args:
        iso_time_str: ISO 8601 formatted datetime string (with or without timezone)

    Returns:
        Human-readable relative time string ("in 2h", "in 3d", "Past due", etc.)
        Returns "Unknown" if parsing fails or input is empty
    """
    from datetime import UTC, datetime

    from app.core.log import logger

    if not iso_time_str:
        return "Unknown"

    try:
        # Handle both timezone-aware and naive datetimes
        if iso_time_str.endswith("Z"):
            next_run = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
        elif "+" in iso_time_str or iso_time_str.endswith("00:00"):
            next_run = datetime.fromisoformat(iso_time_str)
        else:
            # Assume UTC if no timezone info
            next_run = datetime.fromisoformat(iso_time_str).replace(tzinfo=UTC)

        now = datetime.now(UTC)

        # Make sure both datetimes are timezone-aware
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        delta = next_run - now
        total_seconds = delta.total_seconds()

        if total_seconds < 0:
            return "Past due"
        elif total_seconds < 60:
            return f"in {int(total_seconds)}s"
        elif total_seconds < 3600:
            minutes = int(total_seconds / 60)
            return f"in {minutes}m"
        elif total_seconds < 86400:
            hours = total_seconds / 3600
            if hours < 2:
                return f"in {hours:.1f}h"
            else:
                return f"in {int(hours)}h"
        else:
            days = int(total_seconds / 86400)
            return f"in {days}d"
    except Exception as e:
        logger.debug(f"Failed to format next run time '{iso_time_str}': {e}")
        return "Unknown"


def format_schedule_human_readable(schedule: str) -> str:
    """
    Convert schedule format to human readable description.

    Generic utility that can be used by any component card/modal to display
    scheduling patterns in a user-friendly format.

    Args:
        schedule: Schedule string (typically from APScheduler or similar)

    Returns:
        Human-readable schedule description ("Daily at 2:00 AM UTC", etc.)
        Returns original schedule string if no pattern matches
        Returns "Unknown schedule" for empty/invalid input
    """
    import re

    from app.core.log import logger

    if not schedule or "Unknown" in schedule:
        return "Unknown schedule"

    # Handle common cron patterns
    if "hour=2, minute=0, second=0" in schedule:
        return "Daily at 2:00 AM UTC"
    elif "hour=" in schedule and "minute=" in schedule:
        # Extract hour and minute from the schedule string
        try:
            hour_match = re.search(r"hour=([0-9]+)", schedule)
            minute_match = re.search(r"minute=([0-9]+)", schedule)
            if hour_match and minute_match:
                hour = int(hour_match.group(1))
                minute = int(minute_match.group(1))
                time_str = f"{hour:02d}:{minute:02d}"
                return f"Daily at {time_str} UTC"
        except Exception as e:
            logger.debug(f"Failed to parse schedule pattern '{schedule}': {e}")

    # Fallback to original schedule
    return schedule


def format_duration_ms(duration_ms: int | float | str | None) -> str:
    """Format milliseconds to human-readable duration (e.g., '1.2s', '3m 45s')."""
    if not duration_ms:
        return "\u2014"
    try:
        ms = float(duration_ms)
        if ms < 1000:
            return f"{ms:.0f}ms"
        s = ms / 1000
        if s < 60:
            return f"{s:.1f}s"
        m = int(s // 60)
        s = s % 60
        return f"{m}m {s:.0f}s"
    except (ValueError, TypeError):
        return "\u2014"


def format_timestamp(iso_str: str | None) -> str:
    """Format ISO timestamp for display (HH:MM:SS)."""
    if not iso_str:
        return "\u2014"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "\u2014"


def format_span(seconds: float | None) -> str | None:
    """A length of time in its two largest units: ``90061`` -> ``"1d 1h"``."""
    if seconds is None or seconds < 0:
        return None
    seconds = int(seconds)
    units = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
    parts = []
    for label, size in units:
        if seconds >= size or (label == "s" and not parts):
            parts.append(f"{seconds // size}{label}")
            seconds %= size
        if len(parts) == 2:
            break
    return " ".join(parts)


# Anything that could end a header line or a quoted filename.
_UNSAFE_FILENAME = re.compile(r'[\r\n"\\]+')


def safe_filename(name: str, fallback: str = "document") -> str:
    """A name safe inside ``Content-Disposition: ...; filename="..."``.

    The name is often user input (a document title, an object key), so a
    stray newline there is header injection, not a formatting nuisance.
    """
    return _UNSAFE_FILENAME.sub("", name).strip() or fallback


def is_local_path(target: str | None) -> bool:
    """Whether ``target`` is a path on this site, the only thing a ``next``
    or a redirect may send someone to: it starts with one ``/``, and holds
    no backslash (browsers read ``/\\host`` as ``//host``, off the site)."""
    return bool(
        target
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
    )


def row_matches(query: str, values: Iterable[object]) -> bool:
    """Does this row match a search box, looking at EVERY column?

    Callers pass the same values they render, so the rule stays "if you
    can see it, you can search it" without this needing to know their
    shapes. Something that pages searches server-side instead.
    """
    needle = (query or "").strip().casefold()
    if not needle:
        return True
    return any(needle in str(value).casefold() for value in values if value is not None)


def split_matches(text: str, query: str) -> list[tuple[str, bool]]:
    """``text`` as runs, each marked True where it matches ``query`` (any
    case): what a UI highlights for a search."""
    if not query:
        return [(text, False)]
    runs: list[tuple[str, bool]] = []
    at = 0
    for match in re.finditer(re.escape(query), text, re.IGNORECASE):
        if match.start() > at:
            runs.append((text[at : match.start()], False))
        runs.append((match.group(), True))
        at = match.end()
    if at < len(text):
        runs.append((text[at:], False))
    return runs or [(text, False)]
