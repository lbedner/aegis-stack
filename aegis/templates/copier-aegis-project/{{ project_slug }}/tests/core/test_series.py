"""Time series for live charts (``app.core.series``): whatever a sampler
reads is kept for an hour under its name, one process samples each tick,
at the sampler's pace while someone watches and slowly otherwise; its
latest reading is kept whole for views, events add points without any
polling, and a chart lines the series up on the times they share."""

import pytest

from app.core import series
from app.core.series import Sample, Sampler


def _sampler(reads_made: list[float], name: str = "containers") -> Sampler:
    async def read() -> Sample:
        reads_made.append(1)
        return Sample({"redis:app-redis-1:cpu": 12.5}, latest={"redis": "table"})

    return Sampler(name, read, interval=1.0, idle_interval=15.0)


async def test_a_sample_is_kept_under_its_samplers_name() -> None:
    await series.sample(_sampler([]))
    found = await series.read("containers:redis:", window=60)
    assert {name: [v for _, v in points] for name, points in found.items()} == {
        "app-redis-1:cpu": [12.5]
    }


async def test_the_latest_reading_is_kept_whole_for_views() -> None:
    await series.sample(_sampler([]))
    assert await series.latest("containers") == {"redis": "table"}


async def test_one_process_samples_each_tick() -> None:
    reads_made: list[float] = []
    sampler = _sampler(reads_made, "once")
    await series.sample(sampler)
    await series.sample(sampler)  # another process, same tick
    assert len(reads_made) == 1


async def test_unwatched_it_samples_at_the_idle_pace_and_watched_every_tick() -> None:
    reads_made: list[float] = []
    sampler = _sampler(reads_made, "paced")
    last = await series.tick(sampler, last=float("-inf"), now=100.0)
    last = await series.tick(sampler, last=last, now=101.0)  # nobody watching
    assert len(reads_made) == 1
    await series.watch("paced")
    await series.tick(sampler, last=last, now=102.0)
    assert len(reads_made) == 2


async def test_an_event_is_a_point_without_any_polling() -> None:
    await series.record({"llm:qwen3:tokens_per_second": 42.0})
    found = await series.read("llm:", window=60)
    assert [v for _, v in found["qwen3:tokens_per_second"]] == [42.0]


def test_a_chart_lines_series_up_on_their_shared_times() -> None:
    found = {"a:cpu": [(100.0, 1.0), (105.0, 2.0)], "b:cpu": [(105.0, 3.0)]}
    data = series.chart(found, label=lambda name: name.split(":")[0], fmt="percent")
    assert data["labels"] == [100_000, 105_000]  # ms, for the browser's clock
    assert data["series"] == [
        {"label": "a", "values": [1.0, 2.0]},
        {"label": "b", "values": [None, 3.0]},
    ]
    assert data["points"] == 3  # what every view reads to say "nothing yet"
    assert (data["x"], data["format"]) == ("time", "percent")


def test_any_chart_can_mark_where_warning_and_alert_begin() -> None:
    """``thresholds`` (``app.core.thresholds.levels``): the ones in reach."""
    found = {"depth": [(100.0, 30.0)]}
    data = series.chart(
        found,
        str,
        thresholds=[{"value": 50, "tone": "warn"}, {"value": 90, "tone": "error"}],
    )
    assert data["thresholds"] == [{"value": 50, "tone": "warn"}]
    assert "thresholds" not in series.chart(found, str)


def test_a_live_frame_carries_only_what_the_chart_lacks() -> None:
    """A live chart already holds what it was sent: the next frame carries
    the times from the last one sent on (that bucket may still be filling),
    and still counts every point, so "nothing yet" reads right."""
    drawn = {
        "labels": [1000, 2000, 3000],
        "series": [{"label": "a", "values": [1.0, 2.0, 3.0]}],
        "x": "time",
        "points": 3,
        "window": [0, 3000],
    }
    newer = series.since(drawn, 2000)
    assert newer["labels"] == [2000, 3000]
    assert newer["series"] == [{"label": "a", "values": [2.0, 3.0]}]
    assert (newer["points"], newer["window"]) == (3, [0, 3000])


