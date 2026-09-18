"""Jinja2 filters: the only place templates format money, dates, percents.

Registered on the environment by ``rendering.py``. Amounts arrive from the
finance service as integer minor units with a currency code.
"""

import html
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from markupsafe import Markup

# Symbols for the codes a household ledger actually sees; anything else
# shows its code.
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
_ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW"}


def _utc_today() -> date:
    """Today in UTC, the clock the rest of the app stamps rows with.

    Spelled out rather than imported from a service: the web frontend
    ships in projects that have none of them.
    """
    return datetime.now(UTC).date()


def money(cents: int | None, currency: str = "USD", whole: bool = False) -> str:
    """Minor units -> ``-$1,234.56`` (the Flet register's ``_usd`` rule,
    widened to honour the currency code).

    ``whole`` rounds the cents away for somewhere they are noise rather
    than precision - a projected month chip reading ``Nov $4,208``. It is
    the only reason to format money any other way, which is why it lives
    here instead of in the f-string that wanted it: hand-rolled
    ``f"${cents / 100:,.2f}"`` ignores the currency and will print a GBP
    figure with a dollar sign.
    """
    code = (currency or "USD").upper()
    if code in _ZERO_DECIMAL_CURRENCIES:
        value, number = cents or 0, f"{abs(cents or 0):,}"
    elif whole:
        value = (cents or 0) / 100
        number = f"{abs(round(value)):,}"
    else:
        value = (cents or 0) / 100
        number = f"{abs(value):,.2f}"
    sign = "-" if value < 0 else ""
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{sign}{symbol}{number}" if symbol else f"{sign}{code} {number}"


def dollars(cents: int | None) -> float:
    """Minor units as dollars, for a chart's SCALE.

    Charts are drawn in dollars. Cents on the axis draw a $711,200 house
    at seventy million, and the mistake is invisible until a chart has a
    figure somebody knows by heart - so the conversion has one home
    rather than a ``/ 100`` in every series that gets written.
    """
    return (cents or 0) / 100


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
    if value.year == (today or _utc_today()).year:
        return label
    return f"{label}, {value.year}"


def pct(ratio: float | None, digits: int = 0) -> str:
    """A 0-1 ratio -> ``15%`` (``digits`` decimals). Blank stays blank."""
    if ratio is None:
        return ""
    return f"{ratio * 100:.{digits}f}%"


def cents_to_input(cents: int | None) -> str:
    """The inverse of ``money_to_cents`` for form values: ``350,000.00``."""
    return "" if cents is None else f"{cents / 100:,.2f}"


def money_to_cents(raw: str | None) -> int | None:
    """``"$1,200.50"`` / ``"3,000"`` / ``" 12 "`` -> cents; blank -> 0;
    anything else -> ``None`` (the caller decides that is a 422)."""
    cleaned = (raw or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return None


# A settled assistant message is markdown written by a model. marko renders
# it (GFM: tables, strikethrough, autolinks); raw HTML in the source is
# escaped rather than passed through, so the model can format but never
# inject markup. The mixin is registered LAST so it sits first in the
# renderer's MRO, ahead of GFM's own tag filter.
#
# Built once at import: marko compiles its parser and renderer per
# ``Markdown()``, and a chat thread renders one of these per message.
def _safe_markdown() -> Any:
    from marko import Markdown
    from marko.ext.gfm import GFM
    from marko.helpers import MarkoExtension

    class EscapeHTML:
        def render_html_block(self, element: Any) -> str:
            return html.escape(element.body)

        def render_inline_html(self, element: Any) -> str:
            return html.escape(element.children)

    return Markdown(extensions=[GFM, MarkoExtension(renderer_mixins=[EscapeHTML])])


_MARKDOWN = _safe_markdown()


def markdown(text: str | None) -> Markup:
    """Model markdown as HTML, with any raw HTML in it escaped.

    The one renderer for anything a model wrote: chat replies, generated
    reports, long-form fields. Rendering markdown in the browser instead
    means a second, weaker implementation drifting from this one, and the
    escaping has to be re-earned there.
    """
    return Markup(_MARKDOWN.convert(text or ""))


# Tailwind classes for a block of rendered markdown. One string, because a
# heading that looks different in chat than it does in a report is a bug
# nobody files and everybody notices.
PROSE_CLASSES = (
    "text-sm leading-relaxed [&_p]:my-2 "
    "[&_h1]:text-xl [&_h1]:font-semibold [&_h1]:mt-5 [&_h1]:mb-2 "
    "[&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2 "
    "[&_h3]:font-semibold [&_h3]:mt-4 [&_h3]:mb-1 "
    "[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-2 "
    "[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-2 [&_li]:my-0.5 "
    "[&_strong]:font-semibold "
    "[&_code]:font-mono [&_code]:text-xs "
    "[&_pre]:rounded [&_pre]:border [&_pre]:p-3 [&_pre]:my-2 "
    "[&_pre]:overflow-x-auto "
    "[&_table]:my-2 [&_th]:text-left [&_th]:font-medium [&_th]:pr-4 "
    "[&_td]:pr-4 [&_td]:py-0.5 "
    "[&_a]:underline "
    "[&_blockquote]:border-l-2 [&_blockquote]:pl-3"
)


FILTERS: dict[str, Callable[..., str]] = {
    "money": money,
    "cents_to_input": cents_to_input,
    "short_date": short_date,
    "pct": pct,
    "markdown": markdown,
}
