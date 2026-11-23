"""Audit events: each one a log line, and a row in the audit log where the
stack has the database component (``app.components.database.audit``).

The row is written off the caller, in a session of its own: it survives the
caller's rollback, and the caller never waits on it (on SQLite, a caller
holding its session would wait on itself). A write that fails is logged,
never raised; a process waits for the rest as it ends (``concurrency.drain``).
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
import getpass
import logging
from typing import Any

from app.core.concurrency import background
from app.core.discovery import optional

logger = logging.getLogger("audit")


def keeper() -> Callable[[dict[str, Any]], Coroutine[object, object, None]] | None:
    """What keeps an event beside its log line, where the stack has one."""
    return optional("app.components.database.audit", "keep")


class AuditEmitter:
    """Emit structured audit events: a log line, and a row where kept."""

    async def emit(
        self,
        event_type: str,
        *,
        actor_id: int | None = None,
        actor_email: str | None = None,
        target_type: str | None = None,
        target_id: int | str | None = None,
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
        keep = keeper()
        if keep is not None:
            background(keep(event), finish=True)  # a failure is logged there


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
