"""Per-user daily spend guard for open-ended chat.

GENERIC. Reports and commentary are fixed-cost per artifact; chat is the
first open-ended AI surface, so spend is metered per user per day and checked
BEFORE the model call. The guard sums the shared ``llm_usage`` ledger for one
action family (e.g. ``chat:%``) over today (UTC) and compares it to a budget.

Guests (``app.core.visitor``) share one account, so each is metered by its
session against its own ceiling (``guest_session_usd``), and all of them
together against one more (``all_guests_usd``): strangers on a public page
can never spend past what the operator set aside for them.

Fail-open: if the ledger is unreadable, the turn is allowed with a warning
and ``degraded=True``. This matches the repo's "instrumentation never breaks a
request" stance — a DB outage takes the whole app down anyway, and blocking
chat on a transient read error is worse than briefly uncapped spend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.log import logger
from app.core.visitor import GUESTS, is_guest_visitor
from app.services.ai.domains.spend import queries as spend_queries

from .models import BudgetStatus


def _utc_day_start() -> datetime:
    """Midnight today, UTC, as a naive datetime.

    ``llm_usage.timestamp`` is stored in a naive TIMESTAMP column (asyncpg
    rejects an aware datetime bound against it), so the bound must be naive
    too — same conversion the insight monthly-ceiling query uses.
    """
    return datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )


class BudgetGuard:
    """Checks one user's daily spend for an action family against a ceiling."""

    def __init__(
        self,
        action_prefix: str,
        daily_budget_usd: float,
        *,
        guest_session_usd: float | None = None,
        all_guests_usd: float | None = None,
    ) -> None:
        # ``action_prefix`` is a family ending in ":" ("chat:", never
        # touching insight spend), or one action: ``chat_action`` of one
        # agent counts that agent alone (``owner_spend_since``).
        self.action_prefix = action_prefix
        self.daily_budget_usd = daily_budget_usd
        self.guest_session_usd = (
            daily_budget_usd if guest_session_usd is None else guest_session_usd
        )
        self.all_guests_usd = all_guests_usd

    async def check(self, session: Any, user_id: str) -> BudgetStatus:
        """Sum today's spend for this user + action family; allow if under.
        A guest is refused once every guest together is over theirs too."""
        guest = is_guest_visitor(user_id)
        ceiling = self.guest_session_usd if guest else self.daily_budget_usd
        since = _utc_day_start()
        try:
            if guest and self.all_guests_usd is not None:
                shared, spent = await spend_queries.shared_spend_since(
                    session,
                    users=GUESTS,
                    user_id=user_id,
                    action_prefix=self.action_prefix,
                    since=since,
                )
                if shared >= self.all_guests_usd:
                    return BudgetStatus(
                        allowed=False,
                        spent_usd=shared,
                        budget_usd=self.all_guests_usd,
                        shared=True,
                    )
            else:
                spent = await spend_queries.owner_spend_since(
                    session,
                    user_id=user_id,
                    action_prefix=self.action_prefix,
                    since=since,
                )
        except Exception as exc:  # noqa: BLE001 - fail open, see module docstring
            logger.warning(
                "chat budget check failed; allowing turn",
                user_id=user_id,
                error=str(exc),
            )
            return BudgetStatus(
                allowed=True, spent_usd=0.0, budget_usd=ceiling, degraded=True
            )
        return BudgetStatus(
            allowed=spent < ceiling, spent_usd=spent, budget_usd=ceiling
        )
