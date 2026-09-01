"""The shared card subject: every describe renders the same
transaction the same way."""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import format_date
from app.services.finance.domains.detection.insights.formatting import format_usd
from app.services.finance.domains.ledger import transactions


async def txn_subject(
    db: AsyncSession, transaction_id: int, owner_user_id: int | None
) -> tuple[Any, str]:
    """The row and its card-ready one-liner: the register's curated
    payee (never the raw bank descriptor), amount, date. Every
    describe renders the same subject the same way."""
    txn = await transactions.get_transaction(
        db, transaction_id, owner_user_id=owner_user_id
    )
    subject = (
        f"{txn.merchant_name or txn.name} "
        f"({format_usd(abs(txn.amount))} on {format_date(txn.date_)})"
        if txn is not None
        else f"transaction {transaction_id} (missing)"
    )
    return txn, subject
