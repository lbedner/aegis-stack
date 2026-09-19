"""Accounts and liabilities: what Plaid says the account IS.

The upsert keys on Plaid's ``account_id`` so a renamed or re-linked
account stays one row, and the liability detail carries the APRs and
due dates the credit rules later read.
"""

from __future__ import annotations

from datetime import date
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.adapters.providers import queries
from app.services.finance.adapters.providers.connections.common import (
    _to_cents,
    relinked_account,
)
from app.services.finance.constants import Provider
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceConnection,
    FinanceLiabilityDetail,
)
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)


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
    return await relinked_account(
        db, connection, provider=Provider.PLAID, name=name, mask=mask
    )


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
        account.balance_as_of = utcnow()
        account.deleted_at = None
        db.add(account)
        await db.flush()
        mapping[plaid_id] = account.id
    return mapping


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
        detail.updated_at = utcnow()
        db.add(detail)
        written += 1
    await db.flush()
    return written
