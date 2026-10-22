"""A service opened up on the map (``?view=map&zoom=service_<name>``):
the same lanes for every service, left to right (its ways in, wiring,
facade, domains, data, the parts it reaches), its pieces (``service_pieces``) in
them with the imports between as lines, a missing part a dashed slot, the
way back up, and what each piece should fix."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import (
    overseer_conformance,
    overseer_container,
    overseer_map,
    overseer_zoom,
)
from app.core.ontology.model import Edge, EdgeKind, RouteNode
from app.services.system import service_pieces
from app.services.system.service_pieces import Piece
from tests._ontology import model_of
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html
from tests.web.zoomed import LINES, PIECES, ROUTER, auth_opens, finding_of, zoomable

OPENED = "/overseer?view=map&zoom=service_auth"


def _opened(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """``zoomable``, Auth with four pieces and a route in its router."""
    client = zoomable(app, monkeypatch)
    route = RouteNode(
        name="GET /auth/me",
        method="GET",
        path="/auth/me",
        owner="service:auth",
        module=ROUTER,
    )
    calling = Edge(
        source="service:auth", target="component:database", kind=EdgeKind.CALLS
    )
    model = model_of([route], [calling])
    monkeypatch.setattr(overseer_container, "current", lambda: model)
    lacking = overseer_conformance.Conformance({}, {"service_auth": ["Tests"]})
    monkeypatch.setattr(overseer_conformance, "conformance", lambda: lacking)
    auth_opens(monkeypatch)
    return client


def test_only_a_service_that_opens_up_is_a_zoom() -> None:
    """A stale or hand-typed link (a removed service, a sub-service with
    no level of its own) opens nothing, rather than an empty map."""
    for zoom in ("service_nope", "service_rag"):
        state = overseer_container.map_state({"view": "map", "zoom": zoom})
        assert state["zoom"] is None
    opened = overseer_container.map_state({"view": "map", "zoom": "service_auth"})
    assert opened["zoom"] == "service_auth"


def test_each_service_in_the_server_opens_up(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = page_html(_opened(app, monkeypatch), "/overseer?view=map&zoom=backend")
    zoom = one(html, '[data-node="service_auth"] [data-zoom]')
    assert zoom.get("href") == OPENED
    none(html, '[data-node="secrets"] [data-zoom]')  # no pieces of its own


def test_a_service_opened_up_is_its_pieces_and_what_they_reach(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("app.services.auth.service")  # its pieces open Auth's code
    html = page_html(_opened(app, monkeypatch), OPENED)
    for piece in PIECES:
        assert text(one(html, f'[data-node="{piece.key}"] [data-title]')) == piece.title
    assert len(select(html, "[data-lane]")) == 6
    # Its imports as lines: past the facade to data red, back a lane amber.
    path = 'svg path[data-from="{}"][data-to="{}"]'
    tone = lambda a, b: one(html, path.format(a, b)).get("data-tone")  # noqa: E731
    assert tone("piece:router", "piece:facade") not in ("error", "warn")
    assert tone("piece:router", "piece:queries") == "error"
    assert tone("piece:queries", "piece:facade") == "warn"
    none(html, '[data-from="piece:health"]')  # a probe watches; no lines
    # Each says why on hover, in a panel; a key names the tones drawn.
    whys = {text(hint) for hint in select(html, "[data-line-hint] .tooltip-panel")}
    assert whys == {
        "Router skips the facade into Queries",
        "Queries goes back a lane to Facade",
    }
    hits = {hit.get("data-hit") for hit in select(html, "svg [data-hit]")}
    assert hits == {
        hint.get("data-line-hint") for hint in select(html, "[data-line-hint]")
    }
    keyed = select(html, "[data-line-key] [data-tone]")
    assert [swatch.get("data-tone") for swatch in keyed] == ["error", "warn"]
    none(html, '[data-node="backend"]')  # the Server it lives in
    # What nearly every piece uses rides a rail, each user badged.
    one(html, '[data-rail] [data-rail-item="database"]')
    none(html, 'svg path[data-to="database"]')
    assert "database" in one(html, '[data-node="piece:facade"]').get("data-uses")
    # A part it lacks: a dashed slot in its lane, no toggle needed to see it.
    assert one(html, '[data-node="missing:Tests"]').get("data-missing") is not None
    # A piece opens its code.
    assert "/overseer/code" in one(html, '[data-node="piece:facade"] [data-title]').get(
        "href"
    )
    # What hangs off a piece: counted on it, named in its hint; a piece
    # with none names its public functions and classes.
    assert text(one(html, '[data-node="piece:router"] [data-figure]')) == "1 route"
    holds = lambda key: text(one(html, f'[data-node="{key}"] [data-holds]'))  # noqa: E731
    assert holds("piece:router") == "GET /auth/me"
    assert "get_current_user_from_token" in holds("piece:facade")
    assert "_build_dev_user" not in holds("piece:facade")
    # Each opens its code: at its definition, or its module (a route).
    held = 'a[data-held="{}"]'
    there = one(html, held.format("get_current_user_from_token")).get("href")
    assert "service.py#L-" in there
    assert "#L-" not in one(html, held.format("GET /auth/me")).get("href")
    # The way back up, a level at a time.
    trail = [a.get("href") for a in select(html, "[data-breadcrumb] a")]
    assert trail == ["/overseer?view=map", "/overseer?view=map&zoom=backend"]
    assert text(one(html, "[data-breadcrumb] [aria-current]")) == "Authentication"
    # Traffic is counted by part, not piece: no overlay here.
    none(html, "[data-overlays]")
    assert "zoom=service_auth" in one(html, "#overview-stack").get("sse-connect")


def test_a_piece_says_what_its_files_should_fix(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finding about the service marks the piece its evidence sits in:
    how many places, and on hover each one, linked, with its line. No
    overlay: a piece's tone, and so its lines', stay its own."""
    client = _opened(app, monkeypatch)
    evidence = ("app/services/auth/service.py:12", "app/services/auth/service.py:30")
    finding = finding_of("parts.reads-in-queries", "Reads live in queries", evidence)
    found = overseer_conformance.Conformance(
        {"service_auth": [finding]}, {"service_auth": ["Queries"]}
    )
    monkeypatch.setattr(overseer_conformance, "conformance", lambda: found)
    html = page_html(client, OPENED)
    none(html, "[data-overlays]")
    facade = one(html, '[data-node="piece:facade"]')
    assert facade.get("data-tone") != "error"
    assert text(one(facade, "[data-to-fix]")) == "2 to fix"
    # What to do, then each place in full, with what it says there.
    assert text(one(facade, "[data-todo] p")) == "Fix it."
    assert text(one(facade, "[data-hint]")).startswith("Files: service")
    places = select(facade, "[data-todo] li")
    assert [text(one(p, "a")) for p in places] == [
        "app/services/auth/service.py:12",
        "app/services/auth/service.py:30",
    ]
    none(html, '[data-node="piece:health"] [data-to-fix]')
    # A long list stays inside the window: the hint scrolls, not the page.
    panel = one(facade, "[data-hint] .tooltip-panel").get("class") or ""
    assert "overflow-y-auto" in panel and "max-h-" in panel
    into = select(html, 'path[data-link][data-to="piece:facade"]')
    assert into and all(line.get("data-tone") != "error" for line in into)


