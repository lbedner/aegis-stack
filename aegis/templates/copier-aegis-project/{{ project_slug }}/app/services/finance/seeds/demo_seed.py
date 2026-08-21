"""Deterministic demo dataset for the finance service.

Turns an empty install into one that looks like a working app: a handful of
accounts, months of believable activity, detected recurring streams and
transfers, investment positions, and a net-worth curve. Built for dashboard
development, docs screenshots, and a first-run impression that isn't a wall of
empty states.

Everything goes through the real service layer (``FinanceService``,
``imports``, the ``detection`` finders, ``networth``) rather
than raw inserts, so the seeded data exercises the same code paths a real
import does - and stays correct when those paths change.

Two properties make it safe to re-run:

- **Marked.** Seeded accounts carry ``metadata["demo_seed"]``, and everything
  else hangs off them. Identification never depends on names, so ``reset``
  deletes exactly what this module wrote and can't touch real data that
  happens to share a payee or account name.
- **Deterministic.** The ledger is planned by a pure function off a fixed
  seed, so the same anchor date always produces the same dataset. The
  calendar window is anchored to today, so the dashboard shows a current
  curve; the amounts, payees, and cadences do not drift between runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import random

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import imports
from app.services.finance.domains.detection import (
    detect_recurring,
    detect_transfers,
    generate_insights,
)
from app.services.finance.domains.investments.securities import market_value_cents
from app.services.finance.domains.ledger import networth
from app.services.finance.models import (
    FinanceAccount,
    FinanceBalanceSnapshot,
    FinanceHolding,
    FinanceImportBatch,
    FinanceImportBatchRow,
    FinanceLiabilityDetail,
    FinanceNetWorthSnapshot,
    FinanceRecurringStream,
    FinanceTrade,
    FinanceTransaction,
    FinanceTransactionSplit,
    FinanceTransactionTag,
    FinanceTransfer,
    FinanceValuation,
)
from app.services.finance.service import FinanceService

# Bumping this re-marks future seeds without invalidating older ones.
DEMO_MARKER_KEY = "demo_seed"
DEMO_MARKER_VALUE = 1

_SEED = 20260838
_DEFAULT_MONTHS = 8
# The recent slice that arrives as a file import rather than direct writes.
_IMPORT_WINDOW_DAYS = 30
_QUANTITY_SCALE = 10**8


class DemoAccountSpec(BaseModel):
    """One seeded account. ``key`` is the ledger's stable handle for it."""

    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    account_type: str
    classification: str
    opening_balance: int = 0


DEMO_ACCOUNTS: tuple[DemoAccountSpec, ...] = (
    DemoAccountSpec(
        key="checking",
        name="Chase Total Checking",
        account_type="checking",
        classification="asset",
        opening_balance=482_355,
    ),
    DemoAccountSpec(
        key="savings",
        name="Ally Online Savings",
        account_type="savings",
        classification="asset",
        opening_balance=1_845_000,
    ),
    DemoAccountSpec(
        key="card",
        name="Amex Blue Cash Preferred",
        account_type="credit_card",
        classification="liability",
    ),
    DemoAccountSpec(
        key="home",
        name="Primary Residence",
        account_type="property",
        classification="asset",
        opening_balance=52_500_000,
    ),
    DemoAccountSpec(
        key="brokerage",
        name="Fidelity Brokerage",
        account_type="brokerage",
        classification="asset",
    ),
    DemoAccountSpec(
        key="mortgage",
        name="Mortgage",
        account_type="loan",
        classification="liability",
        opening_balance=31_842_000,
    ),
)
DEMO_ACCOUNT_NAMES: tuple[str, ...] = tuple(a.name for a in DEMO_ACCOUNTS)

# Positions held in the brokerage account: (ticker, name, unit price in cents).
DEMO_SECURITIES: tuple[tuple[str, str, int], ...] = (
    ("VTI", "Vanguard Total Stock Market ETF", 29_142),
    ("VXUS", "Vanguard Total International Stock ETF", 6_488),
    ("BND", "Vanguard Total Bond Market ETF", 7_326),
)

