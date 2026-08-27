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
import re
import statistics

from app.services.finance.constants import CADENCES
from app.services.finance.models import FinanceTransaction
from app.services.finance.utils import normalize_payee

MIN_OCCURRENCES = 3

# Key suffix separating "a second bill on the same payee" from the base
# key ("anthropic", "anthropic#2", "anthropic#a2" for an amount band).
SPLIT_MARK = "#"


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
MAX_SILENCE_DAYS = 120


SILENCE_CADENCE_MULTIPLE = 2


AMOUNT_TOLERANCE = 0.20  # within 20% of median => fixed amount

# When a candidate group resembles a CONFIRMED bill (nested key tokens,
# same cadence, same slot), this is how far its price may sit from the
# bill's average and still be "that bill again" - wider than
# AMOUNT_TOLERANCE because a bill's own history spans its price bumps
# ($15.49 HBO era vs the $18.49 bill it became).
BILL_RESEMBLANCE_TOLERANCE = 0.35


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


# Descriptor churn the fallback key must survive: embedded statement
# dates ("CA 05/25" becomes "CA 06/25" next month), masked card
# references that reformat ("XXXX--X4013", "XXXX4013"), and long
# reference numbers. Each makes one bill a parade of unique keys that
# never reaches MIN_OCCURRENCES.
_EMBEDDED_DATE = re.compile(r"\b\d{1,2}[/-]\d{2,4}\b")
_KEY_NOISE = re.compile(r"\b(?:X{2,}\w*|\w*\d{3,}\w*)\b")
_SPACES = re.compile(r"\s+")


def _descriptor_key(raw: str) -> str:
    """``normalize_payee`` minus the parts that change between charges.

    Only the detection KEY - stored aliases and display names keep the
    full normalization, so nothing already persisted re-keys."""
    base = normalize_payee(_EMBEDDED_DATE.sub(" ", raw))
    return _SPACES.sub(" ", _KEY_NOISE.sub(" ", base)).strip()


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
    feature working at all. The fallback strips descriptor churn first
    (see ``_descriptor_key``): without that, the YouTube case above is
    every unassigned vendor's fate.
    """
    if txn.merchant_id is not None:
        return f"merchant:{txn.merchant_id}"
    return _descriptor_key(
        txn.merchant_name or txn.original_description or txn.name or ""
    )


def _has_gone_quiet(last_date: date, canonical: int | None, today: date) -> bool:
    """Has this stream been silent long enough to be over?

    ``max`` of a flat floor and twice the cadence: the floor gives a
    monthly bill a few months' grace (a card swap, a skipped cycle)
    before it reads as stopped, the multiple keeps an annual one alive
    through its normal 11-month gap. A flat YEAR here meant a monthly
    subscription dead since January was still proposed in August.
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


def _group_cadence(members: list[FinanceTransaction], today: date) -> str | None:
    """The cadence this group would detect as, or None - the same gates
    the main pass applies, shared so the amount-band fallback can never
    disagree with it about what "fails"."""
    if len(members) < MIN_OCCURRENCES:
        return None
    ordered = sorted(members, key=lambda t: (t.date_, t.id or 0))
    gaps = [
        (ordered[i].date_ - ordered[i - 1].date_).days for i in range(1, len(ordered))
    ]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return None
    frequency = _frequency_for(statistics.median(gaps))
    if frequency is None:
        return None
    canonical = _canonical_days(frequency)
    if not canonical or _rhythm_ratio(gaps, canonical) < MIN_RHYTHM_RATIO:
        return None
    if _has_gone_quiet(ordered[-1].date_, canonical, today):
        return None
    return frequency


def _amount_bands(
    members: list[FinanceTransaction],
) -> list[list[FinanceTransaction]]:
    """Greedy clustering by charge size (25%, floored at $3), largest
    band first so the dominant subscription keeps the base key."""
    bands: list[list[FinanceTransaction]] = []
    for txn in sorted(members, key=lambda t: abs(t.amount)):
        for band in bands:
            anchor = abs(band[0].amount)
            if abs(abs(txn.amount) - anchor) <= max(0.25 * anchor, 300):
                band.append(txn)
                break
        else:
            bands.append([txn])
    bands.sort(key=len, reverse=True)
    return bands


def split_interleaved(
    work: list[tuple[int, str, str, list[FinanceTransaction]]],
    today: date,
) -> tuple[
    list[tuple[int, str, str, list[FinanceTransaction]]],
    list[FinanceTransaction],
]:
    """Split a payee group into amount bands when the bands are the
    truer story.

    A group splits when at least TWO bands are independently viable
    streams (enough members, own clean cadence) - authoritative, because
    interleaved gaps can fake a shorter cadence for the whole group - or
    when the whole group has no rhythm and exactly ONE band does: a live
    subscription must not die with the dead sibling it used to share a
    descriptor with. A variable bill (seasonal electric) reaches
    neither: one viable band, but the whole group keeps its own clean
    rhythm and stays whole. The dominant band keeps the base key;
    members in no viable band are returned for release.
    """
    expanded: list[tuple[int, str, str, list[FinanceTransaction]]] = []
    released: list[FinanceTransaction] = []
    for account_id, direction, payee, members in work:
        if len(members) >= 2 * MIN_OCCURRENCES:
            bands = [b for b in _amount_bands(members) if _group_cadence(b, today)]
            if bands and (len(bands) >= 2 or _group_cadence(members, today) is None):
                for index, band in enumerate(bands):
                    key = payee if index == 0 else f"{payee}{SPLIT_MARK}a{index + 1}"
                    expanded.append((account_id, direction, key, band))
                banded = {id(t) for b in bands for t in b}
                released.extend(t for t in members if id(t) not in banded)
                continue
        expanded.append((account_id, direction, payee, members))
    return expanded, released
