"""Jinja2 filters: the only place templates format money, dates, percents.

Registered on the environment by ``rendering.py``. Amounts arrive from the
finance service as integer minor units with a currency code.
"""

from collections.abc import Callable
from datetime import date, datetime

# Symbols for the codes a household ledger actually sees; anything else
# shows its code.
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
_ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW"}


def money(cents: int | None, currency: str = "USD") -> str:
    """Minor units -> ``-$1,234.56`` (the Flet register's ``_usd`` rule,
    widened to honour the currency code)."""
    code = (currency or "USD").upper()
    if code in _ZERO_DECIMAL_CURRENCIES:
        value, number = cents or 0, f"{abs(cents or 0):,}"
    else:
        value = (cents or 0) / 100
        number = f"{abs(value):,.2f}"
    sign = "-" if value < 0 else ""
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{sign}{symbol}{number}" if symbol else f"{sign}{code} {number}"


def short_date(value: date | datetime | str | None, today: date | None = None) -> str:
    """``Jul 15`` this year, ``Jul 15, 2025`` otherwise. Blank stays blank."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    label = f"{value:%b} {value.day}"
    if value.year == (today or date.today()).year:
        return label
    return f"{label}, {value.year}"


def pct(ratio: float | None, digits: int = 0) -> str:
    """A 0-1 ratio -> ``15%`` (``digits`` decimals). Blank stays blank."""
    if ratio is None:
        return ""
    return f"{ratio * 100:.{digits}f}%"


FILTERS: dict[str, Callable[..., str]] = {
    "money": money,
    "short_date": short_date,
    "pct": pct,
}