# Monthly fixed bills on the checking account: (day, payee, amount, category).
_FIXED_CHECKING: tuple[tuple[int, str, int, str], ...] = (
    (1, "Mortgage Payment", -218_400, "LOAN_PAYMENTS"),
    (12, "Comcast Xfinity", -8_999, "RENT_AND_UTILITIES"),
)
# Monthly subscriptions on the card: (day, payee, amount, category).
_SUBSCRIPTIONS: tuple[tuple[int, str, int, str], ...] = (
    (3, "Apple iCloud+", -299, "ENTERTAINMENT"),
    (6, "Netflix", -1_549, "ENTERTAINMENT"),
    (11, "Spotify", -1_199, "ENTERTAINMENT"),
)
_GROCERS: tuple[str, ...] = ("Whole Foods Market", "Trader Joe's")

_TRANSFER_OUT_NAME = "Transfer to Ally Online Savings"
_TRANSFER_IN_NAME = "Transfer from Chase Total Checking"
_CARD_PAYMENT_OUT_NAME = "Amex Autopay Payment"
_CARD_PAYMENT_IN_NAME = "Payment Received - Thank You"
_PAYROLL_NAME = "Payroll Direct Deposit"


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


class DemoSeedResult(BaseModel):
    """What one seed run wrote (all zero when ``skipped``)."""

    accounts: int = 0
    transactions: int = 0
    imported_rows: int = 0
    splits: int = 0
    transfers: int = 0
    recurring: int = 0
    valuations: int = 0
    trades: int = 0
    net_worth_days: int = 0
    skipped: bool = False
    reset: bool = False


