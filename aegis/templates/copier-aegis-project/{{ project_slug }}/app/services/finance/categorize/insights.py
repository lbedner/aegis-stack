"""Rule-based "wasting money" insights, no AI.

Runs nightly after recurring detection. Writes ``finance_insight`` rows
(deduped on ``(owner, dedup_key)``) so the same alert isn't regenerated every
night. The rules:

- **price_hike** — a fixed-amount recurring stream charged more than last time.
- **fee_charged** — a bank/finance fee or interest charge hit an account.
- **overspend_category** — this month's category spend is way above its recent
  norm (needs >= 3 prior full months, else skipped silently).
- **large_transaction** — one charge far outside its own account's recent norm.
- **missed_recurring** — a mature stream's expected charge never showed up.
- **card_overdue** — the institution reports a credit account past due.
- **min_payment_gap** — a minimum payment due soon exceeds cash on hand.
- **high_apr_carry** — a balance is accruing interest at an expensive APR.
- **credit_utilization** — a card is close to its credit limit.
- **cash_runway** — scheduled bills walk the cash balance below zero.
- **subscription_creep** — the subscription total drifted well above its norm.

Every rule is deterministic: thresholds are module constants, tuned by test
rather than by config surface. Anything that reads these rows (the Insights
list, the analyst agent's daily note) consumes findings it did not make, so a
model can never invent an alert.

This is the finance-local path. When the insights service is present a bridge
can additionally emit through its event machinery; the local rows are the
source of truth for dedup + the finance modal's Insights list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re
import statistics
from typing import TypedDict

from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import CADENCES, CASH_ACCOUNT_TYPES
from app.services.finance.models import (
    FinanceAccount,
    FinanceInsight,
    FinanceLiabilityDetail,
    FinanceRecurringStream,
    FinanceTransaction,
)

PRICE_HIKE_THRESHOLD = 1.10  # >10% over the stream's average
OVERSPEND_MULTIPLE = 1.5  # > 1.5x the 3-month median
OVERSPEND_MIN_HISTORY = 3  # need >= 3 prior full months
# Comparing on pace shrinks the baseline, which is the point (the rule can
# now fire while the month can still be steered) but also makes the early
# days dangerous: three days of history is mostly noise, and one grocery
# run against it reads as an emergency. Judge nothing until a quarter of
# the month has passed, and never multiply a baseline too small to mean
# anything.
OVERSPEND_MIN_ELAPSED = 0.25
OVERSPEND_MIN_BASELINE = 5_000  # cents
_FEE_PFC = "BANK_FEES"
_FEE_RE = re.compile(r"FEE|INTEREST CHARGE|FINANCE CHARGE", re.IGNORECASE)

# large_transaction: an outlier is judged against its OWN account, because a
# normal charge on a grocery card and a normal charge on a mortgage account are
# nothing alike. The floors keep a quiet account from crying wolf over an
# ordinary purchase that happens to beat its small median.
LARGE_TXN_WINDOW_DAYS = 35  # how far back to look for candidates
LARGE_TXN_BASELINE_DAYS = 90  # the account's own recent norm
LARGE_TXN_MIN_BASELINE = 10  # peers needed before the median is trusted
LARGE_TXN_MULTIPLE = 4  # x the account's median outflow
LARGE_TXN_CRITICAL_MULTIPLE = 10  # x the median -> critical, not warning
LARGE_TXN_FLOOR = 20_000  # cents; never alert below this
LARGE_TXN_THIN_FLOOR = 50_000  # cents; the only test when history is thin

# Credit-card / liquidity rules. These are the "someone told the system to
# look" checks: a card in trouble is flagged by code reading the provider's
# own liability detail, never by a model happening to notice. APRs are basis
# points (2999 = 29.99%); amounts are cents.
HIGH_APR_BPS = 2_000  # >= 20.00% counts as expensive money
HIGH_APR_MIN_BALANCE = 10_000  # ignore trivial carried balances
UTILIZATION_WARNING = 0.80  # of the credit limit
UTILIZATION_CRITICAL = 0.95
MIN_PAYMENT_LOOKAHEAD_DAYS = 14  # how far ahead a due date is "soon"
RUNWAY_DAYS = 60  # projection window for the cash-runway rule
SUBSCRIPTION_CREEP_MULTIPLE = 1.25  # x the prior-months median

# missed_recurring: days past the expected date before a stream counts as
# missed. Short cadences get a tighter window - a weekly charge four days late
# is meaningful, a monthly one is not.
_MISSED_GRACE_DAYS: dict[str, int] = {
    key: cadence.grace_days for key, cadence in CADENCES.items()
}
_MISSED_GRACE_DEFAULT = 5
# Only commitments are worth chasing. Detection happily finds a weekly cadence
# in someone's coffee habit, and "you have not been to Starbucks" is not an
# alert - so weekly/biweekly OUTFLOWS are skipped. Income is always chased at
# any cadence, because a late paycheck matters whatever its rhythm.
_BILL_FREQUENCIES = frozenset({"semi_monthly", "monthly", "quarterly", "annually"})


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


# Monthly-equivalent multiplier for the recurring-cost rollup, derived from
# the cadence table so a bill cannot be weighed at one size here and
# stepped at another by the forecast.
_MONTHLY_FACTOR = {key: cadence.monthly_factor for key, cadence in CADENCES.items()}


class CommitmentRollup(TypedDict):
    monthly_total: int
    fixed: list[FinanceRecurringStream]
    non_monthly: list[FinanceRecurringStream]


def _not_paused_clause(today: date):
    """SQL half of ``is_paused`` for the rules that filter in the query.

    Kept adjacent to the Python predicate so the two cannot drift: a rule
    firing about a paused bill is precisely the nag the pause exists to
    silence.
    """
    return or_(
        FinanceRecurringStream.paused_until.is_(None),
        FinanceRecurringStream.paused_until <= today,
    )


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
        factor = _MONTHLY_FACTOR.get(stream.frequency, 0.0)
        total += stream.average_amount * factor
        (fixed if factor >= 1.0 else non_monthly).append(stream)
    return {"monthly_total": int(total), "fixed": fixed, "non_monthly": non_monthly}


def stream_staleness(
    stream: FinanceRecurringStream, today: date, floor: date | None
) -> str:
    """"fresh" | "overdue" | "stale" - the exact recency signal
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


