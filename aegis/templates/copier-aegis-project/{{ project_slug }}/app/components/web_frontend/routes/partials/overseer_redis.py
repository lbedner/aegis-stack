"""Fragments for the Overseer Redis page: one key family's detail.

Mounted by ``routes/pages.py`` at ``overseer_redis.PARTIALS``.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_redis
from app.components.web_frontend.rendering import templates

router = APIRouter(prefix=overseer_redis.PARTIALS)


@router.get("/family/{family}", response_class=HTMLResponse)
async def family_detail(request: Request, family: int) -> Response:
    """What one key family is for and what its newest key holds."""
    keyspace = await overseer_redis.load_keyspace()
    found = next((f for f in keyspace.get("families", []) if f["id"] == family), None)
    if found is None:
        raise HTTPException(status_code=404)
    view = overseer_redis.keyspace_view({"families": [found]})["keyspace"]["families"][
        0
    ]
    return templates.TemplateResponse(
        request,
        "pages/overseer/redis/_family.html",
        {
            "family": view,
            "peek": overseer_redis.peek_view(await overseer_redis.load_peek(family)),
        },
    )
