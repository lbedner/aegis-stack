"""What happened to a container between two readings (``container_events``):
a restart, an exit, a health check that failed or recovered, each a point
on the Events chart. The readings are rows as the sampler keeps them
(``container_rows.row``)."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

from app.core.time import utcnow
from app.services.system import container_events, container_rows
from tests._fake_runtime import REDIS

UP = replace(REDIS, health="healthy", started_at=utcnow() - timedelta(hours=1))


def _tables(**changed: Any) -> dict[str, Any]:
    row = container_rows.row(replace(UP, **changed), None)
    return {"redis": {"rows": [row], "note": None}}


def test_nothing_happened_without_a_change() -> None:
    assert container_events.changes(_tables(), _tables()) == {}


def test_the_first_reading_has_nothing_to_compare_with() -> None:
    assert container_events.changes(None, _tables()) == {}


def test_uptime_starting_over_is_a_restart() -> None:
    restarted = _tables(started_at=utcnow() - timedelta(seconds=3))
    assert container_events.changes(_tables(), restarted) == {
        "redis:app-redis-1:restart": 1.0
    }


def test_coming_back_after_stopping_is_a_restart() -> None:
    stopped = _tables(state="exited", started_at=None, exit_code=0)
    assert container_events.changes(stopped, _tables()) == {
        "redis:app-redis-1:restart": 1.0
    }


def test_stopping_is_an_exit() -> None:
    stopped = _tables(state="exited", started_at=None, exit_code=137)
    assert container_events.changes(_tables(), stopped) == {
        "redis:app-redis-1:exit": 1.0
    }


def test_a_health_check_failing_and_recovering() -> None:
    healthy = _tables()  # read first: its uptime is the shorter
    sick = _tables(health="unhealthy")
    assert container_events.changes(healthy, sick) == {
        "redis:app-redis-1:unhealthy": 1.0
    }
    assert container_events.changes(sick, _tables()) == {
        "redis:app-redis-1:recovered": 1.0
    }


def test_a_new_container_is_not_an_event() -> None:
    before = {"redis": {"rows": [], "note": None}}
    assert container_events.changes(before, _tables()) == {}


def test_a_stopped_containers_state_says_how_it_exited() -> None:
    stopped = replace(REDIS, state="exited", exit_code=137)
    assert container_rows.row(stopped, None)["state"] == "exited (137)"
    assert (
        container_rows.row(replace(stopped, exit_code=None), None)["state"] == "exited"
    )
