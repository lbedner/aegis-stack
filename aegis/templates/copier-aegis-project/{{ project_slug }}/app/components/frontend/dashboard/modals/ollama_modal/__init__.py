"""The Ollama detail modal, split by tab.

``ollama_modal.py`` was eleven hundred lines of three tabs plus the
table machinery the models tab needs. Each is now its own module; this
re-exports the names that were importable before, so nothing outside
the package had to change.
"""

from .activity_tab import ActivitySection, ActivityTab
from .cells import (
    build_modified_cell,
    capability_cell,
    format_context_length,
    format_model_id,
    format_quantization,
    model_cell,
)
from .columns import (
    ACTIVITY_COLUMNS,
    CAPABILITIES,
    MODEL_COLUMNS,
    MODEL_TABLE_WIDTH,
    MODELS_MODAL_WIDTH,
    Capability,
    table_width,
)
from .dialog import OllamaDetailDialog
from .model_actions import ModelActionButton, UseModelControl
from .models_tab import ModelsSection, ModelsTab
from .overview_tab import OverviewSection, OverviewTab, ServerInfoSection

__all__ = [
    "ACTIVITY_COLUMNS",
    "CAPABILITIES",
    "MODELS_MODAL_WIDTH",
    "MODEL_COLUMNS",
    "MODEL_TABLE_WIDTH",
    "ActivitySection",
    "ActivityTab",
    "Capability",
    "ModelActionButton",
    "ModelsSection",
    "ModelsTab",
    "OllamaDetailDialog",
    "OverviewSection",
    "OverviewTab",
    "ServerInfoSection",
    "UseModelControl",
    "build_modified_cell",
    "capability_cell",
    "format_context_length",
    "format_model_id",
    "format_quantization",
    "model_cell",
    "table_width",
]
