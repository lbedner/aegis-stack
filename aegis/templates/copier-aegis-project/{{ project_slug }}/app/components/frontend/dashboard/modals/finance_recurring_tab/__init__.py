"""Bills & Income, split by concern.

``tab`` owns state and the load/render spine; ``rows``, ``actions``,
``dialogs`` and ``editor`` are mixins over ``base``; ``projection`` is
the forecast panel; ``shared`` the vocabulary. The legacy underscore
names stay re-exported - tests and the dialog import them.
"""

from app.components.frontend.dashboard.modals.finance_recurring_tab.projection import (
    ProjectionPanel,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _COLUMNS,
    _NEXT_DUE_COLUMN,
    _NEXT_DUE_SORT_DESC,
    _status_key,
    pause_label,
    pause_options,
    projection_columns,
    projection_layout,
    stream_is_paused,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.tab import (
    RecurringTab,
)

__all__ = [
    "ProjectionPanel",
    "RecurringTab",
    "_COLUMNS",
    "_NEXT_DUE_COLUMN",
    "_NEXT_DUE_SORT_DESC",
    "_status_key",
    "pause_label",
    "pause_options",
    "projection_columns",
    "projection_layout",
    "stream_is_paused",
]
