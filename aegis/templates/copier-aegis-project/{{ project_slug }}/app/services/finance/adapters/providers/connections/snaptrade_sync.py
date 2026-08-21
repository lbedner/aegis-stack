"""SnapTrade connections: register the user, adopt brokerages, sync them.

``start_snaptrade_connect`` registers (or reuses) the owner's SnapTrade
user - its ``user_secret``, the actual credential, is AES-GCM encrypted per
connection row - and returns the connection-portal URL.
``complete_snaptrade_connect`` adopts new brokerage authorizations into
connection rows. ``sync_snaptrade_connection`` polls accounts, positions
and date-windowed activities into the same tables Plaid writes, through
the same shared upsert helpers (``upsert_provider_security`` merges
cross-provider duplicates by FIGI/CUSIP/ISIN).

Writes but does not commit - the caller owns the transaction.
"""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret
from app.services.finance.adapters.providers import queries
from app.services.finance.adapters.providers.connections.common import (
    _SNAPTRADE_SECRET_CONTEXT,
    SyncResult,
    _recompute_net_worth,
    _to_cents,
    _utcnow,
    list_provider_connections,
)
from app.services.finance.adapters.providers.snaptrade import (
    SnapTradeClient,
    SnapTradeError,
)
from app.services.finance.constants import Provider
from app.services.finance.models import FinanceAccount, FinanceConnection
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)

# SnapTrade error code 1010: a user with this userId already exists. The only
# condition under which the destructive delete + re-register recovery in
# start_snaptrade_connect may run.
_SNAPTRADE_USER_EXISTS_CODE = "1010"

# First sync pulls this trailing window of activities; SnapTrade has no cursor,
# so later syncs re-window from the last pull (minus a small overlap for
# late-posting rows) and dedup on the activity id.
_SNAPTRADE_LOOKBACK_DAYS = 730
_SNAPTRADE_ACTIVITY_OVERLAP_DAYS = 7
_SNAPTRADE_ACTIVITY_PAGE = 500

# SnapTrade activity ``type`` -> canonical finance_trade type. TRANSFER is
# resolved by cash direction below; anything unknown degrades to "other" so a
# new provider type never breaks a sync.
_SNAPTRADE_TRADE_TYPES: dict[str, str] = {
    "BUY": "buy",
    "SELL": "sell",
    "DIVIDEND": "dividend",
    "STOCK_DIVIDEND": "dividend",
    "REI": "reinvest",
    "INTEREST": "interest",
    "FEE": "fee",
    "TAX": "tax",
    "CONTRIBUTION": "deposit",
    "WITHDRAWAL": "withdrawal",
    "SPLIT": "split",
}


def _snaptrade_user_id(owner_user_id: int | None) -> str:
    """The immutable SnapTrade ``userId`` for an app user. Deterministic so it
    never needs storing; SnapTrade scopes user ids to the partner app."""
    return "user-standalone" if owner_user_id is None else f"user-{owner_user_id}"


def _map_snaptrade_trade_type(raw_type: str | None, amount: int | None) -> str:
    kind = (raw_type or "").upper()
    if kind == "TRANSFER":
        return "transfer_in" if (amount or 0) >= 0 else "transfer_out"
    return _SNAPTRADE_TRADE_TYPES.get(kind, "other")


def _snaptrade_symbol_fields(symbol: dict[str, Any] | None) -> dict[str, Any] | None:
    """Flatten a SnapTrade symbol payload to upsert_provider_security kwargs.

    Positions nest it as ``position.symbol.symbol`` (a UniversalSymbol);
    activities carry the UniversalSymbol directly. Both are handled here.
    """
    if not symbol:
        return None
    inner = symbol.get("symbol")
    if isinstance(inner, dict):  # PositionSymbol wrapper -> UniversalSymbol
        symbol = inner
    provider_security_id = symbol.get("id")
    if not provider_security_id:
        return None
    security_type = symbol.get("type") or {}
    currency = symbol.get("currency") or {}
    return {
        "provider_security_id": str(provider_security_id),
        "ticker": symbol.get("raw_symbol") or symbol.get("symbol"),
        "name": symbol.get("description"),
        "security_type": security_type.get("code")
        if isinstance(security_type, dict)
        else security_type,
        "figi": symbol.get("figi_code"),
        "currency": (
            currency.get("code", "usd") if isinstance(currency, dict) else currency
        ).lower(),
    }


