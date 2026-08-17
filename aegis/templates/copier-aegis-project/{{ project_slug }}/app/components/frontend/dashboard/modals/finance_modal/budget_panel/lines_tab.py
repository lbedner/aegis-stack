"""The Budget sub-tab: commitments, flexible lines, limits, trims.

One mixin of ``BudgetPanel`` - state contract in ``base``.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    NumericText,
    SecondaryText,
    SectionCard,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_lines_grid,
    close_gap_row_copy,
    compact_budget_row,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _parse_dollars,
    _usd,
)
from app.components.frontend.dashboard.modals.modal_sections import status_dot
from app.components.frontend.theme import AegisTheme as Theme


class LinesTabMixin(BudgetPanelState):
    """The Budget sub-tab: commitments, flexible lines, limits, trims."""

    def _commitments_toggle(self, buckets: dict[str, Any]) -> ft.Control:
        """One line standing in for both commitment sections.

        States the total rather than listing it: "what am I already
        committed to" is a number, and the rows behind it are Bills &
        Income's job.
        """
        rows = 0
        total = 0
        for key in ("fixed", "non_monthly"):
            bucket = buckets.get(key) or {}
            lines = bucket.get("lines", []) or []
            rows += len(lines)
            total += sum(line.get("amount", 0) or 0 for line in lines)

        def _toggle(_e: ft.ControlEvent) -> None:
            self._show_commitments = not self._show_commitments
            self._render()

        return ft.Container(
            content=ft.Row(
                [
                    SecondaryText(
                        f"{_usd(total)}/month already committed across "
                        f"{rows:,} bill{'s' if rows != 1 else ''}"
                    ),
                    ft.Container(expand=True),
                    SecondaryText(
                        "Hide bills" if self._show_commitments else "Show bills",
                        color=Theme.Colors.ACCENT,
                    ),
                    ft.Icon(
                        ft.Icons.EXPAND_LESS
                        if self._show_commitments
                        else ft.Icons.EXPAND_MORE,
                        size=18,
                        color=Theme.Colors.ACCENT,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            ),
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.MD, vertical=10),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            ink=True,
            on_click=_toggle,
        )

    # -- Fixed / Non-monthly: context only, no limit to set or remove ----

    def _commitment_section(
        self,
        title: str,
        subtitle: str,
        bucket: dict[str, Any] | None,
        caption_prefix: str,
    ) -> ft.Control:
        lines = (bucket or {}).get("lines", [])
        total = (bucket or {}).get("total_allocated", 0)
        header = ft.Row(
            [H3Text(title), SecondaryText(subtitle)],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if not lines:
            body: ft.Control = SecondaryText(f"No {title.lower()} bills detected yet.")
        else:
            body = budget_lines_grid([self._commitment_row(line) for line in lines])
        return SectionCard(
            title=header,
            body=body,
            actions=[SecondaryText(f"{caption_prefix} - {_usd(total)}/mo")],
            body_padding=Theme.Spacing.MD,
        )

    def _commitment_row(self, line: dict[str, Any]) -> ft.Control:
        label = line.get("category_name") or "Uncategorized"
        variance = line.get("variance_amount")
        if variance is None:
            status = status_dot(
                "On schedule",
                Theme.Colors.SUCCESS,
                "This period's charge is close to what it typically costs.",
            )
        else:
            sign = "+" if variance > 0 else "-"
            status = status_dot(
                f"{sign}{_usd(abs(variance))} vs last mo.",
                Theme.Colors.WARNING,
                "This period's charge moved from last month's.",
            )
        return ft.Row(
            [
                TableNameText(label),
                ft.Container(expand=True),
                NumericText(f"{_usd(line.get('allocated_amount', 0))} /mo", size=14),
                status,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # -- Flexible: the actual budget, chosen limits only ------------------

    def _flexible_section(self, bucket: dict[str, Any] | None) -> ft.Control:
        lines = (bucket or {}).get("lines", [])
        header = ft.Row(
            [
                H3Text("Flexible"),
                SecondaryText("Limits you've set - by category or by payee"),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if not lines:
            body: ft.Control = SecondaryText(
                "No budget lines set yet - use the goal box above, or "
                "“+ Add a limit” below, for a specific category or payee."
            )
        else:
            body = budget_lines_grid([self._line_row(line) for line in lines])
        return SectionCard(
            title=header,
            body=ft.Column(
                [body, self._add_line_button()],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            body_padding=Theme.Spacing.MD,
        )

    def _line_row(self, line: dict[str, Any]) -> ft.Control:
        label = line.get("category_name") or line.get("payee_label") or "Overall"
        progress = compact_budget_row(
            label,
            line.get("allocated_amount", 0),
            line.get("spent_amount", 0),
            line.get("status", "good"),
        )
        # The bar itself opens the editor: a limit you cannot change
        # without deleting and re-adding it is not a dial, and tuning
        # one and watching the month react is the whole loop this tab
        # is for.
        return ft.Row(
            [
                ft.Container(
                    content=progress,
                    expand=True,
                    on_click=lambda _e, row=line: self._open_edit_limit(row),
                    tooltip="Change this limit",
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=14,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Remove this limit",
                    on_click=lambda e, line_id=line["id"]: e.page.run_task(
                        self._delete_line, line_id
                    ),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _open_edit_limit(self, line: dict[str, Any]) -> None:
        """Change one limit's amount. Everything else about the line -
        its category or payee - is what identifies it, so the dialog
        edits the single number that is a decision."""
        label = line.get("category_name") or line.get("payee_label") or "Overall"
        amount = FormTextField(
            label="Monthly limit ($)",
            value=f"{line.get('allocated_amount', 0) / 100:.2f}",
            width=200,
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            cents = _parse_dollars(amount.value or "")
            if cents <= 0:
                ErrorSnackBar("Give the limit an amount.").launch(self.page)
                return
            await _close()
            await self._save_limit(line, cents)

        spent = line.get("spent_amount", 0)
        dialog = StyledAlertDialog(
            title=f"Limit for {label}",
            body=ft.Column(
                [
                    amount,
                    SecondaryText(
                        f"{_usd(spent)} already spent this month",
                        size=Theme.Typography.BODY_SMALL,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=380,
        )
        self.page.open(dialog)

    async def _save_limit(self, line: dict[str, Any], cents: int) -> None:
        """Upsert the line at a new amount, then reload so the header's
        verdict re-answers on the spot."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/lines",
            json={
                "category_id": line.get("category_id"),
                "payee_key": line.get("payee_key"),
                "payee_label": line.get("payee_label"),
                "allocated_amount": cents,
            },
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not save that limit.").launch(self.page)
            return
        await self._load()

    async def _delete_line(self, line_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/budget/lines/{line_id}")
        await self._load()

    # -- manual add ------------------------------------------------------

    def _add_line_button(self) -> ft.Control:
        return ft.Row(
            [
                PulseButton(
                    on_click_callable=self._open_add_line,
                    text="+ Add a limit",
                    variant="muted",
                    compact=True,
                )
            ]
        )

    async def _open_add_line(self) -> None:
        form: dict[str, str] = {"amount": ""}
        category_dd = FormDropdown(
            label="Category",
            options=self._categories,
            value=self._categories[0][0] if self._categories else None,
            width=360,
        )
        amount = FormTextField(
            label="Monthly limit ($)",
            on_change=lambda e: form.__setitem__(
                "amount", getattr(e.control, "value", "") or ""
            ),
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _add() -> None:
            cents = _parse_dollars(form["amount"])
            if cents <= 0:
                ErrorSnackBar("Limit must be more than $0.").launch(self.page)
                return
            if not category_dd.value:
                ErrorSnackBar("Pick a category.").launch(self.page)
                return
            dialog.open = False
            self.page.update()

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.post(
                "/api/v1/finance/budget/lines",
                json={
                    "category_id": int(category_dd.value),
                    "allocated_amount": cents,
                },
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
                return
            SuccessSnackBar("Budget line set.").launch(self.page)
            await self._load()

        dialog = StyledAlertDialog(
            title="Add a category limit",
            body=ft.Column([category_dd, amount], spacing=Theme.Spacing.MD, tight=True),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_add,
                    text="Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    def _trims_section(self, trims: list[dict[str, Any]]) -> ft.Control:
        """The month is short - here is what closes it.

        Deterministic, computed server-side (``plan_budget_trims``): cuts
        distribute proportionally to each line's slack above what it has
        already spent, so no suggestion asks for money that is gone.
        Each row applies on its own; nothing is written until one is.
        """

        def row(trim: dict[str, Any]) -> ft.Row:
            title, delta, sub = close_gap_row_copy(trim)
            is_pause = trim.get("kind") == "pause_goal"
            return ft.Row(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                TableNameText(title),
                                SecondaryText(sub, size=Theme.Typography.BODY_SMALL),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                        expand=True,
                    ),
                    NumericText(
                        delta,
                        size=Theme.Typography.BODY_SMALL,
                        # Recovered money reads calm, taken money warns.
                        color=(
                            Theme.Colors.SUCCESS if is_pause else Theme.Colors.WARNING
                        ),
                    ),
                    PulseButton(
                        on_click_callable=(lambda t=trim: self._apply_trim(t)),
                        text="Apply",
                        variant="muted",
                        compact=True,
                    ),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        # Server order is already goals-first (plan_budget_trims tier 1).
        rows = [row(trim) for trim in trims]
        total = sum(t.get("cut") or t.get("recovered", 0) for t in trims)
        return SectionCard(
            title=ft.Row(
                [
                    H3Text("Close the gap"),
                    SecondaryText(
                        f"Free up {_usd(total)} across {len(trims)} "
                        f"row{'s' if len(trims) != 1 else ''} to break even"
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            body=budget_lines_grid(rows),
            body_padding=Theme.Spacing.MD,
        )

    async def _apply_trim(self, trim: dict[str, Any]) -> None:
        if trim.get("kind") == "pause_goal":
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            await api.patch(
                f"/api/v1/finance/goals/{trim['account_id']}",
                json={"status": "paused"},
            )
            await self._load()
            return
        await self._save_limit(trim, trim["suggested_amount"])