@dataclass
class InsightGenerationResult:
    """Counts from one generation pass."""

    created: int = 0


def format_usd(cents: int) -> str:
    return f"${abs(cents) / 100:,.2f}"


def format_apr(bps: int) -> str:
    """Basis points as a display percentage: 2999 -> '29.99%'."""
    return f"{bps / 100:.2f}%"


def card_apr_bps(detail: FinanceLiabilityDetail) -> int | None:
    """The account's headline APR in basis points.

    Prefers the purchase APR (the rate a carried card balance actually pays),
    falls back to the highest APR the provider reports, then to the flat
    ``interest_rate_bps`` a loan carries. Shared with the analyst snapshot so
    the alert and the context always quote the same rate.
    """
    best: int | None = None
    for entry in detail.aprs or []:
        bps = entry.get("apr_percentage_bps")
        if bps is None:
            continue
        if entry.get("apr_type") == "purchase_apr":
            return bps
        best = bps if best is None else max(best, bps)
    return best if best is not None else detail.interest_rate_bps


def month_key(day: date) -> str:
    """The ``YYYY-MM`` bucket a day falls in."""
    return f"{day.year:04d}-{day.month:02d}"


def _month_start_before(day: date, months_back: int) -> date:
    """The first of the month ``months_back`` months before ``day``'s month."""
    year, month = day.year, day.month
    for _ in range(months_back):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return date(year, month, 1)


def _owner_clause(column, owner_user_id: int | None):
    """Scan the owner's rows; a NULL owner (standalone, no auth) uses IS NULL."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


def live_account_ids(owner_user_id: int | None):
    """Subquery selecting the owner's non-deleted account ids."""
    return select(FinanceAccount.id).where(
        FinanceAccount.deleted_at.is_(None),
        _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
    )


def _days_in_month(day: date) -> int:
    """Days in ``day``'s own month."""
    first_next = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    return (first_next - day.replace(day=1)).days


