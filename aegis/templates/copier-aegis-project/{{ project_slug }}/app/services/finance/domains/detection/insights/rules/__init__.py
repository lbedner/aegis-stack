"""The nine deterministic "wasting money" rules.

Runs nightly after recurring detection. Writes ``finance_insight`` rows
(deduped on ``(owner, dedup_key)``) so the same alert is not regenerated
every night. Every rule is deterministic: thresholds are constants tuned
by test, not by a config surface. Anything reading these rows - the
Insights list, the analyst agent's daily note - consumes findings it did
not make, so a model can never invent an alert.

A package rather than one module, grouped by what a rule reasons about:

- ``spending``  a charge against a norm the account or stream set itself
- ``recurring`` the one rule about absence: an expected charge missing
- ``balances``  what the institution itself reports about the account
- ``shared``    thresholds, the result tally, and the writer that dedups
- ``generate``  the dispatcher

This is the finance-local path. When the insights service is present a
bridge can additionally emit through its event machinery; the local rows
are the source of truth for dedup and the finance modal's Insights list.

The commitment vocabulary (``is_commitment``, ``is_paused``,
``commitment_rollup``) sits in ``commitments`` instead: half the app
needs those predicates and none of it should have to import the rules,
which read the database, to get them.
"""

from app.services.finance.domains.detection.insights.rules.generate import (
    generate_insights,
)
from app.services.finance.domains.detection.insights.rules.shared import (
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
    "OVERSPEND_MIN_BASELINE",
    "OVERSPEND_MIN_ELAPSED",
    "OVERSPEND_MIN_HISTORY",
    "OVERSPEND_MULTIPLE",
    "PRICE_HIKE_THRESHOLD",
    "RUNWAY_DAYS",
    "SUBSCRIPTION_CREEP_MULTIPLE",
    "UTILIZATION_CRITICAL",
    "UTILIZATION_WARNING",
    "InsightGenerationResult",
    "create_insight_if_new",
    "generate_insights",
    "live_account_ids",
    "monthly_category_spend",
]
