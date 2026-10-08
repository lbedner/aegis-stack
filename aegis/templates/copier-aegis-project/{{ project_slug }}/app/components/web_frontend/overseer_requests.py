"""A route's request form, read from its OpenAPI operation (``request_form``).

Routes shows it under each route to send one request (Execute) and see
what came back, as FastAPI's ``/docs`` does. Load Tests shows the same form
with requests and clients added (``overseer_server_load_tests``), so the
two pages cannot drift. Execute's requests are not load-test runs and stay
out of their history.
"""

from collections.abc import Sequence
import json
from typing import Any

from fastapi import FastAPI
from markupsafe import Markup
from starlette.routing import BaseRoute

from app.core.constants import ComponentName
from app.services.load_test.api import auth, request_form
from app.services.load_test.api.request_form import Answer, Operation

from .overseer_nav import page_url
from .rendering import hx_replace

PARTIALS = "/partials/overseer/server/routes"
FORM = "pages/overseer/server/_request_form.html"
ANSWER = "pages/overseer/server/_request_answer.html"
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
    return {
        "op": op,
        "key": f"{op.method} {op.path}",
        "mode": mode,
        "fields": [_field(p, values) for p in op.params],
        "body": values.get(request_form.BODY) or example,
        "role": values.get("role") or auth.default_role(),
        "roles": [{"id": r, "name": r.capitalize()} for r in auth.roles()],
        "partials": PARTIALS,
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
