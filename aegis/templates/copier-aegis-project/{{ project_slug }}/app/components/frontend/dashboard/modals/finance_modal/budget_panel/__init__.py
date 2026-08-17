"""The Budget tab, split by sub-tab.

``panel`` owns state and the load/render spine; ``suggestions``,
``lines_tab``, ``goals_tab`` and ``envelopes_tab`` are mixins over the
shared contract in ``base``. Import ``BudgetPanel`` from here.
"""

from app.components.frontend.dashboard.modals.finance_modal.budget_panel.panel import (
    BudgetPanel,
)

__all__ = ["BudgetPanel"]
