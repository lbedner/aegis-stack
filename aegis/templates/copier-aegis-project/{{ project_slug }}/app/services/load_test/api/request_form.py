"""A route's request, read from its OpenAPI operation: the fields a form
shows, and the request a filled-in form makes.

The schema is the one ``/openapi.json`` and ``/docs`` serve
(``get_openapi`` over the app's routes), so Overseer's Routes, its load
tests and Swagger cannot disagree about what a route takes. Routes sends a
request once (``execute``); a load test sends it many times.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import shlex
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
import httpx
from starlette.routing import BaseRoute

WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Form field names: ``path.<name>`` and ``query.<name>`` for parameters,
# ``body`` for the JSON body, ``confirm`` to send a write.
PATH, QUERY, BODY, CONFIRM = "path.", "query.", "body", "confirm"
_EXAMPLE_DEPTH = 6
_BODY_SHOWN = 20_000  # characters of a response body shown


@dataclass(frozen=True)
class Param:
    """One path or query parameter, as a form field."""

    name: str
    location: str  # "path" or "query"
    required: bool
    kind: str  # the JSON schema type: string, integer, number, boolean
    default: Any = None
    choices: list[Any] = field(default_factory=list)
    description: str = ""

    @property
    def field(self) -> str:
        return f"{self.location}.{self.name}"


@dataclass(frozen=True)
class Operation:
    """What a route takes and gives, for its form and its docs."""

    method: str
    path: str
    summary: str
    description: str
    params: list[Param]
    body_example: Any
    body_required: bool
    responses: list[tuple[str, str]]  # (status code, description)

    @property
    def writes(self) -> bool:
        return self.method in WRITES


@dataclass(frozen=True)
class Request:
    """A filled-in form: the request it makes."""

    method: str
    path: str  # the route's path, ``{name}`` placeholders and all
    path_params: dict[str, str]
    query: dict[str, str]
    payload: Any

    @property
    def url(self) -> str:
        """The path with its parameters in, and the query after it."""
        path = self.path
        for name, value in self.path_params.items():
            path = path.replace("{" + name + "}", value)
        return f"{path}?{urlencode(self.query)}" if self.query else path

    @property
    def load_test_path(self) -> str:
        """The path a load test sends: placeholders kept (it fills them in
        from ``path_params``), the query after it."""
        return f"{self.path}?{urlencode(self.query)}" if self.query else self.path


@dataclass(frozen=True)
class Answer:
    """What one request came back with."""

    status: int
    headers: list[tuple[str, str]]
    body: str
    ms: float
    curl: str
    json: bool = False  # the body is JSON, shown highlighted


def documented(routes: Sequence[BaseRoute]) -> set[str]:
    """Every ``"<METHOD> <path>"`` the schema describes: what has a form."""
    paths = get_openapi(title="", version="", routes=list(routes)).get("paths", {})
    return {f"{m.upper()} {path}" for path, ops in paths.items() for m in ops}


def operation(routes: Sequence[BaseRoute], method: str, path: str) -> Operation | None:
    """The route's operation, or None if the app has no such route."""
    spec = get_openapi(title="", version="", routes=list(routes))
    op = (spec.get("paths", {}).get(path) or {}).get(method.lower())
    if op is None:
        return None
    schemas = spec.get("components", {}).get("schemas", {})
    body = op.get("requestBody") or {}
    body_schema = (body.get("content", {}).get("application/json") or {}).get("schema")
    return Operation(
        method=method.upper(),
        path=path,
        summary=op.get("summary", ""),
        description=op.get("description", ""),
        params=[
            _param(p, schemas)
            for p in op.get("parameters", [])
            if p.get("in") in ("path", "query")
        ],
        body_example=example(body_schema, schemas) if body_schema else None,
        body_required=bool(body.get("required")),
        responses=[
            (code, r.get("description", ""))
            for code, r in op.get("responses", {}).items()
        ],
    )


