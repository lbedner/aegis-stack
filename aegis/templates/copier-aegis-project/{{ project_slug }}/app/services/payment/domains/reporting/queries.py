"""Reads the reporting domain counts with, beside what its mixin reads:
what the payment service's aggregates are made of."""

from datetime import datetime

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.payment.models import PaymentTransaction
from app.services.shared.queries import within


async def status_counts(
    session: AsyncSession, since: datetime | None
) -> dict[str, tuple[int, int]]:
    """``{status: (transactions, cents)}`` since ``since`` (all of them
    when None), in one query."""
    result = await session.exec(
        select(
            PaymentTransaction.status,
            func.count(),
            func.coalesce(func.sum(PaymentTransaction.amount), 0),
        )
        .where(*within(PaymentTransaction.created_at, since, None))
        .group_by(PaymentTransaction.status)
    )
    return {
        str(getattr(status, "value", status)): (int(n), int(cents))
        for status, n, cents in result.all()
    }
