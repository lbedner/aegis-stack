"""The requests the server kept (``app.core.replays``) as one typed read,
for every reader: the API (``/api/v1/requests``), Illiana's ``requests``
tool and Overseer's replay, so all three say a request the same way.

A hop names what it went through as the dry path does (``dry_path``): a
part by its model node, a sub-part only where the model has one; and each
line of code it was made through by the service it is in and the piece of
that service (``service_pieces``): Auth's Queries, its Users domain. The
store is the shared cache's last ``replays.KEEP`` (Redis where the stack
has it, so they outlive a restart)."""

import asyncio
from dataclasses import asdict
from itertools import groupby, islice

from pydantic import BaseModel

from app.core import replays
from app.core.edges import part_of
from app.core.ontology import Kind, current
from app.core.ontology.model import parse_node_id
from app.services.system import service_pieces
from app.services.system.node_now import FIGURES


class _Read(BaseModel):
    model_config = FIGURES


class Piece(_Read):
    """A piece of a service, as its map draws it: ``piece:queries`` of
    ``service:auth``."""

    key: str
    title: str
    service: str


class CodeLine(_Read):
    """A line of the app's code a hop was made through, and the piece of a
    service it is in (none for code no service holds)."""

    path: str
    line: int
    piece: Piece | None


class RequestHop(_Read):
    """One hop: the parts it went through, ending where it went, its real
    start (from the request's) and length, the tables a query touched and
    the lines it was made through, outermost first."""

    chain: tuple[str, ...]
    at_ms: float
    ms: float
    error: bool
    tables: tuple[str, ...]
    lines: tuple[CodeLine, ...]

    @property
    def where(self) -> str | None:
        """The line that made it (the innermost), as ``path:line``."""
        return f"{self.lines[-1].path}:{self.lines[-1].line}" if self.lines else None

    def pieces(self, service: str) -> list[Piece]:
        """The pieces of ``service`` its lines went through, outermost first."""
        return [p for line in self.lines if (p := line.piece) and p.service == service]


class RequestSummary(_Read):
    """A request kept: how it was answered, how long it took, its hops
    (``dropped``: past what one request keeps)."""

    id: str
    method: str
    path: str
    route: str
    status: int
    ms: float
    hop_count: int
    dropped: int


class RequestHops(RequestSummary):
    """A request with its hops, in the order they started."""

    hops: tuple[RequestHop, ...]


async def recent(
    route: str | None = None, limit: int = replays.KEEP
) -> list[RequestSummary]:
    """The requests kept, newest first; ``route`` keeps one route's."""
    kept = (r for r in await replays.recent() if route is None or r.route == route)
    return [RequestSummary(**asdict(r)) for r in islice(kept, limit)]


async def find(request_id: str) -> RequestHops | None:
    """A kept request with its hops; None unless it is one and is kept."""
    recording = await replays.find(request_id)
    if recording is None:
        return None
    return await asyncio.to_thread(_read, recording)


def _read(recording: replays.Recording) -> RequestHops:
    """``recording`` named as the model names it (read from source)."""
    ids = {node.id for node in current().nodes}
    hops = sorted(recording.hops, key=lambda hop: hop.at_ms)
    chains = [_named(hop.chain, ids) for hop in hops]
    services = {
        part_of(key)
        for chain in chains
        for key in chain
        if parse_node_id(key)[0] is Kind.SERVICE
    }
    held = {
        path: Piece(key=piece.key, title=piece.title, service=service)
        for service in services
        for piece in service_pieces.held(service)
        for path in piece.paths
    }
    return RequestHops(
        **asdict(replays.summary(recording)),
        hops=tuple(
            RequestHop(
                chain=chain,
                at_ms=hop.at_ms,
                ms=hop.ms,
                error=hop.error,
                tables=tuple(hop.tables),
                lines=tuple(
                    CodeLine(path=path, line=line, piece=held.get(path))
                    for path, line in hop.trail
                ),
            )
            for hop, chain in zip(hops, chains, strict=True)
        ),
    )


def _named(chain: tuple[str, ...], ids: set[str]) -> tuple[str, ...]:
    """A hop's parts as the model's nodes: a sub-part it lacks as its part
    (``service:auth.users``: ``service:auth``), each once in a row."""
    named = (
        part_of(key) if key not in ids and part_of(key) in ids else key for key in chain
    )
    return tuple(key for key, _ in groupby(named))
