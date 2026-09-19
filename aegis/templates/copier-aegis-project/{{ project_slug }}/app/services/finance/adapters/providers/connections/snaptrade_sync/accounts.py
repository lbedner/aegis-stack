"""The brokerage accounts SnapTrade reports.

Keyed on SnapTrade's own account id so a renamed account stays one
row, and written into the same tables Plaid writes.
"""

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
from app.services.finance.models import FinanceAccount, FinanceConnection
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)


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
    return await relinked_account(
        db, connection, provider=Provider.SNAPTRADE, name=name, mask=mask
    )


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
        account.balance_as_of = utcnow()
        account.deleted_at = None
        db.add(account)
        await db.flush()
        mapping[snaptrade_id] = account.id
    return mapping
