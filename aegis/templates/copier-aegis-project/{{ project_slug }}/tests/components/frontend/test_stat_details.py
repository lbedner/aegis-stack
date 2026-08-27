"""The Budget header's click-through popup."""

from typing import Any

from tests.components.frontend._fakes import tap


class TestPanelChrome:
    """The panel is a Dropdown panel like the account filter's, and has to
    wear the same padding: rows that run edge to edge read as text tearing
    through the popup's border."""

    def test_rows_carry_the_house_horizontal_padding(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal.stat_details import (
            stat_detail_panel,
        )
        from app.components.frontend.theme import AegisTheme as Theme

        panel = stat_detail_panel(
            "Everything else",
            [{"label": "Health & Fitness:Dentist", "value": 73_209}],
            footer="last 3 months",
        )

        padded = [
            c
            for c in panel.controls
            if getattr(getattr(c, "padding", None), "left", 0) >= Theme.Spacing.MD
        ]
        assert len(padded) == len(panel.controls), "every line needs side padding"


class TestStatPopupHugsItsContent:
    """One popup serves a four-row income list and a twenty-row category
    list; a fixed height is right only for the second - the short list
    was stranded at the top of a mostly-empty full-height box."""

    @staticmethod
    def _popup() -> Any:
        from app.components.frontend.dashboard.modals.finance_modal.stat_details import (
            StatDetailPopup,
        )

        return StatDetailPopup()

    @staticmethod
    def _rows(n: int) -> list[dict[str, Any]]:
        return [{"label": f"Row {i}", "value": 1_000} for i in range(n)]

    def test_a_short_list_does_not_reserve_the_full_height(self) -> None:
        popup = self._popup()
        popup.open_at(tap(), "Confirmed income", self._rows(4))

        assert popup._panel_frame.height is not None
        assert popup._panel_frame.height < 380

    def test_a_long_list_is_capped_and_scrolls(self) -> None:
        popup = self._popup()
        popup.open_at(tap(), "Everything else", self._rows(20))

        assert popup._panel_frame.height == 380
