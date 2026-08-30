"""The Overview tab's Pending changes section.

The queue lays out as one horizontal band: fixed-width cards side by
side, scrolling sideways on overflow - approvals read as a short rail
above the page, never a column pushing the net worth chart down.
"""

import flet as ft


class TestCardsLayOutHorizontally:
    def test_the_card_rail_is_a_sideways_scrolling_row(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal.pending_changes import (
            PendingChangesSection,
        )

        section = PendingChangesSection(page=None)

        rail = section._cards
        assert isinstance(rail, ft.Row)
        assert rail.scroll == ft.ScrollMode.AUTO
        assert rail.vertical_alignment == ft.CrossAxisAlignment.START
