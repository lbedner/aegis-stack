"""The Lifecycle tab: a queue picker over a flow diagram.

Reads the selected queue's registered stages out of the worker
registry and draws them as cards joined by connectors, with an
inspector under it for whichever stage is selected.
"""

import flet as ft
from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.components.worker.registry import (
    discover_worker_queues,
    get_queue_lifecycle,
    get_queue_metadata,
)

from ..modal_sections import (
    FlowConnector,
    FlowSection,
    LifecycleCard,
    LifecycleInspector,
)


class WorkerLifecycleTab(ft.Container):
    """Lifecycle tab with queue dropdown and flow diagram."""

    def __init__(self) -> None:
        """Initialize worker lifecycle tab."""
        super().__init__()

        self.inspector = LifecycleInspector()
        queue_names = discover_worker_queues()

        # Pre-build flow controls for each queue
        self._queue_flows: dict[str, ft.Column] = {}
        for qn in queue_names:
            self._queue_flows[qn] = self._build_queue_flow(qn)

        # Flow container that swaps content
        first = queue_names[0] if queue_names else None
        self._flow_container = ft.Column(
            self._queue_flows[first].controls if first else [],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # Queue dropdown
        self._dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(qn) for qn in queue_names],
            value=first,
            on_change=self._on_queue_change,
            width=200,
            text_size=13,
            content_padding=ft.padding.symmetric(
                horizontal=12,
                vertical=8,
            ),
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.ACCENT,
        )

        header = ft.Row(
            [
                SecondaryText("Queue:"),
                self._dropdown,
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        left_column = ft.Column(
            [header, self._flow_container],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

        self.content = ft.Row(
            [
                ft.Container(content=left_column, expand=True),
                self.inspector,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    def _on_queue_change(self, e: ft.ControlEvent) -> None:
        """Swap flow diagram when dropdown changes."""
        self.inspector.clear_selection()
        queue_name = e.control.value
        flow = self._queue_flows.get(queue_name)
        if flow:
            self._flow_container.controls = flow.controls
            self._flow_container.update()

    def _build_queue_flow(
        self,
        queue_name: str,
    ) -> ft.Column:
        """Build the flow diagram controls for a single queue."""
        lifecycle = get_queue_lifecycle(queue_name)
        metadata = get_queue_metadata(queue_name)
        functions = metadata.get("functions", [])
        controls: list[ft.Control] = []
        step = 1

        # 1. Startup hook
        startup_cards: list[LifecycleCard] = []
        hook = lifecycle.get("on_startup")
        if hook:
            details: dict[str, object] = {}
            if hook["description"]:
                details["Description"] = hook["description"]
            if hook["module"]:
                details["Module"] = hook["module"]
            startup_cards.append(
                LifecycleCard(
                    name=hook["name"],
                    subtitle=hook["module"],
                    section="Startup",
                    details=details,
                    inspector=self.inspector,
                )
            )
        controls.append(
            FlowSection(
                title="Startup",
                cards=startup_cards,
                icon=ft.Icons.PLAY_ARROW,
                step_number=step,
            )
        )
        step += 1

        # 2. Job Processing
        job_cards: list[LifecycleCard] = []

        job_start_hook = lifecycle.get("on_job_start")
        if job_start_hook:
            js_details: dict[str, object] = {}
            if job_start_hook["description"]:
                js_details["Description"] = job_start_hook["description"]
            if job_start_hook["module"]:
                js_details["Module"] = job_start_hook["module"]
            job_cards.append(
                LifecycleCard(
                    name=job_start_hook["name"],
                    subtitle=job_start_hook["module"],
                    section="Job Processing",
                    details=js_details,
                    badge="Hook",
                    badge_color=ft.Colors.TEAL,
                    inspector=self.inspector,
                )
            )

        from app.components.worker.registry import get_task_docstrings

        task_docs = get_task_docstrings(queue_name)
        for func_name in functions:
            func_details: dict[str, object] = {
                "Queue": queue_name,
            }
            info = task_docs.get(func_name, {})
            if info.get("description"):
                func_details["Description"] = info["description"]
            if info.get("module"):
                func_details["Module"] = info["module"]
            job_cards.append(
                LifecycleCard(
                    name=func_name,
                    subtitle=str(
                        func_details.get("Module", ""),
                    ),
                    section="Job Processing",
                    details=func_details,
                    badge="Task",
                    badge_color=ft.Colors.BLUE,
                    inspector=self.inspector,
                )
            )

        job_end_hook = lifecycle.get("after_job_end")
        if job_end_hook:
            je_details: dict[str, object] = {}
            if job_end_hook["description"]:
                je_details["Description"] = job_end_hook["description"]
            if job_end_hook["module"]:
                je_details["Module"] = job_end_hook["module"]
            job_cards.append(
                LifecycleCard(
                    name=job_end_hook["name"],
                    subtitle=job_end_hook["module"],
                    section="Job Processing",
                    details=je_details,
                    badge="Hook",
                    badge_color=ft.Colors.TEAL,
                    inspector=self.inspector,
                )
            )

        controls.append(FlowConnector())
        controls.append(
            FlowSection(
                title="Job Processing",
                cards=job_cards,
                icon=ft.Icons.BOLT,
                step_number=step,
            )
        )
        step += 1

        # 3. Shutdown hook
        shutdown_cards: list[LifecycleCard] = []
        shutdown_hook = lifecycle.get("on_shutdown")
        if shutdown_hook:
            sd_details: dict[str, object] = {}
            if shutdown_hook["description"]:
                sd_details["Description"] = shutdown_hook["description"]
            if shutdown_hook["module"]:
                sd_details["Module"] = shutdown_hook["module"]
            shutdown_cards.append(
                LifecycleCard(
                    name=shutdown_hook["name"],
                    subtitle=shutdown_hook["module"],
                    section="Shutdown",
                    details=sd_details,
                    inspector=self.inspector,
                )
            )

        controls.append(FlowConnector())
        controls.append(
            FlowSection(
                title="Shutdown",
                cards=shutdown_cards,
                icon=ft.Icons.STOP,
                step_number=step,
            )
        )

        return ft.Column(
            controls,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
