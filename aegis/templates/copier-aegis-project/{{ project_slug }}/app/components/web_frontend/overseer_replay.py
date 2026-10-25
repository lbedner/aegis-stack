"""One request replayed on Overseer's map (``/overseer/replay/<id>``), a
scene a level, one after the other: the Server opened up where the
request went past one service, then each service it ran in opened up (one
with pieces of its own), the first opening on the way in (the stack's
edge, the Server), each drawing only what the request went through
(``overseer_zoom.along_*``) and drawn once (no stream: a live frame would
wipe the replay). The request's hops, read as every reader reads them
(``kept_requests``: each line of code with its service's piece), are the
player's steps (``static/js/timeline.js``) in each, at their real timing; in a view of
their own (``LIST_VIEW``) they are a list in the order they ran, each at
its line of code. And the recent requests, to pick one from
(``/overseer/replay``)."""

from collections.abc import Iterable
from itertools import groupby, pairwise
from typing import Any

from markupsafe import Markup

from app.core.edges import SERVER
from app.core.ontology.model import State
from app.core.ontology.observed import running
from app.core.ownership import HOST
from app.services.system import kept_requests, staged_paths, topology
from app.services.system.kept_requests import RequestHop, RequestHops, RequestSummary
from app.services.system.staged_paths import registry_of
from app.services.system.ui import is_service

from . import overseer_container
from .filters import answer_tone, worst_tone
from .overseer_nav import NavItem, current_navigation
from .overseer_zoom import Path, subject_of, title_of
from .rendering import fragment, templates, with_query

HOME = "/overseer/replay"
BEATS = 10  # the way in takes a tenth of the request a part
MAP = "pages/overseer/_overview_map.html"
LIST_VIEW = "hops"  # a request's hops as a list (``listed``)
# The way back out as it was answered (``filters.answer_tone``): fine,
# refused (4xx), or failed (5xx).
ANSWERED = {"ok": "active", "warn": "refused", "error": "failed"}
UNDECLARED = (State.OBSERVED_ONLY, State.BYPASS)  # an edge seen, never declared


def url(request_id: str = "", view: str | None = None) -> str:
    """A request's replay (or ``view`` of it); the recent ones without one."""
    return with_query(f"{HOME}/{request_id}", view=view) if request_id else HOME


# What links to a replay from elsewhere (an error, an Execute answer).
templates.env.globals["replay_url"] = url


async def recent() -> dict[str, Any]:
    """The requests kept, one row a route (the latest first): how many,
    the slowest, the most hops, and each of them, newest first."""
    routes: dict[str, list[RequestSummary]] = {}
    for kept in await kept_requests.recent():
        routes.setdefault(f"{kept.method} {kept.route or kept.path}", []).append(kept)
    return {
        "replay_routes": [
            {
                "route": route,
                "requests": kept,
                "count": len(kept),
                "slowest": f"{max(r.ms for r in kept)} ms",
                "hops": max(r.hop_count for r in kept),
                "tone": worst_tone(answer_tone(r.status) for r in kept),
            }
            for route, kept in routes.items()
        ]
    }


async def replay(
    navigation: dict[str, list[NavItem]],
    recording: RequestHops,
    scenes: int | None = None,
) -> dict[str, Any]:
    """``recording`` level by level, one after the other, each at the
    request's real timing (staged, a beat a hop); the first opens on the
    way in (the stack's edge, the Server), a beat a part, drawn ahead of
    what ran its route. On one service's screen, the answer goes back out
    the same way after it, on a track of its own (on several, the way in
    is not on the last; on the Server opened up, there is no second
    track). ``scenes``: the first so many levels drawn (all when None)."""
    recording = _folded(recording)
    hops, span = _timed(recording)
    parts = [_parts(hop) for hop in hops]
    installed = {entry.name for entry in navigation["components"]}
    # A request came in through the Server, even where its own hop for
    # that was not kept; a staged flow may start anywhere.
    entered = not recording.staged or any(hop.chain[0] == SERVER for hop in hops)
    way = [*(k for k in topology.EDGE if k in installed), HOST] if entered else []
    beat = span / BEATS
    services = _services(hops, parts)
    server = [[key for key in keys if key != HOST] for keys in parts]
    # One service's scene shows all the Server opened up would: every hop
    # was made in it.
    alone = len(services) == 1 and all(
        not keys or keys[0] == services[0][0] for keys in server
    )
    levels = services if alone else [(HOST, {}, server), *services]
    key, titles, lit = levels[0]
    entry = next(
        (keys[:1] for hop, keys in zip(hops, lit) if hop.chain[0] == SERVER), []
    )
    lead = beat * len(way)
    out = [*entry, *reversed(way)] if len(levels) == 1 and key != HOST else []
    ways = [*lit, way + entry, *([out] if out else [])]
    # Staged (read from the code, or joined on the map), nothing was seen.
    seen = frozenset() if recording.staged else None
    drawn = [await _scene(navigation, key, ways, 0.0, span, lead, seen)]
    found = _beats(key, [(None, way[0]), *pairwise(way)], 0.0, beat) if way else []
    found += _steps(key, lead, hops, lit, titles, recording.staged)
    if out:
        answered = ANSWERED[answer_tone(recording.status)]
        found += _beats(key, list(pairwise(out)), lead + span, beat, answered=answered)
    for key, titles, lit in levels[1:scenes]:
        at = drawn[-1]["at"] + drawn[-1]["lead"] + drawn[-1]["ms"]
        drawn.append(await _scene(navigation, key, lit, at, span, seen=seen))
        found += _steps(key, at, hops, lit, titles, recording.staged)
    return {
        "replay": recording,
        "replay_scenes": drawn,
        "replay_steps": found,
        "replay_switch": (url(recording.id, LIST_VIEW), "Hops"),
    }


