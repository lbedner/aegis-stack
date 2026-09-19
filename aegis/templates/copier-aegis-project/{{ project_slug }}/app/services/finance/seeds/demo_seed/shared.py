"""What the clearing and the writing both need.

The demo marker is the whole mechanism: every row this package
writes carries it, so clearing can find exactly what it made and
nothing a user added alongside.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceValuation,
)
from app.services.finance.seeds.demo_plan import (  # noqa: F401
    _DEFAULT_MONTHS,
    _SEED,
    PlannedSplit,
    PlannedTransaction,
    _day_in_month,
    _jitter,
    _month_starts,
    build_demo_ledger,
)

# Bumping this re-marks future seeds without invalidating older ones.
DEMO_MARKER_KEY = "demo_seed"
DEMO_MARKER_VALUE = 1

_IMPORT_WINDOW_DAYS = 30
_QUANTITY_SCALE = 10**8


class DemoSeedResult(BaseModel):
    """What one seed run wrote (all zero when ``skipped``)."""

    accounts: int = 0
    transactions: int = 0
    imported_rows: int = 0
    splits: int = 0
    transfers: int = 0
    recurring: int = 0
    valuations: int = 0
    trades: int = 0
    net_worth_days: int = 0
    skipped: bool = False
    reset: bool = False


def _is_demo(account: FinanceAccount) -> bool:
    return bool((account.metadata_ or {}).get(DEMO_MARKER_KEY))


async def _demo_accounts(
    db: AsyncSession, owner_user_id: int | None
) -> list[FinanceAccount]:
    """Seeded accounts for this owner, identified by their marker.

    Filtered in Python rather than SQL: JSON predicates differ across SQLite
    and Postgres, and an install's account list is small enough that one scan
    is cheaper than the portability problem.
    """
    query = select(FinanceAccount)
    if owner_user_id is None:
        query = query.where(FinanceAccount.owner_user_id.is_(None))
    else:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return [a for a in (await db.exec(query)).all() if _is_demo(a)]


async def _seeded_window_start(db: AsyncSession, account_ids: list[int]) -> date | None:
    """Earliest day the seeded accounts have history for, if any."""
    earliest = (
        await db.exec(
            select(FinanceValuation.as_of_date)
            .where(FinanceValuation.account_id.in_(account_ids))
            .order_by(FinanceValuation.as_of_date)
            .limit(1)
        )
    ).first()
    return earliest
