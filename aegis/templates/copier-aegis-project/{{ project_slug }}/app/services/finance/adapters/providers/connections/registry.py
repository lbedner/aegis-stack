"""Provider-agnostic verbs: disconnect one, sync all of them.

The only module that knows both providers exist. Everything here
dispatches on ``connection.provider`` and hands off - which is why the
per-provider modules never import each other, and why adding a third
aggregator touches this file and nothing else in the package.

``_sync_isolated`` is the reason a batch sync is safe: one dead
connection returns ``None`` instead of taking the other accounts' data
down with it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

from cryptography.fernet import InvalidToken
import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_secret
from app.services.finance.adapters.providers import queries
from app.services.finance.adapters.providers.connections import (
    plaid_sync,
    snaptrade_sync,
)
from app.services.finance.adapters.providers.connections.common import (
    _ACCESS_TOKEN_CONTEXT,
    _SNAPTRADE_SECRET_CONTEXT,
    SyncResult,
    _recompute_net_worth,
    _utcnow,
    get_connection,
    list_plaid_connections,
    list_provider_connections,
)
from app.services.finance.adapters.providers.plaid import PlaidClient, PlaidError
from app.services.finance.adapters.providers.snaptrade import (
    SnapTradeClient,
    SnapTradeError,
)
from app.services.finance.constants import Provider
from app.services.finance.models import FinanceConnection

logger = logging.getLogger(__name__)


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
                            else snaptrade_sync._snaptrade_user_id(conn_owner_id),
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
    accounts = await queries.live_accounts_for_connection(db, connection_id)
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
                lambda c=connection: plaid_sync.sync_plaid_connection(
                    db, c, client=client
                ),
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
                lambda c=connection: snaptrade_sync.sync_snaptrade_connection(
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
        result = await plaid_sync.sync_plaid_connection(
            db, connection, client=client or PlaidClient()
        )
    elif (
        connection.provider == Provider.SNAPTRADE
        and connection.provider_item_id is not None
    ):
        result = await snaptrade_sync.sync_snaptrade_connection(
            db, connection, client=snaptrade_client or SnapTradeClient()
        )
    else:
        return None
    await _recompute_net_worth(db, connection.owner_user_id, [result])
    return result
