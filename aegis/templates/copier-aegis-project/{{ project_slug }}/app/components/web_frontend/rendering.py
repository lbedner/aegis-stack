"""The Jinja2 environment and the two ways a page is rendered.

Route modules import ``templates``, ``render`` and ``with_toast`` from
here. ``render`` is the one-route-two-paths rule: the same handler serves
a full page inside the page layout and a bare fragment for htmx.
"""

import json
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
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


def hx_dialog(url: str, extra: str = "") -> Markup:
    """The attributes for "open this in the one modal" (pattern 4), so no
    template has to remember which element the dialog swaps into.
    ``extra`` rides along for the openers that carry more (an
    ``hx-include`` of the checked rows, a role for a clickable cell)."""
    return Markup(f'hx-get="{escape(url)}" hx-target="#dialog-body" {extra}')


def hx_dialog_post(url: str) -> Markup:
    """The attributes for a dialog's own form: post to ``url`` and swap
    the answer back into the dialog, which is how a 422 re-renders the
    form with its errors (pattern 1 inside pattern 4)."""
    return Markup(f'hx-post="{escape(url)}" hx-target="#dialog-body"')


def hx_replace(url: str, target: str, oob: str | None = None) -> Markup:
    """The attributes for "re-request ``url`` and replace ``target`` with
    the same element from the response": filter forms, pagers, list links.

    Selecting the element you target needs an outerHTML swap, or every
    request nests a copy inside the last one; keeping the recipe here
    means no template has to remember that. ``oob`` names a second
    element to re-take out of band (``hx-select-oob``).
    """
    attrs = {
        "hx-get": url,
        "hx-target": target,
        "hx-select": target,
        "hx-swap": "outerHTML",
        "hx-push-url": "true",
    }
    if oob:
        attrs["hx-select-oob"] = oob
    return Markup(" ".join(f'{k}="{escape(v)}"' for k, v in attrs.items()))


templates.env.globals["hx_replace"] = hx_replace
templates.env.globals["hx_dialog"] = hx_dialog
templates.env.globals["hx_dialog_post"] = hx_dialog_post


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


def dialog(
    request: Request, template: str, /, status_code: int = 200, **context: Any
) -> Response:
    """A dialog's body (pattern 4): a bare fragment, never a layout. The
    partial is swapped into ``#dialog-body``, which opens the modal; a
    422 re-renders the same partial with its errors.

    The first two arguments are positional so a form's own context can
    carry any key it likes, ``name`` and ``template`` included.
    """
    return templates.TemplateResponse(
        request=request, name=template, context=context, status_code=status_code
    )


def trigger(
    response: Response, event: str, detail: Any = None, header: str = "HX-Trigger"
) -> Response:
    """Add an htmx client event to ``response`` via ``HX-Trigger`` (or the
    after-swap/after-settle variants named by ``header``).

    Merges with triggers already on the response; a bare event-name header
    is kept as an event with no detail. The toast region, the dialog and
    any page hook listen for these by name.
    """
    existing = response.headers.get(header)
    triggers: dict[str, Any] = {}
    if existing:
        try:
            triggers = json.loads(existing)
        except json.JSONDecodeError:
            triggers = {name.strip(): None for name in existing.split(",")}
    triggers[event] = detail
    response.headers[header] = json.dumps(triggers)
    return response


def with_toast(response: Response, text: str, tone: str = "ok") -> Response:
    """Attach a toast to any response (pattern 6): a ``toast`` event the
    region in base.html shows."""
    return trigger(response, "toast", {"text": text, "tone": tone})


def close_dialog(response: Response) -> Response:
    """Close the one modal from a successful in-dialog action (pattern 4).

    After settle, not before the swap: a plain ``HX-Trigger`` fires first,
    and the swap into ``#dialog-body`` that follows (rows out of band leave
    nothing in it) would re-open the dialog, empty.
    """
    return trigger(response, "dialog:close", header="HX-Trigger-After-Settle")


def navigate(response: Response, path: str, target: str = "#app-content") -> Response:
    """Send the browser to ``path`` the htmx way: a GET with HX-Request
    swapped into ``target`` and pushed to the URL bar (``HX-Location``).
    The usual close of a dialog form that made something new.

    Closes the dialog with the plain trigger: htmx follows HX-Location
    instead of swapping this response, so nothing after-settle would ever
    fire, and nothing swaps into the dialog that could re-open it.
    """
    response.headers["HX-Location"] = json.dumps({"path": path, "target": target})
    return trigger(response, "dialog:close")


def dialog_done(path: str, toast: str) -> Response:
    """The end of a dialog form that made something: close it, say what
    happened, and send the content area where the result lives."""
    response = Response(status_code=200)
    navigate(response, path)
    return close_dialog(with_toast(response, toast))
