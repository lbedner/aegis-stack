"""Goals - the set-aside accounts with a finish line.

One sub-router of the finance API (see ``router.py``, the aggregator).
A goal is an account wearing goal metadata; these endpoints assemble
GoalResponse from account + metadata + the derived trio (progress /
monthly_need / eta), all precomputed server-side.
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
    Query,
    status,
)

from app.components.backend.api.finance.base import _NOT_FOUND
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.domains.planning.allocation import MonthlyFigures
from app.services.finance.schemas import (
    GoalContribute,
    GoalCreate,
    GoalListResponse,
    GoalResponse,
    GoalTargetPreview,
    GoalUpdate,
)
from app.services.finance.service import FinanceService

router = APIRouter()


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
        # A relative rule sizes itself; the probe only needs a positive
        # placeholder to exercise the contract's own validator.
        target_amount=body.target_amount or 1,
        target_rule=body.target_rule,
        target_factor=body.target_factor,
        target_scope=body.target_scope,
        target_date=body.target_date,
        monthly_contribution=body.monthly_contribution,
        contribution_kind=body.contribution_kind,
        contribution_bps=body.contribution_pct_bps,
        priority=body.priority,
    )


async def _new_goal_target(
    service: FinanceService,
    body: GoalCreate,
    *,
    owner_user_id: int | None,
    today: date,
) -> int:
    """The cents a new goal stores: its own figure under a fixed target,
    the resolved rule under a relative one.

    A relative goal on a book with no bills and no budget lines has
    nothing to resolve against, so it is refused with the reason rather
    than stored as a target of zero.
    """
    from app.services.finance.domains.planning.allocation import target_for_rule

    if body.target_rule == "fixed":
        if body.target_amount is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A fixed goal needs target_amount.",
            )
        return body.target_amount
    figures = await service.goal_month_figures(owner_user_id=owner_user_id, today=today)
    resolved = target_for_rule(
        rule=body.target_rule,
        factor=body.target_factor,
        figures=figures,
        scope=tuple(body.target_scope),
    )
    if resolved <= 0:
        if body.target_amount is not None:
            return body.target_amount
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "These accounts carry no bills or budget lines to size a "
                "goal against. Add them first, widen the scope, or set a "
                "fixed target_amount."
            ),
        )
    return resolved


async def _goal_response(
    service: FinanceService,
    account: Any,
    *,
    today: date | None = None,
    allocations: dict[int, int] | None = None,
    rates: dict[int, int | None] | None = None,
    figures: MonthlyFigures | None = None,
) -> GoalResponse:
    """``allocations`` is the engine's run over the WHOLE goal set (surplus
    rules depend on the other goals) - a caller without one in hand lets
    this fetch it. ``figures`` is what a relative target resolves against;
    the listing fetches it once for every row."""
    from app.services.finance.domains.planning.allocation import resolved_meta
    from app.services.finance.domains.planning.goals import (
        GOAL_ACCOUNT_TYPE,
        goal_auto_contribute,
        goal_eta,
        goal_metadata,
        goal_progress,
    )

    stored = goal_metadata(account.metadata_)
    assert stored is not None  # callers only pass goal-wearing accounts
    now = today or datetime.now(UTC).date()
    if figures is None:
        figures = await service.goal_month_figures(
            owner_user_id=account.owner_user_id, today=now
        )
    # Resolved here, not read from storage: a months-of-expenses target
    # moves with the month's figures, and progress/ETA must move with it.
    meta = resolved_meta(stored, figures)
    balance = account.current_balance or 0
    if allocations is None:
        allocations = await service.goal_allocations(
            owner_user_id=account.owner_user_id, today=now, figures=figures
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
        target_rule=meta.target_rule,
        target_factor=meta.target_factor,
        target_scope=meta.target_scope,
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


@router.get("/goals/target-preview", response_model=GoalTargetPreview)
async def preview_goal_target(
    factor: int = Query(gt=0, le=120),
    rule: str = Query(default="months_of_expenses"),
    scope: list[int] = Query(default=[]),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> GoalTargetPreview:
    """The dialog asks the server what a rule resolves to, rather than
    doing the arithmetic itself - the preview and the saved goal come out
    of the same function, so they cannot disagree."""
    from app.services.finance.domains.planning.allocation import target_for_rule

    figures = await service.goal_month_figures(
        owner_user_id=owner_user_id, today=datetime.now(UTC).date()
    )
    return GoalTargetPreview(
        expenses=figures.expenses_for(tuple(scope)),
        target_amount=target_for_rule(
            rule=rule, factor=factor, figures=figures, scope=tuple(scope)
        ),
        scope=scope,
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
    # One fetch of the month's figures for the page: every relative
    # target on it resolves against the same numbers, and the engine
    # below is handed them rather than querying for them again.
    figures = await service.goal_month_figures(owner_user_id=owner_user_id, today=today)
    allocations = await service.goal_allocations(
        owner_user_id=owner_user_id, today=today, figures=figures
    )
    # One snapshot fetch covers every goal's observed rate - never one per row.
    rates = await service.goal_rates(accounts, today=today)
    items = [
        await _goal_response(
            service, a, allocations=allocations, rates=rates, figures=figures
        )
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
    today = datetime.now(UTC).date()
    target_amount = await _new_goal_target(
        service, body, owner_user_id=owner_user_id, today=today
    )
    if body.account_id is not None:
        account = await service.flag_account_as_goal(
            body.account_id,
            owner_user_id=owner_user_id,
            target_amount=target_amount,
            target_date=body.target_date,
            monthly_contribution=body.monthly_contribution,
            contribution_kind=body.contribution_kind,
            contribution_bps=body.contribution_pct_bps,
            priority=body.priority,
            target_rule=body.target_rule,
            target_factor=body.target_factor,
            target_scope=body.target_scope,
        )
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )
    else:
        account = await service.create_virtual_goal(
            owner_user_id=owner_user_id,
            name=body.name,
            target_amount=target_amount,
            target_date=body.target_date,
            monthly_contribution=body.monthly_contribution,
            contribution_kind=body.contribution_kind,
            contribution_bps=body.contribution_pct_bps,
            priority=body.priority,
            target_rule=body.target_rule,
            target_factor=body.target_factor,
            target_scope=body.target_scope,
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
    rule = body.target_rule if body.target_rule is not None else meta.target_rule
    factor = (
        body.target_factor if body.target_factor is not None else meta.target_factor
    )
    scope = body.target_scope if body.target_scope is not None else meta.target_scope
    if rule == "fixed":
        factor = None
        scope = []
    stored_target = (
        body.target_amount if body.target_amount is not None else meta.target_amount
    )
    if rule != "fixed":
        from app.services.finance.domains.planning.allocation import target_for_rule

        figures = await service.goal_month_figures(
            owner_user_id=owner_user_id, today=datetime.now(UTC).date()
        )
        stored_target = (
            target_for_rule(
                rule=rule, factor=factor, figures=figures, scope=tuple(scope)
            )
            or stored_target
        )
    account.metadata_ = set_goal_metadata(
        account.metadata_,
        target_amount=stored_target,
        target_rule=rule,
        target_factor=factor,
        target_scope=scope,
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
