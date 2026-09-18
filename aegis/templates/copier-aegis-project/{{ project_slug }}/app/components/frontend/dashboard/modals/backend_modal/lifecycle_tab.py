"""The Lifecycle tab: a request's path through the middleware stack.

Cards joined by connectors, with an inspector under whichever stage is
selected. The stack is read off the component status rather than
hardcoded, so a stack that installs an extra middleware shows it.
"""

import flet as ft
from app.components.frontend.theme import AegisTheme as Theme
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
