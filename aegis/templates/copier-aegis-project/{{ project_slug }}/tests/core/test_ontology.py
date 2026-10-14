"""What this app is (``ontology.system_model``): one typed model of its
parts, routes, jobs, tools, change types, containers and outside providers,
and the edges between them, derived from the code and the registries."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core import secrets, source_index
from app.core.ontology import (
    SCHEMA_VERSION,
    EdgeKind,
    Kind,
    Mode,
    PartNode,
    SystemModel,
    calls,
    system_model,
)
from app.core.ontology.parts import service_folders
from app.core.parts import Category
from app.services.system import health, topology
from app.services.system.patterns import PROJECT_ROOT


@pytest.fixture
def model(app: FastAPI, client: TestClient) -> SystemModel:
    """Built while the app runs (``client``): startup has registered every
    health check, as in the webserver."""
    return system_model(app)


def _parts(model: SystemModel) -> dict[str, PartNode]:
    return {n.id: n for n in model.nodes if isinstance(n, PartNode)}


def test_the_top_level_shape_is_pinned(model: SystemModel) -> None:
    """A consumer may rely on these keys: new ones are additive, and only a
    breaking change bumps ``schema_version``."""
    dumped = model.model_dump()
    assert set(dumped) == {"schema_version", "partial", "stack", "nodes", "edges"}
    assert dumped["schema_version"] == SCHEMA_VERSION == 1
    assert set(dumped["stack"]) == {"name", "env", "build", "aegis_version"}
    assert set(dumped["edges"][0]) == {
        "source",
        "target",
        "kind",
        "mode",
        "via",
        "to",
        "observed",
        "state",
    }
    assert not model.partial


def test_every_installed_part_is_a_node_with_its_concern(model: SystemModel) -> None:
    names = health.registered_health_names()
    parts = _parts(model)
    for name in names["components"]:
        assert f"component:{name}" in parts
    for name in names["services"]:
        assert f"service:{name}" in parts
    assert parts["component:backend"].category is Category.COMPUTE
    assert all(isinstance(p.category, Category) for p in parts.values())


def test_every_route_job_tool_and_change_type_has_an_owner(model: SystemModel) -> None:
    ids = {n.id for n in model.nodes}
    owned = (Kind.ROUTE, Kind.JOB, Kind.TOOL, Kind.CHANGE)
    unowned = [
        n.id
        for n in model.nodes
        if n.kind in owned and (n.owner is None or n.owner not in ids)
    ]
    assert not unowned, unowned
    contained = {e.target for e in model.edges if e.kind is EdgeKind.CONTAINS}
    assert all(n.id in contained for n in model.nodes if n.kind in owned)
    assert any(n.kind is Kind.ROUTE for n in model.nodes)
    # And the module that defines it: where in its part it lives.
    unplaced = [
        n.id
        for n in model.nodes
        if n.kind in owned and not getattr(n, "module", None)
    ]
    assert not unplaced, unplaced


def test_the_components_links_are_the_maps(model: SystemModel) -> None:
    """``topology.shape``'s lines, from the model's edges: work handed to
    the queue is asynchronous."""
    components = [p.name for p in _parts(model).values() if p.kind is Kind.COMPONENT]
    expected = {
        (f"component:{a}", f"component:{b}")
        for a, b in topology.shape(components).links
    }
    depends = [e for e in model.edges if e.kind is EdgeKind.DEPENDS_ON]
    assert {(e.source, e.target) for e in depends} == expected
    queue = f"component:{topology.QUEUE}"
    assert all(
        (e.mode is Mode.ASYNC) == (queue in (e.source, e.target)) for e in depends
    )


def test_each_services_calls_are_what_it_imports(model: SystemModel) -> None:
    """What each services folder's code reaches (``calls.talks_to``), from
    the part the folder is: rag's calls are AI's RAG's."""
    found = {(e.source, e.target) for e in model.edges if e.kind is EdgeKind.CALLS}
    ids = {n.id for n in model.nodes}
    index = source_index.project()
    for folder, source in service_folders(index, ids):
        if source.startswith(f"{Kind.STACK}:"):
            continue
        package = index.root / "app" / "services" / folder
        for target in calls.talks_to(package, secrets.declared(), index):
            if target in ids and target != source:
                assert (source, target) in found
    # Work handed to the queue is never waited on.
    queue = f"component:{topology.QUEUE}"
    edges = [e for e in model.edges if e.kind is EdgeKind.CALLS]
    assert all((e.mode is Mode.ASYNC) == (e.target == queue) for e in edges)


def test_a_folder_part_of_a_service_is_its_sub_service(model: SystemModel) -> None:
    if not (PROJECT_ROOT / "app" / "services" / "rag").is_dir():
        pytest.skip("no RAG in this stack")
    rag = _parts(model)["service:ai.rag"]
    assert rag.owner == "service:ai"
    assert rag.category is Category.AI
    contains = {
        (e.source, e.target) for e in model.edges if e.kind is EdgeKind.CONTAINS
    }
    assert ("service:ai", "service:ai.rag") in contains


def test_every_part_runs_somewhere_named(model: SystemModel) -> None:
    """The webserver hosts every service; a container a part runs as is a
    node."""
    ids = {n.id for n in model.nodes}
    runs_on = [e for e in model.edges if e.kind is EdgeKind.RUNS_ON]
    assert all(e.target in ids for e in runs_on)
    hosted = {e.source for e in runs_on if e.target == "container:webserver"}
    services = [
        p.id for p in _parts(model).values() if p.kind is Kind.SERVICE and not p.owner
    ]
    assert set(services) <= hosted


def test_before_startup_the_model_says_it_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside the webserver nothing has registered: what is on disk, said
    to be partial rather than passed off as the whole."""
    monkeypatch.setattr(
        health, "registered_health_names", lambda: {"components": (), "services": ()}
    )
    found = system_model()
    assert found.partial
    assert "component:backend" in _parts(found)


@pytest.mark.usefixtures("model")  # startup has registered the rest
def test_a_plugin_service_is_a_node_of_its_own(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registered but unknown to the app's names: a service all the same,
    in the App concern unless its package says otherwise."""
    names = health.registered_health_names()
    monkeypatch.setattr(
        health,
        "registered_health_names",
        lambda: {**names, "services": (*names["services"], "fake_plugin")},
    )
    plugin = _parts(system_model(app))["service:fake_plugin"]
    assert plugin.category is Category.APP
