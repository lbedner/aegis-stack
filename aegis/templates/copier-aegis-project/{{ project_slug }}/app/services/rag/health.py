"""
RAG service health check.

Provides health check functions for monitoring RAG service status.
"""

from typing import Any

from app.core.log import logger

from .collections import collection_stats
from .config import get_rag_service


async def check_rag_service_health() -> dict[str, Any]:
    """
    Check RAG service health status.

    Returns:
        dict: Health status including:
            - healthy: bool indicating if service is operational
            - status: Current service status and config
            - collections: List of available collections
            - issues: Any validation issues
    """
    try:
        service = get_rag_service()

        # Get service status
        status = service.get_service_status()

        # Validate configuration
        issues = service.validate_service()

        collection_info = await collection_stats()

        healthy = len(issues) == 0 and status.get("enabled", False)

        return {
            "healthy": healthy,
            "status": status,
            "collections": [c.model_dump() for c in collection_info],
            "collection_count": len(collection_info),
            "issues": issues,
        }

    except Exception as e:
        logger.error("rag_health_check.failed", error=str(e))
        return {
            "healthy": False,
            "status": None,
            "collections": [],
            "collection_count": 0,
            "issues": [f"Health check failed: {e}"],
        }
