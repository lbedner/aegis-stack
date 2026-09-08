"""Per-user daily spend guard for open-ended chat.

GENERIC. Reports and commentary are fixed-cost per artifact; chat is the
first open-ended AI surface, so spend is metered per user per day and checked
BEFORE the model call. The guard sums the shared ``llm_usage`` ledger for one
action family (e.g. ``chat:%``) over today (UTC) and compares it to a budget.

Fail-open: if the ledger is unreadable, the turn is allowed with a warning
and ``degraded=True``. This matches the repo's "instrumentation never breaks a
request" stance — a DB outage takes the whole app down anyway, and blocking
chat on a transient read error is worse than briefly uncapped spend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.log import logger
from app.services.ai.domains.llm import queries as llm_queries

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

    def __init__(self, action_prefix: str, daily_budget_usd: float) -> None:
        # ``action_prefix`` matches the ledger's ``action`` column as a LIKE
        # pattern ("chat:" -> "chat:%"), so a surface can budget its own
        # family without touching insight ("insight:%") spend.
        self.action_prefix = action_prefix
        self.daily_budget_usd = daily_budget_usd

    async def check(self, session: Any, user_id: str) -> BudgetStatus:
        """Sum today's spend for this user + action family; allow if under."""
        try:
            spent = await llm_queries.spend_since(
                session,
                user_id=user_id,
                action_prefix=self.action_prefix,
                since=_utc_day_start(),
            )
        except Exception as exc:  # noqa: BLE001 - fail open, see module docstring
            logger.warning(
                "chat budget check failed; allowing turn",
                user_id=user_id,
                error=str(exc),
            )
            return BudgetStatus(
                allowed=True,
                spent_usd=0.0,
                budget_usd=self.daily_budget_usd,
                degraded=True,
            )
        return BudgetStatus(
            allowed=spent < self.daily_budget_usd,
            spent_usd=spent,
            budget_usd=self.daily_budget_usd,
        )
