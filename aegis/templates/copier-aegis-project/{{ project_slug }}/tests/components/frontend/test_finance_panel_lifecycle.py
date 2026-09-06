"""One lifecycle, owned once, for every finance panel.

Each panel used to hand-roll the same trio - fetch on mount, reload on
account-filter change, reload on tab revisit - and each copy drifted:
Budget shipped without the filter leg, Projection shipped without the
revisit leg (a confirmed payment stayed invisible on the Projected page
until the dialog reopened - confirmed live). The base owns all three;
a panel implements ``_load`` and cannot forget a leg it never writes.
"""

from types import SimpleNamespace

from app.components.frontend.dashboard.modals.finance_attention_tab import AttentionTab
from app.components.frontend.dashboard.modals.finance_modal import (
    AccountsTab,
    BudgetPanel,
    ConnectionsTab,
    FinancePanel,
    NoPayeePanel,
    OverviewTab,
    ReviewTab,
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.finance_payees_tab import PayeesTab
from app.components.frontend.dashboard.modals.finance_recurring_tab import (
    ProjectionPanel,
    RecurringTab,
)


class _Probe(FinancePanel):
    def __init__(self, page, **kwargs) -> None:
        super().__init__(page, **kwargs)
        self.loads = 0

    async def _load(self) -> None:
        self.loads += 1


def _fake_page(calls):
    return SimpleNamespace(run_task=lambda fn, *a: calls.append(fn))


class TestTheBaseOwnsTheTrio:
    def test_mount_filter_change_and_revisit_all_drive_load(self) -> None:
        calls: list = []
        panel = _Probe(_fake_page(calls))

        panel.did_mount()
        panel._on_account_filter_change()
        panel.refresh_on_revisit()

        assert len(calls) == 3
        assert all(fn == panel._load for fn in calls)

    def test_it_registers_with_the_shared_filter(self) -> None:
        listeners: list = []
        panel = _Probe(_fake_page([]), register_filter_listener=listeners.append)
        assert listeners == [panel._on_account_filter_change]

    def test_no_page_means_no_crash(self) -> None:
        panel = _Probe(None)
        panel.refresh_on_revisit()  # nothing to run against; must not raise


class TestEveryPanelInherits:
    """The roster. A panel on it cannot re-introduce the drift class."""

    ROSTER = [
        OverviewTab,
        BudgetPanel,
        UncategorizedPanel,
        NoPayeePanel,
        ReviewTab,
        ConnectionsTab,
        AttentionTab,
        ProjectionPanel,
        RecurringTab,
        PayeesTab,
    ]

    def test_the_roster_rides_the_base(self) -> None:
        for cls in self.ROSTER:
            assert issubclass(cls, FinancePanel), cls.__name__

    def test_every_rostered_panel_answers_a_revisit(self) -> None:
        """The leg Projection forgot - now unforgettable."""
        for cls in self.ROSTER:
            assert callable(getattr(cls, "refresh_on_revisit", None)), cls.__name__

    def test_no_panel_inherits_the_abstract_load(self) -> None:
        """The base raises NotImplementedError so a panel cannot forget to
        implement it. ReviewTab did forget: it is pure composition, its
        four sub-tabs each own their own read, so it looked complete - and
        logged a traceback on every mount and every account-filter change.
        A composed panel still has to say so, with a no-op."""
        for cls in self.ROSTER:
            assert cls._load is not FinancePanel._load, (
                f"{cls.__name__} inherits the abstract _load and will raise"
            )

    def test_custom_filter_behavior_survives(self) -> None:
        """DRY must not steamroll deliberate differences: Bills & Income
        refilters its last fetch locally, Uncategorized debounces with
        kept state - both keep their own handlers."""
        assert (
            RecurringTab._on_account_filter_change
            is not FinancePanel._on_account_filter_change
        )
        assert (
            UncategorizedPanel._on_account_filter_change
            is not FinancePanel._on_account_filter_change
        )

    def test_the_standard_panels_share_one_implementation(self) -> None:
        for cls in (OverviewTab, BudgetPanel, ProjectionPanel, PayeesTab):
            assert (
                cls._on_account_filter_change
                is FinancePanel._on_account_filter_change
            ), cls.__name__

    def test_the_accounts_composite_forwards_revisits(self) -> None:
        """AccountsTab hosts the register rather than loading data itself;
        a revisit must still reach the panel it hosts."""
        assert callable(getattr(AccountsTab, "refresh_on_revisit", None))
