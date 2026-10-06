"""The Overseer MCP page's token dialogs: make one (its value shown once),
and the revoke confirmation, whose button calls the token API. Mounted by
``routes/pages.py`` at ``overseer_mcp.PARTIALS`` behind Overseer's gate.

Tokens belong to people, so every route here is 404 without auth.
"""

from types import ModuleType
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_mcp
from app.components.web_frontend.overseer_access import overseer_actor, overseer_db
from app.components.web_frontend.overseer_nav import page_url
from app.components.web_frontend.rendering import dialog
from app.services.shared.deps import Actor
from app.services.system import ui_mcp

router = APIRouter(prefix=overseer_mcp.PARTIALS)

NEW = "pages/overseer/mcp/_new_token.html"
MADE = "pages/overseer/mcp/_token_made.html"
PAGE = page_url("components", ui_mcp.NAME) + "/tokens"
SCOPES = [{"id": key, "name": label} for key, label in ui_mcp.SCOPE_LABELS.items()]


def _tokens() -> ModuleType:
    """``app.components.mcp.tokens``; 404 without auth, where it is not."""
    if not ui_mcp.has_tokens():
        raise HTTPException(status_code=404)
    from app.components.mcp import tokens

    return tokens


def _form(
    request: Request, form: dict[str, str], errors: list[str], status_code: int = 200
) -> Response:
    return dialog(
        request,
        NEW,
        status_code,
        form=form,
        errors=errors,
        scopes=SCOPES,
        partials=overseer_mcp.PARTIALS,
    )


@router.get("/tokens/new", response_class=HTMLResponse)
async def new_token(request: Request) -> Response:
    """The new-token form."""
    _tokens()
    return _form(request, {}, [])


@router.post("/tokens", response_class=HTMLResponse)
async def make_token(
    request: Request,
    name: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "read",
    actor: Actor = Depends(overseer_actor),
    db: Any = Depends(overseer_db),
) -> Response:
    """Make a token for the viewer and show its value, this once."""
    tokens = _tokens()
    form = {"name": name, "scope": scope}
    if not name.strip():
        return _form(request, form, ["Name the token."], 422)
    try:
        row, value = await tokens.create(db, actor.id, name.strip(), scope)
    except ValueError as exc:
        return _form(request, form, [str(exc)], 422)
    return dialog(
        request,
        MADE,
        name=row.name,
        scope=ui_mcp.SCOPE_LABELS[row.scope],
        value=value,
        shown_once=ui_mcp.SHOWN_ONCE,
        page=PAGE,
    )


@router.get("/tokens/{token_id}/revoke", response_class=HTMLResponse)
async def confirm_revoke(
    request: Request,
    token_id: int,
    actor: Actor = Depends(overseer_actor),
    db: Any = Depends(overseer_db),
) -> Response:
    """The revoke confirmation. Its button calls the token API."""
    rows = await _tokens().live(db, actor.id)
    row = next((r for r in rows if r.id == token_id), None)
    if row is None:
        raise HTTPException(status_code=404)
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title="Revoke token",
        body=f"Revoke {row.name}? A client using it is refused on its next request.",
        method="delete",
        url=f"/api/v1/mcp/tokens/{row.id}",
        label="Revoke",
        done="Token revoked",
    )
