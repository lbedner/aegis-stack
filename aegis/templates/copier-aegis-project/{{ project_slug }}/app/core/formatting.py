"""Shared formatting utilities for display across CLI and frontend."""

from datetime import UTC, datetime


def format_number(num: int) -> str:
    """Format large numbers with commas (e.g., 1234567 -> '1,234,567')."""
    return f"{num:,}"


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
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 365:
        months = max(1, round(days / 30.44))
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = max(1, round(days / 365.25))
    return f"{years} year{'s' if years != 1 else ''} ago"


def format_relative_time(
    iso_str: str | None, *, now: datetime | None = None, coarse: bool = False
) -> str:
    """Format an ISO timestamp as a relative duration ("3 minutes ago").

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
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        if seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if coarse:
            return _coarse_age(seconds)
        return dt.strftime("%b %d %H:%M")
    except (ValueError, TypeError, IndexError):
        return str(iso_str)
