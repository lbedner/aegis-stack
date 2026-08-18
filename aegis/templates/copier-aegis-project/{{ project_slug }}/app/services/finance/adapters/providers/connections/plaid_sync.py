"""Plaid connections: create one, sync it, and answer its webhooks.

``create_plaid_connection`` stores an exchanged access token (AES-GCM
encrypted) as a ``FinanceConnection``. ``sync_plaid_connection`` pulls the
item's accounts (upserting ``FinanceAccount`` rows keyed by Plaid
``account_id``), its transactions via the cursor-based ``transactions/sync``
(LANE-1 dedup on the Plaid ``transaction_id``), and its liabilities,
holdings and trades.

Writes but does not commit - the caller owns the transaction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret
from app.services.finance.adapters.providers import queries
from app.services.finance.adapters.providers.connections.common import (
    _ACCESS_TOKEN_CONTEXT,
    SyncResult,
    _recompute_net_worth,
    _to_cents,
    _utcnow,
    get_connection,
    list_plaid_connections,
)
from app.services.finance.adapters.providers.plaid import PlaidClient, PlaidError
from app.services.finance.constants import Provider
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceConnection,
    FinanceImportBatch,
    FinanceLiabilityDetail,
    FinanceTransaction,
    FinanceWebhookEvent,
)
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)

# Plaid ``type`` -> (account_type, classification). Depository subtypes refine
# checking vs savings below.
_PLAID_TYPE_MAP: dict[str, tuple[str, str]] = {
    "depository": ("checking", "asset"),
    "credit": ("credit_card", "liability"),
    "loan": ("loan", "liability"),
    "investment": ("brokerage", "asset"),
}
_DEPOSITORY_SAVINGS = frozenset({"savings", "cd", "money market", "hsa"})


def _map_account_kind(
    plaid_type: str | None, plaid_subtype: str | None
) -> tuple[str, str]:
    account_type, classification = _PLAID_TYPE_MAP.get(
        plaid_type or "", ("other_asset", "asset")
    )
    if plaid_type == "depository" and (plaid_subtype or "") in _DEPOSITORY_SAVINGS:
        account_type = "savings"
    return account_type, classification


async def create_plaid_connection(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    access_token: str,
    item_id: str,
    institution_id: int | None = None,
    label: str | None = None,
    environment: str = "sandbox",
) -> FinanceConnection:
    """Persist an exchanged Plaid access token as a connection (idempotent on
    the provider item id)."""
    existing = await queries.connection_by_provider_item(
        db, provider=Provider.PLAID, provider_item_id=item_id
    )
    if existing is not None:
        existing.access_token_encrypted = encrypt_secret(
            access_token, context=_ACCESS_TOKEN_CONTEXT
        )
        existing.status = "healthy"
        existing.removed_at = None
        existing.deleted_at = None
        db.add(existing)
        await db.flush()
        return existing
    connection = FinanceConnection(
        owner_user_id=owner_user_id,
        provider=Provider.PLAID,
        connection_type="oauth_access_token",
        provider_item_id=item_id,
        institution_id=institution_id,
        label=label,
        environment=environment,
        access_token_encrypted=encrypt_secret(
            access_token, context=_ACCESS_TOKEN_CONTEXT
        ),
        status="healthy",
    )
    db.add(connection)
    await db.flush()
    return connection


async def _find_plaid_account(
    db: AsyncSession,
    connection: FinanceConnection,
    *,
    plaid_id: str,
    persistent: str | None,
    name: str,
    mask: str | None,
) -> FinanceAccount | None:
    """Find the account this Plaid account maps to, so re-linking the same
    institution (a new Item with fresh ``account_id``s) updates the existing
    rows instead of duplicating them."""
    # 1) Stable persistent id — real institutions provide it across re-links.
    if persistent:
        found = await queries.account_by_persistent_id(
            db, provider=Provider.PLAID, persistent_account_id=persistent
        )
        if found is not None:
            return found
    # 2) Same Item re-sync (unchanged account_id).
    found = await queries.account_by_provider_account_id(
        db, provider=Provider.PLAID, provider_account_id=plaid_id
    )
    if found is not None:
        return found
    # 3) Re-link fallback (no persistent id, e.g. sandbox): same owner + name +
    # mask. Plaid regenerates account_ids per Item, but name/mask are stable.
    filters = [
        FinanceAccount.provider == Provider.PLAID,
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_(None),
        FinanceAccount.mask == mask
        if mask is not None
        else FinanceAccount.mask.is_(None),
    ]
    if connection.owner_user_id is not None:
        filters.append(FinanceAccount.owner_user_id == connection.owner_user_id)
    return await queries.account_first_where(db, filters)


async def _upsert_accounts(
    db: AsyncSession,
    service: FinanceService,
    connection: FinanceConnection,
    plaid_accounts: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert one FinanceAccount per Plaid account; return {plaid_id: account_id}."""
    mapping: dict[str, int] = {}
    for plaid_account in plaid_accounts:
        plaid_id = plaid_account["account_id"]
        persistent = plaid_account.get("persistent_account_id")
        name = (
            plaid_account.get("name") or plaid_account.get("official_name") or "Account"
        )
        mask = plaid_account.get("mask")
        balances = plaid_account.get("balances") or {}
        currency = (balances.get("iso_currency_code") or "usd").lower()
        await service.get_or_create_currency(currency)
        account_type, classification = _map_account_kind(
            plaid_account.get("type"), plaid_account.get("subtype")
        )
        account = await _find_plaid_account(
            db,
            connection,
            plaid_id=plaid_id,
            persistent=persistent,
            name=name,
            mask=mask,
        )
        if account is None:
            account = FinanceAccount(
                owner_user_id=connection.owner_user_id,
                provider=Provider.PLAID,
                account_type=account_type,
                classification=classification,
                name=name,
                is_manual=False,
            )
        # (Re)point at this connection + refresh the provider ids and balances.
        account.connection_id = connection.id
        account.institution_id = connection.institution_id or account.institution_id
        account.provider_account_id = plaid_id
        account.persistent_account_id = persistent
        account.currency = currency
        account.name = name
        account.mask = mask
        account.current_balance = _to_cents(balances.get("current"))
        account.available_balance = _to_cents(balances.get("available"))
        account.balance_as_of = _utcnow()
        account.deleted_at = None
        db.add(account)
        await db.flush()
        mapping[plaid_id] = account.id
    return mapping


