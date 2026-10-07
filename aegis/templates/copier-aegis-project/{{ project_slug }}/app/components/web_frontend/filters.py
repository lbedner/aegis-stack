"""Jinja2 filters: the only place templates format money, dates, percents.

Registered on the environment by ``rendering.py``. Amounts arrive from the
finance service as integer minor units with a currency code.
"""

from collections.abc import Callable, Iterable
from datetime import date, datetime
from functools import cache
import html
import re
from typing import Any

from markupsafe import Markup

from app.core.time import today as utc_today
from app.services.system.models import ComponentStatusType
from app.services.system.ui import get_status_color_name

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
    if value.year == (today or utc_today()).year:
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
# Fenced code is highlighted by Pygments (already installed with rich) for
# its language, or a guess without one. marko's own codehilite extension is
# not used: it passes ``key=value`` pairs from the fence line to Pygments'
# formatter, which lets model markdown turn on ``full`` or ``cssfile``. The
# formatter here takes no options from the text.
#
# Built once at import: marko compiles its parser and renderer per
# ``Markdown()``, and a chat thread renders one of these per message.
def _safe_markdown() -> Any:
    from marko import Markdown
    from marko.ext.gfm import GFM
    from marko.helpers import MarkoExtension
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.util import ClassNotFound

    class EscapeHTML:
        def render_html_block(self, element: Any) -> str:
            return html.escape(element.body)

        def render_inline_html(self, element: Any) -> str:
            return html.escape(element.children)

    class Highlight:
        def render_fenced_code(self, element: Any) -> str:
            code = element.children[0].children
            try:
                lexer = (
                    get_lexer_by_name(element.lang)
                    if element.lang
                    else guess_lexer(code)
                )
            except ClassNotFound:
                lexer = guess_lexer(code)
            return highlight(code, lexer, HtmlFormatter())

    return Markdown(
        extensions=[GFM, MarkoExtension(renderer_mixins=[Highlight, EscapeHTML])]
    )


_MARKDOWN = _safe_markdown()


def markdown(text: str | None) -> Markup:
    """Model markdown as HTML, with any raw HTML in it escaped.

    The one renderer for anything a model wrote: chat replies, generated
    reports, long-form fields. Rendering markdown in the browser instead
    means a second, weaker implementation drifting from this one, and the
    escaping has to be re-earned there.
    """
    return Markup(_MARKDOWN.convert(text or ""))


_RST_LITERAL = re.compile(r"``(.+?)``")
# A literal set as code, in the accent: a docstring's, a message's names.
_LITERAL = '<code class="font-mono text-aegis-teal">{}</code>'
# An upper-case name, as settings and secrets are (``STRIPE_SECRET_KEY``).
_NAME = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def docstring(text: str | None) -> Markup:
    """A docstring as HTML: escaped, its RST ``literals`` set as code.

    Values that are already HTML (``Markup``) pass through as given.
    """
    if isinstance(text, Markup):
        return text
    escaped = html.escape(text or "", quote=False)
    return Markup(_RST_LITERAL.sub(lambda m: _LITERAL.format(m.group(1)), escaped))


def message(text: str | None) -> Markup:
    """A health check's message as HTML: escaped, every setting or secret
    it names (``STRIPE_SECRET_KEY not configured``) set as code, as a
    docstring's literals are. An upper-case word nothing declares (``OK``)
    is left alone."""
    known = _declared_names()
    escaped = html.escape(text or "", quote=False)
    return Markup(
        _NAME.sub(lambda m: _LITERAL.format(m[0]) if m[0] in known else m[0], escaped)
    )


@cache
def _declared_names() -> frozenset[str]:
    """Every setting and declared secret, by name: code, so read once."""
    from app.core import secrets
    from app.core.config import settings

    names = {entry.name for entry in secrets.declared()}
    return frozenset(names | set(type(settings).model_fields))


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


_WORST_FIRST = ("error", "warn")


def worst_tone(tones: Iterable[str]) -> str:
    """The worst of ``tones``: error, then warn, else ok."""
    found = set(tones)
    return next((tone for tone in _WORST_FIRST if tone in found), "ok")


def health_tone(state: str) -> str:
    """The badge tone for a health status value."""
    try:
        return color_tone(get_status_color_name(ComponentStatusType(state)))
    except ValueError:
        return "muted"


FILTERS: dict[str, Callable[..., Any]] = {
    "money": money,
    "dollars": dollars,
    "cents_to_input": cents_to_input,
    "short_date": short_date,
    "pct": pct,
    "markdown": markdown,
    "docstring": docstring,
    "message": message,
    "health_tone": health_tone,
    "color_tone": color_tone,
}
