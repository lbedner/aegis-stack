"""Envelopes and goals - the set-aside accounts.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from datetime import (
    UTC,
    date,
    datetime,
)
from typing import Any

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
    EnvelopeCreate,
    EnvelopeListResponse,
    EnvelopeMove,
    EnvelopeResponse,
    EnvelopeUpdate,
    GoalContribute,
    GoalCreate,
    GoalListResponse,
    GoalResponse,
    GoalUpdate,
)
from app.services.finance.service import FinanceService

router = APIRouter()


# -- Envelopes ------------------------------------------------------------
#
# Virtual sub-accounts (an allowance the kid draws down): hidden manual
# accounts whose balance and history ride valuations. Both directions,
# no target - the goals design minus the finish line.


def _envelope_response(account: Any) -> EnvelopeResponse:
    from app.services.finance.domains.planning.envelopes import envelope_metadata

    meta = envelope_metadata(account.metadata_)
    assert meta is not None  # callers only pass envelope accounts
    return EnvelopeResponse(
        account_id=account.id,
        name=account.name,
        balance=account.current_balance or 0,
        monthly_credit=meta.monthly_credit,
        auto_credit=meta.auto_credit,
        cadence=meta.cadence,
    )


@router.get("/envelopes", response_model=EnvelopeListResponse)
async def list_envelopes(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> EnvelopeListResponse:
    accounts = await service.list_envelopes(owner_user_id=owner_user_id)
    items = [_envelope_response(a) for a in accounts]
    return EnvelopeListResponse(items=items, total=len(items))


@router.post(
    "/envelopes", response_model=EnvelopeResponse, status_code=status.HTTP_201_CREATED
)
async def create_envelope(
    body: EnvelopeCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> EnvelopeResponse:
    account = await service.create_envelope(
        owner_user_id=owner_user_id,
        name=body.name,
        monthly_credit=body.monthly_credit,
        cadence=body.cadence,
        starting_balance=body.starting_balance,
    )
    return _envelope_response(account)


@router.patch("/envelopes/{account_id}", response_model=EnvelopeResponse)
async def update_envelope(
    account_id: int,
    body: EnvelopeUpdate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> EnvelopeResponse:
    account = await service.update_envelope(
        account_id,
        owner_user_id=owner_user_id,
        monthly_credit=body.monthly_credit,
        auto_credit=body.auto_credit,
        cadence=body.cadence,
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return _envelope_response(account)


@router.delete("/envelopes/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_envelope(
    account_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> None:
    from app.services.finance.domains.planning.envelopes import envelope_metadata

    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None or envelope_metadata(account.metadata_) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    await service.soft_delete_account(account_id, owner_user_id=owner_user_id)


@router.post("/envelopes/{account_id}/credit", response_model=EnvelopeResponse)
async def credit_envelope(
    account_id: int,
    body: EnvelopeMove,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> EnvelopeResponse:
    try:
        account = await service.credit_envelope(
            account_id,
            amount=body.amount,
            owner_user_id=owner_user_id,
            when=body.when,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _envelope_response(account)


@router.post("/envelopes/{account_id}/spend", response_model=EnvelopeResponse)
async def spend_from_envelope(
    account_id: int,
    body: EnvelopeMove,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> EnvelopeResponse:
    try:
        account = await service.spend_from_envelope(
            account_id,
            amount=body.amount,
            owner_user_id=owner_user_id,
            when=body.when,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _envelope_response(account)


# -- Goals ----------------------------------------------------------------
#
# . A goal is an account wearing goal metadata; these
# endpoints assemble GoalResponse from account + metadata + the derived
# trio (progress / monthly_need / eta), all precomputed server-side.


def _probe_goal_rule(body: GoalCreate) -> None:
    """Fail a bad rule combination (percent without bps) BEFORE any account
    is created - the metadata contract's own validator is the authority."""
    from app.services.finance.domains.planning.goals import set_goal_metadata

    set_goal_metadata(
        None,
        target_amount=body.target_amount,
        target_date=body.target_date,
        monthly_contribution=body.monthly_contribution,
        contribution_kind=body.contribution_kind,
        contribution_bps=body.contribution_pct_bps,
        priority=body.priority,
    )


async def _goal_response(
    service: FinanceService,
    account: Any,
    *,
    today: date | None = None,
    allocations: dict[int, int] | None = None,
    rates: dict[int, int | None] | None = None,
) -> GoalResponse:
    """``allocations`` is the engine's run over the WHOLE goal set (surplus
    rules depend on the other goals) - a caller without one in hand lets
    this fetch it."""
    from app.services.finance.domains.planning.goals import (
        GOAL_ACCOUNT_TYPE,
        goal_auto_contribute,
        goal_eta,
        goal_metadata,
        goal_progress,
    )

    meta = goal_metadata(account.metadata_)
    assert meta is not None  # callers only pass goal-wearing accounts
    now = today or datetime.now(UTC).date()
    balance = account.current_balance or 0
    if allocations is None:
        allocations = await service.goal_allocations(
            owner_user_id=account.owner_user_id, today=now
        )
    ask = allocations.get(account.id, 0)
    # The evaluated ask IS the plan's saving rate; only a goal asking
    # nothing falls back to the observed trailing rate.
    if ask > 0:
        rate = ask
    elif rates is not None:
        rate = rates.get(account.id)
    else:
        rate = await service.goal_rate(account, today=now)
    return GoalResponse(
        account_id=account.id,
        name=account.name,
        funding="virtual" if account.account_type == GOAL_ACCOUNT_TYPE else "linked",
        status=meta.status,
        target_amount=meta.target_amount,
        target_date=meta.target_date,
        monthly_contribution=meta.monthly_contribution,
        balance=balance,
        progress=goal_progress(balance=balance, target=meta.target_amount),
        monthly_need=ask,
        eta=goal_eta(
            balance=balance,
            target=meta.target_amount,
            monthly_rate=rate,
            today=now,
        ),
        auto_contribute=goal_auto_contribute(account.metadata_),
        contribution_kind=meta.contribution_kind,
        contribution_pct_bps=meta.contribution_bps,
        priority=meta.priority,
    )


