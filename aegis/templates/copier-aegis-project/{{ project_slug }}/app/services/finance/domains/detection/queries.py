"""Batched read queries for the detection package.

Detection fetches are analytical one-offs, so alongside the named
fetchers this module exposes generic executors taking caller-built
predicate lists (built from the models plus ``owner_clause``). Either
way, every statement executes here - no ``db.exec`` in the detectors.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceAnalystSnapshot,
    FinanceCategory,
    FinanceInsight,
    FinanceMerchant,
    FinanceRecurringStream,
    FinanceTransaction,
    FinanceTransfer,
)


def owner_clause(column, owner_user_id: int | None):
    """Detection's owner scope: NULL-owner rows match IS NULL (standalone
    installs), unlike the API layer's skip-when-None convention."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


# -- generic executors --------------------------------------------------------


async def transaction_rows_where(
    db: AsyncSession,
    filters: list,
    *,
    order_by_id: bool = False,
    limit: int | None = None,
) -> list[FinanceTransaction]:
    query = select(FinanceTransaction).where(*filters)
    if order_by_id:
        query = query.order_by(FinanceTransaction.id)
    if limit is not None:
        query = query.limit(limit)
    return list((await db.exec(query)).all())


async def account_rows_where(db: AsyncSession, filters: list) -> list[FinanceAccount]:
    return list((await db.exec(select(FinanceAccount).where(*filters))).all())


# -- transfers ----------------------------------------------------------------


async def claimed_leg_ids(db: AsyncSession, owner_user_id: int | None) -> set[int]:
    """Transaction ids already claimed by a transfer of ANY status, so
    pairings (including rejected ones) never recur."""
    transfer_owner = owner_clause(FinanceTransfer.owner_user_id, owner_user_id)
    paired_ids: set[int] = set()
    for col in (
        FinanceTransfer.from_transaction_id,
        FinanceTransfer.to_transaction_id,
    ):
        rows = (
            await db.exec(select(col).where(col.is_not(None), transfer_owner))
        ).all()
        paired_ids.update(int(r) for r in rows)
    return paired_ids


def transfer_category_ids():
    """Subquery: category ids classified as transfers."""
    return select(FinanceCategory.id).where(
        FinanceCategory.classification == "transfer"
    )


# -- streams ------------------------------------------------------------------


async def promotable_streams(
    db: AsyncSession, *, store_owner: int
) -> list[FinanceRecurringStream]:
    """Derived outflow streams not yet marked subscriptions."""
    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.owner_user_id == store_owner,
                    FinanceRecurringStream.deleted_at.is_(None),
                    FinanceRecurringStream.direction == "outflow",
                    FinanceRecurringStream.is_subscription.is_(False),
                    FinanceRecurringStream.source == "derived",
                )
            )
        ).all()
    )


async def stream_member_categories(
    db: AsyncSession, stream_ids: list[int], owner_user_id: int | None
) -> list[tuple[int, str]]:
    """(stream_id, category name) for every categorized live member."""
    if not stream_ids:
        return []
    rows = (
        await db.exec(
            select(FinanceTransaction.recurring_stream_id, FinanceCategory.name)
            .join(
                FinanceCategory,
                FinanceCategory.id == FinanceTransaction.category_id,
            )
            .where(
                owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.recurring_stream_id.in_(stream_ids),
                FinanceTransaction.category_id.is_not(None),
            )
        )
    ).all()
    return list(rows)


# -- insights -----------------------------------------------------------------


async def insight_rows_where(db: AsyncSession, filters: list) -> list[FinanceInsight]:
    return list((await db.exec(select(FinanceInsight).where(*filters))).all())


async def insight_first_where(db: AsyncSession, filters: list) -> FinanceInsight | None:
    return (await db.exec(select(FinanceInsight).where(*filters))).first()


async def stream_rows_where(
    db: AsyncSession, filters: list
) -> list[FinanceRecurringStream]:
    return list((await db.exec(select(FinanceRecurringStream).where(*filters))).all())


async def stream_ids_where(db: AsyncSession, filters: list) -> list[int]:
    return list(
        (await db.exec(select(FinanceRecurringStream.id).where(*filters))).all()
    )


async def insight_exists(
    db: AsyncSession, *, owner_user_id: int, dedup_key: str
) -> bool:
    """The dedup probe behind ``create_insight_if_new`` - one indexed
    lookup per candidate."""
    row = (
        await db.exec(
            select(FinanceInsight.id).where(
                FinanceInsight.owner_user_id == owner_user_id,
                FinanceInsight.dedup_key == dedup_key,
            )
        )
    ).first()
    return row is not None


