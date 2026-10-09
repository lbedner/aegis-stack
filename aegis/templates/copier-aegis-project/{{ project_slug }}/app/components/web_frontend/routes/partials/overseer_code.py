"""Overseer > Code fragments, mounted behind the Overseer gate: a clicked
name's definition and references, in a popover beside it."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.components.web_frontend import overseer_code
from app.components.web_frontend.rendering import fragment

router = APIRouter()


@router.get(overseer_code.SYMBOL, response_class=HTMLResponse, include_in_schema=False)
async def symbol(
    path: str = Query("", alias=overseer_code.FILE),
    line: int = Query(1, ge=1),
    col: int = Query(0, ge=0),
) -> HTMLResponse:
    if not overseer_code.enabled():
        raise HTTPException(status_code=404)
    context = overseer_code.symbol_context(path, line, col)
    return HTMLResponse(fragment("pages/overseer/code/_symbol.html", **context))
