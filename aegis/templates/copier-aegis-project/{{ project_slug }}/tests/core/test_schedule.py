"""Scheduled jobs are declared by the service that owns them (#1419).

Each service lists its jobs in ``app/services/<service>/scheduled_jobs.py``;
``service_jobs`` finds every such module on disk, so a plugin's or a
hand-written service's jobs are scheduled with no edit anywhere else.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from app.core import schedule
from app.core.schedule import ServiceJob, service_jobs

FakeService = Callable[..., Path]


_ONE_JOB = (
    "from app.core.schedule import ServiceJob\n"
    "async def {func}() -> None:\n"
    "    pass\n"
    "JOBS = (ServiceJob({func}, '{id}', 'Demo', {{'trigger': 'interval', 'hours': 1}}),)\n"
)


def test_a_services_schedule_is_found_without_editing_anything(
    fake_service: FakeService,
) -> None:
    fake_service(
        "demo_plugin", scheduled_jobs=_ONE_JOB.format(func="demo_job", id="demo")
    )

    jobs = {job.id: job for job in service_jobs()}

    assert jobs["demo"].task_name == "demo_job"
    assert jobs["demo"].app_service == "demo_plugin"


def test_a_schedule_without_jobs_is_an_error(fake_service: FakeService) -> None:
    """A ``scheduled_jobs.py`` that forgot ``JOBS`` would schedule nothing, silently."""
    fake_service("demo_empty", scheduled_jobs="")

    with pytest.raises(ValueError, match=r"demo_empty\.scheduled_jobs.*JOBS"):
        service_jobs()


def test_two_services_cannot_claim_one_id(fake_service: FakeService) -> None:
    fake_service("demo_a", scheduled_jobs=_ONE_JOB.format(func="a_job", id="same"))
    fake_service("demo_b", scheduled_jobs=_ONE_JOB.format(func="b_job", id="same"))

    with pytest.raises(ValueError, match="id 'same'"):
        service_jobs()


def test_two_jobs_cannot_share_a_task_name(fake_service: FakeService) -> None:
    fake_service("demo_a", scheduled_jobs=_ONE_JOB.format(func="sync_job", id="a"))
    fake_service("demo_b", scheduled_jobs=_ONE_JOB.format(func="sync_job", id="b"))

    with pytest.raises(ValueError, match="task 'sync_job'"):
        service_jobs()


def _sweep(
    done: list[object],
    items: tuple[object, ...] = ("u1", "u2", None),
    broken: object = "never",
    app_service: str | None = None,
) -> ServiceJob:
    """A sweep over ``items`` (owners; ``None`` is a standalone stack's),
    each item done appended to ``done``; ``broken`` fails."""

    async def owners_job() -> list[object]:
        return list(items)

    async def note_for(owner: object) -> None:
        if owner == broken:
            raise RuntimeError("model exploded")
        done.append(owner)

    return ServiceJob(
        owners_job, "owners", "Owners", {}, each=note_for, app_service=app_service
    )


def test_a_sweep_hands_the_worker_its_items_not_itself() -> None:
    """The scheduler runs the sweep, so the worker knows only the item's
    task; a job that is no sweep is its own."""
    sweep = _sweep([])
    job = ServiceJob(sweep.func, "plain", "Plain", {})

    assert (sweep.handed_to, job.handed_to) == ("owners_job_each", "owners_job")


async def test_without_a_worker_the_sweep_does_each_item_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schedule, "QUEUED", False)
    done: list[object] = []

    assert await _sweep(done).fire() == 3
    assert done == ["u1", "u2", None]


async def test_with_a_worker_each_item_is_queued_once(
    monkeypatch: pytest.MonkeyPatch, queued: list[tuple[object, ...]]
) -> None:
    """The scheduler only sweeps: each item is a task on the system queue,
    queued once while it may still be waiting; the worker does the work."""
    monkeypatch.setattr(schedule, "QUEUED", True)
    done: list[object] = []
    job = _sweep(done)

    assert await job.fire() == 3
    assert await job.fire() == 0
    assert done == []
    assert queued == [
        ("owners_job_each", "system", "u1"),
        ("owners_job_each", "system", "u2"),
        ("owners_job_each", "system", None),
    ]


async def test_with_a_worker_a_job_that_is_no_sweep_is_queued_whole(
    monkeypatch: pytest.MonkeyPatch, queued: list[tuple[object, ...]]
) -> None:
    monkeypatch.setattr(schedule, "QUEUED", True)
    ran: list[bool] = []

    async def sync_job() -> None:
        ran.append(True)

    await ServiceJob(sync_job, "sync", "Sync", {}).fire()

    assert (queued, ran) == ([("sync_job", "system")], [])


async def test_an_item_runs_as_its_service() -> None:
    """The worker's task for one item: the owning service bound, as a run."""
    from structlog.contextvars import get_contextvars

    seen: list[object] = []

    async def note_for(owner: object) -> None:
        seen.append(get_contextvars().get("app_service"))

    job = _sweep([], app_service="finance")

    await replace(job, each=note_for).run_each("u1")

    assert seen == ["finance"]


async def test_without_a_worker_one_failing_item_costs_none_of_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As on the worker, where each is a task of its own: the failure is
    logged and the sweep goes on, and the run is recorded as failed."""
    monkeypatch.setattr(schedule, "QUEUED", False)
    done: list[object] = []

    with pytest.raises(schedule.SweepFailedError, match="1 of 3 items failed"):
        await _sweep(done, items=("u1", "broken", "u2"), broken="broken").fire()

    assert done == ["u1", "u2"]
