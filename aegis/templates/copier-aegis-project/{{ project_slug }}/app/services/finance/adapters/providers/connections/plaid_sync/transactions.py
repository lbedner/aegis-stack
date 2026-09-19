"""Transactions: the cursor-based ``transactions/sync`` lane.

LANE-1 dedup on Plaid's ``transaction_id``, and the removal half -
Plaid reports deletions explicitly, so a charge that vanishes upstream
has to vanish here rather than linger as a ghost.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.adapters.providers import queries
from app.services.finance.adapters.providers.connections import plaid_mapping
from app.services.finance.constants import Provider
from app.services.finance.models import (
    FinanceConnection,
    FinanceTransaction,
)
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)


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
            existing.logo_url = plaid_mapping.merchant_logo(txn)
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
        created.logo_url = plaid_mapping.merchant_logo(txn)
        db.add(created)
        lane1[(account_id, external_id)] = created
        added += 1
        if not pending and pending_provider_id:
            collapse.append((account_id, pending_provider_id, created))

    # Pending -> posted: link the posted row to its pre-auth via the self-FK
    # and tombstone the pre-auth so exactly one row stays visible.
    now = utcnow()
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
    now = utcnow()
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
