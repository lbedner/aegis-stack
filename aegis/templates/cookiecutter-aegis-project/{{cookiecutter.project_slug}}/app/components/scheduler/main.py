"""
Scheduler component for {{ cookiecutter.project_name }}.

Simple, explicit job scheduling - just import functions and schedule them.
Add your own jobs by importing service functions and calling scheduler.add_job().
"""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.log import logger
from app.services.system.health import check_system_status, register_health_check
from app.services.system.models import ComponentStatus

# Global scheduler instance for health checking
_scheduler: AsyncIOScheduler | None = None


async def _check_scheduler_health() -> ComponentStatus:
    """Health check for the scheduler component."""
    global _scheduler

    if _scheduler is None:
        return ComponentStatus(
            name="scheduler",
            healthy=False,
            message="Scheduler not initialized",
            response_time_ms=None,
        )

    if not _scheduler.running:
        return ComponentStatus(
            name="scheduler",
            healthy=False,
            message="Scheduler is not running",
            response_time_ms=None,
        )

    # Get scheduler statistics
    jobs = _scheduler.get_jobs()
    job_count = len(jobs)

    # Check if scheduler is responsive
    try:
        state = _scheduler.state
        healthy = state == 1  # STATE_RUNNING = 1

        return ComponentStatus(
            name="scheduler",
            healthy=healthy,
            message=f"Scheduler running with {job_count} jobs",
            response_time_ms=None,
            metadata={
                "job_count": job_count,
                "state": state,
                "jobs": [{"id": job.id, "name": job.name} for job in jobs[:5]],
            },
        )
    except Exception as e:
        return ComponentStatus(
            name="scheduler",
            healthy=False,
            message=f"Scheduler health check failed: {str(e)}",
            response_time_ms=None,
        )


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the scheduler with all jobs."""
    scheduler = AsyncIOScheduler()

    # ============================================================================
    # JOB SCHEDULE CONFIGURATION
    # Add your scheduled jobs below - import service functions and schedule them!
    # ============================================================================

    # System health check every 5 minutes
    # Adjust this interval based on your monitoring needs:
    # - Production systems: 1-5 minutes
    # - Development: 10-15 minutes
    # - High-availability: 30 seconds - 1 minute
    scheduler.add_job(
        check_system_status,
        trigger="interval",
        minutes=1,
        id="system_status_check",
        name="System Health Check",
        max_instances=1,  # Prevent overlapping health checks
        coalesce=True,  # Coalesce missed executions
    )

    # Add your own scheduled jobs here by importing service functions
    # and calling scheduler.add_job() with your custom business logic

    return scheduler


async def run_scheduler() -> None:
    """Main scheduler runner with lifecycle management."""
    global _scheduler

    logger.info("🕒 Starting {{ cookiecutter.project_name }} Scheduler")

    scheduler = create_scheduler()
    _scheduler = scheduler  # Store for health checking

    try:
        scheduler.start()
        logger.info("✅ Scheduler started successfully")
        logger.info(f"📋 {len(scheduler.get_jobs())} jobs scheduled:")

        for job in scheduler.get_jobs():
            logger.info(f"   • {job.name} - {job.trigger}")

        # Register scheduler health check with the system health service
        register_health_check("scheduler", _check_scheduler_health)
        logger.info("🩺 Scheduler health check registered")

        # Keep the scheduler running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal")
    except Exception as e:
        logger.error(f"❌ Scheduler error: {e}")
        raise
    finally:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("✅ Scheduler stopped gracefully")
        _scheduler = None  # Clear global reference
