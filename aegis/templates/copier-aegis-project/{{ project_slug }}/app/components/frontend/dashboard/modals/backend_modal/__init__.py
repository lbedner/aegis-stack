"""The backend detail modal, one module per tab.

``backend_modal.py`` was twelve hundred lines of six tabs. Each tab is
now its own module; this re-exports the names that were importable
before, so nothing outside the package had to change.
"""

from .dialog import BackendDetailDialog
from .lifecycle_tab import LifecycleTab
from .overview_tab import OverviewTab
from .performance_tab import PerformanceTab
from .routes_tab import RouteGroupSection, RoutesTab, RouteTableRow
from .traffic_tab import TrafficTab

__all__ = [
    "BackendDetailDialog",
    "LifecycleTab",
    "OverviewTab",
    "PerformanceTab",
    "RouteGroupSection",
    "RouteTableRow",
    "RoutesTab",
    "TrafficTab",
]
