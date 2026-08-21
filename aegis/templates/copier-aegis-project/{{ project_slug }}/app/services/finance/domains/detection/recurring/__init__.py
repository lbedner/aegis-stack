"""Recurring-stream detection.

Finds subscriptions, bills, and paychecks so the product can answer "what
am I paying every month?" and flag price hikes.

Three concerns, one per module - ``cadence`` for the pure judgement about
whether a set of gaps is a rhythm, ``detect`` for the nightly pass that
applies it and writes streams, ``declare`` for the "Make recurring" path
where a person picks the rows instead.

``declare`` reuses ``detect``'s upsert and purge helpers on purpose: a
bill someone declared and a bill the detector found are the same kind of
row, and the moment they stop being written by the same code they start
diverging.
"""

from app.services.finance.domains.detection.recurring import cadence, declare, detect
from app.services.finance.domains.detection.recurring.cadence import (
    AMOUNT_TOLERANCE,
    INTERVAL_TOLERANCE,
    MAX_INTERVAL_SLACK_DAYS,
    MAX_SILENCE_DAYS,
    MIN_OCCURRENCES,
    MIN_RHYTHM_RATIO,
    MIN_STREAM_AMOUNT,
    SILENCE_CADENCE_MULTIPLE,
)
from app.services.finance.domains.detection.recurring.declare import (
    DeclareRecurringResult,
    RecurringPlanGroup,
    declare_recurring,
    plan_recurring,
)
from app.services.finance.domains.detection.recurring.detect import (
    RecurringDetectionResult,
    detect_recurring,
)

__all__ = [
    "AMOUNT_TOLERANCE",
    "INTERVAL_TOLERANCE",
    "MAX_INTERVAL_SLACK_DAYS",
    "MAX_SILENCE_DAYS",
    "MIN_OCCURRENCES",
    "MIN_RHYTHM_RATIO",
    "MIN_STREAM_AMOUNT",
    "SILENCE_CADENCE_MULTIPLE",
    "DeclareRecurringResult",
    "RecurringDetectionResult",
    "RecurringPlanGroup",
    "cadence",
    "declare",
    "declare_recurring",
    "detect",
    "detect_recurring",
    "plan_recurring",
]
