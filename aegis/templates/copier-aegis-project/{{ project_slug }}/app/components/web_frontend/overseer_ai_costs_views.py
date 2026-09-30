"""The Costs section's four views, built from what the ledger read: pure
functions, no database. Overview (a month in figures and charts), Users (who
it was spent on), Projections (where the last 90 days say it is heading) and
Breakdown (every action under the feature it pays for).

A feature is the ledger's action with its call style dropped:
``stream_chat:finance-assistant`` and ``chat:finance-assistant`` are one
agent's spend. ``by_feature`` is the one place that grouping happens.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel

from app.services.ai.domains.spend.schemas import ActionSpend, ModelSpend, SpendLedger

from .overseer_ai_common import dollars
from .rendering import chart, ranked

MODELS_CHARTED = 7
# The window Projections averages over, and the horizons it can look ahead.
WINDOW_DAYS = 90
HORIZONS = (3, 6, 12)
DAYS_PER_MONTH = 30
NO_USER = "No user (background)"


class FeatureSpend(BaseModel):
    """A feature's spend: its calls and cost, and the actions that made it."""

    name: str
    calls: int
    cost: float
    actions: list[tuple[str, ActionSpend]]


def feature(action: str) -> str:
    """An action as the feature it pays for: the agent, not the call style."""
    name = action.split(":", 1)[-1]
    return name.replace("_", " ").replace("-", " ").title()


def by_feature(actions: dict[str, ActionSpend]) -> list[FeatureSpend]:
    """Actions grouped by feature, most spent first, each feature's actions
    most spent first."""
    groups: dict[str, list[tuple[str, ActionSpend]]] = {}
    for action, spend in actions.items():
        groups.setdefault(feature(action), []).append((action, spend))
    features = [
        FeatureSpend(
            name=name,
            calls=sum(s.calls for _, s in members),
            cost=sum(s.cost for _, s in members),
            actions=sorted(members, key=lambda m: -m[1].cost),
        )
        for name, members in groups.items()
    ]
    return sorted(features, key=lambda f: -f.cost)


def _per_call(cost: float, calls: int) -> str | None:
    return dollars(cost / calls if calls else 0)


def _figure(
    label: str, value: str | None, caption: str | None = None
) -> dict[str, Any]:
    return {"label": label, "value": value, "caption": caption}


# --- Overview ------------------------------------------------------------------


def _daily_chart(daily: dict[date, float], first: date, last: date) -> dict[str, Any]:
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    labels = [d.strftime("%b %d") for d in days]
    return chart(labels, "Spend", [daily.get(d, 0.0) for d in days], money=True)


def _models_chart(models: list[ModelSpend]) -> dict[str, Any]:
    by_cost = sorted((m for m in models if m.cost), key=lambda m: -m.cost)
    shown, rest = by_cost[:MODELS_CHARTED], by_cost[MODELS_CHARTED:]
    labels = [m.title or m.model_id for m in shown]
    values = [round(m.cost, 4) for m in shown]
    if rest:
        labels.append("Other")
        values.append(round(sum(m.cost for m in rest), 4))
    return chart(labels, "Spend", values, money=True)


def overview(data: SpendLedger, first: date, now: date) -> dict[str, Any]:
    """A month in figures, a daily chart, and where the money went."""
    current = first == now.replace(day=1)
    last = now if current else _month_end(first)
    days = (last - first).days + 1
    model_spend = sum(data.daily.values())
    total = model_spend + sum(data.voice.values())
    features = by_feature(data.actions)
    top = features[0] if features else None
    projected = total / days * _days_in(first) if current and days else None
    split = {"Model calls": model_spend, **data.voice}
    return {
        "figures": [
            _figure(
                "Total spend",
                dollars(total),
                f"Projected {dollars(projected)} by month end" if projected else None,
            ),
            _figure("Daily average", dollars(total / days if days else 0)),
            _figure(
                "Cost per user",
                dollars(total / data.users if data.users else 0),
                f"{data.users:,} users",
            ),
            _figure(
                "Top feature",
                dollars(top.cost if top else 0),
                top.name if top else None,
            ),
        ],
        "daily": _daily_chart(data.daily, first, last),
        "features": ranked(
            [
                {
                    "label": f.name,
                    "count": f"{f.calls:,} calls",
                    "value": dollars(f.cost),
                    "cost": f.cost,
                }
                for f in features
            ],
            by="cost",
        ),
        "models": _models_chart(data.models),
        "split": ranked(
            [{"label": k, "value": dollars(v), "cost": v} for k, v in split.items()],
            by="cost",
        ),
    }


