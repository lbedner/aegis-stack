"""How money and dates read in this modal.

Amounts arrive from the provider in cents, and timestamps in three
shapes depending on which endpoint answered. Four rules, each used by
at least one tab, kept together so a change to how a dollar reads
happens once.
"""

from datetime import datetime


def _fmt_amount(amount_cents: int, currency: str = "usd") -> str:
    """Render a cents amount as a currency string."""
    symbol = "$" if currency.lower() == "usd" else ""
    suffix = "" if symbol else currency.upper()
    return f"{symbol}{amount_cents / 100:,.2f} {suffix}".strip()


def _fmt_datetime(iso_str: str | None) -> str:
    """Render an ISO datetime string as a compact display string."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str


def _fmt_date(iso_str: str | None) -> str:
    """Render an ISO datetime string as a date-only display string."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_str


def _short_date(iso: str) -> str:
    """Render ``2026-04-22`` as ``Apr 22``."""
    try:
        return datetime.fromisoformat(iso).strftime("%b %d")
    except ValueError:
        return iso
