"""The shape of the system model: typed through and through, so a reader
(Overseer, MCP, docs) gets named fields, never a free dict. Each node kind
is its own model, told apart by ``kind``; ``SystemModel.model_json_schema``
is the published schema. New fields are additive; only a breaking change
bumps ``SCHEMA_VERSION``."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.parts import Category

SCHEMA_VERSION = 2


class Kind(StrEnum):
    SHARED = "shared"  # the app's shared code, no one part's (system, shared)
    COMPONENT = "component"
    SERVICE = "service"
    ROUTE = "route"
    JOB = "job"
    TOOL = "tool"
    CHANGE = "change"  # a change type the propose/approve queue runs
    CONTAINER = "container"
    EXTERNAL = "external"  # an outside provider a service calls
    OBJECT = "object"  # a table: what the app's data is (``domain``)
    KEYS = "keys"  # what a part keeps in Redis, by key pattern (``KeyFamily``)


class EdgeKind(StrEnum):
    CONTAINS = "contains"  # a part and its sub-part (AI and RAG)
    DEPENDS_ON = "depends_on"  # a process and what it needs (backend, database)
    CALLS = "calls"  # a service, or a job, and what its code reaches
    RUNS_ON = "runs_on"  # a part, or a job, and the container it runs in
    LINK = "link"  # a table and one its foreign key points at (``via``, ``to``)
    CHANGES = "changes"  # a change type and the table it changes


class Mode(StrEnum):
    SYNC = "sync"
    ASYNC = "async"  # handed to the queue, never waited on


def node_id(kind: Kind, name: str) -> str:
    """``<kind>:<name>``: ``component:cache``, ``service:ai.voice``."""
    return f"{kind.value}:{name}"


def parse_node_id(found: str) -> tuple[Kind, str]:
    """``node_id`` the other way: ``(Kind.COMPONENT, "cache")``."""
    kind, _, name = found.partition(":")
    return Kind(kind), name


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Kind
    name: str
    owner: str | None = None  # the id of the part it belongs to

    @computed_field
    @property
    def id(self) -> str:
        return node_id(self.kind, self.name)


class PartOption(BaseModel):
    """One way a part can be built (``ai[postgres]``), chosen when the stack
    is generated: its choices, the default, this stack's choice (None where
    none is recorded) and what each choice means, where its name does not
    say. ``aegis add`` raises an ordered option, turns a flag on and adds to
    a multi one; it refuses to swap any other on an existing stack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    mode: Literal["single", "multi", "flag"]
    choices: tuple[str, ...]
    default: str | tuple[str, ...] | bool | None = None
    chosen: str | tuple[str, ...] | bool | None = None
    ordered: bool = False  # the choices rise in order (auth: basic, rbac, org)
    about: dict[str, str] = {}


class PartNode(_Node):
    """A component, a service (``ai``) or sub-service (``ai.rag``), or the
    app's shared code (``system``)."""

    kind: Literal[Kind.SHARED, Kind.COMPONENT, Kind.SERVICE]
    category: Category
    description: str = ""  # its package's docstring, first line
    cli: str | None = None  # its name to the aegis CLI, where it has one
    page: str | None = None  # its Overseer page, where that is not its name
    experimental: bool = False  # its schema, APIs and CLI may still change
    options: tuple[PartOption, ...] = ()  # what else it could be


class _Code(_Node):
    """A node that is code in a part: the module defining it, where in its
    part it lives (a route in its router, a tool in a domain)."""

    module: str | None = None


class RouteNode(_Code):
    kind: Literal[Kind.ROUTE] = Kind.ROUTE
    method: str
    path: str


class JobNode(_Code):
    kind: Literal[Kind.JOB] = Kind.JOB
    schedule: str  # its trigger, as written: ``cron hour=3``


class ToolNode(_Code):
    kind: Literal[Kind.TOOL] = Kind.TOOL
    effect: str  # read, proposes or writes
    admin: bool


