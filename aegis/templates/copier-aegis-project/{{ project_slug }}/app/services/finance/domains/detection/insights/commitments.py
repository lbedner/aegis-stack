"""What counts as a commitment, and whether it is currently owed.

The vocabulary half of insights: predicates and rollups over a recurring
stream, no database and no rules. Half the app asks these questions - the
forecast, the Budget tab, the suggestion guards, the missed-payment nag -
so they answer once here rather than each surface deciding for itself
what "a bill" means. Muting taught us what per-surface treatment costs: a
muted bill vanished from the forecast but kept counting in the Bills
total, and the two disagreed by the whole bill.

Deliberately dependency-light (constants and models only) so a caller can
import it without dragging in the rules that read the database.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict

from sqlmodel import or_

from app.services.finance.constants import CADENCES
from app.services.finance.models import FinanceRecurringStream

# Monthly-equivalent multiplier for the recurring-cost rollup, derived from
# the cadence table so a bill cannot be weighed at one size here and
# stepped at another by the forecast.
MONTHLY_FACTOR = {key: cadence.monthly_factor for key, cadence in CADENCES.items()}

# missed_recurring: days past the expected date before a stream counts as
# missed. Short cadences get a tighter window - a weekly charge four days late
# is meaningful, a monthly one is not.
_MISSED_GRACE_DAYS: dict[str, int] = {
    key: cadence.grace_days for key, cadence in CADENCES.items()
}
_MISSED_GRACE_DEFAULT = 5


class CommitmentRollup(TypedDict):
    monthly_total: int
    fixed: list[FinanceRecurringStream]
    non_monthly: list[FinanceRecurringStream]


def is_commitment(stream: FinanceRecurringStream) -> bool:
    """Whether a stream is part of THE RECORD - created or confirmed by
    the user - and therefore counts.

    This is the money-math half of the structural split: proposals
    (detector guesses, however subscription-ish) count for NOTHING - not
    the forecast, not the monthly-cost headline, not the Budget tab's
    Fixed bucket, not the missed-payment nag. The old shape let a fixed
    monthly guess through, which is how the headline read "$23,575 fixed
    this month from 97 detected bills" about rows nobody had touched, and
    how the app nagged about "missed" bills the user never acknowledged
    having. Confirm is the one door in.
    """
    return stream.is_user_confirmed or stream.source == "user"


def is_paused(stream: FinanceRecurringStream, today: date | None = None) -> bool:
    """Paused while ``paused_until`` is ahead of today.

    A stated fact, not an inference from a pushed date: "skip my
    investments for a few months" without losing the bill. Lazy by
    design - nothing ever un-sets it, so "until Nov 1" means active
    again ON Nov 1 by pure comparison, and no scheduler job exists to
    forget to run. One predicate for every consumer, because mute taught
    us what per-surface treatment costs: a muted bill vanished from the
    forecast but kept counting in the Bills total, and the two surfaces
    disagreed by the whole bill.
    """
    if stream.paused_until is None:
        return False
    return (today or date.today()) < stream.paused_until


def not_paused_clause(today: date):
    """SQL half of ``is_paused`` for the rules that filter in the query.

    Kept adjacent to the Python predicate so the two cannot drift: a rule
    firing about a paused bill is precisely the nag the pause exists to
    silence.
    """
    return or_(
        FinanceRecurringStream.paused_until.is_(None),
        FinanceRecurringStream.paused_until <= today,
    )


def commitment_rollup(
    streams: list[FinanceRecurringStream], today: date | None = None
) -> CommitmentRollup:
    """Commitment outflows only (see ``is_commitment``), split by whether
    they hit monthly or less often - the same monthly-cost math `/recurring`
    already does, shared instead of duplicated so the Budget tab's
    Fixed/Non-monthly split can never drift from it."""
    fixed: list[FinanceRecurringStream] = []
    non_monthly: list[FinanceRecurringStream] = []
    total = 0.0
    for stream in streams:
        # Muted and paused bills charge NOTHING here - the same silence
        # the forecast already honors. Counting them (the original mute
        # behavior) made the Bills cell and the Projected tab disagree
        # by the whole bill.
        if stream.is_muted or is_paused(stream, today):
            continue
        if not (
            stream.direction == "outflow"
            and stream.average_amount
            and is_commitment(stream)
        ):
            continue
        factor = MONTHLY_FACTOR.get(stream.frequency, 0.0)
        total += stream.average_amount * factor
        (fixed if factor >= 1.0 else non_monthly).append(stream)
    return {"monthly_total": int(total), "fixed": fixed, "non_monthly": non_monthly}


def stream_staleness(
    stream: FinanceRecurringStream, today: date, floor: date | None
) -> str:
    """ "fresh" | "overdue" | "stale" - the exact recency signal
    ``_missed_recurring`` already computes to decide whether to fire a
    missed-bill insight, extracted so it can also drive a per-row display
    (the Bills & Income tab) instead of staying implicit in a hidden
    Attention-tab rule. A stream reading "stale" here is precisely the set
    ``_missed_recurring`` already skips as a zombie: "not a live bill that
    just went missing." ``floor`` is the same lookback floor
    ``generate_insights`` computes (``today - FINANCE_RULES_LOOKBACK_DAYS``,
    or ``None`` when lookback is disabled) - callers outside that pass
    compute the identical value themselves rather than this function
    reaching for settings on its own, so a caller testing a specific
    ``lookback_days`` isn't second-guessed by a different default here.
    """
    due = stream.next_expected_date
    if due is None:
        return "fresh"  # no cadence resolved yet - nothing to be overdue against
    if floor is not None and due < floor:
        return "stale"
    grace = _MISSED_GRACE_DAYS.get(stream.frequency, _MISSED_GRACE_DEFAULT)
    if today <= due + timedelta(days=grace):
        return "fresh"
    if stream.last_date is not None and stream.last_date >= due:
        return "fresh"  # it arrived
    return "overdue"
