"""Finance categorization + reconciliation passes (transfers, rules, …)."""

from app.services.finance.categorize.insights import (
    InsightGenerationResult,
    commitment_rollup,
    generate_insights,
    is_commitment,
    is_paused,
    stream_staleness,
)
from app.services.finance.categorize.promote import promote_curated_streams
from app.services.finance.categorize.recurring import (
    DeclareRecurringResult,
    RecurringDetectionResult,
    RecurringPlanGroup,
    declare_recurring,
    detect_recurring,
    plan_recurring,
)
from app.services.finance.categorize.transfers import (
    TransferDetectionResult,
    detect_transfers,
)

__all__ = [
    "DeclareRecurringResult",
    "InsightGenerationResult",
    "RecurringDetectionResult",
    "RecurringPlanGroup",
    "TransferDetectionResult",
    "commitment_rollup",
    "declare_recurring",
    "detect_recurring",
    "detect_transfers",
    "generate_insights",
    "is_commitment",
    "is_paused",
    "plan_recurring",
    "promote_curated_streams",
    "stream_staleness",
]