@router.get("/goals", response_model=GoalListResponse)
async def list_goals(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> GoalListResponse:
    """Every goal, virtual and linked alike (virtual goal accounts are
    hidden from /accounts; this is their front door)."""
    accounts = await service.list_goals(owner_user_id=owner_user_id)
    today = datetime.now(UTC).date()
    allocations = await service.goal_allocations(
        owner_user_id=owner_user_id, today=today
    )
    # One snapshot fetch covers every goal's observed rate - never one per row.
    rates = await service.goal_rates(accounts, today=today)
    items = [
        await _goal_response(service, a, allocations=allocations, rates=rates)
        for a in accounts
    ]
    return GoalListResponse(items=items, total=len(items))


@router.post("/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    body: GoalCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> GoalResponse:
    """A virtual goal by name, or flag an existing account (linked) by id."""
    if (body.name is None) == (body.account_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of name (virtual) or account_id (linked).",
        )
    try:
        _probe_goal_rule(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if body.account_id is not None:
        account = await service.flag_account_as_goal(
            body.account_id,
            owner_user_id=owner_user_id,
            target_amount=body.target_amount,
            target_date=body.target_date,
            monthly_contribution=body.monthly_contribution,
            contribution_kind=body.contribution_kind,
            contribution_bps=body.contribution_pct_bps,
            priority=body.priority,
        )
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )
    else:
        account = await service.create_virtual_goal(
            owner_user_id=owner_user_id,
            name=body.name,
            target_amount=body.target_amount,
            target_date=body.target_date,
            monthly_contribution=body.monthly_contribution,
            contribution_kind=body.contribution_kind,
            contribution_bps=body.contribution_pct_bps,
            priority=body.priority,
        )
    if body.auto_contribute:
        from app.services.finance.domains.planning.goals import set_auto_contribute

        account.metadata_ = set_auto_contribute(account.metadata_, True)
        service.db.add(account)
        await service.db.flush()
    return await _goal_response(service, account)


@router.patch("/goals/{account_id}", response_model=GoalResponse)
async def update_goal(
    account_id: int,
    body: GoalUpdate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> GoalResponse:
    """Partial update of targets/status; unknown statuses die in the schema."""
    from app.services.finance.domains.planning.goals import (
        goal_metadata,
        set_auto_contribute,
        set_goal_metadata,
    )

    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    meta = goal_metadata(account.metadata_) if account is not None else None
    if account is None or meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    account.metadata_ = set_goal_metadata(
        account.metadata_,
        target_amount=(
            body.target_amount if body.target_amount is not None else meta.target_amount
        ),
        target_date=(
            body.target_date if body.target_date is not None else meta.target_date
        ),
        monthly_contribution=(
            body.monthly_contribution
            if body.monthly_contribution is not None
            else meta.monthly_contribution
        ),
        status=body.status if body.status is not None else meta.status,
        contribution_kind=(
            body.contribution_kind
            if body.contribution_kind is not None
            else meta.contribution_kind
        ),
        contribution_bps=(
            body.contribution_pct_bps
            if body.contribution_pct_bps is not None
            else meta.contribution_bps
        ),
        priority=body.priority if body.priority is not None else meta.priority,
    )
    if body.auto_contribute is not None:
        account.metadata_ = set_auto_contribute(account.metadata_, body.auto_contribute)
    service.db.add(account)
    await service.db.flush()
    return await _goal_response(service, account)


@router.delete("/goals/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    account_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> None:
    """Virtual goal: soft-delete the account. Linked goal: unflag - the
    real account survives, untouched."""
    from app.services.finance.domains.planning.goals import (
        GOAL_ACCOUNT_TYPE,
        goal_metadata,
    )

    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None or goal_metadata(account.metadata_) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    if account.account_type == GOAL_ACCOUNT_TYPE:
        await service.soft_delete_account(account_id, owner_user_id=owner_user_id)
    else:
        await service.unflag_goal(account_id, owner_user_id=owner_user_id)


@router.post("/goals/{account_id}/contribute", response_model=GoalResponse)
async def contribute_to_goal(
    account_id: int,
    body: GoalContribute,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> GoalResponse:
    """Assign money to a virtual goal. Linked goals refuse: their
    contributions are their own real transfers."""
    from app.services.finance.domains.planning.goals import goal_metadata

    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None or goal_metadata(account.metadata_) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    try:
        account = await service.contribute_to_goal(
            account_id, amount=body.amount, owner_user_id=owner_user_id, when=body.when
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return await _goal_response(service, account)
