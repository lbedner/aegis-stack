"""The Jinja2 environment and the two ways a page is rendered.

Route modules import ``templates``, ``render`` and ``with_toast`` from
here. ``render`` is the one-route-two-paths rule: the same handler serves
a full page inside the page layout and a bare fragment for htmx.
"""

from base64 import b64decode
from hashlib import sha1
import json
from typing import Any
from urllib.parse import urlencode

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
templates.env.globals["email_flows_enabled"] = (
    settings.AUTH_ENABLED and settings.AUTH_LEVEL != "basic"
)
templates.env.filters.update(FILTERS)


def hx_dialog(url: str, extra: str = "") -> Markup:
    """The attributes for "open this in the one modal" (pattern 4), so no
    template has to remember which element the dialog swaps into.
    ``extra`` rides along for the openers that carry more (an
    ``hx-include`` of the checked rows, a role for a clickable cell).

    The swap is stated, not left to default. htmx INHERITS ``hx-swap``
    from ancestors, so an opener that sits inside a form swapping ITSELF
    ``outerHTML`` borrows that and REPLACES ``#dialog-body`` with the
    dialog's content - the element is gone, and every later open fails
    with ``htmx:targetError`` until the page is reloaded. Found live on
    a row-form's opener ("I can't open a new one until I refresh").
    Saying ``innerHTML`` here costs nothing and cannot be borrowed
    against, and it fixes every opener at once."""
    return _hx_open(url, "#dialog-body", extra)


def hx_drawer(url: str) -> Markup:
    """The attributes for "open this in the side drawer": the panel an item
    is edited in beside the page, without the address bar naming it (the
    list-driven ``drawer_sync`` does that). Same stated swap as
    ``hx_dialog``, for the same reason."""
    return _hx_open(url, "#drawer-body")


def _hx_open(url: str, target: str, extra: str = "") -> Markup:
    return Markup(
        f'hx-get="{escape(url)}" hx-target="{target}" hx-swap="innerHTML" {extra}'
    )


def hx_dialog_post(url: str) -> Markup:
    """The attributes for a dialog's own form: post to ``url`` and swap
    the answer back into the dialog, which is how a 422 re-renders the
    form with its errors (pattern 1 inside pattern 4). States its swap
    for the same reason ``hx_dialog`` does."""
    return Markup(
        f'hx-post="{escape(url)}" hx-target="#dialog-body" hx-swap="innerHTML"'
    )


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


