"""Overseer's pages and its streams. Mounted by ``routes/pages.py`` behind
its gate (``overseer_access``), after
the partial routers, so a partial's path wins over the catch-all pages."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from app.components.web_frontend import (
    overseer_connections,
    overseer_container,
    overseer_redis,
    overseer_secrets,
    overseer_worker,
)
from app.components.web_frontend.overseer_access import (
    Db,
    Viewer,
    overseer_db,
    session_expires,
    session_id,
    viewer,
)
from app.components.web_frontend.overseer_events import health_events
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.overseer_nav import (
    SectionRequest,
    build_navigation,
    find_item,
)
from app.components.web_frontend.overseer_sections import (
    SECTIONED_PAGES,
    STANDALONE,
    page_for,
)
from app.components.web_frontend.rendering import render
from app.services.system.health import last_system_status

router = APIRouter()


@router.get("/overseer", response_class=HTMLResponse, include_in_schema=False)
async def overseer_page(request: Request, user: Viewer = Depends(viewer)) -> Response:
    """Overseer's home: every page's glance at its containers."""
    status = last_system_status()
    navigation = build_navigation(status)
    overview = await overseer_container.overview(
        navigation, request.query_params.get("view"), request.query_params.get("zoom")
    )
    return render(
        request,
        name="pages/overseer/index.html",
        context={"user": user, "navigation": navigation, "status": status} | overview,
        page_layout="layouts/overseer.html",
    )


@router.get("/overseer/events", include_in_schema=False)
async def overseer_events() -> StreamingResponse:
    """One stream for all sidebar status indicators."""
    return event_stream(health_events())


@router.get(overseer_redis.KEYSPACE_EVENTS, include_in_schema=False)
async def overseer_redis_keyspace() -> StreamingResponse:
    """The Redis page's keyspace map, while that page is open."""
    return event_stream(overseer_redis.keyspace_events())


@router.get(overseer_worker.QUEUES_EVENTS, include_in_schema=False)
async def overseer_worker_queues() -> StreamingResponse:
    """The Worker page's queues, while that page is open."""
    return event_stream(overseer_worker.queues_events())


@router.get(overseer_connections.EVENTS, include_in_schema=False)
async def overseer_server_connections(request: Request) -> StreamingResponse:
    """The Server page's connections table, filters and all, while it is open."""
    return event_stream(
        overseer_connections.connections_events(dict(request.query_params))
    )


@router.get("/overseer/{group}", response_class=HTMLResponse, include_in_schema=False)
async def overseer_standalone_page(
    request: Request,
    group: str,
    user: Viewer = Depends(viewer),
    db: Db = Depends(overseer_db),
) -> Response:
    """A page outside the health tree (``STANDALONE``). Secrets lives on the
    component's own page when the stack has it."""
    if group == "secrets" and overseer_secrets.has_component():
        return RedirectResponse(url=overseer_secrets.COMPONENT_URL, status_code=303)
    return await _standalone(request, group, "", user, db)


async def _standalone(
    request: Request, group: str, section: str, user: Viewer, db: Db
) -> Response:
    """A ``STANDALONE`` page on one of its sections, its first by default."""
    page = SECTIONED_PAGES.get((group, group))
    if page is None:
        raise HTTPException(status_code=404)
    labels = list(page.labels)
    if section and section not in labels[1:]:
        raise HTTPException(status_code=404)
    return await _overseer_detail(request, group, group, user, db, section or labels[0])


@router.get(
    "/overseer/{group}/{name}", response_class=HTMLResponse, include_in_schema=False
)
async def overseer_detail(
    request: Request,
    group: str,
    name: str,
    user: Viewer = Depends(viewer),
    db: Db = Depends(overseer_db),
) -> Response:
    """A navigable status page for an installed component or service."""
    if group in STANDALONE:
        return await _standalone(request, group, name, user, db)
    return await _overseer_detail(request, group, name, user, db)


@router.get(
    "/overseer/{group}/{name}/{section}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def overseer_section(
    request: Request,
    group: str,
    name: str,
    section: str,
    user: Viewer = Depends(viewer),
    db: Db = Depends(overseer_db),
) -> Response:
    """One section of a page with a sub-menu; the first lives at the page's URL."""
    page = page_for(group, name)
    if page is None or section not in list(page.labels)[1:]:
        raise HTTPException(status_code=404)
    return await _overseer_detail(request, group, name, user, db, section)


async def _overseer_detail(
    request: Request,
    group: str,
    name: str,
    user: Viewer,
    db: Db,
    section: str = "overview",
) -> Response:
    """Render a page on the request's own session (``db``): a second one would
    wait on SQLite's write lock and fail with "database is locked"."""
    status = last_system_status()
    navigation = build_navigation(status)
    item = STANDALONE.get(group) or find_item(navigation, group, name)
    if item is None:
        raise HTTPException(status_code=404)
    context = {"user": user, "navigation": navigation, "status": status, "item": item}
    if page := page_for(group, name):
        req = SectionRequest(
            user,
            db,
            request.query_params,
            request.url.path,
            request.app.routes,
            session_id(request),
            session_expires(request),
        )
        context |= {"page": page, "current": section}
        context |= await page.context(section, item.component, req)
    return render(
        request,
        name="pages/overseer/detail.html",
        context=context,
        page_layout="layouts/overseer.html",
    )
