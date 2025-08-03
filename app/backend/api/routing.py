from fastapi import FastAPI

from app.backend.api import health


def include_routers(app: FastAPI) -> None:
    """Include all API routers in the FastAPI app"""
    app.include_router(health.router, prefix="/health", tags=["health"])
