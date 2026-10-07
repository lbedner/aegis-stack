"""The Overseer AI page's Costs section: the money view beside Usage.

Four tabs, each its own URL (``?tab=``): Overview, Users, Projections and
Breakdown. A month picker (``?month=YYYY-MM``) rides every tab that reads a
month; Projections looks ahead from today instead. This module does the
reading (the usage ledgers through ``domains/spend/queries.py``) and the
routing; ``overseer_ai_costs_views`` shapes what each tab shows. Needs a
persistence backend.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core.time import today
from app.services.ai.domains.llm import queries as llm_queries
from app.services.ai.domains.spend import queries
from app.services.ai.domains.spend.schemas import ActionSpend, ModelSpend, SpendLedger

from . import overseer_ai_costs_views as views
from .chat_surface import HAS_VOICE
from .overseer_access import user_names
from .overseer_ai_common import section_url

TABS = {
    "overview": "Overview",
    "users": "Users",
    "projections": "Projections",
    "breakdown": "Breakdown",
}
# Tabs that read one month; Projections reads the last 90 days from today.
MONTH_TABS = ("overview", "users", "breakdown")
MONTHS_SHOWN = 12


# --- Reads ---------------------------------------------------------------------


async def ledger(db: Any, start: datetime, end: datetime) -> SpendLedger:
    """Every figure a report needs for ``[start, end)``, on one session."""
    models = await llm_queries.usage_by_model(
        db, user_id=None, start_time=start, end_time=end
    )
    return SpendLedger(
        daily=await queries.daily_spend(db, start, end),
        actions=await queries.spend_by_action(db, start, end),
        users=await queries.spenders(db, start, end),
        models=[
            ModelSpend(model_id=m.model_id, title=m.title, cost=float(m.cost))
            for m in models
        ],
        voice=await queries.voice_spend(db, start, end) if HAS_VOICE else {},
    )


async def first_call(db: Any) -> datetime | None:
    return await queries.first_call(db)


async def user_spend(
    db: Any, start: datetime, end: datetime
) -> dict[str | None, dict[str, ActionSpend]]:
    return await queries.spend_by_user_action(db, start, end)


# --- Month and tab -------------------------------------------------------------


def _month(raw: str | None, now: date) -> date:
    """The first of the chosen month, or of this one."""
    try:
        return datetime.strptime(raw or "", "%Y-%m").date().replace(day=1)
    except ValueError:
        return now.replace(day=1)


def _next_month(first: date) -> date:
    return (first + timedelta(days=32)).replace(day=1)


def _months(first_seen: datetime | None, now: date) -> list[date]:
    """The months the ledger covers, newest first, and always this one."""
    oldest = first_seen.date().replace(day=1) if first_seen else now.replace(day=1)
    months, cursor = [], now.replace(day=1)
    while cursor >= oldest and len(months) < MONTHS_SHOWN:
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return months


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _horizon(raw: str | None) -> int:
    picked = int(raw) if raw and raw.isdigit() else 0
    return picked if picked in views.HORIZONS else views.HORIZONS[1]


def _url(tab: str, **query: str | None) -> str:
    """A Costs URL: the Overview is the section's own address."""
    return section_url("costs", tab=None if tab == "overview" else tab, **query)


async def _frame(
    db: Any, tab: str, month: date, now: date, query: Any
) -> dict[str, Any]:
    """What every tab shares: the tab row, and the month row where the tab
    reads one, each keeping the other's choice in its URL."""
    picked = query.get("month")
    horizon = _horizon(query.get("horizon"))
    months = _months(await first_call(db), now) if tab in MONTH_TABS else []
    return {
        "tab": tab,
        "tabs": [
            {"label": label, "url": _url(key, month=picked), "active": key == tab}
            for key, label in TABS.items()
        ],
        "month_label": month.strftime("%B %Y"),
        "chips": [
            {
                "label": m.strftime("%b %Y"),
                "url": _url(tab, month=m.strftime("%Y-%m")),
                "active": m == month,
            }
            for m in months
        ],
        "horizons": [
            {
                "label": f"{h} months",
                "url": _url(tab, month=picked, horizon=str(h)),
                "active": h == horizon,
            }
            for h in views.HORIZONS
        ],
    }


# --- The section ---------------------------------------------------------------


async def section_context(db: Any, query: Any) -> dict[str, Any]:
    now = today()
    tab = query.get("tab") if query.get("tab") in TABS else "overview"
    month = _month(query.get("month"), now)
    frame = await _frame(db, tab, month, now, query)
    if tab == "projections":
        start = now - timedelta(days=views.WINDOW_DAYS - 1)
        data = await ledger(db, _midnight(start), _midnight(now + timedelta(days=1)))
        return frame | views.projections(data, now, _horizon(query.get("horizon")))
    window = (_midnight(month), _midnight(_next_month(month)))
    if tab == "users":
        spend = await user_spend(db, *window)
        names = await user_names(db, [u for u in spend if u is not None])
        return frame | views.users(spend, names)
    data = await ledger(db, *window)
    if tab == "breakdown":
        return frame | views.breakdown(data.actions)
    return frame | views.overview(data, month, now)
