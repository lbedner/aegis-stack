"""A flow on the map, drawn under an answer and played as Overseer's
replay plays it (the ``path`` card kind).

She names its source, never its layout: a kept request (``request_id``,
as ``requests`` lists them: its replay), a route (``route``: its code
path, every hop its code can take, read without running it) or a flow's
stops (``stops``, model node ids, joined along the lines the running
model declares). Every hop is the app's own, run, read or declared; none
is guessed. The server stages it once, when it is drawn (``prepare``),
into the hops a replay plays (``RequestHops``), so the card plays after
the request is no longer kept. A request's path is the app's code and
traffic: an admin's to draw."""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from app.core.ontology.observed import running
from app.services.shared.deps import caller_is_admin
from app.services.system import kept_requests, staged_paths
from app.services.system.kept_requests import RequestHops

SOURCES = ("request_id", "route", "stops")


class PathAsk(BaseModel):
    """What she asks for: a title and exactly one source."""

    title: str
    request_id: str | None = None  # a kept request's ``id``
    route: str | None = None  # "GET /api/v1/...": its code path
    stops: list[str] | None = None  # node ids in order, at least two

    @model_validator(mode="after")
    def _one_source(self) -> PathAsk:
        given = [n for n in SOURCES if getattr(self, n) is not None]
        if len(given) != 1:
            raise ValueError(
                "name one of request_id (a kept request: its replay), route "
                "('METHOD /path': its code path, drawn for you) or stops (two "
                "or more node ids such as service:auth, for a flow no request "
                f"or route shows); got {', '.join(given) or 'none'}"
            )
        if self.stops is not None and len(self.stops) < 2:
            raise ValueError("stops: a flow goes from one part to another; name two")
        return self


class PathCard(BaseModel):
    """What is kept: the path as hops (a request's as it ran, or staged)."""

    title: str
    path: RequestHops


async def prepare(ask: PathAsk) -> PathCard:
    """``ask`` staged as the hops a replay plays; ValueError saying what to
    fix when it cannot be."""
    if not await caller_is_admin():
        raise ValueError("A request's path is the app's code: an admin's to draw.")
    if ask.request_id is not None:
        found = await kept_requests.find(ask.request_id)
        if found is None:
            raise ValueError(
                f"Request {ask.request_id!r} is no longer kept; "
                "the requests tool lists the ones that are."
            )
        return PathCard(title=ask.title, path=found)
    if ask.route is not None:
        staged = await staged_paths.route(ask.route)
    else:
        staged = staged_paths.joined(await running(), ask.stops or [])
    return PathCard(title=ask.title, path=staged)
