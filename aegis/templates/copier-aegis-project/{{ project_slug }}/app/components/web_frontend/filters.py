"""Jinja2 filters: the only place templates format money, dates, percents.

Registered on the environment by ``rendering.py``. Amounts arrive from the
finance service as integer minor units with a currency code.
"""

from collections.abc import Callable, Iterable
import re
from typing import Any

from app.core.formatting import counted, format_value
from app.core.money import dollars
from app.core.time import short_date
from app.services.system.models import ComponentStatusType
from app.services.system.ui import get_status_color_name

from .markup import LINE_ANCHOR as LINE_ANCHOR
from .markup import code, docstring, highlight, markdown, message

# Symbols for the codes a household ledger actually sees; anything else
# shows its code.
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
_ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW"}


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


def pct(ratio: float | None, digits: int = 0) -> str:
    """A 0-1 ratio -> ``15%`` (``digits`` decimals). Blank stays blank."""
    if ratio is None:
        return ""
    return f"{ratio * 100:.{digits}f}%"


def figure(value: float, unit: str) -> str:
    """A chat card's figure in its unit: money from cents, a percent (0 to
    100) as the charts read one, a count whole."""
    if unit == "money":
        return money(int(value))
    if unit == "percent":
        return format_value(value, "percent")
    return f"{round(value):,}"


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


# The web's badge tones for the shared semantic colours
# (``get_status_color_name``, ``ui_auth``), so a state reads the same here
# as on the CLI and the Flet dashboard.
_TONE_BY_COLOR = {"green": "ok", "yellow": "warn", "red": "error"}


def color_tone(color: str) -> str:
    """The badge tone (ok, warn, error, muted) for a semantic colour name."""
    return _TONE_BY_COLOR.get(color, "muted")


# A badge's tones, what wants a look first.
LOUDEST = ("error", "warn", "accent", "muted", "ok")
_WORST_FIRST = LOUDEST[:2]


def loudness(tone: str) -> int:
    """Where a tone stands among ``LOUDEST``, to sort by; one it does not
    know comes last."""
    return LOUDEST.index(tone) if tone in LOUDEST else len(LOUDEST)


# What a ``pattern`` attribute escapes: the browser compiles it with the v
# flag, where escaping anything else is a syntax error that drops the check.
_PATTERN_SYNTAX = re.compile(r"[\^$\\.*+?()[\]{}|/]")


def exactly(text: str) -> str:
    """A ``pattern`` attribute matching ``text`` and nothing else: a typed
    confirmation the browser holds its form for."""
    return _PATTERN_SYNTAX.sub(lambda found: "\\" + found.group(), text)


def worst_tone(tones: Iterable[str]) -> str:
    """The worst of ``tones``: error, then warn, else ok."""
    found = set(tones)
    return next((tone for tone in _WORST_FIRST if tone in found), "ok")


def answer_tone(status: int) -> str:
    """The tone of an HTTP answer: a failure (5xx) error, a refusal (4xx,
    the server working) warn, the rest ok."""
    return "error" if status >= 500 else "warn" if status >= 400 else "ok"


def button_attrs(attrs: str) -> str:
    """A button macro's extra attributes, refusing a ``type=``: the macro
    writes the button's type itself, and a second one is ignored by the
    browser, so a submit button would silently never submit."""
    if re.search(r"(^|\s)type\s*=", attrs):
        raise ValueError(f"pass type= as the macro's argument, not in attrs: {attrs!r}")
    return attrs


def health_tone(state: str) -> str:
    """The badge tone for a health status value."""
    try:
        return color_tone(get_status_color_name(ComponentStatusType(state)))
    except ValueError:
        return "muted"


FILTERS: dict[str, Callable[..., Any]] = {
    "money": money,
    "exactly": exactly,
    "dollars": dollars,
    "cents_to_input": cents_to_input,
    "short_date": short_date,
    "pct": pct,
    "figure": figure,
    "markdown": markdown,
    "highlight": highlight,
    "code": code,
    "docstring": docstring,
    "message": message,
    "health_tone": health_tone,
    "answer_tone": answer_tone,
    "counted": counted,
    "color_tone": color_tone,
    "button_attrs": button_attrs,
}
