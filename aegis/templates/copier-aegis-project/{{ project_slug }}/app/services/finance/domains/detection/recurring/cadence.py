"""Does this look like a rhythm, and whose rhythm is it.

Pure judgement over gaps and descriptors - no database, no writes. The
tuning constants live here with the functions that read them, because
every one of them is a threshold somebody will want to argue with, and an
argument about MIN_STREAM_AMOUNT should land in the same file as the
arithmetic it feeds.

Heuristic: group posted, non-transfer transactions by
``(account, direction, normalized payee)``; a group with >=
``MIN_OCCURRENCES`` whose median gap matches a known cadence (within
``INTERVAL_TOLERANCE``) is a stream. Amounts within ``AMOUNT_TOLERANCE``
of the median are "fixed"; otherwise the stream is variable (a utility
bill).
"""

from __future__ import annotations

from datetime import date
import statistics

from app.services.finance.constants import CADENCES
from app.services.finance.models import FinanceTransaction
from app.services.finance.utils import normalize_payee

MIN_OCCURRENCES = 3


INTERVAL_TOLERANCE = 0.20  # +/- 20% of a canonical cadence


# ...but never more than this in absolute days. 20% of a year is a 73-day
# window, so anything from 292 to 438 days read as "yearly" - which is how
# a convenience store with four visits (gaps of 2044, 430 and 17 days)
# became an annual subscription. The cap only binds on long cadences; 20%
# of a week is a day and a half, and stays.
MAX_INTERVAL_SLACK_DAYS = 21


# How many of a group's gaps must actually sit near the cadence before it
# counts as a rhythm. A median alone cannot tell [30, 31, 29] from
# [2044, 430, 17]. Two thirds leaves room for a bill that skipped a month
# without letting noise through.
MIN_RHYTHM_RATIO = 0.6


# Below this a stream is a rounding error with a heartbeat: a savings
# account paid $0.31 for 54 months running - flawless cadence, fixed
# amount, and meaningless. Set under a real cheap subscription ($5.41 CVS
# ExtraCare) so those still count.
MIN_STREAM_AMOUNT = 200


# How long a stream may go quiet before it stops being a live bill. Shape
# alone cannot catch these: CAPITAL ONE AUTO CARPAY really was monthly,
# and so were Wix, AES, TJX and Synchrony - they simply ended in 2019.
# Scaled by cadence, because 11 months of silence is normal for an annual
# bill and terminal for a monthly one.
MAX_SILENCE_DAYS = 365


SILENCE_CADENCE_MULTIPLE = 2


AMOUNT_TOLERANCE = 0.20  # within 20% of median => fixed amount


# Canonical cadence (median-gap days) -> frequency label.
# Derived from the cadence table (constants.CADENCES), which is ordered
# shortest-first - and the order is load-bearing here, because the FIRST
# band a median falls in wins. Where two touch, the shorter cadence takes
# the overlap: at 72 days that is bimonthly, which is also the closer
# canonical value (12 days from 60, 18 from 90).
_CADENCES: tuple[tuple[int, str], ...] = tuple(
    (cadence.detect_days, key) for key, cadence in CADENCES.items()
)


_SUBSCRIPTION_FREQUENCIES = {"monthly", "annually"}


def _cadence_slack(days: int) -> float:
    """Allowed drift around a canonical cadence, in days."""
    return min(days * INTERVAL_TOLERANCE, MAX_INTERVAL_SLACK_DAYS)


def _frequency_for(median_interval: float) -> str | None:
    """Map a median day-gap to a cadence label, or None if it matches none."""
    for days, label in _CADENCES:
        if abs(median_interval - days) <= _cadence_slack(days):
            return label
    return None


def _canonical_days(frequency: str) -> int | None:
    for days, label in _CADENCES:
        if label == frequency:
            return days
    return None


def _rhythm_ratio(gaps: list[int], canonical: int) -> float:
    """Fraction of gaps that actually sit near ``canonical``.

    The median says where the middle is; this says whether there IS a
    middle. ``[30, 31, 29]`` scores 1.0 and ``[2044, 430, 17]`` scores
    0.33 even though both have a median inside their cadence band.
    """
    if not gaps:
        return 0.0
    slack = _cadence_slack(canonical)
    return sum(1 for g in gaps if abs(g - canonical) <= slack) / len(gaps)


def _payee_key(txn: FinanceTransaction) -> str:
    """Stable grouping key for one transaction.

    An assigned payee (``FinanceMerchant``, "the prerequisite for
    recurring/subscription detection" per its own model docstring) wins
    outright: a bank descriptor is not a stable identity, and treating it
    as one splits a single bill every time the format drifts. Confirmed
    live on real data - one YouTube Premium subscription appeared as
    "YOUTUBEPREMIG.CO/HELPPAY# CA XXXX--X3007" then "YOUTUBEPREMI
    G.CO/HELPPAY# CA XXXX3007" (a space moved, the card ref changed) =
    two streams, and after it moved to another account as "YouTubePremi
    g.co/helppay# CA 07/19" the embedded statement date made EVERY month
    a unique string, so it never reached MIN_OCCURRENCES and was never
    detected at all.

    The normalized-descriptor fallback is what still auto-detects
    everything nobody has named a payee for - so assigning payees is an
    improvement you opt into per merchant, not a prerequisite for the
    feature working at all.
    """
    if txn.merchant_id is not None:
        return f"merchant:{txn.merchant_id}"
    return normalize_payee(
        txn.merchant_name or txn.original_description or txn.name or ""
    )


def _has_gone_quiet(last_date: date, canonical: int | None, today: date) -> bool:
    """Has this stream been silent long enough to be over?

    ``max`` of a flat year and twice the cadence: the flat floor kills a
    monthly bill that stopped, the multiple keeps an annual one alive
    through its normal 11-month gap.
    """
    window = max(MAX_SILENCE_DAYS, SILENCE_CADENCE_MULTIPLE * (canonical or 0))
    return (today - last_date).days > window


def _declared_cadence(members: list[FinanceTransaction]) -> tuple[str, float | None]:
    """``(frequency, median gap)`` for a group the USER says is recurring.

    Detection may decline - fewer than ``MIN_OCCURRENCES``, or a median gap
    matching no canonical cadence - and returning "not recurring" is right
    for a guess. It is wrong for an instruction: the user selected these
    rows and said this is a bill, so the only open question is which label
    fits, not whether to make one.

    So the ladder never bottoms out at a refusal. A cadence that matches a
    canonical gap gets that name; one that does not is "irregular" and
    still carries its real median forward, so the next date is projected
    from what actually happened; a single transaction has no gap to
    measure at all and stays "unknown" until a second one arrives.
    """
    gaps = [
        (members[i].date_ - members[i - 1].date_).days for i in range(1, len(members))
    ]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return "unknown", None
    median_interval = statistics.median(gaps)
    return _frequency_for(median_interval) or "irregular", median_interval
