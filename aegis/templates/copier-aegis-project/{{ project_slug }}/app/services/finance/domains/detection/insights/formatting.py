"""Turning figures and dates into the shapes an insight body quotes.

Pure functions over cents, basis points, and calendar months. The
analyst's snapshot shares them with the rules on purpose: an alert and
the note describing it must never quote the same rate or the same month
two different ways.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.finance.models import FinanceLiabilityDetail


def format_usd(cents: int) -> str:
    return f"${abs(cents) / 100:,.2f}"


def format_apr(bps: int) -> str:
    """Basis points as a display percentage: 2999 -> '29.99%'."""
    return f"{bps / 100:.2f}%"


def card_apr_bps(detail: FinanceLiabilityDetail) -> int | None:
    """The account's headline APR in basis points.

    Prefers the purchase APR (the rate a carried card balance actually pays),
    falls back to the highest APR the provider reports, then to the flat
    ``interest_rate_bps`` a loan carries. Shared with the analyst snapshot so
    the alert and the context always quote the same rate.
    """
    best: int | None = None
    for entry in detail.aprs or []:
        bps = entry.get("apr_percentage_bps")
        if bps is None:
            continue
        if entry.get("apr_type") == "purchase_apr":
            return bps
        best = bps if best is None else max(best, bps)
    return best if best is not None else detail.interest_rate_bps


def month_key(day: date) -> str:
    """The ``YYYY-MM`` bucket a day falls in."""
    return f"{day.year:04d}-{day.month:02d}"


def month_start_before(day: date, months_back: int) -> date:
    """The first of the month ``months_back`` months before ``day``'s month."""
    year, month = day.year, day.month
    for _ in range(months_back):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return date(year, month, 1)


def days_in_month(day: date) -> int:
    """Days in ``day``'s own month."""
    first_next = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    return (first_next - day.replace(day=1)).days


def month_is_complete(day: date) -> bool:
    """Is ``day`` the last day of its own month?"""
    return (day + timedelta(days=1)).month != day.month


def pace_day(today: date) -> int | None:
    """The day-of-month prior months should be measured to, or ``None``.

    ``None`` on the last day of a month: there is nothing to pro-rate, and
    truncating whole months would understate the norm instead.
    """
    return None if month_is_complete(today) else today.day
