"""The Routes tab, and the rows it draws.

One route is a row that expands into its parameters and responses; one
router is a group of those rows behind a heading. The tab is the third
thing here only because it is fifty lines of arranging the other two,
and splitting it out would separate a caller from the only two things
it calls.

The auth keywords are a heuristic, not a lookup: a route is marked
protected when a dependency in its signature is named like an auth
dependency. It is here because both the row and the group ask it.
"""

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    ExpandArrow,
    LabelText,
    MethodBadge,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.surface_panel import SurfacePanel
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

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
        self.table_container = SurfacePanel(
            content=ft.Column(
                [table_header] + route_rows,
                spacing=0,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
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