def test_a_way_in_running_its_adapters_is_not_a_shortcut() -> None:
    """Jobs run the providers' syncs and the collectors: a way in using
    the service's adapters is its work, not a step past the facade; and
    adapters sit with the domains, so reading what those know is no step
    back (one-way use within a lane is a hint, not a line)."""
    lane = {
        "jobs": "entry",
        "facade": "facade",
        "adapters": service_pieces.LANE_OF["Adapters"],
    }
    links = [("jobs", "adapters"), ("facade", "adapters")]
    assert overseer_zoom._tones(links, lane, {k: k for k in lane}) == {}
    assert service_pieces.LANE_OF["Adapters"] == "domains"


def test_a_service_reads_left_to_right_in_lanes() -> None:
    """Every service the same shape: a lane each for its ways in, wiring,
    facade, domains, data and what it reaches, its imports as lines between (each as
    toned as flagged; within a lane an arrow out
    to the side); its probes set apart under its ways in."""
    places = {
        "router": "entry",
        "deps": "wiring",
        "facade": "facade",
        "chat": "domains",
        "llm": "domains",
        "queries": "data",
        "health": "probe",
        "database": "outside",
    }
    stack = [
        {"key": k, "registry": k, "title": k, "tone": "ok", "place": place}
        for k, place in places.items()
    ]
    links = [("router", "deps"), ("router", "queries"), ("chat", "llm")]
    found = overseer_map.lanes(
        stack, links, {("router", "queries"): {"tone": "error", "why": "past"}}
    )
    x = {n["key"]: n["left"] for n in found["map_nodes"]}
    top = {n["key"]: n["top"] for n in found["map_nodes"]}
    assert x["router"] < x["deps"] < x["facade"] < x["chat"] == x["llm"]
    assert x["llm"] < x["queries"]
    assert x["queries"] < x["database"]
    assert [lane["label"] for lane in found["map_lanes"]] == [
        "Entry",
        "Wiring",
        "Facade",
        "Domains",
        "Data",
        "Outside",
    ]
    assert x["health"] == x["router"] and top["health"] > top["chat"]
    drawn = {(link["start"], link["end"]): link for link in found["map_links"]}
    assert drawn[("router", "queries")]["tone"] == "error"
    assert drawn[("chat", "llm")]["arrow"] and not drawn[("router", "deps")]["arrow"]


