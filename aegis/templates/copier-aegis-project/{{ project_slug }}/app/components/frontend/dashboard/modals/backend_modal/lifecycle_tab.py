"""The Lifecycle tab: a request's path through the middleware stack.

Cards joined by connectors, with an inspector under whichever stage is
selected. The stack is read off the component status rather than
hardcoded, so a stack that installs an extra middleware shows it.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import ui_backend
from app.services.system.models import ComponentStatus

from ..modal_sections import (
    FlowConnector,
    FlowSection,
    LifecycleCard,
    LifecycleInspector,
)


class LifecycleTab(ft.Container):
    """Lifecycle tab displaying startup → middleware → shutdown flow diagram."""

    def __init__(self, backend_component: ComponentStatus) -> None:
        """
        Initialize lifecycle tab with flow diagram layout.

        Args:
            backend_component: ComponentStatus containing backend data
        """
        super().__init__()
        steps = ui_backend.lifecycle(backend_component.metadata or {})

        # Create shared inspector panel
        self.inspector = LifecycleInspector()

        def cards(key: str, section: str) -> list[LifecycleCard]:
            return [
                LifecycleCard(
                    name=entry["name"],
                    subtitle=entry["module"],
                    section=section,
                    details=entry["details"] or None,
                    badge="Security" if entry["security"] else None,
                    badge_color=ft.Colors.AMBER if entry["security"] else None,
                    inspector=self.inspector,
                )
                for entry in steps[key]
            ]

        startup_cards = cards("startup", "Startup Hooks")
        middleware_cards = cards("middleware", "Middleware Stack")
        shutdown_cards = cards("shutdown", "Shutdown Hooks")

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
