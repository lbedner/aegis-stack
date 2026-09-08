"""The Jinja2 environment and the two ways a page is rendered.

Route modules import ``templates``, ``render`` and ``with_toast`` from
here. ``render`` is the one-route-two-paths rule: the same handler serves
a full page inside the page layout and a bare fragment for htmx.
"""

import json
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.components.web_frontend.assets import COMPONENT_DIR, static_url
from app.components.web_frontend.filters import FILTERS
from app.core.config import settings

templates = Jinja2Templates(directory=str(COMPONENT_DIR / "templates"))

templates.env.globals["static"] = static_url
# Every page's <title> and navbar name the project, so these are globals
# rather than something each route has to remember to pass through.
templates.env.globals["project_name"] = settings.PROJECT_DISPLAY_NAME
templates.env.globals["project_description"] = settings.PROJECT_DESCRIPTION
# Whether the auth service is wired up. Templates gate sign-in affordances
# on this at render time. AUTH_ENABLED is False when the service was not
# selected.
templates.env.globals["auth_enabled"] = settings.AUTH_ENABLED
templates.env.globals["registration_enabled"] = settings.REGISTRATION_ENABLED
templates.env.filters.update(FILTERS)


PAGE_LAYOUT = "layouts/page.html"
FRAGMENT_LAYOUT = "layouts/fragment.html"


def wants_fragment(request: Request) -> bool:
    """True when htmx will swap the response into ``#app-content``.

    A boosted request (``hx-boost``) replaces the whole body, so it still
    needs the shell; history restores never reach here because the htmx
    config turns them into full page loads.
    """
    headers = request.headers
    return headers.get("HX-Request") == "true" and headers.get("HX-Boosted") != "true"


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> Response:
    """Render page template ``name`` for either render path.

    The template ends with ``{% extends layout %}``; ``layout`` is set here
    to the page layout on a full load and to the bare fragment when htmx asks,
    so a view has one URL and one template. ``Vary`` tells caches the two
    bodies differ. ``status_code`` is for validation re-renders (422).
    """
    layout = FRAGMENT_LAYOUT if wants_fragment(request) else PAGE_LAYOUT
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context={
            **(context or {}),
            "layout": layout,
            # Lets navigation mark the current page on full loads.
            "current_path": request.url.path,
        },
        status_code=status_code,
    )
    response.headers["Vary"] = "HX-Request"
    return response


def with_toast(response: Response, text: str, tone: str = "ok") -> Response:
    """Attach a toast to any response (pattern 6).

    Written into ``HX-Trigger`` so htmx raises a ``toast`` event that the
    region in base.html shows. Merges with triggers already on the
    response; a bare event-name header is kept as an event with no detail.
    """
    existing = response.headers.get("HX-Trigger")
    triggers: dict[str, Any] = {}
    if existing:
        try:
            triggers = json.loads(existing)
        except json.JSONDecodeError:
            triggers = {name.strip(): None for name in existing.split(",")}
    triggers["toast"] = {"text": text, "tone": tone}
    response.headers["HX-Trigger"] = json.dumps(triggers)
    return response