async def card(path: RequestHops, large: bool) -> dict[str, Any]:
    """A path card's stage (``path_card``): its hops replayed as the
    Replay page replays them; in the thread (not ``large``), its first
    scene alone, the thumbnail."""
    scenes = None if large else 1
    played = await replay(current_navigation(), path, scenes)
    return {
        "path_steps": played["replay_steps"],
        "path_scenes": played["replay_scenes"],
    }


async def wiring(node_id: str) -> dict[str, Any]:
    """A path card's wiring (its ``node``): its lines as the map draws
    them (``staged_paths.wired``), on the Server's map as a replay draws a
    path, so the card shows what she read; still, nothing to play."""
    pairs = staged_paths.wired(await running(), node_id)
    # A part joined to it both ways (seen calling it, and called) is drawn
    # once, as its caller: above it, not tangled through what it calls.
    key = registry_of(node_id)
    ways = [[a, b] for a, b in pairs if not (a == key and (b, a) in pairs)]
    # Seen only where no edge of it is declared: a line its code draws is not.
    seen = frozenset(
        p for p, found in pairs.items() if all(e.state in UNDECLARED for e in found)
    )
    scene = await _scene(current_navigation(), HOST, ways, 0.0, 0.0, seen=seen)
    return {
        "path_steps": [],
        "path_scenes": [scene],
        "path_wired": title_of(key),
    }


def listed(recording: RequestHops) -> dict[str, Any]:
    """``recording``'s hops in a list (``LIST_VIEW``), in the order they
    ran: what each went through, its timing as a bar on the request's, and
    the line of code that made it (linked while Overseer > Code is on)."""
    hops, span = _timed(recording)
    rows = [
        {
            "label": _path_words(map(title_of, _parts(hop))),
            "hop": hop,
            "line": hop.lines[-1] if hop.lines else None,
            "left": hop.at_ms / span * 100,
            "width": max(hop.ms / span * 100, 0.5),
        }
        for hop in hops
    ]
    return {
        "replay": recording,
        "replay_rows": rows,
        "replay_switch": (url(recording.id), "Replay"),
    }


def _folded(recording: RequestHops) -> RequestHops:
    """A staged path as it plays: read function by function, it folds onto
    a few parts on the map, so a hop through the parts an earlier one went
    through is that one again; it joins it (its tables named there) rather
    than lighting the same line again, and the rest play a beat apart. A
    request that ran keeps every hop at its own time."""
    if not recording.staged:
        return recording
    kept: dict[tuple[str, ...], RequestHop] = {}
    for hop in recording.hops:
        # What the map lights for it (the Server's own map draws no Server).
        key = tuple(k for k in _parts(hop) if k != HOST)
        if (first := kept.get(key)) is None:
            kept[key] = hop
        else:
            tables = tuple(dict.fromkeys((*first.tables, *hop.tables)))
            kept[key] = first.model_copy(update={"tables": tables})
    return staged_paths.paced(recording, kept.values())


def _timed(recording: RequestHops) -> tuple[tuple[RequestHop, ...], float]:
    """Its hops, and how long it all ran."""
    hops = recording.hops
    return hops, max(recording.ms, *(hop.at_ms + hop.ms for hop in hops), 0.001)


