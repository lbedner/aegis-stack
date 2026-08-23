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

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    add_months,
)
from app.services.finance.domains.ledger import accounts
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.models import (
    FinanceAccount,
)
from app.services.finance.utils import (
    utcnow,
)

GOAL_ACCOUNT_TYPE = "goal"
GOAL_STATUSES = ("active", "paused", "reached")

_TARGET_KEY = "goal_target_amount"
_DATE_KEY = "goal_target_date"
_MONTHLY_KEY = "goal_monthly_contribution"
_STATUS_KEY = "goal_status"
_KIND_KEY = "goal_contribution_kind"
_BPS_KEY = "goal_contribution_bps"
_PRIORITY_KEY = "goal_priority"
_RULE_KEY = "goal_target_rule"
_FACTOR_KEY = "goal_target_factor"
_SCOPE_KEY = "goal_target_scope"
_GOAL_KEYS = (
    _TARGET_KEY,
    _DATE_KEY,
    _MONTHLY_KEY,
    _STATUS_KEY,
    _KIND_KEY,
    _BPS_KEY,
    _PRIORITY_KEY,
    _RULE_KEY,
    _FACTOR_KEY,
    _SCOPE_KEY,
)


CONTRIBUTION_KINDS = ("fixed", "percent_income", "surplus")
# How the finish line is expressed. ``fixed`` is a pile of cents;
# ``months_of_expenses`` is a multiple of the month's committed figure,
# re-resolved on every read (see ``allocation.resolve_target``).
TARGET_RULES = ("fixed", "months_of_expenses")
MAX_TARGET_FACTOR = 120
DEFAULT_PRIORITY = 100


