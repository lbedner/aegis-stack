"""Column widths and thresholds the tabs share."""

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTable,
    DataTableColumn,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.expandable_data_table import (
    ExpandableDataTable,
    ExpandableRow,
)
from app.components.frontend.controls.markdown import copyable_markdown
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from ..modal_sections import PIE_CHART_COLORS, EmptyStatePlaceholder, MetricCard


OVERVIEW_BAR_CHART_LIMIT = 10
STAT_LABEL_WIDTH = 150
_EXC_COLUMNS = [
    DataTableColumn("Exception", style="primary"),
    DataTableColumn("Message", style="body"),
    DataTableColumn("Count", width=80, style="secondary"),
    DataTableColumn("Latest", width=150, style="secondary"),
]


def _format_latency(ms: float) -> str:
    """Format latency value for display."""
    if ms == 0:
        return "0 ms"
    if ms < 1:
        return f"{ms:.2f} ms"
    if ms < 1000:
        return f"{ms:.1f} ms"
    return f"{ms / 1000:.2f} s"
