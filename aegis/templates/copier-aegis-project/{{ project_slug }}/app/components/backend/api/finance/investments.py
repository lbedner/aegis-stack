"""Holdings, trades, securities, and the investment import.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from datetime import (
    UTC,
    date,
    datetime,
)

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.finance.base import (
    _INVESTMENT_IMPORT_PROFILES,
    _MAX_IMPORT_BYTES,
    _NOT_FOUND,
)
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.domains.investments.securities import market_value_cents
from app.services.finance.schemas import (
    HoldingCreate,
    HoldingListResponse,
    HoldingResponse,
    InvestmentImportPosition,
    InvestmentImportPreviewResponse,
    InvestmentImportResultResponse,
    SecurityCreate,
    SecurityResponse,
    TradeListResponse,
    TradeResponse,
)
from app.services.finance.service import FinanceService

router = APIRouter()


@router.post(
    "/accounts/{account_id}/holdings",
    response_model=HoldingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_holding(
    account_id: int,
    body: HoldingCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> HoldingResponse:
    """Add or update a position (security resolved/created by ticker). Repeating
    an (account, security, date) updates it in place."""
    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    security = await service.get_or_create_security(
        ticker=body.ticker, name=body.name, security_type=body.security_type
    )
    holding = await service.upsert_holding(
        owner_user_id=owner_user_id,
        account_id=account_id,
        security_id=security.id,
        as_of_date=body.as_of_date or datetime.now(UTC).date(),
        quantity_e8=round(body.quantity * 100_000_000),
        price=body.price,
        cost_basis=body.cost_basis,
    )
    price = holding.price if holding.price is not None else security.close_price
    value = market_value_cents(holding.quantity_e8, price, holding.price_scale)
    return HoldingResponse.from_parts(holding, security, value)


@router.get("/accounts/{account_id}/holdings", response_model=HoldingListResponse)
async def list_account_holdings(
    account_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> HoldingListResponse:
    """Current positions in an account, with per-holding + total market value."""
    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    holdings = await service.list_current_holdings(
        owner_user_id=owner_user_id, account_id=account_id
    )
    items = [HoldingResponse.from_parts(h, s, v) for h, s, v in holdings]
    await _attach_holding_icons(service.db, items)
    return HoldingListResponse(
        items=items,
        total=len(items),
        portfolio_value=sum(item.market_value for item in items),
    )


async def _read_investment_ledger(file: UploadFile, profile: str) -> list:
    """Shared parse step for the investment preview and commit endpoints:
    profile gate, size gate, then parse - with each failure mapped to the
    HTTP status the register import uses for the same class of problem."""
    from app.services.finance.domains.investments.optum import (
        UnknownActivityTypeError,
        parse_optum_settled_transactions,
    )

    if profile not in _INVESTMENT_IMPORT_PROFILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown profile {profile!r}. Known: {_INVESTMENT_IMPORT_PROFILES}.",
        )
    data = await file.read()
    if len(data) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 10 MB).",
        )
    try:
        return parse_optum_settled_transactions(data.decode("utf-8-sig"))
    except UnknownActivityTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/import-investments/preview",
    response_model=InvestmentImportPreviewResponse,
)
async def preview_import_investments(
    file: UploadFile = File(...),
    profile: str = "optum",
) -> InvestmentImportPreviewResponse:
    """Parse a custodian activity ledger and report what it carries -
    row count, date range, and the replayed ending positions - without
    touching the database. The dialog between file pick and commit runs
    on this, so the account choice is made looking at real numbers.
    """
    activities = await _read_investment_ledger(file, profile)
    from app.services.finance.domains.investments.activity import replay_positions

    # Value each position at its security's last ledger price - the same
    # mark the loader will store, and the freshest one the file itself
    # can honestly claim (not a live quote).
    last_price: dict[str, float] = {}
    last_date_seen: dict[str, date] = {}
    for activity in activities:
        prior = last_date_seen.get(activity.security_name)
        if prior is None or activity.trade_date >= prior:
            last_date_seen[activity.security_name] = activity.trade_date
            last_price[activity.security_name] = float(activity.price)
    positions = [
        InvestmentImportPosition(
            name=name,
            shares=float(shares),
            value=round(float(shares) * last_price[name] * 100),
        )
        for name, shares in sorted(replay_positions(activities).items())
    ]
    return InvestmentImportPreviewResponse(
        activities_parsed=len(activities),
        first_date=min(a.trade_date for a in activities),
        last_date=max(a.trade_date for a in activities),
        total_value=sum(p.value for p in positions),
        positions=positions,
    )


@router.post("/import-investments", response_model=InvestmentImportResultResponse)
async def import_investments(
    file: UploadFile = File(...),
    account_id: int | None = None,
    account_name: str | None = None,
    profile: str = "optum",
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> InvestmentImportResultResponse:
    """Upload a custodian activity ledger (trades/dividends/fees) into a
    brokerage account. The investments counterpart to ``/import``: writes
    ``FinanceTrade``/``FinanceHolding`` rows, not cash transactions, and
    (unlike the register import) runs synchronously - a ledger like this is
    a few hundred rows at most, not a multi-year bank statement.

    Target: an existing ``account_id``, or an ``account_name`` to create a
    manual brokerage account on the spot - the same courtesy the register
    import extends when an OFX file names an account that doesn't exist yet.
    """
    from app.services.finance.domains.investments.loader import (
        import_investment_activities,
    )

    if account_id is None and not (account_name or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide an account_id, or an account_name to create one.",
        )
    activities = await _read_investment_ledger(file, profile)
    account_created = False
    if account_id is not None:
        account = await service.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )
    else:
        account = await service.create_manual_account(
            owner_user_id=owner_user_id,
            name=account_name.strip(),
            account_type="brokerage",
            classification="asset",
        )
        account_created = True
    result = await import_investment_activities(
        service.db,
        owner_user_id=owner_user_id,
        account_id=account.id,
        activities=activities,
    )
    await service.db.commit()
    return InvestmentImportResultResponse(
        activities_parsed=len(activities),
        trades_inserted=result.trades_inserted,
        trades_updated=result.trades_updated,
        securities_created=result.securities_created,
        securities_matched=result.securities_matched,
        account_id=account.id,
        account_name=account.name,
        account_created=account_created,
    )


@router.get("/accounts/{account_id}/trades", response_model=TradeListResponse)
async def list_account_trades(
    account_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TradeListResponse:
    """Recent investment activity (buy/sell/dividend/...) for an account,
    newest first."""
    account = await service.get_account(account_id, owner_user_id=owner_user_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    trades = await service.list_trades(
        owner_user_id=owner_user_id, account_id=account_id
    )
    items = [TradeResponse.from_row(t) for t in trades]
    return TradeListResponse(items=items, total=len(items))


@router.get("/trades", response_model=TradeListResponse)
async def list_all_trades(
    account_ids: list[int] | None = Query(default=None),
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> TradeListResponse:
    """Recent investment activity, newest first — the All Accounts
    register's investment lane. ``account_ids`` is the same account-scope
    filter the register's transaction fetch uses; without it the picker
    narrowed transactions while every brokerage's trades rode along."""
    trades = await service.list_trades(
        owner_user_id=owner_user_id, account_ids=account_ids
    )
    items = [TradeResponse.from_row(t) for t in trades]
    return TradeListResponse(items=items, total=len(items))


