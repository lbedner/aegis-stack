"""Promote recurring streams the user's own categorization marks as bills.

A Quicken export carries the user's category tree on every transaction;
anything filed under "Bills & Utilities" (or "Subscriptions") is a bill
by the user's own hand, which beats any cadence heuristic. Runs after
recurring detection: a derived stream whose member transactions live
under a bills-type category gets ``is_subscription=True``, which walks it
through the missed-payment rule's commitment gate.

Only ``is_subscription`` is set - ``is_user_confirmed`` stays an explicit
action in the Bills & Income tab, so the UI still distinguishes "your
export implied it" from "you clicked Confirm".
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.models import (
    FinanceCategory,
    FinanceRecurringStream,
    FinanceTransaction,
)

# Category-name prefixes (case-insensitive) that mark a member transaction
# as bill-curated. Matched against the category NAME (the first two path
# segments of the original hint), so "Bills & Utilities:Streaming" matches.
BILL_CATEGORY_PREFIXES = ("bills & utilities", "subscriptions")

# At least this share of a stream's categorized members must be bill-curated
# (guards against one recategorized outlier flipping a shopping habit).
_MIN_CURATED_SHARE = 0.5


@dataclass
class _StreamFacts:
    categorized: int = 0
    curated: int = 0


def _owner_clause(column, owner_user_id: int | None):
    return column.is_(None) if owner_user_id is None else column == owner_user_id


async def promote_curated_streams(
    db: AsyncSession, *, owner_user_id: int | None
) -> int:
    """Mark bills-categorized derived streams as subscriptions. Idempotent.

    Returns the number of streams promoted this pass.
    """
    store_owner = 0 if owner_user_id is None else owner_user_id
    streams = (
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
    if not streams:
        return 0

    stream_ids = [s.id for s in streams]
    rows = (
        await db.exec(
            select(FinanceTransaction.recurring_stream_id, FinanceCategory.name)
            .join(
                FinanceCategory,
                FinanceCategory.id == FinanceTransaction.category_id,
            )
            .where(
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.recurring_stream_id.in_(stream_ids),
                FinanceTransaction.category_id.is_not(None),
            )
        )
    ).all()

    facts: dict[int, _StreamFacts] = {}
    for stream_id, category_name in rows:
        entry = facts.setdefault(stream_id, _StreamFacts())
        entry.categorized += 1
        if (category_name or "").lower().startswith(BILL_CATEGORY_PREFIXES):
            entry.curated += 1

    promoted = 0
    for stream in streams:
        entry = facts.get(stream.id)
        if entry is None or entry.curated == 0:
            continue
        if entry.curated / entry.categorized < _MIN_CURATED_SHARE:
            continue
        stream.is_subscription = True
        db.add(stream)
        promoted += 1
    if promoted:
        await db.flush()
        logger.info(
            "Promoted %d bill-curated recurring stream(s) to subscriptions",
            promoted,
        )
    return promoted
