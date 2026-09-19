"""The cards and cells the Budget panel is assembled from.

Split by what each one describes: ``goals`` for a goal or an
envelope, ``budget`` for a budget line or a month's outlook.
Every name the budget_panel tabs import is re-exported here.
"""

from app.components.frontend.dashboard.modals.finance_modal.budget_cards.budget import (
    budget_lines_grid,
    budget_stats_cells,
    budget_suggestion_caption,
    compact_budget_row,
    outlook_chip,
    outlook_month_label,
    outlook_stats_cells,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_cards.goals import (
    close_gap_row_copy,
    contribution_preview,
    envelope_card,
    goal_amounts_line,
    goal_eta_caption,
    goal_suggestion_message,
    linkable_account_options,
    savings_goal_card,
)

__all__ = [
    "budget_lines_grid",
    "budget_stats_cells",
    "budget_suggestion_caption",
    "close_gap_row_copy",
    "compact_budget_row",
    "contribution_preview",
    "envelope_card",
    "goal_amounts_line",
    "goal_eta_caption",
    "goal_suggestion_message",
    "linkable_account_options",
    "outlook_chip",
    "outlook_month_label",
    "outlook_stats_cells",
    "savings_goal_card",
]
