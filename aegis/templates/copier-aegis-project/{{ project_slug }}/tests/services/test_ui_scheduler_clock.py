"""The scheduler clock: a 24-hour dial drawn from the scheduler's own tasks."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.system import ui_scheduler

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
TASKS = [
    {
        "job_id": "backup",
        "name": "Database backup",
        "next_run": "2026-09-27T02:00:00+00:00",
        "schedule": "Cron: hour=2, minute=0",
    },
    {
        "job_id": "sync",
        "name": "Payment sync",
        "next_run": "2026-09-27T03:30:00+00:00",
        "schedule": "Cron: hour=3, minute=30",
    },
    {
        "job_id": "beat",
        "name": "Scheduler Heartbeat",
        "next_run": "2026-09-26T06:00:15+00:00",
        "schedule": "Every 15s",
    },
]


def test_the_dial_is_twenty_four_hours_with_midnight_at_the_top() -> None:
    assert ui_scheduler.dial_angle(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), UTC) == 0
    assert ui_scheduler.dial_angle(datetime(2026, 1, 1, 6, 0, tzinfo=UTC), UTC) == 90
    assert ui_scheduler.dial_angle(datetime(2026, 1, 1, 18, 0, tzinfo=UTC), UTC) == 270


def test_cron_jobs_sit_on_the_ring_at_their_time_of_day() -> None:
    clock = ui_scheduler.clock(TASKS, NOW, UTC)
    backup, sync = clock["cron"]
    assert (backup["name"], backup["at"], backup["angle"]) == (
        "Database backup",
        "02:00",
        30,
    )
    assert (sync["at"], sync["angle"]) == ("03:30", pytest.approx(52.5))


def test_frequent_interval_jobs_light_the_inner_band_instead_of_the_ring() -> None:
    clock = ui_scheduler.clock(TASKS, NOW, UTC)
    assert [j["name"] for j in clock["cron"]] == ["Database backup", "Payment sync"]
    assert clock["interval"] == [{"name": "Scheduler Heartbeat", "every": "Every 15s"}]
    assert clock["band"]["continuous"] is True


def test_a_daily_interval_job_is_a_dot_at_its_time_of_day() -> None:
    """Every 1d fires at the same time each day, so it belongs on the ring."""
    daily = {"job_id": "cleanup", "name": "Token cleanup", "next_run": "2026-09-27T04:00:00+00:00", "schedule": "Every 1d"}
    clock = ui_scheduler.clock([daily], NOW, UTC)
    (job,) = clock["cron"]
    assert (job["name"], job["at"], job["angle"], job["every"]) == ("Token cleanup", "04:00", 60, "Every 1d")
    assert clock["interval"] == []
    assert clock["band"] == {"continuous": False, "dots": []}


def test_an_hourly_interval_job_is_a_dot_on_the_band_for_each_run() -> None:
    every_2h = {"job_id": "sync", "name": "Sync", "next_run": "2026-09-26T07:00:00+00:00", "schedule": "Every 2h"}
    clock = ui_scheduler.clock([every_2h], NOW, UTC)
    assert clock["cron"] == []
    assert len(clock["band"]["dots"]) == 12
    assert clock["band"]["continuous"] is False
    assert clock["interval"] == [{"name": "Sync", "every": "Every 2h"}]


@pytest.mark.parametrize(
    ("schedule", "seconds"),
    [("Every 15s", 15), ("Every 5m", 300), ("Every 2h", 7200), ("Every 1.5h", 5400), ("Every 1d", 86400), ("Cron: hour=2", None)],
)
def test_interval_periods_are_read_from_the_schedule(schedule: str, seconds: float | None) -> None:
    assert ui_scheduler.interval_seconds(schedule) == seconds


def test_the_hand_is_now_and_the_next_job_is_marked() -> None:
    clock = ui_scheduler.clock(TASKS, NOW, UTC)
    assert clock["hand"] == 90
    assert clock["seconds_since_midnight"] == 6 * 3600
    assert [j["next"] for j in clock["cron"]] == [True, False]


def test_times_are_read_in_the_scheduler_timezone() -> None:
    clock = ui_scheduler.clock(TASKS, NOW, ZoneInfo("America/New_York"))
    assert clock["cron"][0]["at"] == "22:00"  # 02:00 UTC is 22:00 in New York (EDT)
    assert clock["timezone"] == "America/New_York"


def test_positions_are_percentages_of_the_dial() -> None:
    top = ui_scheduler.dial_point(0, 50)
    right = ui_scheduler.dial_point(90, 50)
    assert (top["x"], top["y"]) == (50, 0)
    assert (right["x"], right["y"]) == pytest.approx((100, 50))


def _stats(avg_ms: float, last_status: str, last_ms: float | None = None) -> dict:
    return {
        "avg_duration_ms": avg_ms,
        "last_run": {
            "status": last_status,
            "duration_ms": last_ms if last_ms is not None else avg_ms,
        },
    }


def test_a_job_with_history_draws_an_arc_from_its_dot() -> None:
    clock = ui_scheduler.clock(
        TASKS, NOW, UTC, stats={"backup": _stats(3_600_000, "success")}
    )
    backup = clock["cron"][0]
    assert backup["arc"]["sweep"] == 15  # an hour is 15 degrees of a day
    assert backup["arc"]["d"].startswith("M ")
    assert backup["color"] == "green"


def test_short_jobs_still_show_a_sliver_and_their_real_average() -> None:
    backup = ui_scheduler.clock(
        TASKS, NOW, UTC, stats={"backup": _stats(2000, "success")}
    )["cron"][0]
    assert backup["arc"]["sweep"] == ui_scheduler.MIN_ARC
    assert backup["avg"] == "2.0s"


@pytest.mark.parametrize(
    ("last", "last_ms", "color"),
    [
        ("failed", None, "red"),
        ("missed", None, "yellow"),
        ("running", None, "blue"),
        ("success", 9000, "yellow"),
    ],
)
def test_the_arc_is_coloured_by_the_last_run(
    last: str, last_ms: float | None, color: str
) -> None:
    """Failed is red, missed amber, running blue; a success more than twice
    the average is amber too (it ran slow)."""
    backup = ui_scheduler.clock(
        TASKS, NOW, UTC, stats={"backup": _stats(3000, last, last_ms)}
    )["cron"][0]
    assert backup["color"] == color


def test_no_history_means_just_a_dot() -> None:
    backup = ui_scheduler.clock(TASKS, NOW, UTC, stats={})["cron"][0]
    assert backup["arc"] is None and backup["color"] is None
