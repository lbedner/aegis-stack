"""Transactions: CRUD, splits, tags, search, cashflow reads.

Read statements live in ``ledger/queries.py``; this module owns writes and
orchestration and delegates every fetch.
"""

from __future__ import annotations

from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    Provider,
)
from app.services.finance.domains.ledger import queries
from app.services.finance.domains.ledger.queries import (  # noqa: F401  (re-export)
    transaction_search_filter,
)
from app.services.finance.models import (
    FinanceTag,
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransactionTag,
)
from app.services.finance.schemas import CashflowMonth, PayeeTotal
from app.services.finance.utils import (
    DEFAULT_CURRENCY,
    utcnow,
)


async def transaction_exists(
    db: AsyncSession,
    *,
    account_id: int,
    source: str,
    external_id: str | None = None,
    import_hash: str | None = None,
) -> bool:
    """Two-lane dedup probe (see ``queries.dedup_match``)."""
    match = await queries.dedup_match(
        db,
        account_id=account_id,
        source=source,
        external_id=external_id,
        import_hash=import_hash,
    )
    return match is not None


async def find_transaction(
    db: AsyncSession,
    *,
    account_id: int,
    source: str,
    external_id: str | None = None,
    import_hash: str | None = None,
) -> FinanceTransaction | None:
    """Return the existing two-lane-dedup match, or None (for importers)."""
    return await queries.dedup_match(
        db,
        account_id=account_id,
        source=source,
        external_id=external_id,
        import_hash=import_hash,
    )


async def create_transaction(
    db: AsyncSession,
    *,
    account_id: int,
    amount: int,
    txn_date: date,
    owner_user_id: int | None = None,
    name: str | None = None,
    source: str = Provider.MANUAL,
    external_id: str | None = None,
    external_id_source: str | None = None,
    import_hash: str | None = None,
    within_day_ordinal: int = 0,
    import_batch_id: int | None = None,
    connection_id: int | None = None,
    raw_amount: int | None = None,
    raw_sign_convention: str | None = None,
    original_description: str | None = None,
    memo: str | None = None,
    check_number: str | None = None,
    currency: str = DEFAULT_CURRENCY,
    category_id: int | None = None,
    category_source: str = "unset",
    is_split: bool = False,
    pending: bool = False,
    pending_provider_id: str | None = None,
) -> FinanceTransaction:
    txn = FinanceTransaction(
        owner_user_id=owner_user_id,
        account_id=account_id,
        connection_id=connection_id,
        amount=amount,
        date_=txn_date,
        name=name,
        source=source,
        external_id=external_id,
        external_id_source=external_id_source,
        import_hash=import_hash,
        within_day_ordinal=within_day_ordinal,
        import_batch_id=import_batch_id,
        raw_amount=raw_amount,
        raw_sign_convention=raw_sign_convention,
        original_description=original_description,
        memo=memo,
        check_number=check_number,
        currency=currency,
        category_id=category_id,
        category_source=category_source,
        is_split=is_split,
        pending=pending,
        pending_provider_id=pending_provider_id,
        status="pending" if pending else "posted",
    )
    db.add(txn)
    await db.flush()
    return txn


async def create_split(
    db: AsyncSession,
    *,
    parent_transaction_id: int,
    amount: int,
    owner_user_id: int | None = None,
    category_id: int | None = None,
    memo: str | None = None,
    sort_order: int = 0,
    currency: str = DEFAULT_CURRENCY,
) -> FinanceTransactionSplit:
    split = FinanceTransactionSplit(
        owner_user_id=owner_user_id,
        parent_transaction_id=parent_transaction_id,
        amount=amount,
        category_id=category_id,
        memo=memo,
        sort_order=sort_order,
        currency=currency,
    )
    db.add(split)
    await db.flush()
    return split


async def get_or_create_tag(
    db: AsyncSession, name: str, *, owner_user_id: int | None = None
) -> FinanceTag:
    """Fetch (or create) a tag by normalized name.

    Tags are always user-owned; standalone (NULL-owner) installs use the
    ``0`` sentinel, like insights and recurring streams.
    """
    from app.services.finance.utils import normalize_payee

    store_owner = 0 if owner_user_id is None else owner_user_id
    normalized = normalize_payee(name)
    existing = await queries.tag_by_normalized_name(
        db, store_owner=store_owner, normalized=normalized
    )
    if existing is not None:
        return existing
    tag = FinanceTag(
        owner_user_id=store_owner, name=name.strip(), normalized_name=normalized
    )
    db.add(tag)
    await db.flush()
    return tag