def month_is_complete(day: date) -> bool:
    """Is ``day`` the last day of its own month?"""
    return (day + timedelta(days=1)).month != day.month


def pace_day(today: date) -> int | None:
    """The day-of-month prior months should be measured to, or ``None``.

    ``None`` on the last day of a month: there is nothing to pro-rate, and
    truncating whole months would understate the norm instead.
    """
    return None if month_is_complete(today) else today.day


async def monthly_category_spend(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date,
    months_back: int = OVERSPEND_MIN_HISTORY,
    through_day: int | None = None,
) -> dict[int, dict[str, int]]:
    """``{category_id: {"YYYY-MM": spend_cents}}`` over the trailing window.

    Transfer-excluded, categorized outflows only. Shared by the overspend rule
    and the analyst's snapshot so that "more than usual" means exactly the same
    thing wherever the product says it.

    ``through_day`` counts only spend on or before that day of the month, in
    every month including the current one. Without it a part-finished month is
    weighed against whole prior months: on the 9th that is nine days against
    thirty, which makes almost every category look cheap and makes the
    overspend rule almost unable to fire until the month is over. Pass
    ``pace_day(today)``.
    """
    rows = (
        await db.exec(
            select(FinanceTransaction).where(
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                FinanceTransaction.excluded_from_reports.is_(False),
                FinanceTransaction.amount < 0,
                FinanceTransaction.category_id.is_not(None),
                FinanceTransaction.date_ >= _month_start_before(today, months_back),
                FinanceTransaction.account_id.in_(live_account_ids(owner_user_id)),
            )
        )
    ).all()

    by_category: dict[int, dict[str, int]] = {}
    for txn in rows:
        if through_day is not None and txn.date_.day > through_day:
            continue
        months = by_category.setdefault(txn.category_id, {})
        key = month_key(txn.date_)
        months[key] = months.get(key, 0) + abs(txn.amount)
    return by_category


async def generate_insights(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date | None = None,
    lookback_days: int | None = None,
) -> InsightGenerationResult:
    """Run every insight rule for one owner. Idempotent (dedup_key).

    Insights have a NOT-NULL owner, so a standalone (NULL-owner) install stores
    them under the ``0`` sentinel while scanning its NULL-owner rows.

    ``lookback_days`` (``settings.FINANCE_RULES_LOOKBACK_DAYS`` when not
    given; 0 disables it) floors the fee and missed-recurring rules so a deep
    historical import doesn't flood the list with years-old findings. The
    other rules already carry their own windows.
    """
    from app.core.config import settings

    result = InsightGenerationResult()
    today = today or date.today()
    if lookback_days is None:
        lookback_days = settings.FINANCE_RULES_LOOKBACK_DAYS
    floor = today - timedelta(days=lookback_days) if lookback_days else None
    store_owner = 0 if owner_user_id is None else owner_user_id

    live_accounts = live_account_ids(owner_user_id)

    result.created += await _price_hikes(db, store_owner, today)
    result.created += await _fees(db, owner_user_id, store_owner, live_accounts, floor)
    result.created += await _overspend(db, owner_user_id, store_owner, today)
    result.created += await _large_transactions(
        db, owner_user_id, store_owner, live_accounts, today
    )
    result.created += await _missed_recurring(
        db, store_owner, live_accounts, today, floor
    )
    result.created += await _credit_cards(db, owner_user_id, store_owner, today)
    result.created += await _cash_runway(db, owner_user_id, store_owner, today)
    result.created += await _subscription_creep(db, owner_user_id, store_owner, today)
    return result


async def create_insight_if_new(
    db: AsyncSession,
    *,
    owner_user_id: int,
    insight_type: str,
    dedup_key: str,
    severity: str,
    title: str,
    body: str,
    detected_amount: int | None = None,
    related_stream_id: int | None = None,
    related_transaction_id: int | None = None,
    related_category_id: int | None = None,
    related_account_id: int | None = None,
) -> FinanceInsight | None:
    """Insert an insight unless its dedup_key already exists.

    Returns the new row, or None when one was already there. Truthy exactly
    when it created something, so rules that only count creations read the
    same as they always did.
    """
    exists = (
        await db.exec(
            select(FinanceInsight.id).where(
                FinanceInsight.owner_user_id == owner_user_id,
                FinanceInsight.dedup_key == dedup_key,
            )
        )
    ).first()
    if exists is not None:
        return None
    insight = FinanceInsight(
        owner_user_id=owner_user_id,
        insight_type=insight_type,
        severity=severity,
        title=title,
        body=body,
        dedup_key=dedup_key,
        detected_amount=detected_amount,
        related_stream_id=related_stream_id,
        related_transaction_id=related_transaction_id,
        related_category_id=related_category_id,
        related_account_id=related_account_id,
    )
    db.add(insight)
    await db.flush()
    return insight


