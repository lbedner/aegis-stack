# Scheduler Examples

Essential timing patterns and job configuration examples for the scheduler component.

The examples call `scheduler.add_job` to show each trigger on its own. In a project, a service job's trigger arguments go in its `ServiceJob` entry in `app/components/scheduler/jobs.py` instead (for example `{"trigger": "cron", "hour": 6, "minute": 30}`), so that with a worker it runs on the worker. See [Where Jobs Run](../scheduler.md#where-jobs-run).

## Common Timing Patterns

### Daily Tasks

```python
# app/components/scheduler/main.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    # Daily at 6:30 AM
    scheduler.add_job(
        send_daily_report,
        trigger="cron",
        hour=6, minute=30,
        id="daily_report",
        name="Send Daily Report"
    )
    
    # Daily at midnight
    scheduler.add_job(
        cleanup_temp_files,
        trigger="cron", 
        hour=0, minute=0,
        id="daily_cleanup",
        name="Daily Cleanup"
    )
    
    return scheduler
```

### Weekly Tasks

```python
# Weekly report every Monday at 9 AM
scheduler.add_job(
    generate_weekly_report,
    trigger="cron",
    day_of_week="mon",
    hour=9, minute=0,
    id="weekly_report",
    name="Weekly Report Generation"
)

# Weekend maintenance every Saturday at 2 AM
scheduler.add_job(
    weekend_maintenance,
    trigger="cron",
    day_of_week="sat",
    hour=2, minute=0,
    id="weekend_maintenance",
    name="Weekend System Maintenance"
)
```

### Interval-Based Tasks

```python
# Every 15 minutes
scheduler.add_job(
    health_check,
    trigger="interval",
    minutes=15,
    id="health_check",
    name="System Health Check"
)

# Every 2 hours during business hours
scheduler.add_job(
    business_sync,
    trigger="interval",
    hours=2,
    start_date="2024-01-01 09:00:00",
    end_date="2024-01-01 17:00:00",
    id="business_sync", 
    name="Business Hours Sync"
)
```

### Business Hours Only

```python
# Weekdays 9 AM - 5 PM only
scheduler.add_job(
    business_task,
    trigger="cron",
    day_of_week="mon-fri",
    hour="9-17",
    minute=30,
    id="business_task",
    name="Business Hours Task"
)

# Every 30 minutes during business hours
scheduler.add_job(
    frequent_business_task,
    trigger="cron",
    day_of_week="mon-fri", 
    hour="9-17",
    minute="*/30",
    id="frequent_business",
    name="Frequent Business Task"
)
```

## Job Configuration Options

### Preventing Overlapping Jobs

```python
# Only one instance can run at a time
scheduler.add_job(
    long_running_task,
    trigger="interval",
    minutes=30,
    max_instances=1,
    id="long_task",
    name="Long Running Task"
)

# Skip missed runs and coalesce into one
scheduler.add_job(
    batch_process,
    trigger="interval", 
    hours=1,
    coalesce=True,
    max_instances=1,
    id="batch_process",
    name="Batch Processing"
)
```

### Retry and Error Handling

```python
# Job with retry logic built into function
async def robust_email_task() -> None:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await send_emails()
            break
        except EmailServiceError as e:
            if attempt == max_retries - 1:
                logger.error(f"Email task failed after {max_retries} attempts: {e}")
                raise
            await asyncio.sleep(60)  # Wait 1 minute before retry

scheduler.add_job(
    robust_email_task,
    trigger="cron",
    hour=8, minute=0,
    id="morning_emails",
    name="Morning Email Campaign"
)
```

### Grace Time for Missed Jobs

```python
# Allow jobs to run up to 5 minutes late
scheduler.add_job(
    time_sensitive_task,
    trigger="cron",
    hour=12, minute=0,
    misfire_grace_time=300,  # 5 minutes in seconds
    id="lunch_task",
    name="Lunchtime Task"
)
```

## Real-World Task Functions

### File Processing

```python
# app/services/file_tasks.py
from pathlib import Path
from app.core.log import logger

async def process_uploads() -> None:
    """Process uploaded files in batches."""
    upload_dir = Path("uploads/pending")
    
    if not upload_dir.exists():
        logger.info("No upload directory found, skipping")
        return
    
    files = list(upload_dir.glob("*"))
    if not files:
        logger.info("No files to process")
        return
    
    logger.info(f"Processing {len(files)} files")
    
    for file_path in files:
        try:
            await process_single_file(file_path)
            file_path.unlink()  # Delete after processing
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            # Move to error directory instead of deleting
            error_dir = Path("uploads/errors")
            error_dir.mkdir(exist_ok=True)
            file_path.rename(error_dir / file_path.name)
```

### Database Maintenance

