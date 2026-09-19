"""The two small panels: catalog totals, and the active model."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_number

from ..modal_sections import MetricCard
from .formatting import (
    _format_context,
)


class CatalogStatsSection(ft.Container):
    """Stats section showing catalog overview metrics."""

    def __init__(self, stats: dict[str, Any]) -> None:
        super().__init__()

        vendor_count = stats.get("vendor_count", 0)
        model_count = stats.get("model_count", 0)
        deployment_count = stats.get("deployment_count", 0)
        price_count = stats.get("price_count", 0)

        self.content = ft.Row(
            [
                MetricCard("Vendors", str(vendor_count), Theme.Colors.PRIMARY),
                MetricCard("Models", format_number(model_count), ft.Colors.PURPLE),
                MetricCard(
                    "Deployments", format_number(deployment_count), ft.Colors.CYAN
                ),
                MetricCard("Prices", format_number(price_count), Theme.Colors.SUCCESS),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


class ActiveModelSection(ft.Container):
    """The model the app is currently using, and where that choice came from.

    Reads from ``/api/v1/llm/current``, which reports the resolved runtime
    configuration rather than what is written in ``.env`` - switching from a
    row below takes effect immediately, so this is what the next request will
    actually use.

    Provenance is the point: a stored selection silently shadows ``.env``
    across every rebuild and restart, which reads as "the app is stuck" to
    anyone editing ``.env``. So the row says which source is in charge, and
    an override carries a reset button that hands control back to ``.env``.
    """

    def __init__(
        self,
        current: dict[str, Any],
        page: ft.Page | None = None,
        on_reset: Any = None,
    ) -> None:
        super().__init__()
        self._page = page
        self._on_reset = on_reset

        model = str(current.get("model") or "-")
        provider = str(current.get("provider") or "-")
        context = current.get("context_window")
        source = current.get("source")
        env_model = current.get("env_model")

        facts: list[ft.Control] = [
            SecondaryText("Active model", size=12),
            ft.Text(model, size=16, weight=ft.FontWeight.W_600),
            SecondaryText(f"via {provider}", size=12),
        ]
        if context:
            facts.append(SecondaryText(_format_context(int(context)), size=12))
        if source == "override":
            note = "set from the dashboard"
            if env_model and env_model != model:
                note += f" · .env has {env_model}"
            facts.append(SecondaryText(note, size=12))
        elif source == "env":
            facts.append(SecondaryText("from .env", size=12))

        controls: list[ft.Control] = [*facts, ft.Container(expand=True)]
        if source == "override" and page is not None:
            controls.append(
                PulseButton(
                    on_click_callable=self._reset,
                    text="Reset to .env",
                    variant="muted",
                    compact=True,
                )
            )

        self.content = ft.Row(
            controls,
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.padding = ft.padding.symmetric(
            horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
        )
        self.bgcolor = ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS

    async def _reset(self) -> None:
        """Drop the override; the app answers from .env again."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self._page).api_client
        result = await api.delete("/api/v1/llm/current")
        if isinstance(result, dict):
            SuccessSnackBar(
                f"Override cleared. Active model: {result.get('model')}."
            ).launch(self._page)
        if self._on_reset is not None:
            await self._on_reset()
