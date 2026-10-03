"""How charts.js formats axis ticks and tooltips, run in node.

A chart's numbers are plain unless its data says ``"format": "money"``:
a generic macro must not read jobs per hour as dollars.
"""

import json
from pathlib import Path

import pytest

from tests.test_formatting import CHART_FORMATS
from tests.web.node import call, run

CHARTS_JS = Path("app/components/web_frontend/static/js/charts.js")


def _format(value: float, fmt: str | None) -> object:
    return call(CHARTS_JS, f"c.formatValue({value}, {json.dumps(fmt)})")


@pytest.mark.parametrize(("value", "fmt", "expected"), CHART_FORMATS)
def test_a_value_reads_the_same_in_the_browser(
    value: float, fmt: str | None, expected: str
) -> None:
    """Chart.js formats its own ticks, so the browser keeps a twin of
    ``format_value``; both are held to one table (``CHART_FORMATS``)."""
    assert _format(value, fmt) == expected


REFRESH = """
const c = require(CHARTS_JS);
const canvas = {};
let mode = null;
const chart = { data: { labels: [1], datasets: [{ label: 'a', data: [1] }] },
                update: (m) => { mode = m; } };
global.document = { querySelector: (sel) =>
  (sel === 'canvas[data-chart-data="chart-x-data"]' ? canvas : null) };
const Chart = { getChart: (el) => (el === canvas ? chart : undefined) };
const script = { id: 'chart-x-data',
  textContent: JSON.stringify({ labels: [1, 2], series: [{ label: 'a', values: [3, 4] }] }) };
const refreshed = c.refresh(Chart, script);
console.log(JSON.stringify({ refreshed, labels: chart.data.labels,
  values: chart.data.datasets[0].data, mode }));
"""


def test_a_chart_whose_data_arrives_again_updates_in_place() -> None:
    """A live chart (``chart_panel(live=...)``): its data script swaps in
    over the page's stream and the drawn chart takes it without a redraw."""
    assert run(REFRESH, CHARTS_JS=CHARTS_JS) == {
        "refreshed": True,
        "labels": [1, 2],
        "values": [3, 4],
        "mode": "none",
    }


TIME_REFRESH = """
const c = require(CHARTS_JS);
const empty = { hidden: false };
const canvas = { dataset: { chart: 'line' }, parentElement: { querySelector: () => (
  { classList: { toggle: (c, on) => { empty.hidden = on; } } }) } };
let mode = 'unset';
const kept = { x: 2000, y: 2 };
const points = [{ x: 1000, y: 1 }, kept];
// The newest bucket fills as the tick goes on: its point moves, not a new one.
const chart = { data: { datasets: [{ label: 'a', data: points }] },
                options: { scales: { x: {} } },
                update: (m) => { mode = m ?? null; } };
global.document = { querySelector: () => canvas };
const Chart = { getChart: () => chart };
const script = { id: 'chart-x-data', textContent: JSON.stringify(
  { labels: [2000, 3000], series: [{ label: 'a', values: [2.5, 5] }], x: 'time',
    window: [1500, 3500], points: 2 }) };
c.refresh(Chart, script);
const data = chart.data.datasets[0].data;
console.log(JSON.stringify({ same_array: data === points, kept: data[0] === kept,
  data, window: [chart.options.scales.x.min, chart.options.scales.x.max], mode,
  empty_hidden: empty.hidden }));
"""


def test_a_time_chart_slides_on_to_its_new_points() -> None:
    """Real time: the oldest point leaves and the new one joins the same
    array, so every other point (and a hovered tooltip) stays put. Drawn
    without animation: a tick moves the line under a pixel, and an animated
    new point swoops in from the axis, so the line's end redraws itself."""
    assert run(TIME_REFRESH, CHARTS_JS=CHARTS_JS) == {
        "same_array": True,
        "kept": True,
        "data": [{"x": 2000, "y": 2.5}, {"x": 3000, "y": 5}],
        "window": [1500, 3500],
        "mode": "none",
        "empty_hidden": True,
    }


def test_time_ticks_land_on_the_clock() -> None:
    """Every three minutes over 15, five over 30, ten over an hour, on the
    minute, not wherever the window happens to start."""
    start = 1_790_996_327_000  # 11:38:47
    ticks = call(CHARTS_JS, f"c.timeTicks({start}, {start + 15 * 60_000})")
    assert ticks == [
        t for t in range(start, start + 15 * 60_000 + 1) if t % 180_000 == 0
    ]
    assert len(call(CHARTS_JS, f"c.timeTicks({start}, {start + 3_600_000})")) == 6


def test_byte_axes_step_in_round_units() -> None:
    """18.6 GB tops out on 5 GB steps, not 0.2 GB ones."""
    gb = 1024**3
    assert call(CHARTS_JS, f"c.byteStep({18.6 * gb})") == 5 * gb
    assert call(CHARTS_JS, f"c.byteStep({300 * 1024**2})") == 50 * 1024**2
