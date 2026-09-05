"""Planning the demo ledger: pure data, no database.

The same anchor and month count always yield the same entries, which is
what makes screenshots and docs reproducible, and what lets the shape of
the dataset be tested without a session. ``demo_seed`` writes what this
plans; ``demo_household`` holds the numbers it plans from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import random

from app.services.finance.seeds.demo_household import (
    _BIWEEKLY_PAY,
    _CARD_AUTOPAY,
    _CARD_INTEREST_NAME,
    _CARD_MERCHANTS,
    _CARD_PAYMENT_IN_NAME,
    _CARD_PAYMENT_OUT_NAME,
    _FIXED_CHECKING,
    _INVEST_IN_NAME,
    _INVEST_OUT_NAME,
    _NO_PAYEE,
    _ONE_OFFS,
    _PRICE_HIKE,
    _QUARTERLY,
    _SEMI_MONTHLY_PAY,
    _SUBSCRIPTIONS,
    _TRANSFER_IN_NAME,
    _TRANSFER_OUT_NAME,
    _UNCATEGORIZED,
)

_SEED = 20260838
_DEFAULT_MONTHS = 8


@dataclass(frozen=True)
class PlannedSplit:
    """One part of a split transaction."""

    amount: int
    category: str
    memo: str


@dataclass(frozen=True)
class PlannedTransaction:
    """A single ledger entry, planned before anything touches the database."""

    account_key: str
    txn_date: date
    amount: int
    name: str
    category: str | None = None
    memo: str | None = None
    splits: tuple[PlannedSplit, ...] = ()
    # False for a row the bank named unusably: written with no merchant,
    # which is what the No payee queue exists to fix.
    payee: bool = True


def _month_starts(anchor: date, months: int) -> list[date]:
    """The first of each month in the window, oldest first."""
    starts: list[date] = []
    year, month = anchor.year, anchor.month
    for _ in range(max(months, 1)):
        starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(starts))


def _day_in_month(month_start: date, day: int) -> date:
    """``day`` of ``month_start``'s month, clamped to the month's length."""
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return month_start.replace(day=min(day, last_day))


def _jitter(rng: random.Random, amount: int, pct: float) -> int:
    """``amount`` moved by up to +/-``pct``, keeping its sign."""
    span = int(abs(amount) * pct)
    return amount + rng.randint(-span, span) if span else amount


def build_demo_ledger(
    *, anchor: date, months: int = _DEFAULT_MONTHS
) -> tuple[PlannedTransaction, ...]:
    """Plan the whole ledger as pure data, oldest entry first.

    Pure and seeded: the same ``anchor``/``months`` always yield the same
    entries, which is what makes screenshots and docs reproducible. Nothing
    here touches the database, so the shape of the dataset is testable on its
    own.
    """
    rng = random.Random(_SEED)
    entries: list[PlannedTransaction] = []
    # The card is paid in arrears: each month's spend is paid the next month,
    # minus what is carried. Carrying is deliberate - a card cleared every
    # month has no payoff story and nothing for the credit rules to notice.
    unpaid_card = 0
    carried = 0
    split_used = False
    target_split_left = 1

    months_list = _month_starts(anchor, months)

    # -- Income: one biweekly earner, one semi-monthly ------------------ #
    # Biweekly is stepped in days rather than months, which is the whole
    # point: the paycheck walks through the month instead of landing on
    # the same date every time.
    biweekly_name, biweekly_amount = _BIWEEKLY_PAY
    pay_day = months_list[0]
    while pay_day <= anchor:
        entries.append(
            PlannedTransaction(
                "checking",
                pay_day,
                _jitter(rng, biweekly_amount, 0.015),
                biweekly_name,
                "INCOME",
            )
        )
        pay_day = pay_day + timedelta(days=14)

    semi_name, semi_amount = _SEMI_MONTHLY_PAY

    for month_index, month_start in enumerate(months_list):
        months_back = len(months_list) - 1 - month_index

        # The 15th and the 30th, not the 28th: alternating 13/18-day gaps
        # read as irregular and never became a stream at all, so half the
        # household's income was missing from the forecast.
        for day in (15, 30):
            entries.append(
                PlannedTransaction(
                    "checking",
                    _day_in_month(month_start, day),
                    _jitter(rng, semi_amount, 0.01),
                    semi_name,
                    "INCOME",
                )
            )

        # -- Fixed bills ------------------------------------------------ #
        for day, payee, amount, category in _FIXED_CHECKING:
            entries.append(
                PlannedTransaction(
                    "checking",
                    _day_in_month(month_start, day),
                    amount,
                    payee,
                    category,
                )
            )
        entries.append(
            PlannedTransaction(
                "checking",
                _day_in_month(month_start, 8),
                _jitter(rng, -13_400, 0.30),
                "Pacific Gas & Electric",
                "RENT_AND_UTILITIES",
            )
        )

        # -- Card spend ------------------------------------------------- #
        card_entries: list[PlannedTransaction] = []

        hike_payee, hike_amount, hike_months_back = _PRICE_HIKE
        for day, payee, amount, category in _SUBSCRIPTIONS:
            if payee == hike_payee and months_back <= hike_months_back:
                amount = hike_amount
            card_entries.append(
                PlannedTransaction(
                    "card", _day_in_month(month_start, day), amount, payee, category
                )
            )

        for payee, category, (low, high), typical, spread in _CARD_MERCHANTS:
            for index in range(rng.randint(low, high)):
                amount = _jitter(rng, typical, spread)
                day = _day_in_month(
                    month_start, 1 + (index * 29) // max(high, 1) + rng.randint(0, 2)
                )
                splits: tuple[PlannedSplit, ...] = ()
                # One split already carved, and one Target run left alone:
                # the app's own pitch is that a mixed charge is worth
                # splitting, which needs an unsplit one to point at.
                if not split_used and payee == "Whole Foods Market" and index == 1:
                    household = int(abs(amount) * 0.30)
                    splits = (
                        PlannedSplit(
                            -(abs(amount) - household), "FOOD_AND_DRINK", "Groceries"
                        ),
                        PlannedSplit(-household, "GENERAL_MERCHANDISE", "Household"),
                    )
                    split_used = True
                elif payee == "Target" and target_split_left and months_back <= 1:
                    target_split_left = 0
                    amount = -14_237
                card_entries.append(
                    PlannedTransaction(
                        "card", day, amount, payee, category, splits=splits
                    )
                )

        month_card_spend = sum(abs(e.amount) for e in card_entries)
        entries.extend(card_entries)

        # -- Interest on what is carried -------------------------------- #
        if carried > 0:
            interest = max(int(carried * 0.0199), 100)
            entries.append(
                PlannedTransaction(
                    "card",
                    _day_in_month(month_start, 24),
                    -interest,
                    _CARD_INTEREST_NAME,
                    "BANK_FEES",
                )
            )
            month_card_spend += interest

        # -- Card payment: most of last month's balance, not all of it -- #
        if unpaid_card:
            pay_date = _day_in_month(month_start, 25)
            paid = min(_CARD_AUTOPAY, unpaid_card)
            carried = unpaid_card - paid
            entries.append(
                PlannedTransaction(
                    "checking",
                    pay_date,
                    -paid,
                    _CARD_PAYMENT_OUT_NAME,
                    "TRANSFER_OUT",
                )
            )
            entries.append(
                PlannedTransaction(
                    "card",
                    pay_date,
                    paid,
                    _CARD_PAYMENT_IN_NAME,
                    "TRANSFER_IN",
                )
            )
        unpaid_card = month_card_spend + carried

        # -- Where the surplus goes (both auto-pair) -------------------- #
        # Out of cash, not into it. Savings and checking are both "cash"
        # to the forecast, so sweeping a surplus into savings leaves the
        # same buffer that made the projection undippable - the money has
        # to leave cash entirely to look like a household that invests.
        transfer_date = _day_in_month(month_start, 20)
        entries.append(
            PlannedTransaction(
                "checking",
                transfer_date,
                -5_000,
                _TRANSFER_OUT_NAME,
                "TRANSFER_OUT",
            )
        )
        entries.append(
            PlannedTransaction(
                "savings", transfer_date, 5_000, _TRANSFER_IN_NAME, "TRANSFER_IN"
            )
        )
        invest_date = _day_in_month(month_start, 16)
        entries.append(
            PlannedTransaction(
                "checking",
                invest_date,
                -50_000,
                _INVEST_OUT_NAME,
                "TRANSFER_OUT",
            )
        )
        entries.append(
            PlannedTransaction(
                "brokerage", invest_date, 50_000, _INVEST_IN_NAME, "TRANSFER_IN"
            )
        )

    # -- One-offs and the half-yearly bill ------------------------------ #
    for months_back, day, account_key, payee, amount, category in (
        *_ONE_OFFS,
        *_QUARTERLY,
    ):
        index = len(months_list) - 1 - months_back
        if index < 0:
            continue
        entries.append(
            PlannedTransaction(
                account_key,
                _day_in_month(months_list[index], day),
                amount,
                payee,
                category,
            )
        )

    for months_back, day, name, amount in _UNCATEGORIZED:
        index = len(months_list) - 1 - months_back
        if index >= 0:
            entries.append(
                PlannedTransaction(
                    "card", _day_in_month(months_list[index], day), amount, name
                )
            )
    for months_back, day, name, amount, category in _NO_PAYEE:
        index = len(months_list) - 1 - months_back
        if index >= 0:
            entries.append(
                PlannedTransaction(
                    "card",
                    _day_in_month(months_list[index], day),
                    amount,
                    name,
                    category,
                    payee=False,
                )
            )

    in_window = [e for e in entries if e.txn_date <= anchor]
    in_window.sort(key=lambda e: (e.txn_date, e.account_key, e.name))
    return tuple(in_window)