async def _price_hikes(db: AsyncSession, store_owner: int, today: date) -> int:
    """A fixed-amount recurring stream now costs more than its average."""
    streams = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == store_owner,
                FinanceRecurringStream.deleted_at.is_(None),
                FinanceRecurringStream.status == "mature",
                FinanceRecurringStream.is_muted.is_(False),
                _not_paused_clause(today),
                FinanceRecurringStream.amount_is_variable.is_(False),
                FinanceRecurringStream.direction == "outflow",
            )
        )
    ).all()
    created = 0
    for stream in streams:
        avg = stream.average_amount or 0
        last = stream.last_amount or 0
        if avg <= 0 or last <= avg * PRICE_HIKE_THRESHOLD:
            continue
        # Re-alert only on a NEW price (last_amount in the key).
        if await create_insight_if_new(
            db,
            owner_user_id=store_owner,
            insight_type="price_hike",
            dedup_key=f"price_hike:{stream.id}:{last}",
            severity="warning",
            title=f"{stream.name} went up to {format_usd(last)}",
            body=(
                f"{stream.name} usually costs about {format_usd(avg)} but the latest "
                f"charge was {format_usd(last)}."
            ),
            detected_amount=last,
            related_stream_id=stream.id,
        ):
            created += 1
    return created


async def _fees(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    live_accounts,
    floor: date | None,
) -> int:
    """Bank/finance fees + interest charges dated inside the lookback window."""
    filters = [
        _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.amount < 0,
        FinanceTransaction.account_id.in_(live_accounts),
    ]
    if floor is not None:
        filters.append(FinanceTransaction.date_ >= floor)
    txns = (await db.exec(select(FinanceTransaction).where(*filters))).all()
    created = 0
    for txn in txns:
        is_fee = txn.pfc_primary == _FEE_PFC or bool(_FEE_RE.search(txn.name or ""))
        if not is_fee:
            continue
        if await create_insight_if_new(
            db,
            owner_user_id=store_owner,
            insight_type="fee_charged",
            dedup_key=f"fee:{txn.id}",
            severity="warning",
            title=f"Fee charged: {format_usd(txn.amount)}",
            body=f"{txn.name or 'A fee'} on {txn.date_} cost {format_usd(txn.amount)}.",
            detected_amount=txn.amount,
            related_transaction_id=txn.id,
            related_category_id=txn.category_id,
        ):
            created += 1
    return created


async def _overspend(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    today: date,
) -> int:
    """This month's category spend is > 1.5x the prior-3-month median.

    Measured ON PACE: prior months are counted only to the same day of the
    month, so a part-finished month is not weighed against whole ones. The
    old comparison could barely clear 1.5x before the month was nearly
    over, which made the warning a post-mortem rather than something a
    reader could still act on.
    """
    through = pace_day(today)
    by_cat = await monthly_category_spend(
        db, owner_user_id=owner_user_id, today=today, through_day=through
    )
    current_key = month_key(today)
    days_in_month = _days_in_month(today)
    elapsed = 1.0 if through is None else through / days_in_month

    created = 0
    for category_id, months in by_cat.items():
        current = months.get(current_key, 0)
        prior = [amount for key, amount in months.items() if key != current_key]
        if current <= 0 or len(prior) < OVERSPEND_MIN_HISTORY:
            continue  # not enough history -> skip silently
        if elapsed < OVERSPEND_MIN_ELAPSED:
            continue  # too early in the month to judge it
        median_prior = statistics.median(prior)
        if median_prior < OVERSPEND_MIN_BASELINE:
            continue  # a ratio against pocket change is arithmetic, not news
        if current <= median_prior * OVERSPEND_MULTIPLE:
            continue
        if await create_insight_if_new(
            db,
            owner_user_id=store_owner,
            insight_type="overspend_category",
            dedup_key=f"overspend:{category_id}:{current_key.replace('-', '')}",
            severity="warning",
            title=f"Spending up this month ({format_usd(current)})",
            body=(
                f"This month is {format_usd(current)} vs a typical "
                f"{format_usd(int(median_prior))}"
                + (
                    f" by day {through} for this category."
                    if through is not None
                    else " for this category."
                )
            ),
            detected_amount=current,
            related_category_id=category_id,
        ):
            created += 1
    return created


