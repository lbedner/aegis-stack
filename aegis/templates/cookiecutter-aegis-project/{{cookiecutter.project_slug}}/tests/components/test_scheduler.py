"""
Tests for scheduler functionality.

Note: The scheduler focuses entirely on system service monitoring.
We test the service functions directly rather than complex scheduler components.

For integration tests of the actual scheduler, see the CLI tests that generate
complete projects and validate they work correctly.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytest

from app.components.scheduler.main import _check_scheduler_health, create_scheduler
from app.services.system.health import check_system_status


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
async def test_scheduler_health_check() -> None:
    """Test the scheduler health check functionality."""
    # Test health check when scheduler is not initialized
    health_status = await _check_scheduler_health()
    assert not health_status.healthy
    assert "not initialized" in health_status.message

    # Test with created but not started scheduler
    scheduler = create_scheduler()
    import app.components.scheduler.main as scheduler_module

    scheduler_module._scheduler = scheduler

    health_status = await _check_scheduler_health()
    assert not health_status.healthy
    assert "not running" in health_status.message

    # Test with running scheduler
    scheduler.start()
    try:
        health_status = await _check_scheduler_health()
        assert health_status.healthy
        assert "running with" in health_status.message
        assert health_status.metadata is not None
        assert "job_count" in health_status.metadata
    finally:
        scheduler.shutdown()
        scheduler_module._scheduler = None
