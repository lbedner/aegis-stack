"""Tests for the line-chart axis helpers.

These are the three things that decide whether a chart reads as a trend or as
a solid block: where the y-axis floor sits, how coarse the tick interval is,
and which x-positions get a label.
"""

from app.components.frontend.dashboard.modals.modal_sections import (
    LineChartCard,
    axis_label_positions,
    chart_floor,
)


class TestChartFloor:
    """A floor pinned to zero squashes a real series into the top few percent."""

    def test_a_tight_band_high_above_zero_does_not_start_at_zero(self) -> None:
        """Eight months of net worth moving 287k to 300k is a 4% band. Anchored
        at zero it draws as a flat line on top of a filled slab."""
        values = [287_324.27, 293_000.0, 299_789.66]

        floor = chart_floor(values)

        assert floor > 280_000, "the floor has to sit near the data, not at zero"
        assert floor < min(values), "the low point must stay inside the plot"

    def test_the_series_never_touches_the_axis(self) -> None:
        values = [100.0, 150.0, 200.0]
        assert chart_floor(values) < min(values)

    def test_a_flat_series_still_gets_a_band(self) -> None:
        """Every point identical means zero span; without a pad the line lands
        exactly on the axis and disappears."""
        values = [500.0, 500.0, 500.0]

        floor = chart_floor(values)

        assert floor < 500.0

    def test_an_all_positive_series_never_implies_it_went_negative(self) -> None:
        """Padding below a small low would draw a chart suggesting the account
        was overdrawn when it never was."""
        values = [1.0, 100.0]

        assert chart_floor(values) == 0.0

    def test_a_negative_series_is_allowed_below_zero(self) -> None:
        values = [-5_000.0, -1_000.0]

        assert chart_floor(values) < -5_000.0

    def test_a_single_point_is_handled(self) -> None:
        assert chart_floor([42.0]) < 42.0

    def test_no_points_falls_back_to_zero(self) -> None:
        assert chart_floor([]) == 0.0


class TestSmartStep:
    """The tick interval has to scale with the data, at any magnitude."""

    def test_a_large_money_range_gets_a_proportionate_interval(self) -> None:
        """A fixed ceiling turned a 300k range into a 100-unit step, which is
        3,000 tick labels and a nonsense top value."""
        step = LineChartCard._smart_step(300_000)

        assert step >= 10_000
        assert 300_000 / step <= 12, "too many ticks to read"

    def test_tick_counts_stay_sane_across_magnitudes(self) -> None:
        for value_range in (50, 500, 5_000, 50_000, 500_000, 5_000_000):
            step = LineChartCard._smart_step(value_range)
            ticks = value_range / step
            assert 1 <= ticks <= 12, f"{value_range} produced {ticks:.1f} ticks"

    def test_steps_are_round_numbers(self) -> None:
        """Axis labels people read should end in zeros."""
        for value_range in (5_000, 14_089, 250_000):
            step = LineChartCard._smart_step(value_range)
            leading = step / 10 ** (len(str(step)) - 1)
            assert leading in (1.0, 2.0, 5.0), f"{step} is not a round interval"

    def test_a_zero_range_does_not_divide_by_zero(self) -> None:
        assert LineChartCard._smart_step(0) >= 1


class TestAxisLabelPositions:
    """The final date is the one people look for, and it must be legible."""

    def test_the_last_position_is_always_labelled(self) -> None:
        assert axis_label_positions(90)[-1] == 89

    def test_the_final_label_never_collides_with_the_one_before_it(self) -> None:
        """90 days on an 8-tick grid puts a tick at 88 and the forced last at
        89: two labels one day apart, rendered on top of each other."""
        for count in range(2, 400):
            positions = axis_label_positions(count)
            step = max(1, count // 8)
            gap = positions[-1] - positions[-2]
            assert gap >= step, f"count={count} produced a {gap}-wide final gap"

    def test_positions_are_sorted_and_unique(self) -> None:
        for count in (1, 2, 7, 8, 9, 90, 365):
            positions = axis_label_positions(count)
            assert positions == sorted(set(positions))
            assert all(0 <= p < count for p in positions)

    def test_a_short_series_labels_every_point(self) -> None:
        assert axis_label_positions(3) == [0, 1, 2]

    def test_a_single_point_is_labelled_once(self) -> None:
        assert axis_label_positions(1) == [0]

    def test_no_points_produces_no_labels(self) -> None:
        assert axis_label_positions(0) == []

    def test_the_label_count_stays_readable(self) -> None:
        for count in (30, 90, 365, 1000):
            assert len(axis_label_positions(count)) <= 12
