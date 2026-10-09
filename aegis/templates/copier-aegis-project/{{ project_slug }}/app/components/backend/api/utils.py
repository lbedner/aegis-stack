"""Shared API utilities for common error patterns, and the audit every
admin write action records."""

from typing import Any

from fastapi import HTTPException, Request, status

from app.components.backend.security.rate_limit import get_client_ip
from app.core.audit import AuditEmitter
from app.services.shared.deps import Actor


async def audit_admin_action(
    audit: AuditEmitter,
    actor: Actor,
    request: Request,
    event_type: str,
    outcome: str,
    detail: str,
    **target: Any,
) -> None:
    """One admin action, refused ones included: who, from where (the
    client behind a trusted proxy), what it was done to, and how it went."""
    await audit.emit(
        event_type,
        actor_id=actor.id,
        actor_email=actor.email,
        ip_address=get_client_ip(request),
        detail=detail,
        outcome=outcome,
        **target,
    )


def raise_not_found(resource: str) -> None:
    """Raise 404 for a missing resource."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource} not found",
    )


def raise_bad_request(detail: str) -> None:
    """Raise 400 with a detail message."""
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
    )


def validate_role(role: str, valid_roles: set[str]) -> None:
    """Validate a role is in the allowed set. Raises 400 if not."""
    if role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role}. Valid: {sorted(valid_roles)}",
        )
