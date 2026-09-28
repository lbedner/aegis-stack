"""What the scheduler detail views show, for every frontend.

States carry a semantic colour name (green, blue, yellow, red), the
vocabulary ``get_status_color_name`` uses, so each frontend maps them to
its own theme.
"""

from datetime import datetime, tzinfo
import math
import re
from typing import Any

from app.core.formatting import (
    format_duration_ms,
    format_next_run_time,
    format_schedule_human_readable,
)

# An execution's status: its label and colour.
EXECUTION_STATUSES: dict[str, tuple[str, str]] = {
    "success": ("Success", "green"),
    "failed": ("Failed", "red"),
    "running": ("Running", "blue"),
    "missed": ("Missed", "yellow"),
}


def job_state(status: str, next_run: str) -> tuple[str, str, str]:
    """A scheduled job's next run in words, its state label, and its colour.

    Paused jobs are grey; an active job whose next run has passed stays
    "Active" but turns yellow, since the scheduler should already have
    fired it (the next run reads "Past due").
    """
    next_run_display = format_next_run_time(next_run)
    if status != "active":
        return next_run_display, "Paused", "grey"
    if "Past due" in next_run_display:
        return next_run_display, "Active", "yellow"
    return next_run_display, "Active", "green"


def execution_status(status: str) -> tuple[str, str]:
    """An execution's status label and colour."""
    return EXECUTION_STATUSES.get(status, (status.title(), "grey"))


# ---- The scheduler clock -------------------------------------------------
# A 24-hour dial, midnight at the top, in the scheduler's timezone. Cron and
# one-off jobs are dots on the ring at the time of day they fire; interval
# jobs (a heartbeat every 15s would be thousands of dots) go to an inner
# band instead. Positions are percentages of the dial, so it can be any size.


def dial_angle(moment: datetime, tz: tzinfo) -> float:
    """Degrees clockwise from midnight for ``moment``'s time of day in ``tz``."""
    local = moment.astimezone(tz)
    minutes = local.hour * 60 + local.minute + local.second / 60
    return minutes / 1440 * 360


def dial_point(angle: float, radius: float) -> dict[str, float]:
    """Where ``angle`` falls at ``radius`` (% of the dial's width) from the centre."""
    rad = math.radians(angle)
    return {
        "x": round(50 + math.sin(rad) * radius, 3),
        "y": round(50 - math.cos(rad) * radius, 3),
    }


_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_EVERY = re.compile(r"^Every (\d+(?:\.\d+)?)([smhd])$")
_RAW = re.compile(r"^interval\[(?:(\d+) days?, )?(\d+):(\d{2}):(\d{2})\]$")


def interval_seconds(schedule: str) -> float | None:
    """An interval trigger's period, as the health check words it ("Every
    15s") or as APScheduler prints it ("interval[1 day, 0:00:00]"); None
    for anything else (cron, one-off)."""
    if match := _EVERY.match(schedule):
        return float(match.group(1)) * _UNITS[match.group(2)]
    if match := _RAW.match(schedule):
        days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
        return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)
    return None


def dial_arc(start: float, sweep: float, radius: float | None = None) -> dict[str, Any]:
    """An SVG path (viewBox 0 0 100 100) along the ring from ``start`` for
    ``sweep`` degrees clockwise."""
    radius = RING if radius is None else radius
    a, b = dial_point(start, radius), dial_point(start + sweep, radius)
    large = 1 if sweep > 180 else 0
    return {
        "sweep": sweep,
        "d": f"M {a['x']} {a['y']} A {radius} {radius} 0 {large} 1 {b['x']} {b['y']}",
    }


def run_color(stats: dict[str, Any] | None) -> str | None:
    """How a job's last run went: red failed, yellow missed or slow (more
    than twice its average), blue still running, green clean. None without
    history."""
    last = (stats or {}).get("last_run")
    if not last:
        return None
    status = last.get("status")
    if status == "failed":
        return "red"
    if status == "missed":
        return "yellow"
    if status == "running":
        return "blue"
    avg, took = (stats or {}).get("avg_duration_ms"), last.get("duration_ms")
    if avg and took and took > 2 * avg:
        return "yellow"
    return "green"


def _arc(stats: dict[str, Any] | None) -> dict[str, Any] | None:
    """The job's run as an arc from the top of the dial; the job's slot is
    rotated to its angle, so moving the job only changes that rotation."""
    avg = (stats or {}).get("avg_duration_ms")
    if not avg:
        return None
    sweep = max(avg / 86_400_000 * 360, MIN_ARC)
    return dial_arc(0, round(sweep, 3))


def clock(
    tasks: list[dict[str, Any]],
    now: datetime,
    tz: tzinfo,
    stats: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The dial for ``tasks`` at ``now``: dots, the inner band, and the hand.

    ``stats`` (per job id, from the execution history) adds each cron job's
    arc, as long as its average run, coloured by how its last run went.
    """
    stats = stats or {}
    cron: list[dict[str, Any]] = []
    interval: list[dict[str, Any]] = []
    band: dict[str, Any] = {"continuous": False, "dots": []}
    for task in tasks:
        schedule = str(task.get("schedule", ""))
        next_run = task.get("next_run")
        period = interval_seconds(schedule)
        name = task.get("name") or task.get("job_id")
        if not next_run:
            continue
        fires = datetime.fromisoformat(str(next_run))
        if period is not None and period < DAY:
            # Too frequent for the ring: a dot on the band per run in the
            # day, or, under an hour apart, the band itself lights up.
            interval.append(
                {"name": name, "every": format_schedule_human_readable(schedule)}
            )
            if period < HOUR:
                band["continuous"] = True
            else:
                start = dial_angle(fires, tz)
                band["dots"] += [
                    dial_point((start + k * period / DAY * 360) % 360, BAND)
                    for k in range(int(DAY // period))
                ]
            continue
        angle = dial_angle(fires, tz)
        job_stats = stats.get(str(task.get("job_id")))
        avg = (job_stats or {}).get("avg_duration_ms")
        cron.append(
            {
                "name": name,
                "at": fires.astimezone(tz).strftime("%H:%M"),
                "angle": angle,
                "fires": fires,
                "every": format_schedule_human_readable(schedule) if period else None,
                "id": task.get("job_id"),
                "arc": _arc(job_stats),
                "color": run_color(job_stats),
                "avg": format_duration_ms(avg) if avg else None,
            }
        )
    cron.sort(key=lambda job: job["angle"])
    upcoming = min(cron, key=lambda job: job["fires"], default=None)
    for job in cron:
        job["next"] = job is upcoming
        del job["fires"]
    local = now.astimezone(tz)
    return {
        "cron": cron,
        "interval": interval,
        "band": band,
        "hand": dial_angle(now, tz),
        "seconds_since_midnight": local.hour * 3600 + local.minute * 60 + local.second,
        "timezone": str(tz),
        "ticks": [
            {
                **dial_point(hour * 15, RING),
                "angle": hour * 15 + 90,
                "major": hour % 6 == 0,
            }
            for hour in range(24)
        ],
        "labels": [
            {"text": f"{hour:02d}", **dial_point(hour * 15, LABELS)}
            for hour in (0, 6, 12, 18)
        ],
    }


RING = 47.7  # % of the dial: the ring the dots and ticks sit on
LABELS = 40.4  # % of the dial: the hour labels, inside the ring
BAND = 32.0  # % of the dial: the inner band for jobs too frequent for the ring
HOUR, DAY = 3600, 86400
# Degrees. A 2s job is 0.008 degrees of a day, too thin to see; arcs are at
# least this long, and the legend carries the real average.
MIN_ARC = 2.0
