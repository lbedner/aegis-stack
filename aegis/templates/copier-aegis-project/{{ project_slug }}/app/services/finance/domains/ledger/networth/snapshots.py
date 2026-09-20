"""Rebuilding the net-worth curve from balances and positions.

One pass walks every account's balance points and every holding's
valuation, then writes the daily snapshots the chart reads back.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import queries
from app.services.finance.models import (
    FinanceAccount,
    FinanceBalanceSnapshot,
    FinanceNetWorthSnapshot,
    FinanceValuation,
)
from app.services.finance.utils import DEFAULT_CURRENCY

_DEFAULT_WINDOW_DAYS = 35


def _today() -> date:
    return datetime.now(UTC).date()


def _balance_points(
    account: FinanceAccount,
    valuations: list[FinanceValuation],
    activity: list[tuple[date, int]] | None = None,
    investment: list[tuple[date, int, str]] | None = None,
) -> list[tuple[date, int, str]]:
    """Ordered ``(date, value, source)`` points defining an account's balance.

    Pure: ``valuations`` are the account's rows (ascending by date), preloaded
    in bulk by the caller so recompute issues one query for all accounts rather
    than one per account. Manual accounts follow their valuation series; an
    account with only a ``current_balance`` contributes a single point at
    ``balance_as_of`` (or today). Between points the value is carried forward.
    """
    if valuations:
        return [(v.as_of_date, v.value, "manual") for v in valuations]
    # "Authoritative" is subtle: accounts are CREATED with
    # ``current_balance=0``, so a bare zero only counts as a real balance
    # when ``balance_as_of`` says a write actually happened. Trusting the
    # zero is what made every CSV-imported account contribute $0 to the
    # series while the accounts page showed its true register balance -
    # the chart and the headline number disagreed by design.
    authoritative = account.current_balance is not None and (
        account.current_balance != 0 or account.balance_as_of is not None
    )
    if authoritative:
        as_of = (
            account.balance_as_of.date()
            if account.balance_as_of is not None
            else _today()
        )
        source = "manual" if account.is_manual else "sync"
        anchor = (as_of, account.current_balance, source)
        # A reconstructed history feeds the days BEFORE the synced balance;
        # the synced figure itself always wins on its own date, since it is
        # measured rather than derived.
        if investment:
            return [p for p in investment if p[0] < as_of] + [anchor]
        return [anchor]
    # Fall back to the running register balance, the same figure the
    # accounts page falls back to. Opening balance is assumed zero, so
    # this tracks CHANGE faithfully even when the absolute level is only
    # as good as the imported history.
    if activity:
        running = 0
        points: list[tuple[date, int, str]] = []
        for day, delta in activity:
            running += delta
            # "computed" is the existing vocabulary for a derived balance
            # (the source check constraint allows sync/provider/computed/
            # carried_forward/manual) - a register sum is precisely that,
            # so this needs no migration.
            points.append((day, running, "computed"))
        return points
    return []


def _investment_points(
    account: FinanceAccount,
    holdings: list[tuple[int, int]],
    trades: list[tuple[date, int, int, int, int]],
) -> list[tuple[date, int, str]]:
    """Value history for a single-security investment account, from trades.

    A brokerage sync gives ONE point-in-time balance, so a year of chart
    shows a flat nothing and then a cliff on the day it synced. The trades
    carry unit prices at their own dates, and quantity is exactly
    recoverable by undoing each trade backwards from today's holding - so
    value at trade date ``t`` is ``quantity_after(t) x price(t)``.

    Deliberately limited to accounts holding exactly ONE security. With
    several, the value on a given day needs every security's price on that
    day, and a trade only prices the one it touched; guessing the rest
    would look precise and be fiction.

    ``trades`` is ``(date, security_id, quantity_e8, price, price_scale)``
    ascending, already filtered to priced rows.
    """
    if len(holdings) != 1 or not trades:
        return []
    security_id, current_quantity = holdings[0]
    priced = [t for t in trades if t[1] == security_id and (t[3] or 0) > 0]
    if not priced:
        return []

    # Walk backwards from today's holding, undoing each trade's quantity.
    quantity_after: dict[date, int] = {}
    running = current_quantity
    for trade_date, _sec, quantity_e8, _price, _scale in reversed(priced):
        quantity_after[trade_date] = running
        running -= quantity_e8 or 0

    from app.services.finance.domains.investments.securities import market_value_cents

    points: list[tuple[date, int, str]] = []
    for trade_date, _sec, _quantity_e8, price, price_scale in priced:
        quantity = quantity_after.get(trade_date, 0)
        if quantity <= 0:
            continue
        points.append(
            (trade_date, market_value_cents(quantity, price, price_scale), "computed")
        )
    return points


def _apply_balance_snapshot(
    db: AsyncSession,
    existing: dict[tuple[int, date], FinanceBalanceSnapshot],
    *,
    account: FinanceAccount,
    balance_date: date,
    balance: int,
    source: str,
    is_estimated: bool,
    owner_user_id: int | None,
) -> None:
    """Upsert a balance snapshot against the preloaded ``existing`` map.

    No query: the caller loads every snapshot in the window up front, so this
    is an in-memory dict lookup. New rows are registered in ``existing`` so a
    repeat within the same run updates in place rather than double-inserting.
    """
    prior = existing.get((account.id, balance_date))
    if prior is not None:
        prior.balance = balance
        prior.source = source
        prior.is_estimated = is_estimated
        db.add(prior)
        return
    snapshot = FinanceBalanceSnapshot(
        account_id=account.id,
        owner_user_id=owner_user_id
        if owner_user_id is not None
        else account.owner_user_id,
        balance_date=balance_date,
        balance=balance,
        currency=account.currency,
        source=source,
        is_estimated=is_estimated,
    )
    db.add(snapshot)
    existing[(account.id, balance_date)] = snapshot


def _apply_net_worth_snapshot(
    db: AsyncSession,
    existing: dict[date, FinanceNetWorthSnapshot],
    *,
    owner_user_id: int | None,
    as_of_date: date,
    total_assets: int,
    total_liabilities: int,
) -> None:
    """Upsert a net-worth snapshot against the preloaded ``existing`` map."""
    net_worth = total_assets - total_liabilities
    prior = existing.get(as_of_date)
    if prior is not None:
        prior.total_assets_amount = total_assets
        prior.total_liabilities_amount = total_liabilities
        prior.net_worth_amount = net_worth
        db.add(prior)
        return
    snapshot = FinanceNetWorthSnapshot(
        owner_user_id=owner_user_id,
        as_of_date=as_of_date,
        total_assets_amount=total_assets,
        total_liabilities_amount=total_liabilities,
        net_worth_amount=net_worth,
        currency=DEFAULT_CURRENCY,
    )
    db.add(snapshot)
    existing[as_of_date] = snapshot


async def recompute_snapshots(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    start_date: date | None = None,
) -> int:
    """Recompute balance + net-worth snapshots over the recent window.

    Returns the number of net-worth days written. Idempotent: repeat runs
    upsert the same rows. Writes but does not commit (caller owns the txn).
    """
    today = _today()
    window_start = start_date or (today - timedelta(days=_DEFAULT_WINDOW_DAYS - 1))
    if window_start > today:
        return 0
    days = [
        window_start + timedelta(days=i) for i in range((today - window_start).days + 1)
    ]

    # 1) Accounts in scope.
    accounts = await queries.live_accounts_for_owner(db, owner_user_id=owner_user_id)
    if not accounts:
        return 0
    account_ids = [a.id for a in accounts]

    # 2) All valuations for those accounts in one query, grouped in memory
    #    (was one query per account inside the loop).
    valuations_by_account: dict[int, list[FinanceValuation]] = defaultdict(list)
    valuation_rows = await queries.valuations_for_accounts(db, account_ids)
    for valuation in valuation_rows:
        valuations_by_account[valuation.account_id].append(valuation)

    # 2b) Daily transaction deltas per account, for the register fallback.
    #     One grouped query, ascending, so the running total is a scan.
    activity_by_account: dict[int, list[tuple[date, int]]] = defaultdict(list)
    for account_id, txn_date, delta in await queries.daily_register_deltas(
        db, account_ids
    ):
        activity_by_account[account_id].append((txn_date, delta))

    # 2c) Holdings + priced trades, for reconstructing an investment
    #     account's value on the days before its single synced balance.
    holdings_by_account: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for security_id, account_id, quantity_e8 in await queries.holding_quantities(
        db, account_ids
    ):
        holdings_by_account[account_id].append((security_id, int(quantity_e8 or 0)))

    trades_by_account: dict[int, list[tuple[date, int, int, int, int]]] = defaultdict(
        list
    )
    for (
        account_id,
        trade_date,
        security_id,
        quantity_e8,
        price,
        price_scale,
    ) in await queries.priced_trade_rows(db, account_ids):
        trades_by_account[account_id].append(
            (
                trade_date,
                security_id,
                int(quantity_e8 or 0),
                int(price or 0),
                int(price_scale or 0),
            )
        )

    # 3) Every existing balance snapshot in the window, keyed for in-memory
    #    upsert (was one existence query per account per day).
    existing_balance: dict[tuple[int, date], FinanceBalanceSnapshot] = {}
    balance_rows = await queries.balance_snapshots_between(
        db, account_ids, start=window_start, end=today
    )
    for snapshot in balance_rows:
        existing_balance[(snapshot.account_id, snapshot.balance_date)] = snapshot

    per_day: dict[date, list[int]] = defaultdict(lambda: [0, 0])  # [assets, liab]

    for account in accounts:
        points = _balance_points(
            account,
            valuations_by_account.get(account.id, []),
            activity_by_account.get(account.id),
            _investment_points(
                account,
                holdings_by_account.get(account.id, []),
                trades_by_account.get(account.id, []),
            ),
        )
        if not points:
            continue
        index = 0
        current: tuple[date, int, str] | None = None
        for day in days:
            while index < len(points) and points[index][0] <= day:
                current = points[index]
                index += 1
            if current is None:
                # Before the first known point. Carrying the EARLIEST value
                # backwards is estimated, but it is the least-wrong
                # estimate available: treating the account as $0 until its
                # first sync drew a cliff that read as a sudden windfall.
                # Flagged estimated so the row says so.
                first_date, first_value, _first_source = points[0]
                _apply_balance_snapshot(
                    db,
                    existing_balance,
                    account=account,
                    balance_date=day,
                    balance=first_value,
                    source="carried_forward",
                    is_estimated=True,
                    owner_user_id=owner_user_id,
                )
                if account.classification == "asset":
                    per_day[day][0] += first_value
                elif account.classification == "liability":
                    per_day[day][1] += abs(first_value)
                continue
            point_date, value, native_source = current
            is_exact = point_date == day
            _apply_balance_snapshot(
                db,
                existing_balance,
                account=account,
                balance_date=day,
                balance=value,
                source=native_source if is_exact else "carried_forward",
                is_estimated=not is_exact,
                owner_user_id=owner_user_id,
            )
            if account.classification == "asset":
                per_day[day][0] += value
            elif account.classification == "liability":
                # ``net_worth = assets - liabilities``, so this column is a
                # magnitude OWED, always positive. A register-derived card
                # balance is negative (spending), and adding it raw flipped
                # the subtraction into an addition - net worth came out too
                # high by exactly twice the debt.
                per_day[day][1] += abs(value)

    # 4) Existing net-worth snapshots for the window in one query (was one
    #    existence query per day).
    existing_net_worth: dict[date, FinanceNetWorthSnapshot] = {}
    for snapshot in await queries.net_worth_snapshots_between(
        db,
        owner_user_id=owner_user_id,
        start=window_start,
        end=today,
        currency=DEFAULT_CURRENCY,
    ):
        existing_net_worth[snapshot.as_of_date] = snapshot

    written = 0
    for day, (assets, liabilities) in per_day.items():
        _apply_net_worth_snapshot(
            db,
            existing_net_worth,
            owner_user_id=owner_user_id,
            as_of_date=day,
            total_assets=assets,
            total_liabilities=liabilities,
        )
        written += 1
    await db.flush()
    return written
