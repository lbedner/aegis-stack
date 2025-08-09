# Project Creation Guide

This guide walks you through creating new projects with the Aegis Stack CLI, understanding component composition, and customizing your stack.

## Quick Start

### Create a Basic Project

```bash
python -m aegis init my-project
```

This creates a minimal Aegis Stack project with:
- **FastAPI backend** at `app/components/backend/`
- **Flet frontend** at `app/components/frontend/`
- **Core utilities** for lifecycle, logging, and configuration
- **Automatic service discovery** system

### Create a Project with Components

```bash
python -m aegis init my-project --components scheduler
```

This adds the scheduler component to your project, providing APScheduler integration for background tasks.

## CLI Reference

### `aegis init` Command

```bash
python -m aegis init PROJECT_NAME [OPTIONS]
```

#### Options

- `--components COMPONENTS`: Comma-separated list of components to include
- `--output-dir PATH`: Directory to create the project in (default: current directory)
- `--no-interactive`: Skip interactive prompts
- `--force`: Overwrite existing directory if it exists
- `--yes, -y`: Automatically answer yes to all prompts

### Examples

```bash
# Basic project
python -m aegis init blog-api

# Project with scheduler
python -m aegis init task-runner --components scheduler

# Multiple components (when available)
python -m aegis init full-stack-app --components scheduler,database,cache

# Custom output directory
python -m aegis init my-app --output-dir /path/to/projects/

# Non-interactive mode (useful for CI/CD)
python -m aegis init ci-project --components scheduler --no-interactive --yes
```

## Available Components

### Scheduler Component

**Purpose**: Background task processing and scheduled jobs using APScheduler.

**When to use**:
- Periodic data processing
- Scheduled maintenance tasks
- Background job queues
- Time-based triggers

**Integration**:
- Automatically starts/stops with the application
- Shares the async event loop with FastAPI
- Uses structured logging
- Configurable through settings

**Usage Example**:
```python
from app.components.scheduler import scheduler_component

# Schedule a recurring task
await scheduler_component.schedule_task(
    my_background_function,
    trigger_type="interval",
    minutes=30
)

# Schedule a one-time task
await scheduler_component.schedule_task(
    cleanup_temp_files,
    trigger_type="date",
    run_date=datetime(2024, 12, 31, 23, 59)
)
```

### Database Component *(Coming Soon)*

**Purpose**: PostgreSQL integration with SQLAlchemy ORM and Alembic migrations.

**Features**:
- Async database operations
- Automatic connection pooling
- Schema migrations
- Query optimization tools

### Cache Component *(Coming Soon)*

**Purpose**: Redis integration for high-performance caching and session storage.

**Features**:
- Async Redis operations
- Distributed caching
- Session management
- Rate limiting support

## Component Composition Patterns

### Background Processing Stack

```bash
python -m aegis init processor --components scheduler
```

**Use case**: Data processing, ETL pipelines, scheduled maintenance.

**Architecture**:
- FastAPI serves status endpoints and triggers
- Scheduler handles background processing
- Services contain business logic

**Example structure**:
```
processor/
├── app/
│   ├── components/
│   │   └── scheduler.py          # APScheduler integration
│   ├── services/
│   │   ├── data_processor.py     # Your processing logic
│   │   └── notification_service.py
│   └── backend/
│       └── api/
│           └── status.py         # Status and trigger endpoints
```

### Full-Stack Application *(Future)*

```bash
python -m aegis init webapp --components scheduler,database,cache
```

**Use case**: Complete web applications with background processing.

**Architecture**:
- FastAPI serves API endpoints
- Flet provides the frontend
- Database stores application data
- Cache improves performance
- Scheduler handles background tasks

## Project Structure Deep Dive

### Generated Directory Structure

