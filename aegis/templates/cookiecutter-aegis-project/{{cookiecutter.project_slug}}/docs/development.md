# Development Guide

This guide covers how to develop and maintain {{ cookiecutter.project_name }}.

## Getting Started

### Prerequisites
- Python 3.11+
- UV package manager

### Setup
```bash
# Clone and enter the project
cd {{ cookiecutter.project_slug }}

# Install dependencies
uv sync

# Copy environment template
cp .env.example .env

# Start development server
make run-dev
```

## Development Commands

### Running the Application
```bash
make run-local    # Start with Docker (recommended)
make run-dev      # Start without Docker
```{% if cookiecutter.include_scheduler == "yes" %}

### Scheduler Component
```bash
make run-scheduler  # Run scheduler component locally
```{% endif %}

### Health Monitoring
```bash
make health         # Check system health
make health-detailed # Detailed health information
make health-json    # JSON health output
```

### Code Quality
```bash
make test           # Run test suite
make lint           # Check code style
make typecheck      # Run type checking
make check          # Run all checks
make fix            # Auto-fix code issues
```

### Documentation
```bash
make docs-serve     # Serve documentation locally (http://localhost:8001)
make docs-build     # Build static documentation
```

## Project Structure

```
{{ cookiecutter.project_slug }}/
├── app/
│   ├── components/     # Application components{% if cookiecutter.include_scheduler == "yes" %}
│   │   ├── scheduler/  # Background task scheduling{% endif %}
│   │   ├── backend/    # FastAPI web server
│   │   └── frontend/   # Flet user interface
│   ├── core/          # Core utilities and configuration
│   ├── services/      # Business logic services
│   └── cli/           # Command-line interface
├── tests/             # Test suite
├── docs/              # Project documentation
└── docker-compose.yml # Container orchestration
```

## Adding New Features

### 1. Create Business Logic
Add pure business logic functions to `app/services/`:

```python
# app/services/my_service.py
async def process_data(data: str) -> str:
    """Process data and return result."""
    return f"Processed: {data}"
```

### 2. Add API Endpoints
Create routes in `app/components/backend/api/`:

```python
# app/components/backend/api/my_endpoints.py
from fastapi import APIRouter
from app.services.my_service import process_data

router = APIRouter()

@router.post("/process")
async def process_endpoint(data: str):
    result = await process_data(data)
    return {"result": result}
```

Register in `app/components/backend/api/routing.py`:

```python
from app.components.backend.api import my_endpoints

def include_routers(app: FastAPI) -> None:
    app.include_router(my_endpoints.router, prefix="/api", tags=["processing"])
```{% if cookiecutter.include_scheduler == "yes" %}

### 3. Add Scheduled Tasks
Add jobs to the scheduler component:

```python
# In app/components/scheduler/main.py
from app.services.my_service import process_data

# Add to create_scheduler function
scheduler.add_job(
    func=lambda: process_data("scheduled"),
    trigger="cron",
    hour=2,  # Run at 2 AM daily
    id="daily_processing",
    name="Daily Data Processing"
)
```{% endif %}

## Testing

### Running Tests
```bash
make test           # All tests
make test-verbose   # Verbose output
```

### Writing Tests
Create tests in the `tests/` directory:

```python
# tests/services/test_my_service.py
import pytest
from app.services.my_service import process_data

@pytest.mark.asyncio
async def test_process_data():
    result = await process_data("test")
    assert result == "Processed: test"
```

## Deployment

### Docker Deployment
```bash
# Build and run
make docker-build
make docker-up

# Or use profiles for specific components
docker compose --profile dev up
```

### Environment Configuration
Configure `.env` file for your environment:

```env
# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Logging
LOG_LEVEL=INFO{% if cookiecutter.include_scheduler == "yes" %}

# Scheduler Configuration  
SCHEDULER_TIMEZONE=UTC{% endif %}
```

## Monitoring and Health Checks

{{ cookiecutter.project_name }} includes comprehensive health monitoring:

- **Health Endpoints**: `/health/` and `/health/detailed`
- **CLI Commands**: `{{ cookiecutter.project_slug }} health check`
- **Component Monitoring**: Automatic health checks for all components

See [Health Monitoring](health.md) for complete details.