async def _apply_transactions(
    db: AsyncSession,
    service: FinanceService,
    transactions: list[dict[str, Any]],
    account_by_plaid_id: dict[str, int],
    *,
    connection: FinanceConnection,
    import_batch_id: int | None = None,
) -> tuple[int, int]:
    """Insert new / reconcile Plaid transactions. Returns (added, reconciled).

    LANE 1 = ``(account, transaction_id)`` — exact; catches same-Item re-syncs.
    Re-link fallback: Plaid regenerates ``transaction_id`` for a re-linked Item,
    so a transaction already stored under *another* connection is matched by
    content (account, date, amount, normalized payee) as a multiset. Scoping to
    other connections avoids collapsing legitimate repeat charges in a normal
    same-Item sync. The schema forbids a row carrying both id and hash, so this
    is a query-time check, not a stored second lane.
    """
    from app.services.finance.utils import normalize_payee

    prepared: list[tuple[int, dict[str, Any], int, str | None, date]] = []
    currencies: set[str] = set()
    for txn in transactions:
        plaid_account_id = txn.get("account_id")
        account_id = (
            account_by_plaid_id.get(plaid_account_id) if plaid_account_id else None
        )
        if account_id is None:
            continue
        raw_amount = txn.get("amount")
        # Plaid: positive = outflow -> negate to our convention.
        amount = -round(raw_amount * 100) if raw_amount is not None else 0
        currency = (txn.get("iso_currency_code") or "usd").lower()
        currencies.add(currency)
        prepared.append(
            (
                account_id,
                txn,
                amount,
                txn.get("merchant_name") or txn.get("name"),
                date.fromisoformat(txn["date"]),
            )
        )
    if not prepared:
        return 0, 0
    for currency in currencies:
        await service.get_or_create_currency(currency)

    touched = {account_id for account_id, *_rest in prepared}
    lane1: dict[tuple[int, str], FinanceTransaction] = {}
    other_content: dict[tuple[int, date, int, str], int] = defaultdict(int)
    for row in await queries.provider_rows_for_accounts(
        db, account_ids=touched, source=Provider.PLAID
    ):
        if row.external_id is not None:
            lane1[(row.account_id, row.external_id)] = row
        # Content from OTHER connections = a re-linked Item's existing history.
        if row.connection_id != connection.id:
            other_content[
                (row.account_id, row.date_, row.amount, normalize_payee(row.name or ""))
            ] += 1

    added = reconciled = 0
    # Posted rows referencing an earlier pre-auth (Plaid's id in
    # ``pending_transaction_id``) collapse after the loop, once every row of
    # the batch — including a same-batch pending sibling — is in ``lane1``.
    collapse: list[tuple[int, str, FinanceTransaction]] = []
    for account_id, txn, amount, name, txn_date in prepared:
        external_id = txn["transaction_id"]
        pending = bool(txn.get("pending"))
        pending_provider_id = txn.get("pending_transaction_id")
        pfc = txn.get("personal_finance_category") or {}
        existing = lane1.get((account_id, external_id))
        if existing is not None:  # same Item re-sync -> update in place
            existing.amount = amount
            existing.name = name
            existing.date_ = txn_date
            existing.pending = pending
            if existing.status != "removed":
                existing.status = "pending" if pending else "posted"
            if pending_provider_id:
                existing.pending_provider_id = pending_provider_id
            # Category precedence: provider < rule < user. A provider refresh
            # (modified[]) never clobbers a rule- or user-assigned category.
            if pfc.get("primary") and existing.category_source in (
                "provider",
                "unset",
            ):
                category = await service.get_or_create_pfc_category(pfc["primary"])
                existing.category_id = category.id
                existing.category_source = "provider"
            db.add(existing)
            await db.flush()
            reconciled += 1
            if not pending and pending_provider_id:
                collapse.append((account_id, pending_provider_id, existing))
            continue
        content_key = (account_id, txn_date, amount, normalize_payee(name or ""))
        if other_content.get(content_key, 0) > 0:  # re-link: already stored
            other_content[content_key] -= 1
            reconciled += 1
            continue

        category_id: int | None = None
        if pfc.get("primary"):
            category = await service.get_or_create_pfc_category(pfc["primary"])
            category_id = category.id
        created = await service.create_transaction(
            owner_user_id=connection.owner_user_id,
            account_id=account_id,
            connection_id=connection.id,
            amount=amount,
            txn_date=txn_date,
            name=name,
            source=Provider.PLAID,
            external_id=external_id,
            external_id_source="plaid",
            currency=(txn.get("iso_currency_code") or "usd").lower(),
            original_description=txn.get("name"),
            category_id=category_id,
            category_source="provider" if pfc.get("primary") else "unset",
            pending=pending,
            pending_provider_id=pending_provider_id,
            import_batch_id=import_batch_id,
        )
        lane1[(account_id, external_id)] = created
        added += 1
        if not pending and pending_provider_id:
            collapse.append((account_id, pending_provider_id, created))

    # Pending -> posted: link the posted row to its pre-auth via the self-FK
    # and tombstone the pre-auth so exactly one row stays visible.
    now = _utcnow()
    for account_id, plaid_pending_id, posted in collapse:
        pending_row = lane1.get((account_id, plaid_pending_id))
        if (
            pending_row is None
            or pending_row.id == posted.id
            or pending_row.deleted_at is not None
        ):
            continue
        posted.pending_transaction_id = pending_row.id
        pending_row.deleted_at = now
        db.add(posted)
        db.add(pending_row)
    if collapse:
        await db.flush()
    return added, reconciled


