"""Budgets: the limits you set, and whether the month survives them.

Five concerns, one per module - ``lines`` for setting a limit,
``suggestions`` for proposing and declining them, ``summary`` for reading
a period back and closing a negative month, ``outlook`` for running the
same equation forward, ``queries`` for the reads only this domain issues.
The package boundary is the API: callers reach every verb as
``budgets.foo(db, ...)`` and never import a submodule.
"""

from app.services.finance.domains.planning.budgets import (
    lines,
    outlook,
    queries,
    suggestions,
    summary,
)
from app.services.finance.domains.planning.budgets.lines import (
    budget_line_status,
    delete_budget_line,
    get_or_create_budget,
    spend_for_target,
    upsert_budget_line,
)
from app.services.finance.domains.planning.budgets.outlook import (
    budget_month_outlook,
    parse_budget_goal,
)
from app.services.finance.domains.planning.budgets.queries import month_bounds
from app.services.finance.domains.planning.budgets.suggestions import (
    _BUDGET_BILLED_SHARE,
    _BUDGET_LOOKBACK_MONTHS,
    _BUDGET_MAX_UNUSUAL_MONTHS,
    _BUDGET_MIN_AMOUNT,
    _BUDGET_MIN_MONTHS,
    _BUDGET_UNUSUAL_BAND,
    dismiss_budget_suggestions,
    dismissal_markers,
    list_dismissed_suggestions,
    restore_budget_suggestions,
    suggest_budget_lines,
)
from app.services.finance.domains.planning.budgets.summary import (
    budget_stat_details,
    budget_summary,
    plan_budget_trims,
    uncovered_spend_filters,
    uncovered_spending_rate,
)

__all__ = [
    "_BUDGET_BILLED_SHARE",
    "_BUDGET_LOOKBACK_MONTHS",
    "_BUDGET_MAX_UNUSUAL_MONTHS",
    "_BUDGET_MIN_AMOUNT",
    "_BUDGET_MIN_MONTHS",
    "_BUDGET_UNUSUAL_BAND",
    "budget_line_status",
    "budget_month_outlook",
    "budget_stat_details",
    "budget_summary",
    "delete_budget_line",
    "dismiss_budget_suggestions",
    "dismissal_markers",
    "get_or_create_budget",
    "lines",
    "list_dismissed_suggestions",
    "month_bounds",
    "outlook",
    "parse_budget_goal",
    "plan_budget_trims",
    "queries",
    "restore_budget_suggestions",
    "spend_for_target",
    "suggest_budget_lines",
    "suggestions",
    "summary",
    "uncovered_spend_filters",
    "uncovered_spending_rate",
    "upsert_budget_line",
]
