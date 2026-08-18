"""Batched read queries for provider connectivity (Plaid, SnapTrade).

Set-shaped inputs, map-shaped outputs. Statement builders only - no
business logic, no writes.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceConnection,
    FinanceTransaction,
)


async def connection_by_provider_item(
    db: AsyncSession, *, provider: str, provider_item_id: str, live_only: bool = False
) -> FinanceConnection | None:
    query = select(FinanceConnection).where(
        FinanceConnection.provider == provider,
        FinanceConnection.provider_item_id == provider_item_id,
    )
    if live_only:
        query = query.where(FinanceConnection.deleted_at.is_(None))
    return (await db.exec(query)).first()


async def account_by_persistent_id(
    db: AsyncSession, *, provider: str, persistent_account_id: str
) -> FinanceAccount | None:
    return (
        await db.exec(
            select(FinanceAccount).where(
                FinanceAccount.provider == provider,
                FinanceAccount.persistent_account_id == persistent_account_id,
            )
        )
    ).first()


async def account_by_provider_account_id(
    db: AsyncSession, *, provider: str, provider_account_id: str
) -> FinanceAccount | None:
    return (
        await db.exec(
            select(FinanceAccount).where(
                FinanceAccount.provider == provider,
                FinanceAccount.provider_account_id == provider_account_id,
            )
        )
    ).first()


async def account_first_where(db: AsyncSession, filters: list) -> FinanceAccount | None:
    return (await db.exec(select(FinanceAccount).where(*filters))).first()


async def transaction_first_where(
    db: AsyncSession, filters: list
) -> FinanceTransaction | None:
    return (await db.exec(select(FinanceTransaction).where(*filters))).first()


async def provider_rows_for_accounts(
    db: AsyncSession, *, account_ids: set[int] | list[int], source: str
) -> list[FinanceTransaction]:
    """Live provider-sourced rows on the touched accounts - the sync
    dedup-lane preload."""
    if not account_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id.in_(account_ids),
                    FinanceTransaction.source == source,
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def connections_for_owner(
    db: AsyncSession,
    *,
    provider: str | None = None,
    owner_user_id: int | None = None,
) -> list[FinanceConnection]:
    query = select(FinanceConnection).where(FinanceConnection.deleted_at.is_(None))
    if provider is not None:
        query = query.where(FinanceConnection.provider == provider)
    if owner_user_id is not None:
        query = query.where(FinanceConnection.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())


async def connection_by_id_live(
    db: AsyncSession, connection_id: int, *, owner_user_id: int | None = None
) -> FinanceConnection | None:
    query = select(FinanceConnection).where(
        FinanceConnection.id == connection_id,
        FinanceConnection.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceConnection.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def live_accounts_for_connection(
    db: AsyncSession, connection_id: int
) -> list[FinanceAccount]:
    return list(
        (
            await db.exec(
                select(FinanceAccount).where(
                    FinanceAccount.connection_id == connection_id,
                    FinanceAccount.deleted_at.is_(None),
                )
            )
        ).all()
    )
