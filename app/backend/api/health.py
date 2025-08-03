from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/detailed")
async def detailed_health() -> dict[str, Any]:
    return {"status": "healthy", "service": "aegis-stack", "version": "0.1.0"}
