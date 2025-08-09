# Components Overview

Aegis Stack is built from a set of foundational, battle-tested **Components**. Each component provides a core capability to the stack, such as serving web requests or handling user interfaces. They live in the `app/components` directory of your project.

This is distinct from **Services** (`app/services`), which are where you, the developer, will implement your application's specific business logic.

## Core Components

Every Aegis Stack project starts with two core components:

- **[Web Server](./webserver.md)**: The FastAPI-based backend that serves your API.
- **[Frontend](./frontend.md)**: The Flet-based frontend for user interaction.

## Optional Components

You can add more capabilities to your stack using the `aegis init` command. These optional components are automatically integrated into your project's lifecycle and are guaranteed to work seamlessly with the core components.

- **[Scheduler](./scheduler.md)**: Adds APScheduler for background and scheduled tasks as an independent component.
- **Database**: Adds SQLAlchemy and Alembic for PostgreSQL integration. *(Coming soon)*
- **Cache**: Adds Redis for high-performance caching. *(Coming soon)*

## Component Composition Examples

### Background Processing Stack

```bash
python -m aegis init processor --components scheduler
```

**Perfect for**: ETL pipelines, data processing, scheduled maintenance tasks.

**How it works together**:
```python
# app/services/data_processor.py
from app.core.lifecycle import STARTUP_TASKS
from app.components.scheduler import scheduler_service

async def start_processing_jobs():
    # Schedule recurring data processing
    await scheduler_service.schedule_task(
        process_daily_reports,
        trigger_type="cron",
        hour=2, minute=0  # 2:00 AM daily
    )
    
    # Schedule cleanup tasks
    await scheduler_service.schedule_task(
        cleanup_temp_files,
        trigger_type="interval",
        hours=6  # Every 6 hours
    )

STARTUP_TASKS.append(start_processing_jobs)
```

The **FastAPI backend** provides status endpoints and manual triggers, while the **scheduler component** handles all background work independently. Your **services** contain the actual business logic that can interact with both components.

### Full-Stack Application *(Future)*

```bash
python -m aegis init webapp --components scheduler,database,cache
```

**Perfect for**: Complete web applications with user management, real-time features, and background processing.

**Component interaction**:
- **Database component** provides persistent storage
- **Cache component** speeds up frequent queries
- **Scheduler component** handles background tasks (emails, cleanup, reports)
- **Backend component** serves API endpoints
- **Frontend component** provides the user interface

**Example service leveraging all components**:
```python
# app/services/user_service.py
from app.components.database import get_session
from app.components.cache import get_redis
from app.components.scheduler import scheduler_service

class UserService:
    async def create_user(self, user_data):
        # Save to database
        async with get_session() as session:
            user = User(**user_data)
            session.add(user)
            await session.commit()
            
        # Cache for quick lookup
        redis = await get_redis()
        await redis.set(f"user:{user.id}", user.json())
        
        # Schedule welcome email
        await scheduler_service.schedule_task(
            send_welcome_email,
            trigger_type="date",
            run_date=datetime.now() + timedelta(minutes=5),
            args=[user.id]
        )
        
        return user
```

## Component Integration Patterns

### Lifecycle Coordination

All components participate in the application lifecycle through the registry system:

```python
# Each component registers its tasks
from app.core.lifecycle import STARTUP_TASKS, SHUTDOWN_TASKS

# Scheduler component registration
STARTUP_TASKS.append(start_scheduler)
SHUTDOWN_TASKS.append(stop_scheduler)

# Database component registration (future)
STARTUP_TASKS.append(connect_database)
SHUTDOWN_TASKS.append(disconnect_database)

# Cache component registration (future)
STARTUP_TASKS.append(connect_redis)
SHUTDOWN_TASKS.append(disconnect_redis)
```

### Shared Configuration

Components access shared configuration through the settings system:

```python
from app.core.config import settings

# Scheduler uses shared config
scheduler_config = {
    "timezone": settings.TIMEZONE,
    "max_workers": settings.SCHEDULER_MAX_WORKERS,
}

# Database uses shared config (future)
database_url = settings.DATABASE_URL

# Cache uses shared config (future)
redis_url = settings.REDIS_URL
```

### Error Handling and Monitoring

Components provide health checks and structured logging:

```python
# Health check endpoint includes all components
@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "components": {
            "scheduler": await scheduler.health_check(),
            "database": await database.health_check(),  # future
            "cache": await cache.health_check(),        # future
        }
    }
```

## The "Components" vs. "Services" Philosophy

- **`app/components` is the Stack.** These are the foundational building blocks provided by Aegis. You generally won't modify these files directly. They provide the *capabilities* your application uses.
- **`app/services` is your Application.** This is where you build your business logic. For example, a `user_service.py` would live here and might *use* the `database` component to save a user to the database.

This clear separation allows you to focus on your application's logic while relying on the battle-tested foundation of the Aegis components.

### Real-World Service Examples

**Using the Scheduler Component**:
```python
# app/services/report_service.py
from app.components.scheduler import scheduler

class ReportService:
    async def schedule_daily_report(self, user_id: int):
        await scheduler.schedule_task(
            self.generate_report,
            trigger_type="cron",
            hour=9, minute=0,  # 9:00 AM daily
            args=[user_id]
        )
```

**Using Multiple Components** *(Future)*:
```python
# app/services/notification_service.py
from app.components.database import get_session
from app.components.cache import get_redis
from app.components.scheduler import scheduler

class NotificationService:
    async def send_delayed_notification(self, user_id: int, message: str, delay_minutes: int):
        # Cache the notification
        redis = await get_redis()
        await redis.set(f"pending_notification:{user_id}", message, ex=delay_minutes * 60)
        
        # Schedule delivery
        await scheduler.schedule_task(
            self.deliver_notification,
            trigger_type="date",
            run_date=datetime.now() + timedelta(minutes=delay_minutes),
            args=[user_id, message]
        )
```

This architecture scales naturally from simple single-component applications to complex multi-component systems.
