"""One detection pass over an owner's transactions."""

from __future__ import annotations

from datetime import date, timedelta
import statistics

from sqlalchemy.exc import IntegrityError
from sqlmodel import or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.recurring.cadence import (
    _SUBSCRIPTION_FREQUENCIES,
    MIN_OCCURRENCES,
    MIN_RHYTHM_RATIO,
    MIN_STREAM_AMOUNT,
    _canonical_days,
    _frequency_for,
    _has_gone_quiet,
    _payee_key,
    _rhythm_ratio,
    amount_profile,
    split_interleaved,
)
from app.services.finance.domains.detection.recurring.detect.purge import (
    _purge_stale_proposals,
)
from app.services.finance.domains.detection.recurring.detect.shared import (
    RecurringDetectionResult,
    _curated_members,
    candidate_filters,
)
from app.services.finance.domains.detection.recurring.detect.streams import (
    _upsert_stream,
)
from app.services.finance.domains.detection.recurring.resolve import (
    _is_the_bill_again,
    _resolve_payee_key,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceRecurringStream,
    FinanceTransaction,
)
from app.services.finance.utils import current_date
from app.services.shared.queries import owner_clause


async def detect_recurring(
    db: AsyncSession, *, owner_user_id: int | None, today: date | None = None
) -> RecurringDetectionResult:
    """Detect + upsert recurring streams for one owner. Idempotent.

    Streams/insights have a NOT-NULL owner, so a standalone (NULL-owner) install
    stores them under the ``0`` sentinel while scanning its NULL-owner rows.
    """
    result = RecurringDetectionResult()
    store_owner = 0 if owner_user_id is None else owner_user_id
    today = today or current_date()

    accounts = await queries.account_rows_where(
        db,
        [
            FinanceAccount.deleted_at.is_(None),
            owner_clause(FinanceAccount.owner_user_id, owner_user_id),
        ],
    )
    acct_ids = [a.id for a in accounts]
    if not acct_ids:
        return result
    # Money ARRIVING on a credit card is a payment toward it, never
    # household income - it came from another account of yours. Knowable
    # structurally, which matters because the matching outflow is often
    # not imported at all (81 AMEX credits here with no counterpart).
    # Spending charged TO the card is untouched: that is an ordinary bill.
    liability_accounts = {a.id for a in accounts if a.classification == "liability"}

    txns = await queries.transaction_rows_where(
        db,
        [
            *candidate_filters(owner_user_id),
            FinanceTransaction.account_id.in_(list(acct_ids)),
        ],
    )

    # Group by (account, direction, payee key) - see _payee_key: an
    # assigned merchant, else the normalized descriptor. Transactions the
    # user pinned by confirming their bill are skipped outright: they
    # already have an owner, and regrouping them is how an exclusion or a
    # split gets silently undone overnight.
    curated = await _curated_members(db, owner_user_id)
    # Confirmed bills by (account, direction), for the repropose guard:
    # a group that IS one of these must release, not duplicate. Streams
    # are STORED under ``store_owner`` (0 for a standalone install), so
    # the read matches that, not the raw argument - owner_clause's
    # IS NULL would find nothing a standalone install ever wrote.
    confirmed_by_slot: dict[tuple[int | None, str], list[FinanceRecurringStream]] = {}
    for bill in await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == store_owner,
            or_(
                FinanceRecurringStream.is_user_confirmed.is_(True),
                FinanceRecurringStream.source == "user",
            ),
        ],
    ):
        confirmed_by_slot.setdefault((bill.account_id, bill.direction), []).append(bill)
    groups: dict[tuple[int, str, str], list[FinanceTransaction]] = {}
    for txn in txns:
        # Already spoken for by a real bill - not detection's business.
        if txn.id in curated:
            continue
        key = _payee_key(txn)
        if not key:
            continue
        direction = "outflow" if txn.amount < 0 else "inflow"
        if direction == "inflow" and txn.account_id in liability_accounts:
            continue
        groups.setdefault((txn.account_id, direction, key), []).append(txn)

    # Display names for merchant-keyed groups, in one query - a stream
    # named "merchant:12" would be nonsense in Bills & Income.
    merchant_ids = {t.merchant_id for t in txns if t.merchant_id is not None}
    merchant_names = await queries.merchant_names_by_ids(db, merchant_ids)

    # Only discovered groups do any work. A curated stream - anything in
    # Bills or Income - and every transaction inside it were removed above
    # and are not represented here at all, so nothing below can rename,
    # re-key, merge, re-amount or prune one.
    work: list[tuple[int, str, str, list[FinanceTransaction]]] = [
        (account_id, direction, payee, members)
        for (account_id, direction, payee), members in groups.items()
    ]
    touched: set[int] = set()

    def _release(members: list[FinanceTransaction]) -> None:
        """A rejected group's members must not keep pointing at a row the
        purge below is about to hard-delete."""
        for member in members:
            if member.recurring_stream_id is not None:
                member.recurring_stream_id = None
                db.add(member)

    # One payee interleaving two subscriptions (Apple billing iCloud
    # and Music on one descriptor) either has no rhythm as a single
    # group or fakes a shorter cadence from the interleaved gaps -
    # see split_interleaved for the banding rule and its guardrails.
    work, unbanded = split_interleaved(work, today)
    _release(unbanded)

    for account_id, direction, payee, members in work:
        if len(members) < MIN_OCCURRENCES:
            _release(members)
            continue
        members.sort(key=lambda t: (t.date_, t.id or 0))
        gaps = [
            (members[i].date_ - members[i - 1].date_).days
            for i in range(1, len(members))
        ]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            _release(members)
            continue
        median_interval = statistics.median(gaps)
        matched = _frequency_for(median_interval)
        if matched is None:
            _release(members)
            continue  # no stable cadence -> not a recurring stream
        frequency = matched
        # A median can land on a cadence by coincidence. Require that the
        # gaps themselves mostly agree, or a handful of unrelated visits
        # to the same shop becomes a subscription.
        canonical = _canonical_days(frequency)
        rhythm = _rhythm_ratio(gaps, canonical) if canonical else 0.0
        if rhythm < MIN_RHYTHM_RATIO:
            _release(members)
            continue
        # Real cadence, but it stopped. Releasing lets the prune pass
        # retire it rather than leaving a dead bill in the rollup and the
        # forecast for years.
        if _has_gone_quiet(members[-1].date_, canonical, today):
            _release(members)
            continue

        median_amount, variable = amount_profile(members, today=today)
        if median_amount < MIN_STREAM_AMOUNT:
            _release(members)
            continue
        if _is_the_bill_again(
            confirmed_by_slot.get((account_id, direction), []),
            payee,
            frequency,
            median_amount,
        ):
            _release(members)
            continue
        last = members[-1]
        is_subscription = (
            direction == "outflow"
            and frequency in _SUBSCRIPTION_FREQUENCIES
            and not variable
        )
        # Fit first, evidence second. The old formula was
        # 50 + 10*occurrences + 20 if fixed, so MORE random visits raised
        # confidence - Stewart's scored 90.
        confidence = int(
            round(
                40
                + 30 * rhythm
                + 10 * min(len(members) / 6, 1.0)
                + (0 if variable else 20)
            )
        )
        merchant_id = last.merchant_id
        # A confirmed bill already on this key owns its own membership, so
        # an unpinned group of the same payee is a DIFFERENT bill and gets
        # its own key rather than being merged into someone's decision.
        resolved_key, _target = await _resolve_payee_key(
            db,
            owner_user_id=store_owner,
            account_id=account_id,
            direction=direction,
            base=payee,
            member_ids={m.id for m in members if m.id is not None},
        )
        try:
            async with db.begin_nested():
                stream = await _upsert_stream(
                    db,
                    owner_user_id=store_owner,
                    account_id=account_id,
                    direction=direction,
                    payee=resolved_key,
                    merchant_id=merchant_id,
                    name=(
                        merchant_names.get(merchant_id)
                        if merchant_id is not None
                        else None
                    )
                    or last.merchant_name
                    or last.name
                    or payee,
                    frequency=frequency,
                    average_amount=median_amount,
                    last_amount=abs(last.amount),
                    first_date=members[0].date_,
                    last_date=last.date_,
                    next_expected_date=(
                        last.date_ + timedelta(days=int(median_interval))
                        if median_interval is not None
                        else None
                    ),
                    occurrence_count=len(members),
                    variable=variable,
                    is_subscription=is_subscription,
                    confidence=confidence,
                    currency=last.currency,
                )
                touched.add(stream.id)
                for member in members:
                    member.recurring_stream_id = stream.id
                    db.add(member)
                await db.flush()
        except IntegrityError:
            logger.debug("recurring upsert skipped (race)")
            continue
        result.detected += 1

    result.pruned = await _purge_stale_proposals(db, store_owner, touched)
    return result
