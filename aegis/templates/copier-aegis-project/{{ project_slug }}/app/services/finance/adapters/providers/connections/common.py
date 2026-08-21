"""What both providers need: the connection reads and the sync result shape.

A connection row is provider-agnostic - it is a link, an owner, and an
encrypted credential - so reading one back never needs to know which
aggregator issued it. ``SyncResult`` is the tally every provider's sync
pass reports in, which is what lets ``registry`` sum a mixed batch
without asking who produced each row.

Deliberately free of any provider client, so ``plaid_sync`` and
``snaptrade_sync`` can both import it without importing each other.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.providers import queries
from app.services.finance.constants import Provider
from app.services.finance.models import FinanceConnection

# The named slot a connection's encrypted credential occupies. Each provider
# stores a different secret (Plaid an access token, SnapTrade a user secret),
# but both ride the same column, and the context string is what keeps one
# from ever being decrypted as the other.
_ACCESS_TOKEN_CONTEXT = "finance.plaid.access_token"
_SNAPTRADE_SECRET_CONTEXT = "finance.snaptrade.user_secret"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_cents(amount: float | None) -> int | None:
    return None if amount is None else round(amount * 100)


class SyncResult(BaseModel):
    """What one connection's sync pass wrote."""

    connection_id: int
    accounts: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    holdings: int = 0
    trades: int = 0


async def list_provider_connections(
    db: AsyncSession,
    *,
    provider: str | None = None,
    owner_user_id: int | None = None,
) -> list[FinanceConnection]:
    """Active (non-deleted) provider connections for an owner, optionally
    narrowed to one provider."""
    return await queries.connections_for_owner(
        db, provider=provider, owner_user_id=owner_user_id
    )


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
    return await queries.connection_by_id_live(
        db, connection_id, owner_user_id=owner_user_id
    )


async def _recompute_net_worth(
    db: AsyncSession, owner_user_id: int | None, results: list[SyncResult]
) -> None:
    """Post-sync reconcile: pair internal transfers (so a card payment doesn't
    double-count as spend), detect recurring streams + "wasting money" insights,
    then refresh the net-worth snapshot series so the Overview trend reflects
    the new data. No-op if nothing synced."""
    if not results:
        return
    from app.services.finance.domains.detection import (
        detect_recurring,
        detect_transfers,
        generate_insights,
    )
    from app.services.finance.domains.ledger import networth

    await detect_transfers(db, owner_user_id=owner_user_id)
    await detect_recurring(db, owner_user_id=owner_user_id)
    await generate_insights(db, owner_user_id=owner_user_id)
    await networth.recompute_snapshots(db, owner_user_id=owner_user_id)
