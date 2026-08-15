"""The goal-metadata contract: a goal is an account wearing goal metadata.

No goal tables. A *virtual* goal is a hidden manual account
(``account_type='goal'``, ``is_hidden=True`` - net worth and listings
already exclude hidden accounts) whose assigned-so-far rides
``FinanceValuation``; a *linked* goal is a real visible account flagged
with the same metadata, whose contributions are its own transfers.

The four ``metadata_`` keys below are the whole schema. This module's
accessors are the only reader/writer of that shape - SQL never touches
it, so validation lives here and is strict: corrupt goal metadata raises
rather than degrading into a goal that silently misbehaves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.finance.constants import add_months

GOAL_ACCOUNT_TYPE = "goal"
GOAL_STATUSES = ("active", "paused", "reached")

_TARGET_KEY = "goal_target_amount"
_DATE_KEY = "goal_target_date"
_MONTHLY_KEY = "goal_monthly_contribution"
_STATUS_KEY = "goal_status"
_KIND_KEY = "goal_contribution_kind"
_BPS_KEY = "goal_contribution_bps"
_PRIORITY_KEY = "goal_priority"
_GOAL_KEYS = (
    _TARGET_KEY,
    _DATE_KEY,
    _MONTHLY_KEY,
    _STATUS_KEY,
    _KIND_KEY,
    _BPS_KEY,
    _PRIORITY_KEY,
)


CONTRIBUTION_KINDS = ("fixed", "percent_income", "surplus")
DEFAULT_PRIORITY = 100


@dataclass(frozen=True)
class GoalMeta:
    """An account's goal facts, parsed and validated."""

    target_amount: int  # cents, > 0
    status: str  # one of GOAL_STATUSES
    target_date: date | None = None
    monthly_contribution: int | None = None  # cents, >= 0; fixed kind only
    # How the goal funds itself each month. ``fixed`` keeps the original
    # behaviour (declared cents, or derived from the target date);
    # ``percent_income`` re-evaluates against the month's confirmed
    # income; ``surplus`` sweeps whatever the month has left. Modes
    # (baby-steps, FIRE, 50/30/20) are just prioritized sets of these.
    contribution_kind: str = "fixed"
    contribution_bps: int | None = None  # basis points, percent kind only
    priority: int = DEFAULT_PRIORITY  # lower funds first


def goal_metadata(metadata: dict[str, Any] | None) -> GoalMeta | None:
    """The account's ``GoalMeta``, or ``None`` when it wears no goal
    metadata (the target key is the presence marker).

    Raises ``ValueError`` on corrupt stored values - a goal with an
    unreadable target or an unknown status must fail loudly, not read as
    almost-a-goal.
    """
    if not metadata or _TARGET_KEY not in metadata:
        return None
    target_amount = int(metadata[_TARGET_KEY])
    status = str(metadata.get(_STATUS_KEY, "active"))
    raw_date = metadata.get(_DATE_KEY)
    raw_monthly = metadata.get(_MONTHLY_KEY)
    raw_bps = metadata.get(_BPS_KEY)
    return _validated(
        target_amount=target_amount,
        status=status,
        target_date=date.fromisoformat(raw_date) if raw_date else None,
        monthly_contribution=int(raw_monthly) if raw_monthly is not None else None,
        contribution_kind=str(metadata.get(_KIND_KEY, "fixed")),
        contribution_bps=int(raw_bps) if raw_bps is not None else None,
        priority=int(metadata.get(_PRIORITY_KEY, DEFAULT_PRIORITY)),
    )


def set_goal_metadata(
    metadata: dict[str, Any] | None,
    *,
    target_amount: int,
    target_date: date | None = None,
    monthly_contribution: int | None = None,
    status: str = "active",
    contribution_kind: str = "fixed",
    contribution_bps: int | None = None,
    priority: int = DEFAULT_PRIORITY,
) -> dict[str, Any]:
    """A new metadata dict with the goal keys written (neighbours kept)."""
    meta = _validated(
        target_amount=target_amount,
        status=status,
        target_date=target_date,
        monthly_contribution=monthly_contribution,
        contribution_kind=contribution_kind,
        contribution_bps=contribution_bps,
        priority=priority,
    )
    written: dict[str, Any] = {
        **(metadata or {}),
        _TARGET_KEY: meta.target_amount,
        _STATUS_KEY: meta.status,
        _KIND_KEY: meta.contribution_kind,
        _PRIORITY_KEY: meta.priority,
    }
    written[_DATE_KEY] = meta.target_date.isoformat() if meta.target_date else None
    written[_MONTHLY_KEY] = meta.monthly_contribution
    written[_BPS_KEY] = meta.contribution_bps
    return written


def clear_goal_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """A new metadata dict with the goal keys stripped (the unflag path -
    a linked goal's account survives, wearing everything else it wore)."""
    return {k: v for k, v in (metadata or {}).items() if k not in _GOAL_KEYS}


_AUTO_KEY = "goal_auto_contribute"


