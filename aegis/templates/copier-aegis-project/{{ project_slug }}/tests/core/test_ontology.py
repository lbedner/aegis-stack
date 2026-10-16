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
    JobNode,
    KeysNode,
    Kind,
    Mode,
    ObjectNode,
    PartNode,
    SystemModel,
    calls,
    system_model,
)
from app.core.ontology.parts import _Packages, service_folders
from app.core.parts import Category
from app.services.system import health, redis_keys, topology
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
    assert dumped["schema_version"] == SCHEMA_VERSION == 2
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


def test_every_part_with_code_says_what_it_is_for(model: SystemModel) -> None:
    """Its package's docstring: the line Illiana's app map gives it. The
    backend had none, so asked how the app reaches its database she made
    up an answer (2026-10-16)."""
    packages = _Packages(source_index.project())
    silent = [
        p.id
        for p in model.nodes
        if isinstance(p, PartNode)
        and p.kind in (Kind.COMPONENT, Kind.SERVICE)
        and not p.description
        and packages.of(p.kind, p.name) is not None
    ]
    assert not silent


def test_the_queue_says_what_it_is(model: SystemModel) -> None:
    """It has no package to say it, so asked what breaks when Redis goes
    down she read the cache it sits in and left the worker out
    (2026-10-16)."""
    queue = f"component:{topology.QUEUE}"  # none without a worker
    assert all(n.description for n in model.nodes if n.id == queue)


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
        n.id for n in model.nodes if n.kind in owned and not getattr(n, "module", None)
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
        if source.startswith(f"{Kind.SHARED}:"):
            continue
        package = index.root / "app" / "services" / folder
        for target in calls.talks_to(package, secrets.declared(), index):
            if target in ids and target != source:
                assert (source, target) in found
    # Work handed to the queue is never waited on.
    queue = f"component:{topology.QUEUE}"
    edges = [e for e in model.edges if e.kind is EdgeKind.CALLS]
    assert all((e.mode is Mode.ASYNC) == (e.target == queue) for e in edges)


def test_the_apps_own_code_is_shared_code(model: SystemModel) -> None:
    """No one part's: the code every service imports to be one."""
    system = _parts(model)["shared:system"]
    assert system.kind is Kind.SHARED


def test_the_migration_record_is_the_databases_table(model: SystemModel) -> None:
    """A table no model declares is a node all the same, its owner's, so
    the model's tables are the database's."""
    tables = {n.name: n for n in model.nodes if isinstance(n, ObjectNode)}
    if not tables:
        pytest.skip("no database in this stack")
    record = tables["alembic_version"]
    assert record.owner == "component:database" and record.description


def test_the_schedulers_heartbeat_is_its_job(model: SystemModel) -> None:
    """Every job the scheduler runs is a node: its own, beside the
    services'; the heartbeat runs in the scheduler itself."""
    jobs = {n.name: n for n in model.nodes if isinstance(n, JobNode)}
    if "component:scheduler" not in _parts(model):
        pytest.skip("no scheduler in this stack")
    beat = jobs["scheduler_heartbeat"]
    assert beat.owner == "component:scheduler" and beat.module
    runs_on = {e.target for e in model.edges if e.source == beat.id}
    assert runs_on == {"container:scheduler"}


def test_each_redis_key_family_is_a_node(model: SystemModel) -> None:
    """What the app keeps in Redis, in its owners' words, and held by the
    part declaring it (else by Redis, the cache component)."""
    if "component:cache" not in _parts(model):
        pytest.skip("no Redis in this stack")
    ids = {n.id for n in model.nodes}
    found = {n.name: n for n in model.nodes if isinstance(n, KeysNode)}
    for family in redis_keys.families():
        node = found[family.pattern]
        assert (node.title, node.purpose, node.type) == (
            family.name,
            family.purpose,
            family.kind,
        )
        assert node.owner in ids
    assert found["series-hour:*"].owner == "component:cache"  # core's


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
