"""Scheduled jobs are declared by the service that owns them (#1419).

Each service lists its jobs in ``app/services/<service>/scheduled_jobs.py``;
``service_jobs`` finds every such module on disk, so a plugin's or a
hand-written service's jobs are scheduled with no edit anywhere else.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.schedule import service_jobs

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
    fake_service("demo_plugin", scheduled_jobs=_ONE_JOB.format(func="demo_job", id="demo"))

    jobs = {job.id: job for job in service_jobs()}

    assert jobs["demo"].task_name == "demo_job"


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
