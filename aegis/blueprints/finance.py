"""Personal finance blueprint."""

from __future__ import annotations

from ..constants import (
    AIFrameworks,
    AIProviders,
    ComponentNames,
    StorageBackends,
)
from .spec import Blueprint, QKeys

BLUEPRINT = Blueprint(
    slug="finance",
    title="Personal finance",
    description=(
        "Track accounts, budgets, and goals, with a local AI analyst "
        "that narrates what changed."
    ),
    components=(
        ComponentNames.WORKER,
        ComponentNames.SCHEDULER,
        ComponentNames.DATABASE,
    ),
    services=("ai", "finance"),
    answers={
        QKeys.SCHEDULER_BACKEND: StorageBackends.SQLITE,
        QKeys.DATABASE_ENGINE: StorageBackends.SQLITE,
        QKeys.AI_STORAGE: StorageBackends.SQLITE,
        QKeys.AI_FRAMEWORK: AIFrameworks.PYDANTIC_AI,
        # Local by default: the analyst runs on Ollama, so nothing leaves
        # the machine and no API key is needed to start.
        QKeys.AI_PROVIDERS: (AIProviders.OLLAMA,),
    },
)