def test_a_threshold_is_drawn_only_in_reach_of_the_data() -> None:
    """An alert at 640% (eight cores) would flatten a 5% line, so a guide
    shows once the data is within half of it; the page draws what it is sent."""
    lines = [{"label": "a", "values": [None, 4.0]}]
    levels = [{"value": 8, "tone": "warn"}, {"value": 10, "tone": "error"}]
    assert series.thresholds_in_reach(lines, levels) == [{"value": 8, "tone": "warn"}]


def test_a_chart_spans_its_window_even_with_nothing_in_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The axis runs from ``window`` ago to now, so an empty chart reads
    right and a live one keeps moving."""
    monkeypatch.setattr(series.time, "time", lambda: 1000.0)
    data = series.chart({}, label=str, window=900)
    assert data["window"] == [100_000, 1_000_000]
    assert (data["series"], data["points"]) == ([], 0)


def test_the_windows_read_like_every_other_range_row() -> None:
    """The chips' compact labels (as ``web_frontend/ranges.py`` has them),
    never longer than what is kept."""
    assert [label for _, label in series.WINDOWS] == ["15m", "30m", "1h"]
    assert max(seconds for seconds, _ in series.WINDOWS) <= series.KEEP_SECONDS
    assert series.window_of("1800") == 1800
    assert series.window_of("86400") == series.DEFAULT_WINDOW  # not on offer
    assert series.window_of(None) == series.DEFAULT_WINDOW
    assert series.phrase(900) == "the last 15 minutes"
    assert series.phrase(3600) == "the last hour"


def test_a_long_window_is_averaged_into_at_most_max_points() -> None:
    """An hour at a point a second is too much to draw and re-send each
    tick: it is bucketed on fixed boundaries, so a bucket keeps its place
    as the window moves and only the newest one changes."""
    found = {"a:cpu": [(float(t), float(t % 2)) for t in range(40)]}
    data = series.chart(found, label=str, max_points=10)
    assert data["labels"] == [t * 1000 for t in range(0, 40, 4)]
    assert data["series"][0]["values"] == [0.5] * 10


async def test_a_view_reads_the_kept_reading_and_reads_itself_only_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``reading``: what every view of a sampler shows. The kept reading
    when there is one (taking the first sample if there is none); a read of
    its own only when another process holds this tick and nothing is kept."""
    reads_made: list[float] = []
    sampler = _sampler(reads_made, "viewed")
    assert await series.reading(sampler) == {"redis": "table"}
    assert await series.reading(sampler) == {"redis": "table"}
    assert len(reads_made) == 1

    async def held(sampler: Sampler, *, fill: bool = True) -> None:
        return None

    monkeypatch.setattr(series, "current", held)
    assert await series.reading(sampler) == {"redis": "table"}
    assert len(reads_made) == 2


# A line drawn small (a queue's waiting jobs, a card's CPU): ``sparkline``.
def test_the_waiting_line_spans_the_box() -> None:
    points = series.sparkline([0, 10, 5])
    assert points == "0.0,24.0 50.0,0.0 100.0,12.0"  # the 100 by 24 box


def test_a_flat_or_single_line_sits_on_the_floor() -> None:
    assert series.sparkline([0, 0]) == "0.0,24.0 100.0,24.0"
    assert series.sparkline([]) == ""


def test_a_steady_line_draws_the_same_however_long() -> None:
    """An idle or steady queue must not change the page every sample."""
    assert series.sparkline([0] * 3) == "0.0,24.0 100.0,24.0"
    assert series.sparkline([7] * 2) == (series.sparkline([7] * 50))


def test_a_long_line_draws_a_point_a_unit_keeping_its_peaks() -> None:
    """Fifteen minutes is 900 ticks; the box is 100 wide, so each point is
    the highest of its stretch, and a one-tick spike still shows."""
    values = [1.0] * 900
    values[450] = 9.0
    points = series.sparkline(values).split()
    assert len(points) == 100
    assert sum(p.endswith(",0.0") for p in points) == 1  # the spike, at the top


async def test_a_read_can_keep_only_the_series_it_draws() -> None:
    """A card draws CPU and memory alone: ``ending`` reads just those series,
    not every metric under the prefix."""
    await series.record({"probe:a-1:cpu": 1.0, "probe:a-1:net_in": 9.0})
    found = await series.read("probe:", 60, ending=(":cpu",))
    assert list(found) == ["a-1:cpu"]