def test_a_line_past_a_lane_goes_around_what_is_in_it() -> None:
    """A line skipping lanes never runs behind a node in one (it would read
    as a line into it): it takes a gap clear of them. A line back a lane
    leaves its node's left side, not back through it."""
    places = {"router": "entry", "deps": "wiring", "queries": "data"}
    places |= {"facade": "facade", "database": "outside"}
    stack = [
        {"key": k, "registry": k, "title": k, "tone": "ok", "place": place}
        for k, place in places.items()
    ]
    links = [("router", "database"), ("queries", "facade")]
    found = overseer_map.lanes(stack, links, {})
    nodes = {n["key"]: n for n in found["map_nodes"]}
    drawn = {(link["start"], link["end"]): link["d"] for link in found["map_links"]}
    run = float(drawn[("router", "database")].split(" L ")[1].split()[1])
    for key in ("deps", "facade", "queries"):
        top = nodes[key]["top"]
        assert not top <= run <= top + nodes[key]["height"], key
    back = float(drawn[("queries", "facade")].split()[1])
    queries = nodes["queries"]["left"] * overseer_map.WIDTH / 100
    assert back < queries  # its left side


def test_constants_ride_the_rail_not_a_lane(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Constants are imported from every lane (models, routers, domains):
    in a lane, a line into them from past it reads as a step back. On the
    rail, each user is badged instead, and no line is drawn. Schemas, the
    shapes every lane hands on, the same."""
    assert service_pieces.LANE_OF["Schemas"] == service_pieces.LANE_OF["Constants"]
    client = _opened(app, monkeypatch)
    constants = Piece(
        "piece:constants",
        "Constants",
        service_pieces.LANE_OF["Constants"],
        ("app.services.auth.constants",),
        (),
    )
    lines = LINES | {constants.key: []}
    lines["piece:queries"] = [*LINES["piece:queries"], constants.key]
    monkeypatch.setattr(
        overseer_zoom,
        "pieces_of",
        lambda subject, model: ([*PIECES, constants], lines),
    )
    html = page_html(client, OPENED)
    one(html, '[data-rail] [data-rail-item="piece:constants"]')
    none(html, 'svg path[data-to="piece:constants"]')
    assert "piece:constants" in one(html, '[data-node="piece:queries"]').get(
        "data-uses"
    )
    assert "Constants" in text(one(html, '[data-node="piece:queries"]'))


def test_a_piece_using_another_of_its_lane_says_so_without_a_line(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chat using Spend is said in Chat's hint; only two using each other
    (tangled) draws a line, red. A domain using the facade goes back a
    lane: amber."""
    client = _opened(app, monkeypatch)
    chat = Piece(
        "piece:domains.chat", "Chat", "domains", ("app.services.auth.domains.chat",), ()
    )
    llm = Piece(
        "piece:domains.llm", "Llm", "domains", ("app.services.auth.domains.llm",), ()
    )
    spend = Piece(
        "piece:domains.spend",
        "Spend",
        "domains",
        ("app.services.auth.domains.spend",),
        (),
    )
    lines = LINES | {
        chat.key: [llm.key, spend.key, "piece:facade"],
        llm.key: [chat.key],
        spend.key: [],
    }
    lines["piece:facade"] = [*LINES["piece:facade"], chat.key]
    monkeypatch.setattr(
        overseer_zoom,
        "pieces_of",
        lambda subject, model: ([*PIECES, chat, llm, spend], lines),
    )
    html = page_html(client, OPENED)
    assert "Uses Llm, Spend" in text(one(html, f'[data-node="{chat.key}"] [data-hint]'))
    path = 'svg path[data-from="{}"][data-to="{}"]'
    none(html, path.format(chat.key, spend.key))
    assert one(html, path.format(chat.key, llm.key)).get("data-tone") == "error"
    assert one(html, path.format(chat.key, "piece:facade")).get("data-tone") == "warn"
    whys = {text(hint) for hint in select(html, "[data-line-hint]")}
    assert "Chat and Llm use each other (a loop)" in whys
