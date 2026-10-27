"""What the system tools hand back (``tools``): each answer a model, its
JSON what the agent reads. Where an answer is trimmed, its fields say so:
an edge or a hop names only what is not its default (``SAID``), a node in
a list only what names it (``BriefNode``)."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, PlainSerializer

from app.core.figures import FIGURES, absent
from app.core.ontology.model import Edge, Node
from app.core.ontology.summary import Summary
from app.services.system.dry_path import DryPath
from app.services.system.dry_walk import Hop
from app.services.system.errors.models import ErrorIssue, ErrorOccurrence
from app.services.system.kept_requests import RequestHops, RequestSummary
from app.services.system.models import ComponentStatus
from app.services.system.node_now import Attention, ContainerNow, NodeNow
from app.services.system.pattern_findings import Finding

# Only what is not its default, so a call that waits (every call) says
# nothing of its mode, a hand-off does, and an unset field is not there to
# repeat. An unannotated lambda: a serializer that declares what it returns
# is what the schema shows, and code mode's stubs would lose the fields.
SAID = PlainSerializer(lambda found: found.model_dump(mode="json", exclude_defaults=True))


class BriefNode(BaseModel):
    """A node as a list names it."""

    model_config = FIGURES

    id: str
    kind: str
    name: str
    owner: str | None  # the part it belongs to
    queue: str | None = absent()  # a task's
    category: str | None = absent()  # a part's
    schedule: str | None = absent()  # a job's

    @classmethod
    def of(cls, node: Node, *more: str) -> "BriefNode":
        keep = {"id", "kind", "name", "owner", "queue", *more}
        return cls.model_validate(node.model_dump(mode="json", include=keep))


class HealthTree(BaseModel):
    """A check as the tree shows it: its status, its message, its parts."""

    model_config = FIGURES

    status: str
    message: str
    parts: dict[str, "HealthTree"] | None = absent()


class HealthNow(BaseModel):
    """Every check at once (``health`` with no component)."""

    model_config = FIGURES

    healthy: bool
    checked_at: datetime
    counts: dict[str, int]  # each check once, by status
    attention: list[Attention]
    components: dict[str, HealthTree]
    note: str | None


class ComponentHealth(BaseModel):
    """One check, with what its containers use (``health`` of one)."""

    model_config = FIGURES

    component: ComponentStatus
    containers: list[ContainerNow]
    containers_note: str | None
    note: str | None


class Issues(BaseModel):
    """The issues errors group into, latest first."""

    model_config = FIGURES

    issues: list[ErrorIssue]
    total: int
    note: str | None


class Issue(BaseModel):
    """One issue: its latest occurrence with its traceback, and the rest."""

    model_config = FIGURES

    detail: ErrorOccurrence | None
    occurrences: list[ErrorOccurrence]
    total: int
    note: str | None


class LogEntry(BaseModel):
    """One log line, its traceback folded in."""

    model_config = FIGURES

    at: str
    service: str
    container: str
    level: str | None
    message: str
    logger: str | None
    fields: dict[str, Any]
    trace: str | None


class Logs(BaseModel):
    model_config = FIGURES

    lines: list[LogEntry]
    note: str | None


class RecentRequests(BaseModel):
    model_config = FIGURES

    requests: list[RequestSummary]
    kept: int  # how many the server keeps


class OneRequest(BaseModel):
    model_config = FIGURES

    request: RequestHops


class Walk(DryPath):
    """A dry path whose hops each say only what is not their default."""

    hops: tuple[Annotated[Hop, SAID], ...]


class RouteWalk(BaseModel):
    """A route's dry path, its hops trimmed (``total`` has them all)."""

    model_config = FIGURES

    dry_path: Walk
    total: dict[str, int]


class NodeAnswer(BaseModel):
    """One node, what is true of it now, and what is around it."""

    model_config = FIGURES

    node: Node
    now: NodeNow | None
    findings: list[Finding]
    edges: list[Annotated[Edge, SAID]]
    neighbors: list[BriefNode]
    total: dict[str, int]  # before the lists were trimmed
    note: str | None


class NodeAnswers(BaseModel):
    model_config = FIGURES

    nodes: list[NodeAnswer]


class Paths(BaseModel):
    model_config = FIGURES

    paths: list[list[Annotated[Edge, SAID]]]
    note: str | None


class Matches(BaseModel):
    model_config = FIGURES

    nodes: list[BriefNode]
    total: int
    note: str | None


class AppSummary(Summary):
    """The summary, its parts and jobs named in brief; a reader who may
    not see them (None) is not told of them."""

    model_config = FIGURES

    parts: tuple[BriefNode, ...] | None = absent()
    jobs: tuple[BriefNode, ...] | None = absent()
    note: str | None = None


class QueryRows(BaseModel):
    """A statement's first rows, as text."""

    model_config = FIGURES

    columns: list[str]
    rows: list[list[str]]
    more: bool


class Buckets(BaseModel):
    model_config = FIGURES

    buckets: list[str]


class StoredFile(BaseModel):
    model_config = FIGURES

    key: str
    size: int
    modified: datetime | None


class BucketLevel(BaseModel):
    """One level of a bucket: its folders and its files."""

    model_config = FIGURES

    bucket: str
    prefix: str
    folders: list[str]
    files: list[StoredFile]
    truncated: bool
