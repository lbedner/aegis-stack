"""The landing figures: health, overview, net worth, cashflow.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from app.components.backend.api.finance.accounts import list_accounts
from app.components.backend.api.finance.categories import spending_by_category
from app.components.backend.api.finance.payees import top_payees
from app.components.backend.api.finance.recurring import recurring_projection
from app.components.backend.api.finance.register import (
    list_transactions,
    uncategorized_transactions,
)
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.schemas import (
    CashflowResponse,
    FinanceHealth,
    FinanceOverviewResponse,
    NetWorthPoint,
)
from app.services.finance.service import FinanceService

router = APIRouter()


@router.get("/health", response_model=FinanceHealth)
async def finance_health(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> FinanceHealth:
    """Liveness + a quick summary (account/connection counts, overall status),
    scoped to the caller (aggregate across all accounts in standalone mode)."""
    return await service.health(owner_user_id=owner_user_id)


@router.get("/overview", response_model=FinanceOverviewResponse)
async def finance_overview(
    days: int = Query(default=180, ge=1, le=3650),
    months: int = Query(default=6, ge=1, le=36),
    projection_days: int = Query(default=30, ge=1, le=730),
    preview_limit: int = Query(default=7, ge=1, le=50),
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> FinanceOverviewResponse:
    """The Overview surface in ONE round trip.

    Composes the eight granular endpoints the modal used to call
    individually - same handlers, same shapes - so opening the tab costs
    one request and one DB session instead of eight of each. The
    granular endpoints remain for targeted refreshes; this is the
    surface's front door (house rule: one surface, one composite).
    ``account_ids`` scopes the windowed aggregates (net worth, cashflow,
    spending), exactly as the surface applied it before.
    """
    return FinanceOverviewResponse(
        accounts=await list_accounts(
            include_hidden=False,
            page=1,
            page_size=200,
            service=service,
            owner_user_id=owner_user_id,
        ),
        net_worth=await net_worth_series(
            days=days,
            account_ids=account_ids,
            service=service,
            owner_user_id=owner_user_id,
        ),
        cashflow=await monthly_cashflow(
            months=months,
            account_ids=account_ids,
            service=service,
            owner_user_id=owner_user_id,
        ),
        top_payees=await top_payees(
            days=days,
            limit=preview_limit,
            service=service,
            owner_user_id=owner_user_id,
        ),
        projection=await recurring_projection(
            days=projection_days,
            account_ids=None,
            service=service,
            owner_user_id=owner_user_id,
        ),
        recent_transactions=await list_transactions(
            account_id=None,
            account_ids=None,
            from_date=None,
            to_date=None,
            category_id=None,
            merchant_id=None,
            without_merchant=False,
            tag_id=None,
            q=None,
            include_transfers=False,
            page=1,
            page_size=preview_limit,
            service=service,
            owner_user_id=owner_user_id,
        ),
        uncategorized=await uncategorized_transactions(
            limit=preview_limit,
            q=None,
            from_date=None,
            account_ids=None,
            service=service,
            owner_user_id=owner_user_id,
        ),
        spending=await spending_by_category(
            days=days,
            account_ids=account_ids,
            service=service,
            owner_user_id=owner_user_id,
        ),
    )


@router.get("/net-worth", response_model=list[NetWorthPoint])
async def net_worth_series(
    days: int = 90,
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[NetWorthPoint]:
    """Net-worth-over-time series, oldest first, straight off the snapshot
    table (materialized nightly by the scheduler job). ``account_ids``
    charts just those accounts, summed from the per-account snapshots."""
    rows = await service.get_net_worth_series(
        owner_user_id=owner_user_id,
        days=days,
        account_ids=account_ids,
    )
    return [NetWorthPoint.from_row(row) for row in rows]


@router.get("/cashflow", response_model=CashflowResponse)
async def monthly_cashflow(
    months: int = Query(default=6, ge=1, le=36),
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> CashflowResponse:
    """Income vs spend per calendar month, oldest first, transfers excluded.
    ``account_ids`` narrows the bars to those accounts."""
    rows = await service.monthly_cashflow(
        owner_user_id=owner_user_id, months=months, account_ids=account_ids
    )
    return CashflowResponse(items=rows, total=len(rows))
