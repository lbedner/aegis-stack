"""The register: transactions, uncategorized, tags, bulk deletes.

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

from app.components.backend.api.finance.base import _NOT_FOUND
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.models import FinanceTransactionSplit
from app.services.finance.schemas import (
    CategorySuggestionListResponse,
    SimilarTransaction,
    SimilarTransactionListResponse,
    SplitLineResponse,
    SplitListResponse,
    SuggestCategoriesRequest,
    TagAssign,
    TagRef,
    TagRemoveResult,
    TagResponse,
    TransactionCategorize,
    TransactionDelete,
    TransactionDeleteResult,
    TransactionListResponse,
    TransactionResponse,
    TransactionSplitRequest,
    UnsplitResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


def _split_line(
    split: FinanceTransactionSplit, names: dict[int, str]
) -> SplitLineResponse:
    """A split row as its response shape, category name resolved."""
    return SplitLineResponse(
        id=split.id,
        amount=split.amount,
        category_id=split.category_id,
        category=names.get(split.category_id),
        memo=split.memo,
    )


# -- Transactions ------------------------------------------------------------


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    account_id: int | None = None,
    account_ids: list[int] | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    category_id: int | None = None,
    merchant_id: int | None = None,
    without_merchant: bool = False,
    tag_id: int | None = None,
    q: str | None = None,
    include_transfers: bool = False,
    page: int = 1,
    page_size: int = 50,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransactionListResponse:
    """Transaction feed, newest first. Excludes soft-deleted and
    duplicate-marked rows, and (by default) paired transfer legs so a card
    payment doesn't show as two lines. Filter by account, date, category, payee.
    """
    transactions, total = await service.list_transactions(
        owner_user_id=owner_user_id,
        account_id=account_id,
        account_ids=account_ids,
        from_date=from_date,
        to_date=to_date,
        category_id=category_id,
        merchant_id=merchant_id,
        without_merchant=without_merchant,
        tag_id=tag_id,
        query=q,
        include_transfers=include_transfers,
        page=page,
        page_size=page_size,
    )
    splits_by_txn = await service.transaction_splits(
        [t.id for t in transactions if t.is_split and t.id is not None]
    )
    names = await service.category_names(
        {t.category_id for t in transactions if t.category_id is not None}
        | {
            s.category_id
            for lines in splits_by_txn.values()
            for s in lines
            if s.category_id is not None
        }
    )
    payees = await service.merchant_names(
        {t.merchant_id for t in transactions if t.merchant_id is not None}
    )
    from app.services.finance.domains.ledger.merchant_icon import (
        domain_from_website,
        icons_for_names,
    )

    websites = await service.merchant_websites(
        {t.merchant_id for t in transactions if t.merchant_id is not None}
    )
    icons = await icons_for_names(
        service.db,
        [payees.get(t.merchant_id) or t.name for t in transactions],
        domains_by_name={
            payees[mid]: domain
            for mid, url in websites.items()
            if (domain := domain_from_website(url)) and mid in payees
        },
    )
    tags_by_txn = await service.transaction_tags(
        {t.id for t in transactions if t.id is not None}
    )
    items = []
    for txn in transactions:
        item = TransactionResponse.from_row(txn)
        item.category = names.get(txn.category_id)
        item.merchant = payees.get(txn.merchant_id)
        # Payee first: the raw descriptor is a bank string, the payee is
        # the thing with a brand.
        item.icon_b64 = icons.get(item.merchant or txn.name)
        item.tags = [
            TagRef(id=t.id, name=t.name, color=t.color)
            for t in tags_by_txn.get(txn.id, [])
        ]
        item.splits = [
            _split_line(s, names) for s in splits_by_txn.get(txn.id, [])
        ]
        items.append(item)
    return TransactionListResponse(items=items, total=total)


@router.get("/uncategorized", response_model=TransactionListResponse)
async def uncategorized_transactions(
    limit: int = Query(default=7, ge=1, le=5000),
    q: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransactionListResponse:
    """Transactions nothing has classified, newest first.

    ``total`` is the FULL count, not the page: the point of the card is
    how much work is waiting, and a page size would understate it.

    The default (7) stays small for the Overview card's preview; the
    Uncategorized work queue (``UncategorizedPanel``) requests a much
    higher limit so every row Auto-categorize could suggest for is
    actually visible to review - suggestions were previously computed
    for the full backlog (``suggest_categories`` is already unbounded)
    but silently discarded for any row past the old 100-row page.

    ``q`` is the same payee search ``/transactions`` already has; same
    for ``from`` (no ``to`` - this is a backlog, not a historical
    register, so there's nothing meaningful to filter above "today")
    and ``account_ids`` (the same account-scope filter Overview uses).
    """
    txns, total = await service.uncategorized_transactions(
        owner_user_id=owner_user_id,
        limit=limit,
        query=q,
        from_date=from_date,
        account_ids=account_ids,
    )
    # "Uncategorized" here means the source app's own catch-all bucket
    # counts as unclassified (see UNCATEGORIZED_CATEGORY_NAMES) - not
    # only a NULL category_id. A row from that bucket still has a real
    # category_id, so it still needs a name lookup, same as /transactions
    # does - skipping this left every row's detail popup and hover
    # tooltip with no category shown at all, even when one was assigned
    # (confirmed live: category_source "rule" with no category text).
    names = await service.category_names(
        {t.category_id for t in txns if t.category_id is not None}
    )
    payees = await service.merchant_names(
        {t.merchant_id for t in txns if t.merchant_id is not None}
    )
    items = []
    for txn in txns:
        item = TransactionResponse.from_row(txn)
        item.category = names.get(txn.category_id)
        item.merchant = payees.get(txn.merchant_id)
        items.append(item)
    return TransactionListResponse(items=items, total=total)


@router.post(
    "/transactions/{transaction_id}/categorize", response_model=TransactionResponse
)
async def categorize_transaction(
    transaction_id: int,
    body: TransactionCategorize,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransactionResponse:
    """Set a transaction's category by hand."""
    txn = await service.categorize_transaction(
        transaction_id, body.category_id, owner_user_id=owner_user_id, source="user"
    )
    if txn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    names = await service.category_names({txn.category_id})
    item = TransactionResponse.from_row(txn)
    item.category = names.get(txn.category_id)
    return item


@router.post("/transactions/{transaction_id}/split", response_model=SplitListResponse)
async def split_transaction(
    transaction_id: int,
    body: TransactionSplitRequest,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SplitListResponse:
    """Carve a transaction into category lines. Parts are positive
    magnitudes in cents; any unclaimed difference becomes a remainder
    line under the parent's own category. Replaces existing lines; the
    parent row itself is never modified."""
    try:
        lines = await service.split_transaction(
            transaction_id, body.parts, owner_user_id=owner_user_id
        )
    except ValueError as exc:
        if "not found" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            ) from None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    names = await service.category_names(
        {s.category_id for s in lines if s.category_id is not None}
    )
    return SplitListResponse(items=[_split_line(s, names) for s in lines])


@router.delete("/transactions/{transaction_id}/split", response_model=UnsplitResponse)
async def unsplit_transaction(
    transaction_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> UnsplitResponse:
    """Remove a transaction's split lines; it reports under its own
    category again."""
    try:
        removed = await service.unsplit_transaction(
            transaction_id, owner_user_id=owner_user_id
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
        ) from None
    return UnsplitResponse(removed=removed)


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[TagResponse]:
    """The tag directory: every tag with how many transactions wear it."""
    tags = await service.list_tags(owner_user_id=owner_user_id)
    return [
        TagResponse(id=t.id, name=t.name, color=t.color, transaction_count=count)
        for t, count in tags
    ]


@router.post("/transactions/tags", response_model=TagRef)
async def tag_transactions(
    body: TagAssign,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TagRef:
    """Attach a tag (created on first use) to the given transactions.

    This is the "flag" verb: the tag is whatever the user names it, so
    one mechanism covers follow-ups, trips, and audits alike."""
    tag = await service.tag_transactions(
        body.transaction_ids, body.name, owner_user_id=owner_user_id
    )
    return TagRef(id=tag.id, name=tag.name, color=tag.color)


@router.post("/transactions/delete")
async def delete_transactions(
    body: TransactionDelete,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransactionDeleteResult:
    """Soft-delete the given transactions.

    They leave the register, budgets, and projections immediately, and a
    re-import of the same file will not resurrect them (the plan refuses
    rows matching a deleted transaction, same as removed accounts). A
    transfer pair's surviving leg is unpaired; a split parent takes its
    lines with it."""
    deleted = await service.soft_delete_transactions(
        body.transaction_ids, owner_user_id=owner_user_id
    )
    return TransactionDeleteResult(deleted=deleted)


@router.delete("/transactions/{transaction_id}/tags/{tag_id}")
async def untag_transaction(
    transaction_id: int,
    tag_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TagRemoveResult:
    """Detach one tag from one transaction; the tag itself stays."""
    removed = await service.untag_transactions(
        [transaction_id], tag_id, owner_user_id=owner_user_id
    )
    return TagRemoveResult(removed=removed)


@router.get(
    "/transactions/{transaction_id}/similar",
    response_model=SimilarTransactionListResponse,
)
async def similar_transactions(
    transaction_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SimilarTransactionListResponse:
    """Payee-less lookalikes of this transaction, for the "also apply to N
    similar" offer. A suggestion the caller confirms - see
    ``FinanceService.similar_unassigned`` on why the loose key is only ever
    used here and never by detection itself."""
    rows = await service.similar_unassigned(transaction_id, owner_user_id=owner_user_id)
    return SimilarTransactionListResponse(
        items=[
            SimilarTransaction(
                id=r.id,
                date=r.date_,
                name=r.name or r.original_description or "",
                amount=r.amount,
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.post(
    "/transactions/auto-categorize", response_model=CategorySuggestionListResponse
)
async def suggest_categories(
    body: SuggestCategoriesRequest = SuggestCategoriesRequest(),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> CategorySuggestionListResponse:
    """Preview a category for every uncategorized transaction whose payee
    has a clear precedent among this owner's own past corrections - or,
    with ``transaction_ids`` set, just that subset (a checkbox selection).
    A preview only - nothing is written until the caller applies an
    accepted suggestion through the ordinary categorize endpoint."""
    return await service.suggest_categories(
        owner_user_id=owner_user_id, transaction_ids=body.transaction_ids
    )
