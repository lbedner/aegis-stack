"""
Tests for scheduler functionality.

Note: The scheduler focuses entirely on system service monitoring.
We test the service functions directly rather than complex scheduler components.

For integration tests of the actual scheduler, see the CLI tests that generate
complete projects and validate they work correctly.
"""

import pytest
from app.services.system.health import check_system_status
from apscheduler.schedulers.asyncio import AsyncIOScheduler


@pytest.mark.asyncio
async def test_scheduler_basic_setup() -> None:
    """Test that the scheduler can be set up and jobs can be added."""
    scheduler = AsyncIOScheduler()

    # Add a simple job
    scheduler.add_job(check_system_status, trigger="interval", minutes=5, id="test_job")

    # Check job was added
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "test_job"


@pytest.mark.asyncio
async def test_system_service_can_be_scheduled() -> None:
    """Test that our system service functions work with APScheduler."""
    scheduler = AsyncIOScheduler()

    # Test that our system service function can be scheduled without errors
    scheduler.add_job(check_system_status, trigger="interval", seconds=1, id="system")

    assert len(scheduler.get_jobs()) == 1

    # Get job function
    system_job = scheduler.get_job("system")

    assert system_job.func == check_system_status


@pytest.mark.asyncio
async def test_scheduler_heartbeat_job_registered() -> None:
    """The heartbeat job exists and its beacon file gets touched."""
    from app.components.scheduler.heartbeat import (
        HEARTBEAT_FILE,
        HEARTBEAT_JOB_ID,
        touch_scheduler_heartbeat,
    )
    from app.components.scheduler.main import create_scheduler

    scheduler = create_scheduler()
    job = scheduler.get_job(HEARTBEAT_JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() <= 30

    HEARTBEAT_FILE.unlink(missing_ok=True)
    await touch_scheduler_heartbeat()
    assert HEARTBEAT_FILE.exists()
