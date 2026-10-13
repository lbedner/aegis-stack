"""Calls out over HTTP as hops (``edges``): httpx, and ``requests`` where
installed, each to the part or the provider its host is. Installed once a
process, where each starts (``boot.apply_saved_overrides``): one patch of
the transports, whatever client is built on them.

A call to a model provider the AI service declares, made with no AI code
on the stack, is a bypass of its gateway (``bypass``), whatever else
declares the call."""

from collections.abc import Callable
from functools import cache
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core import edges
from app.core.parts import PARTS

AI = "service:ai"
# A compose service's host as the component it runs (``postgres``: database).
HOSTS = {
    host: f"component:{name}"
    for name, part in PARTS.items()
    for host in (name, *part.containers)
}


@cache
def _providers() -> dict[str, tuple[str, bool]]:
    """Each outside provider a service declares a key for, by the word its
    hosts carry (``stripe``: ``api.stripe.com``), and whether it is the AI
    service's (a model provider). ponytail: a name its hosts do not carry
    is ``external:<host>``; give ``Secret`` a host if one matters."""
    from app.core import secrets
    from app.core.ontology import calls

    declared = secrets.declared()
    models = {p for p, _ in calls.providers(declared, "ai", needed=False)}
    return {
        re.sub(r"\W", "", p.lower()): (p, p in models)
        for p, _ in calls.providers(declared, needed=False)
    }


def target(host: str) -> tuple[str, bool]:
    """``host`` as a node, and whether it is a model provider's."""
    if part := HOSTS.get(host):
        return part, False
    labels = set(host.lower().split("."))
    for word, (provider, model) in _providers().items():
        if word in labels:
            return f"external:{provider}", model
    return edges.outside(host), False


def _called(host: str, started: float, response: Any) -> None:
    node, model = target(host)
    chain = edges.callers()
    edges.hop(
        node,
        via=chain,
        ms=(time.perf_counter() - started) * 1000,
        error=response is None or getattr(response, "status_code", 200) >= 500,
        bypass=model and all(edges.part_of(c) != AI for c in chain),
    )


def _timed(send: Callable[..., Any], host: Callable[[Any], str]) -> Callable[..., Any]:
    def sent(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        started, response = time.perf_counter(), None
        try:
            response = send(self, request, *args, **kwargs)
            return response
        finally:
            _called(host(request), started, response)

    return sent


def _timed_async(
    send: Callable[..., Any], host: Callable[[Any], str]
) -> Callable[..., Any]:
    async def sent(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        started, response = time.perf_counter(), None
        try:
            response = await send(self, request, *args, **kwargs)
            return response
        finally:
            _called(host(request), started, response)

    return sent


def install() -> None:
    """Patch httpx's transports (and ``requests``' adapter) once a process."""
    if getattr(httpx.HTTPTransport, "_edges", False):
        return
    host = lambda request: request.url.host  # noqa: E731
    httpx.HTTPTransport.handle_request = _timed(  # type: ignore[method-assign]
        httpx.HTTPTransport.handle_request, host
    )
    httpx.AsyncHTTPTransport.handle_async_request = _timed_async(  # type: ignore[method-assign]
        httpx.AsyncHTTPTransport.handle_async_request, host
    )
    httpx.HTTPTransport._edges = True  # type: ignore[attr-defined]
    try:
        from requests.adapters import HTTPAdapter
    except ImportError:
        return
    HTTPAdapter.send = _timed(  # type: ignore[method-assign]
        HTTPAdapter.send, lambda request: urlsplit(request.url).hostname or ""
    )
