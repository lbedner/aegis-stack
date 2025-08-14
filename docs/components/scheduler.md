# Scheduler Component

The **Scheduler Component** provides scheduling and cron job capabilities for your Aegis Stack application using [APScheduler](https://apscheduler.readthedocs.io/).

## Adding Scheduled Tasks

### Step 1: Create Service Functions

Add your business logic as functions in `app/services/`:

```python
# app/services/my_tasks.py
from app.core.log import logger

async def send_daily_report() -> None:
    """Generate and send daily reports."""
    logger.info("📊 Generating daily report")
    # Your report generation logic here
    logger.info("✅ Daily report sent successfully")

async def cleanup_temp_files() -> None:
    """Clean up temporary files."""
    logger.info("🗑️ Cleaning temporary files")
    # Your cleanup logic here

async def backup_database() -> None:
    """Backup database weekly."""
    logger.info("💾 Starting database backup")
    # Your backup logic here
```

### Step 2: Schedule Your Tasks

Add your jobs to the scheduler in `app/components/scheduler/main.py`:

```python
# app/components/scheduler/main.py
from app.services.my_tasks import send_daily_report, cleanup_temp_files, backup_database

def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the scheduler with all jobs."""
    scheduler = AsyncIOScheduler()
    
    # Add your scheduled tasks here:
    
    # Daily report at 9 AM
    scheduler.add_job(
        send_daily_report,
        trigger="cron",
        hour=9, minute=0,
        id="daily_report",
        name="Daily Report Generation"
    )
    
    # Clean temp files every 4 hours
    scheduler.add_job(
        cleanup_temp_files,
        trigger="interval",
        hours=4,
        id="temp_cleanup",
        name="Temporary Files Cleanup"
    )
    
    # Weekly database backup on Sundays at 2 AM
    scheduler.add_job(
        backup_database,
        trigger="cron",
        day_of_week="sun",
        hour=2, minute=0,
        id="weekly_backup",
        name="Weekly Database Backup"
    )
    
    return scheduler
```

## Common Scheduling Patterns

### Interval-based Tasks

```python
# Every 30 minutes
scheduler.add_job(my_function, trigger="interval", minutes=30)

# Every 2 hours  
scheduler.add_job(my_function, trigger="interval", hours=2)

# Every day
scheduler.add_job(my_function, trigger="interval", days=1)
```

### Cron-based Tasks

```python
# Daily at 6:30 AM
scheduler.add_job(my_function, trigger="cron", hour=6, minute=30)

# Weekdays at 9 AM
scheduler.add_job(my_function, trigger="cron", day_of_week="mon-fri", hour=9)

# Last day of month at 11 PM
scheduler.add_job(my_function, trigger="cron", day="last", hour=23)

# Every Monday at 8 AM
scheduler.add_job(my_function, trigger="cron", day_of_week="mon", hour=8)
```

## Configuration

Configure the scheduler through environment variables:

```bash
# .env
SCHEDULER_TIMEZONE=UTC
SCHEDULER_MAX_WORKERS=10
SCHEDULER_MISFIRE_GRACE_TIME=600  # 10 minutes
```



## Next Steps

- **[APScheduler Documentation](https://apscheduler.readthedocs.io/en/stable/)** - Complete scheduling capabilities
- **[Component Overview](./index.md)** - Understanding Aegis Stack's component architecture