def _days_in(first: date) -> int:
    return calendar.monthrange(first.year, first.month)[1]


def _month_end(first: date) -> date:
    return first.replace(day=_days_in(first))


# --- Users ---------------------------------------------------------------------


def users(
    spend: dict[str | None, dict[str, ActionSpend]], names: dict[str, str]
) -> dict[str, Any]:
    """Top spenders: a known user by name, else the ledger's id."""
    totals = []
    for user, actions in spend.items():
        top = max(actions.items(), key=lambda a: a[1].cost)[0]
        calls = sum(s.calls for s in actions.values())
        cost = sum(s.cost for s in actions.values())
        totals.append((user, calls, cost, top))
    totals.sort(key=lambda t: -t[2])
    return {
        "rows": [
            {
                "rank": i,
                "user": names.get(user, user) if user is not None else NO_USER,
                "spend": dollars(cost),
                "calls": calls,
                "avg": _per_call(cost, calls),
                "top": feature(top),
            }
            for i, (user, calls, cost, top) in enumerate(totals, 1)
        ]
    }


# --- Projections ---------------------------------------------------------------


def _week_over_week(daily: dict[date, float], now: date) -> tuple[str, str]:
    def week(ending: date) -> float:
        return sum(daily.get(ending - timedelta(days=i), 0.0) for i in range(7))

    this, last = week(now), week(now - timedelta(days=7))
    change = f"{(this - last) / last * 100:+.1f}%" if last else "-"
    return change, f"{dollars(this)} vs {dollars(last)}"


def projections(data: SpendLedger, now: date, horizon: int) -> dict[str, Any]:
    """Where the last 90 days' average says the spend is heading."""
    per_day = (sum(data.daily.values()) + sum(data.voice.values())) / WINDOW_DAYS
    annual = per_day * 365
    horizon_days = horizon * DAYS_PER_MONTH
    change, versus = _week_over_week(data.daily, now)
    return {
        "basis": f"Based on the {WINDOW_DAYS}-day average ({dollars(per_day)}/day)",
        "horizon": horizon,
        "figures": [
            _figure(
                f"{horizon} months forecast",
                dollars(per_day * horizon_days),
                f"next {horizon_days} days",
            ),
            _figure(
                "Month-end forecast",
                dollars(per_day * _days_in(now)),
                f"this month ({_days_in(now)} days)",
            ),
            _figure("Week over week", change, versus),
            _figure(
                "Annual run rate",
                dollars(annual),
                f"{dollars(annual / data.users)}/user/yr" if data.users else None,
            ),
        ],
        "forecast": [
            {
                "feature": f.name,
                "per_day": dollars(f.cost / WINDOW_DAYS),
                "horizon": dollars(f.cost / WINDOW_DAYS * horizon_days),
                "year": dollars(f.cost / WINDOW_DAYS * 365),
            }
            for f in by_feature(data.actions)
        ],
    }


# --- Breakdown -----------------------------------------------------------------


def breakdown(actions: dict[str, ActionSpend]) -> dict[str, Any]:
    """Every action with its cost and share, under the feature it pays for."""
    total = sum(s.cost for s in actions.values())

    def row(name: str, calls: int, cost: float, **flags: bool) -> dict[str, Any]:
        return {
            "name": name,
            "cost": dollars(cost),
            "calls": calls,
            "avg": _per_call(cost, calls),
            "share": f"{cost / total * 100:.1f}%" if total else "-",
            **flags,
        }

    rows: list[dict[str, Any]] = []
    for f in by_feature(actions):
        rows.append(row(f.name, f.calls, f.cost, group=True))
        rows += [row(a, s.calls, s.cost, child=True) for a, s in f.actions]
    return {"rows": rows}