def _today() -> date:
    return datetime.now(UTC).date()


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
    # The card is paid in arrears: each month's spend is paid the next month.
    unpaid_card = 0
    split_used = False

    for month_start in _month_starts(anchor, months):
        # -- Income: semi-monthly payroll ------------------------------- #
        for day in (1, 15):
            entries.append(
                PlannedTransaction(
                    "checking",
                    _day_in_month(month_start, day),
                    _jitter(rng, 419_500, 0.02),
                    _PAYROLL_NAME,
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
        month_card_spend = 0
        card_entries: list[PlannedTransaction] = []

        for day, payee, amount, category in _SUBSCRIPTIONS:
            card_entries.append(
                PlannedTransaction(
                    "card", _day_in_month(month_start, day), amount, payee, category
                )
            )

        for index in range(rng.randint(4, 6)):
            grocer = _GROCERS[index % len(_GROCERS)]
            amount = _jitter(rng, -9_450, 0.45)
            day = _day_in_month(month_start, 2 + index * 5 + rng.randint(0, 2))
            splits: tuple[PlannedSplit, ...] = ()
            # One split transaction: a grocery run with household goods on it.
            if not split_used and index == 1:
                household = int(abs(amount) * 0.30)
                splits = (
                    PlannedSplit(
                        -(abs(amount) - household), "FOOD_AND_DRINK", "Groceries"
                    ),
                    PlannedSplit(-household, "GENERAL_MERCHANDISE", "Household"),
                )
                split_used = True
            card_entries.append(
                PlannedTransaction(
                    "card", day, amount, grocer, "FOOD_AND_DRINK", splits=splits
                )
            )

        for index in range(rng.randint(6, 9)):
            card_entries.append(
                PlannedTransaction(
                    "card",
                    _day_in_month(month_start, 1 + index * 3 + rng.randint(0, 2)),
                    _jitter(rng, -685, 0.35),
                    "Starbucks",
                    "FOOD_AND_DRINK",
                )
            )

        for index in range(rng.randint(2, 3)):
            card_entries.append(
                PlannedTransaction(
                    "card",
                    _day_in_month(month_start, 7 + index * 9),
                    _jitter(rng, -2_240, 0.30),
                    "Chipotle",
                    "FOOD_AND_DRINK",
                )
            )

        for index in range(2):
            card_entries.append(
                PlannedTransaction(
                    "card",
                    _day_in_month(month_start, 5 + index * 14),
                    _jitter(rng, -5_820, 0.25),
                    "Shell",
                    "TRANSPORTATION",
                )
            )

        for index in range(rng.randint(2, 4)):
            card_entries.append(
                PlannedTransaction(
                    "card",
                    _day_in_month(month_start, 4 + index * 7),
                    _jitter(rng, -4_310, 0.60),
                    "Amazon",
                    "GENERAL_MERCHANDISE",
                )
            )

        month_card_spend = sum(abs(e.amount) for e in card_entries)
        entries.extend(card_entries)

        # -- Card payment for last month's balance (auto-pairs) --------- #
        if unpaid_card:
            pay_date = _day_in_month(month_start, 25)
            entries.append(
                PlannedTransaction(
                    "checking",
                    pay_date,
                    -unpaid_card,
                    _CARD_PAYMENT_OUT_NAME,
                    "TRANSFER_OUT",
                )
            )
            entries.append(
                PlannedTransaction(
                    "card",
                    pay_date,
                    unpaid_card,
                    _CARD_PAYMENT_IN_NAME,
                    "TRANSFER_IN",
                )
            )
        unpaid_card = month_card_spend

        # -- Monthly savings transfer (auto-pairs) ---------------------- #
        transfer_date = _day_in_month(month_start, 20)
        entries.append(
            PlannedTransaction(
                "checking",
                transfer_date,
                -75_000,
                _TRANSFER_OUT_NAME,
                "TRANSFER_OUT",
            )
        )
        entries.append(
            PlannedTransaction(
                "savings", transfer_date, 75_000, _TRANSFER_IN_NAME, "TRANSFER_IN"
            )
        )

    in_window = [e for e in entries if e.txn_date <= anchor]
    in_window.sort(key=lambda e: (e.txn_date, e.account_key, e.name))
    return tuple(in_window)


# --------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------- #


def _is_demo(account: FinanceAccount) -> bool:
    return bool((account.metadata_ or {}).get(DEMO_MARKER_KEY))


async def _demo_accounts(
    db: AsyncSession, owner_user_id: int | None
) -> list[FinanceAccount]:
    """Seeded accounts for this owner, identified by their marker.

    Filtered in Python rather than SQL: JSON predicates differ across SQLite
    and Postgres, and an install's account list is small enough that one scan
    is cheaper than the portability problem.
    """
    query = select(FinanceAccount)
    if owner_user_id is None:
        query = query.where(FinanceAccount.owner_user_id.is_(None))
    else:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return [a for a in (await db.exec(query)).all() if _is_demo(a)]


async def _delete_demo_rows(
    db: AsyncSession,
    owner_user_id: int | None,
    *,
    window_start: date | None = None,
) -> None:
    """Delete every row this module wrote for ``owner_user_id``.

    Scoped to the marked accounts and what hangs off them, so a user's own
    accounts, transactions, and imports survive untouched. Ordered to respect
    the foreign keys, including the circular transaction/transfer pair, whose
    back-references are cleared before their targets go.
    """
    accounts = await _demo_accounts(db, owner_user_id)
    if not accounts:
        return
    account_ids = [a.id for a in accounts]
    if window_start is None:
        window_start = await _seeded_window_start(db, account_ids)

    txns = list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id.in_(account_ids)
                )
            )
        ).all()
    )
    txn_ids = [t.id for t in txns]
    batch_ids = sorted(
        {t.import_batch_id for t in txns if t.import_batch_id is not None}
    )

    # Break the transaction <-> transfer/stream back-references first.
    for txn in txns:
        txn.transfer_group_id = None
        txn.transfer_pair_transaction_id = None
        txn.recurring_stream_id = None
        db.add(txn)
    await db.flush()

    if txn_ids:
        await _delete_where(
            db,
            FinanceTransactionSplit,
            FinanceTransactionSplit.parent_transaction_id,
            txn_ids,
        )
        await _delete_where(
            db, FinanceTransactionTag, FinanceTransactionTag.transaction_id, txn_ids
        )
    await _release_transfers(db, account_ids)
    await _delete_where(
        db, FinanceRecurringStream, FinanceRecurringStream.account_id, account_ids
    )
    if batch_ids:
        await _delete_where(
            db, FinanceImportBatchRow, FinanceImportBatchRow.import_batch_id, batch_ids
        )
    await _delete_where(
        db, FinanceTransaction, FinanceTransaction.account_id, account_ids
    )
    if batch_ids:
        await _delete_where(db, FinanceImportBatch, FinanceImportBatch.id, batch_ids)
    for model, column in (
        (FinanceValuation, FinanceValuation.account_id),
        (FinanceBalanceSnapshot, FinanceBalanceSnapshot.account_id),
        (FinanceHolding, FinanceHolding.account_id),
        (FinanceTrade, FinanceTrade.account_id),
        (FinanceLiabilityDetail, FinanceLiabilityDetail.account_id),
    ):
        await _delete_where(db, model, column, account_ids)
    await _delete_where(db, FinanceAccount, FinanceAccount.id, account_ids)

    # Net-worth snapshots are per-owner, not per-account, so they can't be
    # scoped away like the rows above - the seeded accounts are baked into
    # each day's total. Drop the days the seed touched; they are derived, and
    # the caller recomputes them from whatever accounts remain.
    if window_start is not None:
        stale = (
            await db.exec(
                select(FinanceNetWorthSnapshot).where(
                    FinanceNetWorthSnapshot.as_of_date >= window_start,
                    FinanceNetWorthSnapshot.owner_user_id.is_(None)
                    if owner_user_id is None
                    else FinanceNetWorthSnapshot.owner_user_id == owner_user_id,
                )
            )
        ).all()
        for row in stale:
            await db.delete(row)
    await db.flush()


