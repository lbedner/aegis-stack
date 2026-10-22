"""The landing page at ``/``, the framework's front door: mounted by
``main.py`` where the project has no public site of its own (a site's
``routes/site.py`` owns the root instead)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.components.web_frontend.overseer_access import overseer_gate
from app.components.web_frontend.rendering import templates

router = APIRouter(dependencies=[Depends(overseer_gate)])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing(request: Request) -> HTMLResponse:
    """Landing page."""
    return templates.TemplateResponse(request=request, name="pages/landing.html")
