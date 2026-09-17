"""The house vocabulary for modal content, grouped by what things are.

Was a single 2,093-line module holding cards, sections, four kinds of
chart, the lifecycle flow and a handful of formatters. Seventy-five
files import from it, in three different styles, so every name it
exposed is re-exported here and none of them had to change - the same
move finance_modal and insights_modal made before it.
"""

from app.components.frontend.dashboard.modals.modal_sections.cards import (
    InfoCard,
    MetricCard,
    MilestoneCard,
    headline_stat,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_bar import (
    BarChartCard,
    RankedBarCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_line import (
    LineChartCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_pie import (
    PIE_CHART_COLORS,
    PIE_CHART_TAIL_COLOR,
    PieChartCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    BarSeries,
    ChartColors,
    ChartPoint,
    LineSeries,
    RankedBar,
    axis_label_positions,
    chart_floor,
    chart_tooltip_kwargs,
    diverging_stop,
)
from app.components.frontend.dashboard.modals.modal_sections.formatting import (
    date_cell,
    format_duration_ms,
    format_timestamp,
    headline_stat_color,
    ledger_amount_color,
    row_matches,
    status_dot,
)
from app.components.frontend.dashboard.modals.modal_sections.lifecycle import (
    FlowConnector,
    FlowSection,
    LifecycleCard,
    LifecycleInspector,
)
from app.components.frontend.dashboard.modals.modal_sections.sections import (
    DateRangeChips,
    EmptyStatePlaceholder,
    MetricCardSection,
    SectionHeader,
    StatRowsSection,
)

__all__ = [
    "BarChartCard",
    "BarSeries",
    "ChartColors",
    "ChartPoint",
    "DateRangeChips",
    "EmptyStatePlaceholder",
    "FlowConnector",
    "FlowSection",
    "InfoCard",
    "LifecycleCard",
    "LifecycleInspector",
    "LineChartCard",
    "LineSeries",
    "MetricCard",
    "MetricCardSection",
    "MilestoneCard",
    "PIE_CHART_COLORS",
    "PIE_CHART_TAIL_COLOR",
    "PieChartCard",
    "RankedBar",
    "RankedBarCard",
    "SectionHeader",
    "StatRowsSection",
    "axis_label_positions",
    "chart_floor",
    "chart_tooltip_kwargs",
    "date_cell",
    "diverging_stop",
    "format_duration_ms",
    "format_timestamp",
    "headline_stat",
    "headline_stat_color",
    "ledger_amount_color",
    "row_matches",
    "status_dot",
]
