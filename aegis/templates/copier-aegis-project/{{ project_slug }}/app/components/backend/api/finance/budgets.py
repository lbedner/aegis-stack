"""Budget lines, suggestions, summary, outlook, goal parsing.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.components.backend.api.finance.base import _NOT_FOUND
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.schemas import (
    BudgetLineResponse,
    BudgetLineUpsert,
    BudgetOutlookResponse,
    BudgetStatDetailsResponse,
    BudgetSuggestionIds,
    BudgetSuggestionListResponse,
    BudgetSummaryResponse,
    GoalParseRequest,
    GoalParseResponse,
    SuggestionDismissResult,
    SuggestionRestoreResult,
)
from app.services.finance.service import FinanceService

router = APIRouter()


@router.get("/budget/stat-details", response_model=BudgetStatDetailsResponse)
async def budget_stat_details(
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BudgetStatDetailsResponse:
    """Per-row backup for the header cells - what the click-a-cell popup
    shows. Income and Bills mirror the cells' math row for row; the
    everything-else rows group the uncovered-spend bucket by category,
    scoped by the same account filter as the cell."""
    return await service.budget_stat_details(
        owner_user_id=owner_user_id, account_ids=account_ids
    )


@router.get("/budget/outlook", response_model=BudgetOutlookResponse)
async def budget_outlook(
    months: int = 6,
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BudgetOutlookResponse:
    """The header equation per month, months ahead - so the Budget page
    can show the October that breaks even while August looks fine."""
    months = max(1, min(months, 24))
    outlook = await service.budget_month_outlook(
        owner_user_id=owner_user_id, months=months, account_ids=account_ids
    )
    return BudgetOutlookResponse(items=outlook, total=len(outlook))


# -- Budget --------------------------------------------------------------


@router.get("/budget/summary", response_model=BudgetSummaryResponse)
async def budget_summary(
    month: int | None = Query(default=None, ge=100_001, le=999_912),
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BudgetSummaryResponse:
    """Fixed / Non-monthly / Flexible buckets for one month (default: the
    current one). ``month`` is YYYYMM. ``account_ids`` is the same
    account-scope filter Overview/Projected use."""
    return await service.budget_summary(
        owner_user_id=owner_user_id, period_month=month, account_ids=account_ids
    )


@router.get("/budget/suggestions", response_model=BudgetSuggestionListResponse)
async def budget_suggestions(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BudgetSuggestionListResponse:
    """Budget lines the last six months already imply.

    Category level, gated on consistency rather than size: a category has
    to appear in most months and stay inside a spread bound, and the
    amount is a median. Transfers, categories a bill already covers, and
    lines you have already set are excluded - see
    ``FinanceService.suggest_budget_lines``.
    """
    picks = await service.suggest_budget_lines(owner_user_id=owner_user_id)
    dismissed = await service.list_dismissed_suggestions(owner_user_id=owner_user_id)
    return BudgetSuggestionListResponse(
        items=picks,
        total=len(picks),
        dismissed=dismissed,
    )


@router.post("/budget/suggestions/dismiss")
async def dismiss_budget_suggestions(
    body: BudgetSuggestionIds,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SuggestionDismissResult:
    """Decline suggestions. Standing: a dismissed category stays out of the
    suggestion list across months until restored (or until a real budget
    line is set for it). Idempotent."""
    count = await service.dismiss_budget_suggestions(
        owner_user_id=owner_user_id, category_ids=body.category_ids
    )
    await service.db.commit()
    return SuggestionDismissResult(dismissed=count)


@router.post("/budget/suggestions/restore")
async def restore_budget_suggestions(
    body: BudgetSuggestionIds,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SuggestionRestoreResult:
    """Un-decline suggestions previously dismissed."""
    count = await service.restore_budget_suggestions(
        owner_user_id=owner_user_id, category_ids=body.category_ids
    )
    await service.db.commit()
    return SuggestionRestoreResult(restored=count)


@router.post("/budget/lines", response_model=BudgetLineResponse)
async def upsert_budget_line(
    body: BudgetLineUpsert,
    month: int | None = Query(default=None, ge=100_001, le=999_912),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BudgetLineResponse:
    """Create or replace one budget line for the month (default: the
    current one) - a category limit or a payee limit, not both."""
    if body.category_id is not None and body.payee_key is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A budget line targets a category or a payee, not both.",
        )
    result = await service.upsert_budget_line(
        owner_user_id=owner_user_id,
        period_month=month,
        category_id=body.category_id,
        payee_key=body.payee_key,
        payee_label=body.payee_label,
        allocated_amount=body.allocated_amount,
        rollover_enabled=body.rollover_enabled,
    )
    return result


@router.delete("/budget/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget_line(
    line_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> None:
    deleted = await service.delete_budget_line(line_id, owner_user_id=owner_user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)


@router.post("/budget/goal", response_model=GoalParseResponse)
async def parse_budget_goal(
    body: GoalParseRequest,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> GoalParseResponse:
    """Preview a budget line from a natural-language goal ("I wanna cut
    back on Starbucks"). Writes nothing - the frontend's Confirm step
    calls ``POST /budget/lines`` with the accepted suggestion."""
    return await service.parse_budget_goal(owner_user_id=owner_user_id, text=body.text)
