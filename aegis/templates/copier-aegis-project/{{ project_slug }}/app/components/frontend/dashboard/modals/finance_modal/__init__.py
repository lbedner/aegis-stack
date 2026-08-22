"""
Finance Service Detail Modal

A Quicken-style finance workspace, organised into tabs (Accounts, Overview,
Connections, Review, Budget). Split one module per surface; this package
``__init__`` re-exports the public names so every existing import of
``finance_modal`` keeps resolving.

Data is fetched async through the internal ``APIClient`` (never a DB session
from the frontend). All colours, spacing, and type come from ``AegisTheme``.
"""

# Names the old single-module version exposed (helpers the tests reach,
# plus two side-effect re-exports callers came to rely on).
from app.components.frontend.dashboard.modals.finance_modal.accounts_tab import (
    AccountsTab,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_lines_grid,
    budget_stats_cells,
    budget_suggestion_caption,
    close_gap_row_copy,
    compact_budget_row,
    contribution_preview,
    envelope_card,
    goal_amounts_line,
    goal_eta_caption,
    goal_suggestion_message,
    linkable_account_options,
    outlook_chip,
    outlook_month_label,
    outlook_stats_cells,
    savings_goal_card,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel import (
    BudgetPanel,
)
from app.components.frontend.dashboard.modals.finance_modal.connections_tab import (
    ConnectionCard,
    ConnectionsTab,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DECLARE_GROUP_CHROME,
    _DENSE_ROW_HEIGHT,
    _DIALOG_FIXED_CHROME,
    _FREQUENCY_LABELS,
    _GROUP_DIALOG_CHROME,
    _GROUP_TABLE_MIN_HEIGHT,
    BILL_FREQUENCY_OPTIONS,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    CompactIconButton,
    _declare_body_height,
    _group_table_height,
    apply_category_picks,
    create_category,
)
from app.components.frontend.dashboard.modals.finance_modal.dialog import (
    FinanceDetailDialog,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import (
    AccountFilter,
    AccountFilterButton,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _account_display_balance,
    _amount_cell,
    _category_leaf,
    _frequency_label,
    _recurring_display_amount,
    _refresh_row,
    _usd,
    dollars_to_cents,
    goal_shortfall_caption,
    target_note_copy,
)
from app.components.frontend.dashboard.modals.finance_modal.import_preview import (
    import_preview_body,
)
from app.components.frontend.dashboard.modals.finance_modal.import_summary import (
    import_identical_body,
    import_summary_body,
    investment_import_preview_body,
    investment_import_summary_body,
    investment_target_options,
)
from app.components.frontend.dashboard.modals.finance_modal.no_payee_panel import (
    NoPayeePanel,
)
from app.components.frontend.dashboard.modals.finance_modal.overview_tab import (
    OverviewTab,
)
from app.components.frontend.dashboard.modals.finance_modal.review_tab import ReviewTab
from app.components.frontend.dashboard.modals.finance_modal.sidebar import (
    AccountsSidebar,
)
from app.components.frontend.dashboard.modals.finance_modal.stat_details import (
    StatDetailPopup,
    equation_rows,
    stat_detail_caption,
    stat_detail_panel,
    stat_window_label,
)
from app.components.frontend.dashboard.modals.finance_modal.trades_view import (
    trade_detail_sections,
    trades_within_page,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel import (
    TransactionsPanel,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
    fetch_tag_options,
    post_tag,
    register_columns,
    register_count_label,
    transaction_detail_hero,
    transaction_detail_sections,
    transaction_table,
    transaction_tag_chips,
    transaction_tooltip,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_panel import (
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import ledger_amount_color

__all__ = [
    "_category_leaf",
    "_frequency_label",
    "_recurring_display_amount",
    "_refresh_row",
    "_usd",
    "BILL_FREQUENCY_OPTIONS",
    "FinancePanel",
    "_DECLARE_GROUP_CHROME",
    "_DENSE_ROW_HEIGHT",
    "_DIALOG_FIXED_CHROME",
    "_FREQUENCY_LABELS",
    "_GROUP_DIALOG_CHROME",
    "_GROUP_TABLE_MIN_HEIGHT",
    "_account_display_balance",
    "_amount_cell",
    "_declare_body_height",
    "_group_table_height",
    "_transaction_expanded_content",
    "ledger_amount_color",
    "AccountFilter",
    "AccountFilterButton",
    "AccountsSidebar",
    "AccountsTab",
    "BudgetPanel",
    "CompactIconButton",
    "ConnectionCard",
    "ConnectionsTab",
    "FinanceDetailDialog",
    "NoPayeePanel",
    "OverviewTab",
    "ReviewTab",
    "StatDetailPopup",
    "TransactionsPanel",
    "UncategorizedPanel",
    "apply_category_picks",
    "budget_lines_grid",
    "budget_stats_cells",
    "budget_suggestion_caption",
    "close_gap_row_copy",
    "compact_budget_row",
    "contribution_preview",
    "create_category",
    "dollars_to_cents",
    "goal_shortfall_caption",
    "target_note_copy",
    "envelope_card",
    "equation_rows",
    "fetch_tag_options",
    "goal_amounts_line",
    "goal_eta_caption",
    "goal_suggestion_message",
    "import_identical_body",
    "import_preview_body",
    "import_summary_body",
    "investment_import_preview_body",
    "investment_import_summary_body",
    "investment_target_options",
    "linkable_account_options",
    "outlook_chip",
    "outlook_month_label",
    "outlook_stats_cells",
    "post_tag",
    "register_columns",
    "register_count_label",
    "savings_goal_card",
    "stat_detail_caption",
    "stat_detail_panel",
    "stat_window_label",
    "trade_detail_sections",
    "trades_within_page",
    "transaction_detail_hero",
    "transaction_detail_sections",
    "transaction_table",
    "transaction_tag_chips",
    "transaction_tooltip",
]