async def list_tags(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[tuple[FinanceTag, int]]:
    """Every live tag with how many transactions wear it, name order."""
    store_owner = 0 if owner_user_id is None else owner_user_id
    return await queries.tags_with_counts(db, store_owner=store_owner)


async def tag_transactions(
    db: AsyncSession,
    transaction_ids: list[int],
    name: str,
    *,
    owner_user_id: int | None = None,
) -> FinanceTag:
    """Attach a tag (created on first use) to every given transaction.

    Idempotent: rows already wearing it are left alone, so re-flagging
    a mixed selection never trips the composite PK."""
    tag = await get_or_create_tag(db, name, owner_user_id=owner_user_id)
    already = await queries.tagged_transaction_ids(
        db, tag_id=tag.id, transaction_ids=transaction_ids
    )
    for txn_id in transaction_ids:
        if txn_id not in already:
            db.add(FinanceTransactionTag(transaction_id=txn_id, tag_id=tag.id))
    await db.flush()
    return tag


async def untag_transactions(
    db: AsyncSession,
    transaction_ids: list[int],
    tag_id: int,
    *,
    owner_user_id: int | None = None,
) -> int:
    """Detach one tag from the given transactions; the tag itself and
    its other attachments stay. Returns how many rows were removed."""
    links = await queries.tag_links(db, tag_id=tag_id, transaction_ids=transaction_ids)
    for link in links:
        await db.delete(link)
    await db.flush()
    return len(links)


async def soft_delete_transactions(
    db: AsyncSession, transaction_ids: list[int], *, owner_user_id: int | None = None
) -> int:
    """Soft-delete transactions (``deleted_at``), returning how many.

    Every read path already filters ``deleted_at``, so the rows leave
    the register, budgets, and projections with no recompute step.
    Linked-row rules: a transfer pair's SURVIVING leg is unpaired and
    comes back into view (the money movement on its account still
    happened); a split parent takes its split lines with it.
    """
    rows = await queries.live_transactions_by_ids(
        db, transaction_ids, owner_user_id=owner_user_id
    )
    if not rows:
        return 0
    now = utcnow()
    deleting = {txn.id for txn in rows}
    surviving_pair_ids = [
        txn.transfer_pair_transaction_id
        for txn in rows
        if txn.transfer_pair_transaction_id is not None
        and txn.transfer_pair_transaction_id not in deleting
    ]
    survivors = await queries.transactions_by_ids(db, surviving_pair_ids)
    splits_by_parent = await queries.splits_for_parents(
        db, [txn.id for txn in rows if txn.is_split]
    )
    for txn in rows:
        txn.deleted_at = now
        txn.updated_at = now
        db.add(txn)
        pair_id = txn.transfer_pair_transaction_id
        survivor = survivors.get(pair_id) if pair_id is not None else None
        if survivor is not None:
            survivor.is_transfer = False
            survivor.transfer_pair_transaction_id = None
            survivor.transfer_group_id = None
            survivor.updated_at = now
            db.add(survivor)
        for split in splits_by_parent.get(txn.id, []):
            await db.delete(split)
    await db.flush()
    return len(rows)


async def transaction_tags(
    db: AsyncSession, transaction_ids: list[int] | set[int]
) -> dict[int, list[FinanceTag]]:
    """Tags per transaction, batched for a register page."""
    return await queries.tags_by_transaction(db, transaction_ids)


async def uncategorized_transactions(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    limit: int | None = 7,
    query: str | None = None,
    from_date: date | None = None,
    account_ids: list[int] | None = None,
) -> tuple[list[FinanceTransaction], int]:
    """Transactions nothing has classified, newest first, plus a count.

    Uncategorized means EITHER no category or a source app's own
    catch-all bucket (see ``UNCATEGORIZED_CATEGORY_NAMES``). Checking
    for NULL alone reports a clean ledger on an import that carried a
    thousand "Uncategorized" rows straight through.

    ``limit=None`` returns every match, unbounded - used internally by
    the auto-categorize sweep, which needs the full backlog rather than
    a preview page. The public endpoint keeps its own bound.

    ``query``/``from_date``/``account_ids`` are the same filters the
    register list uses (an explicit empty ``account_ids`` means "nothing
    selected" and short-circuits to zero results).
    """
    return await queries.uncategorized_page(
        db,
        owner_user_id=owner_user_id,
        limit=limit,
        query=query,
        from_date=from_date,
        account_ids=account_ids,
    )


async def top_payees(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    days: int = 90,
    limit: int = 8,
) -> list[PayeeTotal]:
    """Who took the most money over the window, biggest first.

    Outflows only, transfers excluded - a card payment is money moved
    between your own accounts, and it would otherwise top the list
    forever. Grouped by merchant when the source names one, else by
    the raw payee: a bank's description varies per charge, and the
    merchant field is the one the provider already normalized.
    """
    rows = await queries.top_payees_over_window(
        db, owner_user_id=owner_user_id, days=days, limit=limit
    )
    return [
        PayeeTotal(payee=payee, amount=amount, transaction_count=count)
        for payee, amount, count in rows
    ]


async def monthly_cashflow(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    months: int = 6,
    today: date | None = None,
    account_ids: list[int] | None = None,
) -> list[CashflowMonth]:
    """Income and spend per calendar month, oldest first.

    Transfers and report-excluded rows are out: a card payment is money
    moved, and counting it as both income and spend would double the
    bars. Months with no activity are still returned at zero so the
    chart keeps an even time axis instead of skipping a quiet month.
    ``account_ids`` narrows the bars to those accounts.

    Bucketing runs in Python rather than SQL date-truncation, which is
    dialect-specific - and at a few thousand rows the loop costs less
    than a millisecond.
    """
    today = today or date.today()
    span = max(1, months)
    first_year, first_month = today.year, today.month - (span - 1)
    while first_month <= 0:
        first_month += 12
        first_year -= 1
    start = date(first_year, first_month, 1)

    rows = await queries.dated_amounts_in_window(
        db,
        owner_user_id=owner_user_id,
        start=start,
        end=today,
        account_ids=account_ids,
    )

    buckets: dict[str, dict[str, int]] = {}
    year, month = first_year, first_month
    for _ in range(span):
        buckets[f"{year:04d}-{month:02d}"] = {"income": 0, "expense": 0}
        month += 1
        if month > 12:
            month = 1
            year += 1
    for txn_date, amount in rows:
        bucket = buckets.get(f"{txn_date.year:04d}-{txn_date.month:02d}")
        if bucket is None:
            continue
        if amount >= 0:
            bucket["income"] += amount
        else:
            bucket["expense"] += -amount  # positive magnitude for the bar
    return [
        CashflowMonth(
            month=key,
            income=value["income"],
            expense=value["expense"],
            net=value["income"] - value["expense"],
        )
        for key, value in buckets.items()
    ]


async def get_transaction(
    db: AsyncSession, transaction_id: int, *, owner_user_id: int | None = None
) -> FinanceTransaction | None:
    return await queries.transaction_by_id(
        db, transaction_id, owner_user_id=owner_user_id
    )


async def transactions_by_ids(
    db: AsyncSession, ids: list[int]
) -> dict[int, FinanceTransaction]:
    """Fetch transactions by id in one query, keyed by id (for enrichment)."""
    return await queries.transactions_by_ids(db, ids)


async def list_transactions(
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
    """The register: not soft-deleted, never the losing side of a dedup,
    accounts still live, paired transfer legs hidden unless asked for."""
    return await queries.transactions_page(
        db,
        owner_user_id=owner_user_id,
        account_id=account_id,
        account_ids=account_ids,
        from_date=from_date,
        to_date=to_date,
        category_id=category_id,
        merchant_id=merchant_id,
        without_merchant=without_merchant,
        tag_id=tag_id,
        query=query,
        include_transfers=include_transfers,
        page=page,
        page_size=page_size,
    )
