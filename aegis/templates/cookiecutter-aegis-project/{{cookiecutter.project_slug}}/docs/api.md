# API Reference

{{ cookiecutter.project_name }} provides a FastAPI-based REST API with automatic documentation.

## Interactive Documentation

When running the application, interactive API documentation is available at:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI Schema**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## Health Endpoints

### Basic Health Check

**GET** `/health/`

Returns basic health status of the application.

```bash
curl http://localhost:8000/health/
```

**Response:**
```json
{
  "healthy": true,
  "status": "healthy",
  "components": {},
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### Detailed Health Check

**GET** `/health/detailed`

Returns comprehensive health information including system metrics.

```bash
curl http://localhost:8000/health/detailed
```

**Response:**
```json
{
  "healthy": true,
  "status": "healthy", 
  "components": {
    "system": {
      "status": "healthy",
      "cpu_percent": 15.2,
      "memory_percent": 45.8,
      "disk_percent": 32.1,
      "response_time_ms": 2.1
    }{% if cookiecutter.include_scheduler == "yes" %},
    "scheduler": {
      "status": "healthy",
      "active_jobs": 2,
      "next_run": "2024-01-01T02:00:00Z",
      "response_time_ms": 1.5
    }{% endif %}
  },
  "timestamp": "2024-01-01T00:00:00Z",
  "uptime_seconds": 3600
}
```

## Authentication

Currently, {{ cookiecutter.project_name }} does not implement authentication. 

To add authentication:

1. **Install dependencies:**
   ```bash
   uv add python-jose[cryptography] passlib[bcrypt]
   ```

2. **Add authentication routes:**
   ```python
   # app/components/backend/api/auth.py
   from fastapi import APIRouter, Depends, HTTPException, status
   from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
   
   router = APIRouter()
   oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
   
   @router.post("/token")
   async def login(form_data: OAuth2PasswordRequestForm = Depends()):
       # Implement login logic
       pass
   ```

3. **Register in routing:**
   ```python
   # app/components/backend/api/routing.py
   from app.components.backend.api import auth
   
   def include_routers(app: FastAPI) -> None:
       app.include_router(auth.router, prefix="/auth", tags=["authentication"])
   ```

## CORS Configuration

CORS is pre-configured to allow all origins in development. For production, update the CORS middleware in `app/components/backend/middleware/cors.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Error Handling

The API includes standard HTTP error responses:

- **400 Bad Request**: Invalid request data
- **404 Not Found**: Resource not found  
- **422 Unprocessable Entity**: Validation errors
- **500 Internal Server Error**: Server errors

Custom error handlers can be added in `app/components/backend/main.py`:

```python
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=404,
        content={"message": "Resource not found"}
    )
```

## Adding Custom Endpoints

### 1. Create Router Module

```python
# app/components/backend/api/my_api.py
from fastapi import APIRouter, HTTPException
from app.services.my_service import get_data, create_item

router = APIRouter()

@router.get("/items")
async def list_items():
    """Get all items."""
    items = await get_data()
    return {"items": items}

@router.post("/items")
async def create_item_endpoint(name: str):
    """Create a new item."""
    try:
        item = await create_item(name)
        return {"item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### 2. Register Router

```python
# app/components/backend/api/routing.py
from app.components.backend.api import my_api

def include_routers(app: FastAPI) -> None:
    app.include_router(my_api.router, prefix="/api", tags=["items"])
```

### 3. Add Tests

```python
# tests/api/test_my_api.py
def test_list_items(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    assert "items" in response.json()
```

The API will automatically include your endpoints in the interactive documentation at `/docs`.