async def _large_transactions(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    live_accounts,
    today: date,
) -> int:
    """One charge far outside its own account's recent norm.

    Recurring members are excluded on purpose: a mortgage payment is large
    every month, and streams already have their own rule (``price_hike``).
    Candidates are limited to a recent window so a first run against years of
    imported history doesn't dump a hundred alerts about ancient purchases.
    """
    rows = (
        await db.exec(
            select(FinanceTransaction).where(
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                FinanceTransaction.excluded_from_reports.is_(False),
                FinanceTransaction.is_transfer.is_(False),
                FinanceTransaction.recurring_stream_id.is_(None),
                FinanceTransaction.amount < 0,
                FinanceTransaction.date_
                >= today - timedelta(days=LARGE_TXN_BASELINE_DAYS),
                FinanceTransaction.account_id.in_(live_accounts),
            )
        )
    ).all()

    by_account: dict[int, list[FinanceTransaction]] = {}
    for txn in rows:
        by_account.setdefault(txn.account_id, []).append(txn)

    candidate_start = today - timedelta(days=LARGE_TXN_WINDOW_DAYS)
    created = 0
    for txns in by_account.values():
        peer_amounts = {txn.id: abs(txn.amount) for txn in txns}
        for txn in txns:
            if txn.date_ < candidate_start:
                continue  # baseline only
            amount = abs(txn.amount)
            # A transaction is never its own baseline.
            peers = [
                value for txn_id, value in peer_amounts.items() if txn_id != txn.id
            ]
            if len(peers) >= LARGE_TXN_MIN_BASELINE:
                median_peer = statistics.median(peers)
                threshold = max(LARGE_TXN_FLOOR, int(median_peer * LARGE_TXN_MULTIPLE))
                critical_at = median_peer * LARGE_TXN_CRITICAL_MULTIPLE
                body = (
                    f"{txn.name or 'A charge'} on {txn.date_} was {format_usd(amount)}, "
                    f"well above the usual {format_usd(int(median_peer))} on this account."
                )
            else:
                threshold = LARGE_TXN_THIN_FLOOR
                critical_at = None
                body = (
                    f"{txn.name or 'A charge'} on {txn.date_} was {format_usd(amount)}, "
                    "unusually large for this account."
                )
            if amount < threshold:
                continue
            severity = (
                "critical"
                if critical_at is not None and amount >= critical_at
                else "warning"
            )
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="large_transaction",
                dedup_key=f"large_txn:{txn.id}",
                severity=severity,
                title=f"Large charge: {format_usd(amount)}",
                body=body,
                detected_amount=txn.amount,
                related_transaction_id=txn.id,
                related_account_id=txn.account_id,
                related_category_id=txn.category_id,
            ):
                created += 1
    return created