async def _seeded_window_start(db: AsyncSession, account_ids: list[int]) -> date | None:
    """Earliest day the seeded accounts have history for, if any."""
    earliest = (
        await db.exec(
            select(FinanceValuation.as_of_date)
            .where(FinanceValuation.account_id.in_(account_ids))
            .order_by(FinanceValuation.as_of_date)
            .limit(1)
        )
    ).first()
    return earliest


async def _release_transfers(db: AsyncSession, account_ids: list[int]) -> None:
    """Delete transfers touching these accounts, freeing every paired leg.

    A transfer can pair a seeded leg with one of the user's own transactions.
    Deleting the transfer without unflagging that surviving leg would leave a
    real transaction marked ``is_transfer`` and hidden from reports, pointing
    at a transfer that no longer exists.
    """
    transfers = list(
        (
            await db.exec(
                select(FinanceTransfer).where(
                    or_(
                        FinanceTransfer.from_account_id.in_(account_ids),
                        FinanceTransfer.to_account_id.in_(account_ids),
                    )
                )
            )
        ).all()
    )
    if not transfers:
        return
    leg_ids = {
        leg_id
        for transfer in transfers
        for leg_id in (transfer.from_transaction_id, transfer.to_transaction_id)
        if leg_id is not None
    }
    if leg_ids:
        legs = (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.id.in_(sorted(leg_ids))
                )
            )
        ).all()
        for leg in legs:
            leg.is_transfer = False
            leg.excluded_from_reports = False
            leg.transfer_group_id = None
            leg.transfer_pair_transaction_id = None
            db.add(leg)
        await db.flush()
    for transfer in transfers:
        await db.delete(transfer)
    await db.flush()


async def _delete_where(
    db: AsyncSession, model: type, column: object, values: list[int]
) -> None:
    """Delete ``model`` rows whose ``column`` is in ``values``."""
    if not values:
        return
    rows = (await db.exec(select(model).where(column.in_(values)))).all()
    for row in rows:
        await db.delete(row)
    await db.flush()


async def _create_accounts(
    service: FinanceService, owner_user_id: int | None
) -> dict[str, FinanceAccount]:
    """Create the seeded account set, each carrying the demo marker."""
    accounts: dict[str, FinanceAccount] = {}
    for spec in DEMO_ACCOUNTS:
        account = await service.create_manual_account(
            owner_user_id=owner_user_id,
            name=spec.name,
            account_type=spec.account_type,
            classification=spec.classification,
            current_balance=spec.opening_balance,
        )
        account.metadata_ = {DEMO_MARKER_KEY: DEMO_MARKER_VALUE, "key": spec.key}
        service.db.add(account)
        accounts[spec.key] = account
    await service.db.flush()
    return accounts


