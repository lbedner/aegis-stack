"""Provider connection sync: turn provider links into finance accounts + txns.

Plaid: ``create_plaid_connection`` stores an exchanged access token (AES-GCM
encrypted) as a ``FinanceConnection``. ``sync_plaid_connection`` pulls the
item's accounts (upserting ``FinanceAccount`` rows keyed by Plaid
``account_id``) and its transactions via the cursor-based ``transactions/sync``
(LANE-1 dedup on the Plaid ``transaction_id``).

SnapTrade: ``start_snaptrade_connect`` registers/reuses the owner's SnapTrade
user (its ``user_secret`` — the actual credential — is AES-GCM encrypted per
connection row) and returns the connection-portal URL;
``complete_snaptrade_connect`` adopts new brokerage authorizations into
connection rows; ``sync_snaptrade_connection`` polls accounts, positions, and
date-windowed activities into the same tables through the same shared upsert
helpers (``upsert_provider_security`` merges cross-provider duplicates by
FIGI/CUSIP/ISIN).

Writes but does not commit — the caller owns the transaction.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import logging
from typing import Any

from cryptography.fernet import InvalidToken
import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret
from app.services.finance.constants import Provider
from app.services.finance.finance_service import FinanceService
from app.services.finance.models import (
    FinanceAccount,
    FinanceConnection,
    FinanceImportBatch,
    FinanceLiabilityDetail,
    FinanceTransaction,
    FinanceWebhookEvent,
)
from app.services.finance.providers.plaid import PlaidClient, PlaidError
from app.services.finance.providers.snaptrade import SnapTradeClient, SnapTradeError

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_CONTEXT = "finance.plaid.access_token"
_SNAPTRADE_SECRET_CONTEXT = "finance.snaptrade.user_secret"
# SnapTrade error code 1010: a user with this userId already exists. The only
# condition under which the destructive delete + re-register recovery in
# start_snaptrade_connect may run.
_SNAPTRADE_USER_EXISTS_CODE = "1010"

# Plaid ``type`` -> (account_type, classification). Depository subtypes refine
# checking vs savings below.
_PLAID_TYPE_MAP: dict[str, tuple[str, str]] = {
    "depository": ("checking", "asset"),
    "credit": ("credit_card", "liability"),
    "loan": ("loan", "liability"),
    "investment": ("brokerage", "asset"),
}
_DEPOSITORY_SAVINGS = frozenset({"savings", "cd", "money market", "hsa"})


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_cents(amount: float | None) -> int | None:
    return None if amount is None else round(amount * 100)


def _map_account_kind(
    plaid_type: str | None, plaid_subtype: str | None
) -> tuple[str, str]:
    account_type, classification = _PLAID_TYPE_MAP.get(
        plaid_type or "", ("other_asset", "asset")
    )
    if plaid_type == "depository" and (plaid_subtype or "") in _DEPOSITORY_SAVINGS:
        account_type = "savings"
    return account_type, classification


@dataclass
class SyncResult:
    connection_id: int
    accounts: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    holdings: int = 0
    trades: int = 0


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
    existing = (
        await db.exec(
            select(FinanceConnection).where(
                FinanceConnection.provider == Provider.PLAID,
                FinanceConnection.provider_item_id == item_id,
            )
        )
    ).first()
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
        found = (
            await db.exec(
                select(FinanceAccount).where(
                    FinanceAccount.provider == Provider.PLAID,
                    FinanceAccount.persistent_account_id == persistent,
                )
            )
        ).first()
        if found is not None:
            return found
    # 2) Same Item re-sync (unchanged account_id).
    found = (
        await db.exec(
            select(FinanceAccount).where(
                FinanceAccount.provider == Provider.PLAID,
                FinanceAccount.provider_account_id == plaid_id,
            )
        )
    ).first()
    if found is not None:
        return found
    # 3) Re-link fallback (no persistent id, e.g. sandbox): same owner + name +
    # mask. Plaid regenerates account_ids per Item, but name/mask are stable.
    query = select(FinanceAccount).where(
        FinanceAccount.provider == Provider.PLAID,
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_(None),
    )
    query = query.where(
        FinanceAccount.mask == mask
        if mask is not None
        else FinanceAccount.mask.is_(None)
    )
    if connection.owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == connection.owner_user_id)
    return (await db.exec(query)).first()


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
    from app.services.finance.importers.base import normalize_payee

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
    for row in (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.account_id.in_(touched),
                FinanceTransaction.source == Provider.PLAID,
                FinanceTransaction.deleted_at.is_(None),
            )
        )
    ).all():
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
    existing_by_account = {
        row.account_id: row
        for row in (
            await db.exec(
                select(FinanceLiabilityDetail).where(
                    FinanceLiabilityDetail.account_id.in_(touched)
                )
            )
        ).all()
    }
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
        txn = (await db.exec(select(FinanceTransaction).where(*conditions))).first()
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


async def list_provider_connections(
    db: AsyncSession,
    *,
    provider: str | None = None,
    owner_user_id: int | None = None,
) -> list[FinanceConnection]:
    """Active (non-deleted) provider connections for an owner, optionally
    narrowed to one provider."""
    query = select(FinanceConnection).where(FinanceConnection.deleted_at.is_(None))
    if provider is not None:
        query = query.where(FinanceConnection.provider == provider)
    if owner_user_id is not None:
        query = query.where(FinanceConnection.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())


async def list_plaid_connections(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceConnection]:
    """Active (non-deleted) Plaid connections for an owner."""
    return await list_provider_connections(
        db, provider=Provider.PLAID, owner_user_id=owner_user_id
    )


async def get_connection(
    db: AsyncSession, connection_id: int, *, owner_user_id: int | None = None
) -> FinanceConnection | None:
    """A single non-deleted connection, scoped to the owner when given."""
    query = select(FinanceConnection).where(
        FinanceConnection.id == connection_id,
        FinanceConnection.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceConnection.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def disconnect_connection(
    db: AsyncSession,
    connection_id: int,
    *,
    owner_user_id: int | None = None,
    client: PlaidClient | None = None,
    snaptrade_client: SnapTradeClient | None = None,
) -> tuple[bool, Callable[[], Awaitable[None]] | None]:
    """Disconnect a connection: soft-delete it and every account under it
    right away, and return a best-effort provider revoke for the caller to
    run AFTER responding (FastAPI ``BackgroundTasks``). The provider round
    trip is the slow part of a disconnect; keeping it out of the request
    path makes the UI feel instant. Transactions/history rows are kept.

    Returns ``(removed, revoke)``: ``removed`` is False when the connection
    doesn't exist for this owner; ``revoke`` is None when there is nothing
    to revoke remotely. The revoke callable never raises — provider errors
    (already-invalid credential, unreachable API) are logged and swallowed,
    since the local teardown has already happened.
    """
    connection = await get_connection(db, connection_id, owner_user_id=owner_user_id)
    if connection is None:
        return False, None

    revoke: Callable[[], Awaitable[None]] | None = None
    if connection.provider == Provider.SNAPTRADE:
        if connection.access_token_encrypted and connection.provider_item_id:
            # A corrupted/rekeyed ciphertext must never block the local
            # teardown - there is simply nothing usable to revoke remotely.
            try:
                user_secret = decrypt_secret(
                    connection.access_token_encrypted,
                    context=_SNAPTRADE_SECRET_CONTEXT,
                )
            except InvalidToken as exc:
                logger.warning(
                    "Stored SnapTrade secret for connection %s is "
                    "undecryptable; skipping provider revoke: %s",
                    connection.id,
                    exc,
                )
                user_secret = None
            if user_secret is not None:
                secret = user_secret
                authorization_id = connection.provider_item_id
                conn_id = connection.id
                conn_owner_id = connection.owner_user_id

                async def _revoke_snaptrade() -> None:
                    try:
                        st_client = snaptrade_client or SnapTradeClient()
                        await st_client.remove_authorization(
                            ""
                            if st_client.is_personal
                            else _snaptrade_user_id(conn_owner_id),
                            secret,
                            authorization_id,
                        )
                    except (SnapTradeError, httpx.HTTPError) as exc:
                        logger.warning(
                            "SnapTrade revoke failed for connection %s (already "
                            "torn down locally): %s",
                            conn_id,
                            exc,
                        )

                revoke = _revoke_snaptrade
    elif connection.access_token_encrypted:
        try:
            access_token = decrypt_secret(
                connection.access_token_encrypted, context=_ACCESS_TOKEN_CONTEXT
            )
        except InvalidToken as exc:
            logger.warning(
                "Stored Plaid token for connection %s is undecryptable; "
                "skipping provider revoke: %s",
                connection.id,
                exc,
            )
            access_token = None
        if access_token is not None:
            token = access_token
            plaid_conn_id = connection.id

            async def _revoke_plaid() -> None:
                try:
                    await (client or PlaidClient()).remove_item(token)
                except (PlaidError, httpx.HTTPError) as exc:
                    # already-invalid token (PlaidError) or Plaid unreachable
                    # (timeout/connect error from httpx) — the local teardown
                    # already happened, so just log it.
                    logger.warning(
                        "Plaid revoke failed for connection %s (already torn "
                        "down locally): %s",
                        plaid_conn_id,
                        exc,
                    )

            revoke = _revoke_plaid

    now = _utcnow()
    accounts = (
        await db.exec(
            select(FinanceAccount).where(
                FinanceAccount.connection_id == connection_id,
                FinanceAccount.deleted_at.is_(None),
            )
        )
    ).all()
    for account in accounts:
        account.deleted_at = now
        db.add(account)

    connection.status = "revoked"
    connection.removed_at = now
    connection.deleted_at = now
    connection.access_token_encrypted = None
    db.add(connection)
    await db.flush()
    return True, revoke


async def _recompute_net_worth(
    db: AsyncSession, owner_user_id: int | None, results: list[SyncResult]
) -> None:
    """Post-sync reconcile: pair internal transfers (so a card payment doesn't
    double-count as spend), detect recurring streams + "wasting money" insights,
    then refresh the net-worth snapshot series so the Overview trend reflects
    the new data. No-op if nothing synced."""
    if not results:
        return
    from app.services.finance import networth_service
    from app.services.finance.categorize import (
        detect_recurring,
        detect_transfers,
        generate_insights,
    )

    await detect_transfers(db, owner_user_id=owner_user_id)
    await detect_recurring(db, owner_user_id=owner_user_id)
    await generate_insights(db, owner_user_id=owner_user_id)
    await networth_service.recompute_snapshots(db, owner_user_id=owner_user_id)


async def _sync_isolated(
    db: AsyncSession,
    connection: FinanceConnection,
    sync: Callable[[], Awaitable[SyncResult]],
) -> SyncResult | None:
    """Run one connection's sync inside a SAVEPOINT.

    A failure rolls back only that connection's partial writes (preserving the
    all-or-nothing cursor invariant), marks the connection ``error`` with
    detail, and returns None — one failing bank never kills the others.
    """
    connection_id = connection.id
    try:
        async with db.begin_nested():
            result = await sync()
    except Exception as exc:
        logger.exception("Finance sync failed for connection %s", connection_id)
        connection.status = "error"
        connection.status_detail = str(exc)[:500]
        connection.last_error_code = getattr(exc, "error_code", None)
        connection.last_sync_attempt_at = _utcnow()
        db.add(connection)
        await db.flush()
        return None
    logger.info(
        "Finance sync: connection %s -> %d account(s), +%d/%d/-%d txn(s), "
        "%d holding(s), %d trade(s)",
        connection_id,
        result.accounts,
        result.added,
        result.updated,
        result.removed,
        result.holdings,
        result.trades,
    )
    return result


async def sync_owner_connections(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    client: PlaidClient | None = None,
    snaptrade_client: SnapTradeClient | None = None,
) -> list[SyncResult]:
    """Sync every healthy provider connection for an owner.

    Dispatches on ``connection.provider``. Provider clients are only
    constructed when a connection of that provider exists, so a
    single-provider deployment never touches the other's credentials/SDK.
    Connections flagged ``needs_user_action`` are skipped (re-auth spam helps
    nobody); per-connection failures are isolated in ``_sync_isolated`` and
    absent from the returned results.
    """
    results: list[SyncResult] = []
    plaid_connections = [
        c
        for c in await list_plaid_connections(db, owner_user_id=owner_user_id)
        if not c.needs_user_action
    ]
    if plaid_connections:
        client = client or PlaidClient()
        for connection in plaid_connections:
            result = await _sync_isolated(
                db,
                connection,
                lambda c=connection: sync_plaid_connection(db, c, client=client),
            )
            if result is not None:
                results.append(result)
    snaptrade_connections = [
        c
        for c in await list_provider_connections(
            db, provider=Provider.SNAPTRADE, owner_user_id=owner_user_id
        )
        # Rows still waiting on the portal (no authorization yet) can't sync.
        if c.provider_item_id is not None and not c.needs_user_action
    ]
    if snaptrade_connections:
        snaptrade_client = snaptrade_client or SnapTradeClient()
        for connection in snaptrade_connections:
            result = await _sync_isolated(
                db,
                connection,
                lambda c=connection: sync_snaptrade_connection(
                    db, c, client=snaptrade_client
                ),
            )
            if result is not None:
                results.append(result)
    await _recompute_net_worth(db, owner_user_id, results)
    return results


async def sync_one_connection(
    db: AsyncSession,
    connection_id: int,
    *,
    owner_user_id: int | None = None,
    client: PlaidClient | None = None,
    snaptrade_client: SnapTradeClient | None = None,
) -> SyncResult | None:
    """Targeted sync of a single connection — the CLI debugging tool.

    Unlike the all-connections path this neither skips ``needs_user_action``
    nor swallows provider errors: when debugging one bank, the caller wants
    the real failure. Returns None when the connection is missing, foreign,
    or not syncable (manual / portal-pending).
    """
    connection = await get_connection(db, connection_id, owner_user_id=owner_user_id)
    if connection is None:
        return None
    if connection.provider == Provider.PLAID:
        result = await sync_plaid_connection(
            db, connection, client=client or PlaidClient()
        )
    elif (
        connection.provider == Provider.SNAPTRADE
        and connection.provider_item_id is not None
    ):
        result = await sync_snaptrade_connection(
            db, connection, client=snaptrade_client or SnapTradeClient()
        )
    else:
        return None
    await _recompute_net_worth(db, connection.owner_user_id, [result])
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
    connection = (
        await db.exec(
            select(FinanceConnection).where(
                FinanceConnection.provider == Provider.PLAID,
                FinanceConnection.provider_item_id == item_id,
                FinanceConnection.deleted_at.is_(None),
            )
        )
    ).first()
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


# --------------------------------------------------------------------------- #
# SnapTrade (brokerage authorizations — the Fidelity path)
# --------------------------------------------------------------------------- #

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
    found = (
        await db.exec(
            select(FinanceAccount).where(
                FinanceAccount.provider == Provider.SNAPTRADE,
                FinanceAccount.provider_account_id == snaptrade_id,
            )
        )
    ).first()
    if found is not None:
        return found
    query = select(FinanceAccount).where(
        FinanceAccount.provider == Provider.SNAPTRADE,
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_(None),
    )
    query = query.where(
        FinanceAccount.mask == mask
        if mask is not None
        else FinanceAccount.mask.is_(None)
    )
    if connection.owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == connection.owner_user_id)
    return (await db.exec(query)).first()


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
