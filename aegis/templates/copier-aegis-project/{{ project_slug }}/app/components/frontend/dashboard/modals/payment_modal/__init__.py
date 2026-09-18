"""The payment modal, one module per tab.

``payment_modal.py`` was eleven hundred lines of six tabs. Each tab is
now its own module; this re-exports the names that were importable
before, so nothing outside the package had to change.
"""

from .actions_tab import ActionsTab
from .dialog import PaymentDetailDialog
from .disputes_tab import DisputesTab
from .overview_tab import OverviewTab
from .settings_tab import SettingsTab
from .subscriptions_tab import SubscriptionsTab
from .transactions_tab import TransactionsTab

__all__ = [
    "ActionsTab",
    "DisputesTab",
    "OverviewTab",
    "PaymentDetailDialog",
    "SettingsTab",
    "SubscriptionsTab",
    "TransactionsTab",
]
