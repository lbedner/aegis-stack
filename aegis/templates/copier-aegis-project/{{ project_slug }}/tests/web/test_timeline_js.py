"""The player (static/js/timeline.js), run in node: what is lit at a moment,
where a step back or forward lands, how the clock runs. It knows nothing
of what it plays; a page hands it steps (``when``, ``how long``, what they
light and how)."""

import json
from pathlib import Path
from typing import Any

from tests.web.node import call

TIMELINE_JS = Path("app/components/web_frontend/static/js/timeline.js")

STEPS = [
    {"at": 0, "ms": 40, "targets": ["#server"], "state": "active"},
    {"at": 5, "ms": 3, "targets": ["#db", "#line"], "state": "active"},
    {"at": 10, "ms": 20, "targets": ["#db"], "state": "stall"},
    {"at": 31, "ms": 2, "targets": ["#api"], "state": "failed"},
]


def _js(expression: str) -> Any:
    return call(TIMELINE_JS, expression.replace("STEPS", json.dumps(STEPS)))


def test_a_moment_lights_what_is_running_then_and_what_ran_before() -> None:
    assert _js("c.frameAt(STEPS, 6)") == {
        "#server": "active",
        "#db": "active",
        "#line": "active",
    }
    # The query is over: done; the slow one later holds the same node.
    assert _js("c.frameAt(STEPS, 9)") == {
        "#server": "active",
        "#db": "done",
        "#line": "done",
    }
    assert _js("c.frameAt(STEPS, 12)")["#db"] == "stall"
    assert _js("c.frameAt(STEPS, 32)")["#api"] == "failed"
    assert _js("c.frameAt(STEPS, 50)") == {
        "#server": "done",
        "#db": "done",
        "#line": "done",
        "#api": "done",
    }


def test_a_failure_outranks_whatever_else_lights_the_same_thing() -> None:
    steps = [
        {"at": 0, "ms": 10, "targets": ["#x"], "state": "active"},
        {"at": 2, "ms": 2, "targets": ["#x"], "state": "failed"},
    ]
    assert call(TIMELINE_JS, f"c.frameAt({json.dumps(steps)}, 3)") == {"#x": "failed"}


def test_a_step_too_short_to_see_is_held_for_the_floor() -> None:
    """A 3 ms query at full speed is one frame; held for ``floor`` it shows."""
    assert _js("c.frameAt(STEPS, 9, 0)")["#db"] == "done"
    assert _js("c.frameAt(STEPS, 9, 5)")["#db"] == "active"


def test_stepping_lands_on_each_steps_start() -> None:
    """Forward past the last step is the end; back from the first, the start."""
    assert _js(
        "[c.stepFrom(STEPS, 0, 1), c.stepFrom(STEPS, 7, 1), c.stepFrom(STEPS, 31, 1)]"
    ) == [5, 10, 40]
    assert _js(
        "[c.stepFrom(STEPS, 12, -1), c.stepFrom(STEPS, 10, -1), c.stepFrom(STEPS, 0, -1)]"
    ) == [10, 5, 0]


def test_the_clock_runs_at_its_speed_and_stops_at_the_end() -> None:
    assert _js("c.tick(STEPS, 10, 50, 0.2)") == 20
    assert _js("c.tick(STEPS, 39, 1000, 1)") == 40


def test_a_late_frame_does_not_jump_the_clock() -> None:
    """A frame held up (the page still loading, the tab away) moves the
    clock one frame's worth at most, so a speed plays as long every time."""
    assert _js("c.tick(STEPS, 0, 400, 0.1)") == _js("c.tick(STEPS, 0, 50, 0.1)")


def test_reduced_motion_steps_instead_of_running() -> None:
    """No motion: each tick moves to the next step's start, never between."""
    assert _js("[c.stepFrom(STEPS, 0, 1), c.stepFrom(STEPS, 5, 1)]") == [
        5,
        10,
    ]


def test_the_starting_speed_plays_the_whole_in_a_few_seconds() -> None:
    """The fastest of the speeds offered that still takes a few seconds: a
    40 ms request at a hundredth of real time; a 2 s one in real time."""
    totals = [40, 300, 500, 2000]
    speeds = [1, 0.2, 0.1, 0.01, 0.001]
    found = call(TIMELINE_JS, f"{totals}.map((t) => c.startingSpeed(t, {speeds}))")
    assert found == [0.01, 0.1, 0.2, 1]


def test_the_end_is_when_the_last_step_does() -> None:
    assert _js("c.endOf(STEPS)") == 40


def test_a_scene_shows_from_its_start_until_the_next() -> None:
    """A player in scenes (a replay's levels, one after another): the one
    whose span holds the moment; the end shows the last."""
    scenes = json.dumps(
        [{"key": "server", "at": 0, "ms": 20}, {"key": "auth", "at": 20, "ms": 20}]
    )
    assert call(
        TIMELINE_JS, f"[0, 19.9, 20, 40].map((t) => c.sceneAt({scenes}, t).key)"
    ) == ["server", "server", "auth", "auth"]
    assert call(TIMELINE_JS, "c.sceneAt([], 3)") is None


def test_the_caption_is_the_latest_step_to_start() -> None:
    """What the moment is, in words: the step started last that says one
    (a request's own spans it; each hop in it says its own)."""
    steps = json.dumps(
        [
            {**STEPS[0], "says": "the route"},
            {**STEPS[1], "says": "the query"},
            {**STEPS[2]},
        ]
    )
    assert call(TIMELINE_JS, f"[1, 6, 12].map((t) => c.saysAt({steps}, t))") == [
        "the route",
        "the query",
        "the query",
    ]


def test_a_scenes_clock_is_its_real_time_staged_beats_held() -> None:
    """A scene led by staged beats (``lead``, a replay's way in) counts
    only its real time: held at the start through them, and at the end
    through any after (the way out)."""
    scene = json.dumps({"key": "auth", "at": 10, "lead": 5, "ms": 20})
    assert call(
        TIMELINE_JS, f"[12, 15, 25, 35, 40].map((t) => c.clockOf({scene}, t))"
    ) == [0, 0, 10, 20, 20]
