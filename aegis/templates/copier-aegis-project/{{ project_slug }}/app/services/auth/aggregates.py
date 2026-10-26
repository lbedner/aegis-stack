"""What the auth service holds, as figures (``app.core.aggregates``):
sign-ins and active users by day, never who."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.auth.domains.sessions.queries import by_day


class SignIns(BaseModel):
    """Each day (``YYYY-MM-DD``) in the window: sessions begun, and users
    active. As far back as sign-ins are kept."""

    model_config = FIGURES

    sign_ins: dict[str, int]
    active_users: dict[str, int]


async def sign_ins(session: AsyncSession, days: int | None) -> SignIns:
    begun, active = await by_day(session, ranges.start(days))
    return SignIns(sign_ins=begun, active_users=active)


AGGREGATES = (Aggregate("sign_ins", "Sign-ins and active users by day", sign_ins),)
