"""The Overview tab: net worth, assets and liabilities with a per-group breakdown."""

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
    BaseIconButton,
    H3Text,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.base_popup import OverlayStyledDialog

# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
# One height for every Overview card, so the row has a single baseline.
# Named slices in the spending donut (and rows in the list under it) before
# the tail folds into "Other". Five left "Other" as the biggest slice on any
# real ledger, which hides exactly the breakdown the card exists to show.
# Measured against a real ledger (23 parent-level categories after the
# spending_by_category rollup): 10 slices still left "Other" at 16.3%; 15
# gets it to 5.3%, with everything past #15 individually under 1% of total
# spend - the tail at that point really is "everything else", not a few
# disguised top categories. PieChartCard's legend scrolls within its fixed
# height (modal_sections.py) rather than clipping, so this isn't bounded
# by legend space anymore.
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
from app.components.frontend.dashboard.modals.finance_modal.overview_drilldowns import (
    OverviewDrilldownMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.overview_load import (
    OverviewLoadMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.pending_changes import (
    PendingChangesBanner,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_panel import (
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
)
from app.components.frontend.theme import AegisTheme as Theme


class OverviewTab(OverviewLoadMixin, OverviewDrilldownMixin, FinancePanel):
    """Net-worth summary: assets, liabilities, net worth, a per-group breakdown,
    and spending by category. No sidebar — this is the landing view."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
        on_open_review: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._body = ft.Column(
            spacing=Theme.Spacing.LG, scroll=ft.ScrollMode.AUTO, expand=True
        )
        # Built once, on first open, then reused - see _open_uncategorized.
        # A fresh dialog + UncategorizedPanel on every click (the original
        # design) never actually left page.overlay once closed: Flet's
        # page.close()/`.open = False` only hides a dialog, it doesn't
        # remove it or its subtree - so every reopen was a permanent leak.
        # This mirrors _open_modal's own cache pattern (card_utils.py) for
        # exactly that reason.
        #
        # OverlayStyledDialog, not StyledAlertDialog: this dialog's body
        # (UncategorizedPanel) hosts its own account-filter Dropdown - a
        # page.overlay-based popup - and a real ft.AlertDialog (what
        # StyledAlertDialog wraps) renders through Flutter's own dialog
        # route, which always paints above page.overlay content regardless
        # of append order. That nested Dropdown opened BEHIND this dialog
        # instead of above it (confirmed live) until this swap - see
        # OverlayStyledDialog's own docstring (base_popup.py).
        self._uncategorized_dialog: OverlayStyledDialog | None = None
        self._uncategorized_panel: UncategorizedPanel | None = None
        # One window drives every card on the page, so the pie, the bars
        # and the net-worth line always describe the same span - three
        # charts on different periods invite false comparisons.
        self._days = 180
        # Parallel to the pie's own ``slices`` (index i here -> the
        # category name(s) slice i represents) - rebuilt every ``_load``.
        # A named slice is one parent category (spending_by_category's own
        # rollup); "Other" is every name that didn't make the cut, which
        # is why this is a list of lists, not a list of names.
        self._pie_slice_categories: list[list[str]] = []
        # Header matches the Projected tab: title + subtitle on the left,
        # the headline figures bare against the right edge. Cards below
        # would cost the chart a card's height and box it twice.
        self._pending_changes = PendingChangesBanner(
            page, on_open_review=on_open_review
        )
        self._stats = ft.Row(
            [],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = ft.Column(
            [
                self._pending_changes,
                ft.Row(
                    [
                        ft.Column(
                            [
                                H3Text("Net worth"),
                                SecondaryText(
                                    "Everything you own, less everything you owe"
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Container(expand=True),
                        DateRangeChips(
                            options=[
                                ("1m", 30),
                                ("3m", 90),
                                ("6m", 180),
                                ("1y", 365),
                                ("All", 9999),
                            ],
                            selected_days=self._days,
                            on_change=self._on_range,
                        ),
                        BaseIconButton(
                            self._load,
                            icon=ft.Icons.REFRESH,
                            icon_size=18,
                            tooltip="Refresh overview",
                        ),
                        self._stats,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.LG,
                ),
                # Separates the headline banner from the charts below, so
                # the figures read as a summary OF the page rather than as
                # a caption on the first card.
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def _on_range(self, days: int) -> None:
        self._days = days
        self._reload()