async def _missed_recurring(
    db: AsyncSession,
    store_owner: int,
    live_accounts,
    today: date,
    floor: date | None = None,
) -> int:
    """A mature stream whose expected charge never arrived.

    Runs after ``detect_recurring``, which advances ``next_expected_date`` when
    a charge lands - so a stream still pointing at a past due date with nothing
    newer than that date is genuinely overdue, not merely stale.
    """
    streams = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id == store_owner,
                FinanceRecurringStream.deleted_at.is_(None),
                FinanceRecurringStream.status == "mature",
                FinanceRecurringStream.is_active.is_(True),
                FinanceRecurringStream.is_muted.is_(False),
                _not_paused_clause(today),
                FinanceRecurringStream.next_expected_date.is_not(None),
                or_(
                    FinanceRecurringStream.account_id.is_(None),
                    FinanceRecurringStream.account_id.in_(live_accounts),
                ),
            )
        )
    ).all()
    if not streams:
        return 0

    # A recurring INTERNAL TRANSFER (a monthly checking->savings sweep) ticks
    # like a bill, but "your transfer hasn't been paid" is not an alert -
    # money you move between your own accounts is not owed to anyone. A
    # stream with any transfer-flagged member is a transfer rhythm; skip it.
    transfer_stream_ids = set(
        (
            await db.exec(
                select(FinanceTransaction.recurring_stream_id)
                .where(
                    FinanceTransaction.recurring_stream_id.in_([s.id for s in streams]),
                    FinanceTransaction.is_transfer.is_(True),
                )
                .distinct()
            )
        ).all()
    )

    created = 0
    for stream in streams:
        if stream.id in transfer_stream_ids:
            # An internal-transfer rhythm, not an obligation. Pairing can
            # land AFTER an earlier pass already alerted (a multi-file
            # import sees one leg before the other), so also retract any
            # alert that pass created - it was wrong, not merely stale.
            stale = (
                await db.exec(
                    select(FinanceInsight).where(
                        FinanceInsight.owner_user_id == store_owner,
                        FinanceInsight.insight_type == "missed_recurring",
                        FinanceInsight.related_stream_id == stream.id,
                    )
                )
            ).all()
            for insight in stale:
                await db.delete(insight)
            if stale:
                await db.flush()
            continue
        inflow = stream.direction == "inflow"
        if not inflow and not is_commitment(stream):
            continue  # a merchant-visit rhythm, not a commitment
        due = stream.next_expected_date
        if stream_staleness(stream, today, floor) != "overdue":
            # "fresh" (not due yet, or arrived) or "stale" (a zombie
            # stream out of imported history - a cancelled subscription,
            # a closed account, not a live bill that just went missing)
            # - only "overdue" is worth an alert.
            continue
        amount = stream.expected_amount or stream.average_amount or 0
        title = (
            f"{stream.name} hasn't arrived"
            if inflow
            else f"{stream.name} hasn't been paid"
        )
        if await create_insight_if_new(
            db,
            owner_user_id=store_owner,
            insight_type="missed_recurring",
            # Keyed to the due date, so the next missed cycle alerts again.
            dedup_key=f"missed:{stream.id}:{due.isoformat()}",
            severity="critical" if inflow else "warning",
            title=title,
            body=(
                f"{stream.name} was expected on {due} ({format_usd(amount)}) and "
                "has not shown up."
            ),
            detected_amount=amount,
            related_stream_id=stream.id,
            related_account_id=stream.account_id,
            related_category_id=stream.category_id,
        ):
            created += 1
    return created


async def _liquid_cash(db: AsyncSession, owner_user_id: int | None) -> int:
    """Spendable cash across the owner's live cash accounts, in cents.

    ``available_balance`` (what the bank will actually let out the door)
    beats ``current_balance`` when present.
    """
    accounts = (
        await db.exec(
            select(FinanceAccount).where(
                _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
                FinanceAccount.deleted_at.is_(None),
                FinanceAccount.classification == "asset",
                FinanceAccount.account_type.in_(CASH_ACCOUNT_TYPES),
                FinanceAccount.is_closed.is_(False),
                FinanceAccount.is_hidden.is_(False),
            )
        )
    ).all()
    total = 0
    for account in accounts:
        balance = account.available_balance
        if balance is None:
            balance = account.current_balance or 0
        total += balance
    return total


def _carried_balance(detail: FinanceLiabilityDetail) -> int | None:
    """The balance actually accruing interest, when the data can prove one.

    The provider's ``balance_subject_to_apr`` is authoritative. Without it, a
    statement that was not paid in full is the fallback proof. A card paid in
    full every month returns None and is never flagged, whatever its APR.
    """
    subject = sum(
        entry.get("balance_subject_to_apr") or 0 for entry in detail.aprs or []
    )
    if subject > 0:
        return subject
    statement = detail.last_statement_balance or 0
    paid = detail.last_payment_amount
    if statement > 0 and paid is not None and paid < statement:
        return statement - paid
    return None


