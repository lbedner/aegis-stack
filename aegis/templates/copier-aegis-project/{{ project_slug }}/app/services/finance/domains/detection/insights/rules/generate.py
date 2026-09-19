"""Running every rule for one owner, in order.

Explicit calls rather than a registry: the rules take different
arguments, and a list of calls reads better than a table of signatures
that all have to agree.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection.insights.rules.balances import (
    _cash_runway,
    _credit_cards,
)
from app.services.finance.domains.detection.insights.rules.recurring import (
    _missed_recurring,
)
from app.services.finance.domains.detection.insights.rules.shared import (
    InsightGenerationResult,
    live_account_ids,
)
from app.services.finance.domains.detection.insights.rules.spending import (
    _fees,
    _large_transactions,
    _overspend,
    _price_hikes,
    _subscription_creep,
)
from app.services.finance.utils import current_date


async def generate_insights(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    today: date | None = None,
    lookback_days: int | None = None,
) -> InsightGenerationResult:
    """Run every insight rule for one owner. Idempotent (dedup_key).

    Insights have a NOT-NULL owner, so a standalone (NULL-owner) install stores
    them under the ``0`` sentinel while scanning its NULL-owner rows.

    ``lookback_days`` (``settings.FINANCE_RULES_LOOKBACK_DAYS`` when not
    given; 0 disables it) floors the fee and missed-recurring rules so a deep
    historical import doesn't flood the list with years-old findings. The
    other rules already carry their own windows.
    """
    from app.core.config import settings

    result = InsightGenerationResult()
    today = today or current_date()
    if lookback_days is None:
        lookback_days = settings.FINANCE_RULES_LOOKBACK_DAYS
    floor = today - timedelta(days=lookback_days) if lookback_days else None
    store_owner = 0 if owner_user_id is None else owner_user_id

    live_accounts = live_account_ids(owner_user_id)

    result.created += await _price_hikes(db, store_owner, today)
    result.created += await _fees(db, owner_user_id, store_owner, live_accounts, floor)
    result.created += await _overspend(db, owner_user_id, store_owner, today)
    result.created += await _large_transactions(
        db, owner_user_id, store_owner, live_accounts, today
    )
    result.created += await _missed_recurring(
        db, store_owner, live_accounts, today, floor
    )
    result.created += await _credit_cards(db, owner_user_id, store_owner, today)
    result.created += await _cash_runway(db, owner_user_id, store_owner, today)
    result.created += await _subscription_creep(db, owner_user_id, store_owner, today)
    return result
