"""The Redis views' shared wording, for Flet and the web frontend."""

from app.services.system import ui_redis


def test_uptime_reads_in_days_hours_minutes() -> None:
    assert ui_redis.uptime(90061) == "1d 1h 1m"


def test_slow_commands_are_coloured_by_duration() -> None:
    assert [ui_redis.slowlog_color(ms) for ms in (5, 150, 1500)] == [
        "green",
        "yellow",
        "red",
    ]


def test_slow_commands_read_cleanly() -> None:
    assert (
        ui_redis.slow_command("evalsha abc 1 queue:x arg") == "EVALSHA (Lua) on queue:x"
    )
    key = "task:123e4567-e89b-12d3-a456-426614174000"
    assert ui_redis.slow_command(f"get {key}") == "GET task:123e4567..."


def test_the_slow_log_is_slowest_first() -> None:
    rows = ui_redis.slow_queries(
        {
            "slowlog_entries": [
                {"duration_ms": 5, "command": "GET a"},
                {"duration_ms": 900, "command": "KEYS *"},
            ]
        }
    )
    assert [r["command"] for r in rows] == ["KEYS *", "GET a"]