```
my-project/
├── app/
│   ├── backend/              # FastAPI backend
│   │   ├── api/
│   │   │   ├── health.py     # Health check endpoints
│   │   │   └── routing.py    # Router registration
│   │   └── main.py           # FastAPI app factory
│   ├── components/           # Stack components
│   │   └── scheduler.py      # (if scheduler selected)
│   ├── core/
│   │   ├── config.py         # Settings management
│   │   ├── discovery.py      # Service auto-discovery
│   │   ├── lifecycle.py      # Startup/shutdown registry
│   │   └── log.py            # Structured logging
│   ├── entrypoints/
│   │   └── webserver.py      # Main application entry
│   ├── frontend/             # Flet frontend
│   │   └── main.py           # Frontend session factory
│   ├── integrations/
│   │   └── main.py           # App composition layer
│   └── services/             # Your business logic goes here
├── tests/
│   └── components/
│       └── test_scheduler.py # (if scheduler selected)
├── scripts/
│   └── entrypoint.sh         # Docker entry point
├── docker-compose.yml        # Development services
├── Dockerfile                # Container configuration
├── Makefile                  # Development commands
├── pyproject.toml            # Dependencies and tools
└── README.md                 # Project documentation
```

### Key Integration Points

#### Lifecycle Registry (`app/core/lifecycle.py`)

All components register their startup and shutdown tasks:

```python
from app.core.lifecycle import STARTUP_TASKS, SHUTDOWN_TASKS

# Components add their initialization here
STARTUP_TASKS.append(start_scheduler)
SHUTDOWN_TASKS.append(stop_scheduler)
```

#### Service Discovery (`app/core/discovery.py`)

Automatically imports all modules in `app/services/`:

```python
from app.core.discovery import auto_discover_services

# This finds and imports all your services
auto_discover_services()
```

#### Configuration (`app/core/config.py`)

Unified settings accessible throughout the application:

```python
from app.core.config import settings

# Components and services use shared configuration
database_url = settings.DATABASE_URL
redis_url = settings.REDIS_URL
```

## Customizing Your Project

### Adding Your Own Services

Create files in `app/services/` - they're automatically discovered:

```python
# app/services/user_service.py
from app.core.lifecycle import STARTUP_TASKS
from app.components.scheduler import scheduler

async def start_user_cleanup():
    """Register cleanup task with scheduler."""
    await scheduler.schedule_task(
        cleanup_inactive_users,
        trigger_type="cron",
        hour=2  # Run at 2 AM daily
    )

STARTUP_TASKS.append(start_user_cleanup)
```

### Adding Custom API Endpoints

```python
# app/backend/api/users.py
from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
async def list_users():
    return {"users": []}
```

Register in `app/backend/api/routing.py`:

```python
from app.backend.api.users import router as users_router

def include_routers(app: FastAPI) -> None:
    app.include_router(users_router)
```

### Environment Configuration

Customize `.env` for your needs:

```env
# Database (when database component added)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/mydb

# Redis (when cache component added)  
REDIS_URL=redis://localhost:6379

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json  # or 'console' for development

# Application
APP_NAME=my-project
DEBUG=false
```

## Testing Your Project

### Generated Tests

Each component includes tests:

```bash
# Run all tests
make test

# Run component-specific tests
pytest tests/components/test_scheduler.py -v
```

### Quality Checks

Every generated project includes quality tooling:

```bash
# Run all checks (linting, type checking, tests)
make check

# Individual checks
make lint      # Ruff linting
make typecheck # MyPy type checking
make test      # Pytest test suite
```

### Docker Development

```bash
# Start development environment
make docker-up

# Or just the webserver
make run-local
```

## Best Practices

### Service Organization

- **Components**: Foundation capabilities (scheduler, database, cache)
- **Services**: Your business logic (user_service, notification_service)
- **API**: HTTP endpoints that use services
- **Frontend**: UI that calls API endpoints

### Lifecycle Management

- Register long-running processes in `STARTUP_TASKS`
- Always provide corresponding cleanup in `SHUTDOWN_TASKS`
- Use async/await consistently throughout

### Configuration

- Put environment-specific values in `.env`
- Use type hints with Pydantic settings
- Keep secrets out of code and logs

### Error Handling

- Use structured logging with context
- Handle component failures gracefully
- Provide health checks for monitoring

## Troubleshooting

### Common Issues

**Template files not processed**:
- Ensure you're using the latest version
- Check that `.j2` files are being rendered during generation

**Components not starting**:
- Check `STARTUP_TASKS` registration
- Verify environment variables are set
- Look at structured logs for initialization errors

**Service discovery not working**:
- Ensure services are in `app/services/` directory
- Check that service modules don't have import errors
- Services are imported automatically, no manual registration needed

### Getting Help

- Check the [Components Overview](../components/index.md) for architecture details
- Review [Lifecycle Management](./lifecycle.md) for startup/shutdown patterns
- See [Services Guide](./services.md) for business logic organization