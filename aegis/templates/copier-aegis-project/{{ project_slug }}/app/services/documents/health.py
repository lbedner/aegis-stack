"""Health check for the document store (dashboard ComponentStatus).

The returned ``metadata`` is the contract the Documents card reads:
``total``, ``this_month``, ``bytes``, ``by_kind``, plus the storage
backend holding the bytes.
"""

import logging

from app.core.db import get_async_session
from app.core.storage import get_storage
from app.services.system.models import ComponentStatus, ComponentStatusType

from .service import DocumentService

logger = logging.getLogger(__name__)

DOCUMENTS_COMPONENT_NAME = "documents"
# The health-tree id: the key the card opens and the modal registers under.
DOCUMENTS_MODAL_ID = f"service_{DOCUMENTS_COMPONENT_NAME}"


async def check_documents_service_health() -> ComponentStatus:
    """Report how much paper the store holds and where."""
    try:
        async with get_async_session() as session:
            summary = await DocumentService(session).summary()
        metadata = {**summary, "backend": get_storage().backend_name}
        if summary["total"] == 0:
            return ComponentStatus(
                name=DOCUMENTS_COMPONENT_NAME,
                status=ComponentStatusType.INFO,
                message="No documents yet",
                metadata=metadata,
            )
        return ComponentStatus(
            name=DOCUMENTS_COMPONENT_NAME,
            status=ComponentStatusType.HEALTHY,
            message=f"{summary['total']} documents, {summary['this_month']} this month",
            metadata=metadata,
        )
    except Exception as e:
        logger.exception("Documents health check failed")
        return ComponentStatus(
            name=DOCUMENTS_COMPONENT_NAME,
            status=ComponentStatusType.UNHEALTHY,
            message=f"Health check error: {e}",
            metadata={"error": str(e)},
        )
