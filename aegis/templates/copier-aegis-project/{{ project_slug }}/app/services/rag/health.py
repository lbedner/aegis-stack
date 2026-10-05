"""
RAG service health check.

Provides health check functions for monitoring RAG service status.
"""

from typing import Any

from app.core.log import logger

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

        # List collections
        collections = await service.list_collections()

        # Get collection details
        collection_info = []
        for name in collections:
            info = await service.get_collection_stats(name)
            if info:
                collection_info.append(info)

        healthy = len(issues) == 0 and status.get("enabled", False)

        return {
            "healthy": healthy,
            "status": status,
            "collections": collection_info,
            "collection_count": len(collections),
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
