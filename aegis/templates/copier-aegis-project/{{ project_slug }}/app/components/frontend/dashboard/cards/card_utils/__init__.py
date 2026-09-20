"""Everything a dashboard card is assembled from.

Split out of one 659-line module. Fifty-six call sites import from
``card_utils``, so every name it used to expose is re-exported here and
none of them changed.
"""

from .layout import (
    create_header_row,
    create_metric_container,
    create_progress_indicator,
    create_responsive_3_section_layout,
    create_stats_row,
)
from .modals import (
    _open_modal,
    create_card_click_handler,
    create_modal_for_component,
    trigger_dashboard_refresh,
)
from .status import (
    PROVIDER_COLORS,
    create_health_status_indicator,
    create_health_tag,
    get_ai_engine_display,
    get_status_color,
    get_status_colors,
    get_status_detail,
)
from .timing import format_next_run_time, format_schedule_human_readable

__all__ = [
    "PROVIDER_COLORS",
    "_open_modal",
    "create_card_click_handler",
    "create_header_row",
    "create_health_status_indicator",
    "create_health_tag",
    "create_metric_container",
    "create_modal_for_component",
    "create_progress_indicator",
    "create_responsive_3_section_layout",
    "create_stats_row",
    "format_next_run_time",
    "format_schedule_human_readable",
    "get_ai_engine_display",
    "get_status_color",
    "get_status_colors",
    "get_status_detail",
    "trigger_dashboard_refresh",
]
