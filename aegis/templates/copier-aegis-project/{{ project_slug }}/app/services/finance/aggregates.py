"""What the finance service holds, as figures (``app.core.aggregates``):
every owner's spend by parent category, as the Overview pie rolls it up,
never a payee, an account or a transaction."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.finance.domains.ledger.categories import spending_by_category


class Spend(BaseModel):
    """Outflows in the window, in cents, by parent category; transfers and
    rows kept out of reports never count."""

    model_config = FIGURES

    cents_by_category: dict[str, int]


async def spend(session: AsyncSession, days: int | None) -> Spend:
    found = await spending_by_category(session, days=days)
    return Spend(cents_by_category=dict(found))


AGGREGATES = (Aggregate("spend", "Spending by parent category, in cents", spend),)
