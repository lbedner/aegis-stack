"""One sync pass over a connection: accounts, then everything keyed
to them.

Writes but does not commit - the caller owns the transaction.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_secret
from app.core.time import utcnow
from app.services.finance.adapters.providers.connections.common import (
    _ACCESS_TOKEN_CONTEXT,
    SyncResult,
)
from app.services.finance.adapters.providers.connections.plaid_sync.accounts import (
    _apply_liabilities,
    _upsert_accounts,
)
from app.services.finance.adapters.providers.connections.plaid_sync.investments import (
    _INVESTMENT_LOOKBACK_DAYS,
    _apply_holdings,
    _apply_trades,
    _upsert_securities,
)
from app.services.finance.adapters.providers.connections.plaid_sync.transactions import (
    _apply_transactions,
    _remove_transactions,
)
from app.services.finance.adapters.providers.plaid import PlaidClient, PlaidError
from app.services.finance.models import (
    FinanceConnection,
    FinanceImportBatch,
)
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)


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
        end = utcnow().date()
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
    connection.last_sync_attempt_at = utcnow()
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
        started_at=utcnow(),
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
    batch.finished_at = utcnow()
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
    connection.last_successful_sync_at = utcnow()
    db.add(connection)
    await db.flush()
    return result
