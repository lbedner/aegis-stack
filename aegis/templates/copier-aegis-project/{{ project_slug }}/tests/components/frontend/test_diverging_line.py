"""A line that is teal above zero and red below it.

The projection's old treatment coloured the WHOLE line by where it
ENDED - a forecast that dips underwater for a week but recovers reads
all-teal, and one that ends $10 short reads all-red. Polarity belongs on
the segments themselves: zero is the meaningful midpoint, and the days
below it are the entire point of the chart.

One series does it (a hard-stop vertical gradient on the stroke, cutoff
fills either side of zero), so tooltips and hover stay intact. Colour is
REINFORCEMENT here, not the only channel - sign is already encoded by
position against the axis - which is what keeps a teal/red pair
accessible.
"""

import flet as ft

from app.components.frontend.dashboard.modals.modal_sections import (
    LineChartCard,
    LineSeries,
    diverging_stop,
)

TEAL = "#17CCBF"
RED = "#EF4444"


class TestTheStopMath:
    def test_the_split_lands_at_its_fraction_of_the_range(self) -> None:
        """Floor -100, ceiling 300: zero sits three quarters of the way
        DOWN from the top, which is where the colour must change."""
        assert diverging_stop(floor=-100, ceiling=300, split=0) == 0.75

    def test_an_all_positive_range_needs_no_split(self) -> None:
        assert diverging_stop(floor=50, ceiling=300, split=0) >= 1.0

    def test_an_all_negative_range_is_all_below(self) -> None:
        assert diverging_stop(floor=-300, ceiling=-50, split=0) <= 0.0

    def test_a_flat_range_does_not_divide_by_zero(self) -> None:
        assert diverging_stop(floor=100, ceiling=100, split=0) >= 1.0


def _card(points: list[tuple[int, float]], min_y: float) -> ft.LineChartData:
    card = LineChartCard(
        title="t",
        x_labels=[str(i) for i, _ in points],
        series=[
            LineSeries(
                label="Balance",
                color=TEAL,
                points=points,
                fill=True,
                split_y=0.0,
                split_below_color=RED,
            )
        ],
        min_y=min_y,
    )

    def find(node: object) -> ft.LineChartData | None:
        if isinstance(node, ft.LineChart):
            return node.data_series[0]
        for child in [getattr(node, "content", None)] + list(
            getattr(node, "controls", None) or []
        ):
            if child is not None:
                found = find(child)
                if found is not None:
                    return found
        return None

    series = find(card)
    assert series is not None
    return series


class TestTheRenderedSeries:
    def test_a_mixed_range_gets_the_hard_stop_gradient(self) -> None:
        data = _card([(0, -100), (1, 300)], min_y=-100)
        gradient = data.gradient
        assert gradient is not None
        assert gradient.colors == [TEAL, TEAL, RED, RED]
        assert gradient.stops == [0.0, 0.75, 0.75, 1.0]
        # Top-to-bottom, or the fractions mean nothing.
        assert gradient.begin == ft.alignment.top_center
        assert gradient.end == ft.alignment.bottom_center

    def test_the_fills_meet_at_zero(self) -> None:
        """Below-line fill covers line-down-to-zero (the positive area),
        above-line fill covers line-up-to-zero (the negative area). Both
        cut at the split, so the tint always sits between the line and
        the axis - the area that IS the money."""
        data = _card([(0, -100), (1, 300)], min_y=-100)
        assert data.below_line_cutoff_y == 0.0
        assert data.above_line_cutoff_y == 0.0
        assert data.below_line_bgcolor is not None
        assert data.above_line_bgcolor is not None

    def test_an_all_positive_window_stays_a_plain_teal_line(self) -> None:
        """The 7d view of a healthy week must look exactly like it always
        has - no gradient machinery, no red anywhere."""
        data = _card([(0, 50), (1, 300)], min_y=0)
        assert data.gradient is None
        assert data.color == TEAL
        assert data.above_line_bgcolor is None

    def test_an_all_negative_window_is_a_solid_red_line(self) -> None:
        data = _card([(0, -300), (1, -50)], min_y=-300)
        assert data.gradient is None
        assert data.color == RED


class TestTheProjectionUsesIt:
    def test_the_panel_splits_at_zero_instead_of_flipping_on_the_end(
        self,
    ) -> None:
        """The wiring pin: the old whole-line flip keyed on the FINAL
        balance, which coloured a mid-window dip teal and a $10 miss
        all-red."""
        import inspect

        from app.components.frontend.dashboard.modals import finance_recurring_tab

        source = inspect.getsource(finance_recurring_tab.ProjectionPanel)
        assert "split_y=0" in source
        assert "line_color" not in source