async def _credit_cards(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    today: date,
) -> int:
    """The predefined credit checks: past due, minimum vs cash, APR, limit.

    All four read the account row and the provider's own liability detail
    (statement, minimum payment, due date, APRs). Silence is the default: an
    account with no detail row and no credit limit has nothing to check, and
    a card that is paid in full never trips the APR rule.
    """
    accounts = (
        await db.exec(
            select(FinanceAccount).where(
                _owner_clause(FinanceAccount.owner_user_id, owner_user_id),
                FinanceAccount.deleted_at.is_(None),
                FinanceAccount.classification == "liability",
                FinanceAccount.is_closed.is_(False),
                FinanceAccount.is_hidden.is_(False),
            )
        )
    ).all()
    if not accounts:
        return 0
    details = {
        row.account_id: row
        for row in (
            await db.exec(
                select(FinanceLiabilityDetail).where(
                    FinanceLiabilityDetail.account_id.in_(
                        [account.id for account in accounts]
                    )
                )
            )
        ).all()
    }
    cash = await _liquid_cash(db, owner_user_id)
    month = month_key(today).replace("-", "")

    created = 0
    for account in accounts:
        # A card near its limit needs only the account row.
        limit = account.credit_limit or 0
        balance = abs(account.current_balance or 0)
        if limit > 0 and balance > 0:
            utilization = balance / limit
            if utilization >= UTILIZATION_WARNING:
                pct = int(round(utilization * 100))
                if await create_insight_if_new(
                    db,
                    owner_user_id=store_owner,
                    insight_type="credit_utilization",
                    dedup_key=f"utilization:{account.id}:{month}",
                    severity=(
                        "critical" if utilization >= UTILIZATION_CRITICAL else "warning"
                    ),
                    title=f"{account.name} is at {pct}% of its limit",
                    body=(
                        f"{format_usd(balance)} of the {format_usd(limit)} limit "
                        f"on {account.name} is in use."
                    ),
                    detected_amount=balance,
                    related_account_id=account.id,
                ):
                    created += 1

        detail = details.get(account.id)
        if detail is None:
            continue

        if detail.is_overdue:
            due = detail.next_payment_due_date
            minimum = detail.minimum_payment_amount
            body = f"The institution reports {account.name} as past due."
            if minimum:
                body += f" The minimum payment is {format_usd(minimum)}."
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="card_overdue",
                dedup_key=f"card_overdue:{account.id}:{due.isoformat() if due else month}",
                severity="critical",
                title=f"{account.name} is past due",
                body=body,
                detected_amount=minimum,
                related_account_id=account.id,
            ):
                created += 1

        minimum = detail.minimum_payment_amount or 0
        due = detail.next_payment_due_date
        if (
            minimum > 0
            and due is not None
            and today <= due <= today + timedelta(days=MIN_PAYMENT_LOOKAHEAD_DAYS)
            and minimum > cash
        ):
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="min_payment_gap",
                dedup_key=f"min_gap:{account.id}:{due.isoformat()}",
                severity="critical",
                title=f"Minimum payment on {account.name} exceeds your cash",
                body=(
                    f"{format_usd(minimum)} is due {due} on {account.name}, but "
                    f"your cash accounts hold {format_usd(cash)} - short "
                    f"{format_usd(minimum - cash)}."
                ),
                detected_amount=minimum,
                related_account_id=account.id,
            ):
                created += 1

        apr = card_apr_bps(detail)
        carried = _carried_balance(detail)
        if (
            apr is not None
            and apr >= HIGH_APR_BPS
            and carried is not None
            and carried >= HIGH_APR_MIN_BALANCE
        ):
            monthly_interest = carried * apr // 10_000 // 12
            if await create_insight_if_new(
                db,
                owner_user_id=store_owner,
                insight_type="high_apr_carry",
                dedup_key=f"high_apr:{account.id}:{month}",
                severity="warning",
                title=(f"{account.name} is carrying a balance at {format_apr(apr)}"),
                body=(
                    f"About {format_usd(carried)} on {account.name} is accruing "
                    f"interest at {format_apr(apr)} - roughly "
                    f"{format_usd(monthly_interest)} a month."
                ),
                detected_amount=carried,
                related_account_id=account.id,
            ):
                created += 1
    return created


