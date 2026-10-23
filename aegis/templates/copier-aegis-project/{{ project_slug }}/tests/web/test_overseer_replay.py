"""One request replayed on the map (``/overseer/replay/<id>``): a scene a
level, the Server then each service it ran in opened up, each drawn once
(no stream: a frame would wipe the replay) with only what the request went
through; the hops as the player's steps and as a list beside it, in the
order they ran; and the recent requests to pick one from."""

from collections.abc import AsyncIterator
import json

from fastapi import FastAPI
import pytest

from app.components.web_frontend import overseer_map, overseer_zoom
from app.components.web_frontend.overseer_zoom import title_of
from app.core import edges, exposure, replays
from app.core.replays import Hop
from app.services.system import service_pieces
from app.services.system.models import ComponentStatus
from tests._replays import kept
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, reported_only
from tests.web.zoomed import DB, auth_opens, zoomable


@pytest.fixture(autouse=True)
async def fresh() -> AsyncIterator[None]:
    await replays.reset()
    yield
    await replays.reset()


ROUTES = "app/components/backend/api/auth/router.py"
FACADE = "app/services/auth/service.py"
QUERIES = "app/services/auth/queries.py"
SERVER = '[data-play-scene="backend"]'
INGRESS = ComponentStatus(name="ingress", message="Routing", metadata={})
AUTH = '[data-play-scene="service_auth"]'


async def _recorded(*hops: Hop, status: int = 200) -> replays.Recording:
    """A request to Auth's route that made ``hops``, the server running
    the route spanning it, answered with ``status``."""
    route = Hop((edges.SERVER, "service:auth"), 0.0, 20.0, False, ((ROUTES, 9),))
    return await kept("/api/v1/auth/me", route, *hops, status=status)


def _from(source: str, to: str, at: float, *paths: str, error: bool = False) -> Hop:
    """A hop from ``source`` made through ``paths``, a query reading ``user``."""
    trail = tuple((path, 1) for path in paths)
    return Hop((source, to), at, 2.0, error, trail, ["user"] if to == DB else [])


def _nodes(scene: object) -> set[str]:
    return {node.get("data-node") for node in select(scene, "[data-node]")}