async def _snaptrade_user_secret(
    db: AsyncSession, *, owner_user_id: int | None
) -> str | None:
    """The owner's SnapTrade ``userSecret``, from any of their connection rows
    (every row stores the same user-level secret)."""
    for connection in await list_provider_connections(
        db, provider=Provider.SNAPTRADE, owner_user_id=owner_user_id
    ):
        if connection.access_token_encrypted:
            return decrypt_secret(
                connection.access_token_encrypted, context=_SNAPTRADE_SECRET_CONTEXT
            )
    return None


async def start_snaptrade_connect(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    broker: str | None = None,
    custom_redirect: str | None = None,
    client: SnapTradeClient | None = None,
) -> tuple[FinanceConnection, str]:
    """Begin a SnapTrade connect: ensure the owner's SnapTrade user exists,
    create a pending (``loading``) connection row holding the encrypted user
    secret, and return it with the connection-portal URL (expires in ~5 min).

    ``complete_snaptrade_connect`` later adopts the authorization the user
    produced in the portal into this row.
    """
    client = client or SnapTradeClient()
    if client.is_personal:
        # Personal (PERS-) keys: the key IS the user. No registration, and
        # data calls are signed with an empty userId/userSecret pair.
        user_id, user_secret = "", ""
    else:
        user_id = _snaptrade_user_id(owner_user_id)
        stored = await _snaptrade_user_secret(db, owner_user_id=owner_user_id)
        if stored is not None:
            user_secret = stored
        else:
            try:
                user_secret = await client.register_user(user_id)
            except SnapTradeError as exc:
                # Delete + re-register mints a fresh secret when the user
                # exists at SnapTrade but no local row holds it (all local
                # rows were removed). Deleting a SnapTrade user revokes its
                # existing authorizations, so this destructive recovery is
                # gated on SnapTrade's specific "user already exists" code -
                # transient failures (timeouts, 5xx, bad credentials) must
                # surface instead.
                if exc.error_code != _SNAPTRADE_USER_EXISTS_CODE:
                    raise
                logger.warning(
                    "SnapTrade user %s exists with no stored secret; "
                    "re-registering (revokes that user's prior authorizations)",
                    user_id,
                )
                await client.delete_user(user_id)
                user_secret = await client.register_user(user_id)
    connection = FinanceConnection(
        owner_user_id=owner_user_id,
        provider=Provider.SNAPTRADE,
        connection_type="aggregator_token",
        environment="production",
        access_token_encrypted=encrypt_secret(
            user_secret, context=_SNAPTRADE_SECRET_CONTEXT
        ),
        status="loading",
    )
    db.add(connection)
    await db.flush()
    if client.is_personal:
        # Personal keys have no partner connection portal (the login
        # endpoint rejects them): brokerages are linked inside SnapTrade's
        # own dashboard, and this app ADOPTS what exists. The empty URL
        # tells the frontend to skip the portal tab and poll adoption
        # immediately.
        return connection, ""
    url = await client.login_url(
        user_id, user_secret, broker=broker, custom_redirect=custom_redirect
    )
    return connection, url


async def complete_snaptrade_connect(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    client: SnapTradeClient | None = None,
) -> list[SyncResult]:
    """Adopt any brokerage authorizations not yet tied to a connection row,
    then sync them. Returns ``[]`` while the portal is still pending, so the
    frontend can poll this until it comes back non-empty (the Hosted Link
    pattern)."""
    client = client or SnapTradeClient()
    if client.is_personal:
        user_id, user_secret = "", ""
    else:
        stored = await _snaptrade_user_secret(db, owner_user_id=owner_user_id)
        if stored is None:
            return []  # connect was never started
        user_id, user_secret = _snaptrade_user_id(owner_user_id), stored

    rows = await list_provider_connections(
        db, provider=Provider.SNAPTRADE, owner_user_id=owner_user_id
    )
    known_authorizations = {r.provider_item_id for r in rows if r.provider_item_id}
    pending = [r for r in rows if r.provider_item_id is None]

    results: list[SyncResult] = []
    for authorization in await client.list_authorizations(user_id, user_secret):
        authorization_id = str(authorization.get("id") or "")
        if not authorization_id or authorization_id in known_authorizations:
            continue
        connection = (
            pending.pop(0)
            if pending
            else FinanceConnection(
                owner_user_id=owner_user_id,
                provider=Provider.SNAPTRADE,
                connection_type="aggregator_token",
                environment="production",
                access_token_encrypted=encrypt_secret(
                    user_secret, context=_SNAPTRADE_SECRET_CONTEXT
                ),
            )
        )
        connection.provider_item_id = authorization_id
        brokerage = authorization.get("brokerage") or {}
        connection.label = (
            brokerage.get("display_name")
            or brokerage.get("name")
            or authorization.get("name")
        )
        connection.status = "healthy"
        db.add(connection)
        await db.flush()
        results.append(await sync_snaptrade_connection(db, connection, client=client))
    await _recompute_net_worth(db, owner_user_id, results)
    return results


