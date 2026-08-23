"""Batched reads the recurring domain issues.

Statement builders only - no business logic, no writes, same contract as
the planning package's shared ``queries``. These live here rather than
there because nothing outside this package asks for them: a stream's
members, the slot its unique key occupies, the rows a payee left
unclaimed.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.orm import aliased
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceCategory,
    FinanceRecurringStream,
    FinanceTransaction,
    FinanceTransfer,
)


def owner_clause_txn(column, owner_user_id: int | None):
    """NULL-owner (standalone) rows match IS NULL, same convention the
    categorize package uses."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


async def all_live_streams(db: AsyncSession) -> list[FinanceRecurringStream]:
    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def active_streams(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceRecurringStream]:
    """Live, non-cancelled streams, soonest-due first."""
    query = select(FinanceRecurringStream).where(
        FinanceRecurringStream.deleted_at.is_(None),
        FinanceRecurringStream.status != "cancelled",
    )
    if owner_user_id is not None:
        query = query.where(FinanceRecurringStream.owner_user_id == owner_user_id)
    query = query.order_by(FinanceRecurringStream.next_expected_date)
    return list((await db.exec(query)).all())


async def stream_by_id(
    db: AsyncSession, stream_id: int, *, owner_user_id: int | None = None
) -> FinanceRecurringStream | None:
    query = select(FinanceRecurringStream).where(FinanceRecurringStream.id == stream_id)
    if owner_user_id is not None:
        query = query.where(FinanceRecurringStream.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def transfer_flagged_stream_ids(
    db: AsyncSession, stream_ids: Sequence[int]
) -> set[int]:
    """Streams with any transfer-flagged member transaction."""
    if not stream_ids:
        return set()
    rows = (
        await db.exec(
            select(FinanceTransaction.recurring_stream_id)
            .where(
                FinanceTransaction.recurring_stream_id.in_(list(stream_ids)),
                FinanceTransaction.is_transfer.is_(True),
            )
            .distinct()
        )
    ).all()
    return {int(row) for row in rows}


async def payment_flagged_stream_ids(
    db: AsyncSession, stream_ids: Sequence[int]
) -> set[int]:
    """Streams whose members are the cash side of confirmed transfers
    into a liability account (card/loan payments)."""
    if not stream_ids:
        return set()
    to_txn = select(FinanceTransaction.account_id).where(
        FinanceTransaction.id == FinanceTransfer.to_transaction_id
    )
    rows = (
        await db.exec(
            select(FinanceTransaction.recurring_stream_id)
            .where(
                FinanceTransaction.recurring_stream_id.in_(list(stream_ids)),
                select(FinanceTransfer.id)
                .join(
                    FinanceAccount,
                    FinanceAccount.id == to_txn.scalar_subquery(),
                )
                .where(
                    FinanceTransfer.from_transaction_id == FinanceTransaction.id,
                    FinanceTransfer.status == "confirmed",
                    FinanceAccount.classification == "liability",
                )
                .exists(),
            )
            .distinct()
        )
    ).all()
    return {int(row) for row in rows}


async def stray_payee_rows(
    db: AsyncSession,
    *,
    exclude_transaction_id: int,
    merchant_id: int,
    inflow: bool,
    owner_clause,
) -> list[FinanceTransaction]:
    """The payee's live rows not claimed by any LIVE stream - the
    backfill population when a transaction is attached to a bill."""
    live_claim = select(FinanceRecurringStream.id).where(
        FinanceRecurringStream.id == FinanceTransaction.recurring_stream_id,
        FinanceRecurringStream.deleted_at.is_(None),
    )
    amount_clause = (
        FinanceTransaction.amount > 0 if inflow else FinanceTransaction.amount < 0
    )
    rows = (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.id != exclude_transaction_id,
                FinanceTransaction.merchant_id == merchant_id,
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                amount_clause,
                or_(
                    FinanceTransaction.recurring_stream_id.is_(None),
                    ~live_claim.exists(),
                ),
                owner_clause,
            )
        )
    ).all()
    return list(rows)


async def candidate_rows(
    db: AsyncSession, filters: list, *, limit: int
) -> list[FinanceTransaction]:
    """Match-candidate fetch under caller-built predicate fragments,
    newest first."""
    return list(
        (
            await db.exec(
                select(FinanceTransaction)
                .where(*filters)
                .order_by(FinanceTransaction.date_.desc())
                .limit(limit)
            )
        ).all()
    )


