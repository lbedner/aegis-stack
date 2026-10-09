"""Overseer's write actions through the socket proxy, behind
``get_admin_actor``: restart one of this app's containers. Every attempt is
audited (who, what, when and how it went), refused ones included. The proxy
allows only this write; the app refuses a container its own services do not
list (``runtime.mine``).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.components.backend.api.utils import audit_admin_action
from app.core import runtime
from app.core.audit import AuditEmitter, get_audit
from app.core.runtime import RuntimeUnavailableError, UnknownInstanceError
from app.services.shared.deps import Actor, get_admin_actor

router = APIRouter(prefix="/runtime", tags=["runtime"])


class Restarted(BaseModel):
    restarted: str
    # The container answering this request: it restarts after the answer.
    own: bool = False


@router.post("/containers/{name}/restart", response_model=Restarted)
async def restart_container(
    name: str,
    request: Request,
    after: BackgroundTasks,
    actor: Actor = Depends(get_admin_actor),
    audit: AuditEmitter = Depends(get_audit),
) -> Restarted:
    """Restart ``name``: 404 for a container that is not this app's, 503
    when the runtime cannot (no deploy target, the proxy refused). The
    container answering this request restarts after the answer, or the
    answer would never arrive; its outcome is the server coming back."""
    try:
        found = await runtime.mine(name)
        if runtime.is_own(found):
            await _audit(
                audit, actor, request, name, "restarting", f"Restarting {name}"
            )
            after.add_task(runtime.restart, found)
            return Restarted(restarted=name, own=True)
        await runtime.restart(found)
    except UnknownInstanceError as exc:
        await _audit(audit, actor, request, name, "refused", str(exc))
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except RuntimeUnavailableError as exc:
        await _audit(audit, actor, request, name, "failed", str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    await _audit(audit, actor, request, name, "restarted", f"Restarted {name}")
    return Restarted(restarted=name)


async def _audit(
    audit: AuditEmitter,
    actor: Actor,
    request: Request,
    name: str,
    outcome: str,
    detail: str,
) -> None:
    await audit_admin_action(
        audit,
        actor,
        request,
        "runtime.container_restart",
        outcome,
        detail,
        container=name,
    )