```python
# app/services/db_tasks.py
async def cleanup_old_records() -> None:
    """Clean up old database records."""
    from datetime import datetime, timedelta
    from app.core.db import get_async_session
    
    cutoff_date = datetime.now() - timedelta(days=90)
    
    async with get_async_session() as session:
        # Clean up old log entries
        result = await session.execute(
            "DELETE FROM logs WHERE created_at < :cutoff",
            {"cutoff": cutoff_date}
        )
        
        deleted_count = result.rowcount
        await session.commit()
        
        logger.info(f"Cleaned up {deleted_count} old log records")

# Schedule for 3 AM daily
scheduler.add_job(
    cleanup_old_records,
    trigger="cron",
    hour=3, minute=0,
    id="db_cleanup",
    name="Database Cleanup"
)
```

### API Integration

```python
# app/services/sync_tasks.py
import httpx
from app.core.config import settings

async def sync_external_data() -> None:
    """Sync data from external API."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://api.external-service.com/data",
                headers={"Authorization": f"Bearer {settings.API_TOKEN}"},
                timeout=30.0
            )
            response.raise_for_status()
            
            data = response.json()
            await process_external_data(data)
            
            logger.info(f"Successfully synced {len(data)} records")
            
        except httpx.RequestError as e:
            logger.error(f"API sync failed: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"API returned error {e.response.status_code}: {e}")
            raise

# Sync every 4 hours
scheduler.add_job(
    sync_external_data,
    trigger="interval",
    hours=4,
    id="external_sync",
    name="External Data Sync"
)
```

## Advanced Patterns

### Dynamic Job Scheduling

```python
# app/services/dynamic_tasks.py
from datetime import datetime, timedelta

async def schedule_user_reminder(user_id: str, reminder_time: datetime) -> None:
    """Dynamically schedule a user reminder."""
    # Access the running scheduler instance (assumes scheduler is already running)
    from app.components.scheduler.main import create_scheduler
    scheduler = create_scheduler()  # Note: This creates a new instance - use carefully
    
    scheduler.add_job(
        send_user_reminder,
        trigger="date",
        run_date=reminder_time,
        args=[user_id],
        id=f"reminder_{user_id}_{int(reminder_time.timestamp())}",
        name=f"Reminder for user {user_id}",
        replace_existing=True
    )

async def send_user_reminder(user_id: str) -> None:
    """Send reminder to specific user."""
    logger.info(f"Sending reminder to user {user_id}")
    await send_notification(user_id, "Your scheduled reminder!")
```

### Conditional Job Execution

```python
async def conditional_backup() -> None:
    """Only backup if conditions are met."""
    from pathlib import Path
    
    # Check if backup is needed
    last_backup = Path("backups/last_backup.txt")
    if last_backup.exists():
        last_backup_time = datetime.fromtimestamp(last_backup.stat().st_mtime)
        if datetime.now() - last_backup_time < timedelta(hours=6):
            logger.info("Recent backup exists, skipping")
            return
    
    # Check system load
    import psutil
    if psutil.cpu_percent(interval=1) > 80:
        logger.info("System load too high, postponing backup")
        return
    
    # Perform backup
    await perform_database_backup()
    last_backup.touch()

scheduler.add_job(
    conditional_backup,
    trigger="interval",
    hours=2,
    id="smart_backup",
    name="Smart Conditional Backup"
)
```

## Testing Job Functions

### Unit Testing Jobs

```python
# tests/test_scheduler_jobs.py
import pytest
from unittest.mock import patch, AsyncMock
from app.services.file_tasks import process_uploads

@pytest.mark.asyncio
async def test_process_uploads_no_files():
    """Test upload processing with no files."""
    with patch("pathlib.Path.exists", return_value=False):
        await process_uploads()  # Should not raise

@pytest.mark.asyncio 
async def test_process_uploads_success():
    """Test successful file processing."""
    from pathlib import Path
    mock_files = [Path("file1.txt"), Path("file2.txt")]
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.glob", return_value=mock_files), \
         patch("app.services.file_tasks.process_single_file", new_callable=AsyncMock) as mock_process, \
         patch.object(Path, "unlink"):  # Mock file deletion
        
        await process_uploads()
        assert mock_process.call_count == 2
```

### Integration Testing

```python
# tests/test_scheduler_integration.py
import pytest
from app.components.scheduler.main import create_scheduler

def test_scheduler_jobs_registered():
    """Test that all expected jobs are registered."""
    scheduler = create_scheduler()
    job_ids = [job.id for job in scheduler.get_jobs()]
    
    expected_jobs = ["daily_cleanup", "health_check", "external_sync"]
    for job_id in expected_jobs:
        assert job_id in job_ids

def test_job_configuration():
    """Test job configuration is correct.""" 
    scheduler = create_scheduler()
    daily_job = scheduler.get_job("daily_cleanup")
    
    assert daily_job is not None
    assert daily_job.name == "Daily Cleanup"
    # Test trigger configuration
    assert daily_job.trigger.hour == 0
    assert daily_job.trigger.minute == 0
```

## Next Steps

- **[Scheduler Component](../scheduler.md)** - Return to scheduler overview
- **[Database Persistence](persistence.md)** - Job persistence and monitoring  
- **[Component Overview](../index.md)** - How components work together