def _qif_bytes(entries: list[PlannedTransaction]) -> bytes:
    """Render entries as a QIF bank export (the format a bank hands you)."""
    lines = ["!Type:Bank"]
    for entry in entries:
        lines.append(f"D{entry.txn_date.strftime('%m/%d/%Y')}")
        lines.append(f"T{entry.amount / 100:.2f}")
        lines.append(f"P{entry.name}")
        if entry.memo:
            lines.append(f"M{entry.memo}")
        lines.append("^")
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _write_transactions(
    service: FinanceService,
    accounts: dict[str, FinanceAccount],
    ledger: tuple[PlannedTransaction, ...],
    *,
    owner_user_id: int | None,
    import_cutoff: date,
) -> tuple[int, int, int]:
    """Persist the ledger; returns (direct, imported, splits) counts.

    Recent checking activity is handed to ``imports`` as a QIF file so
    the import-history surface is populated by the same path a real upload
    takes. Everything else is written directly.
    """
    imported_plan = [
        e for e in ledger if e.account_key == "checking" and e.txn_date >= import_cutoff
    ]
    direct_plan = [e for e in ledger if e not in set(imported_plan)]

    categories: dict[str, int] = {}

    async def _category_id(primary: str | None) -> int | None:
        if not primary:
            return None
        if primary not in categories:
            category = await service.get_or_create_pfc_category(primary)
            categories[primary] = category.id
        return categories[primary]

    splits_written = 0
    for entry in direct_plan:
        account = accounts[entry.account_key]
        category_id = await _category_id(entry.category)
        txn = await service.create_transaction(
            owner_user_id=owner_user_id,
            account_id=account.id,
            amount=entry.amount,
            txn_date=entry.txn_date,
            name=entry.name,
            memo=entry.memo,
            category_id=category_id,
            category_source="rule" if category_id else "unset",
            is_split=bool(entry.splits),
        )
        for order, part in enumerate(entry.splits):
            await service.create_split(
                owner_user_id=owner_user_id,
                parent_transaction_id=txn.id,
                amount=part.amount,
                category_id=await _category_id(part.category),
                memo=part.memo,
                sort_order=order,
            )
            splits_written += 1

    imported_rows = 0
    if imported_plan:
        result = await imports.import_file(
            service.db,
            owner_user_id=owner_user_id,
            file_name="chase-checking-recent.qif",
            file_bytes=_qif_bytes(imported_plan),
            account_id=accounts["checking"].id,
        )
        imported_rows = result.rows_inserted

    return len(direct_plan), imported_rows, splits_written


def _running_balances(
    ledger: tuple[PlannedTransaction, ...],
) -> dict[str, list[tuple[date, int]]]:
    """Per-account ``(date, balance)`` points implied by the ledger."""
    opening = {spec.key: spec.opening_balance for spec in DEMO_ACCOUNTS}
    balances = {key: opening.get(key, 0) for key in opening}
    points: dict[str, list[tuple[date, int]]] = {key: [] for key in opening}
    for entry in ledger:
        balances[entry.account_key] += entry.amount
        points[entry.account_key].append((entry.txn_date, balances[entry.account_key]))
    return points


async def _write_valuations(
    service: FinanceService,
    accounts: dict[str, FinanceAccount],
    ledger: tuple[PlannedTransaction, ...],
    *,
    owner_user_id: int | None,
    anchor: date,
    months: int,
    brokerage_value: int,
) -> int:
    """Post a monthly valuation series so net worth has a curve to draw.

    ``recompute_snapshots`` reads valuations, never transactions - an account
    with only a ``current_balance`` contributes a flat carried-forward line.
    Posting the balance each account actually had is what turns the chart into
    a real series.
    """
    points = _running_balances(ledger)
    marks = [d for d in _month_starts(anchor, months)][1:] + [anchor]
    written = 0

    for key, account in accounts.items():
        if key in ("home", "brokerage", "mortgage"):
            continue
        series = points.get(key, [])
        for mark in marks:
            balance = next((bal for day, bal in reversed(series) if day <= mark), None)
            if balance is None:
                continue
            # A liability's balance is what's owed: a positive number.
            value = abs(balance) if account.classification == "liability" else balance
            await service.upsert_valuation(
                account_id=account.id,
                as_of_date=mark,
                value=value,
                owner_user_id=owner_user_id,
                source="manual",
            )
            written += 1

    # The house appreciates steadily; the mortgage amortizes down.
    home = accounts["home"]
    mortgage = accounts["mortgage"]
    home_spec = next(s for s in DEMO_ACCOUNTS if s.key == "home")
    mortgage_spec = next(s for s in DEMO_ACCOUNTS if s.key == "mortgage")
    for index, mark in enumerate(marks):
        await service.upsert_valuation(
            account_id=home.id,
            as_of_date=mark,
            value=home_spec.opening_balance + index * 121_000,
            owner_user_id=owner_user_id,
        )
        await service.upsert_valuation(
            account_id=mortgage.id,
            as_of_date=mark,
            value=mortgage_spec.opening_balance - index * 42_500,
            owner_user_id=owner_user_id,
        )
        written += 2

    # The brokerage grows with contributions; today's mark is the real
    # market value of the positions written below.
    brokerage = accounts["brokerage"]
    for index, mark in enumerate(marks):
        share = (index + 1) / len(marks)
        await service.upsert_valuation(
            account_id=brokerage.id,
            as_of_date=mark,
            value=int(brokerage_value * (0.82 + 0.18 * share)),
            owner_user_id=owner_user_id,
        )
        written += 1
    return written


