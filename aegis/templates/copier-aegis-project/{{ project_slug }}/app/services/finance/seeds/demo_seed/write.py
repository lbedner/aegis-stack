"""Writing the ledger: accounts, transactions, valuations, positions.

Transactions go in as a QIF through the real import pipeline rather
than as direct inserts, so the demo exercises the same dedup and
batch bookkeeping a real file would.
"""

from __future__ import annotations

from datetime import date
import random

from app.services.finance.adapters.importers import imports
from app.services.finance.domains.investments.securities import market_value_cents
from app.services.finance.models import (
    FinanceAccount,
)
from app.services.finance.seeds.demo_household import (
    DEMO_ACCOUNTS,
    DEMO_SECURITIES,
)
from app.services.finance.seeds.demo_plan import (  # noqa: F401
    _DEFAULT_MONTHS,
    _SEED,
    PlannedSplit,
    PlannedTransaction,
    _day_in_month,
    _jitter,
    _month_starts,
    build_demo_ledger,
)
from app.services.finance.seeds.demo_seed.shared import (
    _QUANTITY_SCALE,
    DEMO_MARKER_KEY,
    DEMO_MARKER_VALUE,
)
from app.services.finance.service import FinanceService


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
            original_description=entry.name,
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
