# Backend Component

The **Backend Component** handles HTTP requests and API endpoints for your Aegis Stack application using [FastAPI](https://fastapi.tiangolo.com/).

## Adding API Routes

API routes require **explicit registration** to maintain clear dependency tracking:

**Step 1: Create your router**
```python
# app/components/backend/api/data.py
from fastapi import APIRouter
from app.services.data_service import get_dashboard_stats, trigger_manual_ingestion

router = APIRouter()

@router.get("/data/stats")
async def get_stats():
    stats = await get_dashboard_stats()
    return {"status": "success", "data": stats}

@router.post("/data/ingest")
async def trigger_ingestion():
    await trigger_manual_ingestion()
    return {"status": "ingestion_started"}
```

**Step 2: Register explicitly**
```python
# app/components/backend/api/routing.py
from app.components.backend.api import data

def include_routers(app: FastAPI) -> None:
    app.include_router(data.router, prefix="/api", tags=["data"])
```

> **Why manual registration?** API routes define your application's public interface. Explicit registration makes dependencies clear and prevents accidental exposure of endpoints.

## Adding Backend Hooks (Auto-Discovered)

Backend hooks are **automatically discovered** by dropping files in designated folders:

```
app/components/backend/
├── middleware/     # Auto-discovered middleware  
├── startup/        # Auto-discovered startup hooks
└── shutdown/       # Auto-discovered shutdown hooks
```

**Example: Add CORS middleware**
```python
# app/components/backend/middleware/cors.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

async def register_middleware(app: FastAPI) -> None:
    """Auto-discovered middleware registration."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"]
    )
```

**No registration required** - just drop the file and restart. See the [Integration Patterns](../integration-patterns.md) for complete details.

## Integration

FastAPI integrates with your application and provides:

- **Interactive docs** at `/docs` (Swagger UI)
- **API schema** at `/openapi.json`  
- **Health check** at `/health`
- **CORS enabled** for frontend integration

## Configuration

The backend runs on port 8000 and is configured through the integration layer with automatic JSON serialization and validation.


## Next Steps

- **[FastAPI Documentation](https://fastapi.tiangolo.com/)** - Complete API framework capabilities
- **[FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)** - Building APIs with FastAPI
- **[Component Overview](./index.md)** - Understanding Aegis Stack's component architecture
- **[Philosophy Guide](../philosophy.md)** - Component architecture principles