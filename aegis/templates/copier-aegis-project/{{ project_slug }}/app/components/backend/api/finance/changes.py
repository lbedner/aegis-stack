"""The propose/approve queue's HTTP surface (FW-05).

Approval is the only execution path, and it lives here - behind the
app user - never in a tool. A proposal that fails execution stays
pending with its error in the payload the card renders.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.domains import writes
from app.services.finance.models import FinancePendingChange
from app.services.finance.schemas import (
    BatchResolveRequest,
    BatchResolveResponse,
    ChangeProposal,
    PendingChangeListResponse,
    PendingChangeResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


async def _to_response(
    service: FinanceService, row: FinancePendingChange
) -> PendingChangeResponse:
    executor = writes.executor_for(row.change_type)
    display = await service.describe_pending_change(row)
    return PendingChangeResponse.from_row(row, title=executor.title, display=display)


@router.post("/changes", response_model=PendingChangeResponse)
async def propose_change(
    body: ChangeProposal,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PendingChangeResponse:
    """Record a proposal. Nothing in the ledger moves here."""
    try:
        row = await service.propose_change(
            body.change_type,
            body.payload,
            owner_user_id=owner_user_id,
            proposed_by_agent=body.proposed_by_agent,
            conversation_id=body.conversation_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from None
    response = await _to_response(service, row)
    await service.db.commit()
    return response


@router.get("/changes", response_model=PendingChangeListResponse)
async def list_changes(
    status_filter: str | None = Query("pending", alias="status"),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PendingChangeListResponse:
    rows = await service.list_pending_changes(
        owner_user_id=owner_user_id, status=status_filter
    )
    items = [await _to_response(service, row) for row in rows]
    return PendingChangeListResponse(items=items, total=len(items))


@router.get("/changes/{change_id}", response_model=PendingChangeResponse)
async def get_change(
    change_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PendingChangeResponse:
    row = await service.get_pending_change(change_id, owner_user_id=owner_user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Change not found"
        )
    return await _to_response(service, row)


@router.post("/changes/{change_id}/approve", response_model=PendingChangeResponse)
async def approve_change(
    change_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PendingChangeResponse:
    """Execute the stored mutation - the one door into the ledger."""
    try:
        row = await service.approve_change(change_id, owner_user_id=owner_user_id)
    except ValueError as e:
        await service.db.commit()  # a recorded execution error is audit
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from None
    response = await _to_response(service, row)
    await service.db.commit()
    return response


@router.post("/changes/{change_id}/reject", response_model=PendingChangeResponse)
async def reject_change(
    change_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PendingChangeResponse:
    try:
        row = await service.reject_change(change_id, owner_user_id=owner_user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from None
    response = await _to_response(service, row)
    await service.db.commit()
    return response


@router.get("/changes/batch/{batch_id}", response_model=PendingChangeListResponse)
async def get_batch(
    batch_id: str,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PendingChangeListResponse:
    """Every row of one batch, whatever its status - the batch card's
    refresh source."""
    rows = await writes.batch_rows(service.db, batch_id, owner_user_id=owner_user_id)
    items = [await _to_response(service, row) for row in rows]
    return PendingChangeListResponse(items=items, total=len(items))


@router.post("/changes/batch/{batch_id}/approve", response_model=BatchResolveResponse)
async def approve_batch(
    batch_id: str,
    body: BatchResolveRequest,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BatchResolveResponse:
    """Approve the batch's pending rows, rejecting any vetoed ids."""
    summary = await service.approve_batch(
        batch_id, owner_user_id=owner_user_id, exclude_ids=body.exclude_ids
    )
    await service.db.commit()
    return BatchResolveResponse(**summary)


@router.post("/changes/batch/{batch_id}/reject", response_model=BatchResolveResponse)
async def reject_batch(
    batch_id: str,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> BatchResolveResponse:
    summary = await service.reject_batch(batch_id, owner_user_id=owner_user_id)
    await service.db.commit()
    return BatchResolveResponse(**summary)
