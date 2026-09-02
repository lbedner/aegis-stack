"""One rule for what a worker queue's state means, shared by every backend.

A queue nobody is consuming is a problem, and the more is waiting the
bigger the problem; the check used to file both as Info, which is how a
crash-looping worker read as a blue dot while jobs piled up.
"""

from app.services.system.health import queue_status
from app.services.system.models import ComponentStatusType


def test_waiting_work_and_no_consumer_is_unhealthy() -> None:
    status, note = queue_status(worker_alive=False, has_functions=True, waiting=3)

    assert status == ComponentStatusType.UNHEALTHY
    assert note == "no worker consuming, 3 waiting"


def test_no_consumer_and_nothing_waiting_is_a_warning() -> None:
    status, note = queue_status(worker_alive=False, has_functions=True, waiting=0)

    assert status == ComponentStatusType.WARNING
    assert note == "no worker consuming"


def test_a_queue_with_no_functions_is_only_information() -> None:
    status, note = queue_status(worker_alive=False, has_functions=False, waiting=0)

    assert status == ComponentStatusType.INFO
    assert note == "configured - no functions defined"


def test_a_live_consumer_is_healthy_until_failures_pile_up() -> None:
    assert queue_status(worker_alive=True, has_functions=True, waiting=5)[0] == (
        ComponentStatusType.HEALTHY
    )
    assert queue_status(
        worker_alive=True, has_functions=True, waiting=0, failure_rate=15.0
    )[0] == ComponentStatusType.WARNING
    assert queue_status(
        worker_alive=True, has_functions=True, waiting=0, failure_rate=40.0
    )[0] == ComponentStatusType.UNHEALTHY


def test_stream_with_no_consumer_group_has_every_entry_waiting() -> None:
    from app.services.system.health import taskiq_group_stats

    consumers, pending, read, lag = taskiq_group_stats([], stream_length=3)
    assert (consumers, pending, read, lag) == (0, 0, 0, 3)


def test_taskiq_group_reports_its_own_lag() -> None:
    from app.services.system.health import taskiq_group_stats

    groups = [
        {"name": b"other", "consumers": 9, "lag": 9},
        {"name": b"taskiq", "consumers": 2, "pending": 1, "entries-read": 4, "lag": 2},
    ]
    assert taskiq_group_stats(groups, stream_length=6) == (2, 1, 4, 2)


def test_taskiq_group_with_unknown_lag_counts_the_stream() -> None:
    from app.services.system.health import taskiq_group_stats

    groups = [{"name": "taskiq", "consumers": 1, "pending": 0, "entries-read": None, "lag": None}]
    assert taskiq_group_stats(groups, stream_length=5) == (1, 0, 0, 5)