async def _write_investments(
    service: FinanceService,
    accounts: dict[str, FinanceAccount],
    *,
    owner_user_id: int | None,
    anchor: date,
    months: int,
) -> tuple[int, int]:
    """Seed securities, monthly buys, and today's positions.

    Returns ``(trades, market_value)``; the value feeds the brokerage
    valuation series so the account's history and its holdings agree.
    """
    rng = random.Random(_SEED + 1)
    brokerage = accounts["brokerage"]
    marks = _month_starts(anchor, months)
    trades = 0
    market_value = 0

    for ticker, name, price in DEMO_SECURITIES:
        security = await service.get_or_create_security(
            ticker=ticker, name=name, security_type="etf"
        )
        await service.upsert_security_price(
            security_id=security.id, price_date=anchor, close_price=price
        )
        total_quantity_e8 = 0
        for index, mark in enumerate(marks):
            buy_date = _day_in_month(mark, 16)
            if buy_date > anchor:
                continue
            # Contributions drift a little; earlier buys got a lower price.
            quantity_e8 = _jitter(rng, 5 * _QUANTITY_SCALE, 0.25)
            unit_price = int(price * (0.88 + 0.12 * (index + 1) / len(marks)))
            total_quantity_e8 += quantity_e8
            await service.upsert_trade(
                owner_user_id=owner_user_id,
                account_id=brokerage.id,
                trade_type="buy",
                trade_date=buy_date,
                amount=-market_value_cents(quantity_e8, unit_price, 2),
                security_id=security.id,
                quantity_e8=quantity_e8,
                price=unit_price,
                name=f"Buy {ticker}",
            )
            trades += 1
        if total_quantity_e8:
            await service.upsert_holding(
                owner_user_id=owner_user_id,
                account_id=brokerage.id,
                security_id=security.id,
                as_of_date=anchor,
                quantity_e8=total_quantity_e8,
                price=price,
                sync_account_balance=False,
            )
            market_value += market_value_cents(total_quantity_e8, price, 2)
    return trades, market_value


async def _count_derived(db: AsyncSession, account_ids: list[int]) -> tuple[int, int]:
    """``(transfers, recurring streams)`` the detectors left on these accounts."""
    transfers = (
        await db.exec(
            select(FinanceTransfer).where(
                or_(
                    FinanceTransfer.from_account_id.in_(account_ids),
                    FinanceTransfer.to_account_id.in_(account_ids),
                )
            )
        )
    ).all()
    streams = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.account_id.in_(account_ids)
            )
        )
    ).all()
    return len(transfers), len(streams)


