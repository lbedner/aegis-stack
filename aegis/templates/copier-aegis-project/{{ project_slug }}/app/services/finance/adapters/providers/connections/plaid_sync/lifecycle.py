"""A connection's life outside of syncing: create it, re-link it, and
answer its webhooks.

``create_plaid_connection`` stores an exchanged access token (AES-GCM
encrypted) as a ``FinanceConnection``. The webhook half turns Plaid's
ITEM codes into the needs-user-action states the UI surfaces, and
kicks a sync when Plaid says there is new data.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret
from app.core.time import utcnow
from app.services.finance.adapters.providers import queries
from app.services.finance.adapters.providers.connections.common import (
    _ACCESS_TOKEN_CONTEXT,
    SyncResult,
    _recompute_net_worth,
    get_connection,
    list_plaid_connections,
)
from app.services.finance.adapters.providers.connections.plaid_sync.sync import (
    sync_plaid_connection,
)
from app.services.finance.adapters.providers.plaid import PlaidClient, PlaidError
from app.services.finance.constants import Provider
from app.services.finance.models import (
    FinanceConnection,
    FinanceWebhookEvent,
)

logger = logging.getLogger(__name__)


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
        event.processed_at = utcnow()
        return "processed"

    result = await sync_plaid_connection(db, connection, client=client or PlaidClient())
    event.status = "processed"
    event.processed_at = utcnow()
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
