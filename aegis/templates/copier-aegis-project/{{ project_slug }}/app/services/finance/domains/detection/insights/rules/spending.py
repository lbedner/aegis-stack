"""Rules about money going out faster than it used to.

price_hike, fee_charged, overspend_category, large_transaction and
subscription_creep - each comparing a charge against a norm the
account or the stream set for itself.
"""

from __future__ import annotations

from datetime import date, timedelta
import statistics

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import queries
from app.services.finance.domains.detection.insights.commitments import (
    not_paused_clause,
)
from app.services.finance.domains.detection.insights.formatting import (
    days_in_month,
    format_usd,
    month_key,
    month_start_before,
    pace_day,
)
from app.services.finance.domains.detection.insights.rules.shared import (
    _FEE_PFC,
    _FEE_RE,
    LARGE_TXN_BASELINE_DAYS,
    LARGE_TXN_CRITICAL_MULTIPLE,
    LARGE_TXN_FLOOR,
    LARGE_TXN_MIN_BASELINE,
    LARGE_TXN_MULTIPLE,
    LARGE_TXN_THIN_FLOOR,
    LARGE_TXN_WINDOW_DAYS,
    OVERSPEND_MIN_BASELINE,
    OVERSPEND_MIN_ELAPSED,
    OVERSPEND_MIN_HISTORY,
    OVERSPEND_MULTIPLE,
    PRICE_HIKE_THRESHOLD,
    SUBSCRIPTION_CREEP_MULTIPLE,
    create_insight_if_new,
    live_account_ids,
    monthly_category_spend,
)
from app.services.finance.models import (
    FinanceRecurringStream,
    FinanceTransaction,
)
from app.services.shared.queries import owner_clause


async def _price_hikes(db: AsyncSession, store_owner: int, today: date) -> int:
    """A fixed-amount recurring stream now costs more than its average."""
    streams = await queries.stream_rows_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == store_owner,
            FinanceRecurringStream.deleted_at.is_(None),
            FinanceRecurringStream.status == "mature",
            FinanceRecurringStream.is_muted.is_(False),
            not_paused_clause(today),
            FinanceRecurringStream.amount_is_variable.is_(False),
            FinanceRecurringStream.direction == "outflow",
        ],
    )
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
        owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.amount < 0,
        FinanceTransaction.account_id.in_(live_accounts),
    ]
    if floor is not None:
        filters.append(FinanceTransaction.date_ >= floor)
    txns = await queries.transaction_rows_where(db, filters)
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
    month_days = days_in_month(today)
    elapsed = 1.0 if through is None else through / month_days

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
    rows = await queries.transaction_rows_where(
        db,
        [
            owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.is_transfer.is_(False),
            FinanceTransaction.recurring_stream_id.is_(None),
            FinanceTransaction.amount < 0,
            FinanceTransaction.date_ >= today - timedelta(days=LARGE_TXN_BASELINE_DAYS),
            FinanceTransaction.account_id.in_(live_accounts),
        ],
    )

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
    sub_ids = await queries.stream_ids_where(
        db,
        [
            FinanceRecurringStream.owner_user_id == store_owner,
            FinanceRecurringStream.deleted_at.is_(None),
            FinanceRecurringStream.direction == "outflow",
            FinanceRecurringStream.is_subscription.is_(True),
            FinanceRecurringStream.is_muted.is_(False),
            not_paused_clause(today),
        ],
    )
    if not sub_ids:
        return 0
    txns = await queries.transaction_rows_where(
        db,
        [
            owner_clause(FinanceTransaction.owner_user_id, owner_user_id),
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.dedup_status != "duplicate",
            FinanceTransaction.excluded_from_reports.is_(False),
            FinanceTransaction.amount < 0,
            FinanceTransaction.recurring_stream_id.in_(sub_ids),
            FinanceTransaction.date_
            >= month_start_before(today, OVERSPEND_MIN_HISTORY),
            FinanceTransaction.account_id.in_(live_account_ids(owner_user_id)),
        ],
    )
    by_month: dict[str, int] = {}
    for txn in txns:
        key = month_key(txn.date_)
        by_month[key] = by_month.get(key, 0) + abs(txn.amount)

    current_key = month_key(today)
    current = by_month.get(current_key, 0)
    prior = [
        by_month.get(month_key(month_start_before(today, back)), 0)
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
