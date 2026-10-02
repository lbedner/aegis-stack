"""Generic audit event emitter with pluggable backends."""

from datetime import UTC, datetime
import getpass
import logging
from typing import Any

logger = logging.getLogger("audit")


class AuditEmitter:
    """Emit structured audit events. Default backend: structured logging."""

    async def emit(
        self,
        event_type: str,
        *,
        actor_id: int | None = None,
        actor_email: str | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        org_id: int | None = None,
        ip_address: str | None = None,
        detail: str | None = None,
        **extra: Any,
    ) -> None:
        """Emit an audit event.

        Args:
            event_type: Domain-prefixed event name (e.g., "auth.login_success")
            actor_id: ID of the user performing the action
            actor_email: Email of the actor
            target_type: Type of the target resource (e.g., "user", "org", "member")
            target_id: ID of the target resource
            org_id: Organization scope (if applicable)
            ip_address: Client IP address
            detail: Human-readable description
            **extra: Additional context
        """
        event = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "actor_id": actor_id,
            "actor_email": actor_email,
            "target_type": target_type,
            "target_id": target_id,
            "org_id": org_id,
            "ip_address": ip_address,
            "detail": detail,
            **extra,
        }
        # Remove None values for cleaner output
        event = {k: v for k, v in event.items() if v is not None}
        logger.info(f"AUDIT: {event_type}", extra={"audit": event})


# Singleton instance
audit_emitter = AuditEmitter()


def cli_actor() -> str:
    """Who a change made from the terminal is recorded as."""
    return f"cli:{getpass.getuser()}"


def get_audit() -> AuditEmitter:
    """FastAPI dependency provider returning the audit emitter singleton.

    Lives with the emitter rather than under
    ``app/components/backend/api/deps.py`` so per-service deps modules
    can import it without going through the api shim (see
    ``app.core.db`` for the same pattern + rationale)."""
    return audit_emitter
