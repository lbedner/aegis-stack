"""The scheduler clock's job-moving logic (static/js/clock.js), run in node.

The browser only turns angles the server computed; these are the rules it
applies while a job is dragged to a new time.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

CLOCK_JS = Path("app/components/web_frontend/static/js/clock.js")


def _call(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = f"const c = require({json.dumps(str(CLOCK_JS.resolve()))}); console.log(JSON.stringify({expression}));"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


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
def test_overlap_of_two_run_windows(a: float, sa: float, b: float, sb: float, expected: bool) -> None:
    assert _call(f"c.overlaps({a}, {sa}, {b}, {sb})") is expected


def test_moves_snap_to_five_minutes() -> None:
    assert _call("[c.snap(31), c.snap(31.9), c.snap(359.9)]") == [31.25, 32.5, 0]


def test_times_read_off_the_dial() -> None:
    assert _call("[c.clockTime(0), c.clockTime(30), c.clockTime(48.75), c.clockTime(359.75)]") == [
        "00:00", "02:00", "03:15", "23:59",
    ]


def test_pointer_angle_is_clockwise_from_the_top() -> None:
    assert _call("[c.pointerAngle(0, -1), c.pointerAngle(1, 0), c.pointerAngle(0, 1), c.pointerAngle(-1, 0)]") == [
        0, 90, 180, 270,
    ]
