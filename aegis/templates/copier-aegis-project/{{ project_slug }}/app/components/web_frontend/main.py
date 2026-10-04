"""Web frontend component - Jinja2 + htmx + Alpine.js.

Pages are served at ``/`` by the same webserver that hosts the API and the
Flet dashboard at ``/dashboard``. The pieces live beside this module:
``assets.py`` (fingerprinted URLs, cache policy), ``filters.py`` (Jinja
filters), ``rendering.py`` (the environment, ``render``, ``with_toast``).
Route modules import from those: full-page handlers live in
``routes/pages.py``, fragment handlers in ``routes/partials/``.
"""

import importlib.util

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

CHANGES = "app.components.web_frontend.routes.partials.changes"
OVERSEER_CHAT = "app.components.web_frontend.routes.partials.overseer_ai_chat"


def create_web_frontend_app() -> APIRouter:
    """Create the web frontend router with page and partial routes.

    None of them belong in the API's OpenAPI schema. Each is tagged
    ``overseer`` or ``web``, so route lists group them apart from the API.
    """
    router = APIRouter()

    from app.components.web_frontend.routes.pages import router as pages_router

    router.include_router(pages_router, include_in_schema=False)
    # The change queue's approval cards (the signed-in user's, not the
    # Overseer's alone), on the stacks that ship the queue.
    if importlib.util.find_spec(CHANGES) is not None:
        changes = importlib.import_module(CHANGES)
        router.include_router(changes.router, include_in_schema=False)
    # The Overseer chat's live call: a socket, outside the pages' gate,
    # behind its own (routes/partials/overseer_ai_chat.py).
    if importlib.util.find_spec(OVERSEER_CHAT) is not None:
        sockets = importlib.import_module(OVERSEER_CHAT).sockets
        if sockets is not None:
            router.include_router(sockets)
    for route in router.routes:
        if isinstance(route, APIRoute):
            route.tags = ["overseer" if "/overseer" in route.path else "web"]

    return router


def add_error_pages(app: FastAPI) -> None:
    """The pages an exception renders instead of JSON: the Overseer's
    "admins only" refusal. The Overseer ships with auth; without it there
    is nothing to refuse."""
    try:
        from app.components.web_frontend.overseer_access import (
            AdminOnlyError,
            admin_only_page,
        )
    except ImportError:  # no auth service, so no Overseer
        return
    app.add_exception_handler(AdminOnlyError, admin_only_page)
