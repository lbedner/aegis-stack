"""Every tab answers to the one account filter.

It sits above the tab strip and reads "All accounts", so it looks global.
It was not: only Overview, Uncategorized and No payee ever registered a
listener, and the rest silently ignored it - which is why changing it
appeared to stop working depending on which tab you were on.
"""

import inspect

from app.components.frontend.dashboard.modals import (
    finance_modal,
    finance_payees_tab,
    finance_recurring_tab,
)

# Every panel that lists money, and the handler each uses.
PANELS = [
    (finance_modal, "OverviewTab"),
    (finance_modal, "TransactionsPanel"),
    (finance_modal, "UncategorizedPanel"),
    (finance_modal, "NoPayeePanel"),
    (finance_recurring_tab, "RecurringTab"),
    (finance_recurring_tab, "ProjectionPanel"),
    (finance_payees_tab, "PayeesTab"),
]


class TestEveryPanelListens:
    def test_each_panel_registers_a_filter_listener(self) -> None:
        from app.components.frontend.dashboard.modals.finance_panel import (
            FinancePanel,
        )

        missing = []
        for module, name in PANELS:
            cls = getattr(module, name)
            # A FinancePanel registers in the base __init__ - enforced by
            # inheritance now, which is exactly what this guard wanted:
            # the per-panel copies it used to grep for were the drift
            # risk (see test_finance_panel_lifecycle).
            if issubclass(cls, FinancePanel):
                continue
            source = inspect.getsource(cls)
            if "register_filter_listener(" not in source:
                missing.append(name)
        assert missing == [], f"these ignore the global filter: {missing}"

    def test_each_panel_reads_the_filter(self) -> None:
        missing = []
        for module, name in PANELS:
            source = inspect.getsource(getattr(module, name))
            if "_account_filter" not in source:
                missing.append(name)
        assert missing == [], f"these never consult the filter: {missing}"

    def test_the_dialog_hands_it_to_every_tab(self) -> None:
        """A panel that accepts the filter but is constructed without it
        silently falls back to its own empty one - listening to nothing."""
        source = inspect.getsource(finance_modal.FinanceDetailDialog)
        factories = source[source.index("factories:") :]
        for tab in ("AccountsTab", "RecurringTab", "ProjectionPanel", "SettingsTab"):
            index = factories.index(tab)
            window = factories[index : index + 160]
            assert "self._account_filter" in window, f"{tab} built without the filter"
