# Integration Patterns Reference

Quick reference for how different parts of Aegis Stack integrate with each other.

## Backend Integration Patterns

**🔄 Auto-Discovered**: Drop files, no registration required

- **Middleware**: `app/components/backend/middleware/`
- **Startup Hooks**: `app/components/backend/startup/`  
- **Shutdown Hooks**: `app/components/backend/shutdown/`

**📝 Manual Registration**: Explicit imports for clarity

- **API Routes**: Register in `app/components/backend/api/routing.py`
- **Services**: Import explicitly where needed

## Service Integration Patterns

Put your business logic in `app/services/` and import it explicitly where needed.

**Services** contain pure business logic functions. **Components** import and use them.

```python
# app/services/report_service.py
async def generate_monthly_report(user_id: int) -> Report:
    # Your business logic here
    pass

# app/components/backend/api/reports.py  
from app.services.report_service import generate_monthly_report

@router.post("/reports")
async def create_report(user_id: int):
    return await generate_monthly_report(user_id)

# app/components/scheduler/main.py
from app.services.report_service import generate_monthly_report

scheduler.add_job(generate_monthly_report, args=[123])
```

**What Goes Where:**

**Services** (`app/services/`):

- Database interactions, external API calls, file processing
- Complex business logic and data transformations  
- Pure functions that can be unit tested
- Single files (`report_service.py`) or folders (`system/health.py`) for complex domains

**Components** (`app/components/`):

- API endpoints, scheduled jobs, UI handlers
- Import services explicitly - no magic auto-discovery
- Keep thin - handle requests, call services, return responses

**Why explicit?** Makes dependencies clear, prevents surprises, easier testing.

## Component Communication

**Backend ↔ Services**: Direct imports
```python
from app.services.system import get_system_status
```

**CLI ↔ Backend**: HTTP API calls
```python
from app.services.system.models import HealthResponse
health_data = HealthResponse.model_validate(api_response.json())
```

**Frontend ↔ Backend**: Flet-FastAPI integration
```python
from app.services.system import get_system_status
# Direct function calls within same process
```

## Data Validation Boundaries

**Trust Zones**: Validate at entry points, trust internally

1. **API Endpoints**: Pydantic `response_model` validates outgoing data
2. **CLI Commands**: Pydantic models validate API responses  
3. **Internal Code**: Direct model attribute access (no `.get()` patterns)

```python
# Entry point - validate hard
@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    # Internal code - trust the data
    status = await get_system_status()
    return HealthResponse(healthy=status.overall_healthy, ...)

# CLI - validate API response
health_data = HealthResponse.model_validate(response.json())
# Then trust: health_data.healthy (not health_data.get("healthy"))
```

## Scheduler Integration

**Job Registration**: Explicit in scheduler component

```python
# app/components/scheduler/main.py
from app.services.reports import generate_daily_report

scheduler.add_job(
    generate_daily_report,
    trigger="cron", 
    hour=9, minute=0
)
```

**Service Functions**: Pure business logic
```python
# app/services/reports.py
async def generate_daily_report() -> None:
    # Pure business logic, no scheduler dependencies
```

## Configuration Access

**Global Settings**: Available everywhere

```python
from app.core.config import settings

# Use throughout application
database_url = settings.DATABASE_URL
api_timeout = settings.API_TIMEOUT
```

**Constants vs Config**:

- **Constants** (`app.core.constants`): Immutable values (API paths, timeouts)
- **Config** (`app.core.config`): Environment-dependent values (URLs, secrets)

## Container Boundaries

Each component manages its own concerns:

- **Backend Container**: Runs FastAPI + Flet, manages backend hooks
- **Scheduler Container**: Runs APScheduler, manages scheduled jobs
- **Shared**: Services, core utilities, configuration

**No Cross-Container Hooks**: Backend hooks don't affect scheduler, and vice versa.

## Key Principles

1. **Auto-discovery for infrastructure** (hooks) → convenience
2. **Explicit imports for business logic** (services, routes) → clarity  
3. **Validate at boundaries** → security and reliability
4. **Trust internally** → clean, readable code
5. **Container isolation** → independent scaling