async def _find_snaptrade_account(
    db: AsyncSession,
    connection: FinanceConnection,
    *,
    snaptrade_id: str,
    name: str,
    mask: str | None,
) -> FinanceAccount | None:
    """Match by the SnapTrade account id, else the re-link fallback (same
    owner + name + mask) — a re-connected brokerage issues fresh account ids
    but keeps the human identity."""
    found = await queries.account_by_provider_account_id(
        db, provider=Provider.SNAPTRADE, provider_account_id=snaptrade_id
    )
    if found is not None:
        return found
    filters = [
        FinanceAccount.provider == Provider.SNAPTRADE,
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_(None),
        FinanceAccount.mask == mask
        if mask is not None
        else FinanceAccount.mask.is_(None),
    ]
    if connection.owner_user_id is not None:
        filters.append(FinanceAccount.owner_user_id == connection.owner_user_id)
    return await queries.account_first_where(db, filters)


async def _upsert_snaptrade_accounts(
    db: AsyncSession,
    service: FinanceService,
    connection: FinanceConnection,
    snaptrade_accounts: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert one FinanceAccount per SnapTrade account; return
    {snaptrade_id: account_id}. SnapTrade accounts are brokerages (assets);
    the account's ``balance.total`` is the provider-authoritative value."""
    mapping: dict[str, int] = {}
    for raw in snaptrade_accounts:
        snaptrade_id = str(raw.get("id") or "")
        if not snaptrade_id:
            continue
        name = raw.get("name") or raw.get("institution_name") or "Brokerage"
        number = raw.get("number") or ""
        mask = number[-4:] if number else None
        total = (raw.get("balance") or {}).get("total") or {}
        currency = (total.get("currency") or "usd").lower()
        await service.get_or_create_currency(currency)
        account = await _find_snaptrade_account(
            db, connection, snaptrade_id=snaptrade_id, name=name, mask=mask
        )
        if account is None:
            account = FinanceAccount(
                owner_user_id=connection.owner_user_id,
                provider=Provider.SNAPTRADE,
                account_type="brokerage",
                classification="asset",
                name=name,
                is_manual=False,
            )
        account.connection_id = connection.id
        account.provider_account_id = snaptrade_id
        account.currency = currency
        account.name = name
        account.mask = mask
        account.current_balance = _to_cents(total.get("amount"))
        account.balance_as_of = _utcnow()
        account.deleted_at = None
        db.add(account)
        await db.flush()
        mapping[snaptrade_id] = account.id
    return mapping


async def _apply_snaptrade_positions(
    service: FinanceService,
    positions: list[dict[str, Any]],
    *,
    account_id: int,
    owner_user_id: int | None,
) -> int:
    """Positions -> securities (via the FIGI-first shared upsert) + dated
    holdings. The account balance stays SnapTrade's ``balance.total``
    (``sync_account_balance=False``), mirroring the Plaid path."""
    count = 0
    for position in positions:
        fields = _snaptrade_symbol_fields(position.get("symbol"))
        if fields is None:
            continue
        units = position.get("units")
        if units is None:
            continue
        price = position.get("price")
        price_cents = round(price * 100) if price is not None else None
        security = await service.upsert_provider_security(
            provider=Provider.SNAPTRADE,
            close_price=price_cents,
            **fields,
        )
        average_cost = position.get("average_purchase_price")
        await service.upsert_holding(
            owner_user_id=owner_user_id,
            account_id=account_id,
            security_id=security.id,
            as_of_date=_utcnow().date(),
            quantity_e8=round(units * 10**8),
            price=price_cents,
            cost_basis=(
                round(average_cost * units * 100)
                if average_cost is not None and units
                else None
            ),
            currency=fields["currency"],
            source=Provider.SNAPTRADE,
            sync_account_balance=False,
        )
        count += 1
    return count


async def _apply_snaptrade_activities(
    service: FinanceService,
    activities: list[dict[str, Any]],
    *,
    account_id: int,
    connection: FinanceConnection,
) -> int:
    """Activities -> finance_trade rows, deduped on the activity id.

    SnapTrade signs ``amount`` positive for cash INTO the account (docs:
    "sell, deposits, dividends ... positive; buy, withdrawals, fees ...
    negative") — already this project's convention, so no negation here.
    """
    count = 0
    for activity in activities:
        external_id = activity.get("id")
        if not external_id:
            continue
        raw_date = activity.get("trade_date") or activity.get("settlement_date")
        if not raw_date:
            continue
        trade_date = date.fromisoformat(str(raw_date)[:10])
        amount = activity.get("amount")
        amount_cents = round(amount * 100) if amount is not None else 0
        fields = _snaptrade_symbol_fields(activity.get("symbol"))
        security_id = None
        if fields is not None:
            security = await service.upsert_provider_security(
                provider=Provider.SNAPTRADE, **fields
            )
            security_id = security.id
        units = activity.get("units")
        price = activity.get("price")
        fee = activity.get("fee")
        currency = activity.get("currency") or {}
        await service.upsert_trade(
            owner_user_id=connection.owner_user_id,
            account_id=account_id,
            trade_type=_map_snaptrade_trade_type(activity.get("type"), amount_cents),
            subtype=activity.get("option_type") or activity.get("type"),
            trade_date=trade_date,
            amount=amount_cents,
            security_id=security_id,
            quantity_e8=round(units * 10**8) if units is not None else None,
            price=round(price * 100) if price is not None else None,
            fees=round(fee * 100) if fee is not None else None,
            currency=(
                currency.get("code", "usd")
                if isinstance(currency, dict)
                else (currency or "usd")
            ).lower(),
            source=Provider.SNAPTRADE,
            external_id=str(external_id),
            external_id_source=Provider.SNAPTRADE,
            name=activity.get("description"),
            connection_id=connection.id,
            raw_payload=activity,
        )
        count += 1
    return count


async def sync_snaptrade_connection(
    db: AsyncSession,
    connection: FinanceConnection,
    *,
    client: SnapTradeClient | None = None,
) -> SyncResult:
    """Sync one SnapTrade authorization: accounts + positions every run,
    activities at most once per day per account.

    SnapTrade's launch guide budgets polling (holdings a few times a day,
    activities ~daily) and refreshes its own upstream cache daily anyway.
    ``sync_cursor`` stores the date of the last activities pull: the window
    re-opens from there (minus a small overlap) and the activity-id dedup
    absorbs the overlap, mirroring the Plaid investments lane.
    """
    client = client or SnapTradeClient()
    service = FinanceService(db)
    result = SyncResult(connection_id=connection.id)
    connection.last_sync_attempt_at = _utcnow()
    if not connection.access_token_encrypted or not connection.provider_item_id:
        return result
    user_id = "" if client.is_personal else _snaptrade_user_id(connection.owner_user_id)
    user_secret = decrypt_secret(
        connection.access_token_encrypted, context=_SNAPTRADE_SECRET_CONTEXT
    )

    accounts = [
        account
        for account in await client.list_accounts(user_id, user_secret)
        if str(account.get("brokerage_authorization") or "")
        == connection.provider_item_id
    ]
    account_map = await _upsert_snaptrade_accounts(db, service, connection, accounts)
    result.accounts = len(account_map)

    today = _utcnow().date()
    last_pull = (
        date.fromisoformat(connection.sync_cursor) if connection.sync_cursor else None
    )
    pull_activities = last_pull is None or last_pull < today
    start = (
        today - timedelta(days=_SNAPTRADE_LOOKBACK_DAYS)
        if last_pull is None
        else last_pull - timedelta(days=_SNAPTRADE_ACTIVITY_OVERLAP_DAYS)
    )

    for snaptrade_id, account_id in account_map.items():
        positions = await client.get_positions(user_id, user_secret, snaptrade_id)
        result.holdings += await _apply_snaptrade_positions(
            service,
            positions,
            account_id=account_id,
            owner_user_id=connection.owner_user_id,
        )
        if not pull_activities:
            continue
        offset = 0
        while True:
            page = await client.get_activities(
                user_id,
                user_secret,
                snaptrade_id,
                start_date=start.isoformat(),
                end_date=today.isoformat(),
                offset=offset,
                limit=_SNAPTRADE_ACTIVITY_PAGE,
            )
            batch = page.get("data") or []
            result.trades += await _apply_snaptrade_activities(
                service, batch, account_id=account_id, connection=connection
            )
            offset += len(batch)
            total = (page.get("pagination") or {}).get("total")
            if not batch or len(batch) < _SNAPTRADE_ACTIVITY_PAGE:
                break
            if total is not None and offset >= int(total):
                break

    if pull_activities:
        connection.sync_cursor = today.isoformat()
    connection.status = "healthy"
    connection.needs_user_action = False
    connection.last_successful_sync_at = _utcnow()
    db.add(connection)
    await db.flush()
    return result
