"""Rule-based "wasting money" insights, no AI.

Three concerns, one per module - ``commitments`` for what counts as a bill
and whether it is currently owed, ``formatting`` for the figures and month
buckets an alert quotes, ``rules`` for the nine deterministic checks that
write ``finance_insight`` rows.

The split exists because the first of those is vocabulary the whole app
speaks: the forecast, the Budget tab, the suggestion guards and the
Bills & Income display all ask "is this a commitment, is it paused". They
can import ``commitments`` directly - it touches nothing but constants and
models - instead of reaching through the rules, which read the database
and the planning domain.
"""

from app.services.finance.domains.detection.insights import (
    commitments,
    formatting,
    rules,
)
from app.services.finance.domains.detection.insights.commitments import (
    MONTHLY_FACTOR,
    CommitmentRollup,
    commitment_rollup,
    is_commitment,
    is_paused,
    not_paused_clause,
    stream_staleness,
)
from app.services.finance.domains.detection.insights.formatting import (
    card_apr_bps,
    days_in_month,
    format_apr,
    format_usd,
    month_is_complete,
    month_key,
    month_start_before,
    pace_day,
)
from app.services.finance.domains.detection.insights.rules import (
    HIGH_APR_BPS,
    HIGH_APR_MIN_BALANCE,
    LARGE_TXN_BASELINE_DAYS,
    LARGE_TXN_CRITICAL_MULTIPLE,
    LARGE_TXN_FLOOR,
    LARGE_TXN_MIN_BASELINE,
    LARGE_TXN_MULTIPLE,
    LARGE_TXN_THIN_FLOOR,
    LARGE_TXN_WINDOW_DAYS,
    MIN_PAYMENT_LOOKAHEAD_DAYS,
    OVERSPEND_MIN_BASELINE,
    OVERSPEND_MIN_ELAPSED,
    OVERSPEND_MIN_HISTORY,
    OVERSPEND_MULTIPLE,
    PRICE_HIKE_THRESHOLD,
    RUNWAY_DAYS,
    SUBSCRIPTION_CREEP_MULTIPLE,
    UTILIZATION_CRITICAL,
    UTILIZATION_WARNING,
    InsightGenerationResult,
    create_insight_if_new,
    generate_insights,
    live_account_ids,
    monthly_category_spend,
)

__all__ = [
    "HIGH_APR_BPS",
    "HIGH_APR_MIN_BALANCE",
    "LARGE_TXN_BASELINE_DAYS",
    "LARGE_TXN_CRITICAL_MULTIPLE",
    "LARGE_TXN_FLOOR",
    "LARGE_TXN_MIN_BASELINE",
    "LARGE_TXN_MULTIPLE",
    "LARGE_TXN_THIN_FLOOR",
    "LARGE_TXN_WINDOW_DAYS",
    "MIN_PAYMENT_LOOKAHEAD_DAYS",
    "MONTHLY_FACTOR",
    "OVERSPEND_MIN_BASELINE",
    "OVERSPEND_MIN_ELAPSED",
    "OVERSPEND_MIN_HISTORY",
    "OVERSPEND_MULTIPLE",
    "PRICE_HIKE_THRESHOLD",
    "RUNWAY_DAYS",
    "SUBSCRIPTION_CREEP_MULTIPLE",
    "UTILIZATION_CRITICAL",
    "UTILIZATION_WARNING",
    "CommitmentRollup",
    "InsightGenerationResult",
    "card_apr_bps",
    "commitment_rollup",
    "commitments",
    "create_insight_if_new",
    "days_in_month",
    "format_apr",
    "format_usd",
    "formatting",
    "generate_insights",
    "is_commitment",
    "is_paused",
    "live_account_ids",
    "month_is_complete",
    "month_key",
    "month_start_before",
    "monthly_category_spend",
    "not_paused_clause",
    "pace_day",
    "rules",
    "stream_staleness",
]
