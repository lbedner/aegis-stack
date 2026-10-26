"""What the payment service holds, as figures (``app.core.aggregates``):
transactions and their cents by status, never a transaction."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.payment.domains.reporting.queries import status_counts


class PaymentStatuses(BaseModel):
    """Transactions in the window, counted and summed (in cents) by
    status."""

    model_config = FIGURES

    count_by_status: dict[str, int]
    cents_by_status: dict[str, int]


async def status(session: AsyncSession, days: int | None) -> PaymentStatuses:
    found = await status_counts(session, ranges.start(days))
    return PaymentStatuses(
        count_by_status={s: n for s, (n, _) in found.items()},
        cents_by_status={s: cents for s, (_, cents) in found.items()},
    )


AGGREGATES = (Aggregate("status", "Transactions and their cents by status", status),)
