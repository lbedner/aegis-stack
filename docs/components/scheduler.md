# Scheduler Component

The **Scheduler Component** provides async task scheduling capabilities using APScheduler, running as an independent component alongside your web server.

## Current Implementation: APScheduler

**Why APScheduler**: Battle-tested Python scheduler with async support, persistent job storage, and flexible trigger types.

**Integration**: Runs as separate container/process, communicating with other components through shared database or message queues.

## Architecture

### Independent Deployment

The scheduler runs as an independent component with its own container:

```yaml
# docker-compose.yml
services:
  webserver:
    command: ["webserver"]
    ports: ["8000:8000"]
    
  scheduler:
    command: ["scheduler"]
    # No port exposure - internal service
```

### Entrypoints

- **Webserver entrypoint** (`app/entrypoints/webserver.py`): Runs FastAPI + Flet
- **Scheduler entrypoint** (`app/entrypoints/scheduler.py`): Runs only scheduler component

```bash
# Run webserver only
./scripts/entrypoint.sh webserver

# Run scheduler only  
./scripts/entrypoint.sh scheduler
```

## Usage Examples

### Basic Task Scheduling

```python
# app/services/report_service.py
from app.components.scheduler import scheduler_service

class ReportService:
    async def setup_reports(self):
        # Schedule daily report generation
        await scheduler_service.schedule_task(
            self.generate_daily_report,
            trigger_type="cron",
            hour=2, minute=0  # 2:00 AM daily
        )
        
        # Schedule cleanup every 6 hours
        await scheduler_service.schedule_task(
            self.cleanup_temp_files,
            trigger_type="interval",
            hours=6
        )
```

### One-time Delayed Tasks

```python
from datetime import datetime, timedelta
from app.components.scheduler import scheduler_service

async def schedule_reminder(user_id: int, delay_minutes: int):
    await scheduler_service.schedule_task(
        send_reminder_email,
        trigger_type="date",
        run_date=datetime.now() + timedelta(minutes=delay_minutes),
        args=[user_id]
    )
```

### Dynamic Job Management

```python
# Schedule a job and store its ID
job_id = await scheduler_service.schedule_task(
    process_large_dataset,
    trigger_type="interval",
    minutes=30
)

# Later, remove the job
await scheduler_service.remove_task(job_id)
```

## Configuration

Scheduler configuration is handled through environment variables:

```bash
# .env
SCHEDULER_TIMEZONE=UTC
SCHEDULER_MAX_WORKERS=10
SCHEDULER_MISFIRE_GRACE_TIME=600  # 10 minutes
```

## Alternative Implementations

### When to Choose APScheduler
- **Small to medium workloads** (< 1000 concurrent jobs)
- **Simple deployment** requirements
- **Mixed sync/async** task support needed
- **In-process scheduling** acceptable

### When to Consider Alternatives

**Celery + Redis/RabbitMQ**:
- **Large-scale distributed** task processing
- **High-throughput** requirements (> 1000 jobs/second)
- **Complex routing** and retry policies
- **Multi-language** worker support

```python
# Future Celery implementation
from app.components.scheduler import scheduler_service

# Same interface, different backend
await scheduler_service.schedule_task(
    process_payment,
    trigger_type="date",
    run_date=payment_date,
    queue="payments"  # Celery-specific option
)
```

**Temporal**:
- **Workflow orchestration** with state management
- **Long-running processes** with checkpoints
- **Complex dependencies** between tasks
- **Guaranteed execution** requirements

**Cloud Schedulers** (AWS EventBridge, GCP Cloud Scheduler):
- **Serverless** architecture
- **Cross-service coordination**
- **Cloud-native** integrations
- **Managed infrastructure**

## Integration Patterns

### With Database Component (Future)

```python
# app/services/data_processor.py
from app.components.scheduler import scheduler_service
from app.components.database import get_session

class DataProcessor:
    async def schedule_batch_processing(self):
        await scheduler_service.schedule_task(
            self.process_pending_records,
            trigger_type="interval",
            minutes=15
        )
    
    async def process_pending_records(self):
        async with get_session() as session:
            # Process database records
            pending = await session.execute(
                select(DataRecord).where(DataRecord.status == "pending")
            )
            for record in pending.scalars():
                await self.process_record(record)
```

### Health Monitoring

The scheduler component provides health checks:

```python
# app/backend/api/health.py
from app.components.scheduler import scheduler_service

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "components": {
            "scheduler": {
                "running": scheduler_service._is_running,
                "jobs_count": len(scheduler_service.scheduler.get_jobs())
            }
        }
    }
```

## Swapping Implementation

To switch from APScheduler to Celery:

1. **Update dependencies**:
```toml
# pyproject.toml
dependencies = [
    # "apscheduler",  # Remove
    "celery[redis]",  # Add
]
```

2. **Replace component implementation**:
```python
# app/components/scheduler.py - Keep same interface
class SchedulerService:
    async def schedule_task(self, func, trigger_type="interval", **kwargs):
        # Celery implementation
        pass
```

3. **Update deployment**:
```yaml
# docker-compose.yml
scheduler:
  command: ["celery", "worker", "-A", "app.components.scheduler"]
```

The beauty of the component architecture is that your application services continue to work unchanged - only the underlying implementation changes.

## Best Practices

### Error Handling
```python
async def robust_scheduled_task():
    try:
        await perform_critical_operation()
    except Exception as e:
        logger.error(f"Scheduled task failed: {e}")
        # Consider rescheduling or alerting
```

### Resource Management
```python
# Keep scheduled tasks lightweight
async def lightweight_task():
    # Queue heavy work to background processors
    await queue_heavy_processing.put(task_data)
```

### Monitoring
```python
# Add metrics to scheduled tasks
from app.core.log import logger

async def monitored_task():
    start_time = time.time()
    try:
        await do_work()
        logger.info("Task completed", duration=time.time() - start_time)
    except Exception as e:
        logger.error("Task failed", error=str(e), duration=time.time() - start_time)
```

## Component Benefits

**Independent Scaling**: Scale scheduler workers separately from web servers
**Fault Isolation**: Scheduler failures don't affect web serving
**Resource Optimization**: Different CPU/memory profiles for different workloads
**Deployment Flexibility**: Update scheduler without touching web server

This architecture enables your application to handle both real-time web requests and background processing efficiently.