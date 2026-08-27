"""Budget lines flow three to a row instead of stacking.

Every line was a full-width row, so a dozen budget lines meant a dozen
rows of mostly empty width and a page of scrolling. Each line is a
label, a small progress bar and two numbers - a third of the modal is
plenty ("hell, 3 can fit").
"""

import flet as ft

from app.components.frontend.dashboard.modals.finance_modal import (
    budget_lines_grid,
)
from tests.components.frontend._tree import texts as _texts
from tests.components.frontend._tree import walk as _walk


class TestTheGrid:
    def test_lines_flow_three_per_row_with_room(self) -> None:
        """Flet's 12-column grid: 4/12 wide on a large window is three
        per row, 6/12 on a middling one is two, full-width when cramped
        - the narrow case degrades to exactly the old layout."""
        grid = budget_lines_grid([ft.Container(), ft.Container()])
        assert isinstance(grid, ft.ResponsiveRow)
        for cell in grid.controls:
            assert cell.col == {"sm": 12, "md": 6, "lg": 4}

    def test_every_line_is_present(self) -> None:
        rows = [ft.Container() for _ in range(7)]
        grid = budget_lines_grid(rows)
        assert [c.content for c in grid.controls] == rows


class TestTheCompactRow:
    """The flexible row, rebuilt on the trim rows' geometry.

    The old row stacked label / 8px bar / a 16px-bold percent line -
    three storeys tall, which is why a dozen limits filled the screen
    while "Close the gap" fit twelve in four lines ("the close the gap
    section looks amazing... show more in less space").
    """

    def _row(self, allocated=139_882, spent=40_617, status="good"):
        from app.components.frontend.dashboard.modals.finance_modal import (
            compact_budget_row,
        )

        return compact_budget_row("Groceries", allocated, spent, status)

    def test_it_carries_name_figures_and_percent(self) -> None:
        texts = _texts(self._row())
        assert "Groceries" in texts
        assert "$406.17 of $1,398.82" in texts
        assert "29%" in texts

    def test_the_bar_is_a_strip_not_a_storey(self) -> None:
        bars = [c for c in _walk(self._row()) if isinstance(c, ft.ProgressBar)]
        assert len(bars) == 1
        assert bars[0].height == 4

    def test_a_healthy_line_wears_no_accent_on_its_percent(self) -> None:
        from app.components.frontend.theme import AegisTheme as Theme

        row = self._row(status="good")
        pct = next(c for c in _walk(row) if getattr(c, "value", None) == "29%")
        assert pct.color == Theme.Colors.TEXT_SECONDARY

    def test_trouble_colors_the_percent(self) -> None:
        from app.components.frontend.theme import AegisTheme as Theme

        critical = self._row(spent=179_882, status="critical")
        pct = next(
            c for c in _walk(critical) if str(getattr(c, "value", "")).endswith("%")
        )
        assert pct.color == Theme.Colors.ERROR

    def test_over_budget_shows_the_real_percent_on_a_full_bar(self) -> None:
        """The bar clamps (Flet has no over-100 concept) but the number
        must not lie: 129% reads as 129%, not 100%."""
        row = self._row(spent=179_882, status="critical")
        bars = [c for c in _walk(row) if isinstance(c, ft.ProgressBar)]
        assert bars[0].value == 1.0
        assert "129%" in _texts(row)

    def test_a_zero_limit_row_does_not_divide_by_zero(self) -> None:
        texts = _texts(self._row(allocated=0, spent=1_000))
        assert "100%" in texts
