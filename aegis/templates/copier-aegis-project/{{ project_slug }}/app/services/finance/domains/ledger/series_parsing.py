"""Parsing a pasted valuation series.

Listing sites paste as a two-column table - a month and a rounded value
(``Aug 2026	$711.2K``) - while a CSV export gives ISO dates and plain
numbers. Both are the same series to a reader, so both parse here.

Every line must parse. A silently skipped row is an invisible dent in a
net-worth chart, and the person pasting has no way to notice it.
"""

from datetime import date
import re

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ),
        start=1,
    )
}

# Split ONCE: the amount keeps its own commas ($711,200.00), so only
# the first separator can be the column boundary.
_SEPARATOR = re.compile(r"[\t;]|\s{2,}|,")


def _parse_date(text: str) -> date:
    """``Aug 2026`` (first of the month) or any ISO date."""
    cleaned = text.strip()
    match = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{4})", cleaned)
    if match:
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month is None:
            raise ValueError(f"Unknown month in {text!r}.")
        return date(int(match.group(2)), month, 1)
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        raise ValueError(f"Cannot read a date from {text!r}.") from None


def _parse_value(text: str) -> int:
    """``$711.2K``, ``711,200``, ``711200.00`` -> cents."""
    cleaned = text.strip().replace("$", "").replace(",", "").replace("_", "")
    if not cleaned:
        raise ValueError("Missing value.")
    multiplier = 1.0
    if cleaned[-1] in "kK":
        multiplier, cleaned = 1_000.0, cleaned[:-1]
    elif cleaned[-1] in "mM":
        multiplier, cleaned = 1_000_000.0, cleaned[:-1]
    try:
        amount = float(cleaned) * multiplier
    except ValueError:
        raise ValueError(f"Cannot read an amount from {text!r}.") from None
    return round(amount * 100)


def parse_series_lines(text: str) -> list[tuple[date, int]]:
    """Parse the block, newest-or-oldest-first, into (date, cents) rows.

    A header line (``Date	This home``) is skipped; anything else that
    fails to parse raises, naming the line.
    """
    rows: list[tuple[date, int]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in _SEPARATOR.split(line, maxsplit=1)]
        if len(parts) < 2 or not parts[1]:
            raise ValueError(f"Expected a date and a value: {raw!r}")
        try:
            parsed_date = _parse_date(parts[0])
        except ValueError:
            if not rows:
                continue  # a header row, before any data
            raise
        rows.append((parsed_date, _parse_value(parts[1])))
    if not rows:
        raise ValueError("No valuations found in that text.")
    return rows
