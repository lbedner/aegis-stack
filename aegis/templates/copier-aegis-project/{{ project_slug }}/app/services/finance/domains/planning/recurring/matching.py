"""Which transaction paid this bill.

The heuristics that build the reconcile shortlist. Deliberately a
ranking and not an auto-match: this feeds a picker where the user
decides, so the job is to put the right row near the top rather than to
be certain.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import CADENCES
from app.services.finance.domains.planning.recurring import queries
from app.services.finance.domains.planning.recurring.streams import get_recurring
from app.services.finance.models import (
    FinanceRecurringStream,
    FinanceTransaction,
)


async def recurring_match_candidates(
    db: AsyncSession,
    stream_id: int,
    *,
    owner_user_id: int | None = None,
    limit: int = 20,
) -> list[FinanceTransaction]:
    """The shortlist a human would scan when reconciling a bill:
    unclaimed rows in the bill's direction whose amount lands in the
    neighborhood of what the bill costs, newest first.

    The amount band is deliberately loose (half to double the
    expected figure, or everything when the bill has no figure) -
    this feeds a picker where the user decides, not an auto-match,
    and a too-tight band hides exactly the changed-amount payment
    that broke the automatic match in the first place.
    """
    stream = await get_recurring(db, stream_id, owner_user_id)
    if stream is None:
        return []
    amount_clause = (
        FinanceTransaction.amount > 0
        if stream.direction == "inflow"
        else FinanceTransaction.amount < 0
    )
    # "Unclaimed" includes rows held by a DELETED stream: a dismissed
    # detector guess keeps claiming its pattern (that is how a
    # dismissal stays silent), but a human reconciling a confirmed
    # bill outranks a dead proposal - hiding those rows made the
    # Fidelity payment invisible here twice (confirmed live).
    live_claim = select(FinanceRecurringStream.id).where(
        FinanceRecurringStream.id == FinanceTransaction.recurring_stream_id,
        FinanceRecurringStream.deleted_at.is_(None),
    )
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        or_(
            FinanceTransaction.recurring_stream_id.is_(None),
            ~live_claim.exists(),
        ),
        amount_clause,
        queries.owner_clause_txn(FinanceTransaction.owner_user_id, owner_user_id),
    ]
    expected = stream.expected_amount or stream.average_amount
    if expected:
        filters.append(
            func.abs(FinanceTransaction.amount).between(
                int(expected * 0.5), int(expected * 2)
            )
        )
    # This dialog answers "which payment was THIS due date" - last
    # year's identical charges are not answers to that question, and
    # six of them crowded out everything else (confirmed live). The
    # window scales with the cadence so an annual bill still sees a
    # sensible neighborhood.
    due = stream.next_expected_date
    if due is not None:
        cadence = CADENCES.get(stream.frequency)
        reach = max(45, int(cadence.detect_days * 1.5)) if cadence else 45
        window = timedelta(days=reach)
        filters.append(FinanceTransaction.date_.between(due - window, due + window))
    rows = await queries.candidate_rows(db, filters, limit=limit * 5)

    # Likeliest first, not newest first: a small bill's band admits
    # every coffee in the register, and the real payment (exact
    # amount, dated near the due date) must not drown under a page
    # of newer lookalikes (confirmed live).
    today = date.today()
    # Name affinity outranks the figures: a candidate carrying the
    # bill's own payee (or its name in the descriptor) is the answer
    # even when a stranger's amount lands a dollar nearer - ranked
    # purely on figures, last year's Etsy outranked rows literally
    # named after the bill (confirmed live).
    stream_name = (stream.name or "").casefold()

    def named_alike(txn: FinanceTransaction) -> bool:
        if stream.merchant_id is not None and txn.merchant_id == stream.merchant_id:
            return True
        if not stream_name:
            return False
        haystack = f"{txn.name or ''} {txn.original_description or ''}".casefold()
        return stream_name in haystack

    def likelihood(txn: FinanceTransaction) -> tuple[int, int, int]:
        amount_distance = abs(abs(txn.amount) - expected) if expected else 0
        date_distance = abs((txn.date_ - (due or today)).days)
        return (0 if named_alike(txn) else 1, amount_distance, date_distance)

    # When rows carry the bill's own name, the strangers are noise
    # and stay out entirely ("it's so obviously Fidelity and not
    # AT&T"); the amount shortlist earns its keep only when the
    # payment arrived under an unrecognizable descriptor.
    named = [t for t in rows if named_alike(t)]
    pool = named if named else rows
    return sorted(pool, key=likelihood)[:limit]
