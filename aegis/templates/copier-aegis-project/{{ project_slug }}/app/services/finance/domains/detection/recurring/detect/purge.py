"""Retiring proposals and streams that no longer describe reality."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.models import (
    FinanceInsight,
    FinanceRecurringStream,
    FinanceTransaction,
)


async def _delete_insights_for(db: AsyncSession, stream_ids: list[int]) -> None:
    """Delete the insights that hang off proposals being purged.

    Same regime rule, one level down: an insight about a proposal is
    derived opinion about derived opinion. A ``missed_recurring`` whose
    stream is gone can never refresh (its dedup_key embeds the dead
    stream id) and its account FK would strand it as debris that blocks
    account deletion - detaching instead of deleting left exactly that.
    Insights on the RECORD are safe by construction: curated streams are
    never purged.
    """
    if not stream_ids:
        return
    rows = await queries.insight_rows_where(
        db, [FinanceInsight.related_stream_id.in_(stream_ids)]
    )
    for row in rows:
        await db.delete(row)


async def _purge_orphaned_proposals(db: AsyncSession, owner_user_id: int) -> int:
    """Hard-delete proposals with no live members.

    The narrow sibling of ``_purge_stale_proposals``, for callers that are
    NOT a full detection pass: "Make recurring" moves one payee's members
    onto a confirmed stream, which empties the descriptor-keyed proposals
    they came from - those are the "folded in" duplicates it reports. A
    full purge here would wrongly delete every other healthy proposal the
    declare never looked at.
    """
    linked = await queries.linked_stream_ids(db)
    stale = await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == owner_user_id,
            FinanceRecurringStream.source == "derived",
            FinanceRecurringStream.is_user_confirmed.is_(False),
            FinanceRecurringStream.provider_stream_id.is_(None),
        ],
    )
    doomed = [row for row in stale if row.id not in linked]
    await _delete_insights_for(db, [row.id for row in doomed])
    for row in doomed:
        await db.delete(row)
    if doomed:
        await db.flush()
    return len(doomed)


async def _purge_stale_proposals(
    db: AsyncSession, owner_user_id: int, touched: set[int]
) -> int:
    """Hard-delete every proposal this pass did not regenerate.

    THE structural rule: a proposal row is never load-bearing. Detection
    owns every derived, unconfirmed row outright and rebuilds them from
    evidence each pass - so anything it did not just produce is stale by
    definition and is REMOVED, not soft-deleted. The old regime
    (soft-delete + watermark + revival gate + release + orphan-prune) let
    a row die only through a four-link chain and revive through three
    doors; broken links made rows immortal (a 2023 Home Depot survived
    every pass, twinned on a duplicate key with a ghost).

    Never touched: the record (``source='user'`` or confirmed) and
    provider-supplied rows. Dismissals (muted/deleted proposals) survive
    exactly as long as their pattern keeps being regenerated - a dismissal
    of something no longer proposed is debris and goes with the rest.
    """
    stale = await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == owner_user_id,
            FinanceRecurringStream.source == "derived",
            FinanceRecurringStream.is_user_confirmed.is_(False),
            FinanceRecurringStream.provider_stream_id.is_(None),
            FinanceRecurringStream.id.not_in(touched) if touched else True,  # noqa: E712
        ],
    )
    if not stale:
        return 0
    stale_ids = [row.id for row in stale]
    await _delete_insights_for(db, stale_ids)
    members = await queries.transaction_rows_where(
        db, [FinanceTransaction.recurring_stream_id.in_(stale_ids)]
    )
    for member in members:
        member.recurring_stream_id = None
        db.add(member)
    for row in stale:
        await db.delete(row)
    await db.flush()
    return len(stale_ids)
