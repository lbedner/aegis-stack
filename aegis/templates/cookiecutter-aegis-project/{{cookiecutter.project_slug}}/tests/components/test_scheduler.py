from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.components.scheduler import SchedulerService


@pytest.fixture
def scheduler_service() -> SchedulerService:
    """Provides a clean instance of the SchedulerService for each test."""
    return SchedulerService()


@pytest.mark.asyncio
async def test_scheduler_start_and_stop(scheduler_service: SchedulerService) -> None:
    """
    Tests that the scheduler starts and stops correctly.
    """
    assert not scheduler_service._is_running

    # Mock the internal scheduler's start and shutdown methods
    scheduler_service.scheduler.start = Mock()
    scheduler_service.scheduler.shutdown = Mock()

    await scheduler_service.start()
    assert scheduler_service._is_running
    scheduler_service.scheduler.start.assert_called_once()

    await scheduler_service.stop()
    assert not scheduler_service._is_running
    scheduler_service.scheduler.shutdown.assert_called_once_with(wait=False)


@pytest.mark.asyncio
async def test_schedule_task(scheduler_service: SchedulerService) -> None:
    """
    Tests that a task can be scheduled.
    """
    mock_task_func = AsyncMock()

    # Mock the add_job method
    mock_job = Mock()
    mock_job.id = "test_job_123"
    mock_add_job = Mock(return_value=mock_job)
    with patch.object(
        scheduler_service.scheduler, "add_job", new=mock_add_job
    ) as mock_add_job:
        job_id = await scheduler_service.schedule_task(
            mock_task_func, trigger_type="interval", minutes=5
        )

        assert job_id == "test_job_123"
        mock_add_job.assert_called_once()
        # You could add more specific assertions here about the trigger if needed


@pytest.mark.asyncio
async def test_remove_task(scheduler_service: SchedulerService) -> None:
    """
    Tests that a task can be removed.
    """
    job_id_to_remove = "test_job_456"

    # Mock the remove_job method
    with patch.object(scheduler_service.scheduler, "remove_job") as mock_remove_job:
        await scheduler_service.remove_task(job_id_to_remove)
        mock_remove_job.assert_called_once_with(job_id_to_remove)