async def stream_slot_clash(
    db: AsyncSession,
    *,
    owner_user_id: int,
    account_id: int,
    direction: str,
    normalized_payee: str,
    exclude_stream_id: int,
) -> FinanceRecurringStream | None:
    """The stream already occupying the (owner, account, direction,
    payee) unique slot, retired rows included (the index has no
    deleted_at predicate)."""
    return (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == owner_user_id,
                FinanceRecurringStream.account_id == account_id,
                FinanceRecurringStream.direction == direction,
                FinanceRecurringStream.normalized_payee == normalized_payee,
                FinanceRecurringStream.provider_stream_id.is_(None),
                FinanceRecurringStream.id != exclude_stream_id,
            )
        )
    ).first()


async def stream_member_category_votes(
    db: AsyncSession, stream_ids: list[int]
) -> list[tuple[int, str, int]]:
    """(stream_id, category name, hits) across member transactions."""
    rows = (
        await db.exec(
            select(
                FinanceTransaction.recurring_stream_id,
                FinanceCategory.name,
                func.count().label("hits"),
            )
            .join(
                FinanceCategory,
                FinanceCategory.id == FinanceTransaction.category_id,
            )
            .where(
                FinanceTransaction.recurring_stream_id.in_(stream_ids),
                FinanceTransaction.deleted_at.is_(None),
            )
            .group_by(FinanceTransaction.recurring_stream_id, FinanceCategory.name)
        )
    ).all()
    return list(rows)


async def stream_member_category_id(
    db: AsyncSession, stream_id: int
) -> int | None:
    """The member transactions' most common category id.

    The id-flavored twin of ``stream_member_category_votes`` (which
    feeds the DISPLAY inference by name): a bill that stores no
    category still has an effective one wherever its matched history
    agrees, and the match shortlist needs it as an id to compare
    against candidates.
    """
    row = (
        await db.exec(
            select(FinanceTransaction.category_id, func.count().label("hits"))
            .where(
                FinanceTransaction.recurring_stream_id == stream_id,
                FinanceTransaction.category_id.is_not(None),
                FinanceTransaction.deleted_at.is_(None),
            )
            .group_by(FinanceTransaction.category_id)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()
    return row[0] if row else None


async def stream_stored_category_names(
    db: AsyncSession, stream_ids: list[int]
) -> list[tuple[int, str]]:
    """(stream_id, category name) for streams with a category set ON the
    bill itself."""
    rows = (
        await db.exec(
            select(FinanceRecurringStream.id, FinanceCategory.name)
            .join(
                FinanceCategory,
                FinanceCategory.id == FinanceRecurringStream.category_id,
            )
            .where(FinanceRecurringStream.id.in_(stream_ids))
        )
    ).all()
    return list(rows)


async def stream_members(db: AsyncSession, stream_id: int) -> list[FinanceTransaction]:
    return list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.recurring_stream_id == stream_id
                )
            )
        ).all()
    )


async def card_payment_stream_ids(
    db: AsyncSession, stream_ids: Sequence[int]
) -> set[int]:
    """Streams paying a REVOLVING account (a credit card), as opposed to
    a loan.

    The distinction only matters to code measuring expenses: a card
    payment settles swipes that are already counted one by one, so
    counting the payment too doubles them - while a loan payment is the
    only record its expense has, and dropping it makes a mortgage cost
    nothing. Walks the join outright (transaction -> transfer -> the
    other leg -> its account) rather than correlating a subquery, which
    cannot narrow by the destination's type.
    """
    if not stream_ids:
        return set()
    to_leg = aliased(FinanceTransaction)
    rows = (
        await db.exec(
            select(FinanceTransaction.recurring_stream_id)
            .join(
                FinanceTransfer,
                FinanceTransfer.from_transaction_id == FinanceTransaction.id,
            )
            .join(to_leg, to_leg.id == FinanceTransfer.to_transaction_id)
            .join(FinanceAccount, FinanceAccount.id == to_leg.account_id)
            .where(
                FinanceTransaction.recurring_stream_id.in_(list(stream_ids)),
                FinanceTransfer.status == "confirmed",
                FinanceAccount.classification == "liability",
                FinanceAccount.account_type == "credit_card",
            )
            .distinct()
        )
    ).all()
    return {int(row) for row in rows if row is not None}
