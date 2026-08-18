"""Insight rows: list and dismiss.

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
    InsightListResponse,
    InsightResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


@router.get("/insights", response_model=InsightListResponse)
async def list_insights(
    status_filter: str | None = Query(default="new", alias="status"),
    insight_type: str | None = Query(default=None),
    exclude_type: list[str] = Query(default=[]),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> InsightListResponse:
    """Wasting-money insights, newest first. Defaults to ``status=new``.

    ``insight_type`` narrows to one kind; repeatable ``exclude_type`` drops
    kinds. The anomaly list and the analyst's notes share this table and each
    filters the other out here rather than after the round trip.
    """
    insights = await service.list_insights(
        owner_user_id=owner_user_id,
        status=status_filter,
        insight_type=insight_type,
        exclude_types=exclude_type,
    )
    return InsightListResponse(
        items=[InsightResponse.from_row(i) for i in insights],
        total=len(insights),
    )


@router.post("/insights/{insight_id}/dismiss", response_model=InsightResponse)
async def dismiss_insight(
    insight_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> InsightResponse:
    """Dismiss an insight; it won't come back (deduped by key on re-run)."""
    insight = await service.dismiss_insight(insight_id, owner_user_id=owner_user_id)
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return InsightResponse.from_row(insight)