async def sibling_streams_raw(
    db: AsyncSession,
    *,
    owner_user_id: int,
    account_id: int,
    direction: str,
) -> list[FinanceRecurringStream]:
    """Every live local (non-provider) stream on this account+direction;
    the caller narrows to the payee base and its splits."""
    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.owner_user_id == owner_user_id,
                    FinanceRecurringStream.account_id == account_id,
                    FinanceRecurringStream.direction == direction,
                    FinanceRecurringStream.provider_stream_id.is_(None),
                    FinanceRecurringStream.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def any_member_linked(
    db: AsyncSession, *, stream_id: int, member_ids: list[int] | set[int]
) -> bool:
    """Whether any of ``member_ids`` already sits in ``stream_id``."""
    row = (
        await db.exec(
            select(FinanceTransaction.id).where(
                FinanceTransaction.recurring_stream_id == stream_id,
                FinanceTransaction.id.in_(list(member_ids)),
            )
        )
    ).first()
    return row is not None


async def confirmed_stream_ids(db: AsyncSession) -> list[int]:
    """Ids of user-confirmed or user-created live streams."""
    from sqlmodel import or_

    rows = (
        await db.exec(
            select(FinanceRecurringStream.id).where(
                or_(
                    FinanceRecurringStream.is_user_confirmed.is_(True),
                    FinanceRecurringStream.source == "user",
                ),
                FinanceRecurringStream.deleted_at.is_(None),
            )
        )
    ).all()
    return [s for s in rows if s is not None]


async def member_ids_of_streams(
    db: AsyncSession, stream_ids: list[int], owner_user_id: int | None
) -> set[int]:
    """Live member-transaction ids of the given streams."""
    if not stream_ids:
        return set()
    rows = (
        await db.exec(
            select(FinanceTransaction.id).where(
                FinanceTransaction.recurring_stream_id.in_(stream_ids),
                FinanceTransaction.deleted_at.is_(None),
                owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            )
        )
    ).all()
    return {t for t in rows if t is not None}


async def merchant_names_by_ids(
    db: AsyncSession, ids: set[int] | list[int]
) -> dict[int, str]:
    wanted = [i for i in set(ids) if i is not None]
    if not wanted:
        return {}
    rows = (
        await db.exec(select(FinanceMerchant).where(FinanceMerchant.id.in_(wanted)))
    ).all()
    return {m.id: m.name for m in rows}


async def streams_by_ids(
    db: AsyncSession, ids: set[int] | list[int]
) -> list[FinanceRecurringStream]:
    wanted = list(set(ids))
    if not wanted:
        return []
    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.id.in_(wanted)
                )
            )
        ).all()
    )


async def linked_stream_ids(db: AsyncSession) -> set[int]:
    """Every stream id with at least one live member transaction."""
    rows = (
        await db.exec(
            select(FinanceTransaction.recurring_stream_id).where(
                FinanceTransaction.recurring_stream_id.is_not(None),
                FinanceTransaction.deleted_at.is_(None),
            )
        )
    ).all()
    return {sid for sid in rows if sid is not None}


async def local_stream_by_key(
    db: AsyncSession,
    *,
    owner_user_id: int,
    account_id: int | None,
    direction: str,
    normalized_payee: str,
) -> FinanceRecurringStream | None:
    """The stream occupying the detected unique key, live or retired."""
    return (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == owner_user_id,
                FinanceRecurringStream.account_id == account_id,
                FinanceRecurringStream.direction == direction,
                FinanceRecurringStream.normalized_payee == normalized_payee,
                FinanceRecurringStream.provider_stream_id.is_(None),
            )
        )
    ).first()


# -- analyst snapshots --------------------------------------------------------


async def analyst_snapshot_on(
    db: AsyncSession, *, store_owner: int, day: date
) -> FinanceAnalystSnapshot | None:
    return (
        await db.exec(
            select(FinanceAnalystSnapshot).where(
                FinanceAnalystSnapshot.owner_user_id == store_owner,
                FinanceAnalystSnapshot.as_of_date == day,
            )
        )
    ).first()


async def analyst_snapshot_before(
    db: AsyncSession, *, store_owner: int, day: date
) -> FinanceAnalystSnapshot | None:
    return (
        await db.exec(
            select(FinanceAnalystSnapshot)
            .where(
                FinanceAnalystSnapshot.owner_user_id == store_owner,
                FinanceAnalystSnapshot.as_of_date < day,
            )
            .order_by(FinanceAnalystSnapshot.as_of_date.desc())
            .limit(1)
        )
    ).first()


async def analyst_snapshots_between(
    db: AsyncSession, *, store_owner: int, start: date, end: date
) -> list[FinanceAnalystSnapshot]:
    return list(
        (
            await db.exec(
                select(FinanceAnalystSnapshot)
                .where(
                    FinanceAnalystSnapshot.owner_user_id == store_owner,
                    FinanceAnalystSnapshot.as_of_date >= start,
                    FinanceAnalystSnapshot.as_of_date <= end,
                )
                .order_by(FinanceAnalystSnapshot.as_of_date)
            )
        ).all()
    )
