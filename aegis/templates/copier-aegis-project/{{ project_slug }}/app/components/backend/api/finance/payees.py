"""Merchants, payee groups, and merchant assignment.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

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
    MerchantAssign,
    MerchantAssignResult,
    MerchantCategorySummary,
    MerchantCreate,
    MerchantListResponse,
    MerchantMerge,
    MerchantMergeResult,
    MerchantResponse,
    MerchantUpdate,
    PayeeGroupAssign,
    PayeeGroupAssignResult,
    PayeeGroupListResponse,
    PayeeListResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


# -- Payees (merchants) ---------------------------------------------------
#
# The stable identity behind a raw bank descriptor - see FinanceService's
# own "payees (merchants)" section for why detection keys off this rather
# than the descriptor string.


@router.get("/merchants", response_model=MerchantListResponse)
async def list_merchants(
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MerchantListResponse:
    """The owner's payees (plus any global seeds), for the assign picker
    and the payee directory. Carries usage so the directory can rank by
    weight; the picker just ignores those fields."""
    from app.services.finance.domains.ledger.merchant_icon import (
        domain_from_website,
        icons_for_names,
    )

    rows = await service.list_merchants(owner_user_id=owner_user_id)
    usage = await service.merchant_usage(
        owner_user_id=owner_user_id, account_ids=account_ids
    )
    # Same resolver the register uses, so the directory shows the logo it
    # exists to let you correct - a stored address wins over the guess.
    domains = {
        m.name: domain
        for m in rows
        if (domain := domain_from_website(m.website_url)) is not None
    }
    icons = await icons_for_names(
        service.db, [m.name for m in rows], domains_by_name=domains
    )
    return MerchantListResponse(
        items=[
            MerchantResponse(
                id=m.id,
                name=m.name,
                website_url=m.website_url,
                logo_url=m.logo_url,
                default_category_id=m.default_category_id,
                transaction_count=usage.get(m.id, {}).get("count", 0),
                total_amount=usage.get(m.id, {}).get("total_amount", 0),
                last_date=usage.get(m.id, {}).get("last_date"),
                icon_b64=icons.get(m.name),
            )
            for m in rows
        ],
        total=len(rows),
    )


@router.post("/merchants/{merchant_id}/merge")
async def merge_merchants(
    merchant_id: int,
    body: MerchantMerge,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MerchantMergeResult:
    """Fold other payees into this one.

    Renaming a duplicate to match its twin does not join them - they stay
    two rows with two ids, splitting one merchant's history in half. This
    is the action that actually merges: transactions and recurring streams
    repoint to the survivor, the losers are soft deleted.
    """
    if not body.source_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one payee to merge in.",
        )
    moved = await service.merge_merchants(
        body.source_ids, merchant_id, owner_user_id=owner_user_id
    )
    await service.db.commit()
    return MerchantMergeResult(moved=moved, merged=len(body.source_ids))


@router.patch("/merchants/{merchant_id}", response_model=MerchantResponse)
async def update_merchant(
    merchant_id: int,
    body: MerchantUpdate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MerchantResponse:
    """Edit a payee directly - name, address, default category.

    The address is the one that matters day to day: the brand icon is
    resolved from it (merchant_icon.py), and guessing ``<name>.com``
    misses every other TLD and can land on a stranger's site. Until this
    existed the only way to set it was ``/payee-groups/assign``, which
    re-files the transactions it is given - so a logo fix was also a
    filing decision, and a payee with an empty backlog was uneditable.
    """
    # exclude_unset is load-bearing: it keeps "left it out" (don't touch)
    # separate from "sent null" (clear it).
    fields = body.model_dump(exclude_unset=True)
    merchant = await service.update_merchant(
        merchant_id, owner_user_id=owner_user_id, **fields
    )
    if merchant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payee not found."
        )
    await service.db.commit()
    usage = await service.merchant_usage(owner_user_id=owner_user_id)
    return MerchantResponse(
        id=merchant.id,
        name=merchant.name,
        website_url=merchant.website_url,
        logo_url=merchant.logo_url,
        default_category_id=merchant.default_category_id,
        transaction_count=usage.get(merchant.id, {}).get("count", 0),
        total_amount=usage.get(merchant.id, {}).get("total_amount", 0),
        last_date=usage.get(merchant.id, {}).get("last_date"),
    )


@router.post(
    "/merchants", response_model=MerchantResponse, status_code=status.HTTP_201_CREATED
)
async def create_merchant(
    body: MerchantCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MerchantResponse:
    """Create a payee by name. Returns the existing one on a duplicate
    name rather than erroring - the picker's "+ Create" is exactly where
    someone retypes a payee they already have."""
    try:
        merchant = await service.create_merchant(
            body.name, owner_user_id=owner_user_id, website_url=body.website_url
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MerchantResponse(
        id=merchant.id,
        name=merchant.name,
        website_url=merchant.website_url,
        logo_url=merchant.logo_url,
        default_category_id=merchant.default_category_id,
    )


@router.post("/transactions/assign-merchant")
async def assign_merchant(
    body: MerchantAssign,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MerchantAssignResult:
    """Point transactions at a payee (``merchant_id=null`` clears it).
    Returns how many rows actually changed."""
    updated = await service.assign_merchant(
        body.transaction_ids,
        body.merchant_id,
        owner_user_id=owner_user_id,
        category_id=body.category_id,
    )
    return MerchantAssignResult(updated=updated)


@router.get(
    "/merchants/{merchant_id}/category-summary",
    response_model=MerchantCategorySummary,
)
async def merchant_category_summary(
    merchant_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> MerchantCategorySummary:
    """How this payee's transactions are categorized today - pre-fills the
    "also set category" offer and reveals a payee arguing with itself."""
    return await service.merchant_category_summary(
        merchant_id, owner_user_id=owner_user_id
    )


@router.get("/payee-groups", response_model=PayeeGroupListResponse)
async def payee_groups(
    limit: int = Query(default=200, ge=1, le=2000),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PayeeGroupListResponse:
    """Payee-less transactions collapsed into named-able groups, biggest
    first - see FinanceService.payee_groups for why this is the unit of
    work rather than the rows themselves."""
    rows, total_groups, total_txns = await service.payee_groups(
        owner_user_id=owner_user_id, limit=limit
    )
    return PayeeGroupListResponse(
        items=rows,
        total=total_groups,
        total_transactions=total_txns,
    )


@router.post("/payee-groups/assign")
async def assign_payee_group(
    body: PayeeGroupAssign,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PayeeGroupAssignResult:
    """Name whole groups at once. Supply ``merchant_id`` for an existing
    payee, or ``name`` to create one; every key in ``keys`` gets it."""
    if not body.keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one key.",
        )
    merchant_id = body.merchant_id
    if merchant_id is None:
        if not body.name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide merchant_id or name.",
            )
        merchant = await service.create_merchant(
            body.name, owner_user_id=owner_user_id, website_url=body.website_url
        )
        merchant_id = merchant.id
    elif body.website_url:
        # Attaching to an existing payee AND supplying an address updates
        # that payee - the natural way to fix a wrong guess after the fact.
        await service.set_merchant_website(merchant_id, body.website_url)
    updated = await service.assign_payee_group(
        body.keys,
        merchant_id,
        owner_user_id=owner_user_id,
        category_id=body.category_id,
    )
    return PayeeGroupAssignResult(updated=updated, merchant_id=merchant_id)


@router.get("/payees", response_model=PayeeListResponse)
async def top_payees(
    days: int = Query(default=90, ge=1, le=3650),
    limit: int = Query(default=8, ge=1, le=50),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> PayeeListResponse:
    """Payees taking the most money over the window, biggest first."""
    rows = await service.top_payees(owner_user_id=owner_user_id, days=days, limit=limit)
    return PayeeListResponse(items=rows, total=len(rows))