class GoalMeta(BaseModel):
    """An account's goal facts, parsed and validated.

    Each field's alias IS its stored ``metadata_`` key, so the model both
    parses a stored blob and serializes back to one.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    target_amount: int = Field(alias=_TARGET_KEY)  # cents, > 0
    status: str = Field(default="active", alias=_STATUS_KEY)  # one of GOAL_STATUSES
    target_date: date | None = Field(default=None, alias=_DATE_KEY)
    # cents, >= 0; fixed kind only
    monthly_contribution: int | None = Field(default=None, alias=_MONTHLY_KEY)
    # How the goal funds itself each month. ``fixed`` keeps the original
    # behaviour (declared cents, or derived from the target date);
    # ``percent_income`` re-evaluates against the month's confirmed
    # income; ``surplus`` sweeps whatever the month has left. Modes
    # (baby-steps, FIRE, 50/30/20) are just prioritized sets of these.
    contribution_kind: str = Field(default="fixed", alias=_KIND_KEY)
    # basis points, percent kind only
    contribution_bps: int | None = Field(default=None, alias=_BPS_KEY)
    priority: int = Field(default=DEFAULT_PRIORITY, alias=_PRIORITY_KEY)  # lower first
    # How ``target_amount`` was arrived at. Under a relative rule the
    # stored cents are the last resolved value, kept as the fallback for
    # a book with no figures yet; the rule plus factor are the truth.
    target_rule: str = Field(default="fixed", alias=_RULE_KEY)
    target_factor: int | None = Field(default=None, alias=_FACTOR_KEY)  # months
    # Which cash accounts the run rate is measured on. Empty means all
    # of them - a book with one checking account never has to care.
    target_scope: list[int] = Field(default_factory=list, alias=_SCOPE_KEY)


def goal_metadata(metadata: dict[str, Any] | None) -> GoalMeta | None:
    """The account's ``GoalMeta``, or ``None`` when it wears no goal
    metadata (the target key is the presence marker).

    Raises ``ValueError`` on corrupt stored values - a goal with an
    unreadable target or an unknown status must fail loudly, not read as
    almost-a-goal.
    """
    if not metadata or _TARGET_KEY not in metadata:
        return None
    stored = {key: metadata[key] for key in _GOAL_KEYS if key in metadata}
    return _validated(GoalMeta.model_validate(stored))


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
    target_rule: str = "fixed",
    target_factor: int | None = None,
    target_scope: list[int] | None = None,
) -> dict[str, Any]:
    """A new metadata dict with the goal keys written (neighbours kept)."""
    meta = _validated(
        GoalMeta(
            target_amount=target_amount,
            status=status,
            target_date=target_date,
            monthly_contribution=monthly_contribution,
            contribution_kind=contribution_kind,
            contribution_bps=contribution_bps,
            priority=priority,
            target_rule=target_rule,
            target_factor=target_factor,
            target_scope=list(target_scope or []),
        )
    )
    return {**(metadata or {}), **meta.model_dump(mode="json", by_alias=True)}


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


def _validated(meta: GoalMeta) -> GoalMeta:
    if meta.target_amount <= 0:
        raise ValueError(
            f"Goal target must be positive cents, got {meta.target_amount}."
        )
    if meta.status not in GOAL_STATUSES:
        raise ValueError(
            f"Unknown goal status {meta.status!r}. Known: {', '.join(GOAL_STATUSES)}."
        )
    if meta.monthly_contribution is not None and meta.monthly_contribution < 0:
        raise ValueError(
            f"Monthly contribution cannot be negative, got {meta.monthly_contribution}."
        )
    if meta.contribution_kind not in CONTRIBUTION_KINDS:
        raise ValueError(
            f"Unknown contribution kind {meta.contribution_kind!r}. "
            f"Known: {', '.join(CONTRIBUTION_KINDS)}."
        )
    if meta.target_rule not in TARGET_RULES:
        raise ValueError(
            f"Unknown target rule {meta.target_rule!r}. Known: {', '.join(TARGET_RULES)}."
        )
    if meta.target_rule == "months_of_expenses" and not (
        meta.target_factor is not None and 0 < meta.target_factor <= MAX_TARGET_FACTOR
    ):
        raise ValueError(
            "months_of_expenses needs a factor in "
            f"(0, {MAX_TARGET_FACTOR}] months; got {meta.target_factor!r}."
        )
    if meta.target_rule == "fixed" and (
        meta.target_factor is not None or meta.target_scope
    ):
        raise ValueError(
            "A fixed target takes no factor or scope; set target_rule to "
            "express one."
        )
    if meta.contribution_kind == "percent_income" and not (
        meta.contribution_bps is not None and 0 < meta.contribution_bps <= 10_000
    ):
        raise ValueError(
            "percent_income needs basis points in (0, 10000]; "
            f"got {meta.contribution_bps!r}."
        )
    return meta


async def list_goals(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceAccount]:
    """Every account wearing goal metadata - virtual (hidden) and
    linked alike. Filtered in Python: the goal keys live in JSON the
    SQL layer never reads, and the account population is tens, not
    thousands."""
    accounts = await ledger_queries.live_accounts_for_owner(
        db, owner_user_id=owner_user_id
    )
    return [a for a in accounts if goal_metadata(a.metadata_) is not None]


def _observed_rate(snapshots: list[Any]) -> int | None:
    """Trailing growth in cents/month from a date-ascending snapshot
    series; None below 2 points or 14 days of history."""
    if len(snapshots) < 2:
        return None
    first, last = snapshots[0], snapshots[-1]
    days = (last.balance_date - first.balance_date).days
    if days < 14:
        return None
    rate = round((last.balance - first.balance) * 30 / days)
    return rate if rate > 0 else None


async def goal_rates(
    db: AsyncSession, accounts: list[FinanceAccount], *, today: date
) -> dict[int, int | None]:
    """``goal_rate`` for many accounts with ONE snapshot query.

    Declared rates come straight off the metadata; the rest share a
    single balance-snapshot fetch instead of one query per goal.
    """
    rates: dict[int, int | None] = {}
    undeclared: list[FinanceAccount] = []
    for account in accounts:
        meta = goal_metadata(account.metadata_)
        if meta is not None and meta.monthly_contribution:
            rates[account.id] = meta.monthly_contribution
        else:
            undeclared.append(account)
    if undeclared:
        window_start = today - timedelta(days=120)
        rows = await ledger_queries.balance_snapshots_between(
            db, [a.id for a in undeclared], start=window_start, end=today
        )
        by_account: dict[int, list[Any]] = {}
        for snapshot in rows:
            by_account.setdefault(snapshot.account_id, []).append(snapshot)
        for account in undeclared:
            snapshots = sorted(
                by_account.get(account.id, []), key=lambda s: s.balance_date
            )
            rates[account.id] = _observed_rate(snapshots)
    return rates


async def goal_rate(
    db: AsyncSession, account: FinanceAccount, *, today: date
) -> int | None:
    """Cents/month the goal is actually growing at: the declared rate
    when one is set, else the trailing observed rate from the
    account's own balance-snapshot history (>=14 days of it within the
    last 120), else ``None`` - which renders as "never"."""
    rates = await goal_rates(db, [account], today=today)
    return rates.get(account.id)


async def create_virtual_goal(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    name: str,
    target_amount: int,
    target_date: date | None = None,
    monthly_contribution: int | None = None,
    contribution_kind: str = "fixed",
    contribution_bps: int | None = None,
    priority: int = DEFAULT_PRIORITY,
    target_rule: str = "fixed",
    target_factor: int | None = None,
    target_scope: list[int] | None = None,
) -> FinanceAccount:
    """A virtual goal: hidden manual account (its money already sits in
    a cash account, so it must not count twice in net worth)."""
    account = await accounts.create_manual_account(
        db,
        owner_user_id=owner_user_id,
        name=name,
        account_type=GOAL_ACCOUNT_TYPE,
        classification="asset",
    )
    account.is_hidden = True
    account.metadata_ = set_goal_metadata(
        account.metadata_,
        target_amount=target_amount,
        target_date=target_date,
        monthly_contribution=monthly_contribution,
        contribution_kind=contribution_kind,
        contribution_bps=contribution_bps,
        priority=priority,
        target_rule=target_rule,
        target_factor=target_factor,
        target_scope=target_scope,
    )
    db.add(account)
    await db.flush()
    return account


async def flag_account_as_goal(
    db: AsyncSession,
    account_id: int,
    *,
    owner_user_id: int | None,
    target_amount: int,
    target_date: date | None = None,
    monthly_contribution: int | None = None,
    contribution_kind: str = "fixed",
    contribution_bps: int | None = None,
    priority: int = DEFAULT_PRIORITY,
    target_rule: str = "fixed",
    target_factor: int | None = None,
    target_scope: list[int] | None = None,
) -> FinanceAccount | None:
    """A linked goal: an existing real account starts wearing goal
    metadata. It stays visible and keeps counting in net worth - the
    money is really there."""
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return None
    account.metadata_ = set_goal_metadata(
        account.metadata_,
        target_amount=target_amount,
        target_date=target_date,
        monthly_contribution=monthly_contribution,
        contribution_kind=contribution_kind,
        contribution_bps=contribution_bps,
        priority=priority,
        target_rule=target_rule,
        target_factor=target_factor,
        target_scope=target_scope,
    )
    db.add(account)
    await db.flush()
    return account


async def unflag_goal(
    db: AsyncSession, account_id: int, *, owner_user_id: int | None
) -> FinanceAccount | None:
    """Strip the goal keys; everything else about the account survives."""
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return None
    account.metadata_ = clear_goal_metadata(account.metadata_)
    db.add(account)
    await db.flush()
    return account


async def contribute_to_goal(
    db: AsyncSession,
    account_id: int,
    *,
    amount: int,
    owner_user_id: int | None,
    when: date | None = None,
) -> FinanceAccount:
    """Assign money to a VIRTUAL goal: a valuation at balance+amount
    (idempotent per date via upsert; ``upsert_valuation`` maintains
    ``current_balance``). Refused for linked goals - their
    contributions are their real transfers, and a manual top-up would
    double-count against the account's own register.
    """
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        raise ValueError(f"No account {account_id}.")
    if account.account_type != GOAL_ACCOUNT_TYPE:
        raise ValueError(
            "Linked goals book contributions from their own transfers; "
            "manual contributions are for virtual goals only."
        )
    await accounts.upsert_valuation(
        db,
        account_id=account_id,
        as_of_date=when or utcnow().date(),
        value=(account.current_balance or 0) + amount,
        owner_user_id=owner_user_id,
        note="Goal contribution",
    )
    refreshed = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    assert refreshed is not None  # just written
    return refreshed


async def set_goal_status(
    db: AsyncSession, account_id: int, status: str, *, owner_user_id: int | None
) -> FinanceAccount | None:
    """active | paused | reached - validated by the metadata contract."""
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return None
    meta = goal_metadata(account.metadata_)
    if meta is None:
        raise ValueError(f"Account {account_id} is not a goal.")
    account.metadata_ = set_goal_metadata(
        account.metadata_,
        target_amount=meta.target_amount,
        target_date=meta.target_date,
        monthly_contribution=meta.monthly_contribution,
        status=status,
        contribution_kind=meta.contribution_kind,
        contribution_bps=meta.contribution_bps,
        priority=meta.priority,
        target_rule=meta.target_rule,
        target_factor=meta.target_factor,
        target_scope=meta.target_scope,
    )
    db.add(account)
    await db.flush()
    return account


async def set_goal_auto_contribute(
    db: AsyncSession, account_id: int, enabled: bool, *, owner_user_id: int | None
) -> FinanceAccount | None:
    """Toggle 's monthly auto-booking for one goal."""
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return None
    if goal_metadata(account.metadata_) is None:
        raise ValueError(f"Account {account_id} is not a goal.")
    account.metadata_ = set_auto_contribute(account.metadata_, enabled)
    db.add(account)
    await db.flush()
    return account