def _pct_to_bps(pct: float | None) -> int | None:
    return int(round(pct * 100)) if pct is not None else None


async def _apply_liabilities(
    db: AsyncSession,
    liabilities: dict[str, Any],
    account_by_plaid_id: dict[str, int],
    *,
    owner_user_id: int | None,
) -> int:
    """Upsert credit-lane liability detail, 1:1 per account, ever.

    Money lands as int cents, APRs as basis points (int) — no floats stored.
    Fields the institution doesn't report (the AMEX case) stay NULL.
    """
    entries = liabilities.get("credit") or []
    if not entries:
        return 0
    touched = [
        account_by_plaid_id[e["account_id"]]
        for e in entries
        if e.get("account_id") in account_by_plaid_id
    ]
    existing_by_account = await ledger_queries.liability_details_by_account(db, touched)
    written = 0
    for entry in entries:
        account_id = account_by_plaid_id.get(entry.get("account_id"))
        if account_id is None:
            continue
        detail = existing_by_account.get(account_id)
        if detail is None:
            detail = FinanceLiabilityDetail(
                owner_user_id=owner_user_id, account_id=account_id
            )
        detail.liability_type = "credit"
        detail.last_statement_balance = _to_cents(entry.get("last_statement_balance"))
        raw_issue = entry.get("last_statement_issue_date")
        detail.last_statement_issue_date = (
            date.fromisoformat(raw_issue) if raw_issue else None
        )
        detail.last_payment_amount = _to_cents(entry.get("last_payment_amount"))
        raw_paid = entry.get("last_payment_date")
        detail.last_payment_date = date.fromisoformat(raw_paid) if raw_paid else None
        detail.minimum_payment_amount = _to_cents(entry.get("minimum_payment_amount"))
        raw_due = entry.get("next_payment_due_date")
        detail.next_payment_due_date = date.fromisoformat(raw_due) if raw_due else None
        detail.is_overdue = entry.get("is_overdue")
        detail.aprs = [
            {
                "apr_type": apr.get("apr_type"),
                "apr_percentage_bps": _pct_to_bps(apr.get("apr_percentage")),
                "balance_subject_to_apr": _to_cents(apr.get("balance_subject_to_apr")),
                "interest_charge_amount": _to_cents(apr.get("interest_charge_amount")),
            }
            for apr in entry.get("aprs") or []
        ]
        detail.raw = entry
        detail.updated_at = _utcnow()
        db.add(detail)
        written += 1
    await db.flush()
    return written


