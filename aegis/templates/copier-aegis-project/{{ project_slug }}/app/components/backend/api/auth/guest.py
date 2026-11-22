"""Guest sign-in (``auth[guest]``): "Continue as guest" starts a session of
its own on the one shared guest account (``domains/sessions/guest.py``).

Behind two checks before any session is made: how many guest sessions one
address may start (``RATE_LIMIT_GUEST_*``, counted across processes), then
Cloudflare Turnstile (``turnstile.py``, off without keys).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status

from app.components.backend.api.auth.sessions import sign_in
from app.components.backend.security import turnstile
from app.components.backend.security.rate_limit import get_client_ip, too_many
from app.core.audit import AuditEmitter, get_audit
from app.core.limits import Budget
from app.core.visitor import GUEST
from app.models.user import TokenResponse
from app.services.auth.deps import get_refresh_service, get_user_service
from app.services.auth.service import RefreshService, UserService, guest_user

router = APIRouter(prefix="/auth", tags=["auth"])

STARTS = Budget("guest-starts", "RATE_LIMIT_GUEST_MAX", "RATE_LIMIT_GUEST_WINDOW")


@router.post("/guest", response_model=TokenResponse)
async def guest_sign_in(
    request: Request,
    response: Response,
    human: Annotated[str | None, Form(alias=turnstile.FIELD)] = None,
    users: UserService = Depends(get_user_service),
    refresh_service: RefreshService = Depends(get_refresh_service),
    audit: AuditEmitter = Depends(get_audit),
) -> TokenResponse:
    """Sign in as a guest: a new session on the shared guest account, its
    cookies set as every sign-in sets them. 429 past the address's limit,
    403 when the human check fails."""
    ip = get_client_ip(request)
    if not await STARTS.take(ip or "unknown"):
        raise too_many(STARTS.window_seconds)
    if not await turnstile.passed(human, ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="guest_human")
    user = await guest_user(users)
    if not user.is_active:  # the operator closed guest sign-in
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="guest_closed")
    access_token = await sign_in(request, response, user, GUEST, refresh_service)
    await audit.emit("auth.guest_sign_in", actor_id=user.id, ip_address=ip)
    return TokenResponse(access_token=access_token)