async def auto_contribute_goals(
    db: AsyncSession, *, owner_user_id: int | None, today: date
) -> int:
    """'s monthly booking: each toggled-on, ACTIVE, VIRTUAL goal
    gets its declared amount as a ``goal_auto`` valuation dated the
    1st. Returns how many booked. Idempotent per month: the distinct
    source makes "already booked" a precise existence check, not a
    note-string match. Linked goals never book - reality does.
    """
    # Local import: the engine reads this module's contract, so it can
    # only depend one way and the booking path asks it at call time.
    from app.services.finance.domains.planning.allocation import goal_allocations

    first = date(today.year, today.month, 1)
    allocations = await goal_allocations(db, owner_user_id=owner_user_id, today=today)
    booked = 0
    for account in await list_goals(db, owner_user_id=owner_user_id):
        meta = goal_metadata(account.metadata_)
        if (
            meta is None
            or meta.status != "active"
            or account.account_type != GOAL_ACCOUNT_TYPE
            or not goal_auto_contribute(account.metadata_)
        ):
            continue
        amount = allocations.get(account.id, 0)
        if amount <= 0:
            continue
        already = await ledger_queries.valuation_by_key(
            db, account_id=account.id, as_of_date=first, source="goal_auto"
        )
        if already is not None:
            continue
        await accounts.upsert_valuation(
            db,
            account_id=account.id,
            as_of_date=first,
            value=(account.current_balance or 0) + amount,
            owner_user_id=owner_user_id,
            source="goal_auto",
            note="Goal auto-contribution",
        )
        booked += 1
    return booked
