"""Reads for the register: transactions, their splits, their tags.

The paging and search reads are the ones that grow: they carry the
filter fragments, the dedup lookup, and the payee/amount roll-ups the
transaction surfaces are built from.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger.queries.filters import (
    live_account_ids,
    transaction_search_filter,
    uncategorized_catchall_ids,
)
from app.services.finance.models import (
    FinanceTag,
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransactionTag,
)


async def splits_for_parents(
    db: AsyncSession, parent_ids: Iterable[int]
) -> dict[int, list[FinanceTransactionSplit]]:
    """All split rows for the given parent transactions, one query,
    grouped by parent id."""
    wanted = set(parent_ids)
    if not wanted:
        return {}
    rows = (
        await db.exec(
            select(FinanceTransactionSplit).where(
                FinanceTransactionSplit.parent_transaction_id.in_(wanted)
            )
        )
    ).all()
    grouped: dict[int, list[FinanceTransactionSplit]] = defaultdict(list)
    for split in rows:
        grouped[split.parent_transaction_id].append(split)
    return dict(grouped)


async def dedup_match(
    db: AsyncSession,
    *,
    account_id: int,
    source: str,
    external_id: str | None = None,
    import_hash: str | None = None,
) -> FinanceTransaction | None:
    """The two-lane dedup match, or None. LANE 1 keys on
    ``(account_id, source, external_id)``; LANE 2 on
    ``(account_id, import_hash)``. Soft-deleted rows release the key."""
    query = select(FinanceTransaction).where(
        FinanceTransaction.account_id == account_id,
        FinanceTransaction.deleted_at.is_(None),
    )
    if external_id is not None:
        query = query.where(
            FinanceTransaction.source == source,
            FinanceTransaction.external_id == external_id,
        )
    elif import_hash is not None:
        query = query.where(FinanceTransaction.import_hash == import_hash)
    else:
        return None
    return (await db.exec(query)).first()


async def transaction_by_id(
    db: AsyncSession, transaction_id: int, *, owner_user_id: int | None = None
) -> FinanceTransaction | None:
    query = select(FinanceTransaction).where(
        FinanceTransaction.id == transaction_id,
        FinanceTransaction.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def transactions_by_ids(
    db: AsyncSession, ids: list[int]
) -> dict[int, FinanceTransaction]:
    if not ids:
        return {}
    rows = (
        await db.exec(select(FinanceTransaction).where(FinanceTransaction.id.in_(ids)))
    ).all()
    return {t.id: t for t in rows}


async def live_transactions_by_ids(
    db: AsyncSession, ids: list[int], *, owner_user_id: int | None = None
) -> list[FinanceTransaction]:
    """Not-deleted rows among ``ids``, owner-scoped when given."""
    query = select(FinanceTransaction).where(
        FinanceTransaction.id.in_(ids),
        FinanceTransaction.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())


async def transactions_page(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    account_id: int | None = None,
    account_ids: list[int] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    category_id: int | None = None,
    merchant_id: int | None = None,
    without_merchant: bool = False,
    tag_id: int | None = None,
    query: str | None = None,
    include_transfers: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FinanceTransaction], int]:
    """The register page + total count (two statements)."""
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.account_id.in_(live_account_ids()),
    ]
    if not include_transfers:
        filters.append(FinanceTransaction.is_transfer.is_(False))
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    if account_id is not None:
        filters.append(FinanceTransaction.account_id == account_id)
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    if from_date is not None:
        filters.append(FinanceTransaction.date_ >= from_date)
    if to_date is not None:
        filters.append(FinanceTransaction.date_ <= to_date)
    if category_id is not None:
        filters.append(FinanceTransaction.category_id == category_id)
    if merchant_id is not None:
        filters.append(FinanceTransaction.merchant_id == merchant_id)
    if without_merchant:
        filters.append(FinanceTransaction.merchant_id.is_(None))
    if tag_id is not None:
        filters.append(
            FinanceTransaction.id.in_(
                select(FinanceTransactionTag.transaction_id).where(
                    FinanceTransactionTag.tag_id == tag_id
                )
            )
        )
    if query:
        filters.append(transaction_search_filter(query))
    count_query = select(func.count()).select_from(FinanceTransaction).where(*filters)
    total = (await db.exec(count_query)).one()
    query_obj = (
        select(FinanceTransaction)
        .where(*filters)
        .order_by(FinanceTransaction.date_.desc(), FinanceTransaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.exec(query_obj)).all()), total


async def uncategorized_page(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    limit: int | None = 7,
    query: str | None = None,
    from_date: date | None = None,
    account_ids: list[int] | None = None,
) -> tuple[list[FinanceTransaction], int]:
    """Rows nothing has classified (NULL category or a source app's own
    catch-all bucket), newest first, plus a count (two statements)."""
    if account_ids is not None and not account_ids:
        return [], 0
    catchall = uncategorized_catchall_ids()
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.account_id.in_(live_account_ids()),
        or_(
            FinanceTransaction.category_id.is_(None),
            FinanceTransaction.category_id.in_(catchall),
        ),
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    if query:
        filters.append(transaction_search_filter(query))
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    if from_date is not None:
        filters.append(FinanceTransaction.date_ >= from_date)

    total = (
        await db.exec(
            select(func.count()).select_from(FinanceTransaction).where(*filters)
        )
    ).one()
    select_query = (
        select(FinanceTransaction)
        .where(*filters)
        .order_by(FinanceTransaction.date_.desc())
    )
    if limit is not None:
        select_query = select_query.limit(limit)
    rows = (await db.exec(select_query)).all()
    return list(rows), int(total or 0)


async def top_payees_over_window(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int = 90,
    limit: int = 8,
) -> list[tuple[str, int, int]]:
    """(payee, outflow total as positive cents, transaction count) grouped
    by merchant (falling back to raw payee), biggest first, transfers
    excluded."""
    payee = func.coalesce(FinanceTransaction.merchant_name, FinanceTransaction.name)
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.account_id.in_(live_account_ids()),
        FinanceTransaction.amount < 0,
        FinanceTransaction.date_ >= date.today() - timedelta(days=days),
        payee.is_not(None),
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    rows = (
        await db.exec(
            select(
                payee,
                func.sum(FinanceTransaction.amount),
                func.count(FinanceTransaction.id),
            )
            .where(*filters)
            .group_by(payee)
            .order_by(func.sum(FinanceTransaction.amount))
            .limit(limit)
        )
    ).all()
    return [(name, -int(total or 0), int(count or 0)) for name, total, count in rows]


async def dated_amounts_in_window(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    start: date,
    end: date,
    account_ids: list[int] | None = None,
) -> list[tuple[date, int]]:
    """(date, amount) pairs for cashflow bucketing: live accounts,
    non-duplicate, report-included, transfers excluded."""
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.account_id.in_(live_account_ids()),
        FinanceTransaction.date_ >= start,
        FinanceTransaction.date_ <= end,
    ]
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    rows = (
        await db.exec(
            select(FinanceTransaction.date_, FinanceTransaction.amount).where(*filters)
        )
    ).all()
    return [(txn_date, amount) for txn_date, amount in rows]


async def tag_by_normalized_name(
    db: AsyncSession, *, store_owner: int, normalized: str
) -> FinanceTag | None:
    return (
        await db.exec(
            select(FinanceTag).where(
                FinanceTag.owner_user_id == store_owner,
                FinanceTag.normalized_name == normalized,
                FinanceTag.deleted_at.is_(None),
            )
        )
    ).first()


async def tags_with_counts(
    db: AsyncSession, *, store_owner: int
) -> list[tuple[FinanceTag, int]]:
    """Every live tag with its attachment count, one outer-joined query."""
    rows = (
        await db.exec(
            select(FinanceTag, func.count(FinanceTransactionTag.tag_id))
            .join(
                FinanceTransactionTag,
                FinanceTransactionTag.tag_id == FinanceTag.id,
                isouter=True,
            )
            .where(
                FinanceTag.owner_user_id == store_owner,
                FinanceTag.deleted_at.is_(None),
            )
            .group_by(FinanceTag.id)
            .order_by(FinanceTag.name)
        )
    ).all()
    return [(tag, int(count)) for tag, count in rows]


async def tagged_transaction_ids(
    db: AsyncSession, *, tag_id: int, transaction_ids: list[int]
) -> set[int]:
    """Which of ``transaction_ids`` already wear ``tag_id``."""
    rows = (
        await db.exec(
            select(FinanceTransactionTag.transaction_id).where(
                FinanceTransactionTag.tag_id == tag_id,
                FinanceTransactionTag.transaction_id.in_(transaction_ids),
            )
        )
    ).all()
    return set(rows)


async def tag_links(
    db: AsyncSession, *, tag_id: int, transaction_ids: list[int]
) -> list[FinanceTransactionTag]:
    return list(
        (
            await db.exec(
                select(FinanceTransactionTag).where(
                    FinanceTransactionTag.tag_id == tag_id,
                    FinanceTransactionTag.transaction_id.in_(transaction_ids),
                )
            )
        ).all()
    )


async def tags_by_transaction(
    db: AsyncSession, transaction_ids: list[int] | set[int]
) -> dict[int, list[FinanceTag]]:
    """Tags per transaction, batched for a register page - every id gets
    a key (empty list when untagged), one query for the lot."""
    by_txn: dict[int, list[FinanceTag]] = {txn_id: [] for txn_id in transaction_ids}
    if not by_txn:
        return by_txn
    rows = (
        await db.exec(
            select(FinanceTransactionTag.transaction_id, FinanceTag)
            .join(FinanceTag, FinanceTag.id == FinanceTransactionTag.tag_id)
            .where(
                FinanceTransactionTag.transaction_id.in_(list(by_txn)),
                FinanceTag.deleted_at.is_(None),
            )
            .order_by(FinanceTag.name)
        )
    ).all()
    for txn_id, tag in rows:
        by_txn[txn_id].append(tag)
    return by_txn


async def outflow_by_account_in_window(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    start: date,
    end: date,
    exclude_stream_ids: Sequence[int] | None = None,
) -> list[tuple[int, int]]:
    """(account_id, money out as positive cents) over the window.

    What actually left, rather than what was declared: the measured
    denominator a fund sized in months of expenses needs. Transfers are
    excluded by the same filter every other spending read uses, which is
    also what keeps a card payment from counting on top of the swipes it
    settles - but ``is_transfer`` is set by matching, so a payment nobody
    matched still looks like spending. ``exclude_stream_ids`` drops whole
    streams for that case: the stream knows it is a card payment even
    when one of its transactions was never paired.
    """
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.account_id.in_(live_account_ids()),
        FinanceTransaction.amount < 0,
        FinanceTransaction.date_ >= start,
        FinanceTransaction.date_ <= end,
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    if exclude_stream_ids:
        filters.append(
            or_(
                FinanceTransaction.recurring_stream_id.is_(None),
                FinanceTransaction.recurring_stream_id.notin_(
                    list(exclude_stream_ids)
                ),
            )
        )
    rows = (
        await db.exec(
            select(
                FinanceTransaction.account_id,
                func.sum(FinanceTransaction.amount),
            )
            .where(*filters)
            .group_by(FinanceTransaction.account_id)
        )
    ).all()
    return [(int(account_id), -int(total or 0)) for account_id, total in rows]
