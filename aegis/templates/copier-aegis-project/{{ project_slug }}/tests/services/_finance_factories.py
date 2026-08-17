"""Shared factories for the finance test suite.

One canonical seed per row kind. Before this file, ``_account`` was
re-typed in 17 test files and ``_category``'s slug rule had already
drifted between copies ("&" handled in one, not the others) - which is
the failure mode a shared factory exists to prevent. Files alias these
on import (``from tests.services._finance_factories import seed_account
as _account``) so call sites stay short.

Keep factories SUPERSETS: add keywords with the old defaults, never
change a default - fifteen files inherit it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.finance.models import FinanceCategory
from app.services.finance.service import FinanceService


async def seed_account(
    svc: FinanceService,
    name: str = "Checking",
    account_type: str = "checking",
    classification: str = "asset",
    owner_user_id: int = 1,
    **kwargs: Any,
):
    """A manual account; defaults to the plain checking account most tests want."""
    return await svc.create_manual_account(
        name=name,
        account_type=account_type,
        classification=classification,
        owner_user_id=owner_user_id,
        **kwargs,
    )


async def seed_category(db: Any, name: str) -> FinanceCategory:
    """An expense category with the FULL slug normalization - one copy had
    "&" handling and two did not, which is exactly the drift this fixes."""
    row = FinanceCategory(
        owner_user_id=1,
        name=name,
        slug=name.lower().replace(" ", "-").replace(":", "-").replace("&", "and"),
        classification="expense",
    )
    db.add(row)
    await db.flush()
    return row


async def seed_spend_series(
    svc: FinanceService,
    account_id: int,
    days: list[date],
    cents: int = -2_500,
    name: str = "ACME",
) -> list[Any]:
    """One transaction per day - the rhythm the detection tests feed."""
    return [
        await svc.create_transaction(
            account_id=account_id,
            amount=cents,
            txn_date=day,
            owner_user_id=1,
            name=name,
        )
        for day in days
    ]


async def live_streams(db: Any) -> list[Any]:
    """Live (non-deleted) recurring streams, unordered."""
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream

    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
    )


async def seed_txn(
    svc: FinanceService,
    account_id: int,
    amount: int,
    day: date,
    *,
    name: str | None = None,
    category_id: int | None = None,
    owner_user_id: int = 1,
):
    """One transaction. The canonical signature; files with their own
    argument conventions keep a two-line wrapper that delegates here."""
    return await svc.create_transaction(
        account_id=account_id,
        amount=amount,
        txn_date=day,
        owner_user_id=owner_user_id,
        name=name,
        category_id=category_id,
    )


async def seed_payee_txn(
    svc: FinanceService,
    account_id: int,
    name: str,
    day: date,
    cents: int,
):
    """The payee-first convention two suites share: name up front, because
    the payee IS the subject under test."""
    return await seed_txn(svc, account_id, cents, day, name=name)


async def seed_stream(
    svc: FinanceService,
    *,
    name: str,
    expected_amount: int,
    next_expected_date: date,
    direction: str = "outflow",
    frequency: str = "monthly",
    owner_user_id: int = 1,
    account_id: int | None = None,
    **overrides: Any,
):
    """A hand-declared recurring stream (bill or income)."""
    kwargs: dict[str, Any] = dict(
        owner_user_id=owner_user_id,
        name=name,
        direction=direction,
        frequency=frequency,
        expected_amount=expected_amount,
        next_expected_date=next_expected_date,
        account_id=account_id,
    )
    kwargs.update(overrides)
    return await svc.create_recurring_stream(**kwargs)


async def declare_bill(
    svc: FinanceService,
    db: Any,
    account_id: int,
    name: str,
    days: list[date],
    cents: int = -1_000,
):
    """A bill the DETECTOR made: a transaction series, declared recurring.

    Returns ``(stream, txns)`` - callers that only need the side effect
    ignore the return.
    """
    from app.services.finance.domains.detection import declare_recurring

    txns = await seed_spend_series(svc, account_id, days, cents=cents, name=name)
    await declare_recurring(db, [t.id for t in txns], owner_user_id=1)
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream

    stream = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.deleted_at.is_(None),
                FinanceRecurringStream.name == name,
            )
        )
    ).first()
    return stream, txns