async def test_a_request_plays_in_through_the_ingress_then_inside_auth(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    # A query from a part of Auth's (its users): still Auth's, to the Database.
    trail = tuple((path, 1) for path in (ROUTES, FACADE, QUERIES))
    query = Hop(("service:auth", "service:auth.users", DB), 5.0, 2.0, False, trail)
    query.tables.append("user")
    found = await _recorded(
        query,
        _from("service:auth", "external:Stripe", 9.0, ROUTES, FACADE, error=True),
    )
    html = page_html(client, f"/overseer/replay/{found.id}")
    player = one(html, "[data-player]")
    # Speeds said plainly.
    speeds = [text(option) for option in select(player, "[data-play-speed] option")]
    assert speeds == [
        "Real time",
        "5x slower",
        "10x slower",
        "50x slower",
        "100x slower",
        "1000x slower",
    ]
    # Drawn once: no map stream (the sidebar keeps its own).
    none(html, "#overview-stack")
    none(player, "[sse-connect]")
    # One screen: all it did was Auth's, so Auth opened up is the whole
    # of it, the way in (the ingress, the Server) drawn ahead of its pieces;
    # no scenes to go between, so no chapters.
    none(player, "[data-play-chapter]")
    none(player, SERVER)
    auth = one(player, AUTH)
    assert float(auth.get("data-play-at")) == 0.0
    # Its clock is the request's: the way in leads it, staged.
    way_in = float(auth.get("data-play-lead"))
    assert 0 < way_in < 20.0
    assert float(auth.get("data-play-ms")) == 20.0
    # Drawn at its own height, not stretched to the window.
    assert "map-fill" not in one(auth, "[data-map]").get("class")
    # Only what the request went through.
    assert _nodes(auth) == {
        "ingress",
        "backend",
        "piece:router",
        "piece:facade",
        "piece:queries",
        "database",
        "outside:Stripe",
    }
    one(auth, 'path[data-from="ingress"][data-to="backend"]')
    one(auth, 'path[data-from="backend"][data-to="piece:router"]')
    # Only the lanes it went through: the Database beside the code
    # that queried it.
    lanes = [text(lane) for lane in select(auth, "[data-lane]")]
    assert lanes == ["Edge", "Server", "Entry", "Facade", "Data", "Outside"]
    one(auth, 'path[data-from="piece:router"][data-to="piece:facade"]')
    one(auth, 'path[data-from="piece:queries"][data-to="database"]')
    # Shown, not a way off the replay: nothing on its maps is a link.
    assert all(
        scene.get("inert") is not None for scene in select(player, "[data-scene-map]")
    )
    steps = json.loads(text(one(player, "script[data-play-steps]")))
    lit = {target: step["state"] for step in steps for target in step["targets"]}
    # In a beat at a time: the ingress, then the Server; then the request
    # at its real timing, from its route.
    first = [(step["targets"][0], step["at"]) for step in steps[:3]]
    assert first == [
        (f'{AUTH} [data-node="ingress"]', 0.0),
        (f'{AUTH} [data-node="backend"]', way_in / 2),
        (f'{AUTH} [data-node="piece:router"]', way_in),
    ]
    assert steps[1]["says"] == "Server"
    # Answered, it goes back out the way it came, a beat a part, on its
    # own track (``test_the_way_in_runs_on_two_tracks``).
    one(auth, 'path[data-from="piece:router"][data-to="backend"]')
    one(auth, 'path[data-from="backend"][data-to="ingress"]')
    back = [(step["targets"], step["state"], step["at"]) for step in steps[-2:]]
    assert back == [
        (
            [
                f'{AUTH} [data-node="backend"]',
                f'{AUTH} [data-link][data-from="piece:router"][data-to="backend"]',
            ],
            "active",
            way_in + 20.0,
        ),
        (
            [
                f'{AUTH} [data-node="ingress"]',
                f'{AUTH} [data-link][data-from="backend"][data-to="ingress"]',
            ],
            "active",
            way_in * 1.5 + 20.0,
        ),
    ]
    assert lit[f'{AUTH} [data-node="outside:Stripe"]'] == "failed"
    assert f'{AUTH} [data-link][data-from="piece:queries"][data-to="database"]' in lit
    # What each step is, in words, under the controls.
    one(player, "[data-play-caption]")
    assert any("Database" in s["says"] and "user" in s["says"] for s in steps)
    # The map has the page; the hops in a list are a view of their own.
    none(html, "[data-hops]")
    listed = one(html, "a[data-replay-view]").get("href")
    assert listed == f"/overseer/replay/{found.id}?view=hops"
    hops = page_html(client, listed)
    none(hops, "[data-player]")
    rows = [text(row) for row in select(hops, "[data-hops] [data-hop]")]
    assert ["Auth" in rows[0], "Database" in rows[1], "Stripe" in rows[2]] == [
        True,
        True,
        True,
    ]
    assert "user" in rows[1]  # the table it queried
    assert rows[1].count(title_of("service_auth")) == 1  # its users are Auth's
    back = one(hops, "a[data-replay-view]").get("href")
    assert back == f"/overseer/replay/{found.id}"
    # Each at its line of code, linked while Overseer > Code is on.
    assert one(hops, '[data-hop="1"] a').get("href").startswith("/overseer/code")
    monkeypatch.setattr(exposure, "shown", lambda name: False)
    none(page_html(client, listed), '[data-hop="1"] a')


@pytest.mark.parametrize(
    ("status", "tone", "state"),
    [(200, "ok", "active"), (401, "warn", "refused"), (503, "error", "failed")],
)
async def test_the_answer_goes_back_out_in_its_tone(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, status: int, tone: str, state: str
) -> None:
    """How it was answered, said where it shows: the status at the top and
    the way back out. A refusal (4xx) is the server working, amber; only a
    failure (5xx) is red."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    html = page_html(client, f"/overseer/replay/{(await _recorded(status=status)).id}")
    answer = one(html, "[data-answer]")
    assert (text(answer), answer.get("data-tone")) == (str(status), tone)
    assert text(answer.getparent()).endswith(" 1 hop")
    steps = json.loads(text(one(html, "script[data-play-steps]")))
    assert [step["state"] for step in steps[-2:]] == [state, state]


async def test_a_hop_the_map_has_no_line_for_is_drawn_as_seen(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay, not the plan: a call the model does not declare still ran,
    so it gets a line of its own, marked as seen only."""
    client = zoomable(app, monkeypatch)
    reported_only(monkeypatch)  # not what another test registered
    found = await _recorded(
        _from("service:auth", DB, 2.0), _from(DB, "external:Stripe", 4.0)
    )
    html = page_html(client, f"/overseer/replay/{found.id}")
    # Past Auth (the Database calling out): the Server opened up shows it,
    # first; no ingress, so straight in.
    scene = one(html, SERVER)
    assert {"backend", "service_auth"} <= _nodes(scene)
    assert "ingress" not in _nodes(scene)
    line = one(scene, 'path[data-link][data-from="database"][data-to="outside:Stripe"]')
    assert line.get("data-observed") is not None
    declared = one(
        scene, 'path[data-link][data-from="service_auth"][data-to="database"]'
    )
    assert declared.get("data-observed") is None


def test_a_malformed_id_is_not_looked_up(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = zoomable(app, monkeypatch)

    def looked_up(_: str) -> None:
        raise AssertionError("looked up")

    monkeypatch.setattr(replays, "find", looked_up)
    assert client.get("/overseer/replay/not-an-id").status_code == 404


def test_a_request_no_longer_kept_says_so(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = page_html(zoomable(app, monkeypatch), f"/overseer/replay/{'a' * 32}")
    none(html, "[data-player]")
    assert "no longer kept" in text(one(html, "[data-replay-empty]"))


async def test_the_recent_requests_one_row_a_route_newest_first(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests to one route are one row (how many, the slowest, the most
    hops), in the tone of its worst answer, opening to each of them,
    newest first, each a replay."""
    client = zoomable(app, monkeypatch)
    none(page_html(client, "/overseer/replay"), "[data-route]")
    first, second = await _recorded(), await _recorded(status=401)
    await kept("/health/detailed")
    html = page_html(client, "/overseer/replay")
    routes = select(html, "[data-route]")
    assert [(text(r), r.get("data-tone")) for r in routes] == [
        ("GET /health/detailed", "ok"),
        ("GET /api/v1/auth/me", "warn"),
    ]
    requests = select(html, "[data-replay-requests]")
    assert [a.get("href") for a in select(requests[1], "a")] == [
        f"/overseer/replay/{second.id}",
        f"/overseer/replay/{first.id}",
    ]
    assert "1 hop" in text(requests[1]) and "1 hops" not in text(requests[1])


async def test_a_request_answered_in_the_server_goes_no_way_out(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drawn on the Server opened up (no service of its own to open), its
    way in has one track: no way back out over it."""
    client = zoomable(app, monkeypatch)
    monkeypatch.setattr(overseer_zoom, "pieces_of", lambda subject, model: ([], {}))
    monkeypatch.setattr(service_pieces, "held", lambda subject: [])
    html = page_html(client, f"/overseer/replay/{(await _recorded()).id}")
    one(html, SERVER)
    steps = json.loads(text(one(html, "script[data-play-steps]")))
    assert not [step for step in steps if step["says"].startswith("Back out")]


def test_the_map_offers_a_replay(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    html = page_html(zoomable(app, monkeypatch), "/overseer?view=map")
    assert one(html, "[data-replay-link]").get("href") == "/overseer/replay"


def test_the_way_in_runs_on_two_tracks() -> None:
    """The ingress and the Server stand taller than a piece, so a line both
    ways between two lanes runs on two tracks: in above the middle, back
    out below it."""

    def node(key: str, place: str) -> dict[str, str]:
        return {"key": key, "title": key, "place": place, "tone": "ok"}

    way = ["ingress", "backend", "piece:router"]
    stack = [node(way[0], "edge"), node(way[1], "server"), node(way[2], "entry")]
    there = list(zip(way, way[1:]))
    drawn = overseer_map.lanes(
        stack, there + [(b, a) for a, b in there], {}, used_only=True
    )
    nodes = {node["key"]: node for node in drawn["map_nodes"]}
    assert nodes["ingress"]["height"] == nodes["backend"]["height"]
    assert nodes["ingress"]["height"] > nodes["piece:router"]["height"]
    lines = {
        (line["start"], line["end"]): line["d"].split() for line in drawn["map_links"]
    }
    # "M x y C ...": where each leaves the ingress and lands back on it.
    leaves = float(lines[("ingress", "backend")][2])
    lands = float(lines[("backend", "ingress")][-1])
    top, height = nodes["ingress"]["top"], nodes["ingress"]["height"]
    assert top < leaves < top + height / 2 < lands < top + height


async def test_a_request_whose_server_hop_was_not_kept_still_plays_the_way_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request always came in through the Server: its own hop for that is
    noted last and can be dropped (past what a request keeps), and the
    way in plays all the same."""
    client = zoomable(app, monkeypatch, INGRESS)
    auth_opens(monkeypatch)
    found = await kept("/api/v1/auth/me", _from("service:auth", DB, 2.0, QUERIES))
    html = page_html(client, f"/overseer/replay/{found.id}")
    steps = json.loads(text(one(html, "script[data-play-steps]")))
    assert steps[0]["says"] == title_of("ingress")
