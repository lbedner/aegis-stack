"""Transfer pairs: list, confirm, reject.

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
    TransferListResponse,
    TransferResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


# -- Transfers ---------------------------------------------------------------


@router.get("/transfers", response_model=TransferListResponse)
async def list_transfers(
    status_filter: str | None = Query(default=None, alias="status"),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransferListResponse:
    """Matched internal transfers, newest first. Filter by ``status``
    (suggested/confirmed/rejected) — the UI polls ``?status=suggested``."""
    transfers = await service.list_transfers(
        owner_user_id=owner_user_id, status=status_filter
    )
    # Enrich each transfer with its two legs' descriptions so the review UI can
    # show "Starbucks -> INTRST PYMNT", not just account names + amount.
    leg_ids = [
        txn_id
        for transfer in transfers
        for txn_id in (transfer.from_transaction_id, transfer.to_transaction_id)
        if txn_id is not None
    ]
    legs = await service.transactions_by_ids(leg_ids)
    items = [
        TransferResponse.from_row(
            transfer,
            from_txn=legs.get(transfer.from_transaction_id),
            to_txn=legs.get(transfer.to_transaction_id),
        )
        for transfer in transfers
    ]
    return TransferListResponse(items=items, total=len(transfers))


@router.post("/transfers/{transfer_id}/confirm", response_model=TransferResponse)
async def confirm_transfer(
    transfer_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransferResponse:
    """Confirm a suggested transfer: flag both legs out of reports."""
    transfer = await service.confirm_transfer(transfer_id, owner_user_id=owner_user_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return TransferResponse.from_row(transfer)


@router.post("/transfers/{transfer_id}/reject", response_model=TransferResponse)
async def reject_transfer(
    transfer_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransferResponse:
    """Reject a transfer: both legs stay as normal spend/income and the pair is
    never re-suggested."""
    transfer = await service.reject_transfer(transfer_id, owner_user_id=owner_user_id)
    if transfer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return TransferResponse.from_row(transfer)
