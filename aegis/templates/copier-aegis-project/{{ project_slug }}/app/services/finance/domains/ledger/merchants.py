"""Merchants (payees): CRUD, merge, payee groups."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import categories, queries, transactions
from app.services.finance.models import (
    FinanceMerchant,
    FinanceTransaction,
)
from app.services.finance.schemas import MerchantCategorySummary, PayeeGroup
from app.services.finance.utils import (
    transaction_payee_key,
    utcnow,
)

# Sentinel for "caller did not mention this field", so that None can
# keep its own meaning of "clear it". Without the distinction a patch
# that only sets a website would blank the default category with it.
_UNSET: Any = object()


async def list_merchants(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceMerchant]:
    """The payees available to this owner - their own plus any global
    (NULL-owner) seeds, name-sorted for the picker."""
    return await queries.merchants_for_owner(db, owner_user_id=owner_user_id)


async def create_merchant(
    db: AsyncSession,
    name: str,
    *,
    owner_user_id: int | None = None,
    website_url: str | None = None,
) -> FinanceMerchant:
    """Create a payee, or return the existing one with the same
    normalized name - the unique index (uq_finance_merchant_user /
    _global) makes a duplicate an error rather than a second row, and a
    picker's "+ Create" is exactly where a user retypes a name they
    already have."""
    from app.services.finance.utils import normalize_payee

    display = (name or "").strip()
    normalized = normalize_payee(display)
    if not normalized:
        raise ValueError("A payee needs a name.")
    existing = await queries.merchant_by_normalized(
        db, normalized=normalized, owner_user_id=owner_user_id
    )
    if existing is not None:
        # A domain supplied now fills a gap, but never silently
        # replaces one the user already set.
        if website_url and not existing.website_url:
            existing.website_url = website_url
            db.add(existing)
            await db.flush()
        return existing
    merchant = FinanceMerchant(
        owner_user_id=owner_user_id,
        name=display,
        normalized_name=normalized,
        source="user",
        website_url=website_url or None,
    )
    db.add(merchant)
    await db.flush()
    return merchant


async def set_merchant_website(
    db: AsyncSession, merchant_id: int, website_url: str | None
) -> FinanceMerchant | None:
    """Point a payee at its real address. The icon resolver prefers
    this over guessing ``<name>.com`` - see merchant_icon.py."""
    merchant = await queries.merchant_by_id(db, merchant_id)
    if merchant is None:
        return None
    merchant.website_url = (website_url or "").strip() or None
    merchant.updated_at = utcnow()
    db.add(merchant)
    await db.flush()
    return merchant


async def update_merchant(
    db: AsyncSession,
    merchant_id: int,
    *,
    name: str | None = None,
    website_url: str | None | Any = _UNSET,
    default_category_id: int | None | Any = _UNSET,
    owner_user_id: int | None = None,
) -> FinanceMerchant | None:
    """Edit a payee in place, without touching its transactions.

    Correcting a logo is not a filing decision. The only path that
    could set a website ran through ``/payee-groups/assign``, which
    re-files every transaction in the group it was opened on - so
    fixing an address meant moving rows, and a payee whose backlog was
    already empty could not be edited at all.
    """
    merchant = await queries.merchant_by_id(db, merchant_id)
    if merchant is None:
        return None
    if owner_user_id is not None and merchant.owner_user_id not in (
        owner_user_id,
        None,
    ):
        return None
    if name is not None and name.strip():
        from app.services.finance.utils import normalize_payee

        merchant.name = name.strip()
        # The dedup key travels WITH the name. Leaving it stale means
        # the payee is no longer findable under the name it now shows,
        # so the picker's "+ Create" mints a duplicate beside it - the
        # exact mess merge_merchants exists to clean up. (A pure
        # punctuation fix, "Mcdonald S" -> "McDonald's", normalizes to
        # the same key anyway; a real rename does not.)
        merchant.normalized_name = normalize_payee(merchant.name)
    if website_url is not _UNSET:
        merchant.website_url = (website_url or "").strip() or None
    if default_category_id is not _UNSET:
        merchant.default_category_id = default_category_id
    merchant.updated_at = utcnow()
    db.add(merchant)
    await db.flush()
    return merchant


async def merge_merchants(
    db: AsyncSession,
    source_ids: list[int],
    target_id: int,
    *,
    owner_user_id: int | None = None,
) -> int:
    """Fold payees into one, returning how many transactions moved.

    Two payees for one merchant is the normal end state of naming
    things by hand ("Shop Rite" and "ShopRite", 248 and 219
    transactions here). Renaming one to match the other does NOT join
    them - they are still two rows with two ids - so this is the
    deliberate action that does.

    Everything pointing at a loser is repointed rather than deleted:
    its transactions, and its recurring streams (a bill still pointing
    at a payee that no longer exists loses its name and its icon).
    Curation transfers only into a GAP - the survivor's own website
    and default category always win, because merging is not an edit of
    the payee you chose to keep.
    """
    target = await queries.merchant_by_id(db, target_id)
    if target is None or target.deleted_at is not None:
        return 0
    losers = [
        m
        for m in await queries.live_merchants_by_ids(db, [i for i in source_ids if i])
        # Self-merge would soft-delete the survivor and strand every
        # transaction it had just moved onto a deleted row.
        if m.id != target_id
    ]
    if not losers:
        return 0
    loser_ids = [m.id for m in losers]

    moved = 0
    rows = await queries.live_transactions_by_merchants(db, loser_ids)
    for txn in rows:
        txn.merchant_id = target_id
        db.add(txn)
        moved += 1

    streams = await queries.live_streams_by_merchants(db, loser_ids)
    for stream in streams:
        stream.merchant_id = target_id
        db.add(stream)

    now = utcnow()
    for loser in losers:
        if not target.website_url and loser.website_url:
            target.website_url = loser.website_url
        if target.default_category_id is None:
            target.default_category_id = loser.default_category_id
        loser.deleted_at = now
        db.add(loser)
    target.updated_at = now
    db.add(target)
    await db.flush()
    return moved


async def merchant_usage(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    account_ids: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """``{merchant id: {count, total_amount, last_date}}``.

    Which payee is worth correcting is a function of how much money
    runs through it, so the directory shows weight rather than a bare
    list of names. Grouped in one query; a payee with no transactions
    is simply absent, and the caller defaults it.
    """
    rows = await queries.merchant_usage_rows(
        db, owner_user_id=owner_user_id, account_ids=account_ids
    )
    return {
        merchant_id: {
            "count": count or 0,
            "total_amount": int(total or 0),
            "last_date": last_date,
        }
        for merchant_id, count, total, last_date in rows
        if merchant_id is not None
    }


async def merchant_websites(
    db: AsyncSession, ids: set[int] | list[int]
) -> dict[int, str]:
    """Stored websites by merchant id, for the icon resolver."""
    rows = await queries.merchants_by_ids(db, ids)
    return {
        merchant_id: row.website_url
        for merchant_id, row in rows.items()
        if row.website_url
    }


async def merchant_names(db: AsyncSession, ids: set[int] | list[int]) -> dict[int, str]:
    """Payee names by id, in one query - same shape (and same reason) as
    ``category_names``."""
    rows = await queries.merchants_by_ids(db, ids)
    return {merchant_id: row.name for merchant_id, row in rows.items()}


async def assign_merchant(
    db: AsyncSession,
    transaction_ids: Sequence[int],
    merchant_id: int | None,
    *,
    owner_user_id: int | None = None,
    category_id: int | None = None,
) -> int:
    """Point transactions at a payee (``None`` clears it). Returns how
    many rows were actually updated - a caller's id list is user input
    (a checkbox selection), so ids that aren't found/owned are skipped
    rather than failing the whole batch.

    ``category_id`` also files those rows under that category and
    remembers it as the payee's default, so the SAME decision covers
    the history in front of you and everything that arrives later.
    Confirmed worth having on real data: 7 of 79 GreenSky loan
    payments had been auto-filed as "Food & Dining:Restaurants".
    """
    ids = [i for i in set(transaction_ids) if i is not None]
    if not ids:
        return 0
    rows = await queries.live_transactions_by_ids(db, ids, owner_user_id=owner_user_id)
    for txn in rows:
        txn.merchant_id = merchant_id
        if category_id is not None:
            txn.category_id = category_id
            txn.category_source = "user"
            txn.is_user_categorized = True
            txn.is_reviewed = True
        txn.updated_at = utcnow()
        db.add(txn)
    if category_id is not None and merchant_id is not None:
        merchant = await queries.merchant_by_id(db, merchant_id)
        if merchant is not None:
            merchant.default_category_id = category_id
            merchant.updated_at = utcnow()
            db.add(merchant)
    if rows:
        await db.flush()
    return len(rows)


async def merchant_category_summary(
    db: AsyncSession, merchant_id: int, *, owner_user_id: int | None = None
) -> MerchantCategorySummary:
    """How this payee's transactions are currently categorized - what
    the "also set category" offer pre-fills from, and how it can say
    "72 of 79 already use this" instead of asking blind."""
    merchant = await queries.merchant_by_id(db, merchant_id)
    rows = await queries.live_transactions_for_merchant(
        db, merchant_id, owner_user_id=owner_user_id
    )
    tally = Counter(t.category_id for t in rows if t.category_id is not None)
    dominant_id, dominant_count = tally.most_common(1)[0] if tally else (None, 0)
    names = await categories.category_names(db, {dominant_id} if dominant_id else set())
    return MerchantCategorySummary(
        merchant_id=merchant_id,
        default_category_id=(
            merchant.default_category_id if merchant is not None else None
        ),
        dominant_category_id=dominant_id,
        dominant_category_name=names.get(dominant_id),
        dominant_count=dominant_count,
        total=len(rows),
        distinct_categories=len(tally),
    )


async def payee_groups(
    db: AsyncSession, *, owner_user_id: int | None = None, limit: int = 200
) -> tuple[list[PayeeGroup], int, int]:
    """Payee-less transactions collapsed into named-able groups, biggest
    first, as ``(page, total_groups, total_transactions)``.

    The two totals describe the WHOLE backlog, not the returned page -
    the caller needs them to say honestly how much is left behind the
    limit.

    The backlog is not a list to work through row by row: EVERY
    transaction starts without a payee, so a real import opens at tens
    of thousands (17,675 here) - but they collapse into ~2,473 distinct
    ``transaction_payee_key`` groups, and the largest 15 alone cover
    5,805 rows. Naming a group is one decision that settles all of it.

    The key IS the grouping - nothing is guessed. ``suggested_name``
    is only a suggestion (see ``suggested_payee_name``: the sample's
    own spelling where it reads like a name, else the title-cased
    key); the caller confirms or edits it, because a group can be a
    merchant the key mangles or not a merchant at all
    ("NON CHASE ATM WITHDRAW").
    """
    rows = await queries.payeeless_transactions(db, owner_user_id=owner_user_id)

    groups: dict[str, dict[str, Any]] = {}
    for txn in rows:
        key = transaction_payee_key(
            txn.merchant_name, txn.original_description, txn.name
        )
        if not key:
            continue
        entry = groups.setdefault(
            key,
            {
                "key": key,
                "count": 0,
                "sample": txn.name or txn.original_description or "",
                "total_amount": 0,
            },
        )
        entry["count"] += 1
        entry["total_amount"] += txn.amount
    from app.services.finance.utils import suggested_payee_name

    ordered = sorted(groups.values(), key=lambda g: -g["count"])[:limit]
    page = [
        PayeeGroup(
            key=entry["key"],
            # From the SAMPLE where it reads like a name, not the key -
            # the key has already had its punctuation and case stripped
            # (see suggested_payee_name).
            suggested_name=suggested_payee_name(entry["key"], entry["sample"]),
            count=entry["count"],
            sample=entry["sample"],
            total_amount=entry["total_amount"],
        )
        for entry in ordered
    ]
    # The TRUE totals travel alongside the truncated page. Reporting
    # len(ordered) as the total is a lie that reads as good news -
    # "300 groups" when there are 2,436 - and it silently caps at
    # whatever limit the caller happened to pass.
    return page, len(groups), sum(g["count"] for g in groups.values())


async def assign_payee_group(
    db: AsyncSession,
    keys: Sequence[str],
    merchant_id: int,
    *,
    owner_user_id: int | None = None,
    category_id: int | None = None,
) -> int:
    """Give every payee-less transaction in ``keys`` this payee.

    Resolved server-side from the keys rather than an id list: a single
    group runs to a thousand transactions, and shipping those ids to
    the browser and back just to name one merchant is pure weight.

    Takes the whole set of keys in ONE call because the alternative -
    the caller looping per group - re-reads every payee-less row each
    time. That scan is the expensive half (10,707 rows here), so
    naming a 48-group brand cost 48 full scans instead of one.
    """
    wanted = {k for k in keys if k}
    if not wanted:
        return 0
    rows = await queries.payeeless_transactions(db, owner_user_id=owner_user_id)
    ids = [
        t.id
        for t in rows
        if transaction_payee_key(t.merchant_name, t.original_description, t.name)
        in wanted
    ]
    if not ids:
        return 0
    return await assign_merchant(
        db, ids, merchant_id, owner_user_id=owner_user_id, category_id=category_id
    )


async def similar_unassigned(
    db: AsyncSession, transaction_id: int, *, owner_user_id: int | None = None
) -> list[FinanceTransaction]:
    """Other payee-less transactions whose descriptor looks like this
    one's, for the picker's "also apply to N similar" offer.

    Uses ``transaction_payee_key``'s loose 4-token prefix, which is a
    HEURISTIC - deliberately so, and deliberately only here: the user
    confirms the list before anything is written, so a false match costs
    a glance rather than a silently mis-grouped bill. Detection itself
    never relies on it; it keys off the assigned ``merchant_id``.
    """
    txn = await transactions.get_transaction(
        db, transaction_id, owner_user_id=owner_user_id
    )
    if txn is None:
        return []
    key = transaction_payee_key(txn.merchant_name, txn.original_description, txn.name)
    if not key:
        return []
    rows = await queries.payeeless_transactions(db, owner_user_id=owner_user_id)
    return [
        row
        for row in rows
        if row.id != transaction_id
        and transaction_payee_key(row.merchant_name, row.original_description, row.name)
        == key
    ]
