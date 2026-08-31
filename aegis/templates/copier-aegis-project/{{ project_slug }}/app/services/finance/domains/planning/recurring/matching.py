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
    def named_for(
        name: str | None, merchant_id: int | None, txn: FinanceTransaction
    ) -> bool:
        if merchant_id is not None and txn.merchant_id == merchant_id:
            return True
        name_cf = (name or "").casefold()
        if not name_cf:
            return False
        haystack = f"{txn.name or ''} {txn.original_description or ''}".casefold()
        return name_cf in haystack

    def named_alike(txn: FinanceTransaction) -> bool:
        return named_for(stream.name, stream.merchant_id, txn)

    # A row carrying a DIFFERENT live bill's name is that bill's
    # business, not an answer here: ranked on figures alone, the
    # YouTube picker offered DoorDash rows whose amounts landed in
    # the window (confirmed live). Only the fallback pool filters
    # these - a row naming THIS bill stays offered regardless, and
    # the tie goes to the human.
    siblings = [
        (s.name, s.merchant_id)
        for s in await queries.active_streams(db, owner_user_id=owner_user_id)
        if s.id != stream.id and s.direction == stream.direction
    ]

    def claimed_by_sibling(txn: FinanceTransaction) -> bool:
        return any(named_for(n, m, txn) for n, m in siblings)

    # A row the system already IDENTIFIES as someone else is not a
    # candidate: a $9 bill's band admits every $9 purchase in the
    # register, and they all arrive pre-labelled - McDonald's as Fast
    # Food, CVS as Pharmacy (nine of them in the Patreon picker,
    # confirmed live). A resolved merchant or a category pointing away
    # from the bill is that identification. The fallback exists for
    # UNRECOGNIZABLE descriptors, and those still pass: no merchant, no
    # category, nothing known. The bill's own category is the stored one
    # or, exactly like the display inference, the one its matched
    # history agrees on - the Citi bill stores none, but every member is
    # Finance Charge, and that is what separates the interest rows (the
    # answers) from the grocery runs (confirmed live).
    reference_category = stream.category_id
    if reference_category is None:
        reference_category = await queries.stream_member_category_id(db, stream.id)

    def identified_as_other(txn: FinanceTransaction) -> bool:
        # Category agreement is identification FOR the stream and
        # outranks a merchant mismatch. Inflows are where this bites:
        # a paycheck always arrives pre-labelled with the payroll
        # processor's merchant, which never equals the human-named
        # stream - ranked on merchant alone, the $5,000 paycheck was
        # "someone else" and the picker offered nothing (confirmed
        # live).
        if reference_category is not None and txn.category_id == reference_category:
            return False
        if txn.merchant_id is not None and txn.merchant_id != stream.merchant_id:
            return True
        return (
            reference_category is not None
            and txn.category_id is not None
            and txn.category_id != reference_category
        )

    def likelihood(txn: FinanceTransaction) -> tuple[int, int, int]:
        amount_distance = abs(abs(txn.amount) - expected) if expected else 0
        date_distance = abs((txn.date_ - (due or today)).days)
        return (0 if named_alike(txn) else 1, amount_distance, date_distance)

    # When rows carry the bill's own name, the strangers are noise
    # and stay out entirely ("it's so obviously Fidelity and not
    # AT&T"); the amount shortlist earns its keep only when the
    # payment arrived under an unrecognizable descriptor.
    named = [t for t in rows if named_alike(t)]
    pool = named or [
        t for t in rows if not claimed_by_sibling(t) and not identified_as_other(t)
    ]
    return sorted(pool, key=likelihood)[:limit]