def image_response(
    request: Request, icon_b64: str, media_type: str = "image/png"
) -> Response:
    """A stored base64 image served for the browser to cache: a day's
    ``max-age`` and an ETag of its bytes, so a revalidation is a 304 and a
    changed image is fetched fresh. For icon routes (``<img src=...>``)."""
    etag = '"' + sha1(icon_b64.encode(), usedforsecurity=False).hexdigest()[:16] + '"'
    headers = {"Cache-Control": "public, max-age=86400", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(b64decode(icon_b64), media_type=media_type, headers=headers)


async def form_fields(request: Request) -> dict[str, str]:
    """A form post's fields as text, for an editor with more fields than a
    handler's signature should spell out."""
    return {key: str(value) for key, value in (await request.form()).items()}


def form_number(raw: str | None, label: str, kind: type = int) -> Any:
    """An optional number from a form field: blank is None, anything else
    must parse as ``kind`` (``int`` or ``float``) or it is a ``ValueError``
    naming the field, which a handler turns into its error toast."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return kind(text)
    except ValueError:
        noun = "a whole number" if kind is int else "a number"
        raise ValueError(f"{label} must be {noun}.") from None


def status_cell(label: str, tone: str) -> dict[str, str]:
    """A ``data_table`` status cell (rendered as a ``badge``); ``tone`` is ok,
    warn, error, muted or accent."""
    return {"label": label, "tone": tone}


def ranked(rows: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
    """Rows for the ``ranked_rows`` macro: each gains the ``ratio`` of its
    ``by`` figure to the largest row's, the width of its bar."""
    top = max((row[by] for row in rows), default=0)
    return [row | {"ratio": row[by] / top if top else 0} for row in rows]


def chart(
    labels: list[str], label: str, values: list[float], money: bool = False
) -> dict[str, Any]:
    """Data for the ``chart_panel`` macro: one labelled series, drawn as
    dollars when ``money``."""
    data: dict[str, Any] = {
        "labels": labels,
        "series": [{"label": label, "values": values}],
    }
    return data | {"format": "money"} if money else data


def drawer_state(param: str, url: str | None) -> dict[str, str | None]:
    """What a list hands ``drawer_sync``: the open item's drawer URL (None
    closes it) and the query parameter that holds the item."""
    return {"open_drawer": url, "drawer_param": param}


def with_query(path: str, **params: str | list[str] | None) -> str:
    """``path`` with the given query parameters, leaving out empty ones; a
    list (a multi-select's picks) repeats its key once per value."""
    pairs = [
        (key, value)
        for key, given in params.items()
        for value in (given if isinstance(given, list) else [given])
        if value
    ]
    query = urlencode(pairs)
    return f"{path}?{query}" if query else path


def page_number(raw: str | None) -> int:
    """A ``?page=`` value as a page number, 1 when missing or not a number."""
    try:
        return max(1, int(raw or 1))
    except ValueError:
        return 1


def pager(
    path: str, page: int, page_size: int, total: int, **params: str
) -> dict[str, Any] | None:
    """The ``pager`` macro's ``{start, end, total, prev, next}`` for ``page``
    (1-based) of ``total`` items, or None when everything fits on one page.
    ``params`` ride along on the previous/next links (filters, say)."""
    if total <= page_size:
        return None

    def link(number: int) -> str:
        return f"{path}?{urlencode({**params, 'page': number})}"

    start = (page - 1) * page_size
    return {
        "start": start + 1 if total else 0,
        "end": min(start + page_size, total),
        "total": total,
        "prev": link(page - 1) if page > 1 else None,
        "next": link(page + 1) if start + page_size < total else None,
    }


templates.env.globals["hx_replace"] = hx_replace
templates.env.globals["hx_dialog"] = hx_dialog
templates.env.globals["hx_drawer"] = hx_drawer
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


def fragment(name: str, **context: Any) -> str:
    """Template ``name`` rendered on its own: an SSE frame or a swapped
    part, not a page."""
    return templates.env.get_template(name).render(**context)


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    page_layout: str = PAGE_LAYOUT,
) -> Response:
    """Render page template ``name`` for either render path.

    The template ends with ``{% extends layout %}``; ``layout`` is set here
    to the page layout on a full load and to the bare fragment when htmx asks,
    so a view has one URL and one template. ``Vary`` tells caches the two
    bodies differ. ``status_code`` is for validation re-renders (422).
    """
    layout = FRAGMENT_LAYOUT if wants_fragment(request) else page_layout
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


def toast_response(text: str, tone: str = "ok") -> Response:
    """An action's whole answer when the page stays as it is: a toast.
    An error toast leaves a form holding what was typed."""
    return with_toast(Response(status_code=200), text, tone)


def close_dialog(response: Response) -> Response:
    """Close the one modal from a successful in-dialog action (pattern 4).

    After settle, not before the swap: a plain ``HX-Trigger`` fires first,
    and the swap into ``#dialog-body`` that follows (rows out of band leave
    nothing in it) would re-open the dialog, empty.
    """
    return trigger(response, "dialog:close", header="HX-Trigger-After-Settle")


def navigate(
    response: Response,
    path: str,
    target: str = "#app-content",
    select: str | None = None,
) -> Response:
    """Send the browser to ``path`` the htmx way: a GET with HX-Request
    swapped into ``target`` and pushed to the URL bar (``HX-Location``).
    The usual close of a dialog form that made something new. ``select``
    takes that element out of the answer and swaps it for ``target``
    whole, for a page that answers with more than the target holds.

    Closes the dialog with the plain trigger: htmx follows HX-Location
    instead of swapping this response, so nothing after-settle would ever
    fire, and nothing swaps into the dialog that could re-open it.
    """
    location = {"path": path, "target": target}
    if select:
        location |= {"select": select, "swap": "outerHTML"}
    response.headers["HX-Location"] = json.dumps(location)
    return trigger(response, "dialog:close")


def go_to(path: str, toast: str, target: str) -> Response:
    """Replace ``target`` with the same element from ``path`` and say what
    happened: the ``hx_replace`` recipe, for a region inside a page (the
    Overseer's main area). Swapping the whole answer in would nest the
    page's shell, sidebar and all, inside the target."""
    response = Response(status_code=200)
    navigate(response, path, target=target, select=target)
    return with_toast(response, toast)


def dialog_done(path: str, toast: str, tone: str = "ok") -> Response:
    """The end of a dialog form that made something: close it, say what
    happened, and send the content area where the result lives."""
    response = Response(status_code=200)
    navigate(response, path)
    return close_dialog(with_toast(response, toast, tone))
