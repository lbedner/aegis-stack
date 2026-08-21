"""Accounts: list, edit, delete, reconcile, valuations.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.components.backend.api.finance.base import _NOT_FOUND
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.schemas import (
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
    ManualAccountCreate,
    ReconcileRequest,
    ReconcileResponse,
    ValuationCreateRequest,
    ValuationListResponse,
    ValuationResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


# -- Accounts ----------------------------------------------------------------


@router.post(
    "/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED
)
async def create_account(
    body: ManualAccountCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> AccountResponse:
    """Create a manual account (``is_manual=true``, no provider connection)."""
    account = await service.create_manual_account(
        owner_user_id=owner_user_id,
        name=body.name,
        account_type=body.account_type,
        classification=body.classification,
        current_balance=body.current_balance,
        currency=body.currency,
        institution_id=body.institution_id,
    )
    return AccountResponse.from_row(account)


@router.get("/accounts", response_model=AccountListResponse)
async def list_accounts(
    include_hidden: bool = False,
    page: int = 1,
    page_size: int = 50,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> AccountListResponse:
    """List the caller's accounts (soft-deleted rows excluded)."""
    accounts, total = await service.list_accounts(
        owner_user_id=owner_user_id,
        include_hidden=include_hidden,
        page=page,
        page_size=page_size,
    )
    # Scope the balance aggregate to just this page's accounts.
    page_ids = [account.id for account in accounts]
    totals = await service.account_transaction_totals(
        owner_user_id=owner_user_id,
        account_ids=page_ids,
    )
    liabilities = await service.liability_details(page_ids)
    return AccountListResponse(
        items=[
            AccountResponse.from_row(
                a,
                activity_balance=totals.get(a.id, 0),
                liability=liabilities.get(a.id),
            )
            for a in accounts
        ],
        total=total,
    )


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    body: AccountUpdate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> AccountResponse:
    """Rename / hide / close an account."""
    account = await service.update_account(
        account_id,
        owner_user_id=owner_user_id,
        name=body.name,
        is_hidden=body.is_hidden,
        is_closed=body.is_closed,
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return AccountResponse.from_row(account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> None:
    """Soft-delete an account (the row survives; it drops from listings)."""
    deleted = await service.soft_delete_account(account_id, owner_user_id=owner_user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)


@router.post("/accounts/{account_id}/reconcile", response_model=ReconcileResponse)
async def reconcile_account(
    account_id: int,
    body: ReconcileRequest,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ReconcileResponse:
    """Reconcile the account to a statement balance (FIN-37).

    ``preview=true`` returns the register-vs-statement delta with no
    writes; otherwise the delta lands as one transfer-flagged adjustment
    (or a valuation for a register-less account), the account's
    ``reconciled_through`` waterline is stamped, and net-worth snapshots
    recompute from the statement date forward. Re-reconciling a date
    replaces its adjustment; a zero delta removes it.
    """
    if body.preview:
        result = await service.reconcile_preview(
            account_id,
            owner_user_id=owner_user_id,
            statement_date=body.statement_date,
            statement_balance=body.statement_balance,
        )
    else:
        result = await service.reconcile_account(
            account_id,
            owner_user_id=owner_user_id,
            statement_date=body.statement_date,
            statement_balance=body.statement_balance,
        )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    if not body.preview:
        await service.db.commit()
    return result


# -- Valuations --------------------------------------------------------------


@router.post(
    "/accounts/{account_id}/valuations",
    response_model=ValuationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_valuation(
    account_id: int,
    body: ValuationCreateRequest,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ValuationResponse:
    """Add or update a dated value mark; account ``current_balance`` follows the
    latest-dated valuation. Repeating a (date, source) updates in place."""
    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    valuation = await service.upsert_valuation(
        account_id=account_id,
        owner_user_id=owner_user_id,
        as_of_date=body.as_of_date,
        value=body.value,
        source=body.source,
        note=body.note,
    )
    return ValuationResponse.from_row(valuation)


@router.get("/accounts/{account_id}/valuations", response_model=ValuationListResponse)
async def list_valuations(
    account_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ValuationListResponse:
    """The account's valuation series, oldest first."""
    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    valuations = await service.list_valuations(account_id, owner_user_id=owner_user_id)
    return ValuationListResponse(
        items=[ValuationResponse.from_row(v) for v in valuations],
        total=len(valuations),
    )
