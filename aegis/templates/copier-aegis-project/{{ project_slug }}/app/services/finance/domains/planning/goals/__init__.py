"""Goals: an account with a target, and what that implies.

Split by what a caller wants - ``meta`` for the contract itself,
``reads`` for how a goal is doing, ``actions`` for changing one.
"""

from app.services.finance.domains.planning.goals.actions import (
    auto_contribute_goals,
    contribute_to_goal,
    create_virtual_goal,
    flag_account_as_goal,
    set_goal_auto_contribute,
    set_goal_status,
    unflag_goal,
)
from app.services.finance.domains.planning.goals.meta import (
    DEFAULT_PRIORITY,
    GOAL_ACCOUNT_TYPE,
    GoalMeta,
    clear_goal_metadata,
    goal_auto_contribute,
    goal_metadata,
    set_auto_contribute,
    set_goal_metadata,
)
from app.services.finance.domains.planning.goals.reads import (
    goal_eta,
    goal_monthly_need,
    goal_progress,
    goal_rate,
    goal_rates,
    list_goals,
)

__all__ = [
    "DEFAULT_PRIORITY",
    "GOAL_ACCOUNT_TYPE",
    "GoalMeta",
    "auto_contribute_goals",
    "clear_goal_metadata",
    "contribute_to_goal",
    "create_virtual_goal",
    "flag_account_as_goal",
    "goal_auto_contribute",
    "goal_eta",
    "goal_metadata",
    "goal_monthly_need",
    "goal_progress",
    "goal_rate",
    "goal_rates",
    "list_goals",
    "set_auto_contribute",
    "set_goal_auto_contribute",
    "set_goal_metadata",
    "set_goal_status",
    "unflag_goal",
]
