"""Could this row be this bill's payment.

The question is asked in two places and used to have two answers. The
reconcile picker (``recurring_match_candidates``) learned its rules the
hard way and states them: half to double the expected figure, within a
cadence-scaled window of the due date. The backfill that runs when a
payment is attached asked nothing at all - it claimed every unclaimed
row of the merchant in the bill's direction - so one "mark as paid" on
the CVS ExtraCare charge swept in all 273 CVS purchases ever made, and
Citi's three "INTEREST CHARGED TO ..." lines per statement all landed on
one monthly stream and dragged its amount to a third of the real charge.

The amount band is the shared half and lives here. The date half does
NOT transfer: the picker answers "which payment was THIS due date" and
wants one occurrence's neighborhood, while the backfill answers "which
past rows were this bill" and wants all of them. What the backfill needs
instead is the arithmetic the picker gets for free by only ever
returning one row - a monthly bill is paid once a month, so at most one
row per period, and where a period holds several the nearest to the
bill's own figure is the payment.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.finance.constants import CADENCES
from app.services.finance.models import FinanceRecurringStream, FinanceTransaction


def amount_band(expected: int | None) -> tuple[int, int] | None:
    """Half to double ``expected``, or None when the bill has no figure.

    Deliberately loose, and the looseness is load-bearing: a tight band
    hides exactly the changed-amount payment that broke the automatic
    match in the first place.
    """
    if not expected:
        return None
    return int(expected * 0.5), int(expected * 2)


def claimable_strays(
    stream: FinanceRecurringStream,
    strays: Sequence[FinanceTransaction],
    members: Sequence[FinanceTransaction],
    *,
    band: bool = True,
) -> list[FinanceTransaction]:
    """Which of the payee's unclaimed rows this bill should absorb.

    ``band=False`` drops the amount test and leaves one-per-period as
    the whole rule. The repair pass needs that: it is re-reading streams
    whose amount is KNOWN to be wrong - that is why it is running - so
    banding on that figure would throw away real payments to protect a
    number nobody trusts. American Express lost 67 of its 83 payments
    that way. One-per-period holds regardless: a monthly bill is paid
    once a month whatever it costs.
    """
    expected = stream.amount
    # A variable bill's amount is not evidence of anything - that is
    # what the flag MEANS - and banding one throws away real payments:
    # Central Hudson averages $401 and has billed $918, which half to
    # double does not reach. 587 of the 883 rows this released on the
    # live ledger came from variable streams before the flag was
    # honoured here. One-per-period still caps them, and the nearest
    # row to the bill's own figure is still the one it picks.
    window = amount_band(expected) if band and not stream.amount_is_variable else None
    if window is not None:
        low, high = window
        strays = [t for t in strays if low <= abs(t.amount) <= high]
    cadence = CADENCES.get(stream.frequency)
    if cadence is None or not strays:
        # No cadence, no periods to divide into - "once" and "irregular"
        # have no rhythm to be paid on, so the band is the whole test.
        return list(strays)

    def period(row: FinanceTransaction) -> int:
        return (row.date_ - anchor).days // cadence.detect_days

    def distance(row: FinanceTransaction) -> int:
        return abs(abs(row.amount) - expected) if expected else 0

    anchor = min(t.date_ for t in list(strays) + list(members))
    # A period the bill already has a payment in is settled. Claiming a
    # second row for it is how a monthly stream ends up with 3.2 members
    # a month and a median that describes none of them.
    taken = {period(m) for m in members}
    nearest: dict[int, FinanceTransaction] = {}
    for row in strays:
        slot = period(row)
        if slot in taken:
            continue
        standing = nearest.get(slot)
        if standing is None or distance(row) < distance(standing):
            nearest[slot] = row
    return [nearest[slot] for slot in sorted(nearest)]
