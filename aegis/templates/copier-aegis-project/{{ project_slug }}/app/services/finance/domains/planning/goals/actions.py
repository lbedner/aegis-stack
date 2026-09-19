"""Changing a goal: create, flag, contribute, retire."""

from __future__ import annotations

from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.domains.ledger import accounts, valuations
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning.goals.meta import (
    DEFAULT_PRIORITY,
    GOAL_ACCOUNT_TYPE,
    clear_goal_metadata,
    goal_auto_contribute,
    goal_metadata,
    set_auto_contribute,
    set_goal_metadata,
)
from app.services.finance.domains.planning.goals.reads import list_goals
from app.services.finance.models import (
    FinanceAccount,
)


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
    await valuations.upsert_valuation(
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
        await valuations.upsert_valuation(
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
