# app/components/backend/middleware/cors.py
"""
Auto-discovered CORS middleware for development.

This middleware is automatically registered with FastAPI when the backend starts.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def register_middleware(app: FastAPI) -> None:
    """Auto-discovered middleware registration."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
