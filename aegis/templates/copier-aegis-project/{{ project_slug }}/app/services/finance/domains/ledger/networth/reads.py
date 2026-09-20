"""Reading net worth back: the series, the totals, the rollups.

These are what the dashboard and the health check ask for; none
of them writes.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import queries
from app.services.finance.domains.ledger.networth.snapshots import _today
from app.services.finance.domains.planning import insights
from app.services.finance.models import (
    FinanceNetWorthSnapshot,
)
from app.services.finance.schemas import (
    FinanceHealth,
    FinanceStatusSummary,
    NetWorthResponse,
)
from app.services.finance.utils import DEFAULT_CURRENCY


async def get_net_worth_series(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int = 90,
    currency: str = DEFAULT_CURRENCY,
    account_ids: list[int] | None = None,
) -> list[FinanceNetWorthSnapshot]:
    """The net-worth snapshot series (oldest first) — one indexed range scan.

    With ``account_ids`` the series is summed live from the per-account
    balance snapshots instead of the materialized owner-level rows, so a
    filtered Overview can chart just the accounts in view. The join back to
    ``finance_account`` keeps the owner scope authoritative: an id from
    another owner contributes nothing.
    """
    since = _today() - timedelta(days=max(days, 1) - 1)
    if account_ids is not None:
        rows = await queries.balance_class_series(
            db, account_ids=account_ids, since=since, owner_user_id=owner_user_id
        )
        per_day: dict[date, list[int]] = {}
        for balance_date, classification, total in rows:
            bucket = per_day.setdefault(balance_date, [0, 0])
            if classification == "liability":
                bucket[1] += abs(int(total or 0))
            else:
                bucket[0] += int(total or 0)
        # Transient rows, shaped like the materialized ones; never persisted.
        return [
            FinanceNetWorthSnapshot(
                owner_user_id=owner_user_id,
                as_of_date=day,
                total_assets_amount=assets,
                total_liabilities_amount=liabilities,
                net_worth_amount=assets - liabilities,
                currency=currency,
            )
            for day, (assets, liabilities) in sorted(per_day.items())
        ]

    return await queries.net_worth_series_since(
        db, owner_user_id=owner_user_id, since=since, currency=currency
    )


def analyst_available() -> bool:
    """Whether this build shipped the finance analyst agent.

    The analyst module is pruned entirely from a project generated without the
    AI service, so a failed import is the answer rather than an error: this is
    feature detection, and False is the whole handling. Asking the code beats
    keeping a second record of which capabilities were selected, which would
    only ever drift from the truth.

    Imported inside the function because the analyst imports this module.
    """
    try:
        from app.services.finance.domains.detection import analyst
    except ImportError:
        return False

    return hasattr(analyst, "run_analyst_note")


async def account_rollup(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> tuple[int, int, int]:
    """(assets, liabilities, account_count) in a single aggregate query."""
    return await queries.account_rollup(db, owner_user_id=owner_user_id)


async def connection_rollup(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> tuple[int, int]:
    """(connection_count, needs_action_count) in a single aggregate query."""
    return await queries.connection_rollup(db, owner_user_id=owner_user_id)


async def asset_liability_totals(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> tuple[int, int]:
    """Live (assets, liabilities) totals summed across visible accounts."""
    assets, liabilities, _ = await account_rollup(db, owner_user_id=owner_user_id)
    return assets, liabilities


async def get_net_worth(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> NetWorthResponse:
    assets, liabilities = await asset_liability_totals(db, owner_user_id=owner_user_id)
    return NetWorthResponse(
        net_worth_amount=assets - liabilities,
        total_assets_amount=assets,
        total_liabilities_amount=liabilities,
        currency=currency,
    )


async def get_status_summary(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> FinanceStatusSummary:
    """Headline numbers for the dashboard card, health check, and CLI."""
    assets, liabilities, account_count = await account_rollup(
        db, owner_user_id=owner_user_id
    )
    connection_count, _ = await connection_rollup(db, owner_user_id=owner_user_id)
    new_insight_count = await insights.count_new_insights(
        db, owner_user_id=owner_user_id
    )
    return FinanceStatusSummary(
        net_worth_amount=assets - liabilities,
        total_assets_amount=assets,
        total_liabilities_amount=liabilities,
        account_count=account_count,
        connection_count=connection_count,
        new_insight_count=new_insight_count,
        analyst_enabled=analyst_available(),
        currency=currency,
    )


async def health(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> FinanceHealth:
    """Liveness summary: account/connection counts + worst connection state.

    Backs ``GET /api/v1/finance/health``. ``status`` is ``"ok"`` unless a
    connection needs the user's attention (re-auth, consent expired, ...).
    """
    _, _, accounts = await account_rollup(db, owner_user_id=owner_user_id)
    connections, needs_action = await connection_rollup(db, owner_user_id=owner_user_id)
    return FinanceHealth(
        status="ok" if needs_action == 0 else "attention",
        accounts=accounts,
        connections=connections,
        connections_needing_action=needs_action,
    )
