"""Registering the SnapTrade user and adopting its brokerages.

``start_snaptrade_connect`` registers (or reuses) the owner's
SnapTrade user and returns the connection-portal URL;
``complete_snaptrade_connect`` adopts new brokerage authorizations
into connection rows and syncs them once.
"""

import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_secret
from app.services.finance.adapters.providers.connections.common import (
    _SNAPTRADE_SECRET_CONTEXT,
    SyncResult,
    _recompute_net_worth,
    list_provider_connections,
)
from app.services.finance.adapters.providers.connections.snaptrade_sync.sync import (
    _snaptrade_user_id,
    _snaptrade_user_secret,
    sync_snaptrade_connection,
)
from app.services.finance.adapters.providers.snaptrade import (
    SnapTradeClient,
    SnapTradeError,
)
from app.services.finance.constants import Provider
from app.services.finance.models import FinanceConnection

logger = logging.getLogger(__name__)

# SnapTrade error code 1010: a user with this userId already exists. The only
# condition under which the destructive delete + re-register recovery in
# start_snaptrade_connect may run.
_SNAPTRADE_USER_EXISTS_CODE = "1010"


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
