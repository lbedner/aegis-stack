"""A route's request form, read from its OpenAPI operation (``request_form``).

Routes shows it under each route to send one request (Execute) and see
what came back, as FastAPI's ``/docs`` does. Load Tests shows the same form
with requests and clients added (``overseer_server_load_tests``), so the
two pages cannot drift. Execute's requests are not load-test runs and stay
out of their history. Beside Execute, the route's dry path (``dry_path``):
every hop it can take, read from the code, each opening at its line, and
the parts it crosses lit on the map; shown only where the code is.
"""

from collections.abc import Sequence
import json
from typing import Any

from fastapi import FastAPI
from markupsafe import Markup
from starlette.routing import BaseRoute

from app.core.constants import ComponentName
from app.core.ownership import HOST
from app.services.load_test.api import auth, request_form
from app.services.load_test.api.request_form import Answer, Operation
from app.services.system import dry_path

from . import overseer_code
from .overseer_container import zoom_url
from .overseer_nav import page_url
from .overseer_zoom import registry_of
from .rendering import hx_into, hx_replace, with_query

PARTIALS = "/partials/overseer/server/routes"
FORM = "pages/overseer/server/_request_form.html"
ANSWER = "pages/overseer/server/_request_answer.html"
DRY = "pages/overseer/server/_dry_path.html"
INDENT = 8  # the deepest a hop is set in; deeper ones line up with it
LOAD_TESTS_URL = page_url("components", ComponentName.BACKEND) + "/load-tests"
TRY, LOAD = "try", "load"


def find(routes: Sequence[BaseRoute], key: str) -> Operation | None:
    """The operation behind a ``"<METHOD> <path>"`` key, or None."""
    method, _, path = key.partition(" ")
    return request_form.operation(routes, method, path)


def form_context(op: Operation, mode: str, values: dict[str, str]) -> dict[str, Any]:
    """The form for ``op``, filled from ``values`` (a form sent back, or a
    page's query), else from each field's default and the body's example."""
    example = "" if op.body_example is None else json.dumps(op.body_example, indent=2)
    key = f"{op.method} {op.path}"
    dry = with_query(f"{PARTIALS}/dry", route=key)
    return {
        "op": op,
        "key": key,
        "mode": mode,
        "fields": [_field(p, values) for p in op.params],
        "body": values.get(request_form.BODY) or example,
        "role": values.get("role") or auth.default_role(),
        "roles": [{"id": r, "name": r.capitalize()} for r in auth.roles()],
        "partials": PARTIALS,
        # Beside Execute: the route walked without sending it, where the
        # code is shown (``dry_context``).
        "dry_path": hx_into(dry, "next [data-answer]", "data-dry-path-button")
        if overseer_code.enabled()
        else None,
        # "Load test this": Load Tests, with this form's values in its query.
        "load_test_this": hx_replace(LOAD_TESTS_URL, "#overseer-main")
        + Markup(' hx-include="closest form"'),
    }


def _field(param: request_form.Param, values: dict[str, str]) -> dict[str, Any]:
    given = values.get(param.field)
    value = (
        given if given is not None else ("" if param.default is None else param.default)
    )
    return {
        "param": param,
        "value": str(value),
        "options": [{"id": str(c), "name": str(c)} for c in param.choices],
    }


async def execute(form: dict[str, str], app: FastAPI) -> tuple[Answer | None, str]:
    """Send the form's request once: what came back, or None and why not."""
    op = find(app.routes, form.get("route", ""))
    if op is None:
        return None, "Pick one of this app's routes."
    try:
        request = request_form.build(op, form)
        headers = await auth.bearer_header(form.get("role") or auth.default_role())
    except ValueError as exc:
        return None, str(exc)
    return await request_form.execute(request, app, headers), ""


def dry_context(routes: Sequence[BaseRoute], key: str) -> dict[str, Any] | None:
    """The dry path of the route behind ``key``, each hop set in under the
    one that makes it; None for no such route, or while the code is hidden."""
    route = dry_path.find(routes, key)
    if route is None:
        return None
    try:
        found = dry_path.walk(route)
    except ValueError:
        return None  # the source hidden, or a handler made at runtime
    depth: dict[int, int] = {}
    for hop in found.hops:
        depth[hop.id] = depth[hop.parent] + 1 if hop.parent else 0
    lit = ",".join(sorted({registry_of(h.node) for h in found.hops if h.node}))
    return {
        "rows": [{"hop": h, "depth": min(depth[h.id], INDENT)} for h in found.hops],
        "stops": found.stops,
        "reasons": dry_path.REASONS,
        "unseen": dry_path.UNSEEN,
        "map_url": zoom_url(HOST, lit),
    }
