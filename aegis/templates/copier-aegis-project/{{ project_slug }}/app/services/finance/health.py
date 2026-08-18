"""Health check for the finance service (dashboard ComponentStatus).

Mirrors ``payment/health.py`` but has no upstream-provider probe to cache —
it reads DB-backed counts fresh. The returned ``metadata`` dict is the
contract the dashboard card/modal read from.
"""

import logging

from app.core.db import get_async_session
from app.services.system.models import ComponentStatus, ComponentStatusType

from .constants import FINANCE_COMPONENT_NAME
from .service import FinanceService

logger = logging.getLogger(__name__)


async def check_finance_service_health() -> ComponentStatus:
    """Report finance health: account/connection counts + attention state."""
    try:
        async with get_async_session() as session:
            service = FinanceService(session)
            summary = await service.get_status_summary()
            health = await service.health()
        metadata = summary.model_dump(mode="json")
        metadata["status"] = health.status
        metadata["connections_needing_action"] = health.connections_needing_action
        status = (
            ComponentStatusType.HEALTHY
            if health.status == "ok"
            else ComponentStatusType.WARNING
        )
        message = (
            f"{summary.account_count} accounts, {summary.connection_count} connections"
        )
        return ComponentStatus(
            name=FINANCE_COMPONENT_NAME,
            status=status,
            message=message,
            metadata=metadata,
        )
    except Exception as e:
        logger.exception("Finance health check failed")
        return ComponentStatus(
            name=FINANCE_COMPONENT_NAME,
            status=ComponentStatusType.UNHEALTHY,
            message=f"Health check error: {e}",
            metadata={"error": str(e)},
        )