async def _remove_transactions(
    db: AsyncSession,
    removed: list[dict[str, Any]],
    account_by_plaid_id: dict[str, int],
) -> int:
    """Tombstone retracted transactions (phantom pre-auths, bank deletions).

    Soft-delete only — the tombstone (``is_removed``/``removed_at``/``status``)
    must survive re-syncs so a replayed page can't resurrect the row. Scoped to
    the account the removed[] entry names when Plaid provides it.
    """
    count = 0
    now = _utcnow()
    for item in removed:
        conditions = [
            FinanceTransaction.source == Provider.PLAID,
            FinanceTransaction.external_id == item["transaction_id"],
            FinanceTransaction.deleted_at.is_(None),
        ]
        plaid_account_id = item.get("account_id")
        account_id = (
            account_by_plaid_id.get(plaid_account_id) if plaid_account_id else None
        )
        if account_id is not None:
            conditions.append(FinanceTransaction.account_id == account_id)
        txn = await queries.transaction_first_where(db, conditions)
        if txn is not None:
            txn.is_removed = True
            txn.removed_at = now
            txn.status = "removed"
            txn.deleted_at = now
            db.add(txn)
            count += 1
    return count


async def _upsert_securities(
    service: FinanceService,
    plaid_securities: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert catalog securities keyed by Plaid ``security_id`` (some have no
    ticker, so the provider id is the stable key); FIGI/CUSIP/ISIN merge the
    same instrument across providers. Returns {plaid_id: our_id}."""
    mapping: dict[str, int] = {}
    for sec in plaid_securities:
        plaid_id = sec["security_id"]
        close = sec.get("close_price")
        security = await service.upsert_provider_security(
            provider=Provider.PLAID,
            provider_security_id=plaid_id,
            ticker=sec.get("ticker_symbol"),
            name=sec.get("name"),
            security_type=sec.get("type"),
            cusip=sec.get("cusip"),
            isin=sec.get("isin"),
            figi=sec.get("figi"),
            currency=(sec.get("iso_currency_code") or "usd").lower(),
            close_price=round(close * 100) if close is not None else None,
        )
        mapping[plaid_id] = security.id
    return mapping


# How far back to pull investment transactions each sync. Plaid's endpoint has
# no cursor; we re-window and dedup by ``investment_transaction_id``, so this is
# just the trailing coverage, not an incremental checkpoint.
_INVESTMENT_LOOKBACK_DAYS = 730


def _map_plaid_trade_type(plaid_type: str, subtype: str | None, amount: float) -> str:
    """Map a Plaid (type, subtype, amount) to a normalized ``FinanceTrade.type``.

    Plaid's coarse ``type`` (buy/sell/cancel/cash/fee/transfer) is often too
    blunt, so the granular ``subtype`` wins when it's meaningful. Plaid signs
    ``amount`` positive when cash is debited (money out: a buy) and negative
    when credited (money in: a sell), which disambiguates the direction of the
    ``transfer``/``cash`` types. Unknown shapes fall back to ``other`` rather
    than raising — an unrecognized trade must never break a sync.
    """
    sub = (subtype or "").lower()
    if "reinvest" in sub:
        return "reinvest"
    if "dividend" in sub:
        return "dividend"
    if "interest" in sub:
        return "interest"
    if "tax" in sub:
        return "tax"
    if "split" in sub:
        return "split"
    if sub in ("deposit", "contribution"):
        return "deposit"
    if sub == "withdrawal":
        return "withdrawal"
    if sub in ("buy", "buy to cover"):
        return "buy"
    if sub in ("sell", "sell short"):
        return "sell"
    if "fee" in sub:
        return "fee"
    coarse = (plaid_type or "").lower()
    if coarse in ("buy", "sell", "cancel", "fee"):
        return coarse
    if coarse == "transfer":
        return "transfer_out" if amount > 0 else "transfer_in"
    if coarse == "cash":
        return "withdrawal" if amount > 0 else "deposit"
    return "other"


async def _apply_trades(
    db: AsyncSession,
    service: FinanceService,
    plaid_txns: list[dict[str, Any]],
    account_by_plaid_id: dict[str, int],
    security_by_plaid_id: dict[str, int],
    *,
    connection: FinanceConnection,
) -> int:
    """Upsert each Plaid investment transaction as a FinanceTrade, deduped by
    ``investment_transaction_id`` (the external-id lane). Cash-only rows (fees,
    dividends, deposits) carry no security and are still recorded."""
    count = 0
    for txn in plaid_txns:
        plaid_account_id = txn.get("account_id")
        account_id = (
            account_by_plaid_id.get(plaid_account_id) if plaid_account_id else None
        )
        if account_id is None:
            continue
        plaid_security_id = txn.get("security_id")
        security_id = (
            security_by_plaid_id.get(plaid_security_id) if plaid_security_id else None
        )
        plaid_amount = txn.get("amount") or 0.0
        quantity = txn.get("quantity")
        price = txn.get("price")
        fees = txn.get("fees")
        # Plaid signs ``amount`` positive when cash is debited (a buy). Store it
        # in the app convention used by cash transactions — negative = money out
        # of the account — so amounts colorize consistently in the UI. The raw
        # provider value is preserved in ``raw_payload``.
        await service.upsert_trade(
            owner_user_id=connection.owner_user_id,
            account_id=account_id,
            security_id=security_id,
            connection_id=connection.id,
            source=Provider.PLAID,
            external_id=txn.get("investment_transaction_id"),
            external_id_source=Provider.PLAID,
            trade_type=_map_plaid_trade_type(
                txn.get("type", ""), txn.get("subtype"), plaid_amount
            ),
            subtype=txn.get("subtype"),
            trade_date=date.fromisoformat(txn["date"]),
            amount=round(-plaid_amount * 100),
            quantity_e8=round(quantity * 10**8) if quantity is not None else None,
            price=round(price * 100) if price is not None else None,
            fees=round(fees * 100) if fees is not None else None,
            currency=(txn.get("iso_currency_code") or "usd").lower(),
            name=txn.get("name"),
            raw_payload=txn,
        )
        count += 1
    return count


async def _apply_holdings(
    db: AsyncSession,
    service: FinanceService,
    plaid_holdings: list[dict[str, Any]],
    account_by_plaid_id: dict[str, int],
    security_by_plaid_id: dict[str, int],
    *,
    owner_user_id: int | None,
) -> int:
    """Upsert each Plaid position as a FinanceHolding. Balances come from
    ``accounts/get``, so holdings don't drive the account balance here."""
    count = 0
    for holding in plaid_holdings:
        plaid_account_id = holding.get("account_id")
        plaid_security_id = holding.get("security_id")
        if not plaid_account_id or not plaid_security_id:
            continue
        account_id = account_by_plaid_id.get(plaid_account_id)
        security_id = security_by_plaid_id.get(plaid_security_id)
        if account_id is None or security_id is None:
            continue
        price = holding.get("institution_price")
        cost = holding.get("cost_basis")
        as_of = holding.get("institution_price_as_of")
        await service.upsert_holding(
            owner_user_id=owner_user_id,
            account_id=account_id,
            security_id=security_id,
            as_of_date=date.fromisoformat(as_of) if as_of else _utcnow().date(),
            quantity_e8=round((holding.get("quantity") or 0) * 10**8),
            price=round(price * 100) if price is not None else None,
            cost_basis=round(cost * 100) if cost is not None else None,
            currency=(holding.get("iso_currency_code") or "usd").lower(),
            source=Provider.PLAID,
            sync_account_balance=False,
        )
        count += 1
    return count


async def sync_plaid_connection(
    db: AsyncSession,
    connection: FinanceConnection,
    *,
    client: PlaidClient | None = None,
) -> SyncResult:
    """Pull accounts + transactions (+ holdings) for a connection."""
    client = client or PlaidClient()
    service = FinanceService(db)
    access_token = decrypt_secret(
        connection.access_token_encrypted, context=_ACCESS_TOKEN_CONTEXT
    )
    result = SyncResult(connection_id=connection.id)

    accounts, item = await client.get_accounts(access_token)
    # Label the connection with the real institution name once, so the UI shows
    # "Chase" rather than "Plaid · Sandbox".
    if not connection.label and item.get("institution_id"):
        try:
            connection.label = await client.get_institution_name(item["institution_id"])
        except PlaidError:
            pass
    account_by_plaid_id = await _upsert_accounts(db, service, connection, accounts)
    result.accounts = len(account_by_plaid_id)

    # Investment positions — only items linked with the ``investments`` product
    # return holdings; anything else raises and is skipped.
    try:
        plaid_holdings, plaid_securities = await client.get_holdings(access_token)
    except PlaidError:
        plaid_holdings, plaid_securities = [], []
    if plaid_holdings:
        security_by_plaid_id = await _upsert_securities(service, plaid_securities)
        result.holdings = await _apply_holdings(
            db,
            service,
            plaid_holdings,
            account_by_plaid_id,
            security_by_plaid_id,
            owner_user_id=connection.owner_user_id,
        )

    # Investment transactions (trades) — same investments-product gate as
    # holdings. No cursor: page a trailing date window by offset and dedup on
    # ``investment_transaction_id``. Securities here can include ones not held
    # anymore, so re-upsert the catalog from this response too.
    inv_txns: list[dict[str, Any]] = []
    inv_securities: list[dict[str, Any]] = []
    try:
        end = _utcnow().date()
        start = end - timedelta(days=_INVESTMENT_LOOKBACK_DAYS)
        offset = 0
        while True:
            page = await client.get_investment_transactions(
                access_token, start.isoformat(), end.isoformat(), offset=offset
            )
            batch = page.get("investment_transactions", [])
            inv_txns.extend(batch)
            inv_securities.extend(page.get("securities", []))
            total = page.get("total_investment_transactions", len(inv_txns))
            offset += len(batch)
            if not batch or offset >= total:
                break
    except PlaidError:
        inv_txns, inv_securities = [], []
    if inv_txns:
        trade_security_by_plaid_id = await _upsert_securities(service, inv_securities)
        result.trades = await _apply_trades(
            db,
            service,
            inv_txns,
            account_by_plaid_id,
            trade_security_by_plaid_id,
            connection=connection,
        )

    cursor = connection.sync_cursor
    connection.last_sync_attempt_at = _utcnow()
    # Collect every page first so within-day ordinals span the full set (they
    # must be stable for the LANE-2 re-link dedup to line up).
    collected: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    cursor_before = cursor
    while True:
        page = await client.sync_transactions(access_token, cursor)
        collected.extend(page.get("added", []) + page.get("modified", []))
        removed.extend(page.get("removed", []))
        cursor = page.get("next_cursor")
        if not page.get("has_more"):
            break

    # Audit trail: one finance_import_batch row per sync pass, carrying the
    # cursor window it applied. Committed only after every row lands, so the
    # session's single commit keeps batch, rows, and cursor advance atomic.
    batch = FinanceImportBatch(
        owner_user_id=(
            0 if connection.owner_user_id is None else connection.owner_user_id
        ),
        connection_id=connection.id,
        source_type="plaid_sync",
        sync_cursor_before=cursor_before,
        status="processing",
        rows_total=len(collected) + len(removed),
        started_at=_utcnow(),
    )
    db.add(batch)
    await db.flush()

    result.added, result.updated = await _apply_transactions(
        db,
        service,
        collected,
        account_by_plaid_id,
        connection=connection,
        import_batch_id=batch.id,
    )
    # Removals apply last: a row added on an early page and retracted on a
    # later one (phantom pre-auth) must end tombstoned, not re-inserted.
    result.removed = await _remove_transactions(db, removed, account_by_plaid_id)

    batch.sync_cursor_after = cursor
    batch.rows_inserted = result.added
    batch.rows_updated = result.updated
    batch.status = "committed"
    batch.finished_at = _utcnow()
    db.add(batch)

    # Liability detail (credit APR/statement/min-payment) — capability-gated
    # on the item's products, so institutions without it (the AMEX case) get
    # ZERO extra API calls, zero rows, zero errors.
    item_products = set(
        (item.get("products") or [])
        + (item.get("billed_products") or [])
        + (item.get("available_products") or [])
    )
    if "liabilities" in item_products:
        try:
            plaid_liabilities = await client.get_liabilities(access_token)
        except PlaidError:
            plaid_liabilities = {}
        if plaid_liabilities:
            await _apply_liabilities(
                db,
                plaid_liabilities,
                account_by_plaid_id,
                owner_user_id=connection.owner_user_id,
            )

    connection.sync_cursor = cursor
    connection.status = "healthy"
    connection.needs_user_action = False
    connection.last_successful_sync_at = _utcnow()
    db.add(connection)
    await db.flush()
    return result


async def complete_hosted_link(
    db: AsyncSession,
    link_token: str,
    *,
    owner_user_id: int | None = None,
    client: PlaidClient | None = None,
) -> list[SyncResult]:
    """Finish a Hosted Link: pull any public tokens the user produced, exchange
    each into a connection, and sync it. Returns ``[]`` while still pending."""
    client = client or PlaidClient()
    results: list[SyncResult] = []
    for public_token in await client.link_public_tokens(link_token):
        access_token, item_id = await client.exchange_public_token(public_token)
        connection = await create_plaid_connection(
            db,
            owner_user_id=owner_user_id,
            access_token=access_token,
            item_id=item_id,
            environment=client.environment,
        )
        results.append(await sync_plaid_connection(db, connection, client=client))
    await _recompute_net_worth(db, owner_user_id, results)
    return results


# ITEM webhook codes that flip a connection into a needs-user-action state.
_ITEM_WEBHOOK_STATUS = {
    "PENDING_EXPIRATION": "pending_expiration",
    "PENDING_DISCONNECT": "pending_disconnect",
    "USER_PERMISSION_REVOKED": "revoked",
}


def _parse_consent_expiration(raw: str | None) -> datetime | None:
    """Plaid's ISO-8601 consent deadline -> naive UTC (project convention)."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


async def process_plaid_webhook(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    client: PlaidClient | None = None,
) -> str:
    """Dispatch a VERIFIED inbound Plaid webhook (the route checks the
    ``Plaid-Verification`` JWT before this runs).

    Every first delivery is recorded to ``finance_webhook_event``; the
    idempotency key (a content hash in ``provider_event_id`` — Plaid sends no
    event id) makes a re-delivered webhook a logged-once no-op. TRANSACTIONS
    updates sync the item; ITEM lifecycle codes flip the connection's health
    (``needs_user_action`` drives the UI's amber chip and the relink flow).

    Returns ``synced`` | ``processed`` | ``ignored`` | ``unknown_item`` |
    ``duplicate``.
    """
    item_id = payload.get("item_id")
    webhook_type = payload.get("webhook_type")
    provider_event_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    event = FinanceWebhookEvent(
        provider=Provider.PLAID,
        provider_item_id=item_id,
        webhook_type=webhook_type,
        webhook_code=payload.get("webhook_code"),
        provider_event_id=provider_event_id,
        payload=payload,
        status="received",
    )
    # The unique constraint IS the dedup: inserting inside a SAVEPOINT means a
    # re-delivered (or concurrently delivered) identical webhook rolls back
    # just this insert and returns cleanly — no check-then-insert race.
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        return "duplicate"

    if webhook_type not in ("TRANSACTIONS", "ITEM"):
        event.status = "ignored"
        return "ignored"
    connection = await queries.connection_by_provider_item(
        db, provider=Provider.PLAID, provider_item_id=item_id, live_only=True
    )
    if connection is None:
        event.status = "ignored"
        return "unknown_item"
    event.connection_id = connection.id

    if webhook_type == "ITEM":
        code = payload.get("webhook_code")
        if code == "ERROR":
            error = payload.get("error") or {}
            error_code = error.get("error_code")
            connection.status = (
                "login_required" if error_code == "ITEM_LOGIN_REQUIRED" else "error"
            )
            connection.needs_user_action = True
            connection.last_error_code = error_code
            connection.status_detail = error.get("error_message")
        elif code in _ITEM_WEBHOOK_STATUS:
            connection.status = _ITEM_WEBHOOK_STATUS[code]
            connection.needs_user_action = True
            if code == "PENDING_EXPIRATION":
                connection.consent_expiration_at = _parse_consent_expiration(
                    payload.get("consent_expiration_time")
                )
        else:
            event.status = "ignored"
            return "ignored"
        db.add(connection)
        event.status = "processed"
        event.processed_at = _utcnow()
        return "processed"

    result = await sync_plaid_connection(db, connection, client=client or PlaidClient())
    event.status = "processed"
    event.processed_at = _utcnow()
    await _recompute_net_worth(db, connection.owner_user_id, [result])
    return "synced"


async def refresh_webhook_urls(
    db: AsyncSession,
    *,
    webhook_url: str,
    owner_user_id: int | None = None,
    client: PlaidClient | None = None,
) -> int:
    """Point every Plaid Item at ``webhook_url`` via ``/item/webhook/update``.

    Reconciles existing connections after the dev tunnel's public hostname
    rotates (it changes on every ``docker compose up``). Per-item failures are
    logged and skipped — one broken Item never blocks the rest. Returns the
    number of items updated.
    """
    client = client or PlaidClient()
    updated = 0
    for connection in await list_plaid_connections(db, owner_user_id=owner_user_id):
        if not connection.access_token_encrypted:
            continue
        access_token = decrypt_secret(
            connection.access_token_encrypted, context=_ACCESS_TOKEN_CONTEXT
        )
        try:
            await client.update_item_webhook(access_token, webhook_url)
        except PlaidError as exc:
            logger.warning(
                "Webhook URL update failed for connection %s: %s",
                connection.id,
                exc,
            )
            continue
        updated += 1
    return updated


async def fire_sandbox_webhook(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    connection_id: int | None = None,
    webhook_code: str = "SYNC_UPDATES_AVAILABLE",
    client: PlaidClient | None = None,
) -> list[int]:
    """Sandbox-only dev tool: have Plaid deliver a real signed webhook for
    each (or one) Plaid connection, exercising PLAID_WEBHOOK_URL,
    verification, and dispatch end to end. Returns the connection ids fired.
    """
    client = client or PlaidClient()
    if client.environment != "sandbox":
        raise PlaidError(
            "sandbox_only",
            "fire_sandbox_webhook only works with PLAID_ENV=sandbox.",
        )
    connections = await list_plaid_connections(db, owner_user_id=owner_user_id)
    if connection_id is not None:
        connections = [c for c in connections if c.id == connection_id]
    fired: list[int] = []
    for connection in connections:
        if not connection.access_token_encrypted:
            continue
        access_token = decrypt_secret(
            connection.access_token_encrypted, context=_ACCESS_TOKEN_CONTEXT
        )
        await client.fire_sandbox_webhook(access_token, webhook_code)
        fired.append(connection.id)
    return fired


async def relink_connection(
    db: AsyncSession,
    connection_id: int,
    *,
    owner_user_id: int | None = None,
    client: PlaidClient | None = None,
) -> tuple[str, str] | None:
    """Update-mode Hosted Link for a connection needing re-auth.

    Returns ``(hosted_link_url, link_token)``, or None when the connection is
    missing, another user's, not Plaid, or has no stored token. The access
    token does not change in update mode; the next successful sync flips the
    connection back to healthy and clears ``needs_user_action``.
    """
    connection = await get_connection(db, connection_id, owner_user_id=owner_user_id)
    if (
        connection is None
        or connection.provider != Provider.PLAID
        or not connection.access_token_encrypted
    ):
        return None
    access_token = decrypt_secret(
        connection.access_token_encrypted, context=_ACCESS_TOKEN_CONTEXT
    )
    client = client or PlaidClient()
    return await client.create_hosted_link(
        user_id=(
            connection.owner_user_id
            if connection.owner_user_id is not None
            else "standalone"
        ),
        update_access_token=access_token,
    )
