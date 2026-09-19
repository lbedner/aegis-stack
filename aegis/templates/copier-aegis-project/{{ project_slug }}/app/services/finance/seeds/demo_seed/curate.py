"""The passes that make the dataset look worked-on.

Payees named, proposals filed, derived counts tallied - what
distinguishes a seeded install from one that merely has rows.
"""

from __future__ import annotations

from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import merchants as ledger_merchants
from app.services.finance.domains.writes import propose
from app.services.finance.models import (
    FinanceRecurringStream,
    FinanceTransaction,
    FinanceTransfer,
)
from app.services.finance.seeds.demo_household import (
    _NO_PAYEE,
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
from app.services.finance.service import FinanceService


async def _name_payees(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    account_ids: list[int],
) -> int:
    """Give every recognisable row its payee, the way a curated ledger has.

    An import leaves ``merchant_id`` empty on everything - payees are a
    curation step - so a freshly seeded household showed a thousand rows
    in the No payee queue and the two deliberately bare ones were lost in
    them. One merchant per distinct name, assigned in a batch; the bank's
    own unusable names and the fee lines stay unnamed on purpose.
    """
    bare = {name for _m, _d, name, _a, _c in _NO_PAYEE} | {
        "Interest Charge",
        "Overdraft Fee",
    }
    rows = (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.account_id.in_(account_ids),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.is_transfer.is_(False),
                FinanceTransaction.merchant_id.is_(None),
            )
        )
    ).all()
    by_name: dict[str, list[int]] = {}
    for txn in rows:
        if txn.name and txn.name not in bare and txn.id is not None:
            by_name.setdefault(txn.name, []).append(txn.id)
    named = 0
    for name, ids in by_name.items():
        merchant = await ledger_merchants.create_merchant(
            db, name, owner_user_id=owner_user_id
        )
        named += await ledger_merchants.assign_merchant(
            db, ids, merchant.id, owner_user_id=owner_user_id
        )
    return named


async def _file_proposals(
    db: AsyncSession,
    service: FinanceService,
    *,
    owner_user_id: int | None,
    account_ids: list[int],
) -> int:
    """Leave the Approvals queue with something to approve.

    Without the AI service nothing files a proposal, so the highest-stakes
    queue in Review screenshots as an empty state. Three cards, one per
    change the app's own assistant most often proposes: a category for a
    row that arrived without one, a payee for a row the bank named
    unusably, and a split for the mixed Target run. Filed as
    ``demo_seed`` so a clear can find them.
    """
    rows = (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.account_id.in_(account_ids),
                FinanceTransaction.deleted_at.is_(None),
            )
        )
    ).all()
    merchandise = await service.get_or_create_pfc_category("GENERAL_MERCHANDISE")
    food = await service.get_or_create_pfc_category("FOOD_AND_DRINK")
    filed = 0

    bare = next((t for t in rows if t.category_id is None and t.amount < 0), None)
    if bare is not None:
        await propose(
            db,
            "transaction.categorize",
            {"transaction_id": bare.id, "category_id": merchandise.id},
            owner_user_id=owner_user_id,
            proposed_by_agent="demo_seed",
        )
        filed += 1
    # The bank's own unusable name, not a transfer leg: a transfer has a
    # counterparty already, and "assign a coffee shop to a brokerage
    # transfer" is not a proposal anyone should be asked to approve.
    bare_names = {name for _m, _d, name, _a, _c in _NO_PAYEE}
    unnamed = next(
        (
            t
            for t in rows
            if t.name in bare_names and t.merchant_id is None and not t.is_transfer
        ),
        None,
    )
    if unnamed is not None:
        await propose(
            db,
            "transaction.assign_payee",
            {"transaction_id": unnamed.id, "payee": "Hudson Valley Grounded"},
            owner_user_id=owner_user_id,
            proposed_by_agent="demo_seed",
        )
        filed += 1
    target = next((t for t in rows if t.name == "Target" and t.amount == -14_237), None)
    if target is not None:
        await propose(
            db,
            "transaction.split",
            {
                "transaction_id": target.id,
                "parts": [
                    {"amount": 8_612, "category_id": food.id, "memo": "groceries"},
                    {
                        "amount": 3_400,
                        "category_id": merchandise.id,
                        "memo": "household",
                    },
                ],
            },
            owner_user_id=owner_user_id,
            proposed_by_agent="demo_seed",
        )
        filed += 1
    await db.flush()
    return filed


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
