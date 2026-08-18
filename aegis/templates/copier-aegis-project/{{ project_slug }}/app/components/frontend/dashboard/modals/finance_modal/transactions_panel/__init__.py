"""The Accounts-tab register panel, split by concern.

``panel`` owns state and the load/selection spine; ``imports_flow``,
``declare``, ``bulk`` and ``manage`` are mixins over the shared state
contract in ``base``. Import ``TransactionsPanel`` from here - the split
is internal.
"""

from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.panel import (
    TransactionsPanel,
)

__all__ = ["TransactionsPanel"]
