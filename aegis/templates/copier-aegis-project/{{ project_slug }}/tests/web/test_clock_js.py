"""The scheduler clock's job-moving logic (static/js/clock.js), run in node.

The browser only turns angles the server computed; these are the rules it
applies while a job is dragged to a new time.
"""

from pathlib import Path

import pytest

from tests.web.node import call

CLOCK_JS = Path("app/components/web_frontend/static/js/clock.js")


@pytest.mark.parametrize(
    ("a", "sa", "b", "sb", "expected"),
    [
        (30, 15, 40, 5, True),  # 02:00 for an hour overlaps 02:40
        (30, 15, 50, 5, False),  # ...but not 03:20
        (30, 0, 30, 0, True),  # two jobs at the same minute collide
        (355, 10, 2, 1, True),  # 23:40 for 40 minutes runs past midnight into 00:08
        (0, 0, 180, 0, False),
    ],
)
def test_overlap_of_two_run_windows(
    a: float, sa: float, b: float, sb: float, expected: bool
) -> None:
    assert call(CLOCK_JS, f"c.overlaps({a}, {sa}, {b}, {sb})") is expected


def test_moves_snap_to_five_minutes() -> None:
    assert call(CLOCK_JS, "[c.snap(31), c.snap(31.9), c.snap(359.9)]") == [
        31.25,
        32.5,
        0,
    ]


def test_times_read_off_the_dial() -> None:
    assert call(
        CLOCK_JS,
        "[c.clockTime(0), c.clockTime(30), c.clockTime(48.75), c.clockTime(359.75)]",
    ) == [
        "00:00",
        "02:00",
        "03:15",
        "23:59",
    ]


def test_pointer_angle_is_clockwise_from_the_top() -> None:
    assert call(
        CLOCK_JS,
        "[c.pointerAngle(0, -1), c.pointerAngle(1, 0), c.pointerAngle(0, 1), c.pointerAngle(-1, 0)]",
    ) == [
        0,
        90,
        180,
        270,
    ]
