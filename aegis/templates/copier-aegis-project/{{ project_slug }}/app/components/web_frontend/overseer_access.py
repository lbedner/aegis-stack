"""Who may use the Overseer: admins (``is_admin``), on every page, stream
and action. Applied once, to the pages router, so a page or partial added
later cannot forget it; tests/web/test_overseer_admin_gate.py walks them
all as a signed-in non-admin.

Signed out, a page goes to the login and anything else (a partial, a
stream) is 401. Signed in but not an admin, a page renders the refusal,
which says how to get in, and anything else is a plain 403.

The user lookup is the request's own (``get_optional_user``), shared with
the route's, so it costs no query; the session it opens closes when the
handler returns, before a stream's body is sent (FastAPI 0.116, pinned in
pyproject), so a stream holds no connection.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import Response

from app.models.user import User
from app.services.auth.deps import get_optional_user, is_admin

from .rendering import templates

PREFIXES = ("/overseer", "/partials/overseer")
# Reachable signed out: the way in.
PUBLIC = frozenset({"/overseer/login"})
LOGIN = "/overseer/login"
REFUSED = "Admins only. Add your email to ADMIN_USER_EMAILS."


class AdminOnlyError(Exception):
    """A signed-in non-admin asked for an Overseer page."""


def _is_page(request: Request) -> bool:
    """A page the browser navigates to, as opposed to a fragment or stream."""
    path = request.url.path
    return (
        request.method == "GET"
        and path.startswith("/overseer")
        and not path.startswith("/overseer/events")
    )


async def overseer_gate(
    request: Request, user: User | None = Depends(get_optional_user)
) -> None:
    """Let admins through every Overseer route; send everyone else away."""
    path = request.url.path
    if not path.startswith(PREFIXES) or path in PUBLIC:
        return
    if user is None:
        if _is_page(request):
            raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    if is_admin(user):
        return
    if _is_page(request):
        raise AdminOnlyError
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=REFUSED)


async def admin_only_page(request: Request, exc: Exception) -> Response:
    """The refusal page: who is signed in, and how an admin is made."""
    return templates.TemplateResponse(
        request, "pages/overseer/forbidden.html", status_code=403
    )