class ObjectField(BaseModel):
    """A column, or a change's payload field: names and types, never a
    value or a default."""

    model_config = ConfigDict(frozen=True)

    name: str  # the attribute: ``date_``
    column: str | None = None  # the column, where it is named otherwise: ``date``
    type: str
    nullable: bool = False
    primary_key: bool = False
    description: str = ""
    allowed: tuple[str, ...] = ()  # what a ``CHECK (x IN (...))`` lets in


class ObjectNode(_Code):
    """A table, by its name (never ``schema.name``: SQLite has none)."""

    kind: Literal[Kind.OBJECT] = Kind.OBJECT
    class_name: str = ""  # none for a table no model declares
    description: str = ""  # its class docstring's first sentence
    fields: tuple[ObjectField, ...] = ()


class ChangeNode(_Code):
    """A change an agent may propose and a person approves: what it does
    and the table it changes (its payload: the ``change_types`` tool)."""

    kind: Literal[Kind.CHANGE] = Kind.CHANGE
    title: str = ""
    description: str = ""
    object: str | None = None  # the table it changes, by node id


class KeysNode(_Code):
    """Keys a part keeps in Redis, by their pattern, in its own words."""

    kind: Literal[Kind.KEYS] = Kind.KEYS
    title: str  # its name: ``Chart history``
    purpose: str
    type: str  # the Redis type: ``stream``, ``list``
    db: str  # the settings field naming its logical database


class ContainerNode(_Node):
    kind: Literal[Kind.CONTAINER] = Kind.CONTAINER
    image: str | None = None


class ExternalNode(_Node):
    kind: Literal[Kind.EXTERNAL] = Kind.EXTERNAL
    keys: tuple[str, ...] = ()  # the needed secrets it is called with


Node = Annotated[
    PartNode
    | RouteNode
    | JobNode
    | ToolNode
    | ChangeNode
    | ContainerNode
    | ExternalNode
    | ObjectNode
    | KeysNode,
    Field(discriminator="kind"),
]


class State(StrEnum):
    """An edge as the running app has it (``observed``)."""

    BOTH = "both"  # declared, and seen
    OBSERVED_ONLY = "observed_only"  # seen, never declared: around the plan
    DECLARED_ONLY = "declared_only"  # declared, unseen in a day of traffic: dead
    BYPASS = "bypass"  # a model provider reached around the AI service


class Observed(BaseModel):
    """What the running app did along an edge this build (``edges``)."""

    model_config = ConfigDict(frozen=True)

    count: int
    errors: int
    mean_ms: float
    max_ms: float
    last_seen: float  # epoch seconds


class Edge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    kind: EdgeKind
    mode: Mode = Mode.SYNC
    via: str | None = None  # a link's foreign key column
    to: str | None = None  # ... and the column it points at
    observed: Observed | None = None
    state: State | None = None


class Stack(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    env: str
    build: str
    aegis_version: str


def stack() -> Stack:
    """This app as it names itself, from its settings: the one reader of
    its name, environment and build for the model, its exports and the
    traces it sends."""
    from app.core.config import settings

    return Stack(
        name=settings.PROJECT_NAME,
        env=settings.APP_ENV,
        build=settings.BUILD_ID,
        aegis_version=settings.AEGIS_STACK_VERSION,
    )


class SystemModel(BaseModel):
    """What this app is. ``partial`` when built where nothing registered
    (a CLI, a worker): what is on disk, not what runs."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[2] = SCHEMA_VERSION
    partial: bool
    stack: Stack
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def domain(self) -> Self:
        """Only the app's data and the changes to it, and the edges between
        them: what any chat user may read. The rest (routes, containers,
        providers, the modules the code lives in) is an admin's."""
        nodes = tuple(
            n.model_copy(update={"module": None})
            for n in self.nodes
            if n.kind in (Kind.OBJECT, Kind.CHANGE)
        )
        kept = {n.id for n in nodes}
        edges = tuple(e for e in self.edges if e.source in kept and e.target in kept)
        return self.model_copy(update={"nodes": nodes, "edges": edges})