def goal_auto_contribute(metadata: dict[str, Any] | None) -> bool:
    """Whether 's monthly job books this goal's declared amount.
    Off by default - automation is opted into, never assumed."""
    return bool((metadata or {}).get(_AUTO_KEY))


def set_auto_contribute(
    metadata: dict[str, Any] | None, enabled: bool
) -> dict[str, Any]:
    return {**(metadata or {}), _AUTO_KEY: bool(enabled)}


def goal_progress(*, balance: int, target: int) -> float:
    """Saved-so-far as a fraction of the target, clamped to [0, 1]."""
    if target <= 0:
        return 0.0
    return max(0.0, min(1.0, balance / target))


def goal_monthly_need(meta: GoalMeta, *, balance: int, today: date) -> int:
    """Cents per month this goal asks of the budget right now.

    Zero unless the goal is active with money still to save. A target
    date turns the remainder into remaining/months-left (due this month
    or overdue = 1 month: the rest is wanted now); without a date the
    declared rate is the ask, and no declared rate asks nothing.
    """
    remaining = meta.target_amount - balance
    if meta.status != "active" or remaining <= 0:
        return 0
    if meta.target_date is None:
        return meta.monthly_contribution or 0
    months_left = max(
        1,
        (meta.target_date.year - today.year) * 12
        + (meta.target_date.month - today.month),
    )
    return -(-remaining // months_left)  # ceil division on ints


def goal_eta(
    *, balance: int, target: int, monthly_rate: int | None, today: date
) -> date | None:
    """When the goal lands at ``monthly_rate`` cents/month.

    Already-reached returns ``today``; no rate (or zero) returns ``None``,
    which every caller renders as "never" - spelled out, never recomputed.
    """
    remaining = target - balance
    if remaining <= 0:
        return today
    if not monthly_rate or monthly_rate <= 0:
        return None
    months = -(-remaining // monthly_rate)  # ceil division
    return add_months(today, months)


@dataclass(frozen=True)
class MonthlyFigures:
    """The month's code-owned inputs the engine evaluates against.

    ``income_total`` is the confirmed-commitment monthly income (the same
    gate budget_summary applies); ``committed`` is what the month already
    owes before goals - bills monthly-equivalent plus budget allocations.
    """

    income_total: int
    committed: int


def allocate_month(
    figures: MonthlyFigures,
    goals: list[tuple[str, GoalMeta, int]],
    *,
    today: date | None = None,
) -> dict[str, int]:
    """This month's ask per goal, evaluated in priority order.

    ``goals`` rows are (key, meta, balance). Rules: ``fixed`` keeps the
    original per-goal logic (target-date derived, else declared);
    ``percent_income`` is income x bps/10000; ``surplus`` sweeps what the
    month has left AFTER committed spending and every allocation above
    it, floored at zero. Every ask caps at remaining-to-target;
    paused/reached goals ask nothing. Deterministic: priority then key.
    """
    today = today or date.today()
    asks: dict[str, int] = {}
    room = figures.income_total - figures.committed
    for key, meta, balance in sorted(
        goals, key=lambda row: (row[1].priority, row[0].casefold())
    ):
        remaining = meta.target_amount - balance
        if meta.status != "active" or remaining <= 0:
            asks[key] = 0
            continue
        if meta.contribution_kind == "percent_income":
            ask = figures.income_total * (meta.contribution_bps or 0) // 10_000
        elif meta.contribution_kind == "surplus":
            ask = max(0, room)
        else:
            ask = goal_monthly_need(meta, balance=balance, today=today)
        ask = max(0, min(ask, remaining))
        asks[key] = ask
        room -= ask
    return asks


def _validated(
    *,
    target_amount: int,
    status: str,
    target_date: date | None,
    monthly_contribution: int | None,
    contribution_kind: str = "fixed",
    contribution_bps: int | None = None,
    priority: int = DEFAULT_PRIORITY,
) -> GoalMeta:
    if target_amount <= 0:
        raise ValueError(f"Goal target must be positive cents, got {target_amount}.")
    if status not in GOAL_STATUSES:
        raise ValueError(
            f"Unknown goal status {status!r}. Known: {', '.join(GOAL_STATUSES)}."
        )
    if monthly_contribution is not None and monthly_contribution < 0:
        raise ValueError(
            f"Monthly contribution cannot be negative, got {monthly_contribution}."
        )
    if contribution_kind not in CONTRIBUTION_KINDS:
        raise ValueError(
            f"Unknown contribution kind {contribution_kind!r}. "
            f"Known: {', '.join(CONTRIBUTION_KINDS)}."
        )
    if contribution_kind == "percent_income" and not (
        contribution_bps is not None and 0 < contribution_bps <= 10_000
    ):
        raise ValueError(
            "percent_income needs basis points in (0, 10000]; "
            f"got {contribution_bps!r}."
        )
    return GoalMeta(
        target_amount=target_amount,
        status=status,
        target_date=target_date,
        monthly_contribution=monthly_contribution,
        contribution_kind=contribution_kind,
        contribution_bps=contribution_bps,
        priority=priority,
    )
