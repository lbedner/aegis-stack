"""
Backend Detail Modal

Displays comprehensive backend/FastAPI information including routes,
middleware stack, system metrics, and configuration details in a tabbed interface.
"""

from collections.abc import Generator
from contextlib import contextmanager

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    ExpandArrow,
    H3Text,
    LabelText,
    MethodBadge,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.data_table import DataTableColumn
from app.components.frontend.controls.expandable_data_table import (
    ExpandableDataTable,
    ExpandableRow,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import create_progress_indicator, get_status_detail
from .base_detail_popup import BaseDetailPopup
from .load_tests_tab import LoadTestsTab
from .modal_sections import (
    FlowConnector,
    FlowSection,
    LifecycleCard,
    LifecycleInspector,
    MetricCard,
)

try:
    import logfire
except ModuleNotFoundError:  # observability not installed
    logfire = None  # type: ignore[assignment]


@contextmanager
def _span(name: str) -> Generator[None]:
    """Logfire span wrapper — no-op when logfire is unavailable."""
    if logfire is not None:
        with logfire.span(name):
            yield
    else:
        yield


def _get_metric_color(percent: float) -> str:
    """Get color based on metric percentage."""
    if percent >= 90:
        return Theme.Colors.ERROR
    elif percent >= 70:
        return Theme.Colors.WARNING
    else:
        return Theme.Colors.SUCCESS


# Keywords to detect auth dependencies
AUTH_KEYWORDS = [
    "auth",
    "token",
    "verify",
    "current_user",
    "permission",
    "oauth2",
    "bearer",
]


def _has_auth_dependencies(dependencies: list[str]) -> bool:
    """Check if route has authentication dependencies."""
    if not dependencies:
        return False
    return any(
        any(keyword in dep.lower() for keyword in AUTH_KEYWORDS) for dep in dependencies
    )


def _route_has_auth(route_info: dict[str, object]) -> bool:
    """Whether a route is auth-protected.

    Prefers the accurate ``requires_auth`` flag from route metadata (security
    scheme detection); falls back to dependency-name matching only for older
    payloads that lack it.
    """
    deps = list(route_info.get("dependencies", []))
    return bool(route_info.get("requires_auth", _has_auth_dependencies(deps)))


class RouteTableRow(ft.Container):
    """Expandable table row for a single route."""

    def __init__(self, route_info: dict[str, object]) -> None:
        """Initialize route table row (header only — details built on first expand)."""
        super().__init__()
        self.route_info = route_info
        self.is_expanded = False
        self._details_built = False

        # Extract route data for header
        path = str(route_info.get("path", ""))
        methods = list(route_info.get("methods", []))
        summary = str(route_info.get("summary", ""))
        deprecated = bool(route_info.get("deprecated", False))

        has_auth = _route_has_auth(route_info)

        # Truncate summary for display
        summary_display = summary[:40] + "..." if len(summary) > 40 else summary

        # Method badges (show first method prominently)
        method_badges = [MethodBadge(m) for m in methods]

        # Arrow for expand indicator (reusable control)
        self.expand_arrow = ExpandArrow(expanded=False)

        # Build row header with hover effect
        self.row_container = ft.Container(
            content=ft.Row(
                [
                    # Expand arrow (24px)
                    ft.Container(
                        content=self.expand_arrow,
                        width=24,
                    ),
                    # Method column (70px)
                    ft.Container(
                        content=ft.Row(method_badges, spacing=2),
                        width=70,
                    ),
                    # Path column (flex)
                    ft.Container(
                        content=ft.Row(
                            [
                                PrimaryText(path),
                                ft.Container(
                                    content=SecondaryText(
                                        "DEPRECATED",
                                        size=9,
                                        color=ft.Colors.ORANGE,
                                    ),
                                    visible=deprecated,
                                    padding=ft.padding.only(left=8),
                                ),
                            ],
                            spacing=0,
                        ),
                        expand=True,
                    ),
                    # Auth column (40px)
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.LOCK,
                            size=14,
                            color=Theme.Colors.WARNING,
                        )
                        if has_auth
                        else ft.Container(),
                        width=40,
                        alignment=ft.alignment.center,
                    ),
                    # Summary column (180px)
                    ft.Container(
                        content=SecondaryText(summary_display or "-"),
                        width=180,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.MD, vertical=10),
            bgcolor=ft.Colors.SURFACE,
            on_hover=self._on_hover,
        )

        # Build row header
        self.row_header = ft.GestureDetector(
            content=self.row_container,
            on_tap=self._toggle_expand,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        # Empty placeholder for details (built lazily on first expand)
        self.details = ft.Container(visible=False)

        self.content = ft.Column([self.row_header, self.details], spacing=0)
        self.border = ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE))

    def _build_details(self) -> None:
        """Build the expandable detail panel (called once on first expand)."""
        route_info = self.route_info
        name = str(route_info.get("name", ""))
        summary = str(route_info.get("summary", ""))
        description = str(route_info.get("description", ""))
        path_params = list(route_info.get("path_params", []))
        dependencies = list(route_info.get("dependencies", []))
        response_model = str(route_info.get("response_model", ""))

        detail_rows: list[ft.Control] = []

        if name:
            detail_rows.append(
                ft.Row(
                    [SecondaryText("Endpoint:"), BodyText(name)],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=8,
                )
            )

        if summary:
            detail_rows.append(
                ft.Row(
                    [SecondaryText("Summary:"), BodyText(summary)],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=8,
                )
            )

        if description:
            detail_rows.append(
                ft.Column(
                    [SecondaryText("Description:"), BodyText(description)],
                    spacing=4,
                )
            )

        if path_params:
            detail_rows.append(
                ft.Row(
                    [SecondaryText("Path Params:"), BodyText(", ".join(path_params))],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=8,
                )
            )

        if dependencies:
            dep_badges = []
            for dep in dependencies:
                is_auth = any(kw in dep.lower() for kw in AUTH_KEYWORDS)
                if is_auth:
                    badge_content = ft.Row(
                        [
                            ft.Icon(ft.Icons.LOCK, size=12, color=Theme.Colors.WARNING),
                            LabelText(dep, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=4,
                        tight=True,
                    )
                else:
                    badge_content = LabelText(dep, color=ft.Colors.ON_SURFACE_VARIANT)

                dep_badges.append(
                    ft.Container(
                        content=badge_content,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=4,
                    )
                )

            detail_rows.append(
                ft.Column(
                    [
                        SecondaryText("Dependencies:"),
                        ft.Row(dep_badges, spacing=4, wrap=True),
                    ],
                    spacing=4,
                )
            )

        if response_model:
            detail_rows.append(
                ft.Row(
                    [SecondaryText("Response:"), BodyText(response_model)],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=8,
                )
            )

        self.details.content = ft.Column(detail_rows, spacing=Theme.Spacing.SM)
        self.details.padding = ft.padding.only(
            top=Theme.Spacing.SM,
            left=Theme.Spacing.MD + 24,  # Match arrow column width
            right=Theme.Spacing.MD,
            bottom=Theme.Spacing.MD,
        )
        self.details.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self._details_built = True

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover state change."""
        if e.data == "true":
            self.row_container.bgcolor = ft.Colors.with_opacity(
                0.08, ft.Colors.ON_SURFACE
            )
        else:
            self.row_container.bgcolor = ft.Colors.SURFACE
        if e.control.page:
            self.row_container.update()

    def _toggle_expand(self, e: ft.ControlEvent) -> None:
        """Toggle expansion state."""
        _ = e  # Unused but required by callback signature
        if not self._details_built:
            self._build_details()
        self.is_expanded = not self.is_expanded
        self.details.visible = self.is_expanded
        self.expand_arrow.set_expanded(self.is_expanded)
        self.update()


class RouteGroupSection(ft.Container):
    """Collapsible section containing routes for a single tag group."""

    def __init__(
        self, group_name: str, routes: list[dict[str, object]], start_expanded: bool
    ) -> None:
        """Initialize route group section."""
        super().__init__()
        self.group_name = group_name
        self.routes = routes
        self.is_expanded = start_expanded

        # Sort routes by path
        sorted_routes = sorted(routes, key=lambda r: str(r.get("path", "")))

        # Build table header
        table_header = ft.Container(
            content=ft.Row(
                [
                    # Arrow column placeholder
                    ft.Container(width=24),
                    ft.Container(
                        content=SecondaryText("Method", size=11),
                        width=70,
                    ),
                    ft.Container(
                        content=SecondaryText("Path", size=11),
                        expand=True,
                    ),
                    ft.Container(
                        content=SecondaryText("Auth", size=11),
                        width=40,
                        alignment=ft.alignment.center,
                    ),
                    ft.Container(
                        content=SecondaryText("Summary", size=11),
                        width=180,
                    ),
                ],
                spacing=Theme.Spacing.SM,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        # Build route rows
        route_rows = [RouteTableRow(route) for route in sorted_routes]

        # Table container (matches ExpandableDataTable styling)
        self.table_container = ft.Container(
            content=ft.Column(
                [table_header] + route_rows,
                spacing=0,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=Theme.Components.CARD_RADIUS,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            visible=start_expanded,
        )

        # Group header (clickable)
        self.arrow_icon = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_DOWN
            if start_expanded
            else ft.Icons.KEYBOARD_ARROW_RIGHT,
            size=20,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

        # Group-level auth marker: lock the tag if ANY route in it is
        # protected, so you can see a group contains protected routes without
        # expanding it. Same lock/icon as the per-route Auth column.
        group_has_auth = any(_route_has_auth(r) for r in routes)
        group_lock = (
            ft.Icon(
                ft.Icons.LOCK,
                size=12,
                color=Theme.Colors.WARNING,
                tooltip="Contains protected routes",
            )
            if group_has_auth
            else ft.Container(width=0)
        )

        group_header = ft.GestureDetector(
            content=ft.Container(
                content=ft.Row(
                    [
                        self.arrow_icon,
                        PrimaryText(f"{group_name}"),
                        SecondaryText(f"({len(routes)} routes)"),
                        group_lock,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(vertical=8),
            ),
            on_tap=self._toggle_expand,
            mouse_cursor=ft.MouseCursor.CLICK,
        )

        self.content = ft.Column(
            [group_header, self.table_container],
            spacing=4,
        )
        self.padding = ft.padding.only(bottom=12)

    def _toggle_expand(self, e: ft.ControlEvent) -> None:
        """Toggle expansion state."""
        _ = e  # Unused but required by callback signature
        self.is_expanded = not self.is_expanded
        self.table_container.visible = self.is_expanded
        self.arrow_icon.name = (
            ft.Icons.KEYBOARD_ARROW_DOWN
            if self.is_expanded
            else ft.Icons.KEYBOARD_ARROW_RIGHT
        )
        self.update()


class OverviewTab(ft.Container):
    """Overview tab combining metrics and system resources."""

    def __init__(self, backend_component: ComponentStatus) -> None:
        """
        Initialize overview tab.

        Args:
            backend_component: ComponentStatus containing backend data
        """
        super().__init__()
        metadata = backend_component.metadata or {}
        sub_components = backend_component.sub_components or {}

        # Extract metrics
        total_routes = metadata.get("total_routes", 0)
        total_endpoints = metadata.get("total_endpoints", 0)
        total_middleware = metadata.get("total_middleware", 0)
        security_count = metadata.get("security_count", 0)
        deprecated_count = metadata.get("deprecated_count", 0)
        method_counts = metadata.get("method_counts", {})

        # Build metric cards
        metric_cards = [
            MetricCard(
                value=str(total_routes),
                label="Total Routes",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=str(total_endpoints),
                label="Endpoints",
                color=Theme.Colors.SUCCESS,
            ),
            MetricCard(
                value=str(total_middleware),
                label="Middleware",
                color=ft.Colors.PURPLE,
            ),
            MetricCard(
                value=str(security_count),
                label="Security Layers",
                color=ft.Colors.AMBER,
            ),
        ]

        # Add deprecated count if any
        if deprecated_count > 0:
            metric_cards.append(
                MetricCard(
                    value=str(deprecated_count),
                    label="Deprecated",
                    color=ft.Colors.ORANGE,
                )
            )

        # Method distribution
        method_text = ", ".join(
            [f"{count} {method}" for method, count in method_counts.items()]
        )

        # Build system metrics
        cpu_data = sub_components.get("cpu")
        memory_data = sub_components.get("memory")
        disk_data = sub_components.get("disk")

        system_metrics = []

        # CPU metric
        if cpu_data and cpu_data.metadata:
            cpu_percent = cpu_data.metadata.get("percent_used", 0.0)
            cpu_cores = cpu_data.metadata.get("core_count", 0)
            cpu_color = _get_metric_color(cpu_percent)
            system_metrics.append(
                create_progress_indicator(
                    label=f"CPU Usage ({cpu_cores} cores)",
                    value=cpu_percent,
                    details=f"{cpu_percent:.1f}%",
                    color=cpu_color,
                )
            )

        # Memory metric
        if memory_data and memory_data.metadata:
            memory_percent = memory_data.metadata.get("percent_used", 0.0)
            memory_total = memory_data.metadata.get("total_gb", 0.0)
            memory_available = memory_data.metadata.get("available_gb", 0.0)
            memory_used = memory_total - memory_available
            memory_color = _get_metric_color(memory_percent)
            system_metrics.append(
                create_progress_indicator(
                    label="Memory Usage",
                    value=memory_percent,
                    details=f"{memory_used:.1f} / {memory_total:.1f} GB",
                    color=memory_color,
                )
            )

        # Disk metric
        if disk_data and disk_data.metadata:
            disk_percent = disk_data.metadata.get("percent_used", 0.0)
            disk_free = disk_data.metadata.get("free_gb", 0.0)
            disk_total = disk_data.metadata.get("total_gb", 0.0)
            disk_color = _get_metric_color(disk_percent)
            system_metrics.append(
                create_progress_indicator(
                    label="Disk Usage",
                    value=disk_percent,
                    details=f"{disk_free:.1f} GB free / {disk_total:.1f} GB",
                    color=disk_color,
                )
            )

        self.content = ft.Column(
            [
                # API Metrics section
                ft.Row(
                    metric_cards,
                    spacing=Theme.Spacing.MD,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            SecondaryText("HTTP Methods:"),
                            BodyText(method_text or "None"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    padding=ft.padding.symmetric(
                        horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
                    ),
                ),
                # System Metrics section
                ft.Container(height=Theme.Spacing.MD),  # Spacer
                H3Text("System Metrics"),
                ft.Container(
                    content=ft.Column(
                        system_metrics
                        if system_metrics
                        else [SecondaryText("No metrics available")],
                        spacing=Theme.Spacing.MD,
                    ),
                    padding=ft.padding.symmetric(vertical=Theme.Spacing.SM),
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)


class RoutesTab(ft.Container):
    """Routes tab displaying all backend routes grouped by OpenAPI tags."""

    def __init__(self, backend_component: ComponentStatus) -> None:
        """
        Initialize routes tab.

        Args:
            backend_component: ComponentStatus containing backend data
        """
        super().__init__()
        metadata = backend_component.metadata or {}
        routes = metadata.get("routes", [])

        # Group routes by their first tag (or "Untagged" if no tags)
        groups: dict[str, list[dict[str, object]]] = {}
        for route in routes:
            tags = route.get("tags", [])
            # Use first tag, or "Untagged" if no tags
            group_name = tags[0] if tags else "Untagged"
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(route)

        # Sort groups alphabetically, but put "Untagged" last
        sorted_group_names = sorted([name for name in groups if name != "Untagged"])
        if "Untagged" in groups:
            sorted_group_names.append("Untagged")

        # Smart collapse: expand all if <=5 groups, collapse all if >5
        start_expanded = len(groups) <= 5

        # Create group sections
        group_sections = []
        for group_name in sorted_group_names:
            group_sections.append(
                RouteGroupSection(
                    group_name=group_name,
                    routes=groups[group_name],
                    start_expanded=start_expanded,
                )
            )

        # Use ListView for virtualization - only renders visible items
        self.content = ft.ListView(
            controls=group_sections
            if group_sections
            else [SecondaryText("No routes found")],
            spacing=0,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)


class LifecycleTab(ft.Container):
    """Lifecycle tab displaying startup → middleware → shutdown flow diagram."""

    def __init__(self, backend_component: ComponentStatus) -> None:
        """
        Initialize lifecycle tab with flow diagram layout.

        Args:
            backend_component: ComponentStatus containing backend data
        """
        super().__init__()
        metadata = backend_component.metadata or {}
        lifecycle = metadata.get("lifecycle", {})

        # Create shared inspector panel
        self.inspector = LifecycleInspector()

        # Get middleware stack and hooks
        middleware_stack = metadata.get("middleware_stack", [])
        startup_hooks = lifecycle.get("startup_hooks", [])
        shutdown_hooks = lifecycle.get("shutdown_hooks", [])

        # Build startup hook cards
        startup_cards = []
        for hook in startup_hooks:
            name = str(hook.get("name", "unknown"))
            module = str(hook.get("module", ""))
            description = str(hook.get("description", ""))

            # Build details with description if available
            details: dict[str, object] = {}
            if description:
                details["Description"] = description
            if module:
                details["Module"] = module

            startup_cards.append(
                LifecycleCard(
                    name=name,
                    subtitle=module,
                    section="Startup Hooks",
                    details=details if details else None,
                    inspector=self.inspector,
                )
            )

        # Build middleware cards
        middleware_cards = []
        for mw in middleware_stack:
            type_name = str(mw.get("type", "Unknown"))
            module = str(mw.get("module", ""))
            is_security = bool(mw.get("is_security", False))
            config = mw.get("config", {})
            mw_description = str(mw.get("description", "") or "")

            # Build details dict - description first, then config
            mw_details: dict[str, object] = {}
            if mw_description:
                mw_details["Description"] = mw_description
            if module:
                mw_details["Module"] = module
            if isinstance(config, dict):
                for key, value in config.items():
                    mw_details[key] = value

            middleware_cards.append(
                LifecycleCard(
                    name=type_name,
                    subtitle=module,
                    section="Middleware Stack",
                    details=mw_details,
                    badge="Security" if is_security else None,
                    badge_color=ft.Colors.AMBER if is_security else None,
                    inspector=self.inspector,
                )
            )

        # Build shutdown hook cards
        shutdown_cards = []
        for hook in shutdown_hooks:
            name = str(hook.get("name", "unknown"))
            module = str(hook.get("module", ""))
            description = str(hook.get("description", ""))

            # Build details with description if available
            hook_details: dict[str, object] = {}
            if description:
                hook_details["Description"] = description
            if module:
                hook_details["Module"] = module

            shutdown_cards.append(
                LifecycleCard(
                    name=name,
                    subtitle=module,
                    section="Shutdown Hooks",
                    details=hook_details if hook_details else None,
                    inspector=self.inspector,
                )
            )

        # Build flow sections with step numbers
        startup_section = FlowSection(
            title="Startup Hooks",
            cards=startup_cards,
            icon=ft.Icons.PLAY_ARROW,
            step_number=1,
        )

        middleware_section = FlowSection(
            title="Middleware Stack",
            cards=middleware_cards,
            icon=ft.Icons.BOLT,
            step_number=2,
        )

        shutdown_section = FlowSection(
            title="Shutdown Hooks",
            cards=shutdown_cards,
            icon=ft.Icons.STOP,
            step_number=3,
        )

        # Assemble flow diagram with connectors
        flow_diagram = ft.Column(
            [
                startup_section,
                FlowConnector(),
                middleware_section,
                FlowConnector(),
                shutdown_section,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        )

        # Master-detail layout: flowchart on left, inspector on right
        self.content = ft.Row(
            [
                ft.Container(content=flow_diagram, expand=True),
                self.inspector,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True


class PerformanceTab(ft.Container):
    """Per-endpoint response-time table backed by the in-memory metrics service.

    Fetches ``/api/v1/metrics/summary`` and ``/api/v1/metrics/endpoints``
    in ``did_mount`` (i.e. each time the modal is opened) rather than
    reading the snapshot embedded in the health-poll payload. The
    snapshot can be up to one dashboard-refresh interval old; live
    fetch shows counts as of the open. Backend is excluded from the
    modal cache (see ``card_utils._open_modal``) so ``did_mount``
    fires on every open.
    """

    def __init__(self, backend_component: ComponentStatus) -> None:
        super().__init__()
        # Seed values from the health snapshot. They render instantly
        # under the loading spinner so the tab isn't visually empty
        # while the fresh fetch is in flight, and they're also the
        # fallback if the metrics endpoint is unreachable.
        metadata = backend_component.metadata or {}
        self._initial_summary: dict = metadata.get("performance") or {}
        self._initial_endpoints: dict = metadata.get("performance_endpoints") or {}

        self._body = ft.Container(
            content=ft.Row(
                [ft.ProgressRing(width=20, height=20)],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            alignment=ft.alignment.center,
            expand=True,
            padding=ft.padding.all(Theme.Spacing.LG),
        )
        self.content = self._body
        self.padding = ft.padding.all(Theme.Spacing.MD)

    def did_mount(self) -> None:
        # Flet fires did_mount once per add-to-page. Backend's modal is
        # excluded from _modal_cache, so every open creates a fresh
        # PerformanceTab and this fires again.
        self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        summary: dict = dict(self._initial_summary)
        endpoints: dict = dict(self._initial_endpoints)
        try:
            client = get_session_state(self.page).api_client
            fresh_summary = await client.get("/api/v1/metrics/summary")
            fresh_endpoints = await client.get("/api/v1/metrics/endpoints")
            if isinstance(fresh_summary, dict):
                summary = fresh_summary
            if isinstance(fresh_endpoints, dict):
                endpoints = fresh_endpoints
        except Exception:
            # Fall back to whatever the health snapshot carried — the
            # tab still renders, just at one poll-interval of staleness.
            pass

        self._render(summary, endpoints)
        self._body.update()

    def _render(self, summary: dict, endpoints: dict) -> None:
        total_requests = int(summary.get("total_requests", 0) or 0)

        if total_requests == 0 or not endpoints:
            self._body.content = ft.Column(
                [
                    H3Text("No requests recorded yet"),
                    SecondaryText(
                        "Hit a few endpoints, then reopen this tab — "
                        "metrics are kept in memory for the life of "
                        "the process."
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            )
            self._body.alignment = ft.alignment.center
            self._body.padding = ft.padding.all(Theme.Spacing.LG)
            return

        summary_cards = [
            MetricCard(
                value=str(total_requests),
                label="Total Requests",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=str(summary.get("tracked_endpoints", 0)),
                label="Tracked Endpoints",
                color=Theme.Colors.SUCCESS,
            ),
            MetricCard(
                value=f"{float(summary.get('avg_ms', 0.0) or 0.0):.1f}",
                label="Avg ms",
                color=ft.Colors.PURPLE,
            ),
            MetricCard(
                value=f"{float(summary.get('p95_ms', 0.0) or 0.0):.1f}",
                label="p95 ms",
                color=ft.Colors.AMBER,
            ),
        ]

        slowest = summary.get("slowest_endpoint")
        if isinstance(slowest, dict) and slowest.get("endpoint"):
            slowest_row = ft.Container(
                content=ft.Row(
                    [
                        SecondaryText("Slowest:"),
                        BodyText(str(slowest["endpoint"])),
                        SecondaryText(
                            f"{float(slowest.get('avg_ms', 0.0) or 0.0):.1f}ms avg"
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                ),
                padding=ft.padding.symmetric(
                    horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
                ),
            )
        else:
            slowest_row = ft.Container()

        columns = [
            DataTableColumn("Method", width=80),
            DataTableColumn("Path", style="primary"),
            DataTableColumn("Count", width=80, alignment="right"),
            DataTableColumn("Avg ms", width=90, alignment="right"),
            DataTableColumn("p95 ms", width=90, alignment="right"),
        ]
        sorted_items = sorted(
            endpoints.items(),
            key=lambda kv: int((kv[1] or {}).get("count", 0) or 0),
            reverse=True,
        )
        table_rows = [
            self._build_endpoint_row(key, stats) for key, stats in sorted_items
        ]
        table = ExpandableDataTable(
            columns=columns,
            rows=table_rows,
            row_padding=8,
            empty_message="No endpoints recorded",
        )

        self._body.content = ft.Column(
            [
                ft.Row(summary_cards, spacing=Theme.Spacing.MD),
                slowest_row,
                ft.Container(height=Theme.Spacing.SM),
                H3Text("Endpoints"),
                ft.Container(content=table, expand=True),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self._body.alignment = None
        self._body.padding = None

    @staticmethod
    def _build_endpoint_row(key: str, stats: dict) -> ExpandableRow:
        """Collapsed: method / path / count / avg / p95. Expanded: full stats."""
        stats = stats or {}
        method, _, path = key.partition(" ")
        count = int(stats.get("count", 0) or 0)
        avg_ms = float(stats.get("avg_ms", 0.0) or 0.0)
        p95_ms = float(stats.get("p95_ms", 0.0) or 0.0)

        cells = [
            MethodBadge(method),
            path or key,
            str(count),
            f"{avg_ms:.1f}",
            f"{p95_ms:.1f}",
        ]
        return ExpandableRow(
            cells=cells,
            expanded_content=PerformanceTab._build_expanded_stats(stats),
        )

    @staticmethod
    def _build_expanded_stats(stats: dict) -> ft.Control:
        """Detail view: min / median / max / p99 / last request timestamp."""
        min_ms = float(stats.get("min_ms", 0.0) or 0.0)
        median_ms = float(stats.get("median_ms", 0.0) or 0.0)
        max_ms = float(stats.get("max_ms", 0.0) or 0.0)
        p99_ms = float(stats.get("p99_ms", 0.0) or 0.0)
        last_request_at = stats.get("last_request_at") or "—"

        def _stat(label: str, value: str) -> ft.Control:
            return ft.Column(
                [SecondaryText(label), BodyText(value)],
                spacing=2,
            )

        return ft.Row(
            [
                _stat("Min ms", f"{min_ms:.1f}"),
                _stat("Median ms", f"{median_ms:.1f}"),
                _stat("Max ms", f"{max_ms:.1f}"),
                _stat("p99 ms", f"{p99_ms:.1f}"),
                _stat("Last request", str(last_request_at)),
            ],
            spacing=Theme.Spacing.LG,
            wrap=True,
        )


class TrafficTab(ft.Container):
    """Per-source request volume - the "who's hammering you" view.

    Fetches ``/api/v1/traffic/sources`` in ``did_mount``. The traffic monitor
    counts requests per client IP (Redis-backed when present, in-memory
    otherwise) and flags a source as dominant at read time, so this works
    without Redis or a scheduler - recording and reading both happen in the
    backend process. When the store is in-memory the tab notes that counts are
    per-process and reset on restart.
    """

    def __init__(self, backend_component: ComponentStatus | None = None) -> None:
        super().__init__()
        self._body = ft.Container(
            content=ft.Row(
                [ft.ProgressRing(width=20, height=20)],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            alignment=ft.alignment.center,
            expand=True,
            padding=ft.padding.all(Theme.Spacing.LG),
        )
        self.content = self._body
        self.padding = ft.padding.all(Theme.Spacing.MD)

    def did_mount(self) -> None:
        self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        data: dict = {}
        try:
            client = get_session_state(self.page).api_client
            fresh = await client.get("/api/v1/traffic/sources")
            if isinstance(fresh, dict):
                data = fresh
        except Exception:
            # Endpoint unreachable - render the empty state, not a broken tab.
            pass

        self._render(data)
        self._body.update()

    def _render(self, data: dict) -> None:
        sources = data.get("sources") or []
        total = int(data.get("total_requests", 0) or 0)
        window_hours = int(data.get("window_hours", 24) or 24)
        backend = data.get("backend", "memory")
        dominant = data.get("dominant")

        if total == 0 and not sources:
            self._body.content = ft.Column(
                [
                    H3Text("No traffic recorded yet"),
                    SecondaryText(
                        "Source IPs show up here once requests come in. "
                        "Reopen this tab after some traffic."
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            )
            self._body.alignment = ft.alignment.center
            self._body.padding = ft.padding.all(Theme.Spacing.LG)
            return

        summary_cards = [
            MetricCard(
                value=f"{total:,}",
                label=f"Requests / {window_hours}h",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=str(len(sources)),
                label="Source IPs",
                color=ft.Colors.GREEN,
            ),
            MetricCard(
                value=backend,
                label="Store",
                color=ft.Colors.PURPLE if backend == "redis" else ft.Colors.GREY,
            ),
        ]

        children: list[ft.Control] = [ft.Row(summary_cards, spacing=Theme.Spacing.MD)]

        if dominant:
            pct = int(round(float(dominant.get("share", 0.0)) * 100))
            children.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.WHITE
                            ),
                            BodyText(
                                f"One source is dominating: {dominant.get('ip')} "
                                f"- {pct}% of traffic "
                                f"({int(dominant.get('requests', 0)):,} requests)"
                            ),
                        ],
                        spacing=Theme.Spacing.SM,
                    ),
                    bgcolor=Theme.Colors.ERROR,
                    border_radius=6,
                    padding=ft.padding.symmetric(
                        horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
                    ),
                )
            )

        if backend != "redis":
            children.append(
                SecondaryText(
                    "In-memory store (per-process, resets on restart). "
                    "Add the Redis component for cross-process counts and "
                    "persistence."
                )
            )

        children.extend(
            [
                ft.Container(height=Theme.Spacing.SM),
                H3Text("Top source IPs"),
                ft.Container(content=self._sources_table(sources), expand=True),
            ]
        )

        self._body.content = ft.Column(
            children, spacing=Theme.Spacing.SM, scroll=ft.ScrollMode.AUTO
        )
        self._body.alignment = None
        self._body.padding = None

    @staticmethod
    def _sources_table(sources: list) -> ft.Control:
        columns = [
            DataTableColumn("Source IP", style="primary"),
            DataTableColumn("Requests", width=120, alignment="right"),
            DataTableColumn("Share", width=100, alignment="right"),
        ]
        rows = []
        for src in sources:
            share_pct = float(src.get("share", 0.0) or 0.0) * 100
            rows.append(
                ExpandableRow(
                    cells=[
                        str(src.get("ip", "-")),
                        f"{int(src.get('requests', 0) or 0):,}",
                        f"{share_pct:.0f}%",
                    ],
                    expanded_content=ft.Row(
                        [
                            ft.Column(
                                [SecondaryText("Share"), BodyText(f"{share_pct:.1f}%")],
                                spacing=2,
                            ),
                            ft.Column(
                                [
                                    SecondaryText("Requests"),
                                    BodyText(f"{int(src.get('requests', 0) or 0):,}"),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=Theme.Spacing.LG,
                    ),
                )
            )
        return ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=8,
            empty_message="No source IPs recorded in this window",
        )


class BackendDetailDialog(BaseDetailPopup):
    """
    Comprehensive backend detail popup with tabbed interface.

    Displays routes, middleware stack, system metrics, and configuration
    details for the FastAPI backend component in separate tabs.
    """

    def __init__(self, backend_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize backend detail popup.

        Args:
            backend_component: ComponentStatus containing backend data
            page: Flet page instance
        """
        # Build tabs with optional logfire instrumentation
        with _span("overseer.modal.backend.build_tabs"):
            with _span("overseer.modal.backend.overview_tab"):
                overview_tab = OverviewTab(backend_component)
            with _span("overseer.modal.backend.routes_tab"):
                routes_tab = RoutesTab(backend_component)
            with _span("overseer.modal.backend.performance_tab"):
                performance_tab = PerformanceTab(backend_component)
            with _span("overseer.modal.backend.lifecycle_tab"):
                lifecycle_tab = LifecycleTab(backend_component)
            with _span("overseer.modal.backend.load_tests_tab"):
                load_tests_tab = LoadTestsTab()
            with _span("overseer.modal.backend.traffic_tab"):
                traffic_tab = TrafficTab(backend_component)

            tabs = PulseTabs(
                selected_index=0,
                tabs=[
                    ft.Tab(text="Overview", content=overview_tab),
                    ft.Tab(text="Routes", content=routes_tab),
                    ft.Tab(text="Performance", content=performance_tab),
                    ft.Tab(text="Traffic", content=traffic_tab),
                    ft.Tab(text="Lifecycle", content=lifecycle_tab),
                    ft.Tab(text="Load Tests", content=load_tests_tab),
                ],
                expand=True,
            )

        # Initialize base popup with tabs
        # (non-scrollable - tabs handle their own scrolling)
        super().__init__(
            page=page,
            component_data=backend_component,
            title_text=get_component_title("backend"),
            sections=[tabs],
            subtitle_text=get_component_subtitle("backend", backend_component.metadata),
            scrollable=False,
            width=1100,
            height=800,
            status_detail=get_status_detail(backend_component),
        )
