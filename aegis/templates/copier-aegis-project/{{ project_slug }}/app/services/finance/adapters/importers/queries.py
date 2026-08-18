"""Batched read queries for the import pipeline.

Set-shaped inputs, map-shaped outputs, so callers cannot reintroduce a
per-row query loop. Statement builders only - no business logic, no
writes.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from app.services.finance.models import (
    FinanceAccount,
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceImportProfile,
    FinanceTransaction,
    FinanceTransactionTag,
)


async def account_id_by_provider_key(
    db: AsyncSession, *, account_key: str, owner_user_id: int | None
) -> int | None:
    query = select(FinanceAccount.id).where(
        FinanceAccount.provider_account_id == account_key,
        FinanceAccount.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


def _owner_scoped_account(
    query: SelectOfScalar[int], owner_user_id: int | None
) -> SelectOfScalar[int]:
    if owner_user_id is not None:
        return query.where(FinanceAccount.owner_user_id == owner_user_id)
    return query.where(FinanceAccount.owner_user_id.is_(None))


async def live_account_id_by_name(
    db: AsyncSession, *, name: str, owner_user_id: int | None
) -> int | None:
    query = select(FinanceAccount.id).where(
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_(None),
    )
    return (await db.exec(_owner_scoped_account(query, owner_user_id))).first()


async def removed_account_exists(
    db: AsyncSession, *, name: str, owner_user_id: int | None
) -> bool:
    """A soft-deleted account with this name is a standing "no" - its
    rows are ignored rather than the account resurrected."""
    query = select(FinanceAccount.id).where(
        FinanceAccount.name == name,
        FinanceAccount.deleted_at.is_not(None),
    )
    row = (await db.exec(_owner_scoped_account(query, owner_user_id))).first()
    return row is not None


async def account_ref(db: AsyncSession, account_id: int) -> FinanceAccount | None:
    return await db.get(FinanceAccount, account_id)


async def live_transactions_for_accounts(
    db: AsyncSession, account_ids: list[int] | set[int]
) -> list[FinanceTransaction]:
    """Every live row on the touched accounts - the dedup-lane preload."""
    if not account_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id.in_(account_ids),
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def deleted_transactions_for_accounts(
    db: AsyncSession, account_ids: list[int] | set[int]
) -> list[FinanceTransaction]:
    """Soft-deleted rows on the touched accounts - their lane keys refuse
    resurrection on re-import."""
    if not account_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id.in_(account_ids),
                    FinanceTransaction.deleted_at.is_not(None),
                )
            )
        ).all()
    )


async def tag_links_for_transaction(
    db: AsyncSession, transaction_id: int
) -> list[FinanceTransactionTag]:
    return list(
        (
            await db.exec(
                select(FinanceTransactionTag).where(
                    FinanceTransactionTag.transaction_id == transaction_id
                )
            )
        ).all()
    )


async def prior_batch(
    db: AsyncSession, *, batch_owner: int, file_sha256: str
) -> FinanceImportBatch | None:
    """The batch that already ingested these exact bytes, if any."""
    return (
        await db.exec(
            select(FinanceImportBatch).where(
                FinanceImportBatch.owner_user_id == batch_owner,
                FinanceImportBatch.file_sha256 == file_sha256,
            )
        )
    ).first()


async def csv_profiles(db: AsyncSession) -> list[FinanceImportProfile]:
    return list(
        (
            await db.exec(
                select(FinanceImportProfile).where(
                    FinanceImportProfile.source_format == "csv",
                    FinanceImportProfile.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def import_batch_by_id(
    db: AsyncSession, batch_id: int, *, batch_owner: int
) -> FinanceImportBatch | None:
    return (
        await db.exec(
            select(FinanceImportBatch).where(
                FinanceImportBatch.id == batch_id,
                FinanceImportBatch.owner_user_id == batch_owner,
            )
        )
    ).first()


async def import_batches_page(
    db: AsyncSession, *, batch_owner: int, page: int, page_size: int
) -> list[FinanceImportBatch]:
    query = (
        select(FinanceImportBatch)
        .where(FinanceImportBatch.owner_user_id == batch_owner)
        .order_by(FinanceImportBatch.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.exec(query)).all())


async def import_batch_rows(
    db: AsyncSession, batch_id: int
) -> list[FinanceImportBatchRow]:
    query = (
        select(FinanceImportBatchRow)
        .where(FinanceImportBatchRow.import_batch_id == batch_id)
        .order_by(FinanceImportBatchRow.row_number)
    )
    return list((await db.exec(query)).all())
