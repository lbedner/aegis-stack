from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backend.api.routing import include_routers


def create_backend_app(app: FastAPI) -> FastAPI:
    """Configure FastAPI app with all backend concerns"""

    # Basic CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include all routes
    include_routers(app)

    return app
