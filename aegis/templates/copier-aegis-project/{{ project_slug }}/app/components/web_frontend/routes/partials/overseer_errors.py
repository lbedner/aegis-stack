"""Read-only Errors fragments and SSE, mounted behind the Overseer gate."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from app.components.web_frontend import overseer_errors
from app.components.web_frontend.overseer_live import event_stream
from app.services.system import ui_errors

router = APIRouter()


@router.get(
    "/partials/overseer/errors", response_class=HTMLResponse, include_in_schema=False
)
async def rows(request: Request) -> HTMLResponse:
    return HTMLResponse(await overseer_errors.list_fragment(request.query_params))


@router.get(overseer_errors.EVENTS, include_in_schema=False)
async def events(request: Request) -> StreamingResponse:
    return event_stream(overseer_errors.events(request.query_params))


@router.get(
    overseer_errors.DETAIL, response_class=HTMLResponse, include_in_schema=False
)
async def detail(request: Request) -> HTMLResponse:
    query = request.query_params
    context = await ui_errors.load(query, ui_errors.load_detail)
    return HTMLResponse(overseer_errors.detail(context, query))
