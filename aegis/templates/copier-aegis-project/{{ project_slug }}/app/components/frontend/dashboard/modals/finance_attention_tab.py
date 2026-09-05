"""The Attention tab: what the rules noticed.

One list of findings, each a deterministic rule's claim about a specific
account, transaction or stream, with the severity as the house dot and a
Dismiss. Nothing here is written by a model: the analyst note and its Run
button used to sit above this list and were removed - the chat is the
place to ask for narration now - and the recurring rollup that sat below
it duplicated the Bills & Income tab wholesale.
"""

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.controls.status_dot import status_dot as severity_dot
from app.components.frontend.dashboard.modals.finance_panel import (
    FinancePanel,
)
from app.components.frontend.theme import AegisTheme as Theme

from .modal_sections import EmptyStatePlaceholder

_INSIGHTS_URL = "/api/v1/finance/insights"


# What the severity actually means, for the dot's tooltip: a bare word
# says how loud, never why.
_SEVERITY_MEANING = {
    "info": "Worth knowing about; nothing is wrong.",
    "warning": "Money is being lost or a limit is close.",
    "critical": "Acts on your cash now; look at this first.",
}

_SEVERITY_COLOR = {
    "info": Theme.Colors.INFO,
    "warning": Theme.Colors.WARNING,
    "critical": Theme.Colors.ERROR,
}


class AttentionTab(FinancePanel):
    """The findings: what the rules noticed, nothing a model wrote."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(page, expand=True)
        self.padding = ft.padding.all(Theme.Spacing.LG)
        # Imported here, not at module scope: ``finance_modal`` imports THIS
        # module, so a top-level import would be a cycle.
        from .finance_modal import _refresh_row

        self._body = ft.Column(
            spacing=Theme.Spacing.LG, scroll=ft.ScrollMode.AUTO, expand=True
        )
        self.content = ft.Column(
            [
                _refresh_row(lambda e: e.page.run_task(self._load), "Refresh"),
                self._body,
            ],
            spacing=0,
            expand=True,
        )

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        ins_data = await api.get(_INSIGHTS_URL, params={"status": "new"})
        insights = ins_data.get("items", []) if isinstance(ins_data, dict) else []

        self._body.controls.clear()
        self._body.controls.append(H3Text("Findings"))
        if insights:
            self._body.controls.extend(self._insight_row(i) for i in insights)
        else:
            self._body.controls.append(
                EmptyStatePlaceholder(message="You're all caught up. No new findings.")
            )

        if self._body.page is not None:
            self._body.update()

    def _insight_row(self, item: dict) -> ft.Control:
        severity = item.get("severity", "info")
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            # Just the dot: the title beside it carries the
                            # words, and the colour already says how loud.
                            ft.Container(
                                content=severity_dot(
                                    _SEVERITY_COLOR.get(severity, Theme.Colors.INFO)
                                ),
                                tooltip=_SEVERITY_MEANING.get(severity, ""),
                            ),
                            PrimaryText(
                                item.get("title") or "",
                                weight=Theme.Typography.WEIGHT_SEMIBOLD,
                            ),
                            ft.Container(expand=True),
                            PulseButton(
                                on_click_callable=self._dismiss(item["id"]),
                                text="Dismiss",
                                variant="muted",
                                compact=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=Theme.Spacing.SM,
                    ),
                    SecondaryText(item.get("body") or ""),
                ],
                spacing=Theme.Spacing.XS,
            ),
            padding=ft.padding.all(Theme.Spacing.MD),
            bgcolor=Theme.Colors.SURFACE_1,
            border=ft.border.all(1, Theme.Colors.BORDER_SUBTLE),
            border_radius=Theme.Components.CARD_RADIUS,
        )

    def _dismiss(self, insight_id: int):
        """No-arg async click handler (PulseButton's contract)."""

        async def _handler() -> None:
            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            await api.post(f"{_INSIGHTS_URL}/{insight_id}/dismiss")
            SuccessSnackBar("Dismissed.").launch(self.page)
            await self._load()

        return _handler
