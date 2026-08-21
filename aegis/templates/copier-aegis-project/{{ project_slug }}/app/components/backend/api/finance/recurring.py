"""Recurring streams: list, edit, lifecycle verbs, rescan, projection.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from datetime import (
    date,
    timedelta,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel

from app.components.backend.api.finance.base import _NOT_FOUND
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.domains.detection.insights.commitments import (
    commitment_rollup,
    stream_staleness,
)
from app.services.finance.schemas import (
    ProjectionResponse,
    RecurringAttach,
    RecurringCategorize,
    RecurringCategorizeResult,
    RecurringListResponse,
    RecurringPause,
    RecurringRescanResult,
    RecurringStreamCreate,
    RecurringStreamResponse,
    RecurringStreamUpdate,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


# -- Recurring & insights ----------------------------------------------------


@router.get("/recurring", response_model=RecurringListResponse)
async def list_recurring(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringListResponse:
    """Detected recurring streams, soonest-due first, plus the monthly-cost
    rollup (monthly-equivalent of all recurring outflows).

    Streams whose members are internal-transfer legs (a monthly card
    autopay) are excluded entirely - they are money moved, not bills, and
    one of them can inflate the rollup by a five-figure fiction.
    """
    from app.core.config import settings
    from app.services.finance.domains.ledger.merchant_icon import (
        domain_from_website,
        icons_for_names,
    )

    streams = await service.list_recurring(owner_user_id=owner_user_id)
    transfer_ids = await service.transfer_stream_ids([s.id for s in streams])
    # Payment streams (card/loan autopay) are the carve-out from the
    # transfer exclusion: they stay VISIBLE - a payment has to be
    # confirmable here or it can never reach the cash forecast - but out
    # of the rollup below, because the card's swipes already counted and
    # the payment would double-count the whole statement.
    payment_ids = await service.payment_stream_ids(list(transfer_ids))
    streams = [s for s in streams if s.id not in transfer_ids or s.id in payment_ids]
    # The rollup counts COMMITMENTS only (declared, confirmed, subscription,
    # or fixed-amount at a bill cadence). Summing every detected merchant
    # rhythm reads hundreds of shopping habits as "recurring bills" and
    # produces a five-figure monthly fiction.
    monthly = commitment_rollup([s for s in streams if s.id not in payment_ids])[
        "monthly_total"
    ]
    # Display names in one query each, so the Bills & Income table can show
    # where a stream draws from and what it is filed under.
    category_names = await service.stream_category_names({s.id for s in streams})
    # A stream that has been attributed to a payee takes the PAYEE's name
    # for its icon, not its own: the stream name is whatever descriptor the
    # detector last saw ("YOUTUBEPREMI G.CO/HELPPAY# CA XXXX3007"), while
    # the payee is the thing that actually has a brand ("Google"). Falls
    # back to the stream name for anything not yet named.
    payee_names = await service.merchant_names(
        {s.merchant_id for s in streams if s.merchant_id is not None}
    )
    accounts, _ = await service.list_accounts(
        owner_user_id=owner_user_id, page_size=500
    )
    account_names = {a.id: a.name for a in accounts}
    # Same lookback floor generate_insights computes for _missed_recurring -
    # a stream reading "stale" here is exactly the set that rule already
    # treats as a zombie rather than a live bill (see stream_staleness).
    websites = await service.merchant_websites(
        {s.merchant_id for s in streams if s.merchant_id is not None}
    )
    icons = await icons_for_names(
        service.db,
        [payee_names.get(s.merchant_id) or s.name for s in streams],
        domains_by_name={
            payee_names[mid]: domain
            for mid, url in websites.items()
            if (domain := domain_from_website(url)) and mid in payee_names
        },
    )
    today = date.today()
    floor = (
        today - timedelta(days=settings.FINANCE_RULES_LOOKBACK_DAYS)
        if settings.FINANCE_RULES_LOOKBACK_DAYS
        else None
    )
    return RecurringListResponse(
        items=[
            RecurringStreamResponse.from_row(
                s,
                account_name=account_names.get(s.account_id),
                category_name=category_names.get(s.id),
                icon_b64=icons.get(payee_names.get(s.merchant_id) or s.name),
                staleness=stream_staleness(s, today, floor),
                is_payment=s.id in payment_ids,
            )
            for s in streams
        ],
        total=len(streams),
        monthly_cost=int(monthly),
    )


@router.post("/recurring/rescan")
async def rescan_recurring(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringRescanResult:
    """Re-run detection over the current ledger.

    Detection is what attaches a PAYEE to a stream: it groups by
    ``merchant_id`` when transactions have one (domains/detection/recurring/cadence.py),
    so a payee named after the last nightly pass is invisible to Bills &
    Income until this runs - the bill keeps showing whatever descriptor
    the detector last saw, and its icon keeps being guessed from that
    instead of the payee. Otherwise this only happens nightly or after a
    sync/import, which is a long time to wait to see your own naming take
    effect.
    """
    from app.services.finance.domains.detection import (
        detect_recurring,
        promote_curated_streams,
    )

    result = await detect_recurring(service.db, owner_user_id=owner_user_id)
    await promote_curated_streams(service.db, owner_user_id=owner_user_id)
    await service.db.commit()
    return RecurringRescanResult(detected=result.detected, pruned=result.pruned)


@router.get("/recurring/projection", response_model=ProjectionResponse)
async def recurring_projection(
    days: int = Query(default=180, ge=1, le=730),
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ProjectionResponse:
    """Projected cash balance: today's balance walked forward through
    scheduled bills (commitments) and income over the next ``days``.

    ``account_ids`` narrows it to the dialog's account filter - the same
    param the transaction endpoints take."""
    return await service.project_balances(
        owner_user_id=owner_user_id, days=days, account_ids=account_ids
    )


@router.post(
    "/recurring",
    response_model=RecurringStreamResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recurring(
    body: RecurringStreamCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Declare a bill (outflow) or income (inflow) stream by hand.

    Hand-entered streams are commitments: the missed-payment rule chases
    them at any cadence, unlike detected merchant rhythms.
    """
    if body.account_id is not None:
        account = await service.get_account(
            body.account_id, owner_user_id=owner_user_id
        )
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )
    stream = await service.create_recurring_stream(
        owner_user_id=owner_user_id,
        name=body.name,
        direction=body.direction,
        frequency=body.frequency,
        expected_amount=body.expected_amount,
        next_expected_date=body.next_expected_date,
        account_id=body.account_id,
        is_subscription=body.is_subscription,
    )
    return RecurringStreamResponse.from_row(stream)


