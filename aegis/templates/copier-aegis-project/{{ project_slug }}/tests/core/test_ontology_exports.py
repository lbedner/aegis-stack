"""The system model in other tools' formats (``ontology.exports``): the
docs' ``stack.md``, Backstage's ``catalog-info.yaml`` and the resource
attributes each process reports its traces under."""

import json
from pathlib import Path

import pytest
import yaml

from app.core.ontology import exports
from app.core.ontology.model import (
    Edge,
    EdgeKind,
    ExternalNode,
    JobNode,
    Kind,
    ObjectNode,
    PartNode,
    RouteNode,
    ToolNode,
)
from app.core.parts import Category
from tests._ontology import model_of

BACKEND = PartNode(kind=Kind.COMPONENT, name="backend", category=Category.COMPUTE)
DATABASE = PartNode(kind=Kind.COMPONENT, name="database", category=Category.DATA)
BLOG = PartNode(
    kind=Kind.SERVICE,
    name="blog",
    category=Category.APP,
    description="Markdown publishing",
    experimental=True,
)
AI = PartNode(kind=Kind.SERVICE, name="ai", category=Category.AI)
RAG = PartNode(kind=Kind.SERVICE, name="ai.rag", category=Category.AI, owner=AI.id)
MODEL = model_of(
    nodes=[
        BACKEND,
        DATABASE,
        BLOG,
        AI,
        RAG,
        RouteNode(name="GET /posts", method="GET", path="/posts", owner=BLOG.id),
        RouteNode(name="POST /posts", method="POST", path="/posts", owner=BLOG.id),
        JobNode(name="publish_due", schedule="cron minute=*", owner=BLOG.id),
        ObjectNode(name="blog_post", owner=BLOG.id),
        ToolNode(name="search", effect="read", admin=False, owner=RAG.id),
        ExternalNode(name="openai"),
    ],
    edges=[
        Edge(source=BLOG.id, target=DATABASE.id, kind=EdgeKind.DEPENDS_ON),
        Edge(source=AI.id, target="external:openai", kind=EdgeKind.CALLS),
    ],
)
SCHEMAS = Path(__file__).resolve().parents[1] / "fixtures" / "backstage"


def test_the_stack_page_lists_the_parts_by_category() -> None:
    page = exports.markdown(MODEL)
    assert page.index("## Compute") < page.index("`backend`")
    assert page.index("## Data") < page.index("`database`")
    assert "`blog`" in page and "`ai`" in page
    assert "`ai.rag`" not in page  # a sub-part counts toward its part


def test_a_service_says_what_it_holds() -> None:
    """Routes, jobs, tables and tools, a sub-part's toward its part's."""
    rows = {
        line.split("|")[1].strip(): line
        for line in exports.markdown(MODEL).splitlines()
        if line.startswith("| `")
    }
    assert "| 2 | 1 | 1 | 0 |" in rows["`blog`"]
    assert "| 0 | 0 | 0 | 1 |" in rows["`ai`"]


def test_the_catalog_has_the_stack_its_services_and_their_resources() -> None:
    entities = list(yaml.safe_load_all(exports.backstage(MODEL)))
    by = {(e["kind"], e["metadata"]["name"]): e for e in entities}
    system = by[("System", "app")]
    blog = by[("Component", "blog")]
    assert blog["spec"]["system"] == "app"
    assert blog["spec"]["lifecycle"] == "experimental"
    assert by[("Component", "ai")]["spec"]["lifecycle"] == "production"
    assert "resource:database" in blog["spec"]["dependsOn"]
    assert by[("Resource", "database")]["spec"]["type"] == "database"
    assert by[("Resource", "openai")]["spec"]["type"] == "external"
    assert system["spec"]["owner"] == blog["spec"]["owner"] == "group:default/app"


def test_the_catalog_is_what_backstage_accepts() -> None:
    """Every entity validates against Backstage's own schemas (its
    catalog-model package, vendored under ``tests/fixtures/backstage``)."""
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    schemas = [json.loads(p.read_text()) for p in SCHEMAS.glob("*.json")]
    registry = referencing.Registry().with_resources(
        (s["$id"], referencing.Resource.from_contents(s)) for s in schemas
    )
    by_kind = {s["$id"].removesuffix("V1alpha1").lower(): s for s in schemas}
    for entity in yaml.safe_load_all(exports.backstage(MODEL)):
        schema = by_kind[entity["kind"].lower()]
        jsonschema.Draft7Validator(schema, registry=registry).validate(entity)


def test_each_process_reports_under_its_own_name_in_one_namespace() -> None:
    worker = exports.otel(MODEL.stack, "worker")
    webserver = exports.otel(MODEL.stack, "webserver")
    assert worker["service.name"] == "worker"
    assert webserver["service.name"] == "webserver"
    assert worker["service.namespace"] == webserver["service.namespace"] == "app"
    assert worker["deployment.environment.name"] == "dev"
    assert worker["service.version"] == "dev"