async def _scene(
    navigation: dict[str, list[NavItem]],
    key: str,
    ways: list[list[str]],
    at: float,
    ms: float,
    lead: float = 0.0,
    seen: frozenset[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """A level's scene: its map drawing only the ``ways`` through it (a
    hop's each; ``seen``, its lines seen in traffic only, as ``Path``),
    shown from ``at``, ``ms`` of the request after a ``lead`` of staged
    beats."""
    path = Path(
        list(dict.fromkeys(k for keys in ways for k in keys)),
        list(dict.fromkeys(pair for keys in ways for pair in pairwise(keys))),
        seen,
    )
    query = {"view": overseer_container.MAP_VIEW, "zoom": key}
    view = await overseer_container.overview(navigation, query, path=path)
    return {
        "key": key,
        "title": title_of(key),
        "at": round(at, 3),
        "ms": round(ms, 3),
        "lead": round(lead, 3),
        "map": Markup(fragment(MAP, **view)),
    }


def _steps(
    scene: str,
    offset: float,
    hops: tuple[RequestHop, ...],
    lit: list[list[str]],
    titles: dict[str, str],
    staged: bool,
) -> list[dict[str, Any]]:
    """Each hop as the player's step in ``scene``, ``offset`` on: what it
    lights there (where it went, the lines between; a hop into one part,
    the part), and what it was, in words; the slowest held as a stall, a
    failure flashed. The request's own (the server running its route)
    spans it."""
    timed = [i for i, hop in enumerate(hops) if hop.chain[0] != SERVER and lit[i]]
    slowest = max(timed, key=lambda i: hops[i].ms, default=None)
    found = []
    for index, (hop, keys) in enumerate(zip(hops, lit, strict=True)):
        if not keys:
            continue
        state = "failed" if hop.error else "stall" if index == slowest else "active"
        found.append(
            {
                "at": round(offset + hop.at_ms, 3),
                "ms": hop.ms,
                "targets": _targets(scene, keys[1:] or keys, pairwise(keys)),
                "state": state,
                "says": _says(
                    hop, [titles.get(key) or title_of(key) for key in keys], staged
                ),
            }
        )
    return found


def _beats(
    scene: str,
    pairs: list[tuple[str | None, str]],
    at: float,
    beat: float,
    *,
    answered: str | None = None,
) -> list[dict[str, Any]]:
    """A way (the way in, or back out, lit as it was ``answered``) as the
    player's steps in ``scene`` from ``at``, a ``beat`` a part: each part
    lit with the line from the one before it. Staged, not timed: no hop
    is this."""
    found = []
    for index, (before, key) in enumerate(pairs):
        line = [] if before is None else [(before, key)]
        title = title_of(key)
        found.append(
            {
                "at": round(at + index * beat, 3),
                "ms": round(beat, 3),
                "targets": _targets(scene, [key], line),
                "state": answered or "active",
                "says": f"Back out through {title}" if answered else title,
            }
        )
    return found


def _targets(scene: str, nodes: list[str], lines: Any) -> list[str]:
    """What a step lights in ``scene``: its ``nodes``, then its ``lines``
    (pairs of node keys), as the map draws them (``_overview_map.html``)."""
    within = f'[data-play-scene="{scene}"]'
    return [f'{within} [data-node="{key}"]' for key in nodes] + [
        f'{within} [data-link][data-from="{a}"][data-to="{b}"]' for a, b in lines
    ]


def _parts(hop: RequestHop) -> list[str]:
    """What ``hop`` went through, by map key, each once in a row: a part of
    a service's (Auth's users) is the service's."""
    return [key for key, _ in groupby(map(registry_of, hop.chain))]


def _services(
    hops: tuple[RequestHop, ...], parts: list[list[str]]
) -> list[tuple[str, dict[str, str], list[list[str]]]]:
    """Each service the request ran in that opens up (one it went through
    pieces of: opened up, one it only went past is the Server's map again),
    in the order it reached them: its key, its pieces' titles, and what
    each hop went through in it (``_in``)."""
    found = []
    for key in filter(is_service, dict.fromkeys(k for keys in parts for k in keys)):
        subject = subject_of(key)
        titles = {p.key: p.title for hop in hops for p in hop.pieces(subject)}
        if titles:
            lit = [_in(key, subject, keys, hop) for keys, hop in zip(parts, hops)]
            found.append((key, titles, lit))
    return found


def _in(service: str, subject: str, keys: list[str], hop: RequestHop) -> list[str]:
    """The pieces of ``service`` (``subject``, its node) ``hop`` was made
    through (its lines), then where it went from them; none for a hop not
    in it (``keys``, what it went through)."""
    if service not in keys:
        return []
    went = [piece.key for piece in hop.pieces(subject)]
    after = keys[keys.index(service) + 1 :][:1]
    return [k for k, _ in groupby([*went, *after])]


def _says(hop: RequestHop, titles: list[str], staged: bool) -> str:
    """A hop in words: what it went through, the tables it read, how long
    it took (staged, it took no time of the app's), where in the code it
    was made."""
    took = "" if staged else f"{hop.ms} ms"
    said = [_path_words(titles), ", ".join(hop.tables), took, hop.where]
    return " · ".join(part for part in said if part) + (" failed" if hop.error else "")


def _path_words(titles: Iterable[str]) -> str:
    """What a hop went through, in words: ``Router › Facade › Database``."""
    return " › ".join(titles)