@router.patch("/recurring/{stream_id}", response_model=RecurringStreamResponse)
async def update_recurring(
    stream_id: int,
    body: RecurringStreamUpdate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Edit a stream's declared facts; omitted fields are left alone."""
    try:
        stream = await service.update_recurring(
            stream_id,
            owner_user_id=owner_user_id,
            name=body.name,
            frequency=body.frequency,
            expected_amount=body.expected_amount,
            next_expected_date=body.next_expected_date,
            category_id=body.category_id,
            account_id=body.account_id,
        )
    except ValueError as exc:
        # Moving onto an account that already has this bill - a conflict
        # the user can resolve, not a server fault.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)


@router.post("/recurring/categorize")
async def categorize_recurring(
    body: RecurringCategorize,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringCategorizeResult:
    """Set one category across several bills.

    The bills only: their member transactions keep whatever categories
    they already carry, because a bill's category is otherwise inferred
    from them and a cascade would overwrite corrections made by hand.
    """
    if not body.stream_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one bill.",
        )
    updated = 0
    for stream_id in body.stream_ids:
        stream = await service.update_recurring(
            stream_id, owner_user_id=owner_user_id, category_id=body.category_id
        )
        if stream is not None:
            updated += 1
    await service.db.commit()
    return RecurringCategorizeResult(updated=updated)


@router.delete("/recurring/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring(
    stream_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> None:
    """Soft-delete a bill/income stream (the row survives; it drops from
    listings). A detected rhythm that keeps firing on import may be
    re-found by the detector, but it comes back muted."""
    deleted = await service.delete_recurring(stream_id, owner_user_id=owner_user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)


@router.get(
    "/recurring/{stream_id}/match-candidates", response_model=TransactionListResponse
)
async def recurring_match_candidates(
    stream_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TransactionListResponse:
    """Unclaimed transactions that could be this bill's payment - the
    shortlist for the manual match when the automatic matcher could not
    connect them (changed descriptor, hand-entered bill)."""
    rows = await service.recurring_match_candidates(
        stream_id, owner_user_id=owner_user_id
    )
    items = await _candidate_items(service, rows)
    return TransactionListResponse(items=items, total=len(items))


async def _candidate_items(
    service: FinanceService, rows: list
) -> list[TransactionResponse]:
    """Match candidates as enriched responses - shared by the single-bill
    shortlist and the review queue."""
    names = await service.category_names(
        {t.category_id for t in rows if t.category_id is not None}
    )
    payees = await service.merchant_names(
        {t.merchant_id for t in rows if t.merchant_id is not None}
    )
    items = []
    for t in rows:
        # Build-then-assign, the same shape every transaction listing
        # here uses - from_row takes no enrichment kwargs.
        item = TransactionResponse.from_row(t)
        item.category = names.get(t.category_id)
        item.merchant = payees.get(t.merchant_id)
        items.append(item)
    return items


class ReviewQueueEntry(BaseModel):
    stream_id: int
    candidates: list[TransactionResponse]


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueEntry]


@router.get("/recurring/review-queue", response_model=ReviewQueueResponse)
async def recurring_review_queue(
    ids: str,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ReviewQueueResponse:
    """Shortlists for a whole review session in one call.

    The client sends the bills IT considers past due (one definition of
    "needs review", owned by the UI); the answer carries each bill's
    candidates, and bills with none are omitted - a review session walks
    matches, never no-candidates cards. Bounded loop over the tested
    single-bill matcher on purpose: batching its per-stream windows and
    bands into one query would fork the logic this shortlist just got
    right.
    """
    try:
        stream_ids = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ids must be a comma-separated list of stream ids",
        ) from exc
    entries: list[ReviewQueueEntry] = []
    for stream_id in stream_ids[:50]:
        rows = await service.recurring_match_candidates(
            stream_id, owner_user_id=owner_user_id
        )
        if not rows:
            continue
        entries.append(
            ReviewQueueEntry(
                stream_id=stream_id,
                candidates=await _candidate_items(service, rows),
            )
        )
    return ReviewQueueResponse(items=entries)


@router.post("/recurring/{stream_id}/attach", response_model=RecurringStreamResponse)
async def attach_recurring_payment(
    stream_id: int,
    body: RecurringAttach,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Reconcile a transaction with the bill it paid: consumes the
    occurrence (due date steps forward, nag stops) and teaches the payee
    key so future months match on their own."""
    stream = await service.attach_transaction_to_stream(
        body.transaction_id, stream_id, owner_user_id=owner_user_id
    )
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)


@router.post("/recurring/{stream_id}/pause", response_model=RecurringStreamResponse)
async def pause_recurring(
    stream_id: int,
    body: RecurringPause,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Pause a stream until a date: out of the forecast, the Bills total,
    the month verdict and every nag until then, back on its own the day
    the date passes. ``note`` is the why, shown wherever the pause is."""
    stream = await service.pause_recurring(
        stream_id, until=body.until, note=body.note, owner_user_id=owner_user_id
    )
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)


@router.post("/recurring/{stream_id}/resume", response_model=RecurringStreamResponse)
async def resume_recurring(
    stream_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """End a pause early (the note goes with it)."""
    stream = await service.resume_recurring(stream_id, owner_user_id=owner_user_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)


@router.post("/recurring/{stream_id}/mute", response_model=RecurringStreamResponse)
async def mute_recurring(
    stream_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Mute a stream so it stops raising price-hike insights."""
    stream = await service.mute_recurring(stream_id, owner_user_id=owner_user_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)


@router.post("/recurring/{stream_id}/unmute", response_model=RecurringStreamResponse)
async def unmute_recurring(
    stream_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Reverse a mute."""
    stream = await service.unmute_recurring(stream_id, owner_user_id=owner_user_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)


@router.post("/recurring/{stream_id}/confirm", response_model=RecurringStreamResponse)
async def confirm_recurring(
    stream_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> RecurringStreamResponse:
    """Promote a detected stream to a confirmed commitment."""
    stream = await service.confirm_recurring(stream_id, owner_user_id=owner_user_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return RecurringStreamResponse.from_row(stream)
