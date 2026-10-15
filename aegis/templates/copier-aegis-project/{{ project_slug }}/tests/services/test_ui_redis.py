"""The Redis views' shared wording, for Flet and the web frontend."""

from types import SimpleNamespace

import pytest

from app.services.system import redis_keys, ui_redis

REDIS_DBS = SimpleNamespace(REDIS_DB=0, CACHE_REDIS_DB=1)


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
        ui_redis.slow_command("evalsha abc 1 queue:x arg", ["queue:x"])
        == "EVALSHA (Lua) on queue:x"
    )
    key = "task:123e4567-e89b-12d3-a456-426614174000"
    assert ui_redis.slow_command(f"get {key}", [key]) == "GET task:123e4567..."


def test_the_slow_log_is_slowest_first() -> None:
    rows = ui_redis.slow_queries(
        {
            "slowlog_entries": [
                {"duration_ms": 5, "command": "GET a"},
                {"duration_ms": 900, "command": "KEYS *"},
            ]
        }
    )
    assert [r.command for r in rows] == ["KEYS *", "GET a"]


def test_a_slow_command_names_what_it_touched() -> None:
    """Its key's family (the map's own), not just the command."""
    (row,) = ui_redis.slow_queries(
        {
            "slowlog_entries": [
                {
                    "duration_ms": 50,
                    "command": "ZRANGEBYSCORE traffic:sources:1 0 +inf",
                    "keys": ["traffic:sources:1"],
                }
            ]
        }
    )
    assert row.family == "Traffic sources"
    assert row.key == "traffic:sources:1"
    (bare,) = ui_redis.slow_queries({"slowlog_entries": [{"command": "PING"}]})
    assert bare.family is None and bare.key is None


def test_a_key_is_claimed_only_in_the_database_it_lives_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared cache claims what is left in its own database, not a
    stray key in the app's: that one is unclaimed, as the map says."""
    # A Redis stack's two databases, whatever stack runs this.
    monkeypatch.setattr(redis_keys, "settings", REDIS_DBS)

    def touched(key: str, db: int | None) -> str | None:
        entry = {"command": f"GET {key}", "keys": [key], "db": db}
        return ui_redis.slow_queries({"slowlog_entries": [entry]})[0].touched

    assert touched("legacy:thing", 0) == "Unclaimed"
    assert touched("insights:project:7", 1) == "Shared cache"
    assert touched("legacy:thing", None) == "Unclaimed"  # gone: no catch-all
    assert touched("traffic:sources:1", None) == "Traffic sources"


def test_a_lua_call_reads_as_the_keys_redis_named() -> None:
    script = "EVAL \"return redis.call('get', KEYS[1])\" 1 lock:job"
    (row,) = ui_redis.slow_queries(
        {"slowlog_entries": [{"command": script, "keys": ["lock:job"]}]}
    )
    assert row.command == "EVAL (Lua) on lock:job"