@router.get("/holdings", response_model=HoldingListResponse)
async def list_holdings(
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> HoldingListResponse:
    """All current positions across accounts, with total portfolio value."""
    holdings = await service.list_current_holdings(owner_user_id=owner_user_id)
    items = [HoldingResponse.from_parts(h, s, v) for h, s, v in holdings]
    await _attach_holding_icons(service.db, items)
    return HoldingListResponse(
        items=items,
        total=len(items),
        portfolio_value=sum(item.market_value for item in items),
    )


async def _attach_holding_icons(db: AsyncSession, items: list[HoldingResponse]) -> None:
    """Sets ``icon_b64`` from each holding's fund-family logo.

    Same fetch/cache system as payee icons (``merchant_icon.py``) - only
    the domain resolver differs. A fund's own name is never a usable
    domain guess, so unlike payees this ONLY uses the explicit family
    match; an unrecognized family is left ``None`` (initial-letter
    fallback) rather than risking a wrong guessed logo.
    """
    from app.services.finance.domains.ledger.merchant_icon import (
        fund_family_domain,
        icons_for_names,
    )

    domains = {
        item.name: domain
        for item in items
        if item.name and (domain := fund_family_domain(item.name)) is not None
    }
    if not domains:
        return
    icons = await icons_for_names(db, list(domains.keys()), domains_by_name=domains)
    for item in items:
        item.icon_b64 = icons.get(item.name or "")


# -- Investments (securities + holdings) -------------------------------------


@router.post(
    "/securities",
    response_model=SecurityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_security(
    body: SecurityCreate,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> SecurityResponse:
    """Register (or fetch) a catalog security by ticker."""
    security = await service.get_or_create_security(
        ticker=body.ticker,
        name=body.name,
        security_type=body.security_type,
        currency=body.currency,
    )
    return SecurityResponse.from_row(security)
