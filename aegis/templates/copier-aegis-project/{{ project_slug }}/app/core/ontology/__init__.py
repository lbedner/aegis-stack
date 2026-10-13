"""What this app is, as one typed model (``system_model``): every part,
route, job, tool, change type, container and outside provider, joined by
edges, derived from the code and the registries; nobody keeps it by hand."""

from app.core.ontology.model import (
    SCHEMA_VERSION,
    EdgeKind,
    Kind,
    Mode,
    PartNode,
    SystemModel,
)
from app.core.ontology.system import current, system_model

__all__ = [
    "SCHEMA_VERSION",
    "EdgeKind",
    "Kind",
    "Mode",
    "PartNode",
    "SystemModel",
    "current",
    "system_model",
]
