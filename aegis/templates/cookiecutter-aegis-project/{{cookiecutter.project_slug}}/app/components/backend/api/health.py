from typing import Any

from fastapi import APIRouter, HTTPException
from starlette import status

from app.services.system import (
    DetailedHealthResponse,
    HealthResponse,
    get_system_status,
)

router = APIRouter()


@router.get("/", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Quick health check endpoint.

    Returns basic healthy/unhealthy status for load balancers and monitoring.
    """
    try:
        system_status = await get_system_status()
        return HealthResponse(
            healthy=system_status.overall_healthy,
            status="healthy" if system_status.overall_healthy else "unhealthy",
            components=system_status.components,
            timestamp=system_status.timestamp.isoformat(),
        )
    except Exception:
        # If health checks fail completely, consider unhealthy
        return HealthResponse(
            healthy=False,
            status="unhealthy",
            components={},
            timestamp="",
        )


@router.get("/detailed", response_model=DetailedHealthResponse)
async def detailed_health() -> DetailedHealthResponse:
    """
    Detailed health check with component information.

    Returns comprehensive system status including individual component health,
    system metrics, and diagnostic information.
    """
    try:
        system_status = await get_system_status()

        # Always return 200 OK - service is available even if components are unhealthy
        return DetailedHealthResponse(
            healthy=system_status.overall_healthy,
            status="healthy" if system_status.overall_healthy else "unhealthy",
            service="{{ cookiecutter.project_name }}",
            version="0.1.0",
            components=system_status.components,
            system_info=system_status.system_info,
            timestamp=system_status.timestamp.isoformat(),
            healthy_components=system_status.healthy_components,
            unhealthy_components=system_status.unhealthy_components,
            health_percentage=system_status.health_percentage,
        )

    except HTTPException:
        # Re-raise HTTP exceptions from unexpected errors
        raise
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Health check failed",
                "error": str(e),
                "status": "unhealthy",
            },
        )


@router.get("/dashboard")
async def system_dashboard() -> dict[str, Any]:
    """
    System dashboard endpoint optimized for frontend consumption.

    Returns system status with additional dashboard metadata like
    alert counts, trend data, and formatted display information.
    """
    try:
        system_status = await get_system_status()

        # TODO: Implement alert tracking when alert management is enhanced
        recent_alerts = 0

        return {
            "status": "healthy" if system_status.overall_healthy else "unhealthy",
            "service": "{{ cookiecutter.project_name }}",
            "version": "0.1.0",
            "dashboard_data": {
                "overall_status": {
                    "healthy": system_status.overall_healthy,
                    "percentage": system_status.health_percentage,
                    "status_text": (
                        "System Healthy"
                        if system_status.overall_healthy
                        else "Issues Detected"
                    ),
                },
                "components": {
                    name: {
                        "name": name,
                        "healthy": component.healthy,
                        "message": component.message,
                        "response_time_ms": component.response_time_ms,
                        "metadata": component.metadata,
                    }
                    for name, component in system_status.components.items()
                },
                "summary": {
                    "total_components": len(system_status.components),
                    "healthy_components": len(system_status.healthy_components),
                    "unhealthy_components": len(system_status.unhealthy_components),
                    "recent_alerts": recent_alerts,
                },
                "system_info": system_status.system_info,
                "timestamp": system_status.timestamp.isoformat(),
                "last_updated": system_status.timestamp.strftime("%H:%M:%S"),
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Dashboard data unavailable", "error": str(e)},
        )