async def _cash_runway(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    today: date,
) -> int:
    """Scheduled bills walk the cash balance below zero inside the window.

    Reuses the same projection the Forecast surface renders, so the alert and
    the chart can never disagree about when the money runs out. An already
    negative balance is account state, not a forecast, and stays silent here.
    """
    from app.services.finance.finance_service import FinanceService

    projection = await FinanceService(db).project_balances(
        owner_user_id=owner_user_id, days=RUNWAY_DAYS, today=today
    )
    if projection.start_balance <= 0:
        # Negative is account state, not a forecast; zero is indistinguishable
        # from "no balance data yet", and a rule that cannot tell "broke" from
        # "unknown" must stay silent.
        return 0
    crossing = next((p for p in projection.points if p.balance < 0), None)
    if crossing is None:
        return 0
    if await create_insight_if_new(
        db,
        owner_user_id=store_owner,
        insight_type="cash_runway",
        # One alert per month: the exact crossing date shifts with every sync
        # and re-keying on it would raise the same alarm daily.
        dedup_key=f"cash_runway:{month_key(today).replace('-', '')}",
        severity="critical",
        title=f"Cash is projected to run out on {crossing.date}",
        body=(
            f"You have {format_usd(projection.start_balance)} in cash today; "
            f"after {crossing.name} ({format_usd(crossing.amount)}) on "
            f"{crossing.date} the projected balance is "
            f"-{format_usd(crossing.balance)}."
        ),
        detected_amount=crossing.balance,
        related_stream_id=crossing.stream_id,
    ):
        return 1
    return 0


async def _subscription_creep(
    db: AsyncSession,
    owner_user_id: int | None,
    store_owner: int,
    today: date,
) -> int:
    """The subscription total is drifting up even if no single one spiked.

    ``price_hike`` watches one stream; this watches the pile - a new service
    added on top of the old ones raises the total without any hike. Needs
    activity in every prior month of the window, so a fresh import or a
    brand-new subscriber never trips it on partial history.
    """
    sub_ids = list(
        (
            await db.exec(
                select(FinanceRecurringStream.id).where(
                    FinanceRecurringStream.owner_user_id == store_owner,
                    FinanceRecurringStream.deleted_at.is_(None),
                    FinanceRecurringStream.direction == "outflow",
                    FinanceRecurringStream.is_subscription.is_(True),
                    FinanceRecurringStream.is_muted.is_(False),
                    _not_paused_clause(today),
                )
            )
        ).all()
    )
    if not sub_ids:
        return 0
    txns = (
        await db.exec(
            select(FinanceTransaction).where(
                _owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
                FinanceTransaction.excluded_from_reports.is_(False),
                FinanceTransaction.amount < 0,
                FinanceTransaction.recurring_stream_id.in_(sub_ids),
                FinanceTransaction.date_
                >= _month_start_before(today, OVERSPEND_MIN_HISTORY),
                FinanceTransaction.account_id.in_(live_account_ids(owner_user_id)),
            )
        )
    ).all()
    by_month: dict[str, int] = {}
    for txn in txns:
        key = month_key(txn.date_)
        by_month[key] = by_month.get(key, 0) + abs(txn.amount)

    current_key = month_key(today)
    current = by_month.get(current_key, 0)
    prior = [
        by_month.get(month_key(_month_start_before(today, back)), 0)
        for back in range(1, OVERSPEND_MIN_HISTORY + 1)
    ]
    if current <= 0 or min(prior) <= 0:
        return 0
    typical = int(statistics.median(prior))
    if current <= typical * SUBSCRIPTION_CREEP_MULTIPLE:
        return 0
    if await create_insight_if_new(
        db,
        owner_user_id=store_owner,
        insight_type="subscription_creep",
        dedup_key=f"sub_creep:{current_key.replace('-', '')}",
        severity="warning",
        title=f"Subscriptions cost more this month ({format_usd(current)})",
        body=(
            f"Subscription charges total {format_usd(current)} so far this "
            f"month, against a typical {format_usd(typical)}."
        ),
        detected_amount=current,
    ):
        return 1
    return 0
