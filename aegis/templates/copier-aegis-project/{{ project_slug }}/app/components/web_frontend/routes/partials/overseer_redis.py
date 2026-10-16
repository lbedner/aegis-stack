"""Fragments for the Overseer Redis page: one key family's detail.

Mounted by ``routes/pages.py`` at ``overseer_redis.PARTIALS``.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_redis
from app.components.web_frontend.rendering import templates
from app.services.system import redis_facts

router = APIRouter(prefix=overseer_redis.PARTIALS)


@router.get("/family/{family}", response_class=HTMLResponse)
async def family_detail(request: Request, family: int) -> Response:
    """What one key family is for, how much it holds and has passed
    through, and what its newest key holds."""
    keyspace = await overseer_redis.load_keyspace()
    found = next((f for f in keyspace.families if f.id == family), None)
    if found is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "pages/overseer/redis/_family.html",
        {"row": found, "detail": await redis_facts.detail(family, found.latest)},
    )
