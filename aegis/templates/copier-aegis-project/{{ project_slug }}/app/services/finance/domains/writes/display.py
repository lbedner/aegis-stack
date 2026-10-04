"""The shared card subject: every describe renders the same
transaction the same way."""

from __future__ import annotations

from app.core.formatting import format_date
from app.services.finance.domains.detection.insights.formatting import format_usd
from app.services.finance.domains.ledger.queries import transactions as queries
from app.services.finance.models import FinanceTransaction
from sqlmodel.ext.asyncio.session import AsyncSession


async def live_transactions(
    db: AsyncSession, ids: list[int], owner_user_id: int | None
) -> dict[int, FinanceTransaction]:
    """The cards' transactions in one query, keyed by id; a deleted or
    foreign row is simply absent."""
    rows = await queries.live_transactions_by_ids(
        db, ids, owner_user_id=owner_user_id
    )
    return {txn.id: txn for txn in rows if txn.id is not None}


def txn_subject(txn: FinanceTransaction | None, transaction_id: int) -> str:
    """The card-ready one-liner: the register's curated payee (never the
    raw bank descriptor), amount, date."""
    if txn is None:
        return f"transaction {transaction_id} (missing)"
    return (
        f"{txn.merchant_name or txn.name} "
        f"({format_usd(abs(txn.amount))} on {format_date(txn.date_)})"
    )