def _param(raw: dict[str, Any], schemas: dict[str, Any]) -> Param:
    schema = _plain(raw.get("schema", {}), schemas)
    return Param(
        name=raw["name"],
        location=raw["in"],
        required=bool(raw.get("required")),
        kind=schema.get("type", "string"),
        default=schema.get("default"),
        choices=list(schema.get("enum", [])),
        description=raw.get("description", "") or schema.get("description", ""),
    )


def _plain(schema: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with a ``$ref`` followed and an optional's ``null`` dropped,
    its own default kept."""
    default = schema.get("default")
    if "$ref" in schema:
        schema = schemas.get(schema["$ref"].rsplit("/", 1)[-1], {})
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        found = [o for o in options if o.get("type") != "null"]
        schema = _plain(found[0], schemas) if found else {}
    return schema | ({"default": default} if default is not None else {})


def example(schema: dict[str, Any], schemas: dict[str, Any], depth: int = 0) -> Any:
    """A value ``schema`` accepts, from its example or default, else its type."""
    schema = _plain(schema, schemas)
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if schema.get("examples"):
        return schema["examples"][0]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        if depth >= _EXAMPLE_DEPTH:
            return {}
        return {
            name: example(sub, schemas, depth + 1)
            for name, sub in schema.get("properties", {}).items()
        }
    if kind == "array":
        return [example(schema.get("items", {}), schemas, depth + 1)]
    return {"integer": 0, "number": 0.0, "boolean": False, "null": None}.get(
        str(kind), "string"
    )


def build(op: Operation, form: dict[str, str]) -> Request:
    """The request a filled-in form makes; ``ValueError`` says what is wrong."""
    if op.writes and not form.get(CONFIRM):
        raise ValueError(f"{op.method} changes data: tick the box to send it.")
    path_params: dict[str, str] = {}
    query: dict[str, str] = {}
    for param in op.params:
        value = (form.get(param.field) or "").strip()
        if not value:
            if param.required:
                raise ValueError(f"The request needs {param.name}.")
            continue
        _check(param, value)
        (path_params if param.location == "path" else query)[param.name] = value
    return Request(op.method, op.path, path_params, query, _payload(op, form))


def _check(param: Param, value: str) -> None:
    kinds = {"integer": (int, "a whole number"), "number": (float, "a number")}
    if param.kind not in kinds:
        return
    parse, noun = kinds[param.kind]
    try:
        parse(value)
    except ValueError:
        raise ValueError(f"{param.name} must be {noun}.") from None


def _payload(op: Operation, form: dict[str, str]) -> Any:
    text = (form.get(BODY) or "").strip()
    if not text:
        if op.body_required:
            raise ValueError("The request needs a body.")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("The body is not JSON.") from None


async def execute(request: Request, app: FastAPI, headers: dict[str, str]) -> Answer:
    """Send ``request`` once to ``app``, in this process, and show the answer."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        started = time.perf_counter()
        response = await client.request(
            request.method,
            request.url,
            headers=headers,
            json=request.payload if request.payload is not None else None,
        )
        ms = (time.perf_counter() - started) * 1000
    return Answer(
        status=response.status_code,
        headers=list(response.headers.items()),
        body=_shown(response),
        ms=round(ms, 1),
        curl=curl(request, headers),
        json="json" in response.headers.get("content-type", ""),
    )


def _shown(response: httpx.Response) -> str:
    try:
        text = json.dumps(response.json(), indent=2)
    except ValueError:
        text = response.text
    return text if len(text) <= _BODY_SHOWN else text[:_BODY_SHOWN] + "\n..."


def curl(
    request: Request, headers: dict[str, str], base: str = "http://localhost:8000"
) -> str:
    """The same request as a curl command."""
    parts = ["curl", "-X", request.method, shlex.quote(base + request.url)]
    for name, value in headers.items():
        parts += ["-H", shlex.quote(f"{name}: {value}")]
    if request.payload is not None:
        parts += ["-H", shlex.quote("Content-Type: application/json")]
        parts += ["-d", shlex.quote(json.dumps(request.payload))]
    return " ".join(parts)