async def count_foreign_accounts(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> int:
    """The owner's own (non-seeded) accounts.

    Seeding into an install that already holds real finance data is the one
    case worth a prompt: net-worth snapshots are per-owner aggregates, so the
    demo accounts get folded into the same daily totals as the real ones.
    Clearing afterwards recomputes those days from the accounts that remain,
    which is exact for accounts with a valuation series and lossy for
    provider-synced accounts that only carry a current balance.
    """
    query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
    if owner_user_id is None:
        query = query.where(FinanceAccount.owner_user_id.is_(None))
    else:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return len([a for a in (await db.exec(query)).all() if not _is_demo(a)])


async def clear_demo(db: AsyncSession, *, owner_user_id: int | None = None) -> int:
    """Remove the seeded dataset without rebuilding it. Returns accounts removed.

    The inverse of ``seed_demo``: pulls the demo data back out of an install
    that also holds real data. Writes; the caller commits.
    """
    accounts = await _demo_accounts(db, owner_user_id)
    if not accounts:
        return 0
    window_start = await _seeded_window_start(db, [a.id for a in accounts])
    # Net worth carries an account's earliest known balance BACKWARDS, so
    # the seed can leave snapshots on days before its own first
    # transaction. Widening the repair window to the oldest snapshot makes
    # sure none of those survive the clear, still reflecting accounts that
    # no longer exist.
    oldest_snapshot = (
        await db.exec(
            select(func.min(FinanceNetWorthSnapshot.as_of_date)).where(
                FinanceNetWorthSnapshot.owner_user_id.is_(None)
                if owner_user_id is None
                else FinanceNetWorthSnapshot.owner_user_id == owner_user_id
            )
        )
    ).first()
    if oldest_snapshot is not None:
        window_start = (
            oldest_snapshot
            if window_start is None
            else min(window_start, oldest_snapshot)
        )
    await _delete_demo_rows(db, owner_user_id, window_start=window_start)
    if window_start is not None:
        # Rebuild the days just dropped from whatever accounts survive, so a
        # user with real data keeps a truthful curve instead of a hole.
        await networth.recompute_snapshots(
            db, owner_user_id=owner_user_id, start_date=window_start
        )
    return len(accounts)


async def seed_demo(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    reset: bool = False,
    months: int = _DEFAULT_MONTHS,
) -> DemoSeedResult:
    """Populate a believable finance dataset. Writes; the caller commits.

    Idempotent: a second run without ``reset`` is a no-op and reports
    ``skipped``. With ``reset``, previously seeded rows are deleted first and
    the dataset is rebuilt.
    """
    existing = await _demo_accounts(db, owner_user_id)
    if existing and not reset:
        return DemoSeedResult(skipped=True)
    if reset:
        await _delete_demo_rows(db, owner_user_id)

    service = FinanceService(db)
    anchor = _today()
    window_start = _month_starts(anchor, months)[0]
    ledger = build_demo_ledger(anchor=anchor, months=months)

    accounts = await _create_accounts(service, owner_user_id)
    direct, imported, splits = await _write_transactions(
        service,
        accounts,
        ledger,
        owner_user_id=owner_user_id,
        import_cutoff=anchor - timedelta(days=_IMPORT_WINDOW_DAYS),
    )
    trades, market_value = await _write_investments(
        service, accounts, owner_user_id=owner_user_id, anchor=anchor, months=months
    )
    valuations = await _write_valuations(
        service,
        accounts,
        ledger,
        owner_user_id=owner_user_id,
        anchor=anchor,
        months=months,
        brokerage_value=market_value,
    )

    # Return values deliberately ignored: ``ingest_transactions`` runs these
    # same detectors at the end of the import above, so by now most pairs are
    # already made and a detector's own counter reports only what THIS pass
    # added. Both are idempotent, and running them here is what covers the
    # entries that never went through the import lane. The counts below come
    # from the rows themselves.
    # Full history on purpose: the seed writes months of activity and the
    # demo should show transfers detected across all of it.
    await detect_transfers(db, owner_user_id=owner_user_id, lookback_days=0)
    await detect_recurring(db, owner_user_id=owner_user_id)
    # One more insight pass now that every leg is paired: the per-batch
    # passes above ran before some transfer partners existed, and the rules
    # retract their own now-provably-wrong alerts (e.g. a "transfer hasn't
    # been paid" raised when only one leg had landed).
    # The demo household has confirmed its detected bills - under the
    # record/proposal split an unconfirmed stream counts for nothing, and
    # a showcase with an empty forecast and no missed-bill insights would
    # demo a product nobody configured.
    demo_streams = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.owner_user_id
                == (0 if owner_user_id is None else owner_user_id),
                FinanceRecurringStream.deleted_at.is_(None),
            )
        )
    ).all()
    for stream in demo_streams:
        stream.is_user_confirmed = True
        db.add(stream)
    await db.flush()
    await generate_insights(db, owner_user_id=owner_user_id)
    net_worth_days = await networth.recompute_snapshots(
        db, owner_user_id=owner_user_id, start_date=window_start
    )

    account_ids = [a.id for a in accounts.values()]
    transfers, recurring = await _count_derived(db, account_ids)
    return DemoSeedResult(
        accounts=len(accounts),
        transactions=direct + imported,
        imported_rows=imported,
        splits=splits,
        transfers=transfers,
        recurring=recurring,
        valuations=valuations,
        trades=trades,
        net_worth_days=net_worth_days,
        reset=reset,
    )
