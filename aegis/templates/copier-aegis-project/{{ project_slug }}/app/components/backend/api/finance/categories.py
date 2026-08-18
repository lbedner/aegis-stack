"""The category taxonomy and spending rollups.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.schemas import (
    CategoryCreate,
    CategoryListResponse,
    CategoryOption,
    CategoryOptionListResponse,
    SpendingCategory,
    SpendingSummaryResponse,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(
    days: int | None = Query(default=None, ge=1, le=3650),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> CategoryListResponse:
    """Every category with its usage (count, signed total, last used).

    ``days`` narrows the usage window; omit it for all time. Categories
    with no activity are still listed - the taxonomy is the point.
    """
    rows = await service.category_usage(owner_user_id=owner_user_id, days=days)
    return CategoryListResponse(items=rows, total=len(rows))


@router.post(
    "/categories",
    response_model=CategoryOption,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    body: CategoryCreate,
    service: FinanceService = Depends(get_finance_service),
) -> CategoryOption:
    """Create a category by name, or return the one that already matches.

    Deliberately get-or-CREATE, and deliberately the importer's own
    resolver: it keys on a normalized slug, so "kids: activities" finds
    "Kids:Activities" instead of adding a near-duplicate beside it, and
    it folds a third path segment back to two (a third segment names a
    merchant, not a category).

    201 either way. The caller wants a usable category id, not a race
    between two people typing the same name.
    """
    category = await service.get_or_create_category_from_hint(body.name)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give the category a name.",
        )
    await service.db.commit()
    return CategoryOption(id=category.id, name=category.name)


@router.get("/categories/options", response_model=CategoryOptionListResponse)
async def list_category_options(
    service: FinanceService = Depends(get_finance_service),
) -> CategoryOptionListResponse:
    """id + name for every category, no usage aggregation - for pickers.

    ``/categories`` also lists everything but joins + groups over the
    whole transaction history to compute stats a picker doesn't show;
    this is the plain, cheap version of the same list.
    """
    categories = await service.list_categories()
    return CategoryOptionListResponse(
        items=[CategoryOption(id=c.id, name=c.name) for c in categories]
    )


@router.get("/spending", response_model=list[SpendingCategory])
async def spending_by_category(
    days: int = 30,
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[SpendingCategory]:
    """Spending grouped by category over the recent window — outflows only,
    largest first, as positive amounts. ``account_ids`` narrows the view."""
    rows = await service.spending_by_category(
        owner_user_id=owner_user_id, days=days, account_ids=account_ids
    )
    return [SpendingCategory(category=name, amount=amount) for name, amount in rows]


@router.get("/spending/transactions", response_model=TransactionListResponse)
async def spending_transactions(
    days: int = 30,
    categories: list[str] | None = Query(default=None),
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransactionListResponse:
    """The transactions behind a ``/spending`` slice - same filters as
    ``spending_by_category`` (outflows only, excluded-from-reports rows
    dropped), so the returned rows sum to exactly what the slice showed.
    Click-through from the Overview spending pie/list.

    ``categories`` matches by exact name or "name:" prefix - a slice's
    name is already the PARENT category (spending_by_category's own
    rollup), so passing it here pulls every leaf underneath it too; pass
    every name folded into "Other" to drill into that slice.
    """
    rows = await service.spending_transactions(
        owner_user_id=owner_user_id,
        days=days,
        account_ids=account_ids,
        categories=categories,
    )
    names = await service.category_names(
        {t.category_id for t in rows if t.category_id is not None}
    )
    items = []
    for txn in rows:
        item = TransactionResponse.from_row(txn)
        item.category = names.get(txn.category_id)
        items.append(item)
    return TransactionListResponse(items=items, total=len(items))


@router.get("/spending/summary", response_model=SpendingSummaryResponse)
async def spending_summary(
    month: str | None = None,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SpendingSummaryResponse:
    """Per-category spend for a calendar month (``YYYY-MM``, default current),
    with internal transfers excluded — the report the insights + UI consume."""
    try:
        rows = await service.spending_summary(owner_user_id=owner_user_id, month=month)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month must be a valid YYYY-MM",
        ) from exc
    resolved = month or date.today().strftime("%Y-%m")
    return SpendingSummaryResponse(
        month=resolved,
        categories=[
            SpendingCategory(category=name, amount=amount) for name, amount in rows
        ],
        total=sum(amount for _, amount in rows),
    )
