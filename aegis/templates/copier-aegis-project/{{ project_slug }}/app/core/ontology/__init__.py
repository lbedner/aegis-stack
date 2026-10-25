"""What this app is, as one typed model (``system_model``): every part,
route, job, worker queue and task, tool, change type, table, Redis key
family, container and outside provider, joined by edges, derived from
the code and the registries; nobody keeps it by hand."""

from app.core.ontology.model import (
    SCHEMA_VERSION,
    EdgeKind,
    JobNode,
    KeysNode,
    Kind,
    Mode,
    ObjectNode,
    PartNode,
    QueueNode,
    SystemModel,
    TaskNode,
)
from app.core.ontology.system import current, system_model, with_app

__all__ = [
    "SCHEMA_VERSION",
    "EdgeKind",
    "JobNode",
    "KeysNode",
    "Kind",
    "Mode",
    "ObjectNode",
    "PartNode",
    "QueueNode",
    "SystemModel",
    "TaskNode",
    "current",
    "system_model",
    "with_